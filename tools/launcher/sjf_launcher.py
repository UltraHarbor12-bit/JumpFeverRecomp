#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jump Fever Recomp - Launcher / builder
=====================================

Un solo archivo, solo libreria estandar de Python 3.8+ (tkinter para la GUI).

  1. Pide TU APK de Sonic Jump Fever (1.6.1), lo valida y extrae lo que el port
     necesita: lib/arm64-v8a/libsonicjumpfever.so, el APK como base.apk y los
     61 assets. Opcional: convierte la musica .m4a -> .ogg (ffmpeg).
  2. Eliges plataforma de destino: Windows o Linux.
       host Windows -> Windows : MinGW-w64 (WinLibs) + CMake + Ninja (nativo)
       host Linux   -> Linux   : g++/clang del sistema (o entorno micromamba)
       host Linux   -> Windows : compilacion cruzada con zig (pip ziglang)
       host Windows -> Linux   : via WSL (experimental)
     Detecta las herramientas y descarga las que falten a tools/.
  3. Compila (CMake + Ninja) mostrando el progreso.
  4. Juega, o crea una carpeta portable en dist/<plataforma>/.

Uso:
  python tools/launcher/sjf_launcher.py                 (GUI)
  python tools/launcher/sjf_launcher.py --cli --apk sonic.apk --target linux --build --run
  python tools/launcher/sjf_launcher.py --help

