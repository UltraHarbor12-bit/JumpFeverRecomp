// sjfport — runtime services used by the dependency modules
#pragma once
#include "common.h"
#include <string>

namespace sjf {

// Graceful shutdown: the frame loop exits, the guest gets the Android
// lifecycle (focus lost -> onPause -> onSaveInstanceState -> onStop) so it saves
// its profile, then the process ends.
void request_quit();
// Save editor (hito 9): apply PlayerProfile setters in-game, then save().
bool profile_edit_load(const std::string& path);
void profile_edit_notify_frontend(); // frontend music started (profile loaded)
void profile_edit_poll();            // game thread, between frames
// Zone used when the (dead) game server provides none: green_hill_zone,
// blue_sky_zone, jungle_zone or mechanical_zone. Empty = game default.
void set_default_zone(const std::string& zone);
void set_anim_fallback(bool on);
// Unreleased characters (hito 10): Vector, Rouge, Cream selectable. On by default.
void set_extra_chars(bool on);
bool extra_chars_enabled();
// "player_cream.sla" -> "player_amy.sla" when the package is missing (VFS).
std::string extra_char_donor_name(const std::string& bare_name); // --anim-fallback (auto with non-default zones)
bool quit_requested();

// libc VFS: guest path (assets/..., game/..., bare asset name) -> host path
std::string host_resolve_path(const std::string& guest_path);

// Run the guest function `fn` on a fresh guest thread (one JIT per thread).
// Returns false if the thread could not be started.
bool guest_thread_start(u64 fn, u64 arg);

// Call a guest function from inside a host handler (re-entrant path).
// Spawns a temporary JIT instance sharing the same memory.
u64 guest_call_nested(u64 fn, u64 a0 = 0, u64 a1 = 0, u64 a2 = 0, u64 a3 = 0,
                      u64 a4 = 0, u64 a5 = 0, u64 a6 = 0, u64 a7 = 0);

// Execute a guest function on the calling thread's JIT, synchronously.
// Used for init_array / lifecycle entry points.
u64 guest_call(u64 fn, u64 a0 = 0, u64 a1 = 0, u64 a2 = 0, u64 a3 = 0,
               u64 a4 = 0, u64 a5 = 0, u64 a6 = 0, u64 a7 = 0,
               const char* what = nullptr);

// Walk the current thread's guest frame-pointer chain (diagnostics).
void jit_backtrace_here(const char* why);

// Dump every guest thread's PC/LR/stack (diagnostics).
void jit_dump_threads();

// Guest stack management for new threads.
u64 guest_new_thread_stack(u64 size = 0x100000); // 1 MiB default; returns SP (top)

} // namespace sjf
