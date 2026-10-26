// sjfport — dynarmic A64 JIT wrapper.
//
// Model: one Jit instance per guest thread. All Android/libc calls leave the
// guest through svc-trampolines (see guest_memory.h) and are serviced by the
// native modules; the trampoline's trailing `ret` returns to the caller.
#include "sjfport/runtime.h"
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"

#include <dynarmic/interface/A64/a64.h>
#include <dynarmic/interface/A64/config.h>
#include <dynarmic/interface/exclusive_monitor.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <memory>
#include <mutex>
#include <vector>
#include <thread>

namespace sjf {

namespace {
// Runtime watchpoints (diagnostics): log writes to interesting guest addresses.
constexpr u64 kWatchedAddr = 0x1005cbed0ull; // PlayerProfile singleton (.bss)
constexpr u64 kWatchedSize = 16;
constexpr u64 kWatchedAddr2 = 0x1005c4710ull; // renderer state (slInitialise flag)
constexpr u64 kWatchedSize2 = 32;

inline void watch_write(u64 vaddr, u64 size, u64 value, Dynarmic::A64::Jit* jit) {
    if ((vaddr - kWatchedAddr) < 0x100000ull && debug_mode()) [[unlikely]] {
        if (vaddr < kWatchedAddr2 + kWatchedSize2 && vaddr + size > kWatchedAddr2) {
            static int m2 = 0;
            if (m2++ < 40)
                LOGE("WATCH2 write @0x%llx size=%llu value=0x%llx from pc=0x%llx",
                     (unsigned long long)vaddr, (unsigned long long)size,
                     (unsigned long long)value, (unsigned long long)(jit ? jit->GetPC() : 0));
        }
        if (vaddr < kWatchedAddr + kWatchedSize && vaddr + size > kWatchedAddr) {
            static int n = 0;
            if (n++ < 40)
                LOGE("WATCH write @0x%llx size=%llu value=0x%llx from pc=0x%llx",
                     (unsigned long long)vaddr, (unsigned long long)size,
                     (unsigned long long)value, (unsigned long long)(jit ? jit->GetPC() : 0));
        }
    }
}

// Sentinel return address: any code fetch here fails -> NoExecuteFault ->
// we treat it as "the guest function returned".
constexpr u64 kReturnSentinel = 0xDEAD0000ull;

struct ThreadState {
    std::unique_ptr<Dynarmic::A64::Jit> jit;
    u64 sp = 0;
    bool owns_sp = false;
    u64 last_pc = 0;
    u64 last_x0 = 0;
    std::atomic<u64> snap_pc{0};
    std::atomic<u64> snap_lr{0};
    std::atomic<u64> snap_sp{0};
    std::atomic<u64> snap_fp{0};
};

thread_local ThreadState* t_state = nullptr;

// Per-thread JIT diagnostics/unwind state (declared early: Callbacks uses it).
thread_local u64 t_entry_sp = 0;  // guest SP at the current guest_call entry
thread_local bool t_resilient = true;
thread_local u64 t_unwind_pc = 0;    // cascade target: caller's resume PC
thread_local u64 t_unwind_sp = 0;    // cascade target: caller's SP
thread_local bool t_unwind_pending = false;

class Callbacks final : public Dynarmic::A64::UserCallbacks {
public:
    static Callbacks& instance() {
        thread_local Callbacks cb;
        return cb;
    }

    void bind(Dynarmic::A64::Jit* jit) { jit_ = jit; }
    Dynarmic::A64::Jit* bound() const { return jit_; }

    std::optional<u32> MemoryReadCode(u64 vaddr) override {
        // Return sentinel: our "guest function returned" marker
        if (vaddr == kReturnSentinel)
            return std::nullopt;
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) {
            fault("ReadCode", vaddr, false);
            return std::nullopt;
        }
        u32 v;
        std::memcpy(&v, p, 4);
        return v;
    }

