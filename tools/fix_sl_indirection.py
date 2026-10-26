import io

p = 'port/src/dependencies/libopensl.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# engine GetInterface: wrap the interface vtable in an interface object
old1 = '''    if (c.x[2])
        gwrite(c.x[2], &itf, 8);
    c.ret = SL_SUCCESS;
}

// ---------------------------------------------------------------------------
// SLEngineItf'''
new1 = '''    if (c.x[2]) {
        u64 itf_obj = alloc_native_data(8, 8);
        gwrite(itf_obj, &itf, 8);
        gwrite(c.x[2], &itf_obj, 8);
    }
    c.ret = SL_SUCCESS;
}

// ---------------------------------------------------------------------------
// SLEngineItf'''
if old1 in s:
    s = s.replace(old1, new1, 1)
    print('engine getinterface wrapped')

# player GetInterface: same wrap
old2 = '''    if (c.x[2])
        gwrite(c.x[2], &itf, 8);
    c.ret = SL_SUCCESS;
}

void h_bq_enqueue(GuestCall& c) {'''
new2 = '''    if (c.x[2]) {
        u64 itf_obj = alloc_native_data(8, 8);
        gwrite(itf_obj, &itf, 8);
        gwrite(c.x[2], &itf_obj, 8);
    }
    c.ret = SL_SUCCESS;
}

void h_bq_enqueue(GuestCall& c) {'''
if old2 in s:
    s = s.replace(old2, new2, 1)
    print('player getinterface wrapped')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
