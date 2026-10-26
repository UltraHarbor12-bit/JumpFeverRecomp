import io

# ---- jit.cpp: thread registry + dump ----
p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''thread_local ThreadState* t_state = nullptr;''',
'''thread_local ThreadState* t_state = nullptr;

// Registry of guest threads (for diagnostics).
std::mutex g_threads_mutex;
std::vector<ThreadState*> g_threads;''')

s = s.replace('''ThreadState& thread_state() {
    if (!t_state) {
        t_state = new ThreadState();''',
'''ThreadState& thread_state() {
    if (!t_state) {
        t_state = new ThreadState();
        {
            std::lock_guard<std::mutex> lk(g_threads_mutex);
            g_threads.push_back(t_state);
        }''')

s = s.replace('''            ThreadState ts;
            Dynarmic::A64::UserConfig cfg{};
            ts.jit = make_jit(cfg);
            ts.sp = guest_alloc_stack(0x100000); // 1 MiB per guest thread
            ts.owns_sp = true;''',
'''            ThreadState ts;
            Dynarmic::A64::UserConfig cfg{};
            ts.jit = make_jit(cfg);
            ts.sp = guest_alloc_stack(0x100000); // 1 MiB per guest thread
            ts.owns_sp = true;
            {
                std::lock_guard<std::mutex> lk(g_threads_mutex);
                g_threads.push_back(&ts);
            }''')

s = s.replace('''u64 guest_new_thread_stack(u64 size) { return guest_alloc_stack(size); }''',
'''u64 guest_new_thread_stack(u64 size) { return guest_alloc_stack(size); }

void jit_dump_threads() {
    std::lock_guard<std::mutex> lk(g_threads_mutex);
    LOGI("--- guest threads: %zu ---", g_threads.size());
    for (size_t i = 0; i < g_threads.size(); ++i) {
        ThreadState* ts = g_threads[i];
        u64 pc = ts->jit ? ts->jit->GetPC() : 0;
        u64 lr = ts->jit ? ts->jit->GetRegister(30) : 0;
        u64 sp = ts->jit ? ts->jit->GetSP() : 0;
        u64 fp = ts->jit ? ts->jit->GetRegister(29) : 0;
        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc);
        for (int f = 0; f < 8 && fp; ++f) {
            u64 prev = 0, ret = 0;
            if (!guest_to_host(fp) || !guest_to_host(fp + 8))
                break;
            std::memcpy(&prev, guest_to_host(fp), 8);
            std::memcpy(&ret, guest_to_host(fp + 8), 8);
            LOGI("      frame %d lr=0x%llx", f, (unsigned long long)ret);
            if (prev <= fp)
                break;
            fp = prev;
        }
    }
    LOGI("--- end threads ---");
}''')

s = s.replace('#include <mutex>', '#include <mutex>\n#include <vector>')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok jit thread dump')

# ---- runtime.h: declaration ----
p = 'port/include/sjfport/runtime.h'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''// Guest stack management for new threads.''',
'''// Dump every guest thread's PC/LR/stack (diagnostics).
void jit_dump_threads();

// Guest stack management for new threads.''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok runtime.h')

# ---- main.cpp: call on watchdog ----
p = 'port/src/main.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('''namespace sjf {
bool boot(const std::string& so_path);
}''', '''namespace sjf {
bool boot(const std::string& so_path);
void jit_dump_threads();
}''')
s = s.replace('''        LOGE("watchdog: %d s elapsed, terminating process", seconds);
        std::fflush(stderr);''', '''        LOGE("watchdog: %d s elapsed, terminating process", seconds);
        sjf::jit_dump_threads();
        std::fflush(stderr);''')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('ok main.cpp')