    u8 MemoryRead8(u64 vaddr) override {
        if (vaddr < 0x10000) {
            null_page_read("Read8", vaddr);
            return 0;
        }
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) { fault("Read64", vaddr, false); return 0; }
        return *p;
    }
    u16 MemoryRead16(u64 vaddr) override {
        if (vaddr < 0x10000) {
            null_page_read("Read16", vaddr);
            return 0;
        }
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) { fault("Read16", vaddr, false); return 0; }
        u16 v;
        std::memcpy(&v, p, 2);
        return v;
    }
    u32 MemoryRead32(u64 vaddr) override {
        if (vaddr < 0x10000) {
            null_page_read("Read32", vaddr);
            return 0;
        }
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) { fault("Read32", vaddr, false); return 0; }
        u32 v;
        std::memcpy(&v, p, 4);
        return v;
    }
    u64 MemoryRead64(u64 vaddr) override {
        if (vaddr < 0x10000) {
            null_page_read("Read64", vaddr);
            return 0;
        }
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) { fault("Read64", vaddr, false); return 0; }
        u64 v;
        std::memcpy(&v, p, 8);
        return v;
    }
    Dynarmic::A64::Vector MemoryRead128(u64 vaddr) override {
        if (vaddr < 0x10000) {
            null_page_read("Read128", vaddr);
            return Dynarmic::A64::Vector{};
        }
        Dynarmic::A64::Vector v{};
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) { fault("Read128", vaddr, false); return v; }
        std::memcpy(v.data(), p, 16);
        return v;
    }
    void MemoryWrite8(u64 vaddr, u8 value) override {
        watch_write(vaddr, 1, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("Write8", vaddr, true); return; }
        *p = value;
    }
    void MemoryWrite16(u64 vaddr, u16 value) override {
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("Write16", vaddr, true); return; }
        std::memcpy(p, &value, 2);
    }
    void MemoryWrite32(u64 vaddr, u32 value) override {
        watch_write(vaddr, 4, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("Write32", vaddr, true); return; }
        std::memcpy(p, &value, 4);
    }
    void MemoryWrite64(u64 vaddr, u64 value) override {
        watch_write(vaddr, 8, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("Write64", vaddr, true); return; }
        std::memcpy(p, &value, 8);
    }
    void MemoryWrite128(u64 vaddr, Dynarmic::A64::Vector value) override {
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("Write128", vaddr, true); return; }
        std::memcpy(p, value.data(), 16);
    }

    bool MemoryWriteExclusive8(u64 vaddr, u8 value, u8 expected) override {
        watch_write(vaddr, 1, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("WriteEx8", vaddr, true); return false; }
        if (*p != expected) return false;
        *p = value;
        return true;
    }
    bool MemoryWriteExclusive16(u64 vaddr, u16 value, u16 expected) override {
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("WriteEx16", vaddr, true); return false; }
        u16 cur;
        std::memcpy(&cur, p, 2);
        if (cur != expected) return false;
        std::memcpy(p, &value, 2);
        return true;
    }
    bool MemoryWriteExclusive32(u64 vaddr, u32 value, u32 expected) override {
        watch_write(vaddr, 4, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("WriteEx32", vaddr, true); return false; }
        u32 cur;
        std::memcpy(&cur, p, 4);
        if (cur != expected) return false;
        std::memcpy(p, &value, 4);
        return true;
    }
    bool MemoryWriteExclusive64(u64 vaddr, u64 value, u64 expected) override {
        watch_write(vaddr, 8, value, jit_);
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("WriteEx64", vaddr, true); return false; }
        u64 cur;
        std::memcpy(&cur, p, 8);
        if (cur != expected) return false;
        std::memcpy(p, &value, 8);
        return true;
    }
    bool MemoryWriteExclusive128(u64 vaddr, Dynarmic::A64::Vector value, Dynarmic::A64::Vector expected) override {
        auto* p = (u8*)guest_to_host(vaddr);
        if (!p) { fault("WriteEx128", vaddr, true); return false; }
        if (std::memcmp(p, expected.data(), 16) != 0) return false;
        std::memcpy(p, value.data(), 16);
        return true;
    }

    bool IsReadOnlyMemory(u64) override { return false; }

    void InterpreterFallback(u64 pc, size_t num) override {
        LOGE("InterpreterFallback at pc=0x%llx (%zu instructions)", (unsigned long long)pc, num);
        if (jit_)
            jit_->HaltExecution();
    }

    void CallSVC(u32 swi) override {
        HostFn* fn = host_fn_for_svc_imm((u16)swi);
        if (!fn) {
            LOGE("CallSVC: unimplemented svc #%u at pc=0x%llx", swi,
                 (unsigned long long)(jit_ ? jit_->GetPC() : 0));
            if (jit_)
                jit_->HaltExecution();
            return;
        }
        if (!jit_)
            return;
        GuestCall c{};
        for (int i = 0; i < 8; ++i)
            c.x[i] = jit_->GetRegister((size_t)i);
        c.sp = jit_->GetSP();
        c.lr = jit_->GetRegister(30);
        if (t_state && t_state->jit.get() == jit_) {
            t_state->snap_pc.store(jit_->GetPC(), std::memory_order_relaxed);
            t_state->snap_lr.store(c.lr, std::memory_order_relaxed);
            t_state->snap_sp.store(c.sp, std::memory_order_relaxed);
            t_state->snap_fp.store(jit_->GetRegister(29), std::memory_order_relaxed);
        }
        for (int i = 0; i < 8; ++i)
            c.v[i] = jit_->GetVector((size_t)i)[0];
        c.ret = 0;
        (*fn)(c);
        jit_->SetRegister(0, c.ret);
        if (c.has_vret)
            jit_->SetVector(0, {c.vret, 0});
    }

    void ExceptionRaised(u64 pc, Dynarmic::A64::Exception exception) override {
        using Dynarmic::A64::Exception;
        switch (exception) {
            case Exception::NoExecuteFault:
                // our return sentinel: guest function returned
                if (pc >= kReturnSentinel && pc < kReturnSentinel + 0x10000) {
                    if (jit_)
                        jit_->HaltExecution();
                    return;
                }
                LOGE("NoExecuteFault at pc=0x%llx", (unsigned long long)pc);
                break;
            case Exception::Breakpoint:
                LOGE("Breakpoint (brk) at pc=0x%llx", (unsigned long long)pc);
                break;
            case Exception::WaitForInterrupt:
            case Exception::Yield:
            case Exception::SendEvent:
            case Exception::SendEventLocal:
            case Exception::WaitForEvent:
                return; // benign hints
            default:
                LOGE("ExceptionRaised type=%d at pc=0x%llx", (int)exception,
                     (unsigned long long)pc);
                break;
        }
        if (jit_ && t_resilient && t_entry_sp
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
            jit_->HaltExecution();
    }

    void AddTicks(u64) override {}
    u64 GetTicksRemaining() override { return 100000; }
    u64 GetCNTPCT() override {
        auto now = std::chrono::steady_clock::now().time_since_epoch();
        return (u64)std::chrono::duration_cast<std::chrono::nanoseconds>(now).count();
    }

private:
    void dump_backtrace(const char* why) {
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
        }
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

    void null_page_read(const char* what, u64 vaddr) {
        // The engine dereferenced a null pointer and *read* from the shadow:
        // it expected real data here. Cascade-unwind one frame so the engine's
        // own loop keeps running.
        static std::mutex nm;
        static int nn = 0;
        {
            std::lock_guard<std::mutex> lk(nm);
            if (nn++ < 12) {
                LOGW("null-page read @0x%llx (%s) pc=0x%llx",
                     (unsigned long long)vaddr, what,
                     (unsigned long long)(jit_ ? jit_->GetPC() : 0));
                dump_backtrace("null-page read");
            }
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

    void fault(const char* what, u64 vaddr, bool is_write) {
        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected
        if (vaddr < 0x10000) {
            if (is_write)
                return; // writes into the null-page shadow are absorbed
            // reads mean the engine expected real data here: cascade unwind
        }
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);
        dump_backtrace(what);
        if (jit_)
            jit_->HaltExecution();
    }
    Dynarmic::A64::Jit* jit_ = nullptr;
};

// Registry of guest threads (for diagnostics).
std::mutex g_threads_mutex;
std::vector<ThreadState*> g_threads;

constexpr size_t kMaxExclusiveProcessors = 64;
Dynarmic::ExclusiveMonitor g_exclusive_monitor{kMaxExclusiveProcessors};
std::atomic<size_t> g_next_proc_id{0};

size_t current_processor_id() {
    thread_local size_t id = g_next_proc_id.fetch_add(1, std::memory_order_relaxed) % kMaxExclusiveProcessors;
    return id;
}

std::unique_ptr<Dynarmic::A64::Jit> make_jit(Dynarmic::A64::UserConfig& cfg_out) {
    Dynarmic::A64::UserConfig cfg{};
    cfg.callbacks = &Callbacks::instance();
    cfg.processor_id = current_processor_id();
    cfg.global_monitor = &g_exclusive_monitor;
    cfg.enable_cycle_counting = false;
    cfg.wall_clock_cntpct = true;
    cfg.code_cache_size = 64 * 1024 * 1024;
    // (page_table optimisation lands in Hito 2; callbacks keep it simple)
    cfg_out = cfg;
    auto jit = std::make_unique<Dynarmic::A64::Jit>(cfg);
    return jit;
}

ThreadState& thread_state() {
    if (!t_state) {
        t_state = new ThreadState();
        {
            std::lock_guard<std::mutex> lk(g_threads_mutex);
            g_threads.push_back(t_state);
        }
        Dynarmic::A64::UserConfig cfg{};
        t_state->jit = make_jit(cfg);
        t_state->sp = guest_alloc_stack(kMainStackSize);
        t_state->owns_sp = true;
        LOGI("jit: thread state created (sp=0x%llx)", (unsigned long long)t_state->sp);
    }
    return *t_state;
}

u64 run_on(ThreadState& ts, u64 fn, u64 a0, u64 a1, u64 a2, u64 a3, u64 a4, u64 a5,
           u64 a6, u64 a7, const char* what) {
    auto& jit = *ts.jit;
    if (jit.IsExecuting()) {
        LOGW("run_on: jit already executing (%s) — nested call via new instance", what ? what : "?");
        return guest_call_nested(fn, a0, a1, a2, a3, a4, a5, a6, a7);
    }
    Dynarmic::A64::Jit* prev_jit = Callbacks::instance().bound();
    u64 prev_entry_sp = t_entry_sp;
    u64 prev_unwind_pc = t_unwind_pc;
    u64 prev_unwind_sp = t_unwind_sp;
    bool prev_unwind_pending = t_unwind_pending;

    Callbacks::instance().bind(&jit);

    u64 sp = ts.sp ? ts.sp : (ts.sp = guest_alloc_stack(kMainStackSize));
    // write sentinel return address
    u64 ret_slot = sp - 16;
    u64 sentinel = kReturnSentinel;
    gwrite(ret_slot, &sentinel, 8);
    t_entry_sp = ret_slot;
    t_unwind_pending = false;

    jit.ClearHalt();
    jit.SetPC(fn);
    jit.SetSP(ret_slot);
    jit.SetRegister(30, kReturnSentinel); // LR
    jit.SetRegister(0, a0);
    jit.SetRegister(1, a1);
    jit.SetRegister(2, a2);
    jit.SetRegister(3, a3);
    jit.SetRegister(4, a4);
    jit.SetRegister(5, a5);
    jit.SetRegister(6, a6);
    jit.SetRegister(7, a7);

    if (what)
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
    ts.last_x0 = jit.GetRegister(0);
    const bool returned = (ts.last_pc >= kReturnSentinel && ts.last_pc < kReturnSentinel + 0x10000);
    if (!returned && ts.last_pc != 0) {
        LOGW("run_on(%s): halted at pc=0x%llx (not a normal return)", what ? what : "?",
             (unsigned long long)ts.last_pc);
    }

    Callbacks::instance().bind(prev_jit);
    t_entry_sp = prev_entry_sp;
    t_unwind_pc = prev_unwind_pc;
    t_unwind_sp = prev_unwind_sp;
    t_unwind_pending = prev_unwind_pending;
    return ts.last_x0;
}

} // namespace

