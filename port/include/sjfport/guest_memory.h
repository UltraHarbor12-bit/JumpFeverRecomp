// sjfport — guest memory: one contiguous reserved region mapped at a fixed
// guest address so dynarmic's page table is the identity function.
//
// Guest layout (base 0x1_0000_0000, 32 GiB reserved):
//   +0x000000000  ELF image of libsonicjumpfever.so
//   +0x100000000  trampolines (8 bytes per host function)
//   +0x100100000  native data blobs (for imported data symbols)
//   +0x200000000  guest heap (first-fit free list, grows on demand)
//   +0x7F0000000  main guest stack (16 MiB), thread stacks below downward
#pragma once
#include "common.h"
#include <functional>
#include <string>

namespace sjf {

constexpr u64 kGuestBase = 0x100000000ull;        // 4 GiB
constexpr u64 kGuestReserve = 0x800000000ull;     // 32 GiB reserved
constexpr u64 kTrampolineBase = kGuestBase + 0x100000000ull;
constexpr u64 kTrampolineSize = 0x100000ull;      // 1 MiB = 131072 slots
constexpr u64 kNativeDataBase = kTrampolineBase + kTrampolineSize;
constexpr u64 kNativeDataSize = 0x1000000ull;     // 16 MiB
constexpr u64 kHeapBase = kGuestBase + 0x200000000ull;
constexpr u64 kHeapMaxSize = 0x100000000ull;      // heap grows up to 4 GiB
constexpr u64 kStackTop = kGuestBase + 0x7F0000000ull;
constexpr u64 kMainStackSize = 0x1000000ull;      // 16 MiB

extern u8* g_guest_base;
void* guest_null_page_access(u64 gaddr);

bool guest_memory_init();
inline void* guest_to_host(u64 gaddr) {
    if ((gaddr - kGuestBase) < kGuestReserve) [[likely]]
        return g_guest_base + (gaddr - kGuestBase);
    if (gaddr < 0x10000)
        return guest_null_page_access(gaddr);
    return nullptr;
}
bool guest_is_null_page(u64 gaddr);      // guest addr < 64 KiB (shadow page)
u64 null_page_faults();                  // diagnostics counter
u64 host_to_guest(const void* p);
bool guest_commit(u64 gaddr, u64 size);  // commit pages (RW)
u64 guest_alloc_stack(u64 size);         // returns top-of-stack guest address

// ---- guest heap (serves malloc/free/realloc for the guest) ----
u64 guest_heap_alloc(u64 size);
u64 guest_heap_realloc(u64 ptr, u64 size);
void guest_heap_free(u64 ptr);
u64 guest_heap_usage();

// ---- host-call trampolines ----
// A trampoline is 8 bytes of guest code:  svc #imm16 ; ret
// When the guest branches to a trampoline, dynarmic raises the SVC and our
// dispatcher services the call natively; `ret` then returns to the caller.
u64 register_trampoline(u16 imm, const std::string& name);   // guest address
u64 trampoline_for_host_fn(const std::string& name);         // guest address
const std::string& trampoline_name(u64 gaddr);

// Blob storage for imported *data* symbols (SL_IID_*, __sF, ...).
u64 alloc_native_data(u64 size, u64 align = 8);

} // namespace sjf
