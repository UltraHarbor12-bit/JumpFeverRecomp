import io

p = 'port/src/dex/jni_env.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
old = 'return make_string(g_data_dir + "/base.apk");'
if old in s:
    s = s.replace(old, 'return make_string("game/base.apk");')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('apk path fixed (%d occurrences)' % 1)
else:
    # maybe both getApkFileName and getPackageCodePath/resourcePath
    import re
    n = s.count('base.apk')
    print('base.apk occurrences:', n)
    s = s.replace('g_data_dir + "/base.apk"', '"game/base.apk"')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('replaced all')
