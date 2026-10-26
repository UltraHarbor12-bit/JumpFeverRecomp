import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

bad = '''            // reads mean the engine expected real data here: cascade
        } during startup
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);'''
good = '''            // reads mean the engine expected real data here: cascade unwind
        }
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);'''
if bad in s:
    s = s.replace(bad, good, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('fixed line 258')
else:
    print('pattern not found')
