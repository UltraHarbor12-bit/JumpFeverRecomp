rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    n = p[2]
    if 'PlayerProfile' in n and any(k in n for k in ('C1E', 'C2E', 'D1E', 'D2E', 'init', 'Init',
                                                    'setup', 'load', 'Load', 'reset', 'Reset',
                                                    'create', 'Create')):
        rows.append((int(p[0], 16), int(p[1], 16), n))
print('matches:', len(rows))
for a, sz, n in sorted(rows):
    print('0x%05x +0x%04x %s' % (a, sz, n))
