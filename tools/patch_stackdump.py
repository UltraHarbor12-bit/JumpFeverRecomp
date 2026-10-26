import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'raw stack dump' not in s:
    s = s.replace('''    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx", why, (unsigned long long)lr,
         (unsigned long long)fp);''',
'''    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx", why, (unsigned long long)lr,
         (unsigned long long)fp);
    // raw stack dump (to spot return addresses when the fp chain is broken)
    for (int w = 0; w < 24; ++w) {
        u64 a = sp + (u64)w * 8;
        if (!guest_to_host(a))
            break;
        u64 v = 0;
        std::memcpy(&v, guest_to_host(a), 8);
        if (v >= 0x100100000ull && v < 0x10060b000ull && (v & 3) == 0)
            LOGE("    [sp+%03d] 0x%llx (.text)", w * 8, (unsigned long long)v);
    }''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('raw stack dump added')
