// sjfport — OpenSL ES object model
#pragma once
#include "common.h"

namespace sjf {
void register_libOpenSLES_module();
void sl_bind_iid(const char* name, u64 blob_addr);
} // namespace sjf
