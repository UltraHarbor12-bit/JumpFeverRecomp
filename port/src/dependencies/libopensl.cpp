// sjfport — OpenSL ES object model.
//
// The engine drives audio through the standard OpenSL object model:
//   slCreateEngine -> engine object -> Realize / GetInterface(SL_IID_ENGINE)
//   -> CreateOutputMix / CreateAudioPlayer -> Realize -> GetInterface
//      (SL_IID_PLAY / SL_IID_BUFFERQUEUE / SL_IID_VOLUME / SL_IID_PLAYBACKRATE)
//
// Every object is a guest struct { vtable } whose slots are svc-trampolines.
// Interfaces are identified by matching the IID blob addresses that the ELF
// loader bound for the SL_IID_* data imports.
//
// NOTE: slot orders follow the OpenSL ES 1.0.1 headers. If a slot mapping is
// wrong, the per-slot logging will show it (each slot logs on first use).
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/runtime.h"
#include "sjfport/audio.h"

#include <atomic>
#include <cmath>

#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>

namespace sjf {

namespace {

constexpr u32 SL_SUCCESS = 0;

std::map<u64, std::string> g_iid_names;   // IID blob addr -> name
std::map<u64, std::string> g_obj_kind;    // object addr -> kind
std::mutex g_sl_mutex;

u64 sl_fn(const std::string& name, HostFn fn) {
    return register_host_fn("SL:" + name, std::move(fn));
}

std::string iid_name(u64 iid) {
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    auto it = g_iid_names.find(iid);
    return it == g_iid_names.end() ? std::string("iid?") : it->second;
}

// ---------------------------------------------------------------------------
// generic vtable builder: `n` slots; pairs override the logging default
// ---------------------------------------------------------------------------
u64 vt_build(const std::string& prefix, int n,
             const std::vector<std::pair<int, HostFn>>& pairs) {
    std::map<int, HostFn> m;
    for (auto& pr : pairs)
        m[pr.first] = pr.second;
    u64 vt = alloc_native_data((u64)n * 8, 8);
    for (int i = 0; i < n; ++i) {
        auto it = m.find(i);
        std::string slot_name = prefix + ":s" + std::to_string(i);
        u64 tramp;
        if (it != m.end())
            tramp = sl_fn(slot_name, it->second);
        else
            tramp = sl_fn(slot_name + ":u", [prefix, i](GuestCall& c) {
                static std::mutex m2;
                static std::map<std::string, int> seen;
                {
                    std::lock_guard<std::mutex> lk(m2);
                    if (seen[prefix]++ < 10)
                        LOGD("SL %s slot %d (unimpl) x1=0x%llx x2=0x%llx", prefix.c_str(),
                             i, (unsigned long long)c.x[1], (unsigned long long)c.x[2]);
                }
                c.ret = SL_SUCCESS;
            });
        gwrite(vt + (u64)i * 8, &tramp, 8);
    }
    return vt;
}

// ---------------------------------------------------------------------------
// forward declarations
// ---------------------------------------------------------------------------
void h_object_getinterface(GuestCall& c);
void h_engine_createaudioplayer(GuestCall& c);
void h_engine_createoutputmix(GuestCall& c);
void h_player_getinterface(GuestCall& c);
void h_play_setplaystate(GuestCall& c);
void h_play_getplaystate(GuestCall& c);
void h_play_getposition(GuestCall& c);
void h_bq_enqueue(GuestCall& c);
void h_bq_registercallback(GuestCall& c);

// ---------------------------------------------------------------------------
// SLObjectItf (10 slots): 0 Realize, 3 GetInterface, 6 Destroy, rest logged
// ---------------------------------------------------------------------------
u64 make_object(const std::string& kind) {
    u64 vt = vt_build("obj:" + kind, 10, {
        {0, [](GuestCall& c) { c.ret = SL_SUCCESS; }},
        {3, [](GuestCall& c) { h_object_getinterface(c); }},
        {6, [](GuestCall& c) { c.ret = SL_SUCCESS; }},
    });
    u64 obj = alloc_native_data(8, 8);
    gwrite(obj, &vt, 8);
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        g_obj_kind[obj] = kind;
    }
    return obj;
}

void h_object_getinterface(GuestCall& c) {
    u64 self = c.x[0];
    std::string iid = iid_name(c.x[1]);
    std::string kind;
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        auto it = g_obj_kind.find(self);
        kind = it == g_obj_kind.end() ? "?" : it->second;
    }
    LOGD("SL %s->GetInterface(%s) raw=0x%llx CALLER_LR=0x%llx", kind.c_str(), iid.c_str(),
         (unsigned long long)c.x[1], (unsigned long long)c.lr);
    u64 itf = 0;
    if (kind == "engine" && iid == "SL_IID_ENGINE") {
        // SLEngineItf (10): 0 CreateLEDArray, 1 CreateAudioDecoder,
        // 2 CreateAudioEncoder, 3 CreateAudioPlayer, 4 CreateAudioRecorder,
        // 5 CreateMidiPlayer, 6 CreateMetadataExtractor, 7 CreateOutputStreamMix,
        // 8 CreateOutputMix, 9 CreateVibra
        // NOTE: this build's SLEngineItf has CreateOutputMix at slot 7
        // (2014-era header, no CreateOutputStreamMix) — verified empirically:
        // the engine calls slot 7 right after GetInterface(SL_IID_ENGINE).
        itf = vt_build("engine", 10, {
            {2, [](GuestCall& c) { h_engine_createaudioplayer(c); }},  // 2014 header slot
            {3, [](GuestCall& c) { h_engine_createaudioplayer(c); }},  // spec slot
            {7, [](GuestCall& c) { h_engine_createoutputmix(c); }},    // 2014 header slot
            {8, [](GuestCall& c) { h_engine_createoutputmix(c); }},    // spec slot
        });
    } else if (kind == "audioplayer") {
        // dispatch by IID below
        extern void h_player_getinterface(GuestCall& c);
        h_player_getinterface(c);
        return;
    }
    if (c.x[2]) {
        u64 itf_obj = alloc_native_data(8, 8);
        gwrite(itf_obj, &itf, 8);
        gwrite(c.x[2], &itf_obj, 8);
    }
    c.ret = SL_SUCCESS;
}

