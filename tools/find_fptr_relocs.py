import sys
from elftools.elf.elffile import ELFFile

targets = [int(x, 16) for x in sys.argv[1:]]
e = ELFFile(open('port/game/libsonicjumpfever.so', 'rb'))
rel = e.get_section_by_name('.rela.dyn')
syms = e.get_section_by_name('.dynsym')

for t in targets:
    print('=== relocs with addend 0x%x ===' % t)
    n = 0
    for r in rel.iter_relocations():
        if r['r_addend'] == t:
            sym = syms.get_symbol(r['r_info_sym'])
            where = r['r_offset']
            # which section?
            secname = '?'
            for s in e.iter_sections():
                if s['sh_addr'] <= where < s['sh_addr'] + s['sh_size'] and s['sh_addr']:
                    secname = s.name
                    break
            print('  at 0x%x (%s) type=%d sym=%s' % (where, secname, r['r_info_type'],
                                                     sym.name if sym else '-'))
            n += 1
            if n > 10:
                break
    if n == 0:
        print('  (none)')
