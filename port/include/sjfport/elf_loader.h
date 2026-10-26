// sjfport — ELF64 loader for the guest .so
#pragma once
#include "common.h"
#include <map>
#include <string>
#include <vector>

namespace sjf {

struct LoadedElf {
    u64 base = 0;                 // guest load base
    u64 entry = 0;                // DT_ENTRY (unused for .so)
    std::vector<u64> init_array;  // guest addresses of init functions
    u64 init_fn = 0;              // DT_INIT if present
    std::map<std::string, u64> exports;  // name -> guest address
    u64 symtab_guest = 0;         // .dynsym in guest memory
    u64 symcount = 0;
    u64 strtab_guest = 0;
    u64 image_end = 0;            // highest mapped address + 1
    std::map<std::string, u64> bound_imports;  // name -> trampoline/data
    std::vector<std::string> unresolved;       // imports with no handler
};

// Load `path` at kGuestBase and apply relocations. Returns false on fatal
// parse errors. `so_name` is used for logging.
bool elf_load(const std::string& path, const std::string& so_name, LoadedElf& out);

// Symbol lookup helper over the loaded image (mangled or plain names).
u64 elf_find_symbol(const LoadedElf& elf, const std::string& name);

// Global image accessor (used by libdl's dlsym).
LoadedElf* global_loaded_elf();
void set_global_loaded_elf(LoadedElf* elf);

} // namespace sjf
