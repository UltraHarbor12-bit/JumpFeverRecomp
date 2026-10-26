// Host module: libandroid (NativeActivity glue, input queues, sensors, config)
// For Hito 1 most of this is stubs; the game only needs them once we drive
// the NativeActivity lifecycle, which the engine layer does itself.
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/platform.h"
#include "sjfport/runtime.h"

#include "sjfport/host_compat.h"

#include <cstring>
#include <deque>
#include <map>
#include <mutex>
#include <vector>
#include <thread>
#include <chrono>

namespace sjf {

struct LooperFd {
    int gfd;
    int ident;
    int events;
    u64 data;
};
static std::vector<LooperFd> g_looper_fds;
static std::mutex g_looper_mutex;

// ---- input / sensor state (shared between SDL thread and guest threads) ----
struct TouchEvent {
    int action;
    float x, y;
};
static std::mutex g_input_mutex;
static std::deque<TouchEvent> g_input_fifo;     // not yet fetched by the guest
static std::map<u64, TouchEvent> g_input_live;  // fetched, not yet finished
static int g_input_ident = -1;
static u64 g_input_data = 0;
static int g_sensor_ident = -1;
static u64 g_sensor_data = 0;
static bool g_sensor_enabled = false;
static u64 g_sensor_last_ms = 0;
static float g_tilt_x = 0.f;
static bool g_tilt_override = false; // scripted tilt wins over the keyboard

// Returns true (and the looper ident/data) if input or sensor data is pending.
static bool input_poll_ready(int& ident, u64& data) {
    std::lock_guard<std::mutex> lk(g_input_mutex);
    if (g_input_ident >= 0 && !g_input_fifo.empty()) {
        ident = g_input_ident;
        data = g_input_data;
        return true;
    }
    if (g_sensor_ident >= 0 && g_sensor_enabled && host_ticks_ms() - g_sensor_last_ms >= 16) {
        ident = g_sensor_ident;
        data = g_sensor_data;
        return true;
    }
    return false;
}

void register_libandroid_module() {
    // ---- AConfiguration ----
    register_host_fn("AConfiguration_new", [](GuestCall& c) {
        c.ret = alloc_native_data(64, 8);
    });
    register_host_fn("AConfiguration_delete", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("AConfiguration_fromAssetManager", [](GuestCall& c) {
        c.ret = alloc_native_data(64, 8);
    });
    register_host_fn("AConfiguration_getLanguage", [](GuestCall& c) {
        // writes 2-char language code (bionic: char* outLanguage)
        if (c.x[1]) { char lang[2] = {'e', 'n'}; gwrite(c.x[1], lang, 2); }
        c.ret = 0;
    });
    register_host_fn("AConfiguration_getCountry", [](GuestCall& c) {
        if (c.x[1]) { char cc[2] = {'U', 'S'}; gwrite(c.x[1], cc, 2); }
        c.ret = 0;
    });

    // ---- ANativeActivity / ANativeWindow ----
    register_host_fn("ANativeActivity_finish", [](GuestCall& c) {
        LOGI("ANativeActivity_finish() requested");
        c.ret = 0;
    });
    register_host_fn("ANativeWindow_setBuffersGeometry", [](GuestCall& c) {
        LOGD("ANativeWindow_setBuffersGeometry(%d, %d)", (int)(i32)c.x[1], (int)(i32)c.x[2]);
        c.ret = 0;
    });

    // ---- ALooper (real: blocks on the registered fds, e.g. the self-pipe) ----
    register_host_fn("ALooper_prepare", [](GuestCall& c) {
        static u64 looper = 0;
        if (!looper) looper = alloc_native_data(64, 8);
        c.ret = looper;
    });
    register_host_fn("ALooper_addFd", [](GuestCall& c) {
        // (ALooper*, int fd, int ident, int events, ALooper_callbackFunc* cb, void* data)
        int gfd = (int)(i32)c.x[1];
        int ident = (int)(i32)c.x[2];
        int events = (int)(i32)c.x[3];
        u64 data = c.x[5];
        std::lock_guard<std::mutex> lk(g_looper_mutex);
        g_looper_fds.push_back({gfd, ident, events, data});
        LOGD("ALooper_addFd(fd=%d, ident=%d, events=%#x) registered", gfd, ident, events);
        c.ret = 1;
    });
    register_host_fn("ALooper_pollAll", [](GuestCall& c) {
        int timeout = (int)(i32)c.x[0];
        u64 outFd = c.x[1], outEvents = c.x[2], outData = c.x[3];
        profile_edit_poll(); // game thread, between frames
        u64 t0 = host_ticks_ms();
        for (;;) {
            LooperFd hit{};
            bool found = false;
            {
                std::lock_guard<std::mutex> lk(g_looper_mutex);
                for (auto& e : g_looper_fds) {
                    int hostfd = host_fd_for_guest(e.gfd);
                    if (hostfd < 0)
                        continue;
                    if (host_pipe_available(hostfd) > 0) {
                        hit = e;
                        found = true;
                        break;
                    }
                }
            }
            if (found) {
                static int nf = 0;
                if (nf++ < 20)
                    LOGD("ALooper_pollAll -> ident=%d fd=%d (timeout=%d)", hit.ident, hit.gfd,
                         timeout);
                if (outFd) { i32 v = hit.gfd; gwrite(outFd, &v, 4); }
                if (outEvents) { i32 v = 1; gwrite(outEvents, &v, 4); } // ALOOPER_EVENT_INPUT
                if (outData) { u64 v = hit.data; gwrite(outData, &v, 8); }
                c.ret = (u64)(i64)hit.ident;
                return;
            }
            {
                int ident = 0;
                u64 data = 0;
                if (input_poll_ready(ident, data)) {
                    static int ni = 0;
                    if (ni++ < 40)
                        LOGD("ALooper_pollAll -> input/sensor ident=%d data=0x%llx", ident,
                             (unsigned long long)data);
                    if (outFd) { i32 v = -1; gwrite(outFd, &v, 4); }
                    if (outEvents) { i32 v = 1; gwrite(outEvents, &v, 4); }
                    if (outData) gwrite(outData, &data, 8);
                    c.ret = (u64)(i64)ident;
                    return;
                }
            }
            if (timeout == 0) {
                // The engine's fixed-step loop polls with timeout 0 between
                // frames (~27k polls/s, each followed by 2 JNI calls). A short
                // nap caps that at ~2k/s with no visible effect on pacing.
#ifdef _WIN32
                // Windows sleeps last >= 1 ms (15.6 ms without timeBeginPeriod):
                // napping here starved the engine's fixed-step loop and froze the
                // game on the SEGA splash (hito 10). Yield instead.
                std::this_thread::yield();
#else
                std::this_thread::sleep_for(std::chrono::microseconds(500));
#endif
                break;
            }
            if (timeout > 0 && (host_ticks_ms() - t0) >= (u64)timeout)
                break;
            host_sleep_ms(1);
        }
        {
            static int nt = 0;
            if (nt++ < 20)
                LOGD("ALooper_pollAll -> TIMEOUT (timeout=%d)", timeout);
        }
        c.ret = (u64)(i64)-3; // ALOOPER_POLL_TIMEOUT
    });

    // ---- Input: AInputQueue backed by a host-side event FIFO ----
    // android_native_app_glue attaches the queue to its looper with
    // ident LOOPER_ID_INPUT; ALooper_pollAll (above) reports that ident
    // whenever input_pending() is true, and the glue then drains the queue
    // via AInputQueue_getEvent / preDispatch / finishEvent.
    register_host_fn("AInputQueue_attachLooper", [](GuestCall& c) {
        // (AInputQueue*, ALooper*, int ident, ALooper_callbackFunc cb, void* data)
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_input_ident = (int)(i32)c.x[2];
        g_input_data = c.x[4];
        LOGI("AInputQueue_attachLooper(ident=%d, data=0x%llx)", g_input_ident,
             (unsigned long long)g_input_data);
        c.ret = 0;
    });
    register_host_fn("AInputQueue_detachLooper", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_input_ident = -1;
        c.ret = 0;
    });
    register_host_fn("AInputQueue_getEvent", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        if (g_input_fifo.empty()) { c.ret = (u64)(i64)-1; return; }
        // Event handles are fixed native-data slots (ring of 64).
        static u64 slots = alloc_native_data(64 * 16, 16);
        static unsigned next = 0;
        u64 h = slots + (u64)(next++ % 64) * 16;
        g_input_live[h] = g_input_fifo.front();
        g_input_fifo.pop_front();
        if (c.x[1]) gwrite(c.x[1], &h, 8);
        c.ret = 0;
    });
    register_host_fn("AInputQueue_preDispatchEvent", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("AInputQueue_finishEvent", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_input_live.erase(c.x[1]);
        c.ret = 0;
    });
    register_host_fn("AInputEvent_getType", [](GuestCall& c) {
        c.ret = 2; // AINPUT_EVENT_TYPE_MOTION
    });
    register_host_fn("AMotionEvent_getAction", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        auto it = g_input_live.find(c.x[0]);
        c.ret = it != g_input_live.end() ? (u64)(i64)it->second.action : 0;
    });
    register_host_fn("AMotionEvent_getPointerCount", [](GuestCall& c) { c.ret = 1; });
    register_host_fn("AMotionEvent_getPointerId", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("AMotionEvent_getX", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        auto it = g_input_live.find(c.x[0]);
        c.set_f32(it != g_input_live.end() ? it->second.x : 0.f);
    });
    register_host_fn("AMotionEvent_getY", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        auto it = g_input_live.find(c.x[0]);
        c.set_f32(it != g_input_live.end() ? it->second.y : 0.f);
    });

    // ---- Sensors: a single virtual accelerometer driven by the keyboard ----
    register_host_fn("ASensorManager_getInstance", [](GuestCall& c) {
        static u64 mgr = alloc_native_data(16, 8);
        c.ret = mgr;
    });
    register_host_fn("ASensorManager_getDefaultSensor", [](GuestCall& c) {
        static u64 accel = alloc_native_data(16, 8);
        c.ret = ((i32)c.x[1] == 1) ? accel : 0; // only ASENSOR_TYPE_ACCELEROMETER
    });
    register_host_fn("ASensorManager_createEventQueue", [](GuestCall& c) {
        // (ASensorManager*, ALooper*, int ident, ALooper_callbackFunc cb, void* data)
        static u64 q = alloc_native_data(16, 8);
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_sensor_ident = (int)(i32)c.x[2];
        g_sensor_data = c.x[4];
        LOGI("ASensorManager_createEventQueue(ident=%d)", g_sensor_ident);
        c.ret = q;
    });
    register_host_fn("ASensorManager_destroyEventQueue", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_sensor_ident = -1;
        g_sensor_enabled = false;
        c.ret = 0;
    });
    register_host_fn("ASensorEventQueue_enableSensor", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_sensor_enabled = true;
        c.ret = 0;
    });
    register_host_fn("ASensorEventQueue_disableSensor", [](GuestCall& c) {
        std::lock_guard<std::mutex> lk(g_input_mutex);
        g_sensor_enabled = false;
        c.ret = 0;
    });
    register_host_fn("ASensorEventQueue_setEventRate", [](GuestCall& c) { c.ret = 0; });
    register_host_fn("ASensorEventQueue_getEvents", [](GuestCall& c) {
        // (ASensorEventQueue*, ASensorEvent* events, size_t count) -> n
        std::lock_guard<std::mutex> lk(g_input_mutex);
        u64 now = host_ticks_ms();
        if (!g_sensor_enabled || !c.x[1] || !c.x[2] || now - g_sensor_last_ms < 16) {
            c.ret = 0;
            return;
        }
        g_sensor_last_ms = now;
        // struct ASensorEvent (104 bytes): i32 version, sensor, type, reserved0;
        // i64 timestamp; float data[16] (acceleration x,y,z at +24) ; ...
        u8 ev[104] = {};
        i32 version = 104, sensor = 0, type = 1;
        i64 ts = (i64)now * 1000000;
        // Device held upright at ~45 degrees: gravity split between y and z.
        float acc[3] = {g_tilt_x, 6.93f, 6.93f};
        std::memcpy(ev + 0, &version, 4);
        std::memcpy(ev + 4, &sensor, 4);
        std::memcpy(ev + 8, &type, 4);
        std::memcpy(ev + 16, &ts, 8);
        std::memcpy(ev + 24, acc, 12);
        gwrite(c.x[1], ev, sizeof(ev));
        {
            static u64 last_log = 0;
            static u64 count = 0;
            ++count;
            if (now - last_log >= 1000) {
                last_log = now;
                LOGD("ASensorEventQueue_getEvents: %llu events so far, ax=%.2f",
                     (unsigned long long)count, g_tilt_x);
            }
        }
        c.ret = 1;
    });
}

// ---- input bridge (called from the SDL platform thread) ----
void input_push_touch(int action, float x, float y) {
    std::lock_guard<std::mutex> lk(g_input_mutex);
    if (g_input_fifo.size() > 256)
        g_input_fifo.pop_front();
    g_input_fifo.push_back({action, x, y});
    LOGD("input_push_touch(action=%d, %.0f, %.0f) ident=%d fifo=%zu", action, x, y,
         g_input_ident, g_input_fifo.size());
}

void input_set_tilt(float ax) {
    std::lock_guard<std::mutex> lk(g_input_mutex);
    if (!g_tilt_override)
        g_tilt_x = ax;
}

void input_set_tilt_override(float ax) {
    std::lock_guard<std::mutex> lk(g_input_mutex);
    g_tilt_override = true;
    g_tilt_x = ax;
}

} // namespace sjf
