// profile_edit.cpp — save editor that lets the GAME write the save.
//
// profile0.dat carries a CRC32 computed field by field (PlayerState::updateCRC,
// SynchronizedPlayerState::updateCRC, ChaoState::updateCRC ...). Editing the
// file directly makes the game discard the whole profile (hito 8). Instead we
// call the game's own PlayerProfile setters on the live profile object and
// then PlayerProfile::save(), so the game computes a valid CRC itself.
//
// File format (--profile-edit FILE), one command per line, '#' = comment:
//   rings N            set ring count        (addRings(N - getRings()))
//   redrings N         set red star rings    (addRedStarRings(N - getRedStarRings()))
//   energy N           setEnergyCount(N)
//   unlock NAME|all    setCharacterLocked(c, false)
//   lock NAME          setCharacterLocked(c, true)
//   booster I N        setBoosterCount(I, N)          I = 0..6
//   select NAME        setLastSelectedCharacter(c)    (character shown first)
//   exit               quit after saving (used by the launcher's "Aplicar ahora")
// Enum orders were decoded from the jump tables of setCharacterLocked
// (0x32ce28) and setBoosterCount (0x32b83c); see docs/11.
//
// Applied once, on the game thread (from ALooper_pollAll, i.e. between frames),
// about 1.5 s after the frontend music starts (profile loaded, Home shown).
#include "sjfport/common.h"
#include "sjfport/elf_loader.h"
#include "sjfport/guest_abi.h"
#include "sjfport/runtime.h"
#include "sjfport/host_compat.h"

#include <atomic>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace sjf {

namespace {
struct Cmd { std::string op; std::string a; int b = 0; };
std::vector<Cmd> g_cmds;
std::atomic<bool> g_armed{false};
std::atomic<bool> g_done{false};
std::atomic<u64> g_frontend_ms{0};
bool g_exit_after = false;

const char* kChars[] = {"sonic", "tails", "knuckles", "amy", "blaze",
                        "shadow", "vector", "silver", "rouge", "cream"};
constexpr int kNumChars = 10;
constexpr int kNumBoosters = 7;

int char_index(const std::string& n) {
    for (int i = 0; i < kNumChars; ++i)
        if (n == kChars[i])
            return i;
    return -1;
}

u64 sym(const char* name) {
    LoadedElf* e = global_loaded_elf();
    return e ? elf_find_symbol(*e, name) : 0;
}

i32 as_i32(u64 v) { return (i32)(u32)v; }
} // namespace

bool profile_edit_load(const std::string& path) {
    std::ifstream f(path);
    if (!f) {
        LOGE("profile-edit: cannot open %s", path.c_str());
        return false;
    }
    std::string line;
    while (std::getline(f, line)) {
        auto h = line.find('#');
        if (h != std::string::npos)
            line.resize(h);
        std::istringstream ss(line);
        Cmd c;
        if (!(ss >> c.op))
            continue;
        if (c.op == "exit") { g_exit_after = true; continue; }
        if (c.op == "rings" || c.op == "redrings" || c.op == "energy") {
            if (!(ss >> c.b)) continue;
        } else if (c.op == "unlock" || c.op == "lock" || c.op == "select") {
            if (!(ss >> c.a)) continue;
        } else if (c.op == "booster") {
            if (!(ss >> c.a >> c.b)) continue;
        } else {
            LOGW("profile-edit: unknown command '%s'", c.op.c_str());
            continue;
        }
        g_cmds.push_back(c);
    }
    LOGI("profile-edit: %zu command(s) loaded from %s%s", g_cmds.size(), path.c_str(),
         g_exit_after ? " (exit after save)" : "");
    g_armed = !g_cmds.empty() || g_exit_after;
    return true;
}

void profile_edit_notify_frontend() {
    if (g_armed && g_frontend_ms.load() == 0)
        g_frontend_ms = host_ticks_ms();
}

