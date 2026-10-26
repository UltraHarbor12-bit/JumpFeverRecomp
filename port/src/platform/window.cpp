// sjfport — SDL2 window + OpenGL context + screenshot support
#include "sjfport/platform.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
#include <SDL.h>
#include <SDL_opengl.h>

#include <algorithm>
#include <cmath>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace sjf {

namespace {
SDL_Window* g_window = nullptr;
SDL_GLContext g_ctx = nullptr;
int g_w = 0, g_h = 0;                 // guest surface (fixed after creation)
int g_surf_w = 540, g_surf_h = 960;   // requested guest surface (--surface/--aspect)
float g_aspect = 0.f;                 // 0 = use surface size as given
bool g_aspect_auto = false;
bool g_hidden = false;

// ---- key remapping (hito 9): controls.cfg -> SDL scancodes ----
// Format: "action = Key, Key"  with SDL scancode names (SDL_GetScancodeName):
//   tilt_left, tilt_right, tap, back, fullscreen. Alt+Enter is always fullscreen.
struct KeyMap {
    std::vector<SDL_Scancode> tilt_left{SDL_SCANCODE_LEFT, SDL_SCANCODE_A};
    std::vector<SDL_Scancode> tilt_right{SDL_SCANCODE_RIGHT, SDL_SCANCODE_D};
    std::vector<SDL_Scancode> tap{SDL_SCANCODE_SPACE, SDL_SCANCODE_RETURN};
    std::vector<SDL_Scancode> back{SDL_SCANCODE_ESCAPE, SDL_SCANCODE_BACKSPACE};
    std::vector<SDL_Scancode> fullscreen{SDL_SCANCODE_F11};
};
KeyMap g_keys;
std::string g_controls_path = "controls.cfg";

bool key_in(const std::vector<SDL_Scancode>& v, SDL_Scancode sc) {
    for (SDL_Scancode k : v)
        if (k == sc)
            return true;
    return false;
}
bool any_down(const Uint8* ks, const std::vector<SDL_Scancode>& v) {
    for (SDL_Scancode k : v)
        if (ks[k])
            return true;
    return false;
}
std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
    return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
}
void load_keymap() {
    FILE* f = std::fopen(g_controls_path.c_str(), "r");
    if (!f) {
        LOGI("controls: %s not found, default keys", g_controls_path.c_str());
        return;
    }
    char buf[512];
    while (std::fgets(buf, sizeof buf, f)) {
        std::string line = buf;
        auto h = line.find('#');
        if (h != std::string::npos) line.resize(h);
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string act = trim(line.substr(0, eq));
        std::vector<SDL_Scancode>* dst = act == "tilt_left" ? &g_keys.tilt_left
                                       : act == "tilt_right" ? &g_keys.tilt_right
                                       : act == "tap" ? &g_keys.tap
                                       : act == "back" ? &g_keys.back
                                       : act == "fullscreen" ? &g_keys.fullscreen : nullptr;
        if (!dst) { LOGW("controls: unknown action '%s'", act.c_str()); continue; }
        std::vector<SDL_Scancode> keys;
        std::string rest = line.substr(eq + 1);
        size_t p = 0;
        while (p <= rest.size()) {
            size_t c = rest.find(',', p);
            std::string name = trim(rest.substr(p, c == std::string::npos ? std::string::npos : c - p));
            if (!name.empty()) {
                SDL_Scancode sc = SDL_GetScancodeFromName(name.c_str());
                if (sc == SDL_SCANCODE_UNKNOWN) LOGW("controls: unknown key '%s'", name.c_str());
                else keys.push_back(sc);
            }
            if (c == std::string::npos) break;
            p = c + 1;
        }
        if (!keys.empty()) *dst = keys;
    }
    std::fclose(f);
    auto names = [](const std::vector<SDL_Scancode>& v) {
        std::string s;
        for (SDL_Scancode k : v) { if (!s.empty()) s += ","; s += SDL_GetScancodeName(k); }
        return s;
    };
    LOGI("controls: %s -> left=[%s] right=[%s] tap=[%s] back=[%s] fullscreen=[%s]",
         g_controls_path.c_str(), names(g_keys.tilt_left).c_str(), names(g_keys.tilt_right).c_str(),
         names(g_keys.tap).c_str(), names(g_keys.back).c_str(), names(g_keys.fullscreen).c_str());
}
std::atomic<int> g_dw{0}, g_dh{0};    // real drawable size (changes on resize)
std::atomic<bool> g_resized{false};

