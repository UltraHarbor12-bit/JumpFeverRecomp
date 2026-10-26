import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

if 'SL bind %s' not in s:
    s = s.replace('''void sl_bind_iid(const char* name, u64 blob_addr) {
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    g_iid_names[blob_addr] = name;
}''', '''void sl_bind_iid(const char* name, u64 blob_addr) {
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    g_iid_names[blob_addr] = name;
    LOGI("SL bind %s -> 0x%llx", name, (unsigned long long)blob_addr);
}''')
    print('bind log ok')

if 'raw=0x%llx' not in s:
    s = s.replace('''    LOGI("SL %s->GetInterface(%s)", kind.c_str(), iid.c_str());''',
'''    LOGI("SL %s->GetInterface(%s) raw=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1]);''')
    print('raw log ok')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
