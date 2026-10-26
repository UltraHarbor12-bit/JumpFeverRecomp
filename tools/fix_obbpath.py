import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
s = s.replace('u64 obb = alloc_guest_string("");', 'u64 obb = alloc_guest_string("game/base.apk");')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('obbPath -> game/base.apk')