struct Letterbox { float scale; int x, y, w, h; };
Letterbox letterbox() {
    int dw = g_dw.load(), dh = g_dh.load();
    if (dw <= 0 || dh <= 0 || g_w <= 0 || g_h <= 0)
        return {1.f, 0, 0, g_w, g_h};
    float s = std::min((float)dw / g_w, (float)dh / g_h);
    int w = (int)(g_w * s + 0.5f), h = (int)(g_h * s + 0.5f);
    return {s, (dw - w) / 2, (dh - h) / 2, w, h};
}

void refresh_drawable() {
    int dw = 0, dh = 0;
    SDL_GL_GetDrawableSize(g_window, &dw, &dh);
    if (dw != g_dw.load() || dh != g_dh.load()) {
        g_dw = dw;
        g_dh = dh;
        g_resized = true;
    }
}
int g_swaps = 0;
std::string g_shot_path;
int g_shot_at = -1;
int g_win_w = 0, g_win_h = 0;         // --window override (0 = surface size)

// ---- back button + gamepad ----
std::atomic<bool> g_back{false};      // consumed by the engine loop (boot.cpp)
SDL_GameController* g_pad = nullptr;
float g_cur_x = 270.f, g_cur_y = 480.f; // virtual cursor (guest surface coords)
bool g_cur_visible = false;
bool g_pad_touch = false;             // A held -> finger down at the cursor
Uint64 g_last_pump = 0;

// SJF_VPAD="<ms>:<ctl>=<value>;..." drives an SDL *virtual* game controller
// (ctl: lx ly rx ry = axis -32768..32767, a b start = 0/1) so the real
// GameController path can be tested headless.
SDL_Joystick* g_vpad = nullptr;
struct VpadStep { Uint64 ms; std::string ctl; int value; bool done; };
std::vector<VpadStep> g_vpad_script;
Uint64 g_vpad_t0 = 0;

void open_pad(int index) {
    if (g_pad || !SDL_IsGameController(index))
        return;
    g_pad = SDL_GameControllerOpen(index);
    if (g_pad)
        LOGI("platform: gamepad connected: %s", SDL_GameControllerName(g_pad));
}

void vpad_init() {
    const char* sc = std::getenv("SJF_VPAD");
    if (!sc)
        return;
    int idx = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, SDL_CONTROLLER_AXIS_MAX,
                                        SDL_CONTROLLER_BUTTON_MAX, 0);
    if (idx < 0) {
        LOGW("platform: virtual pad failed: %s", SDL_GetError());
        return;
    }
    g_vpad = SDL_JoystickOpen(idx);
    std::string s = sc;
    size_t p = 0;
    while (p < s.size()) {
        size_t e = s.find(';', p);
        if (e == std::string::npos) e = s.size();
        std::string it = s.substr(p, e - p);
        size_t c = it.find(':'), q = it.find('=');
        if (c != std::string::npos && q != std::string::npos && q > c)
            g_vpad_script.push_back({(Uint64)std::atoll(it.substr(0, c).c_str()),
                                     it.substr(c + 1, q - c - 1), std::atoi(it.substr(q + 1).c_str()),
                                     false});
        p = e + 1;
    }
    g_vpad_t0 = SDL_GetTicks64();
    LOGI("platform: virtual pad attached (%zu scripted steps)", g_vpad_script.size());
}

