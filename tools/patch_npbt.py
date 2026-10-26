import io

p = 'port/src/runtime/jit.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
if 'dump_backtrace' in s and 'dump_backtrace(what);\n        dump_backtrace' not in s:
    pass
# add backtrace to null_page_read
old = '''        static std::mutex nm;
        static int nn = 0;
        {
            std::lock_guard<std::mutex> lk(nm);
            if (nn++ < 60)
                LOGW("null-page read @0x%llx (%s) pc=0x%llx",
                     (unsigned long long)vaddr, what,
                     (unsigned long long)(jit_ ? jit_->GetPC() : 0));
        }'''
new = '''        static std::mutex nm;
        static int nn = 0;
        {
            std::lock_guard<std::mutex> lk(nm);
            if (nn++ < 12) {
                LOGW("null-page read @0x%llx (%s) pc=0x%llx",
                     (unsigned long long)vaddr, what,
                     (unsigned long long)(jit_ ? jit_->GetPC() : 0));
                dump_backtrace("null-page read");
            }
        }'''
if old in s:
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('backtrace added to null_page_read')
else:
    print('pattern miss')
