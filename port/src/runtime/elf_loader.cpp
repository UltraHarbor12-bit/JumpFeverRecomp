// ELF64 (AArch64 ET_DYN) loader: maps PT_LOAD segments into the guest region,
// applies RELA relocations and binds undefined symbols to host trampolines.
#include "sjfport/elf_loader.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/libopensl.h"
#include <cstring>
#include <random>

namespace sjf {

namespace {

// ELF64 constants
constexpr u16 PT_LOAD = 1, PT_DYNAMIC = 2;
constexpr u32 DT_NULL = 0, DT_INIT = 12, DT_FINI = 13, DT_INIT_ARRAY = 25,
             DT_INIT_ARRAYSZ = 27, DT_PREINIT_ARRAY = 32, DT_PREINIT_ARRAYSZ = 33;
constexpr u32 DT_HASH = 4, DT_STRTAB = 5, DT_SYMTAB = 6, DT_SYMENT = 11,
             DT_RELA = 7, DT_RELASZ = 8, DT_RELAENT = 9, DT_STRSZ = 10,
             DT_PLTRELSZ = 2, DT_PLTGOT = 3, DT_JMPREL = 23, DT_PLTREL = 20;
// AArch64 relocation types
constexpr u32 R_AARCH64_ABS64 = 257, R_AARCH64_GLOB_DAT = 1025,
             R_AARCH64_JUMP_SLOT = 1026, R_AARCH64_RELATIVE = 1027,
             R_AARCH64_TLS_DTPMOD64 = 1028, R_AARCH64_TLS_DTPREL64 = 1029,
             R_AARCH64_TLS_TPREL64 = 1030, R_AARCH64_TLSDESC = 1031,
             R_AARCH64_IRELATIVE = 1032;

#pragma pack(push, 1)
struct Elf64_Ehdr {
    u8 e_ident[16];
    u16 e_type, e_machine;
    u32 e_version;
    u64 e_entry, e_phoff, e_shoff;
    u32 e_flags;
    u16 e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx;
};
struct Elf64_Phdr {
    u32 p_type, p_flags;
    u64 p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align;
};
struct Elf64_Dyn { i64 d_tag; u64 d_val; };
struct Elf64_Sym {
    u32 st_name;
    u8 st_info;
    u8 st_other;
    u16 st_shndx;
    u64 st_value;
    u64 st_size;
};
struct Elf64_Rela { u64 r_offset; u64 r_info; i64 r_addend; };
#pragma pack(pop)

u64 rd64(u64 gaddr) { u64 v; std::memcpy(&v, guest_to_host(gaddr), 8); return v; }
void wr64(u64 gaddr, u64 v) { std::memcpy(guest_to_host(gaddr), &v, 8); }

} // namespace

bool elf_load(const std::string& path, const std::string& so_name, LoadedElf& out) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { LOGE("elf_load: cannot open %s", path.c_str()); return false; }
    std::fseek(f, 0, SEEK_END);
    long fsize = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    std::vector<u8> file((size_t)fsize);
    if (std::fread(file.data(), 1, file.size(), f) != file.size()) {
        std::fclose(f);
        LOGE("elf_load: read failed");
        return false;
    }
    std::fclose(f);

    if (file.size() < sizeof(Elf64_Ehdr)) { LOGE("elf_load: too small"); return false; }
    Elf64_Ehdr ehdr;
    std::memcpy(&ehdr, file.data(), sizeof(ehdr));
    if (std::memcmp(ehdr.e_ident, "\x7f""ELF", 4) || ehdr.e_ident[4] != 2 /*ELFCLASS64*/) {
        LOGE("elf_load: not ELF64"); return false;
    }
    if (ehdr.e_machine != 183 /*EM_AARCH64*/) { LOGE("elf_load: not AArch64"); return false; }

    out.base = kGuestBase;

