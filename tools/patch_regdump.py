import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# dump registers at fault for diagnosis
s = s.replace('''    void dump_backtrace(const char* why) {
        if (!jit_)
            return;
        u64 pc = jit_->GetPC(), lr = jit_->GetRegister(30), sp = jit_->GetSP();
        u64 fp = jit_->GetRegister(29);''',
'''    void dump_backtrace(const char* why) {
        if (!jit_)
            return;
        u64 pc = jit_->GetPC(), lr = jit_->GetRegister(30), sp = jit_->GetSP();
        u64 fp = jit_->GetRegister(29);
        {
            static std::mutex rm;
            std::lock_guard<std::mutex> lk(rm);
            LOGE("--- registers: pc=0x%llx sp=0x%llx", (unsigned long long)pc,
                 (unsigned long long)sp);
            for (int i = 0; i < 30; ++i)
                LOGE("    x%-2d = 0x%llx", i, (unsigned long long)jit_->GetRegister((size_t)i));
        }''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched jit register dump')