void vpad_step() {
    if (!g_vpad)
        return;
    Uint64 el = SDL_GetTicks64() - g_vpad_t0;
    for (auto& st : g_vpad_script) {
        if (st.done || el < st.ms)
            continue;
        st.done = true;
        const std::string& k = st.ctl;
        if (k == "lx") SDL_JoystickSetVirtualAxis(g_vpad, SDL_CONTROLLER_AXIS_LEFTX, (Sint16)st.value);
        else if (k == "ly") SDL_JoystickSetVirtualAxis(g_vpad, SDL_CONTROLLER_AXIS_LEFTY, (Sint16)st.value);
        else if (k == "rx") SDL_JoystickSetVirtualAxis(g_vpad, SDL_CONTROLLER_AXIS_RIGHTX, (Sint16)st.value);
        else if (k == "ry") SDL_JoystickSetVirtualAxis(g_vpad, SDL_CONTROLLER_AXIS_RIGHTY, (Sint16)st.value);
        else if (k == "a") SDL_JoystickSetVirtualButton(g_vpad, SDL_CONTROLLER_BUTTON_A, (Uint8)st.value);
        else if (k == "b") SDL_JoystickSetVirtualButton(g_vpad, SDL_CONTROLLER_BUTTON_B, (Uint8)st.value);
        else if (k == "start") SDL_JoystickSetVirtualButton(g_vpad, SDL_CONTROLLER_BUTTON_START, (Uint8)st.value);
    }
}

float stick(SDL_GameControllerAxis a) {
    float v = g_pad ? SDL_GameControllerGetAxis(g_pad, a) / 32767.f : 0.f;
    const float dz = 0.18f;
    if (std::fabs(v) < dz) return 0.f;
    return (v - std::copysign(dz, v)) / (1.f - dz);
}
bool g_start_fullscreen = false;

bool write_bmp(const char* path, int w, int h, const unsigned char* rgba) {
    // 24-bit BMP, bottom-up
    int row = (w * 3 + 3) & ~3;
    int data_size = row * h;
    FILE* f = std::fopen(path, "wb");
    if (!f)
        return false;
    unsigned char hdr[54] = {0};
    hdr[0] = 'B'; hdr[1] = 'M';
    int total = 54 + data_size;
    std::memcpy(hdr + 2, &total, 4);
    int off = 54;
    std::memcpy(hdr + 10, &off, 4);
    int ihs = 40;
    std::memcpy(hdr + 14, &ihs, 4);
    std::memcpy(hdr + 18, &w, 4);
    std::memcpy(hdr + 22, &h, 4);
    short planes = 1, bpp = 24;
    std::memcpy(hdr + 26, &planes, 2);
    std::memcpy(hdr + 28, &bpp, 2);
    std::memcpy(hdr + 34, &data_size, 4);
    std::fwrite(hdr, 1, 54, f);
    std::vector<unsigned char> line(row);
    // glReadPixels returns rows bottom-up, which is exactly BMP's row order.
    for (int y = 0; y < h; ++y) {
        const unsigned char* src = rgba + (size_t)y * w * 4;
        for (int x = 0; x < w; ++x) {
            line[x * 3 + 0] = src[x * 4 + 2]; // B
            line[x * 3 + 1] = src[x * 4 + 1]; // G
            line[x * 3 + 2] = src[x * 4 + 0]; // R
        }
        std::fwrite(line.data(), 1, row, f);
    }
    std::fclose(f);
    return true;
}
// Window (logical) coordinates -> guest surface coordinates. False if outside.
bool window_to_surface(int wx, int wy, float& gx, float& gy) {
    int ww = 0, wh = 0;
    SDL_GetWindowSize(g_window, &ww, &wh);
    int dw = g_dw.load();
    float dpi = (ww > 0 && dw > 0) ? (float)dw / ww : 1.f; // HiDPI: logical -> pixels
    Letterbox lb = letterbox();
    float px = wx * dpi - lb.x, py = wy * dpi - lb.y;
    gx = std::clamp(px / lb.scale, 0.f, (float)g_w - 1);
    gy = std::clamp(py / lb.scale, 0.f, (float)g_h - 1);
    return px >= 0 && py >= 0 && px < lb.w && py < lb.h;
}
} // namespace

void platform_set_surface_size(int w, int h) {
    if (w >= 240 && h >= 240) { g_surf_w = w; g_surf_h = h; }
}
int platform_surface_w() { return g_surf_w; }
void platform_set_hidden(bool hidden) { g_hidden = hidden; }
void platform_set_controls_file(const char* path) { if (path && *path) g_controls_path = path; }
int platform_surface_h() { return g_surf_h; }
void platform_set_aspect(const char* spec) {
    std::string s = spec ? spec : "";
    if (s == "auto") { g_aspect_auto = true; return; }
    float a = 0.f, b = 0.f;
    if (std::sscanf(s.c_str(), "%f:%f", &a, &b) == 2 && a > 0 && b > 0)
        g_aspect = a / b;
    else if (std::sscanf(s.c_str(), "%f", &a) == 1 && a > 0)
        g_aspect = a;
    g_aspect_auto = false;
}

