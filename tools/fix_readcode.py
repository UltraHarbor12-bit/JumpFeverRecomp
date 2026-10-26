import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = 'fault("ReadCode", vaddr);'
if old in s:
    s = s.replace(old, 'fault("ReadCode", vaddr, false);')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('fixed ReadCode call')
else:
    print('not found')
