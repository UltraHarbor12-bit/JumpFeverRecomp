"""Background music for the launcher (no Python dependencies).

Windows: winmm MCI through ctypes (plays .mp3 natively, loops by polling).
Linux:   first available of ffplay / mpv / mpg123 as a child process.
If nothing can play, MusicPlayer.available is False and the GUI hides the toggle.
"""
import os
import shutil
import subprocess
import sys

IS_WIN = sys.platform == 'win32'


class MusicPlayer:
    def __init__(self, path, volume=0.5):
        self.path = path
        self.volume = max(0.0, min(1.0, volume))
        self.playing = False
        self._proc = None
        self._mci_open = False
        self._backend = None
        if not os.path.isfile(path):
            return
        if IS_WIN:
            try:
                import ctypes
                self._mci = ctypes.windll.winmm.mciSendStringW
                self._buf = ctypes.create_unicode_buffer(128)
                self._backend = 'mci'
            except Exception:
                self._backend = None
        else:
            for exe, args in (('ffplay', ['-nodisp', '-loglevel', 'quiet', '-loop', '0']),
                              ('mpv', ['--no-video', '--really-quiet', '--loop-file=inf']),
                              ('mpg123', ['-q', '--loop', '-1'])):
                p = shutil.which(exe)
                if p:
                    self._backend = (p, args, exe)
                    break

    @property
    def available(self):
        return self._backend is not None

    @property
    def backend_name(self):
        if self._backend == 'mci':
            return 'Windows MCI'
        return self._backend[2] if self._backend else 'ninguno'

    # -- MCI helpers ------------------------------------------------------
    def _cmd(self, s):
        self._buf.value = ''
        err = self._mci(s, self._buf, 128, 0)
        return err, self._buf.value

    def play(self):
        if not self.available or self.playing:
            return
        if self._backend == 'mci':
            if not self._mci_open:
                err, _ = self._cmd('open "%s" type mpegvideo alias sjfmusic' % self.path)
                if err:
                    self._backend = None
                    return
                self._mci_open = True
            self._cmd('setaudio sjfmusic volume to %d' % int(self.volume * 1000))
            self._cmd('play sjfmusic from 0')
        else:
            exe, args, name = self._backend
            vol = []
            if name == 'ffplay':
                vol = ['-volume', str(int(self.volume * 100))]
            elif name == 'mpv':
                vol = ['--volume=%d' % int(self.volume * 100)]
            elif name == 'mpg123':
                vol = ['-f', str(int(self.volume * 32768))]
            try:
                self._proc = subprocess.Popen([exe] + args + vol + [self.path], stdin=subprocess.DEVNULL,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self._backend = None
                return
        self.playing = True

    def stop(self):
        if not self.playing:
            return
        if self._backend == 'mci':
            self._cmd('stop sjfmusic')
        elif self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None
        self.playing = False

    def tick(self):
        """Call every ~1 s from the GUI: restarts the track when MCI reaches the end."""
        if self.playing and self._backend == 'mci':
            _, mode = self._cmd('status sjfmusic mode')
            if mode == 'stopped':
                self._cmd('play sjfmusic from 0')
        elif self.playing and self._proc and self._proc.poll() is not None:
            self.playing = False
            self.play()

    def close(self):
        self.stop()
        if self._backend == 'mci' and self._mci_open:
            self._cmd('close sjfmusic')
            self._mci_open = False
