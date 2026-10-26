import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# 1) thread-local entry SP for clean unwinding
s = s.replace('''thread_local ThreadState* t_state = nullptr;''',
'''thread_local ThreadState* t_state = nullptr;
thread_local u64 t_entry_sp = 0; // guest SP at the current guest_call entry
thread_local bool t_resilient = true;''')

# 2) fault(): unwind instead of killing the thread
s = s.replace('''        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected
        if (vaddr < 0x10000)
            return; // null-page shadow: expected
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        dump_backtrace(what);
        if (jit_)
            jit_->HaltExecution();''',
'''        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected
        if (vaddr < 0x10000)
            return; // null-page shadow: expected
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
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
            jit_->HaltExecution();''')

# 3) ExceptionRaised: same unwind for unexpected exceptions (not sentinel, not hints)
s = s.replace('''            default:
                LOGE("ExceptionRaised type=%d at pc=0x%llx", (int)exception,
                     (unsigned long long)pc);
                break;
        }
        if (jit_)
            jit_->HaltExecution();''',
'''            default:
                LOGE("ExceptionRaised type=%d at pc=0x%llx", (int)exception,
                     (unsigned long long)pc);
                break;
        }
        if (jit_ && t_resilient && t_entry_sp && exception != Dynarmic::A64::Exception::Breakpoint) {
            jit_->SetSP(t_entry_sp);
            jit_->SetPC(kReturnSentinel);
            jit_->HaltExecution();
            return;
        }
        if (jit_)
            jit_->HaltExecution();''')

# 4) run_on: record entry sp
s = s.replace('''    u64 sp = ts.sp ? ts.sp : (ts.sp = guest_alloc_stack(kMainStackSize));
    // write sentinel return address
    u64 ret_slot = sp - 16;
    u64 sentinel = kReturnSentinel;
    gwrite(ret_slot, &sentinel, 8);''',
'''    u64 sp = ts.sp ? ts.sp : (ts.sp = guest_alloc_stack(kMainStackSize));
    // write sentinel return address
    u64 ret_slot = sp - 16;
    u64 sentinel = kReturnSentinel;
    gwrite(ret_slot, &sentinel, 8);
    t_entry_sp = ret_slot;''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('resilient unwind installed')
