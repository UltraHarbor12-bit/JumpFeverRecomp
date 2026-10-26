// Host module: libm
//
// AAPCS64 floating-point ABI: scalar float/double arguments arrive in v0..v7
// (s0..s7 / d0..d7) and scalar float/double results are returned in v0 (s0/d0).
// Pointer out-parameters (e.g. modf's iptr, frexp's exp) arrive in x0.
#include "sjfport/guest_abi.h"
#include "sjfport/host_calls.h"
#include <cmath>
#include <cstring>

namespace sjf {

namespace {
template <typename F>
void regf(const char* name, F fn) {
    register_host_fn(name, [fn](GuestCall& c) {
        c.set_f32(fn(c.f32(0)));
    });
}
} // namespace

void register_libm_module() {
    regf("acosf", [](float x) { return std::acos(x); });
    regf("cosf", [](float x) { return std::cos(x); });
    regf("sinf", [](float x) { return std::sin(x); });
    regf("expf", [](float x) { return std::exp(x); });
    regf("log10f", [](float x) { return std::log10(x); });
    regf("sqrtf", [](float x) { return std::sqrt(x); });

    register_host_fn("powf", [](GuestCall& c) {
        c.set_f32(std::pow(c.f32(0), c.f32(1)));
    });
    register_host_fn("atan2f", [](GuestCall& c) {
        c.set_f32(std::atan2(c.f32(0), c.f32(1)));
    });
    register_host_fn("fmodf", [](GuestCall& c) {
        c.set_f32(std::fmod(c.f32(0), c.f32(1)));
    });
    register_host_fn("modf", [](GuestCall& c) {
        double ip = 0;
        double r = std::modf(c.f64(0), &ip);
        if (c.x[0]) gwrite(c.x[0], &ip, 8);
        c.set_f64(r);
    });
    register_host_fn("frexp", [](GuestCall& c) {
        int e = 0;
        double r = std::frexp(c.f64(0), &e);
        if (c.x[0]) { i32 ee = e; gwrite(c.x[0], &ee, 4); }
        c.set_f64(r);
    });
    register_host_fn("pow", [](GuestCall& c) {
        c.set_f64(std::pow(c.f64(0), c.f64(1)));
    });
}

} // namespace sjf
