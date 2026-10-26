"""Find writes to a singleton object accessed through a GOT slot.

Pattern:
    adrp xP, GOT_PAGE          ; page of the GOT slot
    ldr  xT, [xP, #SLOT_OFF]   ; xT = &object
    ... str xS, [xT]           ; *(object) = value      <-- initializer
    ... str xS, [xT, #imm]     ; object->field = value
"""
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, CS_OP_MEM, CS_OP_REG
from elftools.elf.elffile import ELFFile

GOT_SLOT = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x5BD130
SO = 'port/game/libsonicjumpfever.so'

e = ELFFile(open(SO, 'rb'))
text = e.get_section_by_name('.text')
data = open(SO, 'rb').read()
base = text['sh_addr']
code = data[text['sh_offset']:text['sh_offset'] + text['sh_size']]

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True
md.skipdata = True

page = GOT_SLOT & ~0xFFF
slot_off = GOT_SLOT & 0xFFF

page_reg = {}    # reg -> True if holds GOT page
si_reg = {}      # reg -> True if holds &object
writes = []

for ins in md.disasm(code, base):
    if ins.id == 0 or ins.mnemonic == '.byte':
        page_reg.clear()
        si_reg.clear()
        continue
    try:
        ops = ins.operands
        _, written = ins.regs_access()
    except Exception:
        continue

    # detect the GOT load
    if ins.mnemonic == 'ldr' and len(ops) == 2 and ops[0].type == CS_OP_REG and ops[1].type == CS_OP_MEM:
        mem = ops[1]
        if mem.mem.disp == slot_off and mem.mem.base in page_reg:
            si_reg[ops[0].reg] = True
            page_reg.pop(ops[0].reg, None)
            continue
        if mem.mem.disp == 0 and mem.mem.base in si_reg:
            si_reg.pop(ops[0].reg, None)
            continue

    # detect stores through the object pointer
    if ins.mnemonic.startswith('st') and ops and ops[0].type == CS_OP_REG:
        for op in ops:
            if op.type == CS_OP_MEM and op.mem.base in si_reg:
                writes.append((ins.address, ins.mnemonic, ins.op_str, op.mem.disp))
                break

    # adrp tracking
    if ins.mnemonic == 'adrp' and len(ops) == 2:
        if ops[1].imm == page:
            page_reg[ops[0].reg] = True
        else:
            page_reg.pop(ops[0].reg, None)
        continue

    # invalidate clobbered registers
    for r in written:
        page_reg.pop(r, None)
        si_reg.pop(r, None)
    if ins.mnemonic in ('ret',) or ins.mnemonic.startswith('b'):
        page_reg.clear()
        si_reg.clear()

print('stores through &object (0x%x): %d' % (GOT_SLOT, len(writes)))
for a, mn, ops, disp in writes[:40]:
    print('  0x%05x %-6s %-30s disp=0x%x' % (a, mn, ops, disp))
