import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    log_callbacks(callbacks);

    // Deliver the native window immediately after onCreate.'''
add = '''    log_callbacks(callbacks);

    // Scaffold: the PlayerProfile/ConnectedProfileManager static instance
    // (holder at 0x5cbed0) is never initialised by the paths we can reach.
    // Provide a zeroed impl so the engine's per-frame managers survive:
    //   triggerStartCount: [impl+0xb80] -> counter block (+0xb8)
    //   getServerTime:     [impl+0xb78] -> server-time block (+0x78)
    {
        u64 y = alloc_native_data(0x400, 16);
        u64 x = alloc_native_data(0x2000, 16);
        if (x && y) {
            gwrite(x + 0xb78, &y, 8);
            gwrite(x + 0xb80, &y, 8);
            gwrite(0x1005cbed0ull, &x, 8);
            LOGW("boot: scaffolded profile impl=0x%llx data=0x%llx",
                 (unsigned long long)x, (unsigned long long)y);
        }
    }

    // Deliver the native window immediately after onCreate.'''
if anchor in s:
    s = s.replace(anchor, add, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('scaffold re-added')
else:
    print('anchor miss')
