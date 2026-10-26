// Host function registry: binds guest imports to native handlers through
// svc-trampolines (see guest_memory.h).
#include "sjfport/host_calls.h"
#include "sjfport/guest_memory.h"
#include <map>
#include <mutex>

namespace sjf {

namespace {
struct Entry {
    HostFn fn;
    u64 trampoline = 0;
};
std::map<std::string, Entry> g_entries;
std::map<u16, HostFn*> g_by_imm;   // svc imm -> handler
std::mutex g_mutex;
u16 g_next_imm = 1;                // 0 reserved
} // namespace

u64 register_host_fn(const std::string& name, HostFn fn) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_entries.find(name);
    if (it != g_entries.end()) {
        it->second.fn = std::move(fn);
        return it->second.trampoline;
    }
    u16 imm = g_next_imm++;
    u64 tramp = register_trampoline(imm, name);
    if (!tramp) {
        LOGE("register_host_fn: no trampoline for %s", name.c_str());
        return 0;
    }
    Entry e;
    e.fn = std::move(fn);
    e.trampoline = tramp;
    g_by_imm[imm] = &g_entries[name].fn;
    g_entries[name] = std::move(e);
    // refresh pointer (map node address stable? std::map nodes are stable)
    g_by_imm[imm] = &g_entries[name].fn;
    return tramp;
}

const HostFn* find_host_fn(const std::string& name) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_entries.find(name);
    return it == g_entries.end() ? nullptr : &it->second.fn;
}

u64 trampoline_for(const std::string& name) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_entries.find(name);
    return it == g_entries.end() ? 0 : it->second.trampoline;
}

const std::string& name_for_trampoline(u64 gaddr) {
    return trampoline_name(gaddr);
}

HostFn* dispatch_by_imm(u16 imm) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_by_imm.find(imm);
    return it == g_by_imm.end() ? nullptr : it->second;
}

HostFn* host_fn_for_svc_imm(u16 imm) { return dispatch_by_imm(imm); }

} // namespace sjf
