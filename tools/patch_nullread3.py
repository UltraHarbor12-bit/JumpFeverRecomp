import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# 1) add null_page_read helper before fault()
if 'void null_page_read(' not in s:
    anchor = '    void fault(const char* what, u64 vaddr, bool is_write) {'
    helper = '''    void null_page_read(const char* what, u64 vaddr) {
        // The engine dereferenced a null pointer and *read* from the shadow:
        // it expected real data here. Cascade-unwind one frame so the engine's
        // own loop keeps running.
        static std::mutex nm;
        static int nn = 0;
        {
            std::lock_guard<std::mutex> lk(nm);
            if (nn++ < 60)
                LOGW("null-page read @0x%llx (%s) pc=0x%llx",
                     (unsigned long long)vaddr, what,
                     (unsigned long long)(jit_ ? jit_->GetPC() : 0));
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

'''
    s = s.replace(anchor, helper + anchor, 1)
    print('helper inserted')

# 2) insert checks at the start of each read handler
checks = [
    ('    u8 MemoryRead8(u64 vaddr) override {\n', 'u8', 'Read8'),
    ('    u16 MemoryRead16(u64 vaddr) override {\n', 'u16', 'Read16'),
    ('    u32 MemoryRead32(u64 vaddr) override {\n', 'u32', 'Read32'),
    ('    u64 MemoryRead64(u64 vaddr) override {\n', 'u64', 'Read64'),
    ('    Dynarmic::A64::Vector MemoryRead128(u64 vaddr) override {\n', 'vec', 'Read128'),
]
for anchor, rt, op in checks:
    if anchor in s:
        chk = ('        if (vaddr < 0x10000) {\n'
               '            null_page_read("%s", vaddr);\n'
               '            return %s;\n'
               '        }\n' % (op, 'Dynarmic::A64::Vector{}' if rt == 'vec' else '0'))
        s = s.replace(anchor, anchor + chk, 1)
        print('check added:', op)
    else:
        print('ANCHOR MISSING:', op)

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('written')
