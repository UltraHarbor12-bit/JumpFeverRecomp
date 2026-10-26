import io

# 1) runtime.h: declaration
p = 'port/include/sjfport/runtime.h'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'jit_backtrace_here' not in s:
    s = s.replace('''// Dump every guest thread's PC/LR/stack (diagnostics).''',
'''// Walk the current thread's guest frame-pointer chain (diagnostics).
void jit_backtrace_here(const char* why);

// Dump every guest thread's PC/LR/stack (diagnostics).''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('runtime.h ok')

# 2) jit.cpp: implementation
p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'jit_backtrace_here' not in s:
    impl = '''void jit_backtrace_here(const char* why) {
    ThreadState* ts = t_state;
    if (!ts || !ts->jit)
        return;
    u64 fp = ts->jit->GetRegister(29);
    u64 lr = ts->jit->GetRegister(30);
    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx", why, (unsigned long long)lr,
         (unsigned long long)fp);
    for (int i = 0; i < 10 && fp; ++i) {
        u64 prev = 0, ret = 0;
        if (!guest_to_host(fp) || !guest_to_host(fp + 8))
            break;
        std::memcpy(&prev, guest_to_host(fp), 8);
        std::memcpy(&ret, guest_to_host(fp + 8), 8);
        LOGE("    #%d lr=0x%llx", i, (unsigned long long)ret);
        if (prev <= fp)
            break;
        fp = prev;
    }
}

u64 guest_new_thread_stack(u64 size) { return guest_alloc_stack(size); }'''
    s = s.replace('u64 guest_new_thread_stack(u64 size) { return guest_alloc_stack(size); }', impl)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('jit.cpp ok')

# 3) libc.cpp: trace empty-path fopen
p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'jit_backtrace_here' not in s:
    s = s.replace('#include "sjfport/host_calls.h"',
                  '#include "sjfport/host_calls.h"\n#include "sjfport/runtime.h"')
    s = s.replace('''        std::string path = gstr(c.x[0]), mode = gstr(c.x[1]);
        std::string resolved = vfs_resolve(path);''',
'''        std::string path = gstr(c.x[0]), mode = gstr(c.x[1]);
        if (path.empty())
            jit_backtrace_here("fopen with EMPTY path");
        std::string resolved = vfs_resolve(path);''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('libc.cpp ok')