bool platform_create_window(int width, int height) {
    if (g_window)
        return true;
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_GAMECONTROLLER) != 0) {
        LOGE("SDL_Init failed: %s", SDL_GetError());
        return false;
    }
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_COMPATIBILITY);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 2);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 1);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24);
    SDL_GL_SetAttribute(SDL_GL_STENCIL_SIZE, 8);
    Uint32 flags = SDL_WINDOW_OPENGL | (g_hidden ? SDL_WINDOW_HIDDEN : SDL_WINDOW_SHOWN) |
                   SDL_WINDOW_RESIZABLE;
    if (g_start_fullscreen)
        flags |= SDL_WINDOW_FULLSCREEN_DESKTOP;
    SDL_SetHint(SDL_HINT_VIDEO_HIGHDPI_DISABLED, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    flags |= SDL_WINDOW_ALLOW_HIGHDPI;
    // ---- widescreen: derive the surface width from the requested aspect ----
    SDL_Rect usable{0, 0, 0, 0};
    SDL_GetDisplayUsableBounds(0, &usable);
    if (g_aspect_auto) {
        SDL_DisplayMode dm;
        if (SDL_GetDesktopDisplayMode(0, &dm) == 0 && dm.w > 0 && dm.h > 0)
            g_aspect = (float)dm.w / (float)dm.h;
    }
    if (g_aspect > 0.f) {
        float a = std::clamp(g_aspect, 0.4f, 2.5f);
        width = ((int)(height * a + 0.5f)) & ~1;
        g_surf_w = width;
        g_surf_h = height;
        LOGI("platform: aspect %.3f -> surface %dx%d", a, width, height);
    }
    // Default windowed size: the surface, shrunk to fit ~90%% of the desktop.
    int init_w = g_win_w > 0 ? g_win_w : width;
    int init_h = g_win_h > 0 ? g_win_h : height;
    if (g_win_w <= 0 && usable.w > 0 && usable.h > 0) {
        float fit = std::min(0.9f * usable.w / width, 0.9f * usable.h / height);
        if (fit < 1.f) {
            init_w = (int)(width * fit);
            init_h = (int)(height * fit);
        }
    }
    g_window = SDL_CreateWindow("Sonic Jump Fever - sjfport", SDL_WINDOWPOS_CENTERED,
                                SDL_WINDOWPOS_CENTERED, init_w, init_h, flags);
    if (!g_window) {
        LOGE("SDL_CreateWindow failed: %s", SDL_GetError());
        return false;
    }
    g_ctx = SDL_GL_CreateContext(g_window);
    if (!g_ctx) {
        LOGE("SDL_GL_CreateContext failed: %s", SDL_GetError());
        return false;
    }
    SDL_GL_MakeCurrent(g_window, g_ctx);
    SDL_GL_SetSwapInterval(1);
    // Release the context: the engine's RENDER thread will claim it via
    // eglMakeCurrent. A WGL context refuses to be made current on a second
    // thread while still current here ("resource already in use").
    SDL_GL_MakeCurrent(g_window, nullptr);
    g_w = width; // guest surface: fixed, independent of the window size
    g_h = height;
    g_cur_x = width * 0.5f;
    g_cur_y = height * 0.5f;
    vpad_init();
    load_keymap();
    for (int i = 0; i < SDL_NumJoysticks(); ++i)
        open_pad(i);
    refresh_drawable();
    g_resized = false;
    {
        int ww = 0, wh = 0;
        SDL_GetWindowSize(g_window, &ww, &wh);
        LOGI("platform: surface %dx%d in window %dx%d", g_w, g_h, ww, wh);
    }
    LOGI("platform: window %dx%d, GL %s / %s", g_w, g_h,
         (const char*)glGetString(GL_VERSION), (const char*)glGetString(GL_RENDERER));
    return true;
}

