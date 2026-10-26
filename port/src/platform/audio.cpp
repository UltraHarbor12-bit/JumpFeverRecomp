// sjfport — SDL2 audio output + software mixer (see sjfport/audio.h)
#include "sjfport/audio.h"

#include <SDL.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

extern "C" int stb_vorbis_decode_filename(const char* filename, int* channels, int* sample_rate,
                                          short** output);

namespace sjf {

namespace {

constexpr int kOutRate = 44100;
constexpr int kOutChannels = 2;

struct Buffer {
    const u8* data;
    u32 size;
};

struct Voice {
    int rate = 44100, channels = 1, bits = 16;
    std::deque<Buffer> queue;
    double pos = 0.0;      // fractional frame position inside queue.front()
    u32 play_index = 0;    // buffers completed since creation
    bool playing = false;
    float gain = 1.f;
    float rate_mul = 1.f;
    std::function<void()> on_done;
};

struct Music {
    std::vector<float> pcm; // interleaved stereo @ kOutRate
    size_t pos = 0;
    bool loop = false;
    bool active = false;
    bool paused = false;
    float volume = 1.f;
};

std::mutex g_mix_mutex;                       // guards voices + music
std::vector<std::unique_ptr<Voice>> g_voices;
Music g_music;
SDL_AudioDeviceID g_dev = 0;
bool g_tried = false;

// ---- callback thread: runs guest buffer-queue callbacks off the device thread ----
std::mutex g_cb_mutex;
std::condition_variable g_cb_cv;
std::deque<std::function<void()>> g_cb_queue;
std::atomic<bool> g_cb_run{false};
std::thread g_cb_thread;

void cb_post(std::function<void()> f) {
    {
        std::lock_guard<std::mutex> lk(g_cb_mutex);
        g_cb_queue.push_back(std::move(f));
    }
    g_cb_cv.notify_one();
}

void cb_loop() {
    while (g_cb_run) {
        std::function<void()> f;
        {
            std::unique_lock<std::mutex> lk(g_cb_mutex);
            g_cb_cv.wait(lk, [] { return !g_cb_queue.empty() || !g_cb_run; });
            if (!g_cb_run)
                break;
            f = std::move(g_cb_queue.front());
            g_cb_queue.pop_front();
        }
        if (f)
            f();
    }
}

inline float sample_at(const Voice& v, const Buffer& b, u32 frame, int ch) {
    int c = v.channels > 1 ? ch : 0;
    if (v.bits == 8) {
        u32 i = frame * v.channels + c;
        return i < b.size ? (b.data[i] - 128) / 128.f : 0.f;
    }
    u32 i = (frame * v.channels + c) * 2;
    if (i + 1 >= b.size)
        return 0.f;
    i16 s;
    std::memcpy(&s, b.data + i, 2);
    return s / 32768.f;
}

void mix_voice(Voice& v, float* out, int frames) {
    const double step = (double)v.rate * v.rate_mul / kOutRate;
    const u32 frame_bytes = (u32)(v.channels * (v.bits / 8));
    for (int f = 0; f < frames && !v.queue.empty();) {
        Buffer& b = v.queue.front();
        const u32 nframes = frame_bytes ? b.size / frame_bytes : 0;
        if (v.pos >= nframes) {
            v.queue.pop_front();
            v.pos -= nframes;
            ++v.play_index;
            if (v.on_done)
                cb_post(v.on_done);
            continue;
        }
        u32 i0 = (u32)v.pos;
        float t = (float)(v.pos - i0);
        u32 i1 = i0 + 1 < nframes ? i0 + 1 : i0;
        for (int ch = 0; ch < kOutChannels; ++ch) {
            float a = sample_at(v, b, i0, ch), c = sample_at(v, b, i1, ch);
            out[f * kOutChannels + ch] += (a + (c - a) * t) * v.gain;
        }
        v.pos += step;
        ++f;
    }
    // A buffer that ran out exactly at the end of this block completes now.
    if (!v.queue.empty() && frame_bytes) {
        Buffer& b = v.queue.front();
        if (v.pos >= b.size / frame_bytes) {
            v.pos -= b.size / frame_bytes;
            v.queue.pop_front();
            ++v.play_index;
            if (v.on_done)
                cb_post(v.on_done);
        }
    }
}

void SDLCALL device_cb(void*, Uint8* stream, int len) {
    const int frames = len / (int)(sizeof(i16) * kOutChannels);
    static std::vector<float> mix;
    mix.assign((size_t)frames * kOutChannels, 0.f);
    {
        std::lock_guard<std::mutex> lk(g_mix_mutex);
        for (auto& vp : g_voices)
            if (vp->playing)
                mix_voice(*vp, mix.data(), frames);
        Music& m = g_music;
        if (m.active && !m.paused && !m.pcm.empty()) {
            for (int f = 0; f < frames; ++f) {
                if (m.pos >= m.pcm.size()) {
                    if (!m.loop) { m.active = false; break; }
                    m.pos = 0;
                }
                mix[f * 2 + 0] += m.pcm[m.pos] * m.volume;
                mix[f * 2 + 1] += m.pcm[m.pos + 1] * m.volume;
                m.pos += 2;
            }
        }
    }
    i16* out = reinterpret_cast<i16*>(stream);
    for (size_t i = 0; i < mix.size(); ++i) {
        // master gain + soft knee above 0.8 so music + SFX peaks do not clip hard
        float s = mix[i] * 0.85f;
        float a = std::fabs(s);
        if (a > 0.8f)
            s = std::copysign(0.8f + 0.2f * std::tanh((a - 0.8f) / 0.2f), s);
        out[i] = (i16)std::lrintf(s * 32767.f);
    }
}

// Decode an audio file to interleaved stereo float @ kOutRate.
bool load_music_file(const std::string& path, std::vector<float>& out) {
    int ch = 0, rate = 0;
    std::vector<float> src;
    auto ends_with = [&](const char* ext) {
        size_t n = std::strlen(ext);
        return path.size() >= n && path.compare(path.size() - n, n, ext) == 0;
    };
    if (ends_with(".ogg")) {
        short* pcm = nullptr;
        int n = stb_vorbis_decode_filename(path.c_str(), &ch, &rate, &pcm);
        if (n <= 0 || !pcm)
            return false;
        src.resize((size_t)n * ch);
        for (size_t i = 0; i < src.size(); ++i)
            src[i] = pcm[i] / 32768.f;
        std::free(pcm);
    } else {
        SDL_AudioSpec spec;
        Uint8* buf = nullptr;
        Uint32 len = 0;
        if (!SDL_LoadWAV(path.c_str(), &spec, &buf, &len))
            return false;
        SDL_AudioCVT cvt;
        SDL_BuildAudioCVT(&cvt, spec.format, spec.channels, spec.freq, AUDIO_F32SYS, 2, kOutRate);
        cvt.len = (int)len;
        std::vector<Uint8> work((size_t)len * (cvt.len_mult > 0 ? cvt.len_mult : 1));
        std::memcpy(work.data(), buf, len);
        SDL_FreeWAV(buf);
        cvt.buf = work.data();
        if (cvt.needed && SDL_ConvertAudio(&cvt) != 0)
            return false;
        size_t nbytes = cvt.needed ? (size_t)cvt.len_cvt : len;
        out.resize(nbytes / sizeof(float));
        std::memcpy(out.data(), work.data(), out.size() * sizeof(float));
        return true;
    }
    // resample (linear) + upmix to stereo
    if (ch < 1)
        return false;
    size_t in_frames = src.size() / ch;
    double step = (double)rate / kOutRate;
    size_t out_frames = (size_t)(in_frames / step);
    out.resize(out_frames * 2);
    for (size_t f = 0; f < out_frames; ++f) {
        double p = f * step;
        size_t i0 = (size_t)p, i1 = std::min(i0 + 1, in_frames - 1);
        float t = (float)(p - i0);
        for (int c = 0; c < 2; ++c) {
            int sc = ch > 1 ? c : 0;
            float a = src[i0 * ch + sc], b = src[i1 * ch + sc];
            out[f * 2 + c] = a + (b - a) * t;
        }
    }
    return true;
}

Voice* voice(int v) {
    return (v >= 0 && (size_t)v < g_voices.size()) ? g_voices[(size_t)v].get() : nullptr;
}

} // namespace

bool audio_init() {
    if (g_tried)
        return g_dev != 0;
    g_tried = true;
    g_cb_run = true;
    g_cb_thread = std::thread(cb_loop);
    if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) {
        LOGW("audio: SDL audio init failed (%s) - running silent", SDL_GetError());
        return false;
    }
    SDL_AudioSpec want{}, have{};
    want.freq = kOutRate;
    want.format = AUDIO_S16SYS;
    want.channels = kOutChannels;
    want.samples = 1024;
    want.callback = device_cb;
    g_dev = SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
    if (!g_dev) {
        LOGW("audio: no output device (%s) - running silent", SDL_GetError());
        return false;
    }
    SDL_PauseAudioDevice(g_dev, 0);
    LOGI("audio: output %d Hz, %d ch (driver %s)", have.freq, have.channels,
         SDL_GetCurrentAudioDriver());
    return true;
}

