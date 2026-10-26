import io, re

p = 'port/src/dex/jni_env.cpp'  # placeholder no-op
syms = []
for line in open('extracted/analysis/.dynsym_exports.txt', encoding='utf-8', errors='replace'):
    q = line.rstrip().split('\t')
    if len(q) < 3:
        continue
    try:
        syms.append((int(q[0], 16), int(q[1], 16), q[2]))
    except ValueError:
        pass

ctors = {}
for a, sz, n in syms:
    m = re.match(r'_ZN(.+)C[12]Ev$', n)
    if m:
        ctors[m.group(1)] = (a, sz)

for body in ('7network15DownloadManager', '2sl11HttpManager',
             '7network22ConnectedProfileManager'):
    c1 = ctors.get(body)
    print('%-40s ctor=%s size=%s' % (body,
          ('0x%x' % c1[0]) if c1 else 'MISSING', ('0x%x' % c1[1]) if c1 else '-'))
