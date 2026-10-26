import io

# --- ALooper_pollAll: log first calls ---
p = 'port/src/dependencies/libandroid.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''            if (found) {
                if (outFd) { i32 v = hit.gfd; gwrite(outFd, &v, 4); }''',
'''            if (found) {
                static int nf = 0;
                if (nf++ < 20)
                    LOGD("ALooper_pollAll -> ident=%d fd=%d (timeout=%d)", hit.ident, hit.gfd,
                         timeout);
                if (outFd) { i32 v = hit.gfd; gwrite(outFd, &v, 4); }''')
s = s.replace('''        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
#else''',
'''        {
            static int nt = 0;
            if (nt++ < 20)
                LOGD("ALooper_pollAll -> TIMEOUT (timeout=%d)", timeout);
        }
        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
#else''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok pollAll logs')

# --- libc read/write: log pipe traffic ---
p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''        if (kind == 2)
            c.ret = (u64)(i64)_read(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);''',
'''        if (kind == 2) {
            c.ret = (u64)(i64)_read(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
            static int nr = 0;
            if (nr++ < 20)
                LOGD("pipe read(fd=%d) -> %lld", (int)(i32)c.x[0], (long long)(i64)c.ret);
        }''')
s = s.replace('''        if (kind == 2)
            c.ret = (u64)(i64)_write(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);''',
'''        if (kind == 2) {
            c.ret = (u64)(i64)_write(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
            static int nw = 0;
            if (nw++ < 20)
                LOGD("pipe write(fd=%d) -> %lld", (int)(i32)c.x[0], (long long)(i64)c.ret);
        }''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok pipe logs')
