# convert_music.py — make the port's background music playable.
# The game streams AAC (.m4a) through Java's MediaPlayer; the port has no AAC
# decoder, so convert each .m4a once to an .ogg twin (decoded by stb_vorbis).
#
# usage: python tools/convert_music.py [assets_dir] [--ffmpeg PATH]
#   default assets_dir: port/game/assets  (needs ffmpeg on PATH or --ffmpeg)
import os, subprocess, sys, shutil

here = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:]]
ffmpeg = 'ffmpeg'
if '--ffmpeg' in args:
    i = args.index('--ffmpeg'); ffmpeg = args[i + 1]; del args[i:i + 2]
assets = args[0] if args else os.path.join(here, '..', 'port', 'game', 'assets')
if not shutil.which(ffmpeg) and not os.path.isfile(ffmpeg):
    sys.exit('ffmpeg not found (install it or pass --ffmpeg C:/path/ffmpeg.exe)')

n = 0
for name in sorted(os.listdir(assets)):
    if not name.lower().endswith('.m4a'):
        continue
    src = os.path.join(assets, name)
    dst = os.path.splitext(src)[0] + '.ogg'
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        continue
    subprocess.run([ffmpeg, '-loglevel', 'error', '-y', '-i', src, '-vn', '-c:a', 'libvorbis',
                    '-q:a', '5', dst], check=True)
    n += 1
    print('ok', os.path.basename(dst), os.path.getsize(dst) // 1024, 'KiB')
print('%d file(s) converted in %s' % (n, os.path.abspath(assets)))
