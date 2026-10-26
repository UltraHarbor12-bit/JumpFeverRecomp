import io

p = 'port/src/runtime/jit.cpp'
with io.open(p, 'r', encoding='utf-8', newline=None) as f:
    s = f.read()

# 1) thread-local callbacks (one per guest thread)
s = s.replace('''    static Callbacks& instance() {
        static Callbacks cb;
        return cb;
    }''', '''    static Callbacks& instance() {
        thread_local Callbacks cb;
        return cb;
    }''')

# 2) sentinel range wider (dynarmic may stride past the ret)
s = s.replace('if (pc >= kReturnSentinel && pc < kReturnSentinel + 0x100) {',
              'if (pc >= kReturnSentinel && pc < kReturnSentinel + 0x10000) {')

# 3) run_on: treat sentinel range as normal return
s = s.replace('''    if (ts.last_pc != kReturnSentinel && ts.last_pc != 0) {
        LOGW("run_on(%s): halted at pc=0x%llx (not a normal return)", what ? what : "?",
             (unsigned long long)ts.last_pc);
    }''', '''    const bool returned = (ts.last_pc >= kReturnSentinel && ts.last_pc < kReturnSentinel + 0x10000);
    if (!returned && ts.last_pc != 0) {
        LOGW("run_on(%s): halted at pc=0x%llx (not a normal return)", what ? what : "?",
             (unsigned long long)ts.last_pc);
    }''')

with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
    f.write(s)
print('patched jit.cpp (thread-local callbacks, sentinel range)')