u64 guest_call(u64 fn, u64 a0, u64 a1, u64 a2, u64 a3, u64 a4, u64 a5, u64 a6, u64 a7,
               const char* what) {
    return run_on(thread_state(), fn, a0, a1, a2, a3, a4, a5, a6, a7, what);
}

u64 guest_call_nested(u64 fn, u64 a0, u64 a1, u64 a2, u64 a3, u64 a4, u64 a5, u64 a6, u64 a7) {
    thread_local std::vector<std::unique_ptr<ThreadState>> nested_pool;
    thread_local size_t depth = 0;
    if (depth >= nested_pool.size()) {
        auto ts = std::make_unique<ThreadState>();
        Dynarmic::A64::UserConfig cfg{};
        ts->jit = make_jit(cfg);
        ts->sp = guest_alloc_stack(0x80000); // 512 KiB
        ts->owns_sp = true;
        nested_pool.push_back(std::move(ts));
    }
    ThreadState& ts = *nested_pool[depth++];
    u64 ret = run_on(ts, fn, a0, a1, a2, a3, a4, a5, a6, a7, "nested");
    --depth;
    return ret;
}

void jit_backtrace_here(const char* why) {
    ThreadState* ts = t_state;
    if (!ts || !ts->jit)
        return;
    u64 fp = ts->jit->GetRegister(29);
    u64 lr = ts->jit->GetRegister(30);
    u64 sp = ts->jit->GetSP();
    LOGE("guest backtrace (%s): lr=0x%llx fp=0x%llx sp=0x%llx", why,
         (unsigned long long)lr, (unsigned long long)fp, (unsigned long long)sp);
    // raw stack dump (to spot return addresses when the fp chain is broken)
    for (int w = 0; w < 24; ++w) {
        u64 a = sp + (u64)w * 8;
        if (!guest_to_host(a))
            break;
        u64 v = 0;
        std::memcpy(&v, guest_to_host(a), 8);
        if (v >= 0x100100000ull && v < 0x10060b000ull && (v & 3) == 0)
            LOGE("    [sp+%03d] 0x%llx (.text)", w * 8, (unsigned long long)v);
    }
    for (int i = 0; i < 10 && fp; ++i) {
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
}

u64 guest_new_thread_stack(u64 size) { return guest_alloc_stack(size); }

void jit_dump_threads() {
    std::lock_guard<std::mutex> lk(g_threads_mutex);
    LOGI("--- guest threads: %zu ---", g_threads.size());
    for (size_t i = 0; i < g_threads.size(); ++i) {
        ThreadState* ts = g_threads[i];
        bool running = ts->jit && ts->jit->IsExecuting();
        u64 pc = running ? ts->snap_pc.load() : (ts->jit ? ts->jit->GetPC() : 0);
        u64 lr = running ? ts->snap_lr.load() : (ts->jit ? ts->jit->GetRegister(30) : 0);
        u64 sp = running ? ts->snap_sp.load() : (ts->jit ? ts->jit->GetSP() : 0);
        u64 fp = running ? ts->snap_fp.load() : (ts->jit ? ts->jit->GetRegister(29) : 0);
        std::string where = trampoline_name(pc & ~0x7ull);
        if (where.empty())
            where = trampoline_name((pc + 4) & ~0x7ull);
        LOGI("  thread[%zu] pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx last_pc=0x%llx host_call=%s",
             i, (unsigned long long)pc, (unsigned long long)lr, (unsigned long long)sp,
             (unsigned long long)fp, (unsigned long long)ts->last_pc,
             where.empty() ? "-" : where.c_str());
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
}

bool guest_thread_start(u64 fn, u64 arg) {
    try {
        std::thread th([fn, arg]() {
            ThreadState& ts = thread_state();
            LOGI("guest thread started: fn=0x%llx arg=0x%llx", (unsigned long long)fn,
                 (unsigned long long)arg);
            u64 r = run_on(ts, fn, arg, 0, 0, 0, 0, 0, 0, 0, "thread");
            LOGI("guest thread finished: fn=0x%llx ret=0x%llx", (unsigned long long)fn,
                 (unsigned long long)r);
        });
        th.detach();
        return true;
    } catch (const std::exception& e) {
        LOGE("guest_thread_start failed: %s", e.what());
        return false;
    }
}

} // namespace sjf
