import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''    H("gmtime", [](GuestCall& c) {
        // bionic struct tm: 9 ints, const char* tm_zone, long tm_gmtoff
        static u64 slot = 0;
        if (!slot) slot = alloc_native_data(64, 8);
        std::time_t t = (std::time_t)c.x[0];
        std::tm* tm = std::gmtime(&t);'''
new = '''    H("gmtime", [](GuestCall& c) {
        // bionic struct tm: 9 ints, const char* tm_zone, long tm_gmtoff
        static u64 slot = 0;
        if (!slot) slot = alloc_native_data(64, 8);
        std::time_t t = (std::time_t)c.x[0];
        std::tm* tm = std::gmtime(&t);
        static int gn = 0;
        if (gn++ < 5)
            LOGI("gmtime(t=%lld) -> tm=%p slot=0x%llx", (long long)t, (void*)tm,
                 (unsigned long long)slot);'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('gmtime logging added')
else:
    print('pattern miss')
