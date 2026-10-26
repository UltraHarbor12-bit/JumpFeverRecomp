// sjfport — common types and logging
#pragma once
#include <cstdint>
#include <cstdio>
#include <string>

namespace sjf {

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using i8 = std::int8_t;
using i16 = std::int16_t;
using i32 = std::int32_t;
using i64 = std::int64_t;

enum class LogLevel { Debug, Info, Warn, Error };

void log_msg(LogLevel level, const char* tag, const std::string& msg);
void set_log_verbose(bool verbose);
// --debug: enables diagnostic probes (watchpoints, periodic pc samples).
void set_debug_mode(bool on);
bool debug_mode();

#define SJF_LOG(tag, level, ...)                                              \
    do {                                                                      \
        char _buf[1024];                                                      \
        std::snprintf(_buf, sizeof(_buf), __VA_ARGS__);                       \
        ::sjf::log_msg(::sjf::LogLevel::level, tag, _buf);                    \
    } while (0)

#define LOGD(...) SJF_LOG("sjf", Debug, __VA_ARGS__)
#define LOGI(...) SJF_LOG("sjf", Info, __VA_ARGS__)
#define LOGW(...) SJF_LOG("sjf", Warn, __VA_ARGS__)
#define LOGE(...) SJF_LOG("sjf", Error, __VA_ARGS__)

} // namespace sjf
