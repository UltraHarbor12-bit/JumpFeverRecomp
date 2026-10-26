import io

def rd(p):
    with io.open(p, 'r', encoding='utf-8', newline=None) as f:
        return f.read()

def wr(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)

# ---- jni_env.cpp: verbose flag ----
p = 'port/src/dex/jni_env.cpp'
s = rd(p)
s = s.replace('std::string g_data_dir;', 'std::string g_data_dir;\nbool g_verbose_jni = true;')
wr(p, s)
print('ok jni verbose flag')

# ---- libc.cpp: host fd bridge ----
p = 'port/src/dependencies/libc.cpp'
s = rd(p)
s = s.replace('''// Called by engine boot once __sF blob address is known.
void libc_bind_sF(u64 sf_blob) { set_std_streams(sf_blob); }''',
'''// Called by engine boot once __sF blob address is known.
void libc_bind_sF(u64 sf_blob) { set_std_streams(sf_blob); }

// Bridge for ALooper: map a guest fd (pipe) to the host fd.
int host_fd_for_guest(int guest_fd) {
    std::lock_guard<std::mutex> lk(g_fd_mutex);
    auto it = g_fds.find(guest_fd);
    if (it != g_fds.end() && it->second.kind == 2)
        return it->second.hostfd;
    return -1;
}''')
wr(p, s)
print('ok libc host_fd_for_guest')

# ---- host_calls.h: declaration ----
p = 'port/include/sjfport/host_calls.h'
s = rd(p)
s = s.replace('''// libc: bind the guest __sF blob (stdin/stdout/stderr) after ELF load.
void libc_bind_sF(u64 sf_blob);''',
'''// libc: bind the guest __sF blob (stdin/stdout/stderr) after ELF load.
void libc_bind_sF(u64 sf_blob);

// libc: guest fd -> host fd (pipes), -1 if not a pipe.
int host_fd_for_guest(int guest_fd);''')
wr(p, s)
print('ok host_calls.h decl')

# ---- libandroid.cpp: real ALooper ----
p = 'port/src/dependencies/libandroid.cpp'
s = rd(p)
s = s.replace('''#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"''',
'''#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#endif

#include <mutex>
#include <vector>''')

s = s.replace('''    // ---- ALooper ----
    register_host_fn("ALooper_prepare", [](GuestCall& c) {
        static u64 looper = 0;
        if (!looper) looper = alloc_native_data(64, 8);
        c.ret = looper;
    });
    register_host_fn("ALooper_addFd", [](GuestCall& c) {
        LOGD("ALooper_addFd(fd=%d, ident=%d, events=%#x)", (int)(i32)c.x[1], (int)(i32)c.x[2], (u32)c.x[3]);
        c.ret = 1; // success
    });
    register_host_fn("ALooper_pollAll", [](GuestCall& c) {
        // no events: report timeout immediately so callers keep their loop going
        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
    });''',
'''    // ---- ALooper (real: blocks on the registered fds, e.g. the self-pipe) ----
    register_host_fn("ALooper_prepare", [](GuestCall& c) {
        static u64 looper = 0;
        if (!looper) looper = alloc_native_data(64, 8);
        c.ret = looper;
    });
    register_host_fn("ALooper_addFd", [](GuestCall& c) {
        // (ALooper*, int fd, int ident, int events, ALooper_callbackFunc* cb, void* data)
        int gfd = (int)(i32)c.x[1];
        int ident = (int)(i32)c.x[2];
        int events = (int)(i32)c.x[3];
        u64 data = c.x[5];
        std::lock_guard<std::mutex> lk(g_looper_mutex);
        g_looper_fds.push_back({gfd, ident, events, data});
        LOGD("ALooper_addFd(fd=%d, ident=%d, events=%#x) registered", gfd, ident, events);
        c.ret = 1;
    });
    register_host_fn("ALooper_pollAll", [](GuestCall& c) {
        int timeout = (int)(i32)c.x[0];
        u64 outFd = c.x[1], outEvents = c.x[2], outData = c.x[3];
#ifdef _WIN32
        std::vector<HANDLE> handles;
        std::vector<LooperFd> snapshot;
        {
            std::lock_guard<std::mutex> lk(g_looper_mutex);
            for (auto& e : g_looper_fds) {
                int hostfd = host_fd_for_guest(e.gfd);
                if (hostfd < 0)
                    continue;
                HANDLE h = (HANDLE)_get_osfhandle(hostfd);
                if (h == INVALID_HANDLE_VALUE)
                    continue;
                handles.push_back(h);
                snapshot.push_back(e);
            }
        }
        if (handles.empty()) {
            if (timeout > 0)
                Sleep((DWORD)timeout);
            c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
            return;
        }
        DWORD wait = WaitForMultipleObjects((DWORD)handles.size(), handles.data(), FALSE,
                                            timeout < 0 ? INFINITE : (DWORD)timeout);
        if (wait == WAIT_TIMEOUT) {
            c.ret = (u64)(i64)-3;
            return;
        }
        if (wait == WAIT_FAILED) {
            LOGW("ALooper_pollAll: WaitForMultipleObjects failed (%lu)", GetLastError());
            c.ret = (u64)(i64)-4; // ALOOPER_POLL_ERROR
            return;
        }
        size_t idx = wait - WAIT_OBJECT_0;
        if (idx >= snapshot.size()) {
            c.ret = (u64)(i64)-3;
            return;
        }
        const LooperFd& e = snapshot[idx];
        if (outFd) { i32 v = e.gfd; gwrite(outFd, &v, 4); }
        if (outEvents) { i32 v = 1; /* ALOOPER_EVENT_INPUT */ gwrite(outEvents, &v, 4); }
        if (outData) { u64 v = e.data; gwrite(outData, &v, 8); }
        c.ret = (u64)(i64)e.ident;
#else
        (void)outFd; (void)outEvents; (void)outData; (void)timeout;
        c.ret = (u64)(i64)-3;
#endif
    });''')

# looper state (anonymous-namespace free, file scope inside sjf)
s = s.replace('''namespace sjf {

void register_libandroid_module() {''',
'''namespace sjf {

struct LooperFd {
    int gfd;
    int ident;
    int events;
    u64 data;
};
static std::vector<LooperFd> g_looper_fds;
static std::mutex g_looper_mutex;

void register_libandroid_module() {''')

wr(p, s)
print('ok libandroid ALooper')
print('done')