bool platform_pump() {
    if (!g_window)
        return false;
    static bool mouse_down = false;
    SDL_Event ev;
    while (SDL_PollEvent(&ev)) {
        switch (ev.type) {
            case SDL_QUIT:
                LOGI("platform: quit requested");
                return false;
            case SDL_WINDOWEVENT:
                if (ev.window.event == SDL_WINDOWEVENT_SIZE_CHANGED)
                    refresh_drawable(); // guest surface stays fixed: letterbox
                break;
            // Mouse -> single-finger touch (AMOTION_EVENT_ACTION_DOWN/UP/MOVE)
            case SDL_MOUSEBUTTONDOWN:
                if (ev.button.button == SDL_BUTTON_LEFT) {
                    float gx, gy;
                    if (window_to_surface(ev.button.x, ev.button.y, gx, gy)) {
                        mouse_down = true;
                        input_push_touch(0, gx, gy);
                    }
                }
                break;
            case SDL_MOUSEBUTTONUP:
                if (ev.button.button == SDL_BUTTON_LEFT && mouse_down) {
                    float gx, gy;
                    window_to_surface(ev.button.x, ev.button.y, gx, gy);
                    mouse_down = false;
                    input_push_touch(1, gx, gy);
                }
                break;
            case SDL_CONTROLLERDEVICEADDED:
                open_pad(ev.cdevice.which);
                break;
            case SDL_CONTROLLERDEVICEREMOVED:
                if (g_pad && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(g_pad)) ==
                                 ev.cdevice.which) {
                    SDL_GameControllerClose(g_pad);
                    g_pad = nullptr;
                    g_cur_visible = false;
                    LOGI("platform: gamepad disconnected");
                }
                break;
            case SDL_CONTROLLERBUTTONDOWN:
            case SDL_CONTROLLERBUTTONUP: {
                bool down = ev.type == SDL_CONTROLLERBUTTONDOWN;
                switch (ev.cbutton.button) {
                    case SDL_CONTROLLER_BUTTON_A:
                        g_cur_visible = true;
                        if (down && !g_pad_touch) {
                            g_pad_touch = true;
                            input_push_touch(0, g_cur_x, g_cur_y);
                        } else if (!down && g_pad_touch) {
                            g_pad_touch = false;
                            input_push_touch(1, g_cur_x, g_cur_y);
                        }
                        break;
                    case SDL_CONTROLLER_BUTTON_B:
                    case SDL_CONTROLLER_BUTTON_BACK:
                    case SDL_CONTROLLER_BUTTON_START:
                        if (down) g_back = true;
                        break;
                    default:
                        break;
                }
                break;
            }
            case SDL_MOUSEMOTION:
                g_cur_visible = false; // the mouse is in charge again
                if (mouse_down) {
                    float gx, gy;
                    window_to_surface(ev.motion.x, ev.motion.y, gx, gy);
                    input_push_touch(2, gx, gy);
                }
                break;
            // Space / Enter -> tap in the middle of the screen (jump)
            case SDL_KEYDOWN:
                if (!ev.key.repeat && (key_in(g_keys.fullscreen, ev.key.keysym.scancode) ||
                                       (ev.key.keysym.sym == SDLK_RETURN &&
                                        (ev.key.keysym.mod & KMOD_ALT)))) {
                    platform_toggle_fullscreen();
                    break;
                }
                if (!ev.key.repeat && key_in(g_keys.back, ev.key.keysym.scancode)) {
                    LOGI("keys: back (%s)", SDL_GetScancodeName(ev.key.keysym.scancode));
                    g_back = true; // Android BACK (pause / previous screen)
                    break;
                }
                if (!ev.key.repeat && key_in(g_keys.tap, ev.key.keysym.scancode))
                    input_push_touch(0, g_w * 0.5f, g_h * 0.5f);
                break;
            case SDL_KEYUP:
                if (key_in(g_keys.tap, ev.key.keysym.scancode))
                    input_push_touch(1, g_w * 0.5f, g_h * 0.5f);
                break;
            default:
                break;
        }
    }
    // Keyboard -> accelerometer tilt (Sonic Jump steers by tilting the phone).
    // Android: tilting the device to the left gives a positive X acceleration.
    {
        static const bool invert = std::getenv("SJF_TILT_INVERT") != nullptr;
        const Uint8* ks = SDL_GetKeyboardState(nullptr);
        float ax = 0.f;
        if (any_down(ks, g_keys.tilt_left)) ax += 5.0f;
        if (any_down(ks, g_keys.tilt_right)) ax -= 5.0f;
        {
            static float last_kb = 0.f;
            if (ax != last_kb) {
                LOGI("keys: keyboard tilt %+.1f", ax);
                last_kb = ax;
            }
        }
        if (g_pad && ax == 0.f) {
            // left stick (analogue) or D-pad: right = tilt right = negative X
            ax = -stick(SDL_CONTROLLER_AXIS_LEFTX) * 7.0f;
            if (SDL_GameControllerGetButton(g_pad, SDL_CONTROLLER_BUTTON_DPAD_LEFT)) ax = 5.0f;
            if (SDL_GameControllerGetButton(g_pad, SDL_CONTROLLER_BUTTON_DPAD_RIGHT)) ax = -5.0f;
        }
        input_set_tilt(invert ? -ax : ax);
    }
    // Right stick -> virtual cursor (A taps where it points).
    {
        vpad_step();
        Uint64 now = SDL_GetTicks64();
        float dt = g_last_pump ? (now - g_last_pump) / 1000.f : 0.f;
        g_last_pump = now;
        if (dt > 0.1f) dt = 0.1f;
        float vx = stick(SDL_CONTROLLER_AXIS_RIGHTX), vy = stick(SDL_CONTROLLER_AXIS_RIGHTY);
        if (vx != 0.f || vy != 0.f) {
            const float speed = 600.f; // surface px / s at full deflection
            g_cur_x = std::clamp(g_cur_x + vx * speed * dt, 0.f, (float)g_w - 1);
            g_cur_y = std::clamp(g_cur_y + vy * speed * dt, 0.f, (float)g_h - 1);
            g_cur_visible = true;
            if (g_pad_touch)
                input_push_touch(2, g_cur_x, g_cur_y);
        }
    }
    return true;
}

