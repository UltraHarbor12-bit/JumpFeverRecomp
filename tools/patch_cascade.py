import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# 1) cascade unwind state (thread-local, early)
s = s.replace('''// Per-thread JIT diagnostics/unwind state (declared early: Callbacks uses it).
thread_local u64 t_entry_sp = 0;  // guest SP at the current guest_call entry
thread_local bool t_resilient = true;''',
'''// Per-thread JIT diagnostics/unwind state (declared early: Callbacks uses it).
thread_local u64 t_entry_sp = 0;  // guest SP at the current guest_call entry
thread_local bool t_resilient = true;
thread_local u64 t_unwind_pc = 0;    // cascade target: caller's resume PC
thread_local u64 t_unwind_sp = 0;    // cascade target: caller's SP
thread_local bool t_unwind_pending = false;''')

# 2) fault(): cascade unwind one frame via the frame-pointer chain
s = s.replace('''        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        dump_backtrace(what);
        if (jit_ && t_resilient && t_entry_sp) {
            // Resilient unwind: treat the current guest_call as returned.
            static std::mutex um;
            static int un = 0;
            {
                std::lock_guard<std::mutex> lk(um);
                if (un++ < 30)
                    LOGW("resilient unwind #%d (pc=0x%llx)", un,
                         (unsigned long long)jit_->GetPC());
            }
            jit_->SetSP(t_entry_sp);
            jit_->SetPC(kReturnSentinel);
            jit_->HaltExecution();
            return;
        }
        if (jit_)
            jit_->HaltExecution();''',
'''        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        dump_backtrace(what);
        if (jit_ && t_resilient) {
            // Cascade unwind: return to the CALLER of the faulting function
            // using its frame pointer. The caller resumes right after the
            // call, sees a null/garbage return value, and typically unwinds
            // again one level up until a frame tolerates it.
            u64 fp = jit_->GetRegister(29);
            u64 lr = jit_->GetRegister(30);
            u64 sp = jit_->GetSP();
            bool ok = fp && guest_to_host(fp) && guest_to_host(fp + 16) && fp > sp
                      && fp < t_entry_sp + 0x1000000;
            if (ok) {
                t_unwind_pc = lr;
                t_unwind_sp = fp + 16;
                t_unwind_pending = true;
                static std::mutex um;
                static int un = 0;
                {
                    std::lock_guard<std::mutex> lk(um);
                    if (un++ < 40)
                        LOGW("cascade unwind -> pc=0x%llx sp=0x%llx", (unsigned long long)lr,
                             (unsigned long long)t_unwind_sp);
                }
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
            jit_->HaltExecution();''')

# 3) ExceptionRaised: same cascade for fatal exceptions
s = s.replace('''        if (jit_ && t_resilient && t_entry_sp && exception != Dynarmic::A64::Exception::Breakpoint) {
            jit_->SetSP(t_entry_sp);
            jit_->SetPC(kReturnSentinel);
            jit_->HaltExecution();
            return;
        }
        if (jit_)
            jit_->HaltExecution();''',
'''        if (jit_ && t_resilient && t_entry_sp
            && exception != Dynarmic::A64::Exception::Breakpoint) {
            u64 fp = jit_->GetRegister(29);
            u64 lr = jit_->GetRegister(30);
            u64 sp = jit_->GetSP();
            if (fp && guest_to_host(fp) && fp > sp) {
                t_unwind_pc = lr;
                t_unwind_sp = fp + 16;
                t_unwind_pending = true;
                jit_->HaltExecution();
                return;
            }
            jit_->SetSP(t_entry_sp);
            jit_->SetPC(kReturnSentinel);
            t_unwind_pending = false;
            jit_->HaltExecution();
            return;
        }
        if (jit_)
            jit_->HaltExecution();''')

# 4) run_on: re-enter the JIT after each cascade unwind
s = s.replace('''    if (what)
        LOGD("run: %s (fn=0x%llx)", what, (unsigned long long)fn);

    auto halt = jit.Run();
    (void)halt;
    ts.last_pc = jit.GetPC();
    ts.last_x0 = jit.GetRegister(0);''',
'''    if (what)
        LOGD("run: %s (fn=0x%llx)", what, (unsigned long long)fn);

    for (;;) {
        auto halt = jit.Run();
        (void)halt;
        if (t_unwind_pending) {
            t_unwind_pending = false;
            jit.ClearHalt();
            jit.SetPC(t_unwind_pc);
            jit.SetSP(t_unwind_sp);
            continue; // resume at the caller after the cascade unwind
        }
        break;
    }
    ts.last_pc = jit.GetPC();
    ts.last_x0 = jit.GetRegister(0);''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('cascade unwinder installed')
