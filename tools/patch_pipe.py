import io

p = 'port/src/dependencies/libc.cpp'
with io.open(p, 'r', encoding='utf-8', newline=None) as f:
    s = f.read()

# --- include io.h for _pipe/_read/_write/_close ---
s = s.replace('''#include <atomic>
#include <cctype>''', '''#include <atomic>
#include <cctype>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif''')

# --- fd table with pipe support ---
s = s.replace('''struct FdEntry { int kind = 0; FILE* f = nullptr; }; // 0=free 1=file''',
'''struct FdEntry {
    int kind = 0;   // 0=free 1=FILE 2=host fd (pipe)
    FILE* f = nullptr;
    int hostfd = -1;
};''')

# --- pipe() real ---
s = s.replace('''    H("pipe", [](GuestCall& c) {
        LOGW("pipe() — unsupported, returning -1");
        c.ret = (u64)-1;
    });''', '''    H("pipe", [](GuestCall& c) {
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
    });''')

# --- read() supports pipes ---
s = s.replace('''    H("read", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        c.ret = it != g_fds.end() ? (u64)std::fread(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f) : (u64)-1;
    });''', '''    H("read", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it == g_fds.end()) { c.ret = (u64)-1; return; }
        if (it->second.kind == 2)
            c.ret = (u64)(i64)_read(it->second.hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (it->second.kind == 1)
            c.ret = (u64)std::fread(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f);
        else
            c.ret = (u64)-1;
    });''')

# --- write() supports pipes ---
s = s.replace('''        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find(fd);
        c.ret = it != g_fds.end() ? (u64)std::fwrite(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f) : (u64)-1;
    });''', '''        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find(fd);
        if (it == g_fds.end()) { c.ret = (u64)-1; return; }
        if (it->second.kind == 2)
            c.ret = (u64)(i64)_write(it->second.hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (it->second.kind == 1)
            c.ret = (u64)std::fwrite(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f);
        else
            c.ret = (u64)-1;
    });''')

# --- close() supports pipes ---
s = s.replace('''    H("close", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it != g_fds.end()) { std::fclose(it->second.f); g_fds.erase(it); }
        c.ret = 0;
    });''', '''    H("close", [](GuestCall& c) {
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
    });''')

# --- open(): fill new FdEntry form ---
s = s.replace('''        int fd = g_next_fd++;
        { std::lock_guard<std::mutex> lk(g_fd_mutex); g_fds[fd] = {1, f}; }''',
'''        int fd = g_next_fd++;
        { std::lock_guard<std::mutex> lk(g_fd_mutex); g_fds[fd] = {1, f, -1}; }''')

# --- lseek(): guard pipe entries ---
s = s.replace('''        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it == g_fds.end()) { c.ret = (u64)-1; return; }
        int whence = (int)(i32)c.x[2]; // SEEK_SET 0 / CUR 1 / END 2 — same on bionic''',
'''        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it == g_fds.end() || it->second.kind != 1) { c.ret = (u64)-1; return; }
        int whence = (int)(i32)c.x[2]; // SEEK_SET 0 / CUR 1 / END 2 — same on bionic''')

with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
    f.write(s)
print('patched libc.cpp for pipes')
