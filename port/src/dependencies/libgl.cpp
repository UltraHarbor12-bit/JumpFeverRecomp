// sjfport — EGL + GLES2 on top of a desktop OpenGL 2.1 context (SDL2).
//
// GLES2 shaders (GLSL ES 1.0) are not valid desktop GLSL 1.20, so shader
// sources are sanitised: precision qualifiers, #version and #extension lines
// are stripped.
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include "sjfport/host_calls.h"
#include "sjfport/platform.h"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#else
#define GL_GLEXT_LEGACY 1 // we declare the GL 1.5/2.0 types ourselves
#include <GL/gl.h>
#include <SDL.h>
#endif

// GL 1.5/2.0 scalar types missing from MinGW's GL/gl.h
#include <cstddef>
typedef std::ptrdiff_t GLsizeiptr;
typedef std::ptrdiff_t GLintptr;
typedef char GLchar;

#include <cctype>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace sjf {

namespace {

#ifdef _WIN32
HMODULE g_opengl32 = nullptr;
#endif

void* glproc(const char* name) {
    static std::map<std::string, void*> cache;
    auto it = cache.find(name);
    if (it != cache.end())
        return it->second;
#ifndef _WIN32
    void* sp = SDL_GL_GetProcAddress(name);
    if (sp)
        cache[name] = sp;
    return sp;
#else
    PROC p = wglGetProcAddress(name);
    if (!p || p == (PROC)1 || p == (PROC)2 || p == (PROC)3 || p == (PROC)-1) {
        if (!g_opengl32)
            g_opengl32 = LoadLibraryA("opengl32.dll");
        p = g_opengl32 ? GetProcAddress(g_opengl32, name) : nullptr;
    }
    if (p) // never cache NULL (the context may not be current yet)
        cache[name] = (void*)p;
    return (void*)p;
#endif
}

int g_guest_viewport[4] = {0, 0, 0, 0};
int g_guest_scissor[4] = {0, 0, 0, 0};

void reapply_guest_rects() {
    using RectFn = void (*)(GLint, GLint, GLint, GLint);
    static RectFn vp = (RectFn)glproc("glViewport");
    static RectFn sc = (RectFn)glproc("glScissor");
    int r[4];
    if (vp && g_guest_viewport[2] > 0) {
        platform_map_rect(g_guest_viewport[0], g_guest_viewport[1], g_guest_viewport[2],
                          g_guest_viewport[3], r);
        vp(r[0], r[1], r[2], r[3]);
    }
    if (sc && g_guest_scissor[2] > 0) {
        platform_map_rect(g_guest_scissor[0], g_guest_scissor[1], g_guest_scissor[2],
                          g_guest_scissor[3], r);
        sc(r[0], r[1], r[2], r[3]);
    }
}

float farg(GuestCall& c, int i) {
    u32 bits = (u32)c.v[i];
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}

bool is_ident_char(char ch) { return std::isalnum((unsigned char)ch) || ch == '_'; }

// Strip GLSL ES-only constructs so desktop GLSL 1.20 accepts the source.
std::string sanitize_shader(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    const std::string kQualifiers[] = {"highp", "mediump", "lowp", "invariant"};

    std::vector<std::string> lines;
    size_t pos = 0;
    while (pos <= in.size()) {
        size_t e = in.find('\n', pos);
        if (e == std::string::npos)
            e = in.size();
        lines.push_back(in.substr(pos, e - pos));
        if (e == in.size())
            break;
        pos = e + 1;
    }
    for (auto& line : lines) {
        size_t s0 = line.find_first_not_of(" \t\r");
        std::string tl = (s0 == std::string::npos) ? "" : line.substr(s0);
        if (tl.rfind("#version", 0) == 0 || tl.rfind("#extension", 0) == 0 ||
            tl.rfind("precision", 0) == 0)
            continue;
        out += line;
        out += '\n';
    }

    std::string res;
    res.reserve(out.size());
    size_t i = 0;
    while (i < out.size()) {
        if (is_ident_char(out[i]) && (i == 0 || !is_ident_char(out[i - 1]))) {
            size_t j = i;
            while (j < out.size() && is_ident_char(out[j]))
                ++j;
            std::string tok = out.substr(i, j - i);
            bool drop = false;
            for (auto& q : kQualifiers)
                if (tok == q) { drop = true; break; }
            if (!drop)
                res += tok;
            i = j;
        } else {
            res += out[i++];
        }
    }
    return res;
}

} // namespace

