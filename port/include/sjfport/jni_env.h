// sjfport — fake JNI environment
#pragma once
#include "common.h"

namespace sjf {
bool jni_env_init();
u64 jni_vm_guest();
u64 jni_env_guest();
} // namespace sjf
