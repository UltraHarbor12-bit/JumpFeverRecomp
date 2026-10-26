import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx host_call=%s",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc,
             where.empty() ? "-" : where.c_str());''',
'''        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx host_call=%s",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc,
             where.empty() ? "-" : where.c_str());
        if (ts->jit) {
            for (int r = 19; r <= 28; ++r)
                LOGI("      x%-2d = 0x%llx", r,
                     (unsigned long long)ts->jit->GetRegister((size_t)r));
        }''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('callee-saved dump added')

# boot.cpp: probe DownloadManager::s_instance in each sample
p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''            LOGI("--- pc sample ---");
            jit_dump_threads();''',
'''            LOGI("--- pc sample ---");
            jit_dump_threads();
            {
                u64 si = 0, pp = 0;
                gread(&si, 0x100603220ull, 8);  // network::DownloadManager::s_instance
                gread(&pp, 0x1005cbed0ull, 8);  // PlayerProfile-ish singleton
                LOGI("probe: DownloadManager::s_instance=0x%llx  profile_obj=0x%llx",
                     (unsigned long long)si, (unsigned long long)pp);
            }''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('s_instance probe added')
