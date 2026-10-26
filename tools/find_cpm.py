rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    if 'ConnectedProfileManager' in p[2]:
        rows.append((int(p[0], 16), int(p[1], 16), p[2]))
print('ConnectedProfileManager symbols:', len(rows))
for a, sz, n in sorted(rows)[:25]:
    print('0x%05x +0x%04x %s' % (a, sz, n[:95]))
