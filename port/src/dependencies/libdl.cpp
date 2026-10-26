// Host module: libdl
#include "sjfport/guest_abi.h"
#include "sjfport/host_calls.h"
#include "sjfport/elf_loader.h"

namespace sjf {

LoadedElf* g_loaded_elf = nullptr;  // set by engine boot

void register_libdl_module() {
    register_host_fn("dlopen", [](GuestCall& c) {
        std::string name = gstr(c.x[0]);
        LOGI("dlopen(\"%s\") -> self handle", name.c_str());
        c.ret = (u64)0xDEADBEEF; // opaque non-null handle
    });
    register_host_fn("dlsym", [](GuestCall& c) {
        std::string name = gstr(c.x[1]);
        u64 addr = 0;
        if (LoadedElf* elf = global_loaded_elf())
            addr = elf_find_symbol(*elf, name);
        if (!addr)
            addr = trampoline_for(name);
        LOGD("dlsym(\"%s\") -> 0x%llx", name.c_str(), (unsigned long long)addr);
        c.ret = addr;
    });
    register_host_fn("dlclose", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("dl_iterate_phdr", [](GuestCall& c) {
        LOGD("dl_iterate_phdr() -> 0 (no phdrs reported)");
        c.ret = 0;
    });
}

} // namespace sjf
