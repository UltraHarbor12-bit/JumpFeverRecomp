"""Map PLT stub addresses to symbol names (inverse of callers_of)."""
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_OP_MEM
from elftools.elf.elffile import ELFFile

SO = 'port/game/libsonicjumpfever.so'
e = ELFFile(open(SO, 'rb'))
plt = e.get_section_by_name('.plt')
rel = e.get_section_by_name('.rela.plt')
syms = e.get_section_by_name('.dynsym')
data = open(SO, 'rb').read()

slot_sym = {}
for r in rel.iter_relocations():
    s = syms.get_symbol(r['r_info_sym'])
    if s.name:
        slot_sym[r['r_offset']] = s.name

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True
plt_code = data[plt['sh_offset']:plt['sh_offset'] + plt['sh_size']]
insns = list(md.disasm(plt_code, plt['sh_addr']))

for i, ins in enumerate(insns):
    if ins.mnemonic == 'ldr' and len(ins.operands) == 2 and ins.operands[1].type == CS_OP_MEM:
        mem = ins.operands[1]
        for j in range(i - 1, max(-1, i - 4), -1):
            prev = insns[j]
            if prev.mnemonic == 'adrp' and len(prev.operands) == 2 and \
               prev.operands[0].reg == mem.mem.base:
                got = prev.operands[1].imm + mem.mem.disp
                if got in slot_sym:
                    print('PLT 0x%x -> %s' % (ins.address, slot_sym[got]))
                break

# also print which stubs match the addresses given
for a in sys.argv[1:]:
    t = int(a, 16)
    for i, ins in enumerate(insns):
        if ins.address == t:
            # find its ldr
            for j in range(i, min(i + 3, len(insns))):
                if insns[j].mnemonic == 'ldr' and insns[j].operands[1].type == CS_OP_MEM:
                    mem = insns[j].operands[1]
                    for k in range(j - 1, max(-1, j - 4), -1):
                        prev = insns[k]
                        if prev.mnemonic == 'adrp' and prev.operands[0].reg == mem.mem.base:
                            got = prev.operands[1].imm + mem.mem.disp
                            print('%s => %s' % (a, slot_sym.get(got, 'GOT 0x%x (no sym)' % got)))
                            break
                    break
