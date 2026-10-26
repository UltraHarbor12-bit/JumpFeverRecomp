import io

p = 'port/src/runtime/guest_abi.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

s = s.replace('''        if (c.va_gr_offs > -64) {
            c.va_gr_offs -= 8;
            u64 v = 0;
            gread(&v, c.va_gr_top + c.va_gr_offs, 8);
            return v;
        }''',
'''        if (c.va_gr_offs < 0) {
            u64 v = 0;
            gread(&v, c.va_gr_top + c.va_gr_offs, 8);
            c.va_gr_offs += 8;
            return v;
        }''')

s = s.replace('''        if (c.va_vr_offs > -128) {
            c.va_vr_offs -= 16;
            u64 bits = 0;
            gread(&bits, c.va_vr_top + c.va_vr_offs, 8);
            double d;
            std::memcpy(&d, &bits, 8);
            return d;
        }''',
'''        if (c.va_vr_offs < 0) {
            u64 bits = 0;
            gread(&bits, c.va_vr_top + c.va_vr_offs, 8);
            c.va_vr_offs += 16;
            double d;
            std::memcpy(&d, &bits, 8);
            return d;
        }''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('va_list semantics fixed')
