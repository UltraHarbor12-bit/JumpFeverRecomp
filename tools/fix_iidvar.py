import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

old = '''void sl_bind_iid(const char* name, u64 blob_addr) {
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    g_iid_names[blob_addr] = name;
    LOGI("SL bind %s -> 0x%llx", name, (unsigned long long)blob_addr);
}'''
new = '''void sl_bind_iid(const char* name, u64 blob_addr) {
    // On Android the imported `SL_IID_x` symbol is a POINTER VARIABLE whose
    // value (owned by libOpenSLES.so) points to the SLInterfaceID struct.
    // The engine loads the variable then dereferences it, so our blob must
    // contain a pointer to a fake (unique) 16-byte SLInterfaceID.
    static u32 counter = 0x51D10000;
    u64 st = alloc_native_data(16, 4);
    u32 id[4] = {counter++, 0x51D10000u, 0x4F50454Eu, 0x00000000u};
    gwrite(st, id, 16);
    u64 nullv = 0;
    (void)nullv;
    gwrite(blob_addr, &st, 8);
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    g_iid_names[st] = name;
    LOGI("SL bind %s: var@0x%llx -> id 0x%llx", name, (unsigned long long)blob_addr,
         (unsigned long long)st);
}'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('iid var semantics fixed')
else:
    print('pattern miss')
