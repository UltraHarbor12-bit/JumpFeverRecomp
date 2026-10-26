import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# 1) extract cascade logic into a reusable method
s = s.replace('''    void fault(const char* what, u64 vaddr, bool is_write) {''',
'''    void null_page_read(const char* what, u64 vaddr) {
        // The engine dereferenced a null pointer and *read* from the shadow.
        // That means it expected real data here: cascade-unwind one frame.
        static std::mutex nm;
        static int nn = 0;
        {
            std::lock_guard<std::mutex> lk(nm);
            if (nn++ < 50)
                LOGW("null-page read @0x%llx (%s) from pc=0x%llx — cascading",
                     (unsigned long long)vaddr, what, (unsigned long long)(jit_ ? jit_->GetPC() : 0));
        }
        if (jit_ && t_resilient) {
            u64 fp = jit_->GetRegister(29);
            u64 lr = jit_->GetRegister(30);
            u64 sp = jit_->GetSP();
            if (fp && guest_to_host(fp) && guest_to_host(fp + 16) && fp > sp) {
                t_unwind_pc = lr;
                t_unwind_sp = fp + 16;
                t_unwind_pending = true;
                jit_->HaltExecution();
                return;
            }
        }
        if (jit_ && t_resilient && t_entry_sp) {
            jit_->SetSP(t_entry_sp);
            jit_->SetPC(kReturnSentinel);
            t_unwind_pending = false;
            jit_->HaltExecution();
            return;
        }
        if (jit_)
            jit_->HaltExecution();
    }

    void fault(const char* what, u64 vaddr, bool is_write) {''')

# 2) reads from the null page trigger the cascade
for op, cast in (('Read8', 'u8'), ('Read16', 'u16'), ('Read32', 'u32'), ('Read64', 'u64')):
    old = ('    %s Memory%s(u64 vaddr) override {\n'
           '        auto* p = (const u8*)guest_to_host(vaddr);' % (cast, op))
    new = ('    %s Memory%s(u64 vaddr) override {\n'
           '        if (vaddr < 0x10000) {\n'
           '            null_page_read("%s", vaddr);\n'
           '            return 0;\n'
           '        }\n'
           '        auto* p = (const u8*)guest_to_host(vaddr);' % (cast, op, op))
    if old in s:
        s = s.replace(old, new, 1)
        print('ok', op)
    else:
        print('MISS', op)

# Read128 has a different body
s = s.replace('''    Dynarmic::A64::Vector MemoryRead128(u64 vaddr) override {
        Dynarmic::A64::Vector v{};
        auto* p = (const u8*)guest_to_host(vaddr);''',
'''    Dynarmic::A64::Vector MemoryRead128(u64 vaddr) override {
        Dynarmic::A64::Vector v{};
        if (vaddr < 0x10000) {
            null_page_read("Read128", vaddr);
            return v;
        }
        auto* p = (const u8*)guest_to_host(vaddr);''')
print('done')
