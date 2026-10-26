import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# create window before onCreate and deliver the surface right after it
s = s.replace('''    LOGI("boot: ANativeActivity_onCreate(activity=0x%llx)", (unsigned long long)activity);''',
'''    // Create the window before onCreate so a surface exists when the engine's
    // worker thread starts processing lifecycle commands (avoids a race).
    platform_create_window(540, 960);

    LOGI("boot: ANativeActivity_onCreate(activity=0x%llx)", (unsigned long long)activity);''')

s = s.replace('''    log_callbacks(callbacks);

    // 7) lifecycle probe: onStart + onResume (no window yet)''',
'''    log_callbacks(callbacks);

    // Deliver the native window immediately after onCreate.
    {
        u64 nw = alloc_native_data(32, 8);
        if (cb && cb->onNativeWindowCreated) {
            LOGI("boot: -> callbacks->onNativeWindowCreated (early)");
            guest_call((u64)cb->onNativeWindowCreated, activity, nw, 0, 0, 0, 0, 0, 0,
                       "onNativeWindowCreated");
            LOGI("boot: onNativeWindowCreated (early) returned");
        }
    }

    // 7) lifecycle probe: onStart + onResume''')

# remove the later window creation / onNativeWindowCreated block
s = s.replace('''    // ---------- Hito 2: window, surface, frame loop ----------
    if (!platform_create_window(540, 960)) {
        LOGW("boot: window creation failed — stopping before onNativeWindowCreated");
        return true;
    }
    u64 native_window = alloc_native_data(32, 8);
    if (cb && cb->onNativeWindowCreated) {
        LOGI("boot: -> callbacks->onNativeWindowCreated");
        guest_call((u64)cb->onNativeWindowCreated, activity, native_window, 0, 0, 0, 0, 0, 0,
                   "onNativeWindowCreated");
        LOGI("boot: onNativeWindowCreated returned");
    }

    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");''',
'''    // ---------- frame loop ----------
    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched boot ordering')
