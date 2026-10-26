import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''    u64 fp = ts->jit->GetRegister(29);
    u64 lr = ts->jit->GetRegister(30);
    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx", why, (unsigned long long)lr,
         (unsigned long long)fp);''',
'''    u64 fp = ts->jit->GetRegister(29);
    u64 lr = ts->jit->GetRegister(30);
    u64 sp = ts->jit->GetSP();
    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx sp=0x%llx", why,
         (unsigned long long)lr, (unsigned long long)fp, (unsigned long long)sp);''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('sp added')