// ---------------------------------------------------------------------------
// EGL
// ---------------------------------------------------------------------------
void register_libEGL_module() {
    register_host_fn("eglGetDisplay", [](GuestCall& c) { c.ret = 1; });
    register_host_fn("eglInitialize", [](GuestCall& c) {
        if (c.x[1]) { i32 a = 1; gwrite(c.x[1], &a, 4); }
        if (c.x[2]) { i32 b = 4; gwrite(c.x[2], &b, 4); }
        c.ret = 1;
    });
    register_host_fn("eglChooseConfig", [](GuestCall& c) {
        if (c.x[2] && c.x[4]) { u64 cfg = 0xC0F1; gwrite(c.x[2], &cfg, 8); }
        if (c.x[4]) { i32 n = 1; gwrite(c.x[4], &n, 4); }
        c.ret = 1;
    });
    register_host_fn("eglGetConfigAttrib", [](GuestCall& c) {
        if (c.x[3]) { i32 v = 8; gwrite(c.x[3], &v, 4); }
        c.ret = 1;
    });
    register_host_fn("eglCreateWindowSurface", [](GuestCall& c) {
        LOGI("eglCreateWindowSurface");
        if (platform_width() == 0 && !platform_create_window(platform_surface_w(), platform_surface_h()))
            LOGW("eglCreateWindowSurface: window creation failed");
        c.ret = 0xE65;
    });
    register_host_fn("eglCreateContext", [](GuestCall& c) {
        LOGI("eglCreateContext");
        c.ret = 0xC7;
    });
    register_host_fn("eglMakeCurrent", [](GuestCall& c) {
        static int n = 0;
        if (n++ < 5) LOGI("eglMakeCurrent #%d", n);
        platform_make_current();
        c.ret = 1;
    });
    register_host_fn("eglQuerySurface", [](GuestCall& c) {
        if (c.x[3]) {
            u32 attr = (u32)c.x[2];
            i32 v = (attr == 0x3057) ? platform_width() : platform_height();
            gwrite(c.x[3], &v, 4);
        }
        c.ret = 1;
    });
    register_host_fn("eglSwapBuffers", [](GuestCall& c) {
        static int n = 0;
        ++n;
        if (n == 1 || n % 60 == 0) LOGI("eglSwapBuffers #%d", n);
        platform_swap();
        // The window was resized: re-apply the guest's last viewport/scissor
        // with the new letterbox (the engine sets them rarely).
        if (platform_take_resize())
            reapply_guest_rects();
        c.ret = 1;
    });
    register_host_fn("eglDestroySurface", [](GuestCall& c) { c.ret = 1; });
    register_host_fn("eglDestroyContext", [](GuestCall& c) { c.ret = 1; });
    register_host_fn("eglTerminate", [](GuestCall& c) { c.ret = 1; });
}

