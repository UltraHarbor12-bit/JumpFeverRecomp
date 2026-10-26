import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

anchor = '''    // 4) initialisers (.init_array)'''
add = '''    // Probe: verify the GOT slot / PlayerProfile singleton mapping.
    {
        u64 got = 0, first = 0, second = 0;
        gread(&got, 0x1005bd130ull, 8);
        if (got) {
            gread(&first, got, 8);
            if (first)
                gread(&second, first + 0xb80, 8);
        }
        LOGI("probe: GOT[0x5bd130]=0x%llx *obj=0x%llx [obj+0xb80]=0x%llx",
             (unsigned long long)got, (unsigned long long)first, (unsigned long long)second);
    }

    // 4) initialisers (.init_array)'''
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('probe added')