    // 1) map PT_LOAD segments
    u64 max_end = 0;
    for (int i = 0; i < ehdr.e_phnum; ++i) {
        Elf64_Phdr ph;
        std::memcpy(&ph, file.data() + ehdr.e_phoff + (size_t)i * ehdr.e_phentsize, sizeof(ph));
        if (ph.p_type != PT_LOAD)
            continue;
        u64 vstart = out.base + (ph.p_vaddr & ~0xFFFull);
        u64 vend = out.base + ((ph.p_vaddr + ph.p_memsz + 0xFFF) & ~0xFFFull);
        if (!guest_commit(vstart, vend - vstart)) {
            LOGE("elf_load: commit failed for segment %d (0x%llx..0x%llx)", i,
                 (unsigned long long)vstart, (unsigned long long)vend);
            return false;
        }
        u8* dst = reinterpret_cast<u8*>(guest_to_host(out.base + ph.p_vaddr));
        std::memcpy(dst, file.data() + ph.p_offset, (size_t)ph.p_filesz);
        if (ph.p_memsz > ph.p_filesz)
            std::memset(dst + ph.p_filesz, 0, (size_t)(ph.p_memsz - ph.p_filesz)); // .bss
        if (vend > max_end) max_end = vend;
    }
    out.image_end = max_end;
    LOGI("%s: mapped image 0x%llx..0x%llx", so_name.c_str(), (unsigned long long)out.base,
         (unsigned long long)max_end);

    // 2) walk PT_DYNAMIC
    std::vector<Elf64_Dyn> dyns;
    for (int i = 0; i < ehdr.e_phnum; ++i) {
        Elf64_Phdr ph;
        std::memcpy(&ph, file.data() + ehdr.e_phoff + (size_t)i * ehdr.e_phentsize, sizeof(ph));
        if (ph.p_type != PT_DYNAMIC)
            continue;
        size_t n = (size_t)(ph.p_filesz / sizeof(Elf64_Dyn));
        dyns.resize(n);
        std::memcpy(dyns.data(), file.data() + ph.p_offset, n * sizeof(Elf64_Dyn));
    }
    u64 strtab = 0, symtab = 0, syment = 24, strsz = 0;
    u64 rela = 0, relasz = 0, relaent = 24, jmprel = 0, pltrelsz = 0, pltrel = 0;
    u64 initarray = 0, initarraysz = 0, initfn = 0;
    for (auto& d : dyns) {
        switch (d.d_tag) {
            case DT_STRTAB: strtab = d.d_val; break;
            case DT_SYMTAB: symtab = d.d_val; break;
            case DT_SYMENT: syment = d.d_val; break;
            case DT_STRSZ: strsz = d.d_val; break;
            case DT_RELA: rela = d.d_val; break;
            case DT_RELASZ: relasz = d.d_val; break;
            case DT_RELAENT: relaent = d.d_val; break;
            case DT_JMPREL: jmprel = d.d_val; break;
            case DT_PLTRELSZ: pltrelsz = d.d_val; break;
            case DT_PLTREL: pltrel = d.d_val; break;
            case DT_INIT_ARRAY: initarray = d.d_val; break;
            case DT_INIT_ARRAYSZ: initarraysz = d.d_val; break;
            case DT_INIT: initfn = d.d_val; break;
            case DT_NULL: break;
            default: break;
        }
    }
    out.symtab_guest = out.base + symtab;
    out.strtab_guest = out.base + strtab;

    // guest-side symbol helpers
    auto sym_name = [&](u64 idx) -> std::string {
        Elf64_Sym s;
        std::memcpy(&s, guest_to_host(out.symtab_guest + idx * syment), sizeof(s));
        if (!s.st_name)
            return {};
        const char* p = reinterpret_cast<const char*>(guest_to_host(out.strtab_guest + s.st_name));
        return std::string(p);
    };
    auto sym_def = [&](u64 idx) -> u64 {
        Elf64_Sym s;
        std::memcpy(&s, guest_to_host(out.symtab_guest + idx * syment), sizeof(s));
        if (s.st_shndx == 0 /*SHN_UNDEF*/)
            return 0;
        return out.base + s.st_value;
    };
    u64 symcount = 0;
    if (strtab && symtab && symtab < strtab)
        symcount = (strtab - symtab) / syment;
    out.symcount = symcount;

    // 3) collect exports
    for (u64 i = 0; i < symcount; ++i) {
        std::string nm = sym_name(i);
        u64 def = sym_def(i);
        if (!nm.empty() && def)
            out.exports[nm] = def;
    }
    LOGI("%s: %llu dynamic symbols, %llu exports", so_name.c_str(),
         (unsigned long long)symcount, (unsigned long long)out.exports.size());

    // 4) resolve undefined symbols -> trampolines / native data
    //    (trampolines were created at host-module registration time; here we
    //     only record which imports bind to which trampoline)
    for (u64 i = 0; i < symcount; ++i) {
        Elf64_Sym s;
        std::memcpy(&s, guest_to_host(out.symtab_guest + i * syment), sizeof(s));
        if (s.st_shndx != 0)
            continue;
        std::string nm = sym_name(i);
        if (nm.empty())
            continue;
        u64 t = trampoline_for(nm);
        if (t)
            out.bound_imports[nm] = t;
    }

