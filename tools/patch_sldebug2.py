import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'CALLER LR' not in s:
    s = s.replace('''    LOGI("SL %s->GetInterface(%s) raw=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1]);''',
'''    LOGI("SL %s->GetInterface(%s) raw=0x%llx CALLER_LR=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1], (unsigned long long)c.x[30]);''')
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('caller lr log added')
