// sjfport — fake JNI: JavaVM + JNIEnv with a full 233-slot JNINativeInterface.
//
// Object model: every jobject/jclass/jmethodID is a small guest-memory handle
// registered in g_fakes. Method calls are dispatched by *name*, which is
// enough to serve the engine's platform needs (files dir, rotation, music...).
#include "sjfport/common.h"
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/elf_loader.h"
#include "sjfport/jni_env.h"
#include "sjfport/runtime.h"

#include <jni.h>
#include "sjfport/audio.h"

#include <cstring>
#include <filesystem>
#include <map>
#include <mutex>
#include <string>

#include "jni_table_names.h"

namespace sjf {

namespace {

u64 g_vm_guest = 0;
u64 g_env_guest = 0;
std::string g_data_dir;
bool g_verbose_jni = true;

enum class FakeKind : u32 { Class = 0x434C4153, Object = 0x4F424A54, String = 0x53545247 };
constexpr u32 kFakeMagic = 0x4A4E4946; // "JNIF"

struct FakeMeta {
    FakeKind kind = FakeKind::Object;
    std::string name;   // class name / method name
    std::string sig;    // method signature
    std::string sval;   // payload (File path, etc.)
    u64 cls = 0;
};
std::map<u64, FakeMeta> g_fakes;
std::mutex g_fake_mutex;

u64 make_fake(FakeKind kind, const std::string& name, const std::string& sig = {},
              u64 cls = 0, const std::string& sval = {}) {
    u64 g = alloc_native_data(16, 8);
    if (!g)
        return 0;
    u32 magic = kFakeMagic, k = (u32)kind;
    gwrite(g, &magic, 4);
    gwrite(g + 4, &k, 4);
    std::lock_guard<std::mutex> lk(g_fake_mutex);
    FakeMeta m;
    m.kind = kind;
    m.name = name;
    m.sig = sig;
    m.sval = sval;
    m.cls = cls;
    g_fakes[g] = m;
    return g;
}

// Method/field IDs and class handles are immutable: intern them so hot paths
// (the engine re-resolves IDs every frame, ~40k calls/s from the net/ads
// pumps) do not leak a native-data block per call and exhaust the region.
u64 make_fake_interned(FakeKind kind, const std::string& name, const std::string& sig = {},
                       u64 cls = 0) {
    static std::mutex m;
    static std::map<std::string, u64> cache;
    std::string key = std::to_string((int)kind) + '\x1f' + name + '\x1f' + sig + '\x1f' +
                      std::to_string(cls);
    {
        std::lock_guard<std::mutex> lk(m);
        auto it = cache.find(key);
        if (it != cache.end())
            return it->second;
    }
    u64 g = make_fake(kind, name, sig, cls);
    if (g) {
        std::lock_guard<std::mutex> lk(m);
        cache.emplace(key, g);
    }
    return g;
}

FakeMeta* fake_of(u64 handle) {
    if (!handle)
        return nullptr;
    std::lock_guard<std::mutex> lk(g_fake_mutex);
    auto it = g_fakes.find(handle);
    return it == g_fakes.end() ? nullptr : &it->second;
}

u64 make_string(const std::string& s) {
    // Guest heap (4 GiB), not the 16 MiB native-data region: NewStringUTF is hot.
    u64 g = guest_heap_alloc(8 + s.size() + 1);
    if (!g)
        return 0;
    u32 magic = kFakeMagic, kind = (u32)FakeKind::String;
    gwrite(g, &magic, 4);
    gwrite(g + 4, &kind, 4);
    gwrite(g + 8, s.c_str(), s.size() + 1);
    std::lock_guard<std::mutex> lk(g_fake_mutex);
    g_fakes[g] = FakeMeta{FakeKind::String, "java/lang/String", {}, s, 0};
    return g;
}

u64 make_file(const std::string& path) {
    return make_fake(FakeKind::Object, "java/io/File", {}, 0, path);
}

// ---------------------------------------------------------------------------
// Java call arguments. Call<T>Method(env, obj, mid, ...) passes them as C
// varargs (x3..x7, then stack; floats promoted to double in v0..v7),
// Call<T>MethodV passes an AArch64 va_list (pointer to
// {__stack, __gr_top, __vr_top, i32 __gr_offs, i32 __vr_offs}).
// ---------------------------------------------------------------------------
struct JniArgs {
    GuestCall* c = nullptr;
    bool is_va_list = false;
    // va_list cursor
    u64 stack = 0, gr_top = 0, vr_top = 0;
    i32 gr_offs = 0, vr_offs = 0;
    // varargs cursor
    int next_x = 3, next_v = 0;
    u64 next_stack = 0;

