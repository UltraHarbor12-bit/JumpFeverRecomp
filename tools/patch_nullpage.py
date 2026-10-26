import io

def patch(p, pairs):
    s = io.open(p, 'r', encoding='utf-8', newline=None).read()
    for old, new in pairs:
        if old not in s:
            print('MISS %s: %r' % (p, old[:60]))
            continue
        s = s.replace(old, new, 1)
        print('ok  %s' % p)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)

# ---- guest_memory.h: null page API ----
patch('port/include/sjfport/guest_memory.h', [
    ('''bool guest_memory_init();
void* guest_to_host(u64 gaddr);          // nullptr if unmapped''',
     '''bool guest_memory_init();
void* guest_to_host(u64 gaddr);          // nullptr if unmapped
bool guest_is_null_page(u64 gaddr);      // guest addr < 64 KiB (shadow page)
u64 null_page_faults();                  // diagnostics counter'''),
])

# ---- guest_memory.cpp: shadow page ----
patch('port/src/runtime/guest_memory.cpp', [
    ('''bool guest_memory_init() {''',
     '''namespace {
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

bool guest_memory_init() {'''),

    ('''#ifdef _WIN32
    g_base = reinterpret_cast<u8*>(VirtualAlloc(reinterpret_cast<void*>(kGuestBase),''',
     '''    init_null_page();
#ifdef _WIN32
    g_base = reinterpret_cast<u8*>(VirtualAlloc(reinterpret_cast<void*>(kGuestBase),'''),

    ('''void* guest_to_host(u64 gaddr) {
    if (gaddr < kGuestBase || gaddr >= kGuestBase + kGuestReserve)
        return nullptr;
    return g_base + (gaddr - kGuestBase);
}''',
     '''void* guest_to_host(u64 gaddr) {
    if (gaddr < kNullPageSize) {
        std::lock_guard<std::mutex> lk(g_null_mutex);
        ++g_null_faults;
        return g_null_page + gaddr;
    }
    if (gaddr < kGuestBase || gaddr >= kGuestBase + kGuestReserve)
        return nullptr;
    return g_base + (gaddr - kGuestBase);
}'''),
])

# ---- jit.cpp: silence faults inside the null page (it is expected now) ----
patch('port/src/runtime/jit.cpp', [
    ('''        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected''',
     '''        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected
        if (vaddr < 0x10000)
            return; // null-page shadow: expected during startup'''),
])
print('done')