// Called from ALooper_pollAll on the game thread.
void profile_edit_poll() {
    if (!g_armed || g_done)
        return;
    u64 t = g_frontend_ms.load();
    if (t == 0 || host_ticks_ms() - t < 1500)
        return;
    g_done = true;

    u64 gp = sym("_ZN6Global13playerProfileE");
    u64 prof = 0;
    if (gp)
        gread(&prof, gp, 8);
    const u64 f_save = sym("_ZN13PlayerProfile4saveEv");
    const u64 f_get_rings = sym("_ZNK13PlayerProfile8getRingsEv");
    const u64 f_add_rings = sym("_ZN13PlayerProfile8addRingsEi");
    const u64 f_get_red = sym("_ZNK13PlayerProfile15getRedStarRingsEv");
    const u64 f_add_red = sym("_ZN13PlayerProfile15addRedStarRingsEi");
    const u64 f_energy = sym("_ZN13PlayerProfile14setEnergyCountEi");
    const u64 f_lock = sym("_ZN13PlayerProfile18setCharacterLockedEN9Character4EnumEb");
    const u64 f_boost = sym("_ZN13PlayerProfile15setBoosterCountEN20BoosterSpecification4EnumEi");
    const u64 f_select = sym("_ZN13PlayerProfile24setLastSelectedCharacterEN9Character4EnumE");
    if (!prof || !f_save || !f_get_rings || !f_add_rings || !f_get_red || !f_add_red ||
        !f_energy || !f_lock || !f_boost) {
        LOGE("profile-edit: profile/symbols not found (profile=0x%llx) - nothing changed",
             (unsigned long long)prof);
        if (g_exit_after) request_quit();
        return;
    }
    int applied = 0;
    for (const Cmd& c : g_cmds) {
        if (c.op == "rings" || c.op == "redrings") {
            bool red = c.op == "redrings";
            int target = c.b < 0 ? 0 : c.b;
            int cur = as_i32(guest_call_nested(red ? f_get_red : f_get_rings, prof));
            guest_call_nested(red ? f_add_red : f_add_rings, prof, (u64)(u32)(target - cur));
            int now = as_i32(guest_call_nested(red ? f_get_red : f_get_rings, prof));
            LOGI("profile-edit: %s %d -> %d", c.op.c_str(), cur, now);
            ++applied;
        } else if (c.op == "energy") {
            guest_call_nested(f_energy, prof, (u64)(u32)(c.b < 0 ? 0 : c.b));
            LOGI("profile-edit: energy -> %d", c.b);
            ++applied;
        } else if (c.op == "unlock" || c.op == "lock") {
            bool lock = c.op == "lock";
            for (int i = 0; i < kNumChars; ++i) {
                if (c.a != "all" && c.a != kChars[i])
                    continue;
                if (lock && i == 0)
                    continue; // never lock Sonic (the default character)
                guest_call_nested(f_lock, prof, (u64)i, lock ? 1 : 0);
                LOGI("profile-edit: %s %s", c.op.c_str(), kChars[i]);
                ++applied;
            }
            if (c.a != "all" && char_index(c.a) < 0)
                LOGW("profile-edit: unknown character '%s'", c.a.c_str());
        } else if (c.op == "select") {
            int ci = char_index(c.a);
            if (ci < 0 || !f_select) {
                LOGW("profile-edit: cannot select '%s'", c.a.c_str());
                continue;
            }
            guest_call_nested(f_select, prof, (u64)ci);
            LOGI("profile-edit: select %s", kChars[ci]);
            ++applied;
        } else if (c.op == "booster") {
            int idx = std::atoi(c.a.c_str());
            if (idx < 0 || idx >= kNumBoosters) {
                LOGW("profile-edit: booster index %d out of range 0..6", idx);
                continue;
            }
            guest_call_nested(f_boost, prof, (u64)idx, (u64)(u32)(c.b < 0 ? 0 : c.b));
            LOGI("profile-edit: booster %d -> %d", idx, c.b);
            ++applied;
        }
    }
    guest_call_nested(f_save, prof);
    LOGI("profile-edit: %d change(s) applied, PlayerProfile::save() done", applied);
    if (g_exit_after)
        request_quit();
}

} // namespace sjf