void platform_swap() {
    if (!g_window || !g_ctx)
        return;
    ++g_swaps;
    // Gamepad cursor: two nested squares drawn with scissored clears (no
    // shader/state juggling needed), mapped through the letterbox.
    if (g_cur_visible) {
        GLboolean sc = glIsEnabled(GL_SCISSOR_TEST);
        GLint box[4];
        GLfloat cc[4];
        glGetIntegerv(GL_SCISSOR_BOX, box);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, cc);
        glEnable(GL_SCISSOR_TEST);
        const int gy = g_h - (int)g_cur_y; // GL origin is bottom-left
        const struct { int half; float r, g, b; } rings[] = {
            {9, 0.f, 0.f, 0.f}, {7, 1.f, 1.f, 1.f}, {4, g_pad_touch ? 1.f : 0.1f, 0.4f, 1.f}};
        for (auto& rg : rings) {
            int r[4];
            platform_map_rect((int)g_cur_x - rg.half, gy - rg.half, rg.half * 2, rg.half * 2, r);
            glScissor(r[0], r[1], r[2] > 2 ? r[2] : 2, r[3] > 2 ? r[3] : 2);
            glClearColor(rg.r, rg.g, rg.b, 1.f);
            glClear(GL_COLOR_BUFFER_BIT);
        }
        glClearColor(cc[0], cc[1], cc[2], cc[3]);
        glScissor(box[0], box[1], box[2], box[3]);
        if (!sc)
            glDisable(GL_SCISSOR_TEST);
    }
    // Black bars around the letterboxed guest image (the guest's glClear fills
    // the whole window). Save/restore the state we touch.
    {
        Letterbox lb = letterbox();
        int dw = g_dw.load(), dh = g_dh.load();
        if (lb.w < dw || lb.h < dh) {
            GLboolean sc = glIsEnabled(GL_SCISSOR_TEST);
            GLint box[4];
            GLfloat cc[4];
            GLboolean cm[4];
            glGetIntegerv(GL_SCISSOR_BOX, box);
            glGetFloatv(GL_COLOR_CLEAR_VALUE, cc);
            glGetBooleanv(GL_COLOR_WRITEMASK, cm);
            glEnable(GL_SCISSOR_TEST);
            glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
            glClearColor(0.f, 0.f, 0.f, 1.f);
            const int bars[4][4] = {{0, 0, lb.x, dh}, {lb.x + lb.w, 0, dw - lb.x - lb.w, dh},
                                    {0, 0, dw, lb.y}, {0, lb.y + lb.h, dw, dh - lb.y - lb.h}};
            for (auto& b : bars) {
                if (b[2] <= 0 || b[3] <= 0)
                    continue;
                glScissor(b[0], b[1], b[2], b[3]);
                glClear(GL_COLOR_BUFFER_BIT);
            }
            glClearColor(cc[0], cc[1], cc[2], cc[3]);
            glColorMask(cm[0], cm[1], cm[2], cm[3]);
            glScissor(box[0], box[1], box[2], box[3]);
            if (!sc)
                glDisable(GL_SCISSOR_TEST);
        }
    }
    if (g_shot_at > 0 && !g_shot_path.empty() &&
        (g_swaps == 1 || g_swaps % g_shot_at == 0)) {
        // Capture only the guest image (letterbox rectangle), not the bars.
        Letterbox lb = letterbox();
        std::vector<unsigned char> px((size_t)lb.w * lb.h * 4);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadPixels(lb.x, lb.y, lb.w, lb.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        // <path> always holds the latest frame; <path>_<swap>.bmp keeps a history.
        std::string numbered = g_shot_path;
        size_t dot = numbered.rfind('.');
        std::string suffix = "_" + std::to_string(g_swaps);
        if (dot == std::string::npos) numbered += suffix; else numbered.insert(dot, suffix);
        bool ok = write_bmp(g_shot_path.c_str(), lb.w, lb.h, px.data()) &&
                  write_bmp(numbered.c_str(), lb.w, lb.h, px.data());
        if (ok)
            LOGI("platform: screenshot saved to %s (%dx%d)", numbered.c_str(), lb.w, lb.h);
        else
            LOGW("platform: screenshot failed (%s)", g_shot_path.c_str());
    }
    SDL_GL_SwapWindow(g_window);
}

