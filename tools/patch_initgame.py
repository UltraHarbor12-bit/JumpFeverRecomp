import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");'''
add = '''    // Force-open the initGame gate (the app-context singleton is never
    // initialised in our shim — verified with watchpoints) and run the
    // engine's real game initialisation, which creates every manager via its
    // own constructor (appPreInitialise).
    {
        u64 gate_ptr = 0;
        gread(&gate_ptr, 0x1005ba2a0ull, 8); // GOT[0x5ba2a0] -> &gate object
        if (gate_ptr) {
            u64 gate = 0;
            gread(&gate, gate_ptr, 8);
            LOGI("boot: initGame gate at 0x%llx = 0x%llx", (unsigned long long)gate_ptr,
                 (unsigned long long)gate);
            if (!gate) {
                u64 fake = alloc_native_data(0x400, 16);
                gwrite(gate_ptr, &fake, 8);
                LOGW("boot: gate forced open with zeroed object 0x%llx",
                     (unsigned long long)fake);
            }
            u64 f = elf_find_symbol(elf, "_Z8initGamev");
            if (f) {
                LOGI("boot: calling initGame() @0x%llx", (unsigned long long)f);
                u64 r = guest_call(f, 0, 0, 0, 0, 0, 0, 0, 0, "initGame");
                LOGI("boot: initGame returned %d", (int)r);
            }
        }
    }

    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");'''
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('initGame call added')
