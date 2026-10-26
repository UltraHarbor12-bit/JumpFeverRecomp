# dis.py — disassemble guest functions of libsonicjumpfever.so with symbols + PLT names
# usage: python3 dis.py <addr|symbol> [count]     (addr: guest offset, e.g. 0x2852b8)
import sys, bisect
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
import capstone as cs

SO = '/home/user/jfp/port/game/libsonicjumpfever.so'
f = open(SO, 'rb'); data = f.read(); e = ELFFile(open(SO, 'rb'))

syms = {}; byname = {}
for s in e.get_section_by_name('.dynsym').iter_symbols():
    if s.name and s['st_value']:
        syms.setdefault(s['st_value'], s.name); byname[s.name] = (s['st_value'], s['st_size'])
addrs = sorted(syms)

# PLT: map GOT slot -> import name, then decode plt stubs (adrp x16; ldr x17,[x16,#]; add; br x17)
got2name = {}
for sec in e.iter_sections():
    if isinstance(sec, RelocationSection):
        st = e.get_section(sec['sh_link'])
        for r in sec.iter_relocations():
            if r['r_info_sym']:
                n = st.get_symbol(r['r_info_sym']).name
                if n: got2name[r['r_offset']] = n
plt = e.get_section_by_name('.plt')
md = cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_ARM); md.detail = True
plt2name = {}
if plt:
    base = plt['sh_addr']; code = plt.data()
    ins = list(md.disasm(code, base))
    for i in range(len(ins) - 1):
        a, b = ins[i], ins[i + 1]
        if a.mnemonic == 'adrp' and b.mnemonic == 'ldr':
            page = a.operands[1].imm
            off = b.operands[1].mem.disp
            n = got2name.get(page + off)
            if n: plt2name[a.address] = n

def vaddr_to_off(v):
    for seg in e.iter_segments():
        if seg['p_type'] == 'PT_LOAD' and seg['p_vaddr'] <= v < seg['p_vaddr'] + seg['p_filesz']:
            return v - seg['p_vaddr'] + seg['p_offset']
    return None

def symname(v):
    if v in plt2name: return 'PLT:' + plt2name[v]
    i = bisect.bisect_right(addrs, v) - 1
    if i >= 0:
        a = addrs[i]; n = syms[a]
        sz = byname.get(n, (0, 0))[1]
        if v - a < max(sz, 1) or v == a:
            return n if v == a else '%s+%#x' % (n, v - a)
    return None

def dis(addr, count):
    off = vaddr_to_off(addr)
    for i in md.disasm(data[off:off + count * 4], addr):
        s = '%08x  %-8s %s' % (i.address, i.mnemonic, i.op_str)
        if i.mnemonic in ('bl', 'b') or i.mnemonic.startswith('b.') or i.mnemonic in ('cbz','cbnz','tbz','tbnz'):
            t = i.operands[-1].imm
            n = symname(t)
            if n: s += '   ; ' + n
        print(s)
        if i.mnemonic == 'ret' and count > 2000: break

if __name__ == '__main__':
    a = sys.argv[1]
    if a.startswith('0x'): addr = int(a, 16)
    else: addr = byname[a][0]
    if addr >= 0x100000000: addr -= 0x100000000
    n = int(sys.argv[2]) if len(sys.argv) > 2 else (byname.get(symname(addr) or '', (0, 400))[1] // 4 or 100)
    print('#', symname(addr))
    dis(addr, n)
