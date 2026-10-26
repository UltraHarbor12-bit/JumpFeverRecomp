import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    H("read", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find((int)(i32)c.x[0]);
        if (it == g_fds.end()) { c.ret = (u64)-1; return; }
        if (it->second.kind == 2)
            c.ret = (u64)(i64)_read(it->second.hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (it->second.kind == 1)
            c.ret = (u64)std::fread(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f);
        else
            c.ret = (u64)-1;
    });''', '''    H("read", [](GuestCall& c) {
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
        if (kind == 2)
            c.ret = (u64)(i64)_read(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (kind == 1)
            c.ret = (u64)std::fread(guest_to_host(c.x[1]), 1, (size_t)c.x[2], f);
        else
            c.ret = (u64)-1;
    });''')

s = s.replace('''        std::lock_guard<std::mutex> lk(g_fd_mutex);
        auto it = g_fds.find(fd);
        if (it == g_fds.end()) { c.ret = (u64)-1; return; }
        if (it->second.kind == 2)
            c.ret = (u64)(i64)_write(it->second.hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (it->second.kind == 1)
            c.ret = (u64)std::fwrite(guest_to_host(c.x[1]), 1, (size_t)c.x[2], it->second.f);
        else
            c.ret = (u64)-1;
    });''', '''        int kind = 0, hostfd = -1;
        FILE* f = nullptr;
        {
            std::lock_guard<std::mutex> lk(g_fd_mutex);
            auto it = g_fds.find(fd);
            if (it == g_fds.end()) { c.ret = (u64)-1; return; }
            kind = it->second.kind;
            hostfd = it->second.hostfd;
            f = it->second.f;
        }
        if (kind == 2)
            c.ret = (u64)(i64)_write(hostfd, guest_to_host(c.x[1]), (unsigned)c.x[2]);
        else if (kind == 1)
            c.ret = (u64)std::fwrite(guest_to_host(c.x[1]), 1, (size_t)c.x[2], f);
        else
            c.ret = (u64)-1;
    });''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok libc non-blocking fd usage')

# jit dump: show trampoline names
p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc);''',
'''        std::string where = trampoline_name(pc & ~0x7ull);
        if (where.empty())
            where = trampoline_name((pc + 4) & ~0x7ull);
        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx host_call=%s",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc,
             where.empty() ? "-" : where.c_str());''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok jit dump names')
