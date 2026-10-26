// Guest ABI helpers: strings, memory and the AAPCS64 vararg printf engine.
#include "sjfport/guest_abi.h"
#include "sjfport/guest_memory.h"
#include <cctype>
#include <cstdio>
#include <cstring>

namespace sjf {

std::string gstr(u64 gaddr) {
    if (!gaddr)
        return "(null)";
    const char* p = reinterpret_cast<const char*>(guest_to_host(gaddr));
    if (!p)
        return "(bad-addr)";
    // clamp to 4 KiB (strnlen is POSIX; do it manually for portability)
    size_t n = 0;
    while (n < 4096 && p[n])
        ++n;
    return std::string(p, n);
}

void gwrite(u64 gaddr, const void* data, u64 size) {
    void* p = guest_to_host(gaddr);
    if (p)
        std::memcpy(p, data, (size_t)size);
}

void gread(void* out, u64 gaddr, u64 size) {
    void* p = guest_to_host(gaddr);
    if (p)
        std::memcpy(out, p, (size_t)size);
}

u64 GuestCall_vararg_gp(GuestCall& c) {
    if (c.use_valist) {
        if (!c.va_inited) {
            struct VL { u64 stack, gr_top, vr_top; i32 gr_offs, vr_offs; } vl{};
            gread(&vl, c.va_ptr, sizeof(vl));
            c.va_stack = vl.stack;
            c.va_gr_top = vl.gr_top;
            c.va_vr_top = vl.vr_top;
            c.va_gr_offs = vl.gr_offs;
            c.va_vr_offs = vl.vr_offs;
            c.va_inited = true;
        }
        if (c.va_gr_offs < 0) {
            u64 v = 0;
            gread(&v, c.va_gr_top + c.va_gr_offs, 8);
            c.va_gr_offs += 8;
            return v;
        }
        u64 v = 0;
        gread(&v, c.va_stack, 8);
        c.va_stack += 8;
        return v;
    }
    if (c.vargp < 8)
        return c.x[c.vargp++];
    u64 v = 0;
    gread(&v, c.sp + c.vargs, 8);
    c.vargs += 8;
    return v;
}

double GuestCall_vararg_fp(GuestCall& c) {
    if (c.use_valist) {
        if (!c.va_inited) {
            struct VL { u64 stack, gr_top, vr_top; i32 gr_offs, vr_offs; } vl{};
            gread(&vl, c.va_ptr, sizeof(vl));
            c.va_stack = vl.stack;
            c.va_gr_top = vl.gr_top;
            c.va_vr_top = vl.vr_top;
            c.va_gr_offs = vl.gr_offs;
            c.va_vr_offs = vl.vr_offs;
            c.va_inited = true;
        }
        if (c.va_vr_offs < 0) {
            u64 bits = 0;
            gread(&bits, c.va_vr_top + c.va_vr_offs, 8);
            c.va_vr_offs += 16;
            double d;
            std::memcpy(&d, &bits, 8);
            return d;
        }
        u64 bits = 0;
        gread(&bits, c.va_stack, 8);
        c.va_stack += 8;
        double d;
        std::memcpy(&d, &bits, 8);
        return d;
    }
    if (c.vargf < 8) {
        u64 bits = c.v[c.vargf++];
        double d;
        std::memcpy(&d, &bits, 8);
        return d;
    }
    u64 bits = 0;
    gread(&bits, c.sp + c.vargs, 8);
    c.vargs += 8;
    double d;
    std::memcpy(&d, &bits, 8);
    return d;
}

namespace {

struct IntSpec {
    int width = 0;
    int prec = -1;      // -1 = not given
    bool zero = false, left = false, plus = false, space = false, alt = false;
};

// C99 integer conversion (%d %i %u %x %X %o): honours width, precision,
// and the 0 - + space # flags exactly like bionic/glibc printf.
void emit_int(std::string& out, u64 value, bool is_signed, int base, bool upper, const IntSpec& f) {
    const char* digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
    bool neg = false;
    if (is_signed && (i64)value < 0) {
        neg = true;
        value = (u64)0 - value;
    }
    std::string num;
    for (u64 v = value; v; v /= (u64)base)
        num.insert(num.begin(), digits[v % (u64)base]);
    if (f.prec < 0 && num.empty())
        num = "0";                                   // plain 0
    if (f.prec >= 0 && (int)num.size() < f.prec)
        num.insert(0, (size_t)(f.prec - (int)num.size()), '0');
    if (f.alt && base == 8 && (num.empty() || num[0] != '0'))
        num.insert(num.begin(), '0');
    std::string prefix;
    if (is_signed)
        prefix = neg ? "-" : (f.plus ? "+" : (f.space ? " " : ""));
    if (f.alt && base == 16 && value != 0)
        prefix = upper ? "0X" : "0x";
    int len = (int)(prefix.size() + num.size());
    int pad = f.width > len ? f.width - len : 0;
    if (f.left) {
        out += prefix + num;
        out.append((size_t)pad, ' ');
    } else if (f.zero && f.prec < 0) {
        out += prefix;
        out.append((size_t)pad, '0');                // zeros go after the sign/0x
        out += num;
    } else {
        out.append((size_t)pad, ' ');
        out += prefix + num;
    }
}

void emit_fp(std::string& out, double d, char conv, const IntSpec& f) {
    // Delegate to the host printf with the same flags/width/precision.
    char fmt[48], buf[512];
    std::string flags;
    if (f.left) flags += '-';
    if (f.plus) flags += '+';
    if (f.space) flags += ' ';
    if (f.alt) flags += '#';
    if (f.zero) flags += '0';
    if (f.prec >= 0)
        std::snprintf(fmt, sizeof(fmt), "%%%s%d.%d%c", flags.c_str(), f.width, f.prec, conv);
    else
        std::snprintf(fmt, sizeof(fmt), "%%%s%d%c", flags.c_str(), f.width, conv);
    std::snprintf(buf, sizeof(buf), fmt, d);
    out += buf;
}

} // namespace

std::string guest_format(GuestCall& c, u64 fmt_gaddr) {
    std::string fmt = gstr(fmt_gaddr);
    std::string out;
    size_t i = 0;
    while (i < fmt.size()) {
        char ch = fmt[i++];
        if (ch != '%') {
            out += ch;
            continue;
        }
        if (i >= fmt.size())
            break;
        if (fmt[i] == '%') {
            out += '%';
            ++i;
            continue;
        }
        // flags
        bool zero_pad = false, alt = false, left = false, plus = false, space = false;
        while (i < fmt.size()) {
            char f = fmt[i];
            if (f == '0') zero_pad = true;
            else if (f == '#') alt = true;
            else if (f == '-') left = true;
            else if (f == '+') plus = true;
            else if (f == ' ') space = true;
            else break;
            ++i;
        }
        // width
        int width = 0;
        bool has_width = false;
        if (i < fmt.size() && fmt[i] == '*') {
            width = (int)c.vararg_gp();
            has_width = true;
            ++i;
        } else {
            while (i < fmt.size() && std::isdigit((unsigned char)fmt[i])) {
                width = width * 10 + (fmt[i] - '0');
                has_width = true;
                ++i;
            }
        }
        // precision
        int prec = -1;
        if (i < fmt.size() && fmt[i] == '.') {
            ++i;
            prec = 0;
            if (i < fmt.size() && fmt[i] == '*') {
                prec = (int)c.vararg_gp();
                ++i;
            } else {
                while (i < fmt.size() && std::isdigit((unsigned char)fmt[i])) {
                    prec = prec * 10 + (fmt[i] - '0');
                    ++i;
                }
            }
        }
        // length modifiers
        int lng = 0; // 0=int, 1=long, 2=long long, -1=short, -2=char, 'L'=long double, 'z'=size_t
        bool is_size_t = false, is_ptrdiff = false;
        while (i < fmt.size()) {
            char l = fmt[i];
            if (l == 'l') { ++lng; ++i; }
            else if (l == 'h') { --lng; ++i; }
            else if (l == 'z') { is_size_t = true; ++i; }
            else if (l == 't') { is_ptrdiff = true; ++i; }
            else if (l == 'L') { lng = 99; ++i; }
            else if (l == 'j') { lng = 2; ++i; }
            else break;
        }
        if (i >= fmt.size())
            break;
        char conv = fmt[i++];
        bool big = (lng >= 1) || is_size_t || is_ptrdiff; // 64-bit value on LP64
        IntSpec is;
        is.width = width < 0 ? -width : width; // negative '*' width = left-justify
        is.left = left || width < 0;
        is.prec = prec;
        is.zero = zero_pad;
        is.plus = plus;
        is.space = space;
        is.alt = alt;
        (void)has_width;
        switch (conv) {
            case 'd':
            case 'i': {
                u64 v = c.vararg_gp();
                if (lng == -1) v = (u64)(i16)v;
                else if (lng <= -2) v = (u64)(i8)v;
                else if (!big) v = (u64)(i32)v;
                emit_int(out, v, true, 10, false, is);
                break;
            }
            case 'u': {
                u64 v = c.vararg_gp();
                if (lng == -1) v = (u16)v;
                else if (lng <= -2) v = (u8)v;
                else if (!big) v = (u32)v;
                emit_int(out, v, false, 10, false, is);
                break;
            }
            case 'x': {
                u64 v = c.vararg_gp();
                if (lng == -1) v = (u16)v;
                else if (lng <= -2) v = (u8)v;
                else if (!big) v = (u32)v;
                emit_int(out, v, false, 16, false, is);
                break;
            }
            case 'X': {
                u64 v = c.vararg_gp();
                if (lng == -1) v = (u16)v;
                else if (lng <= -2) v = (u8)v;
                else if (!big) v = (u32)v;
                emit_int(out, v, false, 16, true, is);
                break;
            }
            case 'o': {
                u64 v = c.vararg_gp();
                if (lng == -1) v = (u16)v;
                else if (lng <= -2) v = (u8)v;
                else if (!big) v = (u32)v;
                emit_int(out, v, false, 8, false, is);
                break;
            }
            case 'c': {
                u64 v = c.vararg_gp();
                if (!is.left && is.width > 1) out.append((size_t)(is.width - 1), ' ');
                out += (char)(u32)v;
                if (is.left && is.width > 1) out.append((size_t)(is.width - 1), ' ');
                break;
            }
            case 's': {
                u64 p = c.vararg_gp();
                std::string s = gstr(p);
                if (prec >= 0 && (size_t)prec < s.size())
                    s.resize((size_t)prec);
                if (!left && width > (int)s.size())
                    out.append((size_t)(width - (int)s.size()), ' ');
                out += s;
                if (left && width > (int)s.size())
                    out.append((size_t)(width - (int)s.size()), ' ');
                break;
            }
            case 'p': {
                u64 v = c.vararg_gp();
                IntSpec ps;
                ps.alt = true;
                ps.width = is.width;
                ps.left = is.left;
                emit_int(out, v, false, 16, false, ps);
                break;
            }
            case 'f': case 'F': case 'e': case 'E': case 'g': case 'G': {
                double d = c.vararg_fp();
                emit_fp(out, d, conv, is);
                break;
            }
            default:
                out += '%';
                out += conv;
                break;
        }
    }
    return out;
}

} // namespace sjf
