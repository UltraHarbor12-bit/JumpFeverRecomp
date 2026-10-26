import io

p = 'port/src/dex/jni_env.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

old = '''    // ---- network / services: offline behaviour ----
    if (n == "isConnected" || n == "isConnectedToNetwork")
        return 1;'''
new = '''    // ---- network / services: "connected" behaviour ----
    // Softlight.isConnected() fires an ASYNC Java check whose result reaches
    // the engine through the native isConnectedCallBack(bool). Our fake Java
    // calls that native export directly (connected = true).
    if (n == "isConnected" && self && self->name == "com/sega/sonicjumpfever/Softlight") {
        u64 cb = 0;
        if (const LoadedElf* elf = global_loaded_elf())
            cb = elf_find_symbol(*elf,
                                 "Java_com_sega_sonicjumpfever_checkNetwork_isConnectedCallBack");
        if (cb) {
            LOGI("JNI Softlight.isConnected -> firing native isConnectedCallBack(true)");
            guest_call_nested(cb, jni_env_guest(), 0, 1, 0, 0, 0, 0, 0);
        }
        return 0;
    }
    if (n == "isConnected" || n == "isConnectedToNetwork")
        return 1;'''
if old in s:
    s = s.replace(old, new, 1)

# includes for elf access + nested calls
if 'global_loaded_elf' not in s:
    s = s.replace('#include "sjfport/host_calls.h"',
                  '#include "sjfport/host_calls.h"\n#include "sjfport/elf_loader.h"\n#include "sjfport/runtime.h"')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('isConnected callback wired')
