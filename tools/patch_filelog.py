import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''    H("fread", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[3]);
        c.ret = f ? std::fread(guest_to_host(c.x[0]), (size_t)c.x[1], (size_t)c.x[2], f) : 0;
    });''',
'''    H("fread", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[3]);
        c.ret = f ? std::fread(guest_to_host(c.x[0]), (size_t)c.x[1], (size_t)c.x[2], f) : 0;
        static int n = 0;
        if (n++ < 40)
            LOGD("fread(%zu x %zu) -> %llu", (size_t)c.x[1], (size_t)c.x[2],
                 (unsigned long long)c.ret);
    });''')

s = s.replace('''    H("fseek", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::fseek(f, (long)c.x[1], (int)(i32)c.x[2]) : -1);
    });''',
'''    H("fseek", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::fseek(f, (long)c.x[1], (int)(i32)c.x[2]) : -1);
        static int n = 0;
        if (n++ < 40)
            LOGD("fseek(%lld, %d) -> %lld", (long long)c.x[1], (int)(i32)c.x[2],
                 (long long)(i64)c.ret);
    });''')

s = s.replace('''    H("ftell", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::ftell(f) : -1);
    });''',
'''    H("ftell", [](GuestCall& c) {
        FILE* f = file_from_slot(c.x[0]);
        c.ret = (u64)(i64)(f ? std::ftell(f) : -1);
        static int n = 0;
        if (n++ < 40)
            LOGD("ftell -> %lld", (long long)(i64)c.ret);
    });''')

s = s.replace('''        FILE* f = std::fopen(resolved.c_str(), mode.c_str());''',
'''        FILE* f = std::fopen(resolved.c_str(), mode.c_str());
        LOGD("open result: %s", f ? "OK" : "FAILED");''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('file io logging added')
