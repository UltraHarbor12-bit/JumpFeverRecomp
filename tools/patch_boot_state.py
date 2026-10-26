import io

p = 'port/src/engine/boot.cpp'
with io.open(p, 'r', encoding='utf-8', newline=None) as f:
    s = f.read()

s = s.replace('''    LOGI("boot: ANativeActivity_onCreate returned");
    log_callbacks(callbacks);''', '''    LOGI("boot: ANativeActivity_onCreate returned");
    {
        auto* act = reinterpret_cast<ANativeActivity*>(guest_to_host(activity));
        LOGI("boot: activity state after onCreate: instance=0x%llx clazz=0x%llx "
             "vm=0x%llx env=0x%llx am=0x%llx",
             (unsigned long long)(u64)act->instance, (unsigned long long)(u64)act->clazz,
             (unsigned long long)(u64)act->vm, (unsigned long long)(u64)act->env,
             (unsigned long long)(u64)act->assetManager);
    }
    log_callbacks(callbacks);''')

with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
    f.write(s)
print('patched boot.cpp')