Proyecto personal: el launcher no descarga ni distribuye nada del juego; usa
exclusivamente el APK que tu le indiques.
"""
import argparse
import ctypes.util
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
PORT = os.path.join(ROOT, 'port')
TOOLS = os.path.join(ROOT, 'tools')
GAME = os.path.join(PORT, 'game')
SETTINGS = os.path.join(HERE, 'launcher.json')
IS_WIN = os.name == 'nt'
HOST = 'windows' if IS_WIN else ('linux' if sys.platform.startswith('linux') else sys.platform)

APK_PACKAGE = 'com.sega.sonicjumpfever'
SO_IN_APK = 'lib/arm64-v8a/libsonicjumpfever.so'
# Native library the port was reverse-engineered against (addresses are hard-coded).
KNOWN_SO = {
    '4bbe841e2068c389324414750ccd37ca8153a693643d1cd62e4377c5cb07bd3f': 'Sonic Jump Fever 1.6.1 (arm64-v8a)',
}

SDL2_VER = '2.32.10'
URLS = {
    'sdl2_mingw': 'https://github.com/libsdl-org/SDL/releases/download/release-%s/SDL2-devel-%s-mingw.tar.gz'
                  % (SDL2_VER, SDL2_VER),
    'winlibs': 'https://github.com/brechtsanders/winlibs_mingw/releases/download/'
               '14.2.0posix-19.1.1-12.0.0-ucrt-r2/'
               'winlibs-x86_64-posix-seh-gcc-14.2.0-mingw-w64ucrt-12.0.0-r2.zip',
    'boost': 'https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.bz2',
    'ffmpeg_win': 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
    'micromamba_linux': 'https://micro.mamba.pm/api/micromamba/linux-64/latest',
    # Direct fallbacks when pip fails or installs the tool somewhere unexpected.
    'ninja_win': 'https://github.com/ninja-build/ninja/releases/download/v1.13.1/ninja-win.zip',
    'ninja_linux': 'https://github.com/ninja-build/ninja/releases/download/v1.13.1/ninja-linux.zip',
    'cmake_win': 'https://github.com/Kitware/CMake/releases/download/v4.1.2/cmake-4.1.2-windows-x86_64.zip',
}
SDL2_MINGW_DIR = os.path.join(TOOLS, 'sdl2', 'SDL2-%s' % SDL2_VER, 'x86_64-w64-mingw32')
PYDEPS = os.path.join(TOOLS, 'pydeps')          # pip --target: cmake, ninja, ziglang
ENV_LINUX = os.path.join(TOOLS, 'env-linux')    # micromamba env (SDL2/Boost headers)

TARGETS = ('windows', 'linux')

# Zones. Offline the game always falls back to Green Hill (the server used to
# rotate the zone every week); sjfport --zone re-targets that fallback.
ZONES = [('green_hill_zone', 'Green Hill'), ('blue_sky_zone', 'Blue Sky'),
         ('jungle_zone', 'Jungle'), ('mechanical_zone', 'Mechanical')]
ZONE_CHOICES = ['weekly', 'game'] + [z for z, _ in ZONES]
ZONE_LABELS = {'weekly': 'Rotacion semanal (como el original)', 'game': 'La del juego (Green Hill)'}
ZONE_LABELS.update({z: n + ' Zone' for z, n in ZONES})


# Widescreen: the engine lays its UI out against the surface corners and draws
# the level across the whole width, so a wider guest surface (height kept at
# 960) gives real widescreen instead of black bars. sjfport --aspect W:H|auto.
ASPECTS = [('9:16', 'Vertical original (9:16)'), ('3:4', 'Tablet (3:4)'),
           ('4:3', 'Panoramica 4:3'), ('16:10', 'Panoramica 16:10'), ('16:9', 'Panoramica 16:9'),
           ('21:9', 'Ultrapanoramica 21:9'), ('auto', 'Automatica (proporcion del monitor)')]
ASPECT_CHOICES = [k for k, _ in ASPECTS]
ASPECT_LABELS = dict(ASPECTS)


def weekly_zone(date=None):
    """Weekly rotation like the original live service (one zone per ISO week).
    The exact historical order came from the server; this cycles the four zones."""
    import datetime
    d = date or datetime.date.today()
    w = d.isocalendar()[1]
    return ZONES[w % len(ZONES)][0], ZONES[(w + 1) % len(ZONES)][0]


def resolve_zone(choice):
    if choice in (None, '', 'game'):
        return None
    if choice == 'weekly':
        return weekly_zone()[0]
    if choice in dict(ZONES):
        return choice
    raise BuildError('zona desconocida: %s' % choice)


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# logging / settings
# ---------------------------------------------------------------------------
class Log:
    def __init__(self, sink=None):
        self.sink = sink or (lambda s: print(s, flush=True))

    def __call__(self, msg=''):
        self.sink(str(msg))


def load_settings():
    try:
        with open(SETTINGS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(d):
    try:
        with open(SETTINGS, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass


def exe_name(name):
    return name + '.exe' if IS_WIN else name


def which(name, extra_dirs=()):
    for d in extra_dirs:
        p = os.path.join(d, exe_name(name))
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def run(cmd, log, cwd=None, env=None, progress=None):
    """Run a command, stream its output to log; raise BuildError on failure."""
    log('$ ' + ' '.join('"%s"' % c if ' ' in c else c for c in cmd))
    flags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=flags)
    tail = []
    for raw in p.stdout:
        line = raw.decode('utf-8', 'replace').rstrip()
        tail.append(line)
        if len(tail) > 15:
            tail.pop(0)
        m = re.match(r'\[(\d+)/(\d+)\]', line)
        if m and progress:
            progress(int(m.group(1)), int(m.group(2)))
        log(line)
    p.wait()
    if p.returncode != 0:
        last = '\n'.join(l for l in tail if l.strip())[-1500:]
        raise BuildError('el comando fallo (codigo %d): %s\n\nUltimas lineas:\n%s'
                         % (p.returncode, cmd[0], last or '(sin salida)'))


def download(url, dest, log):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        log('ya descargado: %s' % os.path.basename(dest))
        return dest
    log('descargando %s' % url)
    tmp = dest + '.part'
    req = urllib.request.Request(url, headers={'User-Agent': 'sjf-launcher/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        done, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if pct // 10 != last:
                    last = pct // 10
                    log('  %3d%%  (%d / %d MiB)' % (pct, done >> 20, total >> 20))
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------------------
# 1. APK
# ---------------------------------------------------------------------------
def inspect_apk(apk):
    """Returns dict(ok, msg, version, so_sha, assets)."""
    info = {'ok': False, 'msg': '', 'version': None, 'assets': 0}
    if not apk or not os.path.isfile(apk):
        info['msg'] = 'No se encuentra el archivo.'
        return info
    try:
        z = zipfile.ZipFile(apk)
    except zipfile.BadZipFile:
        info['msg'] = 'No es un APK valido (no es un ZIP).'
        return info
    names = set(z.namelist())
    if 'AndroidManifest.xml' not in names:
        info['msg'] = 'No es un APK (falta AndroidManifest.xml).'
        return info
    manifest = z.read('AndroidManifest.xml')
    if APK_PACKAGE.encode('utf-16-le') not in manifest and APK_PACKAGE.encode() not in manifest:
        info['msg'] = 'Este APK no es Sonic Jump Fever (%s).' % APK_PACKAGE
        return info
    if SO_IN_APK not in names:
        info['msg'] = 'El APK no trae la libreria ARM64 (%s). Necesitas la version arm64-v8a.' % SO_IN_APK
        return info
    so = z.read(SO_IN_APK)
    sha = hashlib.sha256(so).hexdigest()
    info['so_sha'] = sha
    info['assets'] = sum(1 for n in names if n.startswith('assets/') and n.count('/') == 1 and n != 'assets/')
    info['version'] = KNOWN_SO.get(sha)
    info['ok'] = True
    if info['version']:
        info['msg'] = 'OK: %s, %d assets.' % (info['version'], info['assets'])
    else:
        info['msg'] = ('APK de Sonic Jump Fever, pero la libreria no es la 1.6.1 conocida '
                       '(sha256 %s...). El port usa direcciones fijas de la 1.6.1: '
                       'probablemente no arranque.' % sha[:12])
    return info


def install_apk(apk, log, convert_music=True):
    info = inspect_apk(apk)
    log(info['msg'])
    if not info['ok']:
        raise BuildError(info['msg'])
    os.makedirs(os.path.join(GAME, 'assets'), exist_ok=True)
    os.makedirs(os.path.join(GAME, 'data'), exist_ok=True)
    z = zipfile.ZipFile(apk)
    with open(os.path.join(GAME, 'libsonicjumpfever.so'), 'wb') as f:
        f.write(z.read(SO_IN_APK))
    log('-> port/game/libsonicjumpfever.so')
    dst_apk = os.path.join(GAME, 'base.apk')
    if os.path.abspath(apk) != os.path.abspath(dst_apk):
        shutil.copyfile(apk, dst_apk)
    log('-> port/game/base.apk')
    n = 0
    for name in z.namelist():
        if name.startswith('assets/') and name.count('/') == 1 and name != 'assets/':
            out = os.path.join(GAME, 'assets', name[7:])
            data = z.read(name)
            if not (os.path.isfile(out) and os.path.getsize(out) == len(data)):
                with open(out, 'wb') as f:
                    f.write(data)
            n += 1
    log('-> port/game/assets: %d archivos' % n)
    build_extra_characters(log, force=True)
    if convert_music:
        convert_music_files(log)


def find_ffmpeg():
    p = shutil.which('ffmpeg')
    if p:
        return p
    base = os.path.join(TOOLS, 'ffmpeg')
    for dp, _, files in os.walk(base) if os.path.isdir(base) else []:
        if exe_name('ffmpeg') in files:
            return os.path.join(dp, exe_name('ffmpeg'))
    return None


def convert_music_files(log, fetch=False):
    ff = find_ffmpeg()
    if not ff and fetch and IS_WIN:
        zp = download(URLS['ffmpeg_win'], os.path.join(TOOLS, 'downloads', 'ffmpeg.zip'), log)
        log('descomprimiendo ffmpeg...')
        zipfile.ZipFile(zp).extractall(os.path.join(TOOLS, 'ffmpeg'))
        ff = find_ffmpeg()
    if not ff:
        log('AVISO: ffmpeg no encontrado: el juego funcionara SIN musica de fondo '
            '(los efectos si suenan). Instala ffmpeg o usa "Descargar lo que falta".')
        return False
    assets = os.path.join(GAME, 'assets')
    n = 0
    for name in sorted(os.listdir(assets)):
        if not name.lower().endswith('.m4a'):
            continue
        src = os.path.join(assets, name)
        dst = os.path.splitext(src)[0] + '.ogg'
        if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        run([ff, '-loglevel', 'error', '-y', '-i', src, '-vn', '-c:a', 'libvorbis', '-q:a', '5', dst], log)
        n += 1
    log('musica: %d pista(s) convertida(s) a .ogg' % n)
    return True


def build_extra_characters(log, force=False):
    """Cream/Rouge/Vector sprite packages (hito 10): donor sprites recoloured."""
    assets = os.path.join(GAME, 'assets')
    if not os.path.isdir(assets):
        return []
    try:
        sys.path.insert(0, HERE)
        import sjf_extra_chars
        return sjf_extra_chars.build_all(assets, log, force=force)
    except Exception as e:  # noqa - never block install/play over this
        log('aviso: no se pudieron generar los paquetes de Cream/Rouge/Vector (%s); '
            'el juego usara los sprites del donante sin recolorear' % e)
        return []


def game_installed():
    return all(os.path.isfile(os.path.join(GAME, f)) for f in ('libsonicjumpfever.so', 'base.apk')) and \
        os.path.isdir(os.path.join(GAME, 'assets')) and len(os.listdir(os.path.join(GAME, 'assets'))) >= 61


# ---------------------------------------------------------------------------
# 2. toolchains
# ---------------------------------------------------------------------------
def pip_tool(pkg, rel):
    p = os.path.join(PYDEPS, pkg, *rel)
    return p if os.path.isfile(p) else None


ENV_BIN = os.path.join(ENV_LINUX, 'bin')


NINJA_DIR = os.path.join(TOOLS, 'ninja')                         # ninja-*.zip fallback
CMAKE_ZIP_DIR = os.path.join(TOOLS, 'cmake-4.1.2-windows-x86_64')  # cmake zip fallback (Windows)


def is_posix_emulation_build(path):
    """MSYS2/Cygwin tools (e.g. devkitPro's c:\\devkitPro\\msys2\\usr\\bin\\cmake.exe) treat
    'C:/...' as a relative path when started from a native process -> configure
    fails ("source directory .../C:/sjf/port does not exist"). Never pick them."""
    if not IS_WIN or not path:
        return False
    low = path.replace('/', '\\').lower()
    if '\\msys' in low or 'cygwin' in low or '\\usr\\bin\\' in low:
        return True
    d = os.path.dirname(path)
    return any(os.path.isfile(os.path.join(d, dll)) for dll in ('msys-2.0.dll', 'cygwin1.dll'))


def find_tool(name, candidates):
    """First existing candidate (bundled copies), then PATH; MSYS/Cygwin builds skipped."""
    for c in candidates:
        if c and os.path.isfile(c) and not is_posix_emulation_build(c):
            return c
    p = shutil.which(name)
    if p and not is_posix_emulation_build(p):
        return p
    return None


def find_cmake():
    # cmake wheels keep the real binary in cmake/data/bin (PYDEPS/bin only has a
    # python launcher stub that needs PYTHONPATH), so prefer that one. The PATH
    # comes last: a stray MSYS2 cmake there broke COMPILAR (informe hito 10, #1).
    return find_tool('cmake', [os.path.join(PYDEPS, 'cmake', 'data', 'bin', exe_name('cmake')),
                               os.path.join(CMAKE_ZIP_DIR, 'bin', exe_name('cmake')),
                               os.path.join(ENV_BIN, exe_name('cmake'))])


def find_ninja():
    # ninja >= 1.13 wheels ship the binary as a "data script": pip --target puts
    # it in PYDEPS/bin (Scripts on some setups), no longer in ninja/data/bin (hito 9).
    # Same candidate order as cmake (informe hito 10, #3).
    return find_tool('ninja', [os.path.join(PYDEPS, 'bin', exe_name('ninja')),
                               os.path.join(PYDEPS, 'Scripts', exe_name('ninja')),
                               os.path.join(PYDEPS, 'ninja', 'data', 'bin', exe_name('ninja')),
                               os.path.join(NINJA_DIR, exe_name('ninja')),
                               os.path.join(ENV_BIN, exe_name('ninja'))])


def fetch_ninja_zip(log):
    url = URLS['ninja_win' if IS_WIN else 'ninja_linux']
    zp = download(url, os.path.join(TOOLS, 'downloads', os.path.basename(url)), log)
    os.makedirs(NINJA_DIR, exist_ok=True)
    zipfile.ZipFile(zp).extractall(NINJA_DIR)
    p = os.path.join(NINJA_DIR, exe_name('ninja'))
    if not IS_WIN and os.path.isfile(p):
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    log('ninja: %s' % p)


def fetch_cmake_zip(log):
    zp = download(URLS['cmake_win'], os.path.join(TOOLS, 'downloads', 'cmake-win.zip'), log)
    log('descomprimiendo CMake...')
    zipfile.ZipFile(zp).extractall(TOOLS)


def find_zig():
    return find_tool('zig', [os.path.join(PYDEPS, 'ziglang', exe_name('zig')),
                             os.path.join(ENV_BIN, exe_name('zig'))])


def have_pip():
    try:
        return subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True).returncode == 0
    except Exception:
        return False


def find_mingw_gxx():
    cands = [os.path.join(TOOLS, 'mingw64', 'bin'), r'C:\sjf-mingw\bin', r'C:\mingw64\bin']
    for d in cands:
        p = os.path.join(d, 'g++.exe')
        if os.path.isfile(p):
            return p
    p = shutil.which('g++')
    if p:
        try:
            out = subprocess.run([p, '-dumpmachine'], capture_output=True, text=True).stdout
            if 'mingw' in out:
                return p
        except Exception:
            pass
    return None


def find_boost():
    cands = [os.path.join(TOOLS, 'boost', 'boost_1_86_0'), r'C:\sjf-boost\boost_1_86_0',
             os.path.join(ENV_LINUX, 'include'), '/usr/include', '/usr/local/include']
    for d in cands:
        if os.path.isfile(os.path.join(d, 'boost', 'version.hpp')):
            return d
    return None


def find_linux_sdl2():
    """(prefix or None, uses_env) for building against SDL2 on Linux."""
    if os.path.isfile(os.path.join(ENV_LINUX, 'include', 'SDL2', 'SDL.h')):
        return ENV_LINUX, True
    for d in ('/usr', '/usr/local'):
        if os.path.isfile(os.path.join(d, 'include', 'SDL2', 'SDL.h')):
            return d, False
    return None, False


def find_linux_cxx():
    return which('g++') or which('clang++')


def toolchain_status(target):
    """List of (name, path_or_None, hint)."""
    s = [('cmake', find_cmake(), 'pip (tools/pydeps)'), ('ninja', find_ninja(), 'pip (tools/pydeps)')]
    if target == 'windows':
        if IS_WIN:
            s.append(('MinGW-w64 g++', find_mingw_gxx(), 'WinLibs GCC 14 -> tools/mingw64'))
        else:
            s.append(('zig (cross)', find_zig(), 'pip ziglang -> tools/pydeps'))
        s.append(('SDL2 MinGW', SDL2_MINGW_DIR if os.path.isdir(SDL2_MINGW_DIR) else None,
                  'SDL2-devel-%s-mingw -> tools/sdl2' % SDL2_VER))
        s.append(('Boost (headers)', find_boost(), 'boost 1.86 -> tools/boost'))
    else:
        if IS_WIN:
            wsl = shutil.which('wsl')
            s = [('WSL', wsl, 'instala WSL + Ubuntu (wsl --install)')]
            return s
        s.append(('g++/clang++', find_linux_cxx(), 'paquete build-essential'))
        sdl, _ = find_linux_sdl2()
        s.append(('SDL2 + Boost + GL headers', sdl if (sdl and find_boost()) else None,
                  'entorno micromamba -> tools/env-linux'))
    return s


def fetch_missing(target, log):
    os.makedirs(os.path.join(TOOLS, 'downloads'), exist_ok=True)
    pip_pkgs = []
    if not find_cmake():
        pip_pkgs.append('cmake')
    if not find_ninja():
        pip_pkgs.append('ninja')
    if target == 'windows' and not IS_WIN and not find_zig():
        pip_pkgs.append('ziglang')
    if pip_pkgs:
        # 'pip install --target --upgrade' replaces tools/pydeps/bin wholesale, so a
        # lone 'cmake' install deleted the ninja.exe of an earlier one (informe #4):
        # always install every pydeps tool together.
        for extra in ('cmake', 'ninja'):
            if extra not in pip_pkgs:
                pip_pkgs.append(extra)
        if target == 'windows' and not IS_WIN and 'ziglang' not in pip_pkgs and \
                os.path.isdir(os.path.join(PYDEPS, 'ziglang')):
            pip_pkgs.append('ziglang')
    if pip_pkgs:
        pip_err = None
        if have_pip():
            try:
                # A global user-install (PIP_USER / pip.ini 'user = true') makes pip refuse
                # '--target' ("Can not combine '--user' and '--target'", informe #2).
                penv = dict(os.environ, PIP_USER='0', PIP_DISABLE_PIP_VERSION_CHECK='1')
                for k in ('PIP_TARGET', 'PIP_PREFIX', 'PIP_REQUIRE_VIRTUALENV'):
                    penv.pop(k, None)
                run([sys.executable, '-m', 'pip', 'install', '--upgrade', '--target', PYDEPS] + pip_pkgs,
                    log, env=penv)
            except BuildError as e:  # proxy/SSL/permissions: fall back to direct downloads
                pip_err = e
                log('pip fallo (%s): uso descargas directas' % e)
        if have_pip() and (pip_err is None or IS_WIN):
            if not find_ninja():
                log('ninja no aparece tras pip: descargando el binario oficial')
                fetch_ninja_zip(log)
            if IS_WIN and not find_cmake():
                log('cmake no aparece tras pip: descargando el zip oficial')
                fetch_cmake_zip(log)
            if IS_WIN and 'ziglang' in pip_pkgs and not find_zig() and pip_err:
                raise pip_err
        elif IS_WIN and not have_pip():
            if not find_ninja():
                fetch_ninja_zip(log)
            if not find_cmake():
                fetch_cmake_zip(log)
        elif not IS_WIN:
            # Python without pip (e.g. Debian without python3-pip): use conda-forge.
            conda = {'cmake': 'cmake', 'ninja': 'ninja', 'ziglang': 'zig'}
            log('pip no disponible: instalando %s con micromamba' % ', '.join(pip_pkgs))
            setup_linux_env(log, [conda[p] for p in pip_pkgs])
        if not (find_ninja() and find_cmake()):
            raise BuildError('no se pudo instalar cmake/ninja (mira el log). Alternativa: instala '
                             'ninja y cmake a mano y ponlos en el PATH.')

    if target == 'windows':
        if not os.path.isdir(SDL2_MINGW_DIR):
            tp = download(URLS['sdl2_mingw'], os.path.join(TOOLS, 'downloads', 'sdl2-mingw.tar.gz'), log)
            log('descomprimiendo SDL2...')
            with tarfile.open(tp) as t:
                t.extractall(os.path.join(TOOLS, 'sdl2'))
        if not find_boost():
            tp = download(URLS['boost'], os.path.join(TOOLS, 'downloads', 'boost_1_86_0.tar.bz2'), log)
            log('descomprimiendo cabeceras de Boost (tarda un poco)...')
            with tarfile.open(tp) as t:
                members = [m for m in t.getmembers() if m.name.startswith('boost_1_86_0/boost/')]
                t.extractall(os.path.join(TOOLS, 'boost'), members=members)
        if IS_WIN and not find_mingw_gxx():
            zp = download(URLS['winlibs'], os.path.join(TOOLS, 'downloads', 'winlibs.zip'), log)
            log('descomprimiendo MinGW-w64 (~1 GiB, tarda)...')
            zipfile.ZipFile(zp).extractall(TOOLS)  # -> tools/mingw64
        if IS_WIN and not find_ffmpeg():
            convert_music_files(log, fetch=True)
    elif not IS_WIN:
        sdl, _ = find_linux_sdl2()
        if not (sdl and find_boost()):
            setup_linux_env(log)
    log('dependencias listas.')


def setup_linux_env(log, extra=()):
    mm = os.path.join(TOOLS, 'micromamba', 'bin', 'micromamba')
    if not os.path.isfile(mm):
        tp = download(URLS['micromamba_linux'], os.path.join(TOOLS, 'downloads', 'micromamba.tar.bz2'), log)
        with tarfile.open(tp) as t:
            t.extract('bin/micromamba', os.path.join(TOOLS, 'micromamba'))
        os.chmod(mm, os.stat(mm).st_mode | stat.S_IEXEC)
    env = dict(os.environ, MAMBA_ROOT_PREFIX=os.path.join(TOOLS, 'micromamba', 'root'))
    verb = 'install' if os.path.isdir(os.path.join(ENV_LINUX, 'conda-meta')) else 'create'
    pkgs = ['sdl2', 'boost-cpp', 'libgl-devel'] + list(extra)
    run([mm, verb, '-y', '-p', ENV_LINUX, '-c', 'conda-forge'] + pkgs, log, env=env)


# ---------------------------------------------------------------------------
# 3. build
# ---------------------------------------------------------------------------
def build_dir(target):
    if target == 'windows':
        return os.path.join(PORT, 'build' if IS_WIN else 'build-win-cross')
    return os.path.join(PORT, 'build-linux')


def exe_path(target):
    return os.path.join(build_dir(target), 'sjfport.exe' if target == 'windows' else 'sjfport')


def windows_src_root(log):
    """MinGW's linker chokes on spaces: build through a junction if needed."""
    if ' ' not in ROOT:
        return ROOT
    link = os.path.join(os.environ.get('SystemDrive', 'C:') + os.sep, 'sjf')
    if os.path.isdir(link):
        if os.path.isfile(os.path.join(link, 'port', 'CMakeLists.txt')) and \
                os.path.samefile(os.path.join(link, 'port'), PORT):
            return link
        raise BuildError('La ruta del proyecto tiene espacios y %s ya existe apuntando a otra carpeta. '
                         'Mueve el proyecto a una ruta sin espacios.' % link)
    log('ruta con espacios: creando union %s -> %s' % (link, ROOT))
    subprocess.run(['cmd', '/c', 'mklink', '/J', link, ROOT], check=True, capture_output=True)
    return link


def write_zig_wrappers(zig):
    d = os.path.join(PORT, 'cmake', 'zig')
    os.makedirs(d, exist_ok=True)
    tools = {'cc': 'cc -target x86_64-windows-gnu', 'c++': 'c++ -target x86_64-windows-gnu',
             'ar': 'ar', 'ranlib': 'ranlib', 'rc': 'rc'}
    for name, sub in tools.items():
        p = os.path.join(d, 'zig-' + name)
        with open(p, 'w', newline='\n') as f:
            f.write('#!/bin/sh\nexec "%s" %s "$@"\n' % (zig, sub))
        os.chmod(p, 0o755)


def fix_future_mtimes(root, log, skip=('build', 'build-linux', 'build-win', 'build-win-cross')):
    """Zip entries carry local time without a zone: unpacked on a machine whose clock
    is behind the packer's, sources look 'from the future' and ninja loops forever
    ("manifest 'build.ninja' still dirty after 100 tries", informe #5)."""
    now = time.time()
    n = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            p = os.path.join(dp, f)
            try:
                if os.path.getmtime(p) > now + 120:
                    os.utime(p, (now, now))
                    n += 1
            except OSError:
                pass
    if n:
        log('aviso: %d archivo(s) tenian fecha futura; ajustados a ahora (evita el bucle de ninja)' % n)
    return n


def build(target, log, jobs=None, config='Release', progress=None):
    fix_future_mtimes(PORT, log)
    if not game_installed():
        log('AVISO: aun no has instalado los datos del juego desde tu APK (paso 1).')
    jobs = jobs or max(1, (os.cpu_count() or 2))
    if target == 'linux' and IS_WIN:
        return build_via_wsl(log, jobs, config)
    missing = [n for n, p, _ in toolchain_status(target) if not p]
    if missing:
        raise BuildError('faltan herramientas: %s (usa "Descargar lo que falta").' % ', '.join(missing))
    cmake, ninja = find_cmake(), find_ninja()
    bdir = build_dir(target)
    env = dict(os.environ)
    args = ['-G', 'Ninja', '-DCMAKE_BUILD_TYPE=%s' % config, '-DCMAKE_MAKE_PROGRAM=%s' % ninja]
    src = PORT
    if target == 'windows' and IS_WIN:
        root = windows_src_root(log)
        src = os.path.join(root, 'port')
        bdir = os.path.join(src, 'build')
        gxx = find_mingw_gxx()
        gcc = os.path.join(os.path.dirname(gxx), 'gcc.exe')
        env['PATH'] = os.path.dirname(gxx) + os.pathsep + env.get('PATH', '')
        args += ['-DCMAKE_C_COMPILER=%s' % gcc, '-DCMAKE_CXX_COMPILER=%s' % gxx,
                 '-DCMAKE_ASM_COMPILER=%s' % gcc, '-DBoost_INCLUDE_DIR=%s' % find_boost()]
    elif target == 'windows':
        write_zig_wrappers(find_zig())
        cache = os.path.join(TOOLS, 'zig-cache')
        env['ZIG_GLOBAL_CACHE_DIR'] = env['ZIG_LOCAL_CACHE_DIR'] = cache
        args += ['-DCMAKE_TOOLCHAIN_FILE=%s' % os.path.join(PORT, 'cmake', 'zig-windows.cmake'),
                 '-DBoost_INCLUDE_DIR=%s' % find_boost()]
        log('compilacion cruzada con zig: la primera vez compila su libc (varios minutos).')
    else:
        sdl, uses_env = find_linux_sdl2()
        prefix = [sdl] if uses_env else []
        args += ['-DCMAKE_PREFIX_PATH=%s' % ';'.join(prefix)] if prefix else []
        args += ['-DBoost_INCLUDE_DIR=%s' % find_boost()]
    run([cmake, '-S', src, '-B', bdir] + args, log, env=env)
    run([cmake, '--build', bdir, '--parallel', str(jobs)], log, env=env, progress=progress)
    exe = os.path.join(bdir, 'sjfport.exe' if target == 'windows' else 'sjfport')
    if not os.path.isfile(exe):
        raise BuildError('la compilacion termino pero no aparece %s' % exe)
    if target == 'windows':
        dll = os.path.join(SDL2_MINGW_DIR, 'bin', 'SDL2.dll')
        if os.path.isfile(dll):
            shutil.copy2(dll, os.path.dirname(exe))
    log('OK: %s' % exe)
    return exe


def build_via_wsl(log, jobs, config):
    wsl = shutil.which('wsl')
    if not wsl:
        raise BuildError('Para compilar la version Linux desde Windows hace falta WSL (wsl --install).')
    me = subprocess.run([wsl, 'wslpath', '-a', os.path.abspath(__file__)], capture_output=True,
                        text=True).stdout.strip()
    run([wsl, 'python3', me, '--cli', '--target', 'linux', '--fetch', '--build', '--jobs', str(jobs),
         '--config', config], log)
    return exe_path('linux')


# ---------------------------------------------------------------------------
# 4. run / portable
# ---------------------------------------------------------------------------
def run_env(target):
    env = dict(os.environ)
    if target == 'linux':
        sdl, uses_env = find_linux_sdl2()
        if uses_env and not ctypes.util.find_library('SDL2-2.0'):
            env['LD_LIBRARY_PATH'] = os.path.join(ENV_LINUX, 'lib') + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    return env


def play(target, log, window=None, fullscreen=False, mute=False, debug=False, extra=(), wait=False,
         env_extra=None, zone=None, aspect=None, extra_chars=True):
    exe = exe_path(target)
    if target == 'windows' and IS_WIN and ' ' in ROOT:
        exe = os.path.join(os.environ.get('SystemDrive', 'C:') + os.sep, 'sjf', 'port', 'build', 'sjfport.exe')
    if not os.path.isfile(exe):
        raise BuildError('no hay ejecutable para %s: compila primero.' % target)
    if (target == 'windows') != IS_WIN:
        raise BuildError('el ejecutable de %s no se puede lanzar desde %s (usa "Crear version portable" '
                         'y copialo a la otra maquina).' % (target, HOST))
    cmd = [exe, os.path.join('game', 'libsonicjumpfever.so'), '--timeout', '0', '--shot-swap', '0']
    wide = aspect and aspect != '9:16'
    if window and wide:
        try:
            ww, wh = [int(v) for v in window.lower().split('x')]
        except ValueError:
            ww, wh = 0, 0
        if ww < wh:  # a portrait window would shrink the widescreen image
            log('ventana %s es vertical: con pantalla %s se ajusta sola' % (window, aspect))
            window = None
    if window:
        cmd += ['--window', window]
    if wide:
        cmd += ['--aspect', aspect]
    if extra_chars:
        build_extra_characters(log)  # no-op when already up to date
    else:
        cmd += ['--no-extra-chars']
        log('pantalla: %s' % ASPECT_LABELS.get(aspect, aspect))
    if fullscreen:
        cmd += ['--fullscreen']
    if debug:
        cmd += ['--debug', '--verbose']
    z = resolve_zone(zone)
    if z:
        cmd += ['--zone', z]
        log('zona: %s%s' % (ZONE_LABELS[z], ' (rotacion semanal)' if zone == 'weekly' else ''))
    cmd += list(extra)
    env = run_env(target)
    if mute:
        env['SDL_AUDIODRIVER'] = 'dummy'
    env.update(env_extra or {})
    logf = open(os.path.join(PORT, 'sjfport_last.log'), 'w', encoding='utf-8', errors='replace')
    log('lanzando: %s   (log: port/sjfport_last.log)' % ' '.join(cmd))
    p = subprocess.Popen(cmd, cwd=PORT, env=env, stdout=logf, stderr=subprocess.STDOUT)
    if wait:
        p.wait()
        logf.close()
    return p


# ---------------------------------------------------------------------------
# Save editor (hito 9). profile0.dat has a field-by-field CRC32, so the file is
# never written here: the edits are applied by the game itself (sjfport
# --profile-edit) through PlayerProfile setters + PlayerProfile::save().
# ---------------------------------------------------------------------------
PROFILE = os.path.join(GAME, 'data', 'profile0.dat')
CHARACTERS = ['sonic', 'tails', 'knuckles', 'amy', 'blaze', 'shadow', 'vector', 'silver', 'rouge', 'cream']
CHAR_LABELS = {'sonic': 'Sonic', 'tails': 'Tails', 'knuckles': 'Knuckles', 'amy': 'Amy', 'blaze': 'Blaze',
               'shadow': 'Shadow', 'vector': 'Vector', 'silver': 'Silver', 'rouge': 'Rouge', 'cream': 'Cream'}
# BoosterSpecification::Enum index -> save field (mapped empirically, docs/11)
BOOSTERS = [(0, 'numGoldTotem', 'Totem dorado'), (1, 'numHoopBoost', 'Aro impulsor'),
            (2, 'numPowerDoubler', 'Doble poder'), (3, 'numQuickFrenzy', 'Frenesi rapido'),
            (4, 'numRingStreak', 'Racha de anillos'), (5, 'numTimeExtend', 'Tiempo extra'),
            (6, 'numAnimalDoubler', 'Doble animales')]


def read_profile():
    """Current values from profile0.dat (read-only) or None if there is no save yet."""
    if not os.path.isfile(PROFILE):
        return None
    sys.path.insert(0, HERE)
    import sjf_save
    v = sjf_save.load(PROFILE)

    def get(key, default=0):
        for _, item in sjf_save.find_all(v, key):
            return item[1][1]
        return default
    return {
        'rings': get('numRings'), 'redrings': get('numRedRings'), 'energy': get('energyCount'),
        'chars': {c: bool(int(get(c) or 0) & 1) for c in CHARACTERS},
        'boosters': {i: get(field) for i, field, _ in BOOSTERS},
        'ftue': get('ftueState'),
    }


def profile_edit_commands(cur, new):
    cmds = []
    for k in ('rings', 'redrings', 'energy'):
        if int(new[k]) != int(cur[k]):
            cmds.append('%s %d' % (k, int(new[k])))
    for c in CHARACTERS:
        if c != 'sonic' and new['chars'][c] != cur['chars'][c]:
            cmds.append('%s %s' % ('unlock' if new['chars'][c] else 'lock', c))
    for i, _, _ in BOOSTERS:
        if int(new['boosters'][i]) != int(cur['boosters'][i]):
            cmds.append('booster %d %d' % (i, int(new['boosters'][i])))
    return cmds


def backup_saves(log):
    d = os.path.join(GAME, 'data')
    if not os.path.isdir(d):
        return None
    bdir = os.path.join(GAME, 'save_backups')
    os.makedirs(bdir, exist_ok=True)
    out = os.path.join(bdir, 'data_%s.zip' % time.strftime('%Y%m%d_%H%M%S'))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in os.listdir(d):
            z.write(os.path.join(d, f), f)
    log('copia de seguridad: %s' % out)
    return out


def apply_profile_edits(target, cmds, log, timeout=90):
    """Run the game hidden + muted; it applies cmds at the Home screen and saves."""
    if not cmds:
        log('editor: no hay cambios')
        return []
    exe = exe_path(target)
    if not os.path.isfile(exe):
        raise BuildError('compila el juego primero (el editor usa el propio juego para guardar).')
    if (target == 'windows') != IS_WIN:
        raise BuildError('elige como plataforma la de este equipo (%s) para editar la partida.' % HOST)
    backup_saves(log)
    ef = os.path.join(PORT, 'profile_edits.txt')
    with open(ef, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# generado por el launcher\n' + '\n'.join(cmds) + '\nexit\n')
    log('editor: aplicando %d cambio(s) con el juego (ventana oculta, sin sonido)...' % len(cmds))
    p = play(target, log, mute=True, wait=True,
             extra=['--hidden', '--profile-edit', 'profile_edits.txt', '--timeout', str(timeout)])
    lines = []
    with open(os.path.join(PORT, 'sjfport_last.log'), encoding='utf-8', errors='replace') as f:
        for line in f:
            if 'profile-edit:' in line:
                lines.append(line.split('profile-edit:', 1)[1].strip())
    for line in lines:
        log('  ' + line)
    if not any('save() done' in l for l in lines):
        raise BuildError('el juego no llego a la pantalla principal o no guardo (codigo %s). Si la '
                         'partida es nueva, juega el tutorial primero. Detalles: port/sjfport_last.log'
                         % p.returncode)
    log('editor: partida guardada por el juego (CRC valido).')
    return lines


def make_portable(target, log):
    exe = exe_path(target)
    if target == 'windows' and IS_WIN and ' ' in ROOT:
        exe = os.path.join(os.environ.get('SystemDrive', 'C:') + os.sep, 'sjf', 'port', 'build', 'sjfport.exe')
    if not os.path.isfile(exe):
        raise BuildError('compila primero (%s).' % target)
    out = os.path.join(ROOT, 'dist', target)
    bin_dir = os.path.join(out, 'bin')
    os.makedirs(bin_dir, exist_ok=True)
    shutil.copy2(exe, bin_dir)
    if target == 'windows':
        shutil.copy2(os.path.join(SDL2_MINGW_DIR, 'bin', 'SDL2.dll'), bin_dir)
    gdst = os.path.join(out, 'game')
    if os.path.isdir(gdst):
        shutil.rmtree(gdst)
    shutil.copytree(GAME, gdst, ignore=shutil.ignore_patterns('data', 'save_backups'))
    if os.path.isfile(os.path.join(PORT, 'controls.cfg')):
        shutil.copy2(os.path.join(PORT, 'controls.cfg'), out)
    os.makedirs(os.path.join(gdst, 'data'), exist_ok=True)
    if target == 'windows':
        with open(os.path.join(out, 'Jugar.bat'), 'w', newline='\r\n') as f:
            f.write('@echo off\r\nrem Zona: Jugar.bat --zone jungle_zone  (green_hill_zone, blue_sky_zone, jungle_zone, mechanical_zone)\r\n'
                    'rem Panoramico: Jugar.bat --aspect 16:9  (9:16, 3:4, 4:3, 16:10, 16:9, 21:9, auto)\r\n'
                    'cd /d "%~dp0"\r\n'
                    'bin\\sjfport.exe game\\libsonicjumpfever.so --timeout 0 --shot-swap 0 %*\r\n')
    else:
        # Bundle SDL2 when it came from the micromamba env; used only if the
        # system has no libSDL2 (jugar.sh checks with ldconfig).
        sdl, uses_env = find_linux_sdl2()
        if uses_env:
            libdir = os.path.join(bin_dir, 'lib')
            os.makedirs(libdir, exist_ok=True)
            src = os.path.join(ENV_LINUX, 'lib', 'libSDL2-2.0.so.0')
            if os.path.exists(src):
                shutil.copy2(os.path.realpath(src), os.path.join(libdir, 'libSDL2-2.0.so.0'))
        p = os.path.join(out, 'jugar.sh')
        with open(p, 'w', newline='\n') as f:
            f.write('#!/bin/sh\n# Zona: ./jugar.sh --zone jungle_zone  (green_hill_zone, blue_sky_zone, jungle_zone, mechanical_zone)\n'
                    '# Panoramico: ./jugar.sh --aspect 16:9  (9:16, 3:4, 4:3, 16:10, 16:9, 21:9, auto)\n'
                    'cd "$(dirname "$0")"\n'
                    'if [ -d bin/lib ] && ! ldconfig -p 2>/dev/null | grep -q libSDL2-2.0.so.0; then\n'
                    '  export LD_LIBRARY_PATH="$PWD/bin/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                    'fi\n'
                    'exec ./bin/sjfport game/libsonicjumpfever.so --timeout 0 --shot-swap 0 "$@"\n')
        os.chmod(p, 0o755)
    log('version portable en %s  (contiene datos de TU APK: no la distribuyas)' % out)
    return out


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
def gui():
    """Game-styled launcher (hito 9). --classic opens the previous plain one."""
    if '--classic' not in sys.argv:
        sys.path.insert(0, HERE)
        import sjf_gui
        return sjf_gui.main()
    return gui_classic()


def gui_classic():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    st = load_settings()
    root = tk.Tk()
    root.title('Jump Fever Recomp - Launcher')
    root.geometry('800x860')
    root.minsize(640, 600)
    q = queue.Queue()
    busy = {'v': False}
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('Head.TLabel', font=('TkDefaultFont', 14, 'bold'))
    style.configure('Ok.TLabel', foreground='#1a7f37')
    style.configure('Bad.TLabel', foreground='#cf222e')
    style.configure('Big.TButton', font=('TkDefaultFont', 11, 'bold'), padding=6)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill='both', expand=True)
    ttk.Label(frm, text='Jump Fever Recomp', style='Head.TLabel').pack(anchor='w')
    ttk.Label(frm, text='Port personal de Sonic Jump Fever (Android ARM64) a PC.  Host: %s' % HOST).pack(anchor='w')

    # -- 1 APK
    box1 = ttk.LabelFrame(frm, text=' 1. Tu APK ', padding=8)
    box1.pack(fill='x', pady=(10, 4))
    apk_var = tk.StringVar(value=st.get('apk', ''))
    row = ttk.Frame(box1)
    row.pack(fill='x')
    ttk.Entry(row, textvariable=apk_var).pack(side='left', fill='x', expand=True)
    apk_status = ttk.Label(box1, text='')
    music_var = tk.BooleanVar(value=st.get('music', True))

    def refresh_apk(*_):
        info = inspect_apk(apk_var.get().strip())
        txt = info['msg'] if apk_var.get().strip() else 'Elige el APK de Sonic Jump Fever 1.6.1 (arm64).'
        style_name = 'Ok.TLabel' if info['ok'] and info.get('version') else ('TLabel' if not apk_var.get() else 'Bad.TLabel')
        apk_status.configure(text=txt, style=style_name)
        if game_installed():
            apk_status.configure(text=txt + '   [datos instalados en port/game]')

    def browse():
        p = filedialog.askopenfilename(title='Selecciona tu APK de Sonic Jump Fever',
                                       filetypes=[('APK de Android', '*.apk'), ('Todos', '*.*')])
        if p:
            apk_var.set(p)
            refresh_apk()

    ttk.Button(row, text='Examinar...', command=browse).pack(side='left', padx=(6, 0))
    apk_status.pack(anchor='w', pady=(4, 2))
    row = ttk.Frame(box1)
    row.pack(fill='x')
    ttk.Checkbutton(row, text='Convertir musica (.m4a -> .ogg, necesita ffmpeg)', variable=music_var).pack(side='left')
    btn_install = ttk.Button(row, text='Instalar datos del juego')
    btn_install.pack(side='right')

    # -- 2 platform
    box2 = ttk.LabelFrame(frm, text=' 2. Plataforma ', padding=8)
    box2.pack(fill='x', pady=4)
    tgt_var = tk.StringVar(value=st.get('target', HOST if HOST in TARGETS else 'linux'))
    row = ttk.Frame(box2)
    row.pack(fill='x')
    ttk.Radiobutton(row, text='Windows (.exe)', value='windows', variable=tgt_var).pack(side='left')
    ttk.Radiobutton(row, text='Linux', value='linux', variable=tgt_var).pack(side='left', padx=12)
    mode_lbl = ttk.Label(row, text='')
    mode_lbl.pack(side='left', padx=8)
    tc_frame = ttk.Frame(box2)
    tc_frame.pack(fill='x', pady=(6, 0))
    btn_fetch = ttk.Button(box2, text='Descargar lo que falta')
    btn_fetch.pack(anchor='e', pady=(4, 0))

    def refresh_tc(*_):
        t = tgt_var.get()
        if t == HOST:
            mode = 'compilacion nativa'
        elif t == 'windows':
            mode = 'compilacion cruzada (zig)'
        else:
            mode = 'via WSL (experimental)'
        mode_lbl.configure(text='-> ' + mode)
        for w in tc_frame.winfo_children():
            w.destroy()
        for i, (name, path, hint) in enumerate(toolchain_status(t)):
            ok = bool(path)
            ttk.Label(tc_frame, text=('OK  ' if ok else 'FALTA'), style='Ok.TLabel' if ok else 'Bad.TLabel',
                      width=6).grid(row=i, column=0, sticky='w')
            ttk.Label(tc_frame, text=name, width=24).grid(row=i, column=1, sticky='w')
            ttk.Label(tc_frame, text=(path if ok else hint), foreground='#555').grid(row=i, column=2, sticky='w')

    tgt_var.trace_add('write', refresh_tc)

    # -- 3 build
    box3 = ttk.LabelFrame(frm, text=' 3. Compilar ', padding=8)
    box3.pack(fill='x', pady=4)
    row = ttk.Frame(box3)
    row.pack(fill='x')
    ttk.Label(row, text='Configuracion').pack(side='left')
    cfg_var = tk.StringVar(value=st.get('config', 'Release'))
    ttk.Combobox(row, textvariable=cfg_var, values=['Release', 'RelWithDebInfo', 'Debug'], width=14,
                 state='readonly').pack(side='left', padx=6)
    ttk.Label(row, text='Hilos').pack(side='left', padx=(12, 0))
    jobs_var = tk.IntVar(value=st.get('jobs', os.cpu_count() or 4))
    ttk.Spinbox(row, from_=1, to=64, textvariable=jobs_var, width=5).pack(side='left', padx=6)
    btn_build = ttk.Button(row, text='Compilar', style='Big.TButton')
    btn_build.pack(side='right')
    prog = ttk.Progressbar(box3, mode='determinate', maximum=100)
    prog.pack(fill='x', pady=(6, 0))

    # -- 4 play
    box4 = ttk.LabelFrame(frm, text=' 4. Jugar ', padding=8)
    box4.pack(fill='x', pady=4)
    row = ttk.Frame(box4)
    row.pack(fill='x')
    ttk.Label(row, text='Ventana').pack(side='left')
    win_var = tk.StringVar(value=st.get('window', '540x960'))
    ttk.Combobox(row, textvariable=win_var, values=['540x960', '720x1280', '450x800', '1280x720', '1920x1080'],
                 width=11).pack(side='left', padx=6)
    fs_var = tk.BooleanVar(value=st.get('fullscreen', False))
    mute_var = tk.BooleanVar(value=False)
    dbg_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(row, text='Pantalla completa', variable=fs_var).pack(side='left', padx=6)
    ttk.Checkbutton(row, text='Sin sonido', variable=mute_var).pack(side='left', padx=6)
    ttk.Checkbutton(row, text='Depuracion', variable=dbg_var).pack(side='left', padx=6)
    row = ttk.Frame(box4)
    row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='Zona').pack(side='left')
    zone_var = tk.StringVar(value=ZONE_LABELS.get(st.get('zone', 'weekly'), ZONE_LABELS['weekly']))
    ttk.Combobox(row, textvariable=zone_var, values=[ZONE_LABELS[z] for z in ZONE_CHOICES],
                 width=34, state='readonly').pack(side='left', padx=6)
    zone_info = ttk.Label(row, text='', foreground='#555')
    zone_info.pack(side='left', padx=6)

    def zone_key():
        lbl = zone_var.get()
        for k, v in ZONE_LABELS.items():
            if v == lbl:
                return k
        return 'weekly'

    def refresh_zone(*_):
        cur, nxt = weekly_zone()
        if zone_key() == 'weekly':
            zone_info.configure(text='esta semana: %s  |  proxima: %s' % (dict(ZONES)[cur], dict(ZONES)[nxt]))
        else:
            zone_info.configure(text='')

    zone_var.trace_add('write', refresh_zone)
    refresh_zone()
    row = ttk.Frame(box4)
    row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='Pantalla').pack(side='left')
    aspect_var = tk.StringVar(value=ASPECT_LABELS.get(st.get('aspect', '9:16'), ASPECT_LABELS['9:16']))
    ttk.Combobox(row, textvariable=aspect_var, values=[l for _, l in ASPECTS],
                 width=34, state='readonly').pack(side='left', padx=6)
    ttk.Label(row, text='panoramica = mas escenario, sin bandas',
              foreground='#555').pack(side='left', padx=6)

    def aspect_key():
        lbl = aspect_var.get()
        for k, v in ASPECTS:
            if v == lbl:
                return k
        return '9:16'
    row = ttk.Frame(box4)
    row.pack(fill='x', pady=(6, 0))
    ttk.Label(row, text='Raton = toque | Flechas/A-D = inclinar | Esc = atras | F11 = pantalla completa\n'
                        'Mando: stick izq./cruceta = inclinar, stick der. = cursor, A = tocar, B/Start = atras',
              foreground='#555', justify='left').pack(side='left')
    row = ttk.Frame(box4)
    row.pack(fill='x', pady=(6, 0))
    btn_portable = ttk.Button(row, text='Crear version portable')
    btn_portable.pack(side='left')
    btn_play = ttk.Button(row, text='JUGAR', style='Big.TButton')
    btn_play.pack(side='right')

    # -- log
    logbox = tk.Text(frm, height=10, wrap='none', font=('TkFixedFont', 9), background='#0d1117',
                     foreground='#c9d1d9', insertbackground='white')
    logbox.pack(fill='both', expand=True, pady=(8, 0))

    def sink(s):
        q.put(('log', s))

    log = Log(sink)

    def pump():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == 'log':
                    logbox.insert('end', val + '\n')
                    if int(logbox.index('end-1c').split('.')[0]) > 4000:
                        logbox.delete('1.0', '1000.0')
                    logbox.see('end')
                elif kind == 'prog':
                    prog['value'] = val
                elif kind == 'done':
                    busy['v'] = False
                    for b in buttons:
                        b.state(['!disabled'])
                    refresh_tc()
                    refresh_apk()
                    if val:
                        messagebox.showerror('Jump Fever Recomp', val)
        except queue.Empty:
            pass
        root.after(80, pump)

    buttons = [btn_install, btn_fetch, btn_build, btn_play, btn_portable]

    def task(fn):
        def go():
            if busy['v']:
                return
            busy['v'] = True
            for b in buttons:
                b.state(['disabled'])
            persist()

            def worker():
                err = None
                try:
                    fn()
                except Exception as e:  # noqa
                    err = str(e)
                    log('ERROR: %s' % err)
                q.put(('done', err))
            threading.Thread(target=worker, daemon=True).start()
        return go

    def persist():
        save_settings({'apk': apk_var.get().strip(), 'target': tgt_var.get(), 'config': cfg_var.get(),
                       'jobs': int(jobs_var.get() or 1), 'window': win_var.get(), 'fullscreen': fs_var.get(),
                       'music': music_var.get(), 'zone': zone_key(),
                       'aspect': aspect_key()})

    def on_progress(i, n):
        q.put(('prog', i * 100.0 / max(n, 1)))

    btn_install.configure(command=task(lambda: install_apk(apk_var.get().strip(), log, music_var.get())))
    btn_fetch.configure(command=task(lambda: fetch_missing(tgt_var.get(), log)))
    btn_build.configure(command=task(lambda: build(tgt_var.get(), log, int(jobs_var.get() or 1),
                                                   cfg_var.get(), on_progress)))
    btn_play.configure(command=task(lambda: play(tgt_var.get(), log, win_var.get() or None, fs_var.get(),
                                                 mute_var.get(), dbg_var.get(), zone=zone_key(),
                                                 aspect=aspect_key())))
    btn_portable.configure(command=task(lambda: make_portable(tgt_var.get(), log)))
    root.protocol('WM_DELETE_WINDOW', lambda: (persist(), root.destroy()))

    refresh_apk()
    refresh_tc()
    log('Listo. Raiz del proyecto: %s' % ROOT)
    root.after(80, pump)
    if os.environ.get('SJF_LAUNCHER_SCREENSHOT_EXIT'):
        root.after(int(os.environ['SJF_LAUNCHER_SCREENSHOT_EXIT']), root.destroy)
    root.mainloop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cli(a):
    log = Log()
    target = a.target or (HOST if HOST in TARGETS else 'linux')
    try:
        if a.apk:
            install_apk(a.apk, log, convert_music=not a.no_music)
        if a.status or not (a.apk or a.fetch or a.build or a.run or a.portable):
            log('host=%s target=%s  datos del juego: %s' % (HOST, target, 'OK' if game_installed() else 'NO'))
            for n, p, h in toolchain_status(target):
                log('  %-6s %-26s %s' % ('OK' if p else 'FALTA', n, p or h))
        if a.fetch:
            fetch_missing(target, log)
        if a.build:
            build(target, log, a.jobs, a.config)
        if a.portable:
            make_portable(target, log)
        if a.run:
            p = play(target, log, a.window, a.fullscreen, a.mute, a.debug, extra=a.extra or (), wait=True,
                     zone=a.zone, aspect=a.aspect, extra_chars=not a.no_extra_chars)
            return p.returncode
    except BuildError as e:
        log('ERROR: %s' % e)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description='Jump Fever Recomp launcher/builder')
    ap.add_argument('--cli', action='store_true', help='modo texto (sin ventana)')
    ap.add_argument('--classic', action='store_true', help='launcher clasico (sin tema)')
    ap.add_argument('--apk', help='ruta a tu APK: valida e instala los datos del juego')
    ap.add_argument('--no-music', action='store_true', help='no convertir la musica a .ogg')
    ap.add_argument('--target', choices=TARGETS, help='plataforma de destino (por defecto: la del host)')
    ap.add_argument('--status', action='store_true', help='muestra herramientas detectadas')
    ap.add_argument('--fetch', action='store_true', help='descarga las herramientas que falten')
    ap.add_argument('--build', action='store_true', help='compila')
    ap.add_argument('--jobs', type=int, default=None)
    ap.add_argument('--config', default='Release', choices=['Release', 'RelWithDebInfo', 'Debug'])
    ap.add_argument('--portable', action='store_true', help='crea dist/<target>/')
    ap.add_argument('--run', action='store_true', help='lanza el juego')
    ap.add_argument('--window', help='tamano de ventana, p.ej. 720x1280')
    ap.add_argument('--fullscreen', action='store_true')
    ap.add_argument('--mute', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--zone', choices=ZONE_CHOICES, default=None,
                    help='zona: weekly (rotacion semanal), game, o una zona concreta')
    ap.add_argument('--aspect', choices=ASPECT_CHOICES, default=None,
                    help='pantalla: 9:16 (original), 3:4, 4:3, 16:10, 16:9, 21:9 o auto (monitor)')
    ap.add_argument('--no-extra-chars', action='store_true',
                    help='oculta a Cream, Rouge y Vector (personajes ineditos)')
    ap.add_argument('extra', nargs='*', help='argumentos extra para sjfport (tras --)')
    a = ap.parse_args()
    if a.cli or any([a.apk, a.fetch, a.build, a.run, a.status, a.portable]):
        sys.exit(cli(a))
    try:
        gui()
    except ImportError:
        print('tkinter no disponible: usa --cli (o instala python3-tk).')
        sys.exit(cli(a))


if __name__ == '__main__':
    main()
