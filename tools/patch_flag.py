import io

# 1) JIT watchpoint covers the renderer flag
p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''constexpr u64 kWatchedAddr = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedSize = 16;'''
new = '''constexpr u64 kWatchedAddr = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedSize = 16;
constexpr u64 kWatchedAddr2 = 0x1005c4710ull; // renderer state (slInitialise flag)
constexpr u64 kWatchedSize2 = 32;'''
if old in s:
    s = s.replace(old, new, 1)

old2 = '''void watch_write(u64 vaddr, u64 size, u64 value, u64 pc) {
    if (vaddr < kWatchedAddr + kWatchedSize && vaddr + size > kWatchedAddr) {'''
new2 = '''void watch_write(u64 vaddr, u64 size, u64 value, u64 pc) {
    if (vaddr < kWatchedAddr2 + kWatchedSize2 && vaddr + size > kWatchedAddr2) {
        static int m2 = 0;
        if (m2++ < 40)
            LOGE("WATCH2 write @0x%llx size=%llu value=0x%llx from pc=0x%llx",
                 (unsigned long long)vaddr, (unsigned long long)size,
                 (unsigned long long)value, (unsigned long long)pc);
    }
    if (vaddr < kWatchedAddr + kWatchedSize && vaddr + size > kWatchedAddr) {'''
if old2 in s:
    s = s.replace(old2, new2, 1)

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('jit watch2 added')

# 2) boot.cpp: force the renderer flag before initGame's slInitialise step
p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''            u64 f = elf_find_symbol(elf, "_Z8initGamev");
            if (f) {
                LOGI("boot: calling initGame() @0x%llx", (unsigned long long)f);
                u64 r = guest_call(f, 0, 0, 0, 0, 0, 0, 0, 0, "initGame");
                LOGI("boot: initGame returned %d", (int)r);
            }'''
new = '''            u64 f = elf_find_symbol(elf, "_Z8initGamev");
            if (f) {
                LOGI("boot: calling initGame() @0x%llx", (unsigned long long)f);
                u64 r = guest_call(f, 0, 0, 0, 0, 0, 0, 0, 0, "initGame");
                LOGI("boot: initGame returned %d", (int)r);
                // The graphics-ready flag (checked by slInitialise) is set by a
                // path that our shim does not trigger yet. Force it and retry
                // once so slInitialise proceeds with real GL initialisation.
                u64 flag = 0;
                gread(&flag, 0x1005c4714ull, 4);
                if (!flag) {
                    u32 one = 1;
                    gwrite(0x1005c4714ull, &one, 4);
                    LOGW("boot: graphics flag forced to 1 — retrying initGame");
                    r = guest_call(f, 0, 0, 0, 0, 0, 0, 0, 0, "initGame#2");
                    LOGI("boot: initGame#2 returned %d", (int)r);
                }
            }'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('flag force + retry added')
else:
    print('boot pattern miss')
