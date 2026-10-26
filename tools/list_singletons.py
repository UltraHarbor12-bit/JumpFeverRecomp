import re

rows = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    try:
        a, sz = int(p[0], 16), int(p[1], 16)
    except ValueError:
        continue
    n = p[2]
    # singleton pointers: _ZN...10s_instanceE (8-byte .bss pointers)
    if 's_instanceE' in n:
        rows.append((a, sz, n))

print('s_instance symbols:', len(rows))
ctors = {}
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    p = line.rstrip().split('\t')
    if len(p) < 3:
        continue
    n = p[2]
    m = re.match(r'_ZN(.+)C[12]Ev$', n)
    if m:
        ctors[m.group(1)] = (int(p[0], 16), int(p[1], 16))

def demangle_class(mangled):
    # _ZN7network15DownloadManager10s_instanceE -> 7network15DownloadManager
    m = re.match(r'_ZN(.+)10s_instanceE$', mangled)
    if not m:
        return None
    body = m.group(1)
    # parse components: [len][name]...
    out = []
    i = 0
    while i < len(body):
        m2 = re.match(r'(\d+)', body[i:])
        if not m2:
            break
        ln = int(m2.group(1))
        i += len(m2.group(1))
        out.append(body[i:i + ln])
        i += ln
    return out

for a, sz, n in sorted(rows):
    parts = demangle_class(n)
    cls = '::'.join(parts) if parts else '?'
    key = ''.join(parts) if parts else ''
    ctor = ctors.get(key)
    print('0x%06x size=%d %-30s ctor=%s' % (a, sz, cls,
          ('0x%x' % ctor[0]) if ctor else 'MISSING'))
