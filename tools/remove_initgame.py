import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

start = s.find('    // Force-open the initGame gate')
end = s.find('    LOGI("boot: entering frame loop')
if start != -1 and end != -1 and start < end:
    s = s[:start] + s[end:]
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('manual initGame/flag hack removed')
else:
    print('anchors off', start, end)
