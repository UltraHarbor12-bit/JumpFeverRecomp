// sjfport — host audio: SDL2 output device + software mixer.
//
// Voices back the guest's OpenSL ES buffer-queue players (sound effects);
// one extra "music" stream backs the Java musicplayer (background music).
#pragma once
#include "common.h"
#include <functional>
#include <string>

namespace sjf {

bool audio_init();     // opens the SDL audio device (idempotent; false = silent mode)
void audio_shutdown();

// ---- OpenSL buffer-queue voices ----
int audio_voice_create(int rate_hz, int channels, int bits);          // -> voice id
void audio_voice_enqueue(int v, const void* pcm, u32 size);           // host pointer
void audio_voice_clear(int v);
void audio_voice_get_state(int v, u32* queued, u32* play_index);
void audio_voice_set_playing(int v, bool playing);                    // PLAYING vs PAUSED/STOPPED
void audio_voice_set_gain(int v, float gain);                         // linear 0..1
void audio_voice_set_rate(int v, float rate);                         // 1.0 = normal
// Called (on the audio callback thread, never the device thread) each time
// a queued buffer has been fully played — mirrors slBufferQueueCallback.
void audio_voice_set_callback(int v, std::function<void()> cb);

// ---- background music (decoded .ogg / .wav next to the game's .m4a) ----
bool audio_music_play(const std::string& path, bool loop);
void audio_music_stop();
void audio_music_set_volume(float v);
void audio_music_set_pause(bool paused);

} // namespace sjf