void audio_shutdown() {
    if (g_dev) {
        SDL_CloseAudioDevice(g_dev);
        g_dev = 0;
    }
    if (g_cb_run) {
        g_cb_run = false;
        g_cb_cv.notify_all();
        if (g_cb_thread.joinable())
            g_cb_thread.detach(); // may be inside guest code; do not block exit
    }
}

int audio_voice_create(int rate_hz, int channels, int bits) {
    audio_init();
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    auto v = std::make_unique<Voice>();
    v->rate = rate_hz > 0 ? rate_hz : 44100;
    v->channels = channels == 2 ? 2 : 1;
    v->bits = bits == 8 ? 8 : 16;
    g_voices.push_back(std::move(v));
    return (int)g_voices.size() - 1;
}

void audio_voice_enqueue(int v, const void* pcm, u32 size) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) {
        p->queue.push_back({static_cast<const u8*>(pcm), size});
        // Without an output device nothing consumes buffers: complete them
        // immediately so the engine's channel bookkeeping keeps working.
        if (!g_dev && p->playing) {
            p->queue.pop_front();
            ++p->play_index;
            if (p->on_done)
                cb_post(p->on_done);
        }
    }
}

void audio_voice_clear(int v) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) {
        p->queue.clear();
        p->pos = 0;
    }
}

