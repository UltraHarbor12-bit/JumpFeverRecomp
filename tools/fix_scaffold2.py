import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''        u64 y = alloc_native_data(0x400, 16);   // inner data object
        u64 x = alloc_native_data(0x2000, 16);  // PlayerProfile impl
        if (x && y) {
            gwrite(x + 0xb80, &y, 8);'''
new = '''        u64 y = alloc_native_data(0x400, 16);   // inner data object
        u64 x = alloc_native_data(0x2000, 16);  // PlayerProfile impl
        if (x && y) {
            // two pointer slots used by different code paths:
            //   triggerStartCount: [impl+0xb80] -> counter block (+0xb8)
            //   getServerTime:     [impl+0xb78] -> server-time block (+0x78)
            gwrite(x + 0xb78, &y, 8);
            gwrite(x + 0xb80, &y, 8);'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('scaffold extended (0xb78 + 0xb80)')
else:
    print('pattern miss')