// ---------------------------------------------------------------------------
// SLEngineItf
// ---------------------------------------------------------------------------
// ---- per-player state (OpenSL audio player -> host mixer voice) ----
struct Player {
    int voice = -1;
    u32 play_state = 1;   // SL_PLAYSTATE_STOPPED
    u64 bq_itf = 0;       // guest SLBufferQueueItf handle (first callback arg)
    u64 cb = 0, cb_ctx = 0;
    i32 volume_mb = 0;    // millibel
    bool muted = false;
    u32 rate_pm = 1000;   // permille
};
std::map<u64, Player> g_players;   // player object -> state
std::map<u64, u64> g_itf_owner;    // interface handle -> player object

Player* player_for_itf(u64 itf) {  // caller holds g_sl_mutex
    auto it = g_itf_owner.find(itf);
    if (it == g_itf_owner.end())
        return nullptr;
    auto p = g_players.find(it->second);
    return p == g_players.end() ? nullptr : &p->second;
}

void apply_gain(Player& p) {
    float g = p.muted ? 0.f : std::pow(10.f, (float)p.volume_mb / 2000.f);
    audio_voice_set_gain(p.voice, g);
}

// ---------------------------------------------------------------------------
// SLEngineItf
// ---------------------------------------------------------------------------
void h_engine_createaudioplayer(GuestCall& c) {
    // (self, SLObjectItf* pPlayer, SLDataSource* pAudioSrc, SLDataSink* pAudioSnk,
    //  numInterfaces, iids, required)
    u64 obj = make_object("audioplayer");
    // SLDataSource { void* pLocator; void* pFormat; }
    // SLDataFormat_PCM { formatType=2, numChannels, samplesPerSec (mHz),
    //                    bitsPerSample, containerSize, channelMask, endianness }
    u32 channels = 1, rate_mhz = 44100000, bits = 16;
    if (c.x[2]) {
        u64 fmt = 0;
        gread(&fmt, c.x[2] + 8, 8);
        if (fmt) {
            u32 f[4] = {};
            gread(f, fmt, sizeof(f));
            if (f[0] == 2 /* SL_DATAFORMAT_PCM */) {
                channels = f[1];
                rate_mhz = f[2];
                bits = f[3];
            }
        }
    }
    int rate_hz = (int)(rate_mhz >= 1000 ? rate_mhz / 1000 : rate_mhz);
    int voice = audio_voice_create(rate_hz, (int)channels, (int)bits);
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        g_players[obj].voice = voice;
    }
    LOGI("SL CreateAudioPlayer -> 0x%llx (%u ch, %d Hz, %u bit, voice %d)",
         (unsigned long long)obj, channels, rate_hz, bits, voice);
    if (c.x[1])
        gwrite(c.x[1], &obj, 8);
    c.ret = SL_SUCCESS;
}

void h_engine_createoutputmix(GuestCall& c) {
    u64 obj = make_object("outputmix");
    LOGI("SL CreateOutputMix -> 0x%llx", (unsigned long long)obj);
    if (c.x[1])
        gwrite(c.x[1], &obj, 8);
    c.ret = SL_SUCCESS;
}

