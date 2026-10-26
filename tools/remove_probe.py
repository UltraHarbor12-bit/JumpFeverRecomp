import io

p = 'port/src/engine/boot.cpp'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()
start = s.find('    // Probe: initialise PlayerProfile')
end = s.find('    // Create the engine\'s lazy singletons')
if start != -1 and end != -1 and start < end:
    s = s[:start] + s[end:]
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('PlayerProfile probe removed')
else:
    print('probe block not found', start, end)