    // 5) apply relocations
    auto apply_rela = [&](u64 rstart, u64 rsize, const char* kind) {
        u64 n = rsize / relaent;
        for (u64 i = 0; i < n; ++i) {
            Elf64_Rela r;
            std::memcpy(&r, guest_to_host(out.base + rstart + i * relaent), sizeof(r));
            u32 type = (u32)(r.r_info & 0xFFFFFFFFull);
            u32 sym = (u32)(r.r_info >> 32);
            u64 S = 0;
            if (sym) {
                S = sym_def(sym);
                if (!S) {
                    std::string nm = sym_name(sym);
                    auto it = out.bound_imports.find(nm);
                    if (it != out.bound_imports.end()) {
                        S = it->second;
                    } else if (find_host_fn(nm)) {
                        S = trampoline_for(nm);
                        out.bound_imports[nm] = S;
                    } else {
                        // data symbol or truly unknown: native data blob
                        u64 st_size = 0;
                        {
                            Elf64_Sym s2;
                            std::memcpy(&s2, guest_to_host(out.symtab_guest + sym * syment), sizeof(s2));
                            st_size = s2.st_size ? s2.st_size : 16;
                        }
                        S = alloc_native_data(st_size, 8);
                        out.bound_imports[nm] = S;
                        out.unresolved.push_back(nm);
                        if (nm.rfind("SL_IID_", 0) == 0)
                            sl_bind_iid(nm.c_str(), S);
                    }
                }
            }
            u64 place = out.base + r.r_offset;
            switch (type) {
                case R_AARCH64_RELATIVE:
                case R_AARCH64_IRELATIVE:
                    wr64(place, out.base + (u64)r.r_addend);
                    break;
                case R_AARCH64_ABS64:
                case R_AARCH64_GLOB_DAT:
                case R_AARCH64_JUMP_SLOT: {
                    u64 val = S + (u64)r.r_addend;
                    wr64(place, val);
                    break;
                }
                case R_AARCH64_TLS_DTPMOD64:
                    wr64(place, 1); // single module id
                    break;
                case R_AARCH64_TLS_DTPREL64:
                case R_AARCH64_TLS_TPREL64:
                    wr64(place, (u64)r.r_addend);
                    break;
                case R_AARCH64_TLSDESC:
                    wr64(place, 0); wr64(place + 8, 0);
                    break;
                default:
                    LOGW("%s: unhandled reloc type %u at 0x%llx", kind, type,
                         (unsigned long long)place);
                    break;
            }
        }
        LOGI("%s: %llu relocations applied", kind, (unsigned long long)n);
    };

    if (rela && relasz) apply_rela(rela, relasz, ".rela.dyn");
    if (jmprel && pltrelsz) apply_rela(jmprel, pltrelsz, ".rela.plt");

    // __stack_chk_guard: random value so stack protector works
    {
        auto it = out.bound_imports.find("__stack_chk_guard");
        if (it != out.bound_imports.end()) {
            std::mt19937_64 rng(0xC0FFEE);
            u64 guard = (rng() & 0x00FFFFFFFFFFFFFFull) | 0x4F4A460000000000ull; // no zero top byte
            wr64(it->second, guard);
        }
    }

    // 6) init array
    if (initarray && initarraysz) {
        u64 n = initarraysz / 8;
        for (u64 i = 0; i < n; ++i)
            out.init_array.push_back(rd64(out.base + initarray + i * 8));
        LOGI("%s: %llu init_array functions", so_name.c_str(), (unsigned long long)n);
    }
    if (initfn)
        out.init_fn = out.base + initfn;

    // report unknown imports
    if (!out.unresolved.empty()) {
        LOGW("%s: %llu imports bound to data blobs (no host handler):", so_name.c_str(),
             (unsigned long long)out.unresolved.size());
        for (auto& u : out.unresolved)
            LOGW("    (data) %s", u.c_str());
    }
    return true;
}

u64 elf_find_symbol(const LoadedElf& elf, const std::string& name) {
    auto it = elf.exports.find(name);
    return it == elf.exports.end() ? 0 : it->second;
}

namespace {
LoadedElf* g_global_elf = nullptr;
}

LoadedElf* global_loaded_elf() { return g_global_elf; }
void set_global_loaded_elf(LoadedElf* elf) { g_global_elf = elf; }

} // namespace sjf
