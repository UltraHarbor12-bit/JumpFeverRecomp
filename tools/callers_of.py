"""Find callers of an exported function (resolves through the PLT)."""
import sys, bisect
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_OP_MEM, CS_OP_IMM, CS_OP_REG
from elftools.elf.elffile import ELFFile

SYMBOL = sys.argv[1]
SO = 'port/game/libsonicjumpfever.so'

e = ELFFile(open(SO, 'rb'))
text = e.get_section_by_name('.text')
plt = e.get_section_by_name('.plt')
data = open(SO, 'rb').read()

# GOT slot -> symbol (from .rela.plt)
rel = e.get_section_by_name('.rela.plt')
syms = e.get_section_by_name('.dynsym')
slot_sym = {}
for r in rel.iter_relocations():
    s = syms.get_symbol(r['r_info_sym'])
    if s.name:
        slot_sym[r['r_offset']] = s.name

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True
md.skipdata = True

# decode plt stubs: adrp x16, page ; ldr x17, [x16, #off] ; add... ; br x17
stub_target = {}
plt_base = plt['sh_addr']
plt_code = data[plt['sh_offset']:plt['sh_offset'] + plt['sh_size']]
insns = list(md.disasm(plt_code, plt_base))
for i, ins in enumerate(insns):
    if ins.mnemonic == 'ldr' and len(ins.operands) == 2 and ins.operands[1].type == CS_OP_MEM:
        mem = ins.operands[1]
        # find preceding adrp for the same base reg
        for j in range(i - 1, max(-1, i - 4), -1):
            prev = insns[j]
            if prev.mnemonic == 'adrp' and len(prev.operands) == 2 and \
               prev.operands[0].reg == mem.mem.base:
                got_addr = prev.operands[1].imm + mem.mem.disp
                if got_addr in slot_sym:
                    stub_target[ins.address] = slot_sym[got_addr]
                break

# symbol -> stub address
wanted = {}
for stub_addr, sym in stub_target.items():
    wanted.setdefault(sym, []).append(stub_addr)

if SYMBOL not in wanted:
    print('no PLT stub for %s (have %d stubs total)' % (SYMBOL, len(stub_target)))
    sys.exit(0)

stub_addrs = wanted[SYMBOL]
print('PLT stubs for %s: %s' % (SYMBOL, [hex(a) for a in stub_addrs]))

# scan text for bl/b to those stubs
tcode = data[text['sh_offset']:text['sh_offset'] + text['sh_size']]
tbase = text['sh_addr']
callers = []
for ins in md.disasm(tcode, tbase):
    if ins.id == 0 or ins.mnemonic == '.byte':
        continue
    if ins.mnemonic in ('bl', 'b'):
        try:
            ops = ins.operands
        except Exception:
            continue
        if ops and ops[0].type == CS_OP_IMM and ops[0].imm in stub_addrs:
            callers.append((ins.address, ins.mnemonic))

print('callers:', len(callers))
for a, mn in callers[:20]:
    print('  0x%05x %s' % (a, mn))
