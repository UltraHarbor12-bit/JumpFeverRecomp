import io, re

rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    if 'DownloadManager' in p[2] or 'AndroidGameApp' in p[2] or re.search(r'android_main|_Z10deInitGame|_Z\d+initGame', p[2]):
        rows.append((int(p[0], 16), int(p[1], 16), p[2]))
print('matches:', len(rows))
for a, sz, n in sorted(rows):
    print('0x%05x +0x%04x %s' % (a, sz, n))
