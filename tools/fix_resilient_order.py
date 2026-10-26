import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

# remove the late declarations
s = s.replace('''thread_local ThreadState* t_state = nullptr;
thread_local u64 t_entry_sp = 0; // guest SP at the current guest_call entry
thread_local bool t_resilient = true;''',
'''thread_local ThreadState* t_state = nullptr;''')

# add them early (before the Callbacks class)
s = s.replace('''// Sentinel return address: any code fetch here fails -> NoExecuteFault ->
// we treat it as "the guest function returned".
constexpr u64 kReturnSentinel = 0xDEAD0000ull;''',
'''// Sentinel return address: any code fetch here fails -> NoExecuteFault ->
// we treat it as "the guest function returned".
constexpr u64 kReturnSentinel = 0xDEAD0000ull;

// Per-thread JIT diagnostics/unwind state (declared early: Callbacks uses it).
thread_local u64 t_entry_sp = 0;  // guest SP at the current guest_call entry
thread_local bool t_resilient = true;''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('declaration order fixed')
