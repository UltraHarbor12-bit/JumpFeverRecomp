import io

p = 'port/src/dependencies/libc.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''namespace {

// ---------- FILE* indirection ----------''',
'''namespace {

constexpr u64 kWatched = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedEnd = kWatched + 16;

inline void watch_mem(const char* op, u64 dst, u64 size) {
    if (dst < kWatchedEnd && dst + size > kWatched) {
        static int n = 0;
        if (n++ < 20)
            LOGE("WATCH %s touches singleton: dst=0x%llx size=%llu",
                 op, (unsigned long long)dst, (unsigned long long)size);
    }
}

// ---------- FILE* indirection ----------''')

s = s.replace('''    H("memcpy", [](GuestCall& c) {
        std::memcpy(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);''',
'''    H("memcpy", [](GuestCall& c) {
        watch_mem("memcpy", c.x[0], c.x[2]);
        std::memcpy(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);''')

s = s.replace('''    H("memset", [](GuestCall& c) {
        std::memset(guest_to_host(c.x[0]), (int)(u32)c.x[1], (size_t)c.x[2]);''',
'''    H("memset", [](GuestCall& c) {
        watch_mem("memset", c.x[0], c.x[2]);
        std::memset(guest_to_host(c.x[0]), (int)(u32)c.x[1], (size_t)c.x[2]);''')

s = s.replace('''    H("memmove", [](GuestCall& c) {
        std::memmove(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);''',
'''    H("memmove", [](GuestCall& c) {
        watch_mem("memmove", c.x[0], c.x[2]);
        std::memmove(guest_to_host(c.x[0]), guest_to_host(c.x[1]), (size_t)c.x[2]);''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('mem watch added')
