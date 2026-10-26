// sjfport — host function registry.
//
// Every Android/libc/libm symbol the guest imports is serviced by a native
// handler. Handlers see the guest register window (x0..x7, sp) through a
// small struct, can read/write guest memory via guest_memory.h, and return
// the value that the guest sees in x0.
#pragma once
#include "common.h"
#include <cstring>
#include <functional>
#include <string>
#include <vector>

namespace sjf {

struct GuestCall;
u64 GuestCall_vararg_gp(GuestCall& c);
double GuestCall_vararg_fp(GuestCall& c);

struct GuestCall {
    u64 x[8];   // x0..x7 argument snapshot
    u64 v[8];   // low 64 bits of v0..v7 (doubles for varargs)
    u64 sp;     // guest stack pointer at the call
    u64 lr;     // guest link register at the call
    u64 ret;    // set this to the value placed in x0 on return
    u64 vret = 0;       // set via set_f32/set_f64 to return in s0/d0 (v0)
    bool has_vret = false;
    // vararg cursor state (see guest_abi.h)
    u64 vargp = 0;   // next GP register index
    u64 vargf = 0;   // next FP register index
    u64 vargs = 0;   // stack cursor (byte offset from sp)
    // va_list mode (for vsnprintf/vprintf handlers)
    bool use_valist = false;
    u64 va_ptr = 0;
    u64 va_stack = 0, va_gr_top = 0, va_vr_top = 0;
    i32 va_gr_offs = 0, va_vr_offs = 0;
    bool va_inited = false;
    // helpers
    u64 arg(u64 i) const { return x[i]; }
    u64& r0() { return ret; }
    float f32(u64 i) const { float f; u32 b = (u32)v[i]; std::memcpy(&f, &b, 4); return f; }
    double f64(u64 i) const { double d; std::memcpy(&d, &v[i], 8); return d; }
    void set_f32(float f) { vret = 0; std::memcpy(&vret, &f, 4); has_vret = true; }
    void set_f64(double d) { std::memcpy(&vret, &d, 8); has_vret = true; }
    u64 vararg_gp() { return GuestCall_vararg_gp(*this); }
    double vararg_fp() { return GuestCall_vararg_fp(*this); }
};

using HostFn = std::function<void(GuestCall&)>;

// Register `fn` under `name`; the loader will bind the guest's undefined
// symbol `name` to a trampoline that dispatches here. Returns trampoline addr.
u64 register_host_fn(const std::string& name, HostFn fn);

// Dispatch table used by the JIT's SVC handler.
HostFn* host_fn_for_svc_imm(u16 imm);

// Lookup (for the ELF loader / debugging).
const HostFn* find_host_fn(const std::string& name);
u64 trampoline_for(const std::string& name);
const std::string& name_for_trampoline(u64 gaddr);

// Modules register themselves here (called from engine boot).
void register_libc_module();
void register_libm_module();
void register_pthread_module();
void register_libstdcxx_module();
void register_liblog_module();
void register_libdl_module();
void register_libandroid_module();
void register_libEGL_module();
void register_libGLESv2_module();
void register_libOpenSLES_module();

// libc: bind the guest __sF blob (stdin/stdout/stderr) after ELF load.
void libc_bind_sF(u64 sf_blob);

// libc: guest fd -> host fd (pipes), -1 if not a pipe.
int host_fd_for_guest(int guest_fd);

} // namespace sjf
