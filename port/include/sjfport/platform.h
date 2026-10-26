// sjfport — PC platform layer (SDL2 window + OpenGL context)
#pragma once
#include "common.h"

namespace sjf {
bool platform_create_window(int width, int height);
bool platform_pump();            // false when the user closes the window
void platform_swap();
void platform_make_current();
int platform_width();            // guest surface size (fixed, e.g. 540x960)
int platform_height();
// Letterboxing: the guest renders into a fixed-size surface; its viewport and
// scissor rectangles are scaled/centred into the real (resizable) window.
void platform_map_rect(int x, int y, int w, int h, int out[4]);
bool platform_take_resize();
bool platform_take_back();       // Esc/Backspace or pad B/Start was pressed     // true once after the drawable size changed
void platform_toggle_fullscreen();
void platform_set_window_options(int w, int h, bool fullscreen); // before create
// Guest surface size (what the game renders at; default 540x960 portrait).
void platform_set_surface_size(int w, int h);
int platform_surface_w();
int platform_surface_h();
// Widescreen: "W:H" (e.g. 16:9, 4:3, 9:16) or "auto" (desktop aspect).
// Keeps the surface height (960) and derives the width; the game's UI
// anchors to the corners and the level renders across the full width.
void platform_set_aspect(const char* spec);
// Create the window hidden (save editor "apply now": no visible window).
void platform_set_hidden(bool hidden);
// Key remapping file (default: controls.cfg in the working directory).
void platform_set_controls_file(const char* path);
void platform_set_screenshot(const char* path, int at_swap);
void platform_capture_i32(int* w, int* h, void** pixels); // GL RGBA readback
void platform_shutdown();

// ---- input bridge (implemented in dependencies/libandroid.cpp) ----
// Touch: action uses Android AMOTION_EVENT_ACTION_* (0=DOWN, 1=UP, 2=MOVE);
// x/y are in window pixels (same space the guest gets from eglQuerySurface).
void input_push_touch(int action, float x, float y);
// Tilt: accelerometer X in m/s^2 (Android convention, + = device tilted left).
void input_set_tilt(float ax);
// Scripted tilt (SJF_TILT): sticks and overrides the keyboard from then on.
void input_set_tilt_override(float ax);
} // namespace sjf
