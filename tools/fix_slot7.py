import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = '''        itf = vt_build("engine", 10, {
            {3, [](GuestCall& c) { h_engine_createaudioplayer(c); }},
            {8, [](GuestCall& c) { h_engine_createoutputmix(c); }},
        });'''
new = '''        // NOTE: this build's SLEngineItf has CreateOutputMix at slot 7
        // (2014-era header, no CreateOutputStreamMix) — verified empirically:
        // the engine calls slot 7 right after GetInterface(SL_IID_ENGINE).
        itf = vt_build("engine", 10, {
            {3, [](GuestCall& c) { h_engine_createaudioplayer(c); }},
            {7, [](GuestCall& c) { h_engine_createoutputmix(c); }},
        });'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('CreateOutputMix moved to slot 7')
else:
    print('pattern miss')