void audio_voice_get_state(int v, u32* queued, u32* play_index) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    Voice* p = voice(v);
    if (queued) *queued = p ? (u32)p->queue.size() : 0;
    if (play_index) *play_index = p ? p->play_index : 0;
}

void audio_voice_set_playing(int v, bool playing) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) {
        p->playing = playing;
        if (!g_dev && playing) {
            while (!p->queue.empty()) {
                p->queue.pop_front();
                ++p->play_index;
                if (p->on_done)
                    cb_post(p->on_done);
            }
        }
    }
}

void audio_voice_set_gain(int v, float gain) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) p->gain = std::clamp(gain, 0.f, 4.f);
}

void audio_voice_set_rate(int v, float rate) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) p->rate_mul = std::clamp(rate, 0.25f, 4.f);
}

void audio_voice_set_callback(int v, std::function<void()> cb) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    if (Voice* p = voice(v)) p->on_done = std::move(cb);
}

bool audio_music_play(const std::string& path, bool loop) {
    audio_init();
    // The game asks for .m4a (AAC); we play a pre-converted .ogg/.wav twin
    // (tools/convert_music.py) because AAC decoding is not bundled.
    std::string base = path;
    size_t dot = base.rfind('.');
    if (dot != std::string::npos && base.find('/', dot) == std::string::npos)
        base.resize(dot);
    std::vector<float> pcm;
    std::string used;
    for (const char* ext : {".ogg", ".wav"}) {
        if (load_music_file(base + ext, pcm)) {
            used = base + ext;
            break;
        }
    }
    if (used.empty()) {
        LOGW("audio: music '%s' not found as .ogg/.wav (run tools/convert_music.py)",
             path.c_str());
        return false;
    }
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    float vol = g_music.volume;
    bool paused = g_music.paused;
    g_music = Music{};
    g_music.pcm = std::move(pcm);
    g_music.loop = loop;
    g_music.active = true;
    g_music.volume = vol;
    g_music.paused = paused;
    LOGI("audio: music %s (%.1f s, loop=%d)", used.c_str(),
         g_music.pcm.size() / 2.0 / kOutRate, (int)loop);
    return true;
}

void audio_music_stop() {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    g_music.active = false;
}

void audio_music_set_volume(float v) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    g_music.volume = std::clamp(v, 0.f, 1.f);
}

void audio_music_set_pause(bool paused) {
    std::lock_guard<std::mutex> lk(g_mix_mutex);
    g_music.paused = paused;
}

} // namespace sjf