    void init(GuestCall& call, const char* jni_name) {
        c = &call;
        size_t n = std::strlen(jni_name);
        is_va_list = n && jni_name[n - 1] == 'V';
        if (is_va_list && c->x[3]) {
            gread(&stack, c->x[3] + 0, 8);
            gread(&gr_top, c->x[3] + 8, 8);
            gread(&vr_top, c->x[3] + 16, 8);
            gread(&gr_offs, c->x[3] + 24, 4);
            gread(&vr_offs, c->x[3] + 28, 4);
        }
        next_x = 3;
        next_v = 0;
        next_stack = c->sp;
    }
    u64 gp() {
        u64 v = 0;
        if (!c) return 0;
        if (is_va_list) {
            if (gr_offs < 0) { gread(&v, gr_top + (i64)gr_offs, 8); gr_offs += 8; }
            else { gread(&v, stack, 8); stack += 8; }
        } else if (next_x <= 7) {
            v = c->x[next_x++];
        } else {
            gread(&v, next_stack, 8);
            next_stack += 8;
        }
        return v;
    }
    double fp() { // float/double argument (varargs promote float -> double)
        double d = 0;
        if (!c) return 0;
        if (is_va_list) {
            if (vr_offs < 0) { gread(&d, vr_top + (i64)vr_offs, 8); vr_offs += 16; }
            else { gread(&d, stack, 8); stack += 8; }
        } else if (next_v <= 7) {
            u64 bits = c->v[next_v++];
            std::memcpy(&d, &bits, 8);
        } else {
            gread(&d, next_stack, 8);
            next_stack += 8;
        }
        return d;
    }
};
thread_local JniArgs t_args;

// ---------------------------------------------------------------------------
// Java-side behaviour the engine depends on
// ---------------------------------------------------------------------------
u64 invoke_method(u64 obj_or_class, u64 method_id, bool is_static, const char* jni_name) {
    FakeMeta* m = fake_of(method_id);
    if (!m) {
        LOGW("%s: unknown method id 0x%llx", jni_name, (unsigned long long)method_id);
        return 0;
    }
    const std::string& n = m->name;
    FakeMeta* self = fake_of(obj_or_class);
    if (g_verbose_jni)
        LOGD("JNI call %s%s.%s", is_static ? "static " : "",
             self ? self->name.c_str() : "?", n.c_str());

    // ---- android.app.NativeActivity ----
    if (n == "getFilesDir" || n == "getCacheDir" || n == "getDir" ||
        n == "getExternalFilesDir" || n == "getExternalCacheDir")
        return make_file(g_data_dir);
    if (n == "getPackageName")
        return make_string("com.sega.sonicjumpfever");
    if (n == "getPackageCodePath" || n == "getPackageResourcePath")
        return make_string("game/base.apk");
    if (n == "getAssets")
        return make_fake(FakeKind::Object, "android/content/res/AssetManager");
    if (n == "getResources")
        return make_fake(FakeKind::Object, "android/content/res/Resources");

    // ---- java.io.File ----
    if (n == "getPath" || n == "getAbsolutePath" || n == "getCanonicalPath")
        return make_string(self ? self->sval : g_data_dir);
    if (n == "exists")
        return 0;
    if (n == "mkdir" || n == "mkdirs")
        return 1;
    if (n == "getName" || n == "getParent" || n == "getParentFile")
        return 0;
    if (n == "listFiles" || n == "list")
        return 0;

    // ---- com.sega.sonicjumpfever.Loader ----
    if (n == "getRotation")
        return 0; // portrait
    if (n == "getLanguage")
        return make_string("en");
    if (n == "getLocaleISO3CountryCode")
        return make_string("USA");
    if (n == "getPlayerName")
        return make_string("");
    if (n == "getIsFirstRun")
        return 0;
    if (n == "getApkFileName")
        return make_string("game/base.apk");
    if (n == "isTabletDevice")
        return 0;

    // ---- network / services: "connected" behaviour ----
    // Softlight.isConnected() fires an ASYNC Java check whose result reaches
    // the engine through the native isConnectedCallBack(bool). Our fake Java
    // calls that native export directly (connected = true).
    if (n == "isConnected" && self && self->name == "com/sega/sonicjumpfever/Softlight") {
        u64 cb = 0;
        if (const LoadedElf* elf = global_loaded_elf())
            cb = elf_find_symbol(*elf,
                                 "Java_com_sega_sonicjumpfever_checkNetwork_isConnectedCallBack");
        if (cb) {
            static int ic_count = 0;
            if (ic_count++ < 3)
                LOGI("JNI Softlight.isConnected -> firing native isConnectedCallBack(true)");
            guest_call_nested(cb, jni_env_guest(), 0, 1, 0, 0, 0, 0, 0);
        }
        return 0;
    }
    if (n == "isConnected" || n == "isConnectedToNetwork")
        return 1;
    if (n == "getData" || n == "startThread" || n == "openURL" || n == "tryOpenURL")
        return 0;
    if (n == "rateThisApp")
        return 0;

    // ---- java.util.HashMap ----
    if (n == "put" || n == "<init>")
        return obj_or_class;
    if (n == "get")
        return 0;
    if (n == "size")
        return 0;

    // ---- musicplayer (background music) ----
    if (self && self->name == "com/sega/sonicjumpfever/musicplayer") {
        if (n == "PlayAudioFile") { // (String path, boolean loop, boolean ?)
            u64 js = t_args.gp();
            bool loop = (t_args.gp() & 0xff) != 0;
            FakeMeta* sm = fake_of(js);
            std::string path = sm ? sm->sval : std::string();
            std::string res = host_resolve_path(path);
            LOGI("musicplayer.PlayAudioFile(\"%s\", loop=%d) -> %s", path.c_str(), (int)loop,
                 res.c_str());
            audio_music_play(res, loop);
            if (path.find("frontend") != std::string::npos)
                profile_edit_notify_frontend();
            return 0;
        }
        if (n == "setVolume") {
            audio_music_set_volume((float)t_args.fp());
            return 0;
        }
        if (n == "setPause") {
            audio_music_set_pause((t_args.gp() & 0xff) != 0);
            return 0;
        }
        if (n.rfind("stop", 0) == 0 || n.rfind("Stop", 0) == 0 || n == "release") {
            audio_music_stop();
            return 0;
        }
        if (n == "resume" || n == "Resume") {
            audio_music_set_pause(false);
            return 0;
        }
        if (n == "pause" || n == "Pause") {
            audio_music_set_pause(true);
            return 0;
        }
        LOGI("musicplayer.%s() [unhandled]", n.c_str());
        return 0;
    }
    if (n.rfind("play", 0) == 0 || n.rfind("stop", 0) == 0 || n.rfind("pause", 0) == 0 ||
        n.rfind("resume", 0) == 0 || n.rfind("set", 0) == 0 || n.rfind("init", 0) == 0 ||
        n.rfind("release", 0) == 0 || n.rfind("mute", 0) == 0 || n.rfind("fade", 0) == 0) {
        LOGD("musicplayer.%s() [stub]", n.c_str());
        return 0;
    }

    LOGD("%s: %s.%s(...) -> default", jni_name,
         self ? self->name.c_str() : (is_static ? "static" : "obj"), n.c_str());
    return 0;
}

u64 jni_fn(const std::string& jni_name, HostFn fn) {
    return register_host_fn("JNI:" + jni_name, std::move(fn));
}

} // namespace

void jni_set_data_path(const std::string& path) { g_data_dir = path; }
u64 jni_vm_guest() { return g_vm_guest; }
u64 jni_env_guest() { return g_env_guest; }

bool jni_env_init() {
    if (g_data_dir.empty()) {
        std::error_code ec;
        auto cwd = std::filesystem::current_path(ec);
        g_data_dir = ec ? std::string("game/data") : (cwd / "game" / "data").string();
    }
    std::error_code ec;
    std::filesystem::create_directories(g_data_dir, ec);

    u64 table = alloc_native_data((u64)kJNINativeInterfaceCount * 8ull, 8);
    if (!table) {
        LOGE("jni_env_init: cannot allocate native interface table");
        return false;
    }

    // default: each slot logs its own name once, returns 0
    for (unsigned i = 0; i < kJNINativeInterfaceCount; ++i) {
        std::string slot_name = kJNINativeInterfaceNames[i];
        u64 tramp = jni_fn("unimpl_" + slot_name, [slot_name](GuestCall& c) {
            static std::mutex m;
            static std::map<std::string, int> seen;
            {
                std::lock_guard<std::mutex> lk(m);
                if (seen[slot_name]++ == 0)
                    LOGW("JNI call not implemented: %s (further calls quiet)", slot_name.c_str());
            }
            c.ret = 0;
        });
        gwrite(table + (u64)i * 8, &tramp, 8);
    }

    auto set = [&](const char* field_name, const char* log_name, HostFn fn) {
        for (unsigned i = 0; i < kJNINativeInterfaceCount; ++i) {
            if (std::strcmp(kJNINativeInterfaceNames[i], field_name) == 0) {
                u64 tramp = jni_fn(std::string("impl_") + log_name, std::move(fn));
                gwrite(table + (u64)i * 8, &tramp, 8);
                return;
            }
        }
        LOGE("jni_env_init: field %s not found in table", field_name);
    };

    // ---------- core ----------
    set("GetVersion", "GetVersion", [](GuestCall& c) { c.ret = 0x00010006; });

    set("FindClass", "FindClass", [](GuestCall& c) {
        std::string name = gstr(c.x[1]);
        LOGD("JNI FindClass(\"%s\")", name.c_str());
        c.ret = make_fake_interned(FakeKind::Class, name);
    });
    set("GetObjectClass", "GetObjectClass", [](GuestCall& c) {
        FakeMeta* f = fake_of(c.x[1]);
        c.ret = make_fake_interned(FakeKind::Class, f ? f->name : "?");
    });
    set("GetMethodID", "GetMethodID", [](GuestCall& c) {
        std::string name = gstr(c.x[2]), sig = gstr(c.x[3]);
        FakeMeta* cls = fake_of(c.x[1]);
        if (g_verbose_jni)
            LOGD("JNI GetMethodID(%s, \"%s\", \"%s\")", cls ? cls->name.c_str() : "?",
                 name.c_str(), sig.c_str());
        c.ret = make_fake_interned(FakeKind::Object, name, sig, c.x[1]);
    });
    set("GetStaticMethodID", "GetStaticMethodID", [](GuestCall& c) {
        std::string name = gstr(c.x[2]), sig = gstr(c.x[3]);
        FakeMeta* cls = fake_of(c.x[1]);
        if (g_verbose_jni)
            LOGD("JNI GetStaticMethodID(%s, \"%s\", \"%s\")", cls ? cls->name.c_str() : "?",
                 name.c_str(), sig.c_str());
        c.ret = make_fake_interned(FakeKind::Object, name, sig, c.x[1]);
    });
    set("GetFieldID", "GetFieldID", [](GuestCall& c) {
        c.ret = make_fake_interned(FakeKind::Object, gstr(c.x[2]), gstr(c.x[3]), c.x[1]);
    });
    set("GetStaticFieldID", "GetStaticFieldID", [](GuestCall& c) {
        c.ret = make_fake_interned(FakeKind::Object, gstr(c.x[2]), gstr(c.x[3]), c.x[1]);
    });

    set("NewGlobalRef", "NewGlobalRef", [](GuestCall& c) { c.ret = c.x[1]; });
    set("NewLocalRef", "NewLocalRef", [](GuestCall& c) { c.ret = c.x[1]; });
    set("DeleteGlobalRef", "DeleteGlobalRef", [](GuestCall& c) { c.ret = 0; });
    set("DeleteLocalRef", "DeleteLocalRef", [](GuestCall& c) { c.ret = 0; });
    set("IsSameObject", "IsSameObject", [](GuestCall& c) { c.ret = (c.x[1] == c.x[2]) ? 1 : 0; });

    // ---------- strings ----------
    set("NewStringUTF", "NewStringUTF", [](GuestCall& c) { c.ret = make_string(gstr(c.x[1])); });
    set("GetStringUTFLength", "GetStringUTFLength", [](GuestCall& c) {
        FakeMeta* s = fake_of(c.x[1]);
        c.ret = s ? s->sval.size() : 0;
    });
    set("GetStringUTFChars", "GetStringUTFChars", [](GuestCall& c) {
        if (c.x[2]) { u8 zero = 0; gwrite(c.x[2], &zero, 1); }
        c.ret = c.x[1] ? c.x[1] + 8 : 0; // strings store their bytes inline
    });
    set("ReleaseStringUTFChars", "ReleaseStringUTFChars", [](GuestCall& c) { c.ret = 0; });
    set("GetStringLength", "GetStringLength", [](GuestCall& c) {
        FakeMeta* s = fake_of(c.x[1]);
        c.ret = s ? s->sval.size() : 0;
    });

    // ---------- method invocation (dispatch by name) ----------
    auto call_handler = [](const char* jni_name, bool is_static) {
        return [jni_name, is_static](GuestCall& c) {
            t_args.init(c, jni_name);
            c.ret = invoke_method(c.x[1], c.x[2], is_static, jni_name);
        };
    };
    const char* instance_calls[] = {
        "CallObjectMethodV", "CallBooleanMethodV", "CallByteMethodV", "CallCharMethodV",
        "CallShortMethodV", "CallIntMethodV", "CallLongMethodV", "CallFloatMethodV",
        "CallDoubleMethodV", "CallVoidMethodV", "CallObjectMethod", "CallIntMethod",
        "CallBooleanMethod", "CallVoidMethod", "CallFloatMethod", "CallDoubleMethod",
        "CallLongMethod", "CallShortMethod", "CallByteMethod", "CallCharMethod"};
    for (const char* f : instance_calls)
        set(f, f, call_handler(f, false));

    const char* static_calls[] = {
        "CallStaticObjectMethodV", "CallStaticBooleanMethodV", "CallStaticByteMethodV",
        "CallStaticCharMethodV", "CallStaticShortMethodV", "CallStaticIntMethodV",
        "CallStaticLongMethodV", "CallStaticFloatMethodV", "CallStaticDoubleMethodV",
        "CallStaticVoidMethodV", "CallStaticObjectMethod", "CallStaticIntMethod",
        "CallStaticBooleanMethod", "CallStaticVoidMethod", "CallStaticFloatMethod",
        "CallStaticDoubleMethod", "CallStaticLongMethod"};
    for (const char* f : static_calls)
        set(f, f, call_handler(f, true));

    set("NewObjectV", "NewObjectV", [](GuestCall& c) {
        FakeMeta* cls = fake_of(c.x[1]);
        c.ret = make_fake(FakeKind::Object, cls ? cls->name : "java/lang/Object");
    });
    set("NewObject", "NewObject", [](GuestCall& c) {
        FakeMeta* cls = fake_of(c.x[1]);
        c.ret = make_fake(FakeKind::Object, cls ? cls->name : "java/lang/Object");
    });
    set("AllocObject", "AllocObject", [](GuestCall& c) {
        FakeMeta* cls = fake_of(c.x[1]);
        c.ret = make_fake(FakeKind::Object, cls ? cls->name : "java/lang/Object");
    });

    // ---------- fields ----------
    set("GetStaticObjectField", "GetStaticObjectField", [](GuestCall& c) { c.ret = 0; });
    set("GetObjectField", "GetObjectField", [](GuestCall& c) { c.ret = 0; });
    set("GetIntField", "GetIntField", [](GuestCall& c) { c.ret = 0; });
    set("GetStaticIntField", "GetStaticIntField", [](GuestCall& c) { c.ret = 0; });
    set("GetBooleanField", "GetBooleanField", [](GuestCall& c) { c.ret = 0; });
    set("GetStaticBooleanField", "GetStaticBooleanField", [](GuestCall& c) { c.ret = 0; });
    set("SetObjectField", "SetObjectField", [](GuestCall& c) { c.ret = 0; });
    set("SetIntField", "SetIntField", [](GuestCall& c) { c.ret = 0; });
    set("SetStaticIntField", "SetStaticIntField", [](GuestCall& c) { c.ret = 0; });
    set("SetBooleanField", "SetBooleanField", [](GuestCall& c) { c.ret = 0; });

    // ---------- misc ----------
    set("RegisterNatives", "RegisterNatives", [](GuestCall& c) {
        FakeMeta* cls = fake_of(c.x[1]);
        LOGI("JNI RegisterNatives(%s, %d)", cls ? cls->name.c_str() : "?", (int)(i32)c.x[3]);
        c.ret = 0;
    });
    set("ExceptionCheck", "ExceptionCheck", [](GuestCall& c) { c.ret = 0; });
    set("ExceptionClear", "ExceptionClear", [](GuestCall& c) { c.ret = 0; });
    set("ExceptionOccurred", "ExceptionOccurred", [](GuestCall& c) { c.ret = 0; });
    set("GetJavaVM", "GetJavaVM", [](GuestCall& c) {
        if (c.x[1]) gwrite(c.x[1], &g_vm_guest, 8);
        c.ret = 0;
    });
    set("PushLocalFrame", "PushLocalFrame", [](GuestCall& c) { c.ret = 0; });
    set("PopLocalFrame", "PopLocalFrame", [](GuestCall& c) { c.ret = 0; });
    set("MonitorEnter", "MonitorEnter", [](GuestCall& c) { c.ret = 0; });
    set("MonitorExit", "MonitorExit", [](GuestCall& c) { c.ret = 0; });
    set("GetObjectRefType", "GetObjectRefType", [](GuestCall& c) { c.ret = 3; });
    set("GetArrayLength", "GetArrayLength", [](GuestCall& c) { c.ret = 0; });
    set("NewDirectByteBuffer", "NewDirectByteBuffer", [](GuestCall& c) { c.ret = 0; });
    set("GetDirectBufferAddress", "GetDirectBufferAddress", [](GuestCall& c) { c.ret = 0; });
    set("GetDirectBufferCapacity", "GetDirectBufferCapacity", [](GuestCall& c) { c.ret = 0; });
    set("FatalError", "FatalError", [](GuestCall& c) {
        LOGE("JNI FatalError: %s", gstr(c.x[1]).c_str());
        std::abort();
    });

    // ---------- JNIEnv ----------
    g_env_guest = alloc_native_data(8, 8);
    if (!g_env_guest) return false;
    gwrite(g_env_guest, &table, 8);

    // ---------- JavaVM ----------
    u64 invoke = alloc_native_data(8 * 9, 8);
    if (!invoke) return false;
    auto set_invoke = [&](unsigned idx, const char* name, HostFn fn) {
        u64 tramp = jni_fn(std::string("invoke_") + name, std::move(fn));
        gwrite(invoke + (u64)idx * 8, &tramp, 8);
    };
    u64 zero = 0;
    for (unsigned i = 0; i < 3; ++i) gwrite(invoke + (u64)i * 8, &zero, 8);
    set_invoke(3, "DestroyJavaVM", [](GuestCall& c) { c.ret = 0; });
    set_invoke(4, "AttachCurrentThread", [](GuestCall& c) {
        if (c.x[1]) gwrite(c.x[1], &g_env_guest, 8);
        c.ret = 0;
    });
    set_invoke(5, "DetachCurrentThread", [](GuestCall& c) { c.ret = 0; });
    set_invoke(6, "GetEnv", [](GuestCall& c) {
        if (c.x[1]) gwrite(c.x[1], &g_env_guest, 8);
        c.ret = 0;
    });
    set_invoke(7, "AttachCurrentThreadAsDaemon", [](GuestCall& c) {
        if (c.x[1]) gwrite(c.x[1], &g_env_guest, 8);
        c.ret = 0;
    });

    g_vm_guest = alloc_native_data(8, 8);
    if (!g_vm_guest) return false;
    gwrite(g_vm_guest, &invoke, 8);

    LOGI("jni: JavaVM @0x%llx, JNIEnv @0x%llx, data dir: %s", (unsigned long long)g_vm_guest,
         (unsigned long long)g_env_guest, g_data_dir.c_str());
    return true;
}

} // namespace sjf
