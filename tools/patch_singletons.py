import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    // 4) initialisers (.init_array)'''
add = '''    // Create the engine's lazy singletons with their REAL constructors.
    // On Android, initGame()/first use creates them; in our shim the worker
    // thread reaches DownloadManager::update() before that happens and spins
    // forever on a zeroed intrusive list. Use the engine's own ctors.
    {
        struct Mgr { const char* ctor_sym; u64 slot; };
        const Mgr mgrs[] = {
            {"_ZN2sl11HttpManagerC1Ev", 0x1005c3628ull},
            {"_ZN7network15DownloadManagerC1Ev", 0x100603220ull},
        };
        for (const Mgr& m : mgrs) {
            u64 ctor = elf_find_symbol(elf, m.ctor_sym);
            u64 existing = 0;
            gread(&existing, m.slot, 8);
            if (!ctor) {
                LOGW("boot: singleton ctor missing: %s", m.ctor_sym);
                continue;
            }
            if (existing) {
                LOGI("boot: singleton %s already created (0x%llx)", m.ctor_sym,
                     (unsigned long long)existing);
                continue;
            }
            u64 blk = alloc_native_data(0x8000, 16);
            if (!blk)
                continue;
            guest_call(ctor, blk, 0, 0, 0, 0, 0, 0, 0, "singleton ctor");
            gwrite(m.slot, &blk, 8);
            LOGI("boot: created singleton %s -> 0x%llx", m.ctor_sym,
                 (unsigned long long)blk);
        }
    }

    // 4) initialisers (.init_array)'''
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('singleton creation added')