// ---------------------------------------------------------------------------
// GLES2 -> OpenGL
// ---------------------------------------------------------------------------
#define GLFN(TYPE, name)                                                       \
    register_host_fn(name, [](GuestCall& c) {                                  \
        using FnT = TYPE;                                                      \
        static FnT fn = (FnT)glproc(name);                                     \
        static bool logged = false;                                            \
        if (!logged) {                                                         \
            logged = true;                                                     \
            LOGI("GL first call: %s (fn=%p)", name, (void*)fn);                 \
        }                                                                      \
        (void)fn;                                                              \
        c.ret = 0;

#define GLFN_END });

void register_libGLESv2_module() {
    // ---- state ----
    GLFN(void (*)(GLenum), "glActiveTexture")
        if (fn) fn((GLenum)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLenum, GLenum), "glBindTexture")
        if (fn) {
            static int n = 0;
            if (n++ < 15) LOGI("glBindTexture target=0x%x tex=%u", (unsigned)c.x[0], (unsigned)c.x[1]);
            fn((GLenum)c.x[0], (GLenum)c.x[1]);
        }
    GLFN_END
    GLFN(void (*)(GLenum), "glDisable") if (fn) fn((GLenum)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLenum), "glEnable") if (fn) fn((GLenum)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLenum), "glBlendEquation") if (fn) fn((GLenum)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLenum, GLenum, GLenum, GLenum), "glBlendFuncSeparate")
        if (fn) fn((GLenum)c.x[0], (GLenum)c.x[1], (GLenum)c.x[2], (GLenum)c.x[3]);
    GLFN_END
    GLFN(void (*)(GLbitfield), "glClear") if (fn) fn((GLbitfield)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLclampf, GLclampf, GLclampf, GLclampf), "glClearColor")
        if (fn) fn((GLclampf)farg(c, 0), (GLclampf)farg(c, 1), (GLclampf)farg(c, 2),
                   (GLclampf)farg(c, 3));
    GLFN_END
    GLFN(void (*)(GLboolean), "glDepthMask") if (fn) fn((GLboolean)c.x[0]);
    GLFN_END
    // Viewport/scissor are in guest-surface pixels: letterbox them into the window.
    GLFN(void (*)(GLint, GLint, GLint, GLint), "glScissor")
        g_guest_scissor[0] = (i32)c.x[0]; g_guest_scissor[1] = (i32)c.x[1];
        g_guest_scissor[2] = (i32)c.x[2]; g_guest_scissor[3] = (i32)c.x[3];
        int r[4];
        platform_map_rect(g_guest_scissor[0], g_guest_scissor[1], g_guest_scissor[2],
                          g_guest_scissor[3], r);
        if (fn) fn(r[0], r[1], r[2], r[3]);
    GLFN_END
    GLFN(void (*)(GLint, GLint, GLsizei, GLsizei), "glViewport")
        g_guest_viewport[0] = (i32)c.x[0]; g_guest_viewport[1] = (i32)c.x[1];
        g_guest_viewport[2] = (i32)c.x[2]; g_guest_viewport[3] = (i32)c.x[3];
        int r[4];
        platform_map_rect(g_guest_viewport[0], g_guest_viewport[1], g_guest_viewport[2],
                          g_guest_viewport[3], r);
        if (fn) fn(r[0], r[1], r[2], r[3]);
    GLFN_END
    GLFN(void (*)(GLenum, GLenum, GLfloat), "glTexParameterf")
        if (fn) fn((GLenum)c.x[0], (GLenum)c.x[1], (GLfloat)farg(c, 0));
    GLFN_END
    GLFN(void (*)(GLenum, GLenum, GLenum), "glTexParameteri")
        if (fn) fn((GLenum)c.x[0], (GLenum)c.x[1], (GLenum)(i32)c.x[2]);
    GLFN_END

    // ---- textures ----
    GLFN(void (*)(GLsizei, GLuint*), "glGenTextures")
        if (fn) {
            std::vector<GLuint> ids((size_t)c.x[0]);
            fn((GLsizei)c.x[0], ids.data());
            if (c.x[1]) gwrite(c.x[1], ids.data(), ids.size() * 4);
        }
    GLFN_END
    GLFN(void (*)(GLsizei, const GLuint*), "glDeleteTextures")
        if (fn) fn((GLsizei)c.x[0], (const GLuint*)guest_to_host(c.x[1]));
    GLFN_END
    GLFN(void (*)(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*),
         "glTexImage2D")
        if (fn) {
            u64 data = 0;
            gread(&data, c.sp, 8); // 9th argument on the stack (AAPCS64)
            LOGI("glTexImage2D: %dx%d fmt=0x%x type=0x%x data=0x%llx",
                 (int)(i32)c.x[3], (int)(i32)c.x[4], (unsigned)c.x[6], (unsigned)c.x[7],
                 (unsigned long long)data);
            fn((GLenum)c.x[0], (GLint)(i32)c.x[1], (GLint)(i32)c.x[2], (GLsizei)(i32)c.x[3],
               (GLsizei)(i32)c.x[4], (GLint)(i32)c.x[5], (GLenum)c.x[6], (GLenum)c.x[7],
               data ? guest_to_host(data) : nullptr);
        }
    GLFN_END
    GLFN(void (*)(GLenum, GLint, GLenum, GLsizei, GLsizei, GLint, GLsizei, const void*),
         "glCompressedTexImage2D")
        GLenum target = (GLenum)c.x[0];
        GLint level = (GLint)(i32)c.x[1];
        GLenum fmt = (GLenum)c.x[2];
        GLsizei w = (GLsizei)(i32)c.x[3];
        GLsizei h = (GLsizei)(i32)c.x[4];
        GLint border = (GLint)(i32)c.x[5];
        GLsizei imgSize = (GLsizei)(i32)c.x[6];
        const u8* src = (const u8*)guest_to_host(c.x[7]);
        if (fmt == 0x8D64 && src && w > 0 && h > 0) {
            // Decode GL_ETC1_RGB8_OES (0x8D64) to RGBA8 on the CPU so any desktop
            // OpenGL 2.1 driver can display compressed Android textures.
            static const int kEtc1Mod[8][2] = {
                {2, 8}, {5, 17}, {9, 29}, {13, 42},
                {18, 60}, {24, 80}, {33, 106}, {47, 183}
            };
            auto clamp8 = [](int v) -> u8 { return (u8)(v < 0 ? 0 : (v > 255 ? 255 : v)); };
            std::vector<u8> rgba((size_t)w * h * 4, 255);
            int bw = (w + 3) / 4, bh = (h + 3) / 4;
            const u8* blk = src;
            for (int by = 0; by < bh; ++by) {
                for (int bx = 0; bx < bw; ++bx, blk += 8) {
                    bool diff = (blk[3] & 2) != 0;
                    bool flip = (blk[3] & 1) != 0;
                    int t1 = (blk[3] >> 5) & 7;
                    int t2 = (blk[3] >> 2) & 7;
                    int r[2], g[2], b[2];
                    if (!diff) {
                        r[0] = ((blk[0] >> 4) & 0xf) * 17; r[1] = (blk[0] & 0xf) * 17;
                        g[0] = ((blk[1] >> 4) & 0xf) * 17; g[1] = (blk[1] & 0xf) * 17;
                        b[0] = ((blk[2] >> 4) & 0xf) * 17; b[1] = (blk[2] & 0xf) * 17;
                    } else {
                        auto s3 = [](int v) { return (v & 4) ? (v - 8) : v; };
                        int r0 = (blk[0] >> 3) & 0x1f, dr = s3(blk[0] & 7);
                        int g0 = (blk[1] >> 3) & 0x1f, dg = s3(blk[1] & 7);
                        int b0 = (blk[2] >> 3) & 0x1f, db = s3(blk[2] & 7);
                        int r1 = (r0 + dr) & 0x1f, g1 = (g0 + dg) & 0x1f, b1 = (b0 + db) & 0x1f;
                        r[0] = (r0 << 3) | (r0 >> 2); r[1] = (r1 << 3) | (r1 >> 2);
                        g[0] = (g0 << 3) | (g0 >> 2); g[1] = (g1 << 3) | (g1 >> 2);
                        b[0] = (b0 << 3) | (b0 >> 2); b[1] = (b1 << 3) | (b1 >> 2);
                    }
                    u32 low = ((u32)blk[4] << 24) | ((u32)blk[5] << 16) |
                              ((u32)blk[6] << 8) | (u32)blk[7];
                    for (int py = 0; py < 4; ++py) {
                        int y = by * 4 + py;
                        if (y >= h) continue;
                        for (int px = 0; px < 4; ++px) {
                            int x = bx * 4 + px;
                            if (x >= w) continue;
                            int sub = flip ? (py >= 2 ? 1 : 0) : (px >= 2 ? 1 : 0);
                            int bit = px * 4 + py;
                            int lsb = (low >> bit) & 1;
                            int msb = (low >> (bit + 16)) & 1;
                            int d = kEtc1Mod[sub ? t2 : t1][lsb];
                            if (msb) d = -d;
                            u8* dst = &rgba[((size_t)y * w + x) * 4];
                            dst[0] = clamp8(r[sub] + d);
                            dst[1] = clamp8(g[sub] + d);
                            dst[2] = clamp8(b[sub] + d);
                            dst[3] = 255;
                        }
                    }
                }
            }
            using Tex2DFn = void (*)(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*);
            static Tex2DFn tex2d = (Tex2DFn)glproc("glTexImage2D");
            if (tex2d) {
                tex2d(target, level, GL_RGBA, w, h, border, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
                LOGI("glCompressedTexImage2D: decoded ETC1 %dx%d (%d B) -> RGBA8", (int)w, (int)h, (int)imgSize);
            }
        } else if (fn) {
            fn(target, level, fmt, w, h, border, imgSize, src);
        }
    GLFN_END

    // ---- buffers ----
    GLFN(void (*)(GLsizei, GLuint*), "glGenBuffers")
        if (fn) {
            std::vector<GLuint> ids((size_t)c.x[0]);
            fn((GLsizei)c.x[0], ids.data());
            if (c.x[1]) gwrite(c.x[1], ids.data(), ids.size() * 4);
        }
    GLFN_END
    GLFN(void (*)(GLsizei, const GLuint*), "glDeleteBuffers")
        if (fn) fn((GLsizei)c.x[0], (const GLuint*)guest_to_host(c.x[1]));
    GLFN_END
    GLFN(void (*)(GLenum, GLenum), "glBindBuffer")
        if (fn) fn((GLenum)c.x[0], (GLenum)c.x[1]);
    GLFN_END
    GLFN(void (*)(GLenum, GLsizeiptr, const void*, GLenum), "glBufferData")
        if (fn) fn((GLenum)c.x[0], (GLsizeiptr)(i64)c.x[1],
                   c.x[2] ? guest_to_host(c.x[2]) : nullptr, (GLenum)c.x[3]);
    GLFN_END
    GLFN(void (*)(GLenum, GLintptr, GLsizeiptr, const void*), "glBufferSubData")
        if (fn) {
            const void* src = c.x[3] ? guest_to_host(c.x[3]) : nullptr;
            static int n = 0;
            if (n++ < 25 && src && c.x[2] >= 20) {
                const float* fv = (const float*)src;
                const u32* iv = (const u32*)src;
                LOGI("glBufferSubData #%d size=%lld v0=(%.2f,%.2f uv=%.2f,%.2f col=0x%08x) v3=(%.2f,%.2f col=0x%08x)",
                     n, (long long)c.x[2], fv[0], fv[1], fv[2], fv[3], iv[4],
                     c.x[2] >= 80 ? fv[15] : 0.f, c.x[2] >= 80 ? fv[16] : 0.f, c.x[2] >= 80 ? iv[19] : 0u);
            }
            fn((GLenum)c.x[0], (GLintptr)(i64)c.x[1], (GLsizeiptr)(i64)c.x[2], src);
        }
    GLFN_END

    // ---- shaders / programs ----
    GLFN(GLuint (*)(GLenum), "glCreateShader")
        if (fn) c.ret = fn((GLenum)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLuint), "glDeleteShader") if (fn) fn((GLuint)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLuint, GLsizei, const GLchar* const*, const GLint*), "glShaderSource")
        if (fn) {
            int n = (int)(i32)c.x[1];
            std::vector<std::string> kept;
            std::vector<const GLchar*> ptrs;
            u64 arr = c.x[2];
            for (int i = 0; i < n; ++i) {
                u64 gp = 0;
                gread(&gp, arr + (u64)i * 8, 8);
                kept.push_back(sanitize_shader(gstr(gp)));
            }
            for (auto& s : kept)
                ptrs.push_back(s.c_str());
            fn((GLuint)c.x[0], n, ptrs.data(), nullptr);
        }
    GLFN_END
    GLFN(void (*)(GLuint), "glCompileShader") if (fn) fn((GLuint)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLuint, GLenum, GLint*), "glGetShaderiv")
        if (fn) {
            GLint v = 0;
            fn((GLuint)c.x[0], (GLenum)c.x[1], &v);
            LOGI("glGetShaderiv(shader=%u, pname=0x%x) -> %d", (unsigned)c.x[0], (unsigned)c.x[1], (int)v);
            if (c.x[2]) gwrite(c.x[2], &v, 4);
        }
    GLFN_END
    GLFN(void (*)(GLuint, GLsizei, GLsizei*, GLchar*), "glGetShaderInfoLog")
        if (fn) {
            static char buf[8192];
            GLsizei len = 0;
            fn((GLuint)c.x[0], (GLsizei)c.x[1], &len, buf);
            if (c.x[3] && len > 0) gwrite(c.x[3], buf, (u64)len);
            if (len > 0) LOGW("shader log: %.*s", (int)len, buf);
        }
    GLFN_END
    GLFN(GLuint (*)(void), "glCreateProgram")
        if (fn) c.ret = fn();
    GLFN_END
    GLFN(void (*)(GLuint), "glDeleteProgram") if (fn) fn((GLuint)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLuint, GLuint), "glAttachShader")
        if (fn) fn((GLuint)c.x[0], (GLuint)c.x[1]);
    GLFN_END
    GLFN(void (*)(GLuint, GLuint), "glDetachShader")
        if (fn) fn((GLuint)c.x[0], (GLuint)c.x[1]);
    GLFN_END
    GLFN(void (*)(GLuint, GLuint, const GLchar*), "glBindAttribLocation")
        if (fn) fn((GLuint)c.x[0], (GLuint)c.x[1], gstr(c.x[2]).c_str());
    GLFN_END
    GLFN(void (*)(GLuint), "glLinkProgram")
        if (fn) {
            fn((GLuint)c.x[0]);
            static int n = 0;
            if (n++ < 5) LOGI("glLinkProgram #%d", n);
        }
    GLFN_END
    GLFN(void (*)(GLuint, GLenum, GLint*), "glGetProgramiv")
        if (fn) {
            GLint v = 0;
            fn((GLuint)c.x[0], (GLenum)c.x[1], &v);
            LOGI("glGetProgramiv(prog=%u, pname=0x%x) -> %d", (unsigned)c.x[0], (unsigned)c.x[1], (int)v);
            if (c.x[2]) gwrite(c.x[2], &v, 4);
        }
    GLFN_END
    GLFN(void (*)(GLuint, GLsizei, GLsizei*, GLchar*), "glGetProgramInfoLog")
        if (fn) {
            static char buf[8192];
            GLsizei len = 0;
            fn((GLuint)c.x[0], (GLsizei)c.x[1], &len, buf);
            if (c.x[3] && len > 0) gwrite(c.x[3], buf, (u64)len);
            if (len > 0) LOGW("program log: %.*s", (int)len, buf);
        }
    GLFN_END
    GLFN(void (*)(GLuint), "glUseProgram")
        if (fn) {
            fn((GLuint)c.x[0]);
            static int n = 0;
            if (n == 1) LOGI("glUseProgram first call");
        }
    GLFN_END
    GLFN(GLint (*)(GLuint, const GLchar*), "glGetAttribLocation")
        if (fn) c.ret = (u64)(i64)fn((GLuint)c.x[0], gstr(c.x[1]).c_str());
        else c.ret = (u64)-1;
    GLFN_END
    GLFN(GLint (*)(GLuint, const GLchar*), "glGetUniformLocation")
        if (fn) c.ret = (u64)(i64)fn((GLuint)c.x[0], gstr(c.x[1]).c_str());
        else c.ret = (u64)-1;
    GLFN_END

    // ---- uniforms ----
    GLFN(void (*)(GLint, GLfloat), "glUniform1f") if (fn) fn((GLint)(i32)c.x[0], farg(c, 0));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLfloat*), "glUniform1fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLfloat*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLint), "glUniform1i") if (fn) fn((GLint)(i32)c.x[0], (GLint)(i32)c.x[1]);
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLint*), "glUniform1iv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLint*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLfloat, GLfloat), "glUniform2f")
        if (fn) fn((GLint)(i32)c.x[0], farg(c, 0), farg(c, 1));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLfloat*), "glUniform2fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLfloat*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLint, GLint), "glUniform2i")
        if (fn) fn((GLint)(i32)c.x[0], (GLint)(i32)c.x[1], (GLint)(i32)c.x[2]);
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLint*), "glUniform2iv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLint*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLfloat, GLfloat, GLfloat), "glUniform3f")
        if (fn) fn((GLint)(i32)c.x[0], farg(c, 0), farg(c, 1), farg(c, 2));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLfloat*), "glUniform3fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLfloat*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLint, GLint, GLint), "glUniform3i")
        if (fn) fn((GLint)(i32)c.x[0], (GLint)(i32)c.x[1], (GLint)(i32)c.x[2], (GLint)(i32)c.x[3]);
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLint*), "glUniform3iv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLint*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLfloat, GLfloat, GLfloat, GLfloat), "glUniform4f")
        if (fn) fn((GLint)(i32)c.x[0], farg(c, 0), farg(c, 1), farg(c, 2), farg(c, 3));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLfloat*), "glUniform4fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLfloat*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLint, GLint, GLint, GLint), "glUniform4i")
        if (fn) fn((GLint)(i32)c.x[0], (GLint)(i32)c.x[1], (GLint)(i32)c.x[2], (GLint)(i32)c.x[3],
                   (GLint)(i32)c.x[4]);
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, const GLint*), "glUniform4iv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (const GLint*)guest_to_host(c.x[2]));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, GLboolean, const GLfloat*), "glUniformMatrix2fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (GLboolean)c.x[2],
                   (const GLfloat*)guest_to_host(c.x[3]));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, GLboolean, const GLfloat*), "glUniformMatrix3fv")
        if (fn) fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (GLboolean)c.x[2],
                   (const GLfloat*)guest_to_host(c.x[3]));
    GLFN_END
    GLFN(void (*)(GLint, GLsizei, GLboolean, const GLfloat*), "glUniformMatrix4fv")
        if (fn) {
            const GLfloat* m = (const GLfloat*)guest_to_host(c.x[3]);
            static int n = 0;
            if (n++ < 4 && m) {
                LOGI("glUniformMatrix4fv loc=%d m=[%.3f %.3f %.3f %.3f | %.3f %.3f %.3f %.3f]",
                     (int)(i32)c.x[0], m[0], m[5], m[10], m[15], m[12], m[13], m[14], m[15]);
            }
            fn((GLint)(i32)c.x[0], (GLsizei)(i32)c.x[1], (GLboolean)c.x[2], m);
        }
    GLFN_END

    // ---- vertex attributes / draws ----
    GLFN(void (*)(GLuint), "glEnableVertexAttribArray") if (fn) fn((GLuint)c.x[0]);
    GLFN_END
    GLFN(void (*)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*), "glVertexAttribPointer")
        if (fn) {
            const void* ptr = (c.x[5] >= kGuestBase) ? guest_to_host(c.x[5]) : (const void*)(uintptr_t)c.x[5];
            static int n = 0;
            if (n++ < 10)
                LOGI("glVertexAttribPointer idx=%u size=%d type=0x%x norm=%u stride=%d ptr=0x%llx",
                     (unsigned)c.x[0], (int)(i32)c.x[1], (unsigned)c.x[2], (unsigned)c.x[3],
                     (int)(i32)c.x[4], (unsigned long long)c.x[5]);
            fn((GLuint)c.x[0], (GLint)(i32)c.x[1], (GLenum)c.x[2], (GLboolean)c.x[3],
               (GLsizei)(i32)c.x[4], ptr);
        }
    GLFN_END
    GLFN(void (*)(GLenum, GLint, GLsizei), "glDrawArrays")
        if (fn) {
            fn((GLenum)c.x[0], (GLint)(i32)c.x[1], (GLsizei)(i32)c.x[2]);
            static int n = 0;
            if (n++ < 5) LOGI("glDrawArrays #%d mode=%u count=%d", n, (unsigned)c.x[0],
                              (int)(i32)c.x[2]);
        }
    GLFN_END
    GLFN(void (*)(GLenum, GLsizei, GLenum, const void*), "glDrawElements")
        if (fn) {
            const void* idx = (c.x[3] >= kGuestBase) ? guest_to_host(c.x[3]) : (const void*)(uintptr_t)c.x[3];
            fn((GLenum)c.x[0], (GLsizei)(i32)c.x[1], (GLenum)c.x[2], idx);
            static int n = 0;
            if (n++ < 15)
                LOGI("glDrawElements #%d mode=%u count=%d type=0x%x idx=0x%llx err=0x%x",
                     n, (unsigned)c.x[0], (int)(i32)c.x[1], (unsigned)c.x[2],
                     (unsigned long long)c.x[3], (unsigned)glGetError());
        }
    GLFN_END

    // ---- queries ----
    register_host_fn("glGetString", [](GuestCall& c) {
        using PFN = const GLubyte* (*)(GLenum);
        static PFN fn = (PFN)glproc("glGetString");
        static std::map<u32, u64> cache;
        u32 name = (u32)c.x[0];
        auto it = cache.find(name);
        if (it != cache.end()) { c.ret = it->second; return; }
        std::string str;
        // The engine validates the GL identity; report GLES2 equivalents.
        if (name == 0x1F02)                      // GL_VERSION
            str = "OpenGL ES 2.0 (sjfport)";
        else if (name == 0x1F01)                 // GL_RENDERER
            str = "sjfport Renderer";
        else if (name == 0x8B8C)                 // GL_SHADING_LANGUAGE_VERSION
            str = "OpenGL ES GLSL ES 1.00";
        else {
            const GLubyte* s = fn ? fn((GLenum)name) : nullptr;
            if (!s) { c.ret = 0; return; }
            str = (const char*)s;
        }
        u64 g = alloc_native_data(str.size() + 1, 8);
        if (g) gwrite(g, str.c_str(), str.size() + 1);
        cache[name] = g;
        c.ret = g;
    });
}

} // namespace sjf
