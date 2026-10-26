import io

def patch(path, pairs):
    with io.open(path, 'r', encoding='utf-8', newline=None) as f:
        s = f.read()
    for old, new in pairs:
        if old not in s:
            print('MISS %s: %r' % (path, old[:70]))
            continue
        s = s.replace(old, new, 1)
        print('ok  %s' % path)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)

patch('port/src/runtime/jit.cpp', [
    ('''    u8 MemoryRead8(u64 vaddr) override {''',
     '''    std::optional<u32> MemoryReadCode(u64 vaddr) override {
        // Return sentinel: our "guest function returned" marker
        if (vaddr == kReturnSentinel)
            return std::nullopt;
        auto* p = (const u8*)guest_to_host(vaddr);
        if (!p) {
            fault("ReadCode", vaddr);
            return std::nullopt;
        }
        u32 v;
        std::memcpy(&v, p, 4);
        return v;
    }

    u8 MemoryRead8(u64 vaddr) override {'''),
    ('''        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);''',
     '''        if (vaddr >= kReturnSentinel && vaddr < kReturnSentinel + 0x10000)
            return; // return-sentinel page: expected
        LOGE("guest memory %s at 0x%llx (unmapped)", what, (unsigned long long)vaddr);'''),
])

patch('port/src/dependencies/libgl.cpp', [
    ('"glDeleteProgram", "glDeleteShader", "glDeleteTextures", "glDepthMask", "glDisable",',
     '"glDeleteProgram", "glDeleteShader", "glDeleteTextures", "glDepthMask", "glDetachShader", "glDisable",'),
])
print('done')
