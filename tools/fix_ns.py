import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

bad = """                 (unsigned long long)value, (unsigned long long)pc);
    }
}
} // namespace

// Sentinel return address"""
good = """                 (unsigned long long)value, (unsigned long long)pc);
    }
}

// Sentinel return address"""

if bad in s:
    s = s.replace(bad, good, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('fixed namespace close')
else:
    print('pattern not found')
