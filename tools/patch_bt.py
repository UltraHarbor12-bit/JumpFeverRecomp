import io

p = 'port/src/runtime/jit.cpp'
with io.open(p, 'r', encoding='utf-8', newline=None) as f:
    s = f.read()

# 1) accept sentinel range as a normal return
s = s.replace('''            case Exception::NoExecuteFault:
                // our return sentinel: guest function returned
                if (pc == kReturnSentinel) {''', '''            case Exception::NoExecuteFault:
                // our return sentinel: guest function returned
                if (pc >= kReturnSentinel && pc < kReturnSentinel + 0x100) {''')

# 2) backtrace helper + use it on faults
s = s.replace('''private:
    void fault(const char* what, u64 vaddr) {''', '''private:
    void dump_backtrace(const char* why) {
        if (!jit_)
            return;
        u64 pc = jit_->GetPC(), lr = jit_->GetRegister(30), sp = jit_->GetSP();
        u64 fp = jit_->GetRegister(29);
        LOGE("--- guest backtrace (%s): pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx ---", why,
             (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp);
        for (int i = 0; i < 12 && fp; ++i) {
            u64 prev = 0, ret = 0;
            if (!guest_to_host(fp) || !guest_to_host(fp + 8))
                break;
            std::memcpy(&prev, guest_to_host(fp), 8);
            std::memcpy(&ret, guest_to_host(fp + 8), 8);
            LOGE("    #%d lr=0x%llx", i, (unsigned long long)ret);
            if (prev <= fp)
                break;
            fp = prev;
        }
        LOGE("--- end backtrace ---");
    }

    void fault(const char* what, u64 vaddr) {''')

s = s.replace('''        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        if (jit_)
            jit_->HaltExecution();''', '''        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        dump_backtrace(what);
        if (jit_)
            jit_->HaltExecution();''')

with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
    f.write(s)
print('patched jit.cpp')
