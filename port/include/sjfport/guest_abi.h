// sjfport — guest ABI helpers: string access, memory peek/poke and a
// printf-style formatter driven by AAPCS64 vararg rules.
//
// AArch64 varargs: integer/pointer args fill x-regs in order, FP args fill
// v-regs in order; once one family is exhausted, that type is served from the
// stack (single shared stack cursor) — mirroring va_arg() over {gr, vr, stack}.
#pragma once
#include "common.h"
#include "host_calls.h"
#include <string>

namespace sjf {

// Read a NUL-terminated string from guest memory (bounds-safe).
std::string gstr(u64 gaddr);
void gwrite(u64 gaddr, const void* data, u64 size);
void gread(void* out, u64 gaddr, u64 size);

// Guest vararg pullers (mutate the cursor state inside the call).
u64 GuestCall_vararg_gp(GuestCall& c);    // int/pointer-sized
double GuestCall_vararg_fp(GuestCall& c); // double (FP reg or stack)

// Guest printf engine. `fmt_gaddr` is the guest format string; varargs are
// pulled from the call's cursors. Returns the formatted string.
std::string guest_format(GuestCall& c, u64 fmt_gaddr);

// Convenience: register a variadic logging function handler.
// first_vararg_gp = index of the first x register that holds a vararg.
void register_printf_style_host_fns();

} // namespace sjf
