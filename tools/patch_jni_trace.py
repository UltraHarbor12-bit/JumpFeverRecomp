import io

p = 'port/src/dex/jni_env.cpp'
s = io.open(p, encoding='utf-8', newline=None).read()

s = s.replace('''    const std::string& n = m->name;
    FakeMeta* self = fake_of(obj_or_class);''',
'''    const std::string& n = m->name;
    FakeMeta* self = fake_of(obj_or_class);
    if (g_verbose_jni)
        LOGD("JNI call %s%s.%s", is_static ? "static " : "",
             self ? self->name.c_str() : "?", n.c_str());''')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched jni trace')
