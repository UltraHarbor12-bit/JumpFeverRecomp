import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

watch = '''namespace {
// Runtime watchpoints (diagnostics): log writes to interesting guest addresses.
constexpr u64 kWatchedAddr = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedSize = 16;

void watch_write(u64 vaddr, u64 size, u64 value, u64 pc) {
    if (vaddr < kWatchedAddr + kWatchedSize && vaddr + size > kWatchedAddr) {
        static int n = 0;
        if (n++ < 40)
            LOGE("WATCH write @0x%llx size=%llu value=0x%llx from pc=0x%llx",
                 (unsigned long long)vaddr, (unsigned long long)size,
                 (unsigned long long)value, (unsigned long long)pc);
    }
}
} // namespace

'''
s = s.replace('namespace {\n\n// Sentinel return address', watch + '// Sentinel return address', 1)

s = s.replace('''    void MemoryWrite64(u64 vaddr, u64 value) override {
        auto* p = (u8*)guest_to_host(vaddr);''',
'''    void MemoryWrite64(u64 vaddr, u64 value) override {
        watch_write(vaddr, 8, value, jit_ ? jit_->GetPC() : 0);
        auto* p = (u8*)guest_to_host(vaddr);''')

s = s.replace('''    void MemoryWrite32(u64 vaddr, u32 value) override {
        auto* p = (u8*)guest_to_host(vaddr);''',
'''    void MemoryWrite32(u64 vaddr, u32 value) override {
        watch_write(vaddr, 4, value, jit_ ? jit_->GetPC() : 0);
        auto* p = (u8*)guest_to_host(vaddr);''')

s = s.replace('''    void MemoryWrite8(u64 vaddr, u8 value) override {
        auto* p = (u8*)guest_to_host(vaddr);''',
'''    void MemoryWrite8(u64 vaddr, u8 value) override {
        watch_write(vaddr, 1, value, jit_ ? jit_->GetPC() : 0);
        auto* p = (u8*)guest_to_host(vaddr);''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('watchpoint installed')
