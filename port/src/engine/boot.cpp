// sjfport — engine boot: load the .so, run initialisers, JNI_OnLoad and
// ANativeActivity_onCreate, then walk the lifecycle.
#include "sjfport/elf_loader.h"
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/jni_env.h"
#include "sjfport/platform.h"
#include "sjfport/runtime.h"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <cstdio>
#include <vector>

namespace sjf {

// ---------------------------------------------------------------------------
// android/native_activity.h layout (ABI-stable)
// ---------------------------------------------------------------------------
struct ANativeActivity;

struct ANativeActivityCallbacks {
    void (*onStart)(ANativeActivity*);
    void (*onResume)(ANativeActivity*);
    void (*onSaveInstanceState)(ANativeActivity*, void*, size_t);
    void (*onPause)(ANativeActivity*);
    void (*onStop)(ANativeActivity*);
    void (*onDestroy)(ANativeActivity*);
    void (*onWindowFocusChanged)(ANativeActivity*, int);
    void (*onNativeWindowCreated)(ANativeActivity*, void*);
    void (*onNativeWindowResized)(ANativeActivity*, void*);
    void (*onNativeWindowRedrawNeeded)(ANativeActivity*, void*);
    void (*onNativeWindowDestroyed)(ANativeActivity*, void*);
    void (*onInputQueueCreated)(ANativeActivity*, void*);
    void (*onInputQueueDestroyed)(ANativeActivity*, void*);
    void (*onContentRectChanged)(ANativeActivity*, const void*);
    void (*onConfigurationChanged)(ANativeActivity*);
    void (*onLowMemory)(ANativeActivity*);
};

struct ANativeActivity {
    ANativeActivityCallbacks* callbacks;
    void* vm;
    void* env;
    void* clazz;
    const char* internalDataPath;
    const char* externalDataPath;
    int32_t sdkVersion;
    void* instance;
    void* assetManager;
    const char* obbPath;
};

namespace {
std::atomic<bool> g_quit{false};
} // namespace

void request_quit() { g_quit = true; }

namespace {
std::string g_default_zone;

// AppLoadingScreen::update, branch taken when localsettings.currentZone is
// empty (always, offline): it builds the zone name from the literal
// "green_hill_zone" (@0x51a748) with
//     0x3c8c6c  adrp x1, 0x51a000
//     0x3c8c78  add  x2, x1, #0x748      (strlen loop)
//     0x3c8c8c  add  x1, x1, #0x748      (RangeInitialize)
// and calls LevelResources::setZone(). Re-target those three instructions
// at another zone literal that already exists in .rodata. The literal
// itself is untouched (it is also referenced from 0x1d21b0).
bool patch_default_zone(const std::string& zone) {
    struct Z { const char* name; u64 addr; };
    static const Z zones[] = {{"green_hill_zone", 0x51a748}, {"blue_sky_zone", 0x51b690},
                              {"jungle_zone", 0x51b670}, {"mechanical_zone", 0x51b6b0}};
    const Z* z = nullptr;
    for (const Z& c : zones)
        if (zone == c.name) z = &c;
    if (!z) {
        LOGW("zone: unknown zone '%s' (green_hill_zone, blue_sky_zone, jungle_zone, "
             "mechanical_zone)", zone.c_str());
        return false;
    }
    const u64 base = 0x100000000ull, pc_adrp = 0x3c8c6c, pc_add1 = 0x3c8c78, pc_add2 = 0x3c8c8c;
    u32 w_adrp = 0, w_add1 = 0, w_add2 = 0;
    gread(&w_adrp, base + pc_adrp, 4);
    gread(&w_add1, base + pc_add1, 4);
    gread(&w_add2, base + pc_add2, 4);
    // Expected original encodings (Sonic Jump Fever 1.6.1 arm64)
    if (w_adrp != 0xd0000a81u || w_add1 != 0x911d2022u || w_add2 != 0x911d2021u) {
        LOGW("zone: unexpected code at 0x3c8c6c (%08x %08x %08x) - not 1.6.1? zone not changed",
             w_adrp, w_add1, w_add2);
        return false;
    }
    const u64 page = z->addr & ~0xfffull, off = z->addr & 0xfff;
    const i64 delta = (i64)(page - (pc_adrp & ~0xfffull)) >> 12;
    const u32 immlo = (u32)delta & 3, immhi = ((u32)(delta >> 2)) & 0x7ffff;
    const u32 n_adrp = 0x90000000u | (immlo << 29) | (immhi << 5) | (w_adrp & 31);
    const u32 n_add1 = (w_add1 & ~(0xfffu << 10)) | ((u32)off << 10);
    const u32 n_add2 = (w_add2 & ~(0xfffu << 10)) | ((u32)off << 10);
    gwrite(base + pc_adrp, &n_adrp, 4);
    gwrite(base + pc_add1, &n_add1, 4);
    gwrite(base + pc_add2, &n_add2, 4);
    LOGI("zone: default zone -> %s", z->name);
    return true;
}
// sl::AnimationSet::getAnimation(HashString) aborts with "Unable to find
// animation %x" when a hash is missing. Optional safety net (--anim-fallback):
// return the set's root animation instead of slFatalError (a wrong sprite
// instead of a crash), in case some content really is missing.
//   0x2f3344  ldr  x4, [x6, #0x10]   ; root node ([set+0x30])
//   0x2f3348  cbz  x4, 0x2f3350      ; empty set -> return NULL (original path)
//   0x2f334c  b    0x2f3338          ; -> ldr x0, [x4, #0x28]; ret
bool g_anim_fallback = false;
bool g_extra_chars = true;

u32 fnv1(const char* s) {
    u32 h = 0x811c9dc5u;
    for (; *s; ++s) h = (h * 0x01000193u) ^ (u8)*s;
    return h;
}

// Character::isAvailable(Enum) @0x3a35a4 returns 0 outright for Vector (6),
// Rouge (8) and Cream (9):
//   0x3a35d8  b.ls  0x3a3618     ; enum <= 5 -> availability checks
//   0x3a35dc  cmp   w20, #7      ; Silver -> checks, everything else -> 0
// Make the first branch unconditional so 6/8/9 take the same path as the
// released characters (a "<name>::enabled" online setting, absent offline).
bool patch_extra_characters() {
    const u64 base = 0x100000000ull, pc = 0x3a35d8;
    u32 w = 0;
    gread(&w, base + pc, 4);
    if (w != 0x54000209u) {
        LOGW("extra-chars: unexpected code at 0x3a35d8 (%08x) - not applied", w);
        return false;
    }
    const u32 b = 0x14000010u; // b 0x3a3618
    gwrite(base + pc, &b, 4);
    LOGI("extra-chars: Vector, Rouge and Cream are now available characters");
    return true;
}

// sl::AnimationSet::getAnimation(HashString) aborts on a missing hash. The
// unreleased characters ask for animations that no shipped sprite set has
// (Cream: Player_Fly/Player_FlytoFall), so route the miss path through a code
// cave that retries with an alias (Fly -> Jump ...). With --anim-fallback a
// remaining miss returns the set's root animation instead of aborting.
// Cave source: docs/12 (assembled with zig cc -target aarch64-linux-gnu).
bool patch_anim_alias_cave(bool fallback) {
    const u64 base = 0x100000000ull;
    u32 w[4] = {};
    gread(w, base + 0x2f3344, 16);
    if (w[0] != 0xd00010e0u || w[1] != 0x91280000u || w[2] != 0x94001c5au || w[3] != 0xd2800000u) {
        LOGW("anim-alias: unexpected code at 0x2f3344 - not applied");
        return false;
    }
    static const u32 code[32] = {
        0x10000402u, 0x28c11043u, 0x340000e3u, 0x6b03003fu, 0x54ffffa1u, 0x2a0403e1u, 0xf94008c0u,
        0x580001f0u, 0xd61f0200u, 0x180002a5u, 0x340000c5u, 0xf94008c4u, 0xb4000084u, 0xf9401480u,
        0x58000150u, 0xd61f0200u, 0x58000140u, 0x58000170u, 0xd63f0200u, 0xd2800000u, 0x58000090u,
        0xd61f0200u, 0x002f32f8u, 0x00000001u, 0x002f333cu, 0x00000001u, 0x00511a00u, 0x00000001u,
        0x002fa4b4u, 0x00000001u, 0x00000000u, 0xd503201fu};
    static const char* const alias[][2] = {
        {"Player_Fly", "Player_Jump"},          {"Player_FlytoFall", "Player_JumpToFall"},
        {"Player_Hover", "Player_Jump"},        {"Player_HovertoFall", "Player_JumpToFall"},
        {"Player_Attack", "Player_Jump"},       {"Player_AttackToFall", "Player_JumpToFall"},
        {"Player_LevelUp", "Player_Complete"}};
    const size_t n = sizeof(alias) / sizeof(alias[0]);
    const u64 cave = alloc_native_data(sizeof(code) + (n + 1) * 8, 16);
    if (!cave) return false;
    u32 buf[32];
    std::memcpy(buf, code, sizeof code);
    buf[30] = fallback ? 1u : 0u; // flag_fallback
    gwrite(cave, buf, sizeof buf);
    for (size_t i = 0; i <= n; ++i) {
        u32 pair[2] = {0, 0};
        if (i < n) { pair[0] = fnv1(alias[i][0]); pair[1] = fnv1(alias[i][1]); }
        gwrite(cave + sizeof code + i * 8, pair, 8);
    }
    const u32 jump[4] = {0x58000050u /* ldr x16, #8 */, 0xd61f0200u /* br x16 */, (u32)cave,
                         (u32)(cave >> 32)};
    gwrite(base + 0x2f3344, jump, 16);
    LOGI("anim-alias: %zu animation aliases installed (cave 0x%llx)%s", n, (unsigned long long)cave,
         fallback ? ", fallback to root on other misses" : "");
    return true;
}

bool patch_missing_anim_fallback() {
    const u64 base = 0x100000000ull;
    u32 w[3] = {};
    gread(w, base + 0x2f3344, 12);
    if (w[0] != 0xd00010e0u || w[1] != 0x91280000u || w[2] != 0x94001c5au) {
        LOGW("anim-fallback: unexpected code at 0x2f3344 - not applied");
        return false;
    }
    const u32 n[3] = {0xF94008C4u, 0xB4000044u, 0x17FFFFFBu};
    gwrite(base + 0x2f3344, n, 12);
    LOGI("anim-fallback: missing animations use the set's first one (no abort)");
    return true;
}
} // namespace

void set_default_zone(const std::string& zone) { g_default_zone = zone; }
void set_anim_fallback(bool on) { g_anim_fallback = on; }
void set_extra_chars(bool on) { g_extra_chars = on; }
bool extra_chars_enabled() { return g_extra_chars; }

// Sprite/sound donors for the characters whose packages were never released.
// Chosen for the animations their code asks for: Vector -> Knuckles (has
// Player_Attack), Rouge -> Silver (has Player_Hover/HovertoFall), Cream -> Amy.
// SJF_CHAR_DONORS="cream=tails,rouge=shadow" overrides. A real package placed
// in game/assets (e.g. hd-player_cream.sla, made by the launcher) wins.
std::string extra_char_donor_name(const std::string& bare) {
    if (!g_extra_chars) return std::string();
    static const char* const prefixes[] = {"player_", "playerextra_", "sfx_"};
    static std::string donors[3] = {"knuckles", "silver", "amy"}; // vector, rouge, cream
    static bool init = false;
    if (!init) {
        init = true;
        if (const char* e = std::getenv("SJF_CHAR_DONORS")) {
            std::string s = e;
            size_t p = 0;
            while (p < s.size()) {
                size_t c = s.find(',', p);
                std::string kv = s.substr(p, c == std::string::npos ? std::string::npos : c - p);
                size_t eq = kv.find('=');
                if (eq != std::string::npos) {
                    std::string k = kv.substr(0, eq), v = kv.substr(eq + 1);
                    if (k == "vector") donors[0] = v;
                    if (k == "rouge") donors[1] = v;
                    if (k == "cream") donors[2] = v;
                }
                if (c == std::string::npos) break;
                p = c + 1;
            }
        }
    }
    static const char* const chars[] = {"vector", "rouge", "cream"};
    for (const char* pre : prefixes)
        for (int i = 0; i < 3; ++i)
            if (bare == std::string(pre) + chars[i] + ".sla")
                return std::string(pre) + donors[i] + ".sla";
    return std::string();
}
bool quit_requested() { return g_quit.load(); }

namespace {

u64 alloc_guest_string(const std::string& s) {
    u64 g = alloc_native_data(s.size() + 1, 8);
    if (g)
        gwrite(g, s.c_str(), s.size() + 1);
    return g;
}

void log_callbacks(u64 callbacks_guest) {
    auto* cb = reinterpret_cast<ANativeActivityCallbacks*>(guest_to_host(callbacks_guest));
    if (!cb) {
        LOGE("boot: callbacks not mapped");
        return;
    }
    struct { const char* name; size_t off; } fields[] = {
        {"onStart", 0}, {"onResume", 1}, {"onSaveInstanceState", 2}, {"onPause", 3},
        {"onStop", 4}, {"onDestroy", 5}, {"onWindowFocusChanged", 6},
        {"onNativeWindowCreated", 7}, {"onNativeWindowResized", 8},
        {"onNativeWindowRedrawNeeded", 9}, {"onNativeWindowDestroyed", 10},
        {"onInputQueueCreated", 11}, {"onInputQueueDestroyed", 12},
        {"onContentRectChanged", 13}, {"onConfigurationChanged", 14}, {"onLowMemory", 15}};
    void** slots = reinterpret_cast<void**>(cb);
    LOGI("boot: ANativeActivity callbacks installed by the guest:");
    for (auto& f : fields) {
        void* p = slots[f.off];
        LOGI("    %-28s %s 0x%llx", f.name, p ? "->" : "--", (unsigned long long)(u64)p);
    }
}

} // namespace

bool boot(const std::string& so_path) {
    LOGI("=== sjfport boot: %s ===", so_path.c_str());
    if (!guest_memory_init()) {
        LOGE("boot: guest memory init failed");
        return false;
    }

    // 1) native modules
    register_libc_module();
    register_libm_module();
    register_pthread_module();
    register_liblog_module();
    register_libdl_module();
    register_libandroid_module();
    register_libEGL_module();
    register_libGLESv2_module();
    register_libOpenSLES_module();
    LOGI("boot: %zu host functions registered", (size_t)0); // count logged by loader

    // 2) load the image
    static LoadedElf elf;
    if (!elf_load(so_path, "libsonicjumpfever.so", elf)) {
        LOGE("boot: ELF load failed");
        return false;
    }
    set_global_loaded_elf(&elf);
    if (g_default_zone.empty())
        if (const char* ez = std::getenv("SJF_ZONE"))
            g_default_zone = ez;
    if (!g_default_zone.empty())
        patch_default_zone(g_default_zone); // before any guest code is translated
    if (std::getenv("SJF_ANIM_FALLBACK"))
        g_anim_fallback = true;
    // Safety net only (opt-in): the "missing" zone animations/effects turned out
    // to be a printf bug (%.2d ignored the precision), fixed in guest_abi.cpp.
    if (std::getenv("SJF_NO_EXTRA_CHARS"))
        g_extra_chars = false;
    if (g_extra_chars) {
        patch_extra_characters();
        patch_anim_alias_cave(g_anim_fallback); // includes the --anim-fallback behaviour
    } else if (g_anim_fallback) {
        patch_missing_anim_fallback();
    }

    // __sF (bionic stdio globals) -> std streams
    {
        auto it = elf.bound_imports.find("__sF");
        if (it != elf.bound_imports.end())
            libc_bind_sF(it->second);
    }

    // 3) JNI
    if (!jni_env_init()) {
        LOGE("boot: JNI init failed");
        return false;
    }

    // Probe: verify the GOT slot / PlayerProfile singleton mapping.
    if (debug_mode()) {
        u64 got = 0, first = 0, second = 0;
        gread(&got, 0x1005bd130ull, 8);
        if (got) {
            gread(&first, got, 8);
            if (first)
                gread(&second, first + 0xb80, 8);
        }
        LOGI("probe: GOT[0x5bd130]=0x%llx *obj=0x%llx [obj+0xb80]=0x%llx",
             (unsigned long long)got, (unsigned long long)first, (unsigned long long)second);
    }

    // Create the engine's lazy singletons with their REAL constructors.
    // On Android, initGame()/first use creates them; in our shim the worker
    // thread reaches DownloadManager::update() before that happens and spins
    // forever on a zeroed intrusive list. Use the engine's own ctors.
    {
        struct Mgr { const char* ctor_sym; u64 slot; };
        const Mgr mgrs[] = {
            {"_ZN2sl11HttpManagerC1Ev", 0x1005c3628ull},
            {"_ZN7network15DownloadManagerC1Ev", 0x100603220ull},
        };
        for (const Mgr& m : mgrs) {
            u64 ctor = elf_find_symbol(elf, m.ctor_sym);
            u64 existing = 0;
            gread(&existing, m.slot, 8);
            if (!ctor) {
                LOGW("boot: singleton ctor missing: %s", m.ctor_sym);
                continue;
            }
            if (existing) {
                LOGI("boot: singleton %s already created (0x%llx)", m.ctor_sym,
                     (unsigned long long)existing);
                continue;
            }
            u64 blk = alloc_native_data(0x8000, 16);
            if (!blk)
                continue;
            guest_call(ctor, blk, 0, 0, 0, 0, 0, 0, 0, "singleton ctor");
            gwrite(m.slot, &blk, 8);
            LOGI("boot: created singleton %s -> 0x%llx", m.ctor_sym,
                 (unsigned long long)blk);
        }
    }

    // 4) initialisers (.init_array)
    LOGI("boot: running %zu init_array functions", elf.init_array.size());
    for (size_t i = 0; i < elf.init_array.size(); ++i) {
        u64 fn = elf.init_array[i];
        if (!fn)
            continue;
        LOGD("boot: init_array[%zu] = 0x%llx", i, (unsigned long long)fn);
        guest_call(fn, 0, 0, 0, 0, 0, 0, 0, 0, "init_array");
    }
    if (elf.init_fn) {
        LOGI("boot: DT_INIT");
        guest_call(elf.init_fn, 0, 0, 0, 0, 0, 0, 0, 0, "DT_INIT");
    }
    LOGI("boot: initialisers done");

    // 5) JNI_OnLoad
    u64 onload = elf_find_symbol(elf, "JNI_OnLoad");
    if (onload) {
        LOGI("boot: JNI_OnLoad(0x%llx)", (unsigned long long)onload);
        u64 r = guest_call(onload, jni_vm_guest(), 0, 0, 0, 0, 0, 0, 0, "JNI_OnLoad");
        LOGI("boot: JNI_OnLoad returned %d (0x%x = JNI 1.x)", (int)r, (unsigned)r);
    } else {
        LOGW("boot: no JNI_OnLoad export");
    }

    // 6) ANativeActivity_onCreate
    u64 oncreate = elf_find_symbol(elf, "ANativeActivity_onCreate");
    if (!oncreate) {
        LOGE("boot: no ANativeActivity_onCreate export");
        return false;
    }

    u64 callbacks = alloc_native_data(sizeof(ANativeActivityCallbacks), 8);
    u64 activity = alloc_native_data(sizeof(ANativeActivity), 8);
    u64 data_path = alloc_guest_string("game/data");
    u64 clazz = alloc_native_data(16, 8);
    u64 asset_manager = alloc_native_data(64, 8);
    u64 obb = alloc_guest_string("game/base.apk");

    // zero callbacks; the guest fills them in
    {
        auto* cb = reinterpret_cast<ANativeActivityCallbacks*>(guest_to_host(callbacks));
        std::memset(cb, 0, sizeof(*cb));
        auto* act = reinterpret_cast<ANativeActivity*>(guest_to_host(activity));
        act->callbacks = reinterpret_cast<ANativeActivityCallbacks*>(callbacks);
        act->vm = reinterpret_cast<void*>(jni_vm_guest());
        act->env = reinterpret_cast<void*>(jni_env_guest());
        act->clazz = reinterpret_cast<void*>(clazz);
        act->internalDataPath = reinterpret_cast<const char*>(data_path);
        act->externalDataPath = reinterpret_cast<const char*>(data_path);
        act->sdkVersion = 21;
        act->instance = nullptr;
        act->assetManager = reinterpret_cast<void*>(asset_manager);
        act->obbPath = reinterpret_cast<const char*>(obb);
    }

    // Create the window before onCreate so a surface exists when the engine's
    // worker thread starts processing lifecycle commands (avoids a race).
    platform_create_window(platform_surface_w(), platform_surface_h());

    LOGI("boot: ANativeActivity_onCreate(activity=0x%llx)", (unsigned long long)activity);
    guest_call(oncreate, activity, 0, 0, 0, 0, 0, 0, 0, "ANativeActivity_onCreate");
    LOGI("boot: ANativeActivity_onCreate returned");
    {
        auto* act = reinterpret_cast<ANativeActivity*>(guest_to_host(activity));
        LOGI("boot: activity state after onCreate: instance=0x%llx clazz=0x%llx "
             "vm=0x%llx env=0x%llx am=0x%llx",
             (unsigned long long)(u64)act->instance, (unsigned long long)(u64)act->clazz,
             (unsigned long long)(u64)act->vm, (unsigned long long)(u64)act->env,
             (unsigned long long)(u64)act->assetManager);
    }
    log_callbacks(callbacks);

    // Scaffold: the PlayerProfile/ConnectedProfileManager static instance
    // (holder at 0x5cbed0) is never initialised by the paths we can reach.
    // Provide a zeroed impl so the engine's per-frame managers survive:
    //   triggerStartCount: [impl+0xb80] -> counter block (+0xb8)
    //   getServerTime:     [impl+0xb78] -> server-time block (+0x78)
    {
        u64 y = alloc_native_data(0x400, 16);
        u64 x = alloc_native_data(0x2000, 16);
        if (x && y) {
            gwrite(x + 0xb78, &y, 8);
            gwrite(x + 0xb80, &y, 8);
            gwrite(0x1005cbed0ull, &x, 8);
            LOGW("boot: scaffolded profile impl=0x%llx data=0x%llx",
                 (unsigned long long)x, (unsigned long long)y);
        }
    }

    // Deliver the native window immediately after onCreate.
    {
        u64 nw = alloc_native_data(32, 8);
        auto* cbx = reinterpret_cast<ANativeActivityCallbacks*>(guest_to_host(callbacks));
        if (cbx && cbx->onNativeWindowCreated) {
            LOGI("boot: -> callbacks->onNativeWindowCreated (early)");
            guest_call((u64)cbx->onNativeWindowCreated, activity, nw, 0, 0, 0, 0, 0, 0,
                       "onNativeWindowCreated");
            LOGI("boot: onNativeWindowCreated (early) returned");
        }
    }

    // 7) lifecycle probe: onStart + onResume
    auto* cb = reinterpret_cast<ANativeActivityCallbacks*>(guest_to_host(callbacks));
    if (cb && cb->onStart) {
        LOGI("boot: -> callbacks->onStart");
        guest_call((u64)cb->onStart, activity, 0, 0, 0, 0, 0, 0, 0, "onStart");
        LOGI("boot: onStart returned");
    }
    if (cb && cb->onResume) {
        LOGI("boot: -> callbacks->onResume");
        guest_call((u64)cb->onResume, activity, 0, 0, 0, 0, 0, 0, 0, "onResume");
        LOGI("boot: onResume returned");
    }
    if (cb && cb->onWindowFocusChanged) {
        LOGI("boot: -> callbacks->onWindowFocusChanged(1)");
        guest_call((u64)cb->onWindowFocusChanged, activity, 1, 0, 0, 0, 0, 0, 0,
                   "onWindowFocusChanged");
        LOGI("boot: onWindowFocusChanged returned");
    }
    if (cb && cb->onInputQueueCreated) {
        // Opaque AInputQueue*: the guest only hands it back to AInputQueue_*.
        u64 queue = alloc_native_data(32, 8);
        LOGI("boot: -> callbacks->onInputQueueCreated(queue=0x%llx)", (unsigned long long)queue);
        guest_call((u64)cb->onInputQueueCreated, activity, queue, 0, 0, 0, 0, 0, 0,
                   "onInputQueueCreated");
        LOGI("boot: onInputQueueCreated returned");
    }

    // ---------- frame loop ----------
    LOGI("boot: entering frame loop (close the window or wait for the watchdog)");
    auto t0 = std::chrono::steady_clock::now();
    auto last_sample = t0;
    // Test hook: SJF_AUTOTAP_MS=<interval> taps the screen centre periodically
    // (lets automated runs get past "tap to continue" screens).
    const char* autotap_env = std::getenv("SJF_AUTOTAP_MS");
    const long autotap_ms = autotap_env ? std::atol(autotap_env) : 0;
    auto last_tap = t0;
    // Test hook: SJF_TAPS="<ms>:<x>,<y>;<ms>:<x>,<y>;..." taps exact window
    // coordinates at the given times (ms since the frame loop started).
    struct ScriptTap { long ms; float x, y; int stage; }; // stage 0=pending 1=down 2=done
    std::vector<ScriptTap> taps;
    if (const char* ts = std::getenv("SJF_TAPS")) {
        std::string s = ts;
        size_t p = 0;
        while (p < s.size()) {
            size_t e = s.find(';', p);
            if (e == std::string::npos) e = s.size();
            long ms = 0; float x = 0, y = 0;
            if (std::sscanf(s.substr(p, e - p).c_str(), "%ld:%f,%f", &ms, &x, &y) == 3)
                taps.push_back({ms, x, y, 0});
            p = e + 1;
        }
        LOGI("boot: %zu scripted taps loaded", taps.size());
    }
    // Test hook: SJF_TILT="<ms>:<ax>;..." holds accelerometer X (m/s^2, Android
    // convention: negative = device tilted right) from each time stamp on.
    std::vector<std::pair<long, float>> tilts;
    if (const char* ts = std::getenv("SJF_TILT")) {
        std::string s = ts;
        size_t p = 0;
        while (p < s.size()) {
            size_t e = s.find(';', p);
            if (e == std::string::npos) e = s.size();
            long ms = 0; float ax = 0;
            if (std::sscanf(s.substr(p, e - p).c_str(), "%ld:%f", &ms, &ax) == 2)
                tilts.push_back({ms, ax});
            p = e + 1;
        }
        LOGI("boot: %zu scripted tilt steps loaded", tilts.size());
    }
    // Android BACK: the Java side calls Loader.triggerBack(), which only sets the
    // flag android_main polls (-> appSystemBackButtonPressed). Call it directly.
    const u64 trigger_back = elf_find_symbol(elf, "Java_com_sega_sonicjumpfever_Loader_triggerBack");
    for (;;) {
        if (!platform_pump() || quit_requested())
            break;
        if (platform_take_back() && trigger_back) {
            LOGI("input: BACK");
            guest_call(trigger_back, jni_env_guest(), clazz, 0, 0, 0, 0, 0, 0, "triggerBack");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
        auto now = std::chrono::steady_clock::now();
        {
            long el = (long)std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
            {
                const std::pair<long, float>* cur = nullptr;
                for (auto& t : tilts)
                    if (el >= t.first) cur = &t;
                if (cur)
                    input_set_tilt_override(cur->second);
            }
            for (auto& t : taps) {
                if (t.stage == 0 && el >= t.ms) {
                    t.stage = 1;
                    input_push_touch(0, t.x, t.y);
                    LOGI("scripted tap at (%.0f, %.0f) t=%ld ms", t.x, t.y, el);
                } else if (t.stage == 1 && el >= t.ms + 100) {
                    t.stage = 2;
                    input_push_touch(1, t.x, t.y);
                }
            }
        }
        if (autotap_ms > 0 &&
            std::chrono::duration_cast<std::chrono::milliseconds>(now - last_tap).count() >=
                autotap_ms) {
            last_tap = now;
            float cx = platform_width() * 0.5f, cy = platform_height() * 0.5f;
            input_push_touch(0, cx, cy);
            taps.push_back({(long)std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count(),
                            cx, cy, 1}); // UP follows 100 ms later via the script queue
            LOGI("autotap at (%.0f, %.0f)", cx, cy);
        }
        if (debug_mode() &&
            std::chrono::duration_cast<std::chrono::milliseconds>(now - last_sample).count()
            >= 2000) {
            last_sample = now;
            LOGI("--- pc sample ---");
            jit_dump_threads();
            {
                u64 si = 0, pp = 0;
                gread(&si, 0x100603220ull, 8);  // network::DownloadManager::s_instance
                gread(&pp, 0x1005cbed0ull, 8);  // PlayerProfile-ish singleton
                LOGI("probe: DownloadManager::s_instance=0x%llx  profile_obj=0x%llx",
                     (unsigned long long)si, (unsigned long long)pp);
                u64 st = 0, flags = 0, b78 = 0, b80 = 0;
                if (pp) {
                    gread(&st, pp + 0xb88, 8);
                    gread(&b78, pp + 0xb78, 8);
                    gread(&b80, pp + 0xb80, 8);
                    if (st) gread(&flags, st + 0x120, 8);
                }
                {
                    // LevelResources::s_currentZone (eastl::string: begin, end, cap)
                    u64 zb = 0, ze = 0;
                    gread(&zb, 0x100601db8ull, 8);
                    gread(&ze, 0x100601dc0ull, 8);
                    std::string z;
                    if (zb && ze > zb && ze - zb < 64) { z.resize(ze - zb); gread(&z[0], zb, ze - zb); }
                    LOGI("probe: LevelResources::s_currentZone='%s'", z.c_str());
                }
                LOGI("probe: profile+0xb78=0x%llx +0xb80=0x%llx +0xb88=0x%llx flags(+0x120)=0x%llx",
                     (unsigned long long)b78, (unsigned long long)b80, (unsigned long long)st,
                     (unsigned long long)flags);
            }
        }
        // No hard cap: the session ends when the window is closed or the
        // --timeout watchdog fires.
    }
    LOGI("boot: frame loop ended");

    // ---------- shutdown: Android lifecycle so the engine saves ----------
    // appLostFocus() -> PlayerProfile::save() (profile0.dat, localsettings.dat).
    // Each glue callback blocks until the engine thread has handled the command,
    // so run them on a helper thread and give up after a few seconds.
    if (cb) {
        std::atomic<bool> done{false};
        std::thread([&done, cb, activity]() {
            auto call = [&](u64 fn, u64 a1, const char* what) {
                if (!fn) return;
                LOGI("boot: shutdown -> %s", what);
                guest_call(fn, activity, a1, 0, 0, 0, 0, 0, 0, what);
            };
            call((u64)cb->onWindowFocusChanged, 0, "onWindowFocusChanged(0)");
            call((u64)cb->onPause, 0, "onPause");
            if (cb->onSaveInstanceState) {
                u64 out_size = alloc_native_data(8, 8);
                call((u64)cb->onSaveInstanceState, out_size, "onSaveInstanceState");
            }
            call((u64)cb->onStop, 0, "onStop");
            done = true;
        }).detach();
        auto t_end = std::chrono::steady_clock::now() + std::chrono::seconds(6);
        while (!done && std::chrono::steady_clock::now() < t_end) {
            platform_pump(); // keep the window responsive
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        // let the engine thread finish its frame (the save runs on it)
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        LOGI(done ? "boot: shutdown lifecycle complete (profile saved)"
                  : "boot: shutdown lifecycle timed out");
    }
    return true;
}

} // namespace sjf
