// Host module: bionic libc (string, stdlib, stdio, unistd, time, errno, misc)
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/runtime.h"

#include "sjfport/host_compat.h"
#include <atomic>
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <map>
#include <mutex>
#include <thread>

namespace sjf {

namespace {

std::string exe_dir() {
    static std::string dir;
    if (dir.empty()) {
        std::string exe = host_exe_path();
        size_t slash = exe.find_last_of("/\\");
        dir = (slash == std::string::npos) ? "." : exe.substr(0, slash);
    }
    return dir;
}

constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedEnd = kWatched + 16;
constexpr u64 kWatched2 = 0x1005c4710ull; // renderer state struct
constexpr u64 kWatched2End = kWatched2 + 32;

inline void watch_mem(const char* op, u64 dst, u64 size) {
    if (!debug_mode())
        return;
    if (dst < kWatched2End && dst + size > kWatched2) {
        static int m = 0;
        if (m++ < 30)
            LOGE("WATCH2 %s renderer-state: dst=0x%llx size=%llu",
                 op, (unsigned long long)dst, (unsigned long long)size);
    }
    if (dst < kWatchedEnd && dst + size > kWatched) {
        static int n = 0;
        if (n++ < 20)
            LOGE("WATCH %s touches singleton: dst=0x%llx size=%llu",
                 op, (unsigned long long)dst, (unsigned long long)size);
    }
}

// ---------- FILE* indirection ----------
// The guest must only see pointers into guest memory, so every host FILE* we
// hand out is stored in an 8-byte guest slot; handlers translate back.
struct FileSlot {
    u64 gaddr = 0;    // guest address of the slot
    FILE* file = nullptr;
};
std::map<u64, FILE*> g_files;      // guest slot -> host FILE*
u64 g_stdin_slot = 0, g_stdout_slot = 0, g_stderr_slot = 0;
std::mutex g_file_mutex;

u64 file_slot_for(FILE* f) {
    u64 slot = alloc_native_data(8, 8);
    if (!slot)
        return 0;
    std::lock_guard<std::mutex> lk(g_file_mutex);
    g_files[slot] = f;
    return slot;
}

FILE* file_from_slot(u64 slot) {
    if (slot == g_stdin_slot) return stdin;
    if (slot == g_stdout_slot) return stdout;
    if (slot == g_stderr_slot) return stderr;
    std::lock_guard<std::mutex> lk(g_file_mutex);
    auto it = g_files.find(slot);
    return it == g_files.end() ? nullptr : it->second;
}

// Resolve Android-ish asset paths to the port's local asset directory.
std::string vfs_resolve(const std::string& guest_path) {
    size_t p = guest_path.find("assets/");
    if (p != std::string::npos) {
        std::string rest = guest_path.substr(p + 7);
        if (!rest.empty()) {
            std::string cand = "game/assets/" + rest;
            if (host_path_exists(cand))
                return cand;
            return exe_dir() + "/../" + cand;
        }
    }
    // game/... paths resolve relative to the executable directory
    if (guest_path.rfind("game/", 0) == 0) {
        std::string cand = exe_dir() + "/../" + guest_path;
        if (host_path_exists(cand))
            return cand;
    }
    // Bare resource names ("fonts-efigsb.sla", "splash.sla", ...): the engine
    // checks the download cache first, then the plain name. Our APK stores
    // them with the "hd-" prefix — try both (CWD and exe_dir/../).
    if (guest_path.find('/') == std::string::npos && guest_path.find('.') != std::string::npos) {
        const std::string cands[] = {
            "game/assets/" + guest_path,
            exe_dir() + "/../game/assets/" + guest_path,
            "game/assets/hd-" + guest_path,
            exe_dir() + "/../game/assets/hd-" + guest_path,
        };
        for (const auto& c : cands) {
            if (host_path_exists(c))
                return c;
        }
        // Unreleased characters (Vector/Rouge/Cream): their player, playerextra
        // and sfx packages never shipped -> borrow a donor's (hito 10).
        std::string donor = extra_char_donor_name(guest_path);
        if (!donor.empty()) {
            static int nlog = 0;
            if (nlog++ < 12)
                LOGI("vfs: %s missing -> using %s", guest_path.c_str(), donor.c_str());
            return vfs_resolve(donor);
        }
    }
    return guest_path;
}

void set_std_streams(u64 sf_blob) {
    // bionic: #define stdin (&__sF[0]) — sizeof(bionic FILE)=152
    g_stdin_slot = sf_blob;
    g_stdout_slot = sf_blob + 152;
    g_stderr_slot = sf_blob + 304;
}

// ---------- fd table for unistd open/read/write ----------
struct FdEntry {
    int kind = 0;   // 0=free 1=FILE 2=host fd (pipe)
    FILE* f = nullptr;
    int hostfd = -1;
};
std::map<int, FdEntry> g_fds;
std::mutex g_fd_mutex;
std::atomic<int> g_next_fd{100};

// ---------- per-thread errno ----------
std::map<std::thread::id, u64> g_errno_slots; // guest int slots
std::mutex g_errno_mutex;
u64 errno_slot() {
    std::lock_guard<std::mutex> lk(g_errno_mutex);
    auto id = std::this_thread::get_id();
    auto it = g_errno_slots.find(id);
    if (it != g_errno_slots.end())
        return it->second;
    u64 slot = alloc_native_data(8, 8);
    g_errno_slots[id] = slot;
    return slot;
}

HostFn H(const std::string& name, HostFn fn) { register_host_fn(name, fn); return fn; }

} // namespace

void register_libc_module() {
    // ================= string.h =================
    H("memcpy", [](GuestCall& c) {
        watch_mem("memcpy", c.x[0], c.x[2]);
        std::memcpy(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);
        c.ret = c.x[0];
    });
    H("memmove", [](GuestCall& c) {
        watch_mem("memmove", c.x[0], c.x[2]);
        std::memmove(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);
        c.ret = c.x[0];
    });
    H("memset", [](GuestCall& c) {
        watch_mem("memset", c.x[0], c.x[2]);
        std::memset(guest_to_host(c.x[0]), (int)(u32)c.x[1], (size_t)c.x[2]);
        c.ret = c.x[0];
    });
    H("memcmp", [](GuestCall& c) {
        c.ret = (u64)(i64)std::memcmp(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);
    });
    H("memchr", [](GuestCall& c) {
        void* r = std::memchr(guest_to_host(c.x[0]), (int)(u32)c.x[1], (size_t)c.x[2]);
        c.ret = r ? host_to_guest(r) : 0;
    });
    H("strlen", [](GuestCall& c) { c.ret = gstr(c.x[0]).size(); });
    H("strcmp", [](GuestCall& c) {
        c.ret = (u64)(i64)std::strcmp(gstr(c.x[0]).c_str(), gstr(c.x[1]).c_str());
    });
    H("strncmp", [](GuestCall& c) {
        c.ret = (u64)(i64)std::strncmp(gstr(c.x[0]).c_str(), gstr(c.x[1]).c_str(), (size_t)c.x[2]);
    });
    H("strcpy", [](GuestCall& c) {
        std::string s = gstr(c.x[1]);
        std::memcpy(guest_to_host(c.x[0]), s.c_str(), s.size() + 1);
        c.ret = c.x[0];
    });
    H("strncpy", [](GuestCall& c) {
        std::string s = gstr(c.x[1]);
        size_t n = (size_t)c.x[2];
        std::memcpy(guest_to_host(c.x[0]), s.c_str(), s.size() < n ? s.size() : n);
        if (s.size() < n)
            std::memset((u8*)guest_to_host(c.x[0]) + s.size(), 0, n - s.size());
        c.ret = c.x[0];
    });
    H("strcat", [](GuestCall& c) {
        std::string a = gstr(c.x[0]), b = gstr(c.x[1]);
        a += b;
        std::memcpy(guest_to_host(c.x[0]), a.c_str(), a.size() + 1);
        c.ret = c.x[0];
    });
    H("strchr", [](GuestCall& c) {
        std::string s = gstr(c.x[0]);
        char target = (char)(u32)c.x[1];
        size_t pos = s.find(target);
        c.ret = pos == std::string::npos ? 0 : c.x[0] + pos;
    });
    H("strstr", [](GuestCall& c) {
        std::string s = gstr(c.x[0]), n = gstr(c.x[1]);
        size_t pos = s.find(n);
        c.ret = (pos == std::string::npos || n.empty()) ? (n.empty() ? c.x[0] : 0) : c.x[0] + pos;
    });
    H("stpcpy", [](GuestCall& c) {
        std::string s = gstr(c.x[1]);
        u8* dst = (u8*)guest_to_host(c.x[0]);
        std::memcpy(dst, s.c_str(), s.size() + 1);
        c.ret = host_to_guest(dst + s.size());
    });
    H("strtok", [](GuestCall& c) {
        // single-threaded simplistic strtok (thread-local state per bionic)
        static u64 next = 0;
        u64 s = c.x[0];
        std::string delim = gstr(c.x[1]);
        if (s)
            next = s;
        while (next) {
            std::string cur = gstr(next);
            size_t start = 0;
            while (start < cur.size() && delim.find(cur[start]) != std::string::npos)
                ++start;
            if (start >= cur.size()) { next = 0; c.ret = 0; return; }
            size_t end = start;
            while (end < cur.size() && delim.find(cur[end]) == std::string::npos)
                ++end;
            u64 tok = next + start;
            u8* p = (u8*)guest_to_host(tok + (end - start));
            *p = 0; // terminate token in place
            next = (end < cur.size()) ? (next + end + 1) : 0;
            c.ret = tok;
            return;
        }
        c.ret = 0;
    });
    H("strerror", [](GuestCall& c) {
        static const char msg[] = "strerror";
        static u64 slot = 0;
        if (!slot) { slot = alloc_native_data(sizeof(msg), 8); gwrite(slot, msg, sizeof(msg)); }
        c.ret = slot;
    });

    // ================= stdlib =================
    H("malloc", [](GuestCall& c) { c.ret = guest_heap_alloc(c.x[0]); });
    H("calloc", [](GuestCall& c) {
        u64 total = c.x[0] * c.x[1];
        u64 p = guest_heap_alloc(total);
        if (p)
            std::memset(guest_to_host(p), 0, (size_t)total);
        c.ret = p;
    });
    H("free", [](GuestCall& c) { guest_heap_free(c.x[0]); });
    H("realloc", [](GuestCall& c) { c.ret = guest_heap_realloc(c.x[0], c.x[1]); });
    H("memalign", [](GuestCall& c) {
        // guest heap is 16-aligned; larger alignments get a manual bump
        u64 align = c.x[0], size = c.x[1];
        if (align <= 16) { c.ret = guest_heap_alloc(size); return; }
        u64 raw = guest_heap_alloc(size + align);
        if (!raw) { c.ret = 0; return; }
        u64 aligned = (raw + align - 1) & ~(align - 1);
        // leak the (aligned-raw) front bytes — acceptable for boot
        c.ret = aligned;
    });
    H("atoi", [](GuestCall& c) { c.ret = (u64)(i64)std::atoi(gstr(c.x[0]).c_str()); });
    H("atof", [](GuestCall& c) {
        double d = std::atof(gstr(c.x[0]).c_str());
        c.set_f64(d);
    });
    H("abort", [](GuestCall& c) {
        LOGE("guest called abort()");
        jit_backtrace_here("abort");
        std::fflush(stderr);
        std::abort();
    });
    H("exit", [](GuestCall& c) {
        LOGI("guest called exit(%d)", (int)(i32)c.x[0]);
        std::fflush(stderr);
        std::exit((int)(i32)c.x[0]);
    });
    // bionic RAND_MAX is 0x7fffffff; MinGW's std::rand() tops out at 32767,
    // which collapsed random spreads (particles, level generation) on Windows.
    // Same generator on every host (splitmix64 -> 31 bits).
    static std::atomic<u64> s_rand_state{0x853c49e6748fea9bull};
    struct R {
        static u32 next() {
            u64 z = (s_rand_state += 0x9e3779b97f4a7c15ull);
            z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
            z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
            return (u32)((z ^ (z >> 31)) >> 33); // 0 .. 0x7fffffff
        }
    };
    H("rand", [](GuestCall& c) { c.ret = (u64)R::next(); });
    H("srand", [](GuestCall& c) { s_rand_state = 0x853c49e6748fea9bull ^ (u64)(u32)c.x[0]; });
    H("raise", [](GuestCall& c) {
        LOGE("guest raise(%d) — aborting", (int)(i32)c.x[0]);
        std::abort();
    });

    // ================= stdio =================
    H("fopen", [](GuestCall& c) {
        std::string path = gstr(c.x[0]), mode = gstr(c.x[1]);
        if (path.empty())
            jit_backtrace_here("fopen with EMPTY path");
        std::string resolved = vfs_resolve(path);
        if (resolved != path)
            LOGD("fopen(\"%s\") -> \"%s\"", path.c_str(), resolved.c_str());
        else
            LOGD("fopen(\"%s\", \"%s\")", path.c_str(), mode.c_str());
        FILE* f = std::fopen(resolved.c_str(), mode.c_str());
        LOGD("open result: %s", f ? "OK" : "FAILED");
        c.ret = f ? file_slot_for(f) : 0;
        if (!f) { u64 e = errno_slot(); gwrite(e, "\x01", 4); } // errno = 1
    });
    H("fclose", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        if (f) std::fclose(f);
        { std::lock_guard<std::mutex> lk(g_file_mutex); g_files.erase(c.x[0]); }
        c.ret = 0;
    });
    H("fread", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[3]);
        c.ret = f ? std::fread(guest_to_host(c.x[0]), (size_t)c.x[1], (size_t)c.x[2], f) : 0;
        static int n = 0;
        if (n++ < 40)
            LOGD("fread(%zu x %zu) -> %llu", (size_t)c.x[1], (size_t)c.x[2],
                 (unsigned long long)c.ret);
    });
    H("fwrite", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[3]);
        c.ret = f ? std::fwrite(guest_to_host(c.x[0]), (size_t)c.x[1], (size_t)c.x[2], f) : 0;
    });
    H("fseek", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::fseek(f, (long)c.x[1], (int)(i32)c.x[2]) : -1);
        static int n = 0;
        if (n++ < 40)
            LOGD("fseek(%lld, %d) -> %lld", (long long)c.x[1], (int)(i32)c.x[2],
                 (long long)(i64)c.ret);
    });
    H("ftell", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::ftell(f) : -1);
        static int n = 0;
        if (n++ < 40)
            LOGD("ftell -> %lld", (long long)(i64)c.ret);
    });
    H("feof", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(f ? std::feof(f) : 0);
    });
    H("ferror", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(f ? std::ferror(f) : 1);
    });
    H("fflush", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::fflush(f) : 0);
    });
    H("fputc", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[1]);
        c.ret = (u64)(f ? std::fputc((int)(u32)c.x[0], f) : (u64)-1);
    });
    H("fputs", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[1]);
        c.ret = (u64)(i64)(f ? (std::fputs(gstr(c.x[0]).c_str(), f) >= 0) : (u64)-1);
    });
    H("putchar", [](GuestCall& c) {
        c.ret = (u64)std::fputc((int)(u32)c.x[0], stdout);
    });
    // printf family — guest varargs
    H("printf", [](GuestCall& c) {
        c.vargp = 1; c.vargf = 0;
        std::string s = guest_format(c, c.x[0]);
        std::fputs(s.c_str(), stdout);
        c.ret = s.size();
    });
    H("vprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[1];
        std::string s = guest_format(c, c.x[0]);
        std::fputs(s.c_str(), stdout);
        c.ret = s.size();
    });
    H("fprintf", [](GuestCall& c) {
        c.vargp = 2; c.vargf = 0;
        std::string s = guest_format(c, c.x[1]);
        FILE* f = file_from_slot(c.x[0]);
        std::fputs(s.c_str(), f ? f : stdout);
        c.ret = s.size();
    });
    H("vfprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[2];
        std::string s = guest_format(c, c.x[1]);
        FILE* f = file_from_slot(c.x[0]);
        std::fputs(s.c_str(), f ? f : stdout);
        c.ret = s.size();
    });
    H("sprintf", [](GuestCall& c) {
        c.vargp = 2; c.vargf = 0;
        std::string s = guest_format(c, c.x[1]);
        std::memcpy(guest_to_host(c.x[0]), s.c_str(), s.size() + 1);
        c.ret = s.size();
    });
    H("snprintf", [](GuestCall& c) {
        c.vargp = 3; c.vargf = 0;
        std::string s = guest_format(c, c.x[2]);
        size_t n = (size_t)c.x[1];
        if (n) {
            size_t copy = s.size() < n - 1 ? s.size() : n - 1;
            std::memcpy(guest_to_host(c.x[0]), s.c_str(), copy);
            ((char*)guest_to_host(c.x[0]))[copy] = 0;
        }
        c.ret = s.size();
    });
    H("vsnprintf", [](GuestCall& c) {
        c.use_valist = true;
        c.va_ptr = c.x[3];
        std::string s = guest_format(c, c.x[2]);
        size_t n = (size_t)c.x[1];
        if (n) {
            size_t copy = s.size() < n - 1 ? s.size() : n - 1;
            std::memcpy(guest_to_host(c.x[0]), s.c_str(), copy);
            ((char*)guest_to_host(c.x[0]))[copy] = 0;
        }
        c.ret = s.size();
    });
    H("remove", [](GuestCall& c) {
        c.ret = (u64)(i64)std::remove(gstr(c.x[0]).c_str());
    });
    H("rename", [](GuestCall& c) {
        c.ret = (u64)(i64)std::rename(gstr(c.x[0]).c_str(), gstr(c.x[1]).c_str());
    });
    H("sscanf", [](GuestCall& c) {
        std::string s = gstr(c.x[0]);
        std::string fmt = gstr(c.x[1]);
        std::string hfmt;
        hfmt.reserve(fmt.size() + 4);
        for (size_t i = 0; i < fmt.size(); ++i) {
            hfmt.push_back(fmt[i]);
            if (fmt[i] == '%' && i + 2 < fmt.size() && fmt[i + 1] == 'l') {
                char nxt = fmt[i + 2];
                if (nxt == 'd' || nxt == 'i' || nxt == 'u' || nxt == 'x' || nxt == 'X')
                    hfmt.push_back('l');
            }
        }
        c.vargp = 2;
        c.vargf = 0;
        void* a[8]{};
        for (int i = 0; i < 8; ++i)
            a[i] = guest_to_host(GuestCall_vararg_gp(c));
        int r = std::sscanf(s.c_str(), hfmt.c_str(), a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
        c.ret = (u64)(i64)r;
    });

    // __sF: bind after registration (loader allocates blob; hook via data path)
    // We handle it in engine boot once we know the blob address.

    // ================= unistd / fcntl =================
    H("open", [](GuestCall& c) {
        std::string path = gstr(c.x[0]);
        int flags = (int)(i32)c.x[1];
        const char* hmode = (flags & 1) ? ((flags & 2) ? "wb+" : "rb") : "rb";
        std::string resolved = vfs_resolve(path);
        FILE* f = std::fopen(resolved.c_str(), hmode);
        LOGD("open(\"%s\", 0x%x) -> %s", path.c_str(), flags, f ? "ok" : "ENOENT");
        if (!f) { c.ret = (u64)-1; return; }
        int fd = g_next_fd++;
        { std::lock_guard<std::mutex> lk(g_fd_mutex); g_fds[fd] = {1, f, -1}; }
        c.ret = (u64)(i32)fd;
    });
    H("close", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it != g_fds.end()) {
            if (it->second.kind == 1 && it->second.f)
                std::fclose(it->second.f);
            else if (it->second.kind == 2)
                _close(it->second.hostfd);
            g_fds.erase(it);
        }
        c.ret = 0;
    });
    H("read", [](GuestCall& c) {
        // NOTE: never hold g_fd_mutex across blocking I/O (pipe deadlock)
        int kind = 0, hostfd = -1;
        FILE* f = nullptr;
        {
            std::lock_guard<std::mutex> lk(g_fd_mutex);
            auto it = g_fds.find((int)(i32)c.x[0]);
            if (it == g_fds.end()) { c.ret = (u64)-1; return; }
            kind = it->second.kind;
            hostfd = it->second.hostfd;
            f = it->second.f;
        }
        if (kind == 2) {
            c.ret = (u64)(i64)_read(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
            static int nr = 0;
            if (nr++ < 20)
                LOGD("pipe read(fd=%d) -> %lld", (int)(i32)c.x[0], (long long)(i64)c.ret);
        }
        else if (kind == 1)
            c.ret = (u64)std::fread(guest_to_host(c.x[1]), 1, (size_t)c.x[2], f);
        else
            c.ret = (u64)-1;
    });
    H("write", [](GuestCall& c) {
        int fd = (int)(i32)c.x[0];
        if (fd == 1 || fd == 2) {
            std::string s((const char*)guest_to_host(c.x[1]), (size_t)c.x[2]);
            std::fwrite(s.data(), 1, s.size(), fd == 1 ? stdout : stderr);
            c.ret = c.x[2];
            return;
        }
        int kind = 0, hostfd = -1;
        FILE* f = nullptr;
        {
            std::lock_guard<std::mutex> lk(g_fd_mutex);
            auto it = g_fds.find(fd);
            if (it == g_fds.end()) { c.ret = (u64)-1; return; }
            kind = it->second.kind;
            hostfd = it->second.hostfd;
            f = it->second.f;
        }
        if (kind == 2) {
            c.ret = (u64)(i64)_write(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
            static int nw = 0;
            if (nw++ < 20)
                LOGD("pipe write(fd=%d) -> %lld", (int)(i32)c.x[0], (long long)(i64)c.ret);
        }
        else if (kind == 1)
            c.ret = (u64)std::fwrite(guest_to_host(c.x[1]), 1, (size_t)c.x[2], f);
        else
            c.ret = (u64)-1;
    });
    H("lseek", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it == g_fds.end() || it->second.kind != 1) { c.ret = (u64)-1; return; }
        int whence = (int)(i32)c.x[2]; // SEEK_SET 0 / CUR 1 / END 2 — same on bionic
        c.ret = (u64)(i64)std::fseek(it->second.f, (long)c.x[1], whence == 0 ? SEEK_SET : whence == 1 ? SEEK_CUR : SEEK_END) == 0
                    ? (u64)(i64)std::ftell(it->second.f) : (u64)-1;
    });
    H("pipe", [](GuestCall& c) {
#ifdef _WIN32
        int hostfds[2] = {-1, -1};
        if (_pipe(hostfds, 65536, _O_BINARY) != 0) {
            LOGW("pipe(): host _pipe failed");
            c.ret = (u64)-1;
            return;
        }
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        int rfd = g_next_fd++;
        int wfd = g_next_fd++;
        g_fds[rfd] = {2, nullptr, hostfds[0]};
        g_fds[wfd] = {2, nullptr, hostfds[1]};
        if (c.x[0]) {
            i32 out[2] = {rfd, wfd};
            gwrite(c.x[0], out, sizeof(out));
        }
        LOGD("pipe() -> guest fds %d/%d", rfd, wfd);
        c.ret = 0;
#else
        int fds[2];
        if (pipe(fds) != 0) { c.ret = (u64)-1; return; }
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        int rfd = g_next_fd++, wfd = g_next_fd++;
        g_fds[rfd] = {2, nullptr, fds[0]};
        g_fds[wfd] = {2, nullptr, fds[1]};
        if (c.x[0]) { i32 out[2] = {rfd, wfd}; gwrite(c.x[0], out, sizeof(out)); }
        c.ret = 0;
#endif
    });
    H("sleep", [](GuestCall& c) {
        std::this_thread::sleep_for(std::chrono::seconds((long)c.x[0]));
        c.ret = 0;
    });
    H("usleep", [](GuestCall& c) {
        std::this_thread::sleep_for(std::chrono::microseconds((long)c.x[0]));
        c.ret = 0;
    });

    // ================= time =================
    // SJF_TIME_TRACE=1: log time calls (first 5, then every 4096th) - diagnostics.
    static const bool s_tt = std::getenv("SJF_TIME_TRACE") != nullptr;
    struct TT {
        static void f(const char* n, i64 a, i64 b) {
            if (!s_tt) return;
            static std::atomic<u64> cnt{0};
            u64 k = cnt++;
            if (k < 5 || (k & 4095) == 0)
                LOGI("time-trace #%llu %s -> %lld %lld", (unsigned long long)k, n, (long long)a, (long long)b);
        }
    };
