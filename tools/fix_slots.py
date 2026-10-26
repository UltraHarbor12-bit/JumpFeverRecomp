import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''        itf = vt_build("engine", 10, {
            {3, [](GuestCall& c) { h_engine_createaudioplayer(c); }},
            {7, [](GuestCall& c) { h_engine_createoutputmix(c); }},
        });'''
new = '''        itf = vt_build("engine", 10, {
            {2, [](GuestCall& c) { h_engine_createaudioplayer(c); }},  // 2014 header slot
            {3, [](GuestCall& c) { h_engine_createaudioplayer(c); }},  // spec slot
            {7, [](GuestCall& c) { h_engine_createoutputmix(c); }},    // 2014 header slot
            {8, [](GuestCall& c) { h_engine_createoutputmix(c); }},    // spec slot
        });'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('engine slots 2/3 + 7/8 both mapped')
else:
    print('pattern miss')
