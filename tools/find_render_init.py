import io, re

rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    q = line.rstrip().split('\t')
    if len(q) < 3:
        continue
    try:
        a, sz = int(q[0], 16), int(q[1], 16)
    except ValueError:
        continue
    n = q[2]
    if 0x2e0000 <= a <= 0x320000 and re.search(r'init|Init|render|Render|GLES|gles|Shader|shader|Create|create', n):
        rows.append((a, sz, n))
print('candidates:', len(rows))
for a, sz, n in sorted(rows):
    print('0x%05x +0x%04x %s' % (a, sz, n[:90]))
