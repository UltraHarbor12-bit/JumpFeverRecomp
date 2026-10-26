// Host module: liblog (__android_log_print & friends)
#include "sjfport/guest_abi.h"
#include "sjfport/host_calls.h"
#include <cstdio>

namespace sjf {

void register_liblog_module() {
    register_host_fn("__android_log_print", [](GuestCall& c) {
        int prio = (int)(i32)c.x[0];
        std::string tag = gstr(c.x[1]);
        c.vargp = 3;
        c.vargf = 0;
        std::string msg = guest_format(c, c.x[2]);
        const char* pl = "?";
        switch (prio) {
            case 2: pl = "V"; break;
            case 3: pl = "D"; break;
            case 4: pl = "I"; break;
            case 5: pl = "W"; break;
            case 6: pl = "E"; break;
            case 7: pl = "F"; break;
            default: pl = "?"; break;
        }
        std::fprintf(stderr, "[%s][%s] %s\n", tag.c_str(), pl, msg.c_str());
        std::fflush(stderr);
        c.ret = (u64)msg.size();
    });
    register_host_fn("__android_log_vprint", [](GuestCall& c) {
        int prio = (int)(i32)c.x[0];
        std::string tag = gstr(c.x[1]);
        c.use_valist = true;
        c.va_ptr = c.x[3];
        std::string msg = guest_format(c, c.x[2]);
        const char* pl = (prio >= 6) ? "E" : (prio >= 5 ? "W" : "I");
        LOGW("logcat[%s][%s] %s", tag.c_str(), pl, msg.c_str());
        c.ret = (u64)msg.size();
    });
}

} // namespace sjf