// ---------------------------------------------------------------------------
// player interfaces
// ---------------------------------------------------------------------------
void h_play_setplaystate(GuestCall& c) {
    u32 st = (u32)c.x[1]; // 1 STOPPED, 2 PAUSED, 3 PLAYING
    static std::atomic<int> nlog{0};
    if (nlog++ < 30)
        LOGD("SL Play::SetPlayState(itf=0x%llx, %u)", (unsigned long long)c.x[0], st);
    int voice = -1;
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        Player* p = player_for_itf(c.x[0]);
        if (!p) { c.ret = SL_SUCCESS; return; }
        p->play_state = st;
        voice = p->voice;
    }
    if (st == 1)
        audio_voice_clear(voice); // STOPPED rewinds and drops queued buffers
    audio_voice_set_playing(voice, st == 3);
    c.ret = SL_SUCCESS;
}

void h_play_getplaystate(GuestCall& c) {
    u32 st = 1;
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        if (Player* p = player_for_itf(c.x[0]))
            st = p->play_state;
    }
    if (c.x[1])
        gwrite(c.x[1], &st, 4);
    c.ret = SL_SUCCESS;
}

void h_play_getposition(GuestCall& c) {
    if (c.x[1]) {
        u32 ms = 0;
        gwrite(c.x[1], &ms, 4);
    }
    c.ret = SL_SUCCESS;
}

void h_player_getinterface(GuestCall& c) {
    std::string iid = iid_name(c.x[1]);
    LOGD("SL player->GetInterface(%s)", iid.c_str());
    u64 itf = 0;
    if (iid == "SL_IID_PLAY") {
        // SLPlayItf (8): 0 SetPlayState, 1 GetPlayState, 2 GetDuration,
        // 3 GetPosition, 4 RegisterCallback, 5 SetCallbackEventsMask,
        // 6 SetPositionUpdatePeriod, 7 GetPositionUpdatePeriod
        itf = vt_build("play", 8, {
            {0, [](GuestCall& c) { h_play_setplaystate(c); }},
            {1, [](GuestCall& c) { h_play_getplaystate(c); }},
            {3, [](GuestCall& c) { h_play_getposition(c); }},
        });
    } else if (iid == "SL_IID_BUFFERQUEUE") {
        // SLBufferQueueItf (4): 0 Enqueue, 1 Clear, 2 GetState, 3 RegisterCallback
        itf = vt_build("bq", 8, {
            {0, [](GuestCall& c) { h_bq_enqueue(c); }},
            {1, [](GuestCall& c) {
                 int v = -1;
                 { std::lock_guard<std::mutex> lk(g_sl_mutex);
                   if (Player* p = player_for_itf(c.x[0])) v = p->voice; }
                 audio_voice_clear(v);
                 c.ret = SL_SUCCESS; }},
            {2, [](GuestCall& c) {
                 // SLBufferQueueState { u32 count; u32 playIndex; }
                 int v = -1;
                 { std::lock_guard<std::mutex> lk(g_sl_mutex);
                   if (Player* p = player_for_itf(c.x[0])) v = p->voice; }
                 u32 st[2] = {0, 0};
                 audio_voice_get_state(v, &st[0], &st[1]);
                 if (c.x[1]) gwrite(c.x[1], st, sizeof(st));
                 c.ret = SL_SUCCESS; }},
            {3, [](GuestCall& c) { h_bq_registercallback(c); }},
        });
    } else if (iid == "SL_IID_VOLUME") {
        // SLVolumeItf (9): 0 SetVolumeLevel, 1 GetVolumeLevel, 2 GetMaxVolumeLevel,
        // 3 SetMute, 4 GetMute, 5 EnableStereoPosition, ...
        itf = vt_build("vol", 9, {
            {0, [](GuestCall& c) {
                 std::lock_guard<std::mutex> lk(g_sl_mutex);
                 if (Player* p = player_for_itf(c.x[0])) {
                     p->volume_mb = (i32)(i16)(u16)c.x[1];
                     apply_gain(*p);
                 }
                 c.ret = SL_SUCCESS; }},
            {1, [](GuestCall& c) {
                 i16 mb = 0;
                 { std::lock_guard<std::mutex> lk(g_sl_mutex);
                   if (Player* p = player_for_itf(c.x[0])) mb = (i16)p->volume_mb; }
                 if (c.x[1]) gwrite(c.x[1], &mb, 2);
                 c.ret = SL_SUCCESS; }},
            {2, [](GuestCall& c) {
                 i16 mx = 0;
                 if (c.x[1]) gwrite(c.x[1], &mx, 2);
                 c.ret = SL_SUCCESS; }},
            {3, [](GuestCall& c) {
                 std::lock_guard<std::mutex> lk(g_sl_mutex);
                 if (Player* p = player_for_itf(c.x[0])) {
                     p->muted = (u32)c.x[1] != 0;
                     apply_gain(*p);
                 }
                 c.ret = SL_SUCCESS; }},
        });
    } else if (iid == "SL_IID_PLAYBACKRATE") {
        // SLPlaybackRateItf (4): 0 SetRate, 1 GetRate, 2 SetPropertyConstraints,
        // 3 GetProperties
        itf = vt_build("rate", 4, {
            {0, [](GuestCall& c) {
                 std::lock_guard<std::mutex> lk(g_sl_mutex);
                 if (Player* p = player_for_itf(c.x[0])) {
                     p->rate_pm = (u32)(i32)(i16)(u16)c.x[1];
                     audio_voice_set_rate(p->voice, p->rate_pm / 1000.f);
                 }
                 c.ret = SL_SUCCESS; }},
            {1, [](GuestCall& c) {
                 i16 r = 1000;
                 { std::lock_guard<std::mutex> lk(g_sl_mutex);
                   if (Player* p = player_for_itf(c.x[0])) r = (i16)p->rate_pm; }
                 if (c.x[1]) gwrite(c.x[1], &r, 2);
                 c.ret = SL_SUCCESS; }},
        });
    }
    if (c.x[2]) {
        u64 itf_obj = alloc_native_data(8, 8);
        gwrite(itf_obj, &itf, 8);
        gwrite(c.x[2], &itf_obj, 8);
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        g_itf_owner[itf_obj] = c.x[0];
        if (iid == "SL_IID_BUFFERQUEUE")
            g_players[c.x[0]].bq_itf = itf_obj;
    }
    c.ret = SL_SUCCESS;
}

