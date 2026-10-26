import io, re

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

start = s.find('    // Deliver the native window immediately after onCreate.')
end = s.find('    // 7) lifecycle probe')
if start == -1 or end == -1:
    print('block not found', start, end)
    raise SystemExit(1)

new_block = '''    // Deliver the native window immediately after onCreate.
    {
        u64 nw = alloc_native_data(32, 8);
        auto* cbx = reinterpret_cast<ANativeActivityCallbacks*>(guest_to_host(callbacks));
        if (cbx && cbx->onNativeWindowCreated) {
            LOGI("boot: -> callbacks->onNativeWindowCreated (early)");
            guest_call((u64)cbx->onNativeWindowCreated, activity, nw, 0, 0, 0, 0, 0, 0,
                       "onNativeWindowCreated");
            LOGI("boot: onNativeWindowCreated (early) returned");
        }
    }

'''
s = s[:start] + new_block + s[end:]
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched block ok')
