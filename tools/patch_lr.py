import io

# GuestCall gains lr
p = 'port/include/sjfport/host_calls.h'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'u64 lr;' not in s:
    s = s.replace('''    u64 sp;     // guest stack pointer at the call''',
'''    u64 sp;     // guest stack pointer at the call
    u64 lr;     // guest link register at the call''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('GuestCall.lr added')

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'c.lr = jit_->GetRegister(30)' not in s:
    s = s.replace('''        c.sp = jit_->GetSP();
        for (int i = 0; i < 8; ++i)
            c.v[i] = jit_->GetVector((size_t)i)[0];''',
'''        c.sp = jit_->GetSP();
        c.lr = jit_->GetRegister(30);
        for (int i = 0; i < 8; ++i)
            c.v[i] = jit_->GetVector((size_t)i)[0];''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('CallSVC lr capture added')

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'CALLER_LR' not in s:
    s = s.replace('''    LOGI("SL %s->GetInterface(%s) raw=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1]);''',
'''    LOGI("SL %s->GetInterface(%s) raw=0x%llx CALLER_LR=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1], (unsigned long long)c.lr);''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('caller lr log ok')