void h_bq_enqueue(GuestCall& c) {
    // (self, const void* pBuffer, SLuint32 size): PCM from the engine.
    int v = -1;
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        if (Player* p = player_for_itf(c.x[0])) v = p->voice;
    }
    const void* host = guest_to_host(c.x[1]);
    u32 size = (u32)c.x[2];
    static int n = 0;
    if (n++ < 10)
        LOGD("SL BufferQueue::Enqueue(voice=%d, size=%u)", v, size);
    if (host && size)
        audio_voice_enqueue(v, host, size);
    c.ret = SL_SUCCESS;
}

void h_bq_registercallback(GuestCall& c) {
    // (self, slBufferQueueCallback cb, void* ctx); cb(SLBufferQueueItf, ctx)
    u64 self = c.x[0], cb = c.x[1], ctx = c.x[2];
    int v = -1;
    {
        std::lock_guard<std::mutex> lk(g_sl_mutex);
        if (Player* p = player_for_itf(self)) {
            p->cb = cb;
            p->cb_ctx = ctx;
            v = p->voice;
        }
    }
    LOGD("SL BufferQueue::RegisterCallback(cb=0x%llx ctx=0x%llx voice=%d)",
         (unsigned long long)cb, (unsigned long long)ctx, v);
    if (cb)
        audio_voice_set_callback(v, [self, cb, ctx, v]() {
            static std::atomic<int> n{0};
            if (n++ < 5)
                LOGD("SL buffer-queue callback (voice %d)", v);
            guest_call(cb, self, ctx, 0, 0, 0, 0, 0, 0, nullptr);
        });
    else
        audio_voice_set_callback(v, nullptr);
    c.ret = SL_SUCCESS;
}

} // namespace

void register_libOpenSLES_module() {
    register_host_fn("slCreateEngine", [](GuestCall& c) {
        u64 obj = make_object("engine");
        if (c.x[0])
            gwrite(c.x[0], &obj, 8);
        LOGI("slCreateEngine -> object 0x%llx", (unsigned long long)obj);
        c.ret = SL_SUCCESS;
    });
}

// Called by the ELF loader for each bound SL_IID_* data import.
void sl_bind_iid(const char* name, u64 blob_addr) {
    // On Android the imported `SL_IID_x` symbol is a POINTER VARIABLE whose
    // value (owned by libOpenSLES.so) points to the SLInterfaceID struct.
    // The engine loads the variable then dereferences it, so our blob must
    // contain a pointer to a fake (unique) 16-byte SLInterfaceID.
    static u32 counter = 0x51D10000;
    u64 st = alloc_native_data(16, 4);
    u32 id[4] = {counter++, 0x51D10000u, 0x4F50454Eu, 0x00000000u};
    gwrite(st, id, 16);
    u64 nullv = 0;
    (void)nullv;
    gwrite(blob_addr, &st, 8);
    std::lock_guard<std::mutex> lk(g_sl_mutex);
    g_iid_names[st] = name;
    LOGI("SL bind %s: var@0x%llx -> id 0x%llx", name, (unsigned long long)blob_addr,
         (unsigned long long)st);
}

} // namespace sjf
