import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    log_callbacks(callbacks);

    // Deliver the native window immediately after onCreate.'''
add = '''    log_callbacks(callbacks);

    // Probe: initialise PlayerProfile (its pimpl stays null otherwise, which
    // crashes the engine's worker thread in triggerStartCount()).
    {
        u64 load = elf_find_symbol(elf, "_ZN13PlayerProfile4loadEv");
        u64 s_inst = 0x1005cbed0ull; // &PlayerProfile::sInstance (.bss)
        u64 before = 0;
        gread(&before, s_inst, 8);
        LOGI("boot: PlayerProfile::load @0x%llx, sInstance=%s (impl=0x%llx)",
             (unsigned long long)load, load ? "found" : "MISSING", (unsigned long long)before);
        if (load) {
            guest_call(load, s_inst, 0, 0, 0, 0, 0, 0, 0, "PlayerProfile::load");
            u64 after = 0;
            gread(&after, s_inst, 8);
            LOGI("boot: after PlayerProfile::load impl=0x%llx", (unsigned long long)after);
        }
    }

    // Deliver the native window immediately after onCreate.'''
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched boot: PlayerProfile::load probe')
