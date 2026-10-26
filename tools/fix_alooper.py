import io

p = 'port/src/dependencies/libandroid.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

start = s.find('    register_host_fn("ALooper_pollAll", [](GuestCall& c) {')
end = s.find('    // ---- Input (Hito 2) ----')
if start == -1 or end == -1:
    print('anchors not found', start, end)
    raise SystemExit(1)

new_block = '''    register_host_fn("ALooper_pollAll", [](GuestCall& c) {
        int timeout = (int)(i32)c.x[0];
        u64 outFd = c.x[1], outEvents = c.x[2], outData = c.x[3];
#ifdef _WIN32
        DWORD t0 = GetTickCount();
        for (;;) {
            LooperFd hit{};
            bool found = false;
            {
                std::lock_guard<std::mutex> lk(g_looper_mutex);
                for (auto& e : g_looper_fds) {
                    int hostfd = host_fd_for_guest(e.gfd);
                    if (hostfd < 0)
                        continue;
                    HANDLE h = (HANDLE)_get_osfhandle(hostfd);
                    if (h == INVALID_HANDLE_VALUE)
                        continue;
                    DWORD avail = 0;
                    if (PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr) && avail > 0) {
                        hit = e;
                        found = true;
                        break;
                    }
                }
            }
            if (found) {
                if (outFd) { i32 v = hit.gfd; gwrite(outFd, &v, 4); }
                if (outEvents) { i32 v = 1; gwrite(outEvents, &v, 4); } // ALOOPER_EVENT_INPUT
                if (outData) { u64 v = hit.data; gwrite(outData, &v, 8); }
                c.ret = (u64)(i64)hit.ident;
                return;
            }
            if (timeout == 0)
                break;
            if (timeout > 0 && (GetTickCount() - t0) >= (DWORD)timeout)
                break;
            Sleep(1);
        }
        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
#else
        (void)outFd; (void)outEvents; (void)outData; (void)timeout;
        c.ret = (u64)(i64)-3;
#endif
    });

'''
s = s[:start] + new_block + s[end:]
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched ALooper pollAll (PeekNamedPipe)')
