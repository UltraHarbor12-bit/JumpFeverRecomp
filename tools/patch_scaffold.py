import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    // Deliver the native window immediately after onCreate.'''
add = '''    // Scaffold: the engine's own path never initialises the PlayerProfile
    // singleton (verified with a runtime watchpoint: zero writes). Provide a
    // zeroed object graph so its command thread survives long enough to show
    // us the next missing piece.
    {
        u64 y = alloc_native_data(0x400, 16);   // inner data object
        u64 x = alloc_native_data(0x2000, 16);  // PlayerProfile impl
        if (x && y) {
            gwrite(x + 0xb80, &y, 8);
            gwrite(0x1005cbed0ull, &x, 8);
            LOGW("boot: scaffolded PlayerProfile impl=0x%llx data=0x%llx (engine never inits it)",
                 (unsigned long long)x, (unsigned long long)y);
        } else {
            LOGE("boot: scaffold allocation failed");
        }
    }

    // Deliver the native window immediately after onCreate.'''
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('scaffold added')
