import io

p = 'port/CMakeLists.txt'
s = io.open(p, encoding='utf-8', newline=None).read()
print('before:', [l for l in s.split('\n') if 'SDL2_DIR' in l])
s = s.replace('${SDL2_DIR}/include\n', '${SDL2_DIR}/include/SDL2\n')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('after :', [l for l in s.split('\n') if 'SDL2_DIR' in l])