#define time_trace TT::f
    // SJF_TIME_OFFSET=<seconds>: debug-only shift of the guest wall clock
    // (lets tests wait out energy recharge timers without editing saves,
    // which the game rejects).
    static const i64 s_time_off = [] {
        const char* e = std::getenv("SJF_TIME_OFFSET");
        return e ? (i64)std::strtoll(e, nullptr, 10) : (i64)0;
    }();
    H("time", [](GuestCall& c) {
        u64 t = (u64)((i64)std::time(nullptr) + s_time_off);
        if (c.x[0]) gwrite(c.x[0], &t, 8);
        c.ret = t;
    });
    H("clock", [](GuestCall& c) {
        // bionic's CLOCKS_PER_SEC is 1000000. Linux hosts match, but MinGW/UCRT
        // use 1000: passing std::clock() through made the game's clock() time
        // run 1000x slower on Windows and froze it on the SEGA splash (hito 10).
        c.ret = (u64)((double)std::clock() * (1000000.0 / (double)CLOCKS_PER_SEC));
        time_trace("clock", (i64)c.ret, 0);
    });
    H("gettimeofday", [](GuestCall& c) {
        auto now = std::chrono::system_clock::now().time_since_epoch();
        i64 sec = std::chrono::duration_cast<std::chrono::seconds>(now).count() + s_time_off;
        i64 usec = std::chrono::duration_cast<std::chrono::microseconds>(now).count() % 1000000;
        if (c.x[0]) { gwrite(c.x[0], &sec, 8); gwrite(c.x[0] + 8, &usec, 8); }
        c.ret = 0;
    });
    H("clock_gettime", [](GuestCall& c) {
        auto now = std::chrono::steady_clock::now().time_since_epoch();
        i64 sec = std::chrono::duration_cast<std::chrono::seconds>(now).count();
        i64 nsec = std::chrono::duration_cast<std::chrono::nanoseconds>(now).count() % 1000000000;
        if (c.x[1]) { gwrite(c.x[1], &sec, 8); gwrite(c.x[1] + 8, &nsec, 8); }
        c.ret = 0;
        time_trace("clock_gettime", sec, nsec);
    });
    H("gmtime", [](GuestCall& c) {
        // bionic struct tm: 9 ints, const char* tm_zone, long tm_gmtoff
        static u64 slot = 0;
        if (!slot) slot = alloc_native_data(64, 8);
        // POSIX: gmtime(const time_t *tp) — the guest passes a POINTER
        std::time_t t = 0;
        if (c.x[0])
            gread(&t, c.x[0], 8);
        else
            t = std::time(nullptr);
        std::tm* tm = std::gmtime(&t);
        static int gn = 0;
        if (gn++ < 5)
            LOGI("gmtime(t=%lld) -> tm=%p slot=0x%llx", (long long)t, (void*)tm,
                 (unsigned long long)slot);
        if (tm) {
            i32 fields[9] = {tm->tm_sec, tm->tm_min, tm->tm_hour, tm->tm_mday,
                             tm->tm_mon, tm->tm_year, tm->tm_wday, tm->tm_yday, 0};
            gwrite(slot, fields, sizeof(fields));
            u64 zone = 0;
            gwrite(slot + 36, &zone, 4); // padding then zone ptr
            i64 gmtoff = 0;
            gwrite(slot + 48, &gmtoff, 8);
            c.ret = slot;
        } else {
            c.ret = 0;
        }
    });
    H("strftime", [](GuestCall& c) {
        // best-effort: support the common %Y-%m-%d %H:%M:%S set
        std::string fmt = gstr(c.x[3]);
        std::time_t t = 0;
        gread(&t, c.x[3 + 1] ? c.x[3] : 0, 8); // not reliable; fallback below
        LOGW("strftime(\"%s\") — emitting raw format", fmt.c_str());
        std::string s = fmt.substr(0, (size_t)c.x[1] - 1);
        std::memcpy(guest_to_host(c.x[0]), s.c_str(), s.size() + 1);
        c.ret = s.size();
    });

    // ================= errno / C runtime glue =================
    H("__errno", [](GuestCall& c) { c.ret = errno_slot(); });
    H("__assert2", [](GuestCall& c) {
        LOGE("guest assert: %s:%d: %s", gstr(c.x[0]).c_str(), (int)(i32)c.x[1], gstr(c.x[2]).c_str());
        std::abort();
    });
    H("__cxa_atexit", [](GuestCall& c) {
        // register dtor — for boot, ignore (process-lifetime leak is fine)
        c.ret = 0;
    });
    H("__cxa_finalize", [](GuestCall& c) { c.ret = 0; });
    H("__stack_chk_fail", [](GuestCall& c) {
        LOGE("stack protector failure in guest code");
        std::abort();
    });

    // ================= mmap =================
    H("mmap", [](GuestCall& c) {
        u64 size = (c.x[1] + 0xFFF) & ~0xFFFull;
        u64 p = alloc_native_data(size, 0x1000);
        if (p) std::memset(guest_to_host(p), 0, (size_t)size);
        c.ret = p ? p : (u64)-1;
    });
    H("munmap", [](GuestCall& c) { c.ret = 0; });

    // ================= network (offline for Hito 1) =================
    for (const char* fn : {"gethostbyname", "connect", "send", "recv"}) {
        H(fn, [fn](GuestCall& c) {
            LOGD("%s() — offline stub", fn);
            c.ret = (u64)-1;
        });
    }
    H("socket", [](GuestCall& c) { LOGD("socket() — offline stub"); c.ret = (u64)-1; });
    H("inet_addr", [](GuestCall& c) {
        std::string s = gstr(c.x[0]);
        unsigned a, b, cc, d;
        if (std::sscanf(s.c_str(), "%u.%u.%u.%u", &a, &b, &cc, &d) == 4)
            c.ret = (u64)(u32)((d << 24) | (cc << 16) | (b << 8) | a);
        else
            c.ret = (u64)(u32)-1;
    });

    // ================= setjmp/longjmp (guest-aware; placeholder) =================
    H("setjmp", [](GuestCall& c) {
        LOGW("setjmp() called — guest-aware implementation pending; returning 0");
        c.ret = 0;
    });
    H("longjmp", [](GuestCall& c) {
        LOGE("longjmp() called — aborting (not yet implemented)");
        std::abort();
    });

    // ctype
    H("isalnum", [](GuestCall& c) { c.ret = (u64)std::isalnum((int)(u32)c.x[0]); });
    H("isalpha", [](GuestCall& c) { c.ret = (u64)std::isalpha((int)(u32)c.x[0]); });
    H("isspace", [](GuestCall& c) { c.ret = (u64)std::isspace((int)(u32)c.x[0]); });
    H("tolower", [](GuestCall& c) { c.ret = (u64)std::tolower((int)(u32)c.x[0]); });
    H("toupper", [](GuestCall& c) { c.ret = (u64)std::toupper((int)(u32)c.x[0]); });
}

// Called by engine boot once __sF blob address is known.
void libc_bind_sF(u64 sf_blob) { set_std_streams(sf_blob); }

// Bridge for ALooper: map a guest fd (pipe) to the host fd.
int host_fd_for_guest(int guest_fd) {
    std::lock_guard<std::mutex> lk(g_fd_mutex);
    auto it = g_fds.find(guest_fd);
    if (it != g_fds.end() && it->second.kind == 2)
        return it->second.hostfd;
    return -1;
}

// Public: map a guest path (assets/..., game/..., bare name) to a host path.
std::string host_resolve_path(const std::string& guest_path) { return vfs_resolve(guest_path); }

} // namespace sjf