void platform_make_current() {
    if (g_window && g_ctx) {
        if (SDL_GL_MakeCurrent(g_window, g_ctx) != 0)
            LOGE("SDL_GL_MakeCurrent failed: %s", SDL_GetError());
    }
}

void platform_map_rect(int x, int y, int w, int h, int out[4]) {
    Letterbox lb = letterbox();
    out[0] = lb.x + (int)(x * lb.scale + 0.5f);
    out[1] = lb.y + (int)(y * lb.scale + 0.5f);
    out[2] = (int)(w * lb.scale + 0.5f);
    out[3] = (int)(h * lb.scale + 0.5f);
}

bool platform_take_resize() { return g_resized.exchange(false); }
bool platform_take_back() { return g_back.exchange(false); }

void platform_toggle_fullscreen() {
    if (!g_window)
        return;
    bool fs = (SDL_GetWindowFlags(g_window) & SDL_WINDOW_FULLSCREEN_DESKTOP) != 0;
    SDL_SetWindowFullscreen(g_window, fs ? 0 : SDL_WINDOW_FULLSCREEN_DESKTOP);
    refresh_drawable();
    LOGI("platform: %s", fs ? "windowed" : "fullscreen");
}

int platform_width() { return g_w; }
int platform_height() { return g_h; }

void platform_set_window_options(int w, int h, bool fullscreen) {
    g_win_w = w;
    g_win_h = h;
    g_start_fullscreen = fullscreen;
}

void platform_set_screenshot(const char* path, int at_swap) {
    g_shot_path = path ? path : "";
    g_shot_at = at_swap;
}

void platform_capture_i32(int* w, int* h, void** pixels) {
    (void)w; (void)h; (void)pixels;
}

void platform_shutdown() {
    if (g_ctx) { SDL_GL_DeleteContext(g_ctx); g_ctx = nullptr; }
    if (g_window) { SDL_DestroyWindow(g_window); g_window = nullptr; }
    SDL_Quit();
}

} // namespace sjf
