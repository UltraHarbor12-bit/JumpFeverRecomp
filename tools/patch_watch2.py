import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedEnd = kWatched + 16;'''
new = '''constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedEnd = kWatched + 16;
constexpr u64 kWatched2 = 0x1005c4710ull; // renderer state struct
constexpr u64 kWatched2End = kWatched2 + 32;'''
if old in s and 'kWatched2' not in s:
    s = s.replace(old, new, 1)

old2 = '''inline void watch_mem(const char* op, u64 dst, u64 size) {
    if (dst < kWatchedEnd && dst + size > kWatched) {'''
new2 = '''inline void watch_mem(const char* op, u64 dst, u64 size) {
    if (dst < kWatched2End && dst + size > kWatched2) {
        static int m = 0;
        if (m++ < 30)
            LOGE("WATCH2 %s renderer-state: dst=0x%llx size=%llu",
                 op, (unsigned long long)dst, (unsigned long long)size);
    }
    if (dst < kWatchedEnd && dst + size > kWatched) {'''
if old2 in s:
    s = s.replace(old2, new2, 1)

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('watch2 added')
