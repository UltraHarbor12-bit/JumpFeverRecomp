// Guest memory region: reserved address space + on-demand commits.
// Heap: simple first-fit free list with coalescing (serves guest malloc/free).
#include "sjfport/guest_memory.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/mman.h>
#endif

#include <cstring>
#include <map>
#include <mutex>
#include <random>

namespace sjf {

u8* g_guest_base = nullptr;

namespace {
u8*& g_base = g_guest_base;                  // host view of kGuestBase
std::map<u64, std::string> g_tramp_names;    // guest addr -> host fn name
std::mutex g_mem_mutex;

// ---- heap ----
struct HeapHeader {
    u64 size;      // usable bytes after header
    u32 magic;     // 0x534A4648 "SJFH"
    u32 free;      // 1 = free block
    u64 prev_size; // size of previous header (for coalescing backwards)
    // padding to 32 bytes so malloc(align 16) stays 16-aligned after header
    u64 pad[1];
};
constexpr u32 kHeapMagic = 0x534A4648;
constexpr u64 kHeapHeaderSize = sizeof(HeapHeader); // 32

u64 g_heap_top = 0;   // highest committed heap address (exclusive)
u64 g_heap_rover = 0; // next-fit cursor into the heap

bool commit_host(u8* p, u64 size) {
#ifdef _WIN32
    return VirtualAlloc(p, (SIZE_T)size, MEM_COMMIT, PAGE_READWRITE) != nullptr;
#else
    // VirtualAlloc(MEM_COMMIT) rounds to pages by itself; mprotect needs it done.
    const uintptr_t pg = 4096;
    uintptr_t a = reinterpret_cast<uintptr_t>(p) & ~(pg - 1);
    uintptr_t e = (reinterpret_cast<uintptr_t>(p) + size + pg - 1) & ~(pg - 1);
    return mprotect(reinterpret_cast<void*>(a), e - a, PROT_READ | PROT_WRITE) == 0;
#endif
}

HeapHeader* hdr(u64 gaddr) { return reinterpret_cast<HeapHeader*>(guest_to_host(gaddr)); }

u64 heap_extend(u64 need) {
    u64 cur = g_heap_top ? g_heap_top : kHeapBase;
    u64 avail = (kHeapBase + kHeapMaxSize) - cur;
    u64 total_need = need + kHeapHeaderSize;
    u64 chunk = total_need > avail ? avail : ((total_need + 0xFFFFF) & ~0xFFFFFull); // 1 MiB granularity
    if (chunk < total_need || !guest_commit(cur, chunk))
        return 0;
    u64 usable = chunk - kHeapHeaderSize;
    HeapHeader* h = hdr(cur);
    h->size = usable;
    h->magic = kHeapMagic;
    h->free = 1;
    h->prev_size = 0;
    g_heap_top = cur + chunk;
    return cur;
}

} // namespace

namespace {
// Null-page shadow: guest addresses 0x0..0xFFFF map here. Reads return 0,
// writes land in the shadow, and every 4-byte word is an ARM64 `ret` so a
// stray call through a null function pointer returns immediately. Every
// access is counted so we know what still needs real initialisation.
u8* g_null_page = nullptr;
u64 g_null_faults = 0;
std::mutex g_null_mutex;
constexpr u64 kNullPageSize = 0x10000;

void init_null_page() {
    g_null_page = reinterpret_cast<u8*>(
#ifdef _WIN32
        VirtualAlloc(nullptr, kNullPageSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
#else
        mmap(nullptr, kNullPageSize, PROT_READ | PROT_WRITE,
             MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
#endif
    if (g_null_page) {
        u32 ret = 0xD65F03C0u; // ret
        for (u64 i = 0; i + 4 <= kNullPageSize; i += 4)
            std::memcpy(g_null_page + i, &ret, 4);
        std::memset(g_null_page, 0, 0x100); // low addresses read as 0
        LOGI("null-page shadow installed at %p (64 KiB, code=ret)", (void*)g_null_page);
    }
}
} // namespace

bool guest_is_null_page(u64 gaddr) { return gaddr < kNullPageSize; }
u64 null_page_faults() {
    std::lock_guard<std::mutex> lk(g_null_mutex);
    return g_null_faults;
}

bool guest_memory_init() {
    init_null_page();
#ifdef _WIN32
    g_base = reinterpret_cast<u8*>(VirtualAlloc(reinterpret_cast<void*>(kGuestBase),
                                               (SIZE_T)kGuestReserve, MEM_RESERVE, PAGE_NOACCESS));
    if (!g_base) {
        // The fixed address is only a convenience (guest == host addresses);
        // every access goes through guest_to_host(), so any base works.
        g_base = reinterpret_cast<u8*>(VirtualAlloc(nullptr, (SIZE_T)kGuestReserve, MEM_RESERVE,
                                                   PAGE_NOACCESS));
        LOGW("guest_memory_init: 0x%llx busy, guest memory reserved at %p instead",
             (unsigned long long)kGuestBase, (void*)g_base);
    }
    if (!g_base) {
        LOGE("guest_memory_init: could not reserve %llu GiB of address space (error %lu)",
             (unsigned long long)(kGuestReserve >> 30), (unsigned long)GetLastError());
        return false;
    }
    // Guard the bottom 64 KiB (null-page protection for the guest).
    return true;
#else
    g_base = reinterpret_cast<u8*>(mmap(reinterpret_cast<void*>(kGuestBase), kGuestReserve,
                                        PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0));
    if (g_base == MAP_FAILED || reinterpret_cast<u64>(g_base) != kGuestBase) {
        LOGE("guest_memory_init: mmap failed");
        return false;
    }
    return true;
#endif
}

void* guest_null_page_access(u64 gaddr) {
    std::lock_guard<std::mutex> lk(g_null_mutex);
    ++g_null_faults;
    return g_null_page + gaddr;
}

u64 host_to_guest(const void* p) {
    u8* q = reinterpret_cast<u8*>(const_cast<void*>(p));
    if (q < g_base || q >= g_base + kGuestReserve)
        return 0;
    return kGuestBase + (q - g_base);
}

bool guest_commit(u64 gaddr, u64 size) {
    u8* p = reinterpret_cast<u8*>(guest_to_host(gaddr));
    if (!p)
        return false;
    return commit_host(p, size);
}

u64 guest_alloc_stack(u64 size) {
    // thread stacks live just below kStackTop; carve downwards
    static u64 next = kStackTop;
    std::lock_guard<std::mutex> lk(g_mem_mutex);
    u64 top = next;
    next -= size;
    if (next < kHeapBase + kHeapMaxSize) {
        LOGE("guest_alloc_stack: stack space exhausted");
        return 0;
    }
    if (!guest_commit(next, size)) {
        LOGE("guest_alloc_stack: commit failed");
        return 0;
    }
    return top;
}

// ---- heap allocator ----

u64 guest_heap_alloc(u64 size) {
    if (!size)
        size = 1;
    u64 need = (size + 15) & ~15ull;
    std::lock_guard<std::mutex> lk(g_mem_mutex);
    auto try_range = [&](u64 start, u64 end) -> u64 {
        for (u64 cur = start; g_heap_top && cur < end;) {
            HeapHeader* h = hdr(cur);
            if (h->magic != kHeapMagic) {
                LOGE("heap corruption at 0x%llx", (unsigned long long)cur);
                break;
            }
            u64 blk = kHeapHeaderSize + h->size;
            if (h->free && h->size >= need) {
                u64 next_rover = cur + blk;
                if (h->size - need >= kHeapHeaderSize + 16) {
                    u64 rem = cur + kHeapHeaderSize + need;
                    HeapHeader* r = hdr(rem);
                    r->size = h->size - need - kHeapHeaderSize;
                    r->magic = kHeapMagic;
                    r->free = 1;
                    r->prev_size = need;
                    h->size = need;
                    u64 nxt = rem + kHeapHeaderSize + r->size;
                    if (nxt < g_heap_top)
                        hdr(nxt)->prev_size = r->size;
                    next_rover = rem;
                }
                h->free = 0;
                g_heap_rover = (next_rover < g_heap_top) ? next_rover : kHeapBase;
                return cur + kHeapHeaderSize;
            }
            cur += blk;
        }
        return 0;
    };

    if (g_heap_top) {
        u64 start = (g_heap_rover >= kHeapBase && g_heap_rover < g_heap_top) ? g_heap_rover : kHeapBase;
        if (u64 p = try_range(start, g_heap_top))
            return p;
        if (start > kHeapBase) {
            if (u64 p = try_range(kHeapBase, start))
                return p;
        }
    }
    u64 blk = heap_extend(need);
    if (!blk)
        return 0;
    g_heap_rover = blk;
    return try_range(blk, g_heap_top);
}

void guest_heap_free(u64 ptr) {
    if (!ptr)
        return;
    u64 cur = ptr - kHeapHeaderSize;
    if (cur < kHeapBase)
        return;
    std::lock_guard<std::mutex> lk(g_mem_mutex);
    HeapHeader* h = hdr(cur);
    if (h->magic != kHeapMagic || h->free) {
        LOGE("guest_heap_free: bad block 0x%llx", (unsigned long long)ptr);
        return;
    }
    h->free = 1;
    // 1) coalesce backward first
    if (h->prev_size) {
        u64 prv = cur - kHeapHeaderSize - h->prev_size;
        if (prv >= kHeapBase) {
            HeapHeader* ph = hdr(prv);
            if (ph->magic == kHeapMagic && ph->free) {
                ph->size += kHeapHeaderSize + h->size;
                h->magic = 0;
                h->free = 0;
                cur = prv;
                h = ph;
            }
        }
    }
    // 2) coalesce forward
    u64 nxt = cur + kHeapHeaderSize + h->size;
    if (nxt < g_heap_top) {
        HeapHeader* nh = hdr(nxt);
        if (nh->magic == kHeapMagic && nh->free) {
            h->size += kHeapHeaderSize + nh->size;
            nh->magic = 0;
            nh->free = 0;
        }
    }
    // 3) update the following block's prev_size
    u64 after = cur + kHeapHeaderSize + h->size;
    if (after < g_heap_top) {
        HeapHeader* ah = hdr(after);
        if (ah->magic == kHeapMagic)
            ah->prev_size = h->size;
    }
    if (g_heap_rover > cur && g_heap_rover < after)
        g_heap_rover = cur;
}

u64 guest_heap_realloc(u64 ptr, u64 size) {
    if (!ptr)
        return guest_heap_alloc(size);
    if (!size) { guest_heap_free(ptr); return 0; }
    u64 old_size = 0;
    {
        std::lock_guard<std::mutex> lk(g_mem_mutex);
        HeapHeader* h = hdr(ptr - kHeapHeaderSize);
        if (h->magic != kHeapMagic || h->free)
            old_size = 0;
        else if (h->size >= size)
            return ptr;
        else
            old_size = h->size;
    }
    if (!old_size)
        return guest_heap_alloc(size);
    u64 np = guest_heap_alloc(size);
    if (!np)
        return 0;
    std::memcpy(guest_to_host(np), guest_to_host(ptr), (size_t)old_size);
    guest_heap_free(ptr);
    return np;
}

u64 guest_heap_usage() {
    u64 used = 0;
    for (u64 cur = kHeapBase; g_heap_top && cur < g_heap_top;) {
        HeapHeader* h = hdr(cur);
        if (h->magic != kHeapMagic)
            break;
        if (!h->free)
            used += h->size;
        cur += kHeapHeaderSize + h->size;
    }
    return used;
}

// ---- trampolines ----

u64 register_trampoline(u16 imm, const std::string& name) {
    static u64 next_slot = 0;
    u64 addr = kTrampolineBase + next_slot * 8;
    if (addr + 8 > kTrampolineBase + kTrampolineSize) {
        LOGE("trampoline table exhausted (%s)", name.c_str());
        return 0;
    }
    if (!guest_commit(addr, 8))
        return 0;
    u32* p = reinterpret_cast<u32*>(guest_to_host(addr));
    p[0] = 0xD4000001u | ((u32)imm << 5); // svc #imm16
    p[1] = 0xD65F03C0u;                    // ret
    g_tramp_names[addr] = name;
    ++next_slot;
    return addr;
}

u64 trampoline_for_host_fn(const std::string& name) {
    for (auto& [addr, nm] : g_tramp_names)
        if (nm == name)
            return addr;
    return 0;
}

const std::string& trampoline_name(u64 gaddr) {
    static const std::string empty;
    auto it = g_tramp_names.find(gaddr);
    return it == g_tramp_names.end() ? empty : it->second;
}

u64 alloc_native_data(u64 size, u64 align) {
    static std::mutex m; // called from every guest thread
    std::lock_guard<std::mutex> lk(m);
    static u64 next = kNativeDataBase;
    next = (next + align - 1) & ~(align - 1);
    u64 addr = next;
    next += size;
    if (next > kNativeDataBase + kNativeDataSize) {
        next = addr; // do not keep growing past the end
        static int n = 0;
        if (n++ < 5)
            LOGE("native data region exhausted (request %llu bytes)", (unsigned long long)size);
        return 0;
    }
    if (!guest_commit(addr, size))
        return 0;
    return addr;
}

namespace {
bool g_verbose = false; // --verbose turns on [D] logs
bool g_debug = false;
std::mutex g_log_mutex;
}

void log_msg(LogLevel level, const char* tag, const std::string& msg) {
    std::lock_guard<std::mutex> lk(g_log_mutex);
    const char* lv = "?";
    switch (level) {
        case LogLevel::Debug: lv = "D"; if (!g_verbose) return; break;
        case LogLevel::Info: lv = "I"; break;
        case LogLevel::Warn: lv = "W"; break;
        case LogLevel::Error: lv = "E"; break;
    }
    std::fprintf(stderr, "[%s][%s] %s\n", tag, lv, msg.c_str());
    std::fflush(stderr);
}

void set_log_verbose(bool v) {
    g_verbose = v;
}

void set_debug_mode(bool on) { g_debug = on; }
bool debug_mode() { return g_debug; }

} // namespace sjf
