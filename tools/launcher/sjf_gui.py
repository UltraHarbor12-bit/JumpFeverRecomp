"""Launcher GUI styled after Sonic Jump Fever's menus (hito 9).

Pure tkinter (no Pillow): sky background PNG, glossy blue menu buttons with a
white rim, a green status banner with yellow text, a purple-headed teal panel
(like the game's "Daily Reward!" pop-up) and a round green "Start!"-style
JUGAR button. Pages: Jugar, Instalar, Compilar, Controles, Partida, Registro.
"""
import os
import queue
import threading
import time

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

import sjf_launcher as L
import sjf_controls
import sjf_music

ASSETS = os.path.join(L.HERE, 'assets')
W, H = 980, 720
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 214, 132, 744, 470
TEAL, TEAL_DARK = '#1f9e8f', '#13786c'
PURPLE, PURPLE_DARK = '#9c27d0', '#6a1596'
YELLOW = '#ffe14d'
NAVY = '#0b2f6b'

COLORS = {  # base, light, dark, text
    'blue': ('#1e78e6', '#5fb2ff', '#0a3f9c', 'white'),
    'green': ('#27c227', '#8cf06a', '#0d7a12', YELLOW),
    'orange': ('#ff8a1e', '#ffc06a', '#b0480a', 'white'),
    'purple': ('#9c27d0', '#cf7af2', '#5a0f86', 'white'),
    'grey': ('#8a96a8', '#c3cbd6', '#5b6574', '#e8edf3'),
}


def pick_font(size, weight='bold', slant='roman'):
    fams = set(tkfont.families())
    for f in ('Arial Rounded MT Bold', 'Segoe UI Black', 'Arial Black', 'Verdana', 'DejaVu Sans', 'Helvetica'):
        if f in fams:
            return (f, size, weight) if slant == 'roman' else (f, size, weight, 'italic')
    return ('TkDefaultFont', size, weight)


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


def outlined_text(cv, x, y, text, font, fill, outline=NAVY, width=2, anchor='center', tags=()):
    ids = []
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                ids.append(cv.create_text(x + dx, y + dy, text=text, font=font, fill=outline,
                                          anchor=anchor, tags=tags))
    ids.append(cv.create_text(x, y, text=text, font=font, fill=fill, anchor=anchor, tags=tags))
    return ids


def draw_glossy(cv, x, y, w, h, r, color, text, font, hover=False, down=False, active=False,
                enabled=True, tag='btn'):
    base, light, dark, fg = COLORS['grey' if not enabled else color]
    off = 2 if down else 0
    round_rect(cv, x + 1, y + 3, x + w - 1, y + h - 1, r, fill='#06264f', outline='', tags=tag)
    round_rect(cv, x + 1, y + 1 + off, x + w - 1, y + h - 3 + off, r, fill='white', outline='', tags=tag)
    round_rect(cv, x + 4, y + 4 + off, x + w - 4, y + h - 6 + off, r - 3, fill=dark, outline='', tags=tag)
    round_rect(cv, x + 4, y + 4 + off, x + w - 4, y + h - 8 + off, r - 3,
               fill=light if hover and enabled else base, outline='', tags=tag)
    round_rect(cv, x + 7, y + 6 + off, x + w - 7, y + 6 + off + (h - 12) * 0.45, r - 5, fill=light,
               outline='', tags=tag)
    if active:
        round_rect(cv, x + 4, y + 4 + off, x + w - 4, y + h - 6 + off, r - 3, outline=YELLOW, width=3,
                   fill='', tags=tag)
    outlined_text(cv, x + w / 2, y + h / 2 - 1 + off, text, font, YELLOW if active else fg, outline=dark,
                  width=1, tags=(tag,))


def draw_start(cv, x, y, s, text, hover=False, down=False, enabled=True, tag='start'):
    o = 3 if down else 0
    c = (lambda v: v) if enabled else (lambda v: '#8a96a8')
    cv.create_oval(x + 6, y + 10, x + s - 4, y + s - 2, fill='#06264f', outline='', tags=tag)
    cv.create_oval(x + 4, y + 4 + o, x + s - 6, y + s - 6 + o, fill='#d9e4ee', outline='#7d8a99', width=2,
                   tags=tag)
    cv.create_oval(x + 13, y + 13 + o, x + s - 15, y + s - 15 + o, fill=c('#0d7a12'), outline='', tags=tag)
    cv.create_oval(x + 15, y + 15 + o, x + s - 17, y + s - 19 + o, fill=c('#5df24a' if hover else '#20c420'),
                   outline='', tags=tag)
    cv.create_oval(x + 28, y + 20 + o, x + s - 30, y + s * 0.5 + o, fill=c('#9cff7a'), outline='', tags=tag)
    outlined_text(cv, x + s / 2 - 3, y + s / 2 + 2 + o, text, pick_font(int(s * 0.12), slant='italic'),
                  YELLOW if enabled else '#e8edf3', outline='#0a4f10', width=2, tags=(tag,))


class CanvasButtons:
    """Buttons drawn straight on the background canvas (no square widget behind them).
    Hover/click are resolved from the pointer position."""

    def __init__(self, cv):
        self.cv = cv
        self.items = []
        cv.bind('<Motion>', self._motion, add='+')
        cv.bind('<Leave>', lambda e: self._motion(None), add='+')
        cv.bind('<ButtonPress-1>', self._press, add='+')
        cv.bind('<ButtonRelease-1>', self._release, add='+')

    def add(self, kind, x, y, w, h, text, command, color='blue', font=None, radius=12):
        b = {'kind': kind, 'x': x, 'y': y, 'w': w, 'h': h, 'text': text, 'command': command, 'color': color,
             'font': font, 'radius': radius, 'hover': False, 'down': False, 'active': False, 'enabled': True,
             'tag': 'cb%d' % len(self.items)}
        self.items.append(b)
        self.draw(b)
        return b

    def update(self, b, **kw):
        b.update(kw)
        self.draw(b)

    def draw(self, b):
        self.cv.delete(b['tag'])
        if b['kind'] == 'start':
            draw_start(self.cv, b['x'], b['y'], b['w'], b['text'], b['hover'], b['down'], b['enabled'], b['tag'])
        else:
            draw_glossy(self.cv, b['x'], b['y'], b['w'], b['h'], b['radius'], b['color'], b['text'], b['font'],
                        b['hover'], b['down'], b['active'], b['enabled'], b['tag'])

    def _hit(self, e):
        if e is None:
            return None
        for b in self.items:
            if b['x'] <= e.x <= b['x'] + b['w'] and b['y'] <= e.y <= b['y'] + b['h']:
                return b
        return None

    def _motion(self, e):
        hit = self._hit(e)
        for b in self.items:
            hv = b is hit and b['enabled']
            if hv != b['hover']:
                b['hover'] = hv
                if not hv:
                    b['down'] = False
                self.draw(b)
        self.cv.configure(cursor='hand2' if hit and hit['enabled'] else '')

    def _press(self, e):
        b = self._hit(e)
        if b and b['enabled']:
            self.update(b, down=True)

    def _release(self, e):
        b = self._hit(e)
        for it in self.items:
            if it['down']:
                self.update(it, down=False)
                if it is b and it['enabled'] and it['command']:
                    it['command']()


class GameButton(tk.Canvas):
    """Glossy rounded button with a white rim (the game's Shop/Spin style)."""

    def __init__(self, parent, text, command=None, color='blue', width=150, height=40, bg=TEAL,
                 font=None, radius=12):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0,
                         cursor='hand2')
        self.text, self.command, self.color = text, command, color
        self.w, self.h, self.radius = width, height, radius
        self.font = font or pick_font(11)
        self.enabled, self.hover, self.down, self.active = True, False, False, False
        self.bind('<Enter>', lambda e: self._set(hover=True))
        self.bind('<Leave>', lambda e: self._set(hover=False, down=False))
        self.bind('<ButtonPress-1>', lambda e: self._set(down=True))
        self.bind('<ButtonRelease-1>', self._release)
        self._draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self._draw()

    def _release(self, e):
        fire = self.down and self.hover and self.enabled
        self._set(down=False)
        if fire and self.command:
            self.command()

    def configure_button(self, text=None, color=None, active=None, command=None):
        if text is not None: self.text = text
        if color is not None: self.color = color
        if active is not None: self.active = active
        if command is not None: self.command = command
        self._draw()

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor='hand2' if on else 'arrow')
        self._draw()

    def _draw(self):
        self.delete('all')
        draw_glossy(self, 0, 0, self.w, self.h, self.radius, self.color, self.text, self.font, self.hover,
                    self.down, self.active, self.enabled)


class App:
    PAGES = [('jugar', 'JUGAR'), ('instalar', 'INSTALAR'), ('compilar', 'COMPILAR'),
             ('controles', 'CONTROLES'), ('partida', 'PARTIDA'), ('registro', 'REGISTRO')]

    def __init__(self):
        self.st = L.load_settings()
        self.root = tk.Tk()
        self.root.title('Jump Fever Recomp')
        self.root.geometry('%dx%d' % (W, H))
        self.root.resizable(False, False)
        self.q = queue.Queue()
        self.busy = False
        self.game_proc = None
        self.resume_music = False
        self.F = {'title': pick_font(22, slant='italic'), 'banner': pick_font(13), 'menu': pick_font(12),
                  'head': pick_font(15), 'label': pick_font(10), 'small': pick_font(9, 'normal'),
                  'btn': pick_font(10)}
        self._style()
        self.cv = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bd=0)
        self.cv.place(x=0, y=0)
        try:
            self.bg = tk.PhotoImage(file=os.path.join(ASSETS, 'bg.png'))
            self.cv.create_image(0, 0, image=self.bg, anchor='nw')
        except tk.TclError:
            self.cv.configure(bg='#3aa0f0')
        self.log = L.Log(lambda s: self.q.put(('log', s)))
        self.music = sjf_music.MusicPlayer(os.path.join(ASSETS, 'menu_music.mp3'),
                                           volume=float(self.st.get('music_volume', 0.45)))
        self._chrome()
        self.pages = {}
        self.page_title = None
        for key, _ in self.PAGES:
            f = tk.Frame(self.root, bg=TEAL, width=PANEL_W - 24, height=PANEL_H - 70)
            f.pack_propagate(False)
            f.grid_propagate(False)
            self.pages[key] = f
        self._page_jugar()
        self._page_instalar()
        self._page_compilar()
        self._page_controles()
        self._page_partida()
        self._page_registro()
        self.cur_page = None
        self.show(os.environ.get('SJF_LAUNCHER_PAGE') or self.st.get('page', 'jugar'))
        self.refresh_all()
        self.log('Listo. Raiz del proyecto: %s' % L.ROOT)
        if self.music.available and self.st.get('menu_music', True):
            self.music.play()
        self._music_btn_update()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(80, self.pump)
        self.root.after(1000, self.tick)

    # ------------------------------------------------------------------ style
    def _style(self):
        s = ttk.Style()
        if 'clam' in s.theme_names():
            s.theme_use('clam')
        s.configure('Game.TCombobox', fieldbackground='white', background='#5fb2ff', foreground=NAVY,
                    arrowcolor=NAVY, bordercolor='white', padding=3)
        s.map('Game.TCombobox', fieldbackground=[('readonly', 'white')], foreground=[('readonly', NAVY)])
        s.configure('Game.Horizontal.TProgressbar', troughcolor=TEAL_DARK, background=YELLOW,
                    bordercolor='white', lightcolor=YELLOW, darkcolor='#e0b800', thickness=16)
        s.configure('Game.TSpinbox', fieldbackground='white', foreground=NAVY, arrowcolor=NAVY,
                    background='#5fb2ff', padding=2)

    def lbl(self, parent, text, font='label', fg='white', **kw):
        return tk.Label(parent, text=text, bg=parent['bg'], fg=fg, font=self.F[font], **kw)

    def check(self, parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=parent['bg'], fg='white',
                              activebackground=parent['bg'], activeforeground=YELLOW,
                              selectcolor=TEAL_DARK, font=self.F['label'], bd=0, highlightthickness=0)

    def combo(self, parent, var, values, width=30):
        return ttk.Combobox(parent, textvariable=var, values=values, width=width, state='readonly',
                            style='Game.TCombobox', font=self.F['small'])

    def btn(self, parent, text, cmd, color='blue', width=170, height=38):
        return GameButton(parent, text, cmd, color=color, width=width, height=height, bg=parent['bg'],
                          font=self.F['btn'])

    # ----------------------------------------------------------------- chrome
    def _chrome(self):
        cv = self.cv
        # top-left HUD pill with the title
        round_rect(cv, 14, 12, 470, 66, 18, fill='white', outline='')
        round_rect(cv, 18, 16, 466, 62, 15, fill='#1565d8', outline='')
        round_rect(cv, 22, 19, 462, 38, 10, fill='#4f9bff', outline='')
        outlined_text(cv, 40, 39, 'JUMP FEVER RECOMP', self.F['title'], YELLOW, anchor='w', width=2)
        # top-right HUD pill: music toggle
        self.cbs = CanvasButtons(cv)
        self.music_btn = self.cbs.add('glossy', W - 196, 16, 176, 46, 'MUSICA: SI', self.toggle_music,
                                      font=self.F['btn'])
        self.host_text = cv.create_text(W - 210, 40, text='Host: %s' % L.HOST, anchor='e',
                                        fill='white', font=self.F['label'])
        # green banner (game's "TRYING TO CONNECT TO SERVER..." strip)
        cv.create_rectangle(0, 76, W, 116, fill='#2f7d0e', outline='')
        cv.create_rectangle(0, 76, W, 94, fill='#4aa61c', outline='')
        cv.create_line(0, 116, W, 116, fill='#1d4f06', width=2)
        self.banner = outlined_text(cv, 22, 96, '', self.F['banner'], YELLOW, outline='#1d4f06', width=1,
                                    anchor='w', tags=('banner',))
        # left menu
        self.menu_btns = {}
        for i, (key, label) in enumerate(self.PAGES):
            self.menu_btns[key] = self.cbs.add('glossy', 18, 136 + i * 64, 180, 52, label,
                                               lambda k=key: self.show(k), font=self.F['menu'], radius=14)
        # content panel: purple header + teal body with white rim
        x0, y0, x1, y1 = PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H
        round_rect(cv, x0 + 3, y0 + 6, x1 + 3, y1 + 6, 22, fill='#0b3a78', outline='')
        round_rect(cv, x0, y0, x1, y1, 22, fill='white', outline='')
        round_rect(cv, x0 + 5, y0 + 5, x1 - 5, y1 - 5, 18, fill=TEAL, outline='')
        round_rect(cv, x0 + 5, y0 + 5, x1 - 5, y0 + 54, 18, fill=PURPLE, outline='')
        cv.create_rectangle(x0 + 5, y0 + 34, x1 - 5, y0 + 54, fill=PURPLE, outline='')
        cv.create_line(x0 + 5, y0 + 54, x1 - 5, y0 + 54, fill=PURPLE_DARK, width=3)
        self.page_title_pos = ((x0 + x1) / 2, y0 + 30)
        self.panel_win = cv.create_window(x0 + 12, y0 + 62, anchor='nw')
        # big round JUGAR button (bottom right), status line bottom-left
        self.start = self.cbs.add('start', W - 142, H - 126, 122, 122, 'JUGAR!', self.do_play)
        self.status_txt = cv.create_text(PANEL_X + 6, H - 70, text='', anchor='nw', fill=NAVY,
                                         font=self.F['label'], width=600)

    def set_banner(self, text):
        self.cv.itemconfigure('banner', text=text.upper())

    def show(self, key):
        if key not in self.pages:
            key = 'jugar'
        self.cur_page = key
        self.cv.itemconfigure(self.panel_win, window=self.pages[key])
        for k, b in self.menu_btns.items():
            self.cbs.update(b, active=(k == key), color='green' if k == key else 'blue')
        self.cv.delete('ptitle')
        title = dict(self.PAGES)[key].capitalize() + '!'
        outlined_text(self.cv, self.page_title_pos[0], self.page_title_pos[1], title, self.F['head'], YELLOW,
                      outline=PURPLE_DARK, width=2, tags=('ptitle',))
        if key == 'partida':
            self.refresh_profile()
        if key == 'controles':
            self.refresh_controls()

    # ------------------------------------------------------------------ pages
    def _row(self, page, pady=(0, 8)):
        r = tk.Frame(page, bg=TEAL)
        r.pack(fill='x', padx=14, pady=pady)
        return r

    def _page_jugar(self):
        p = self.pages['jugar']
        st = self.st
        tk.Frame(p, bg=TEAL, height=6).pack()
        r = self._row(p)
        self.lbl(r, 'Zona', width=10, anchor='w').pack(side='left')
        self.zone_var = tk.StringVar(value=L.ZONE_LABELS.get(st.get('zone', 'weekly'), L.ZONE_LABELS['weekly']))
        self.combo(r, self.zone_var, [L.ZONE_LABELS[z] for z in L.ZONE_CHOICES], 36).pack(side='left')
        r = self._row(p, (0, 10))
        self.lbl(r, '', width=10).pack(side='left')
        self.zone_info = self.lbl(r, '', 'small', fg='#d8fff8')
        self.zone_info.pack(side='left')
        self.zone_var.trace_add('write', lambda *a: self.refresh_zone())
        r = self._row(p)
        self.lbl(r, 'Pantalla', width=10, anchor='w').pack(side='left')
        self.aspect_var = tk.StringVar(value=L.ASPECT_LABELS.get(st.get('aspect', '9:16'), L.ASPECT_LABELS['9:16']))
        self.combo(r, self.aspect_var, [l for _, l in L.ASPECTS], 36).pack(side='left')
        r = self._row(p, (0, 10))
        self.lbl(r, '', width=10).pack(side='left')
        self.lbl(r, 'Panoramica: la interfaz se adapta y ves mas escenario a los lados.', 'small',
                 fg='#d8fff8').pack(side='left')
        r = self._row(p)
        self.lbl(r, 'Ventana', width=10, anchor='w').pack(side='left')
        self.win_var = tk.StringVar(value=st.get('window', '540x960'))
        ttk.Combobox(r, textvariable=self.win_var, values=['540x960', '720x1280', '450x800', '1280x720',
                                                           '1600x900', '1920x1080'], width=12,
                     style='Game.TCombobox', font=self.F['small']).pack(side='left')
        r = self._row(p, (4, 8))
        self.fs_var = tk.BooleanVar(value=st.get('fullscreen', False))
        self.mute_var = tk.BooleanVar(value=False)
        self.dbg_var = tk.BooleanVar(value=False)
        self.check(r, 'Pantalla completa', self.fs_var).pack(side='left', padx=(0, 14))
        self.check(r, 'Sin sonido', self.mute_var).pack(side='left', padx=(0, 14))
        self.check(r, 'Depuracion', self.dbg_var).pack(side='left')
        r = self._row(p, (2, 4))
        self.xchars_var = tk.BooleanVar(value=st.get('extra_chars', True))
        self.check(r, 'Personajes ineditos: Cream, Rouge y Vector (desbloquealos en PARTIDA)',
                   self.xchars_var).pack(side='left')
        r = self._row(p, (10, 6))
        self.keys_hint = self.lbl(r, '', 'small', fg='#d8fff8', justify='left')
        self.keys_hint.pack(side='left')
        r = self._row(p, (14, 0))
        self.b_portable = self.btn(r, 'VERSION PORTABLE', self.do_portable, 'orange', 200)
        self.b_portable.pack(side='left')

    def _page_instalar(self):
        p = self.pages['instalar']
        tk.Frame(p, bg=TEAL, height=6).pack()
        r = self._row(p)
        self.lbl(r, 'Tu APK de Sonic Jump Fever 1.6.1 (arm64)').pack(side='left')
        r = self._row(p)
        self.apk_var = tk.StringVar(value=self.st.get('apk', ''))
        tk.Entry(r, textvariable=self.apk_var, font=self.F['small'], relief='flat', fg=NAVY,
                 highlightthickness=2, highlightcolor=YELLOW, highlightbackground='white').pack(
            side='left', fill='x', expand=True, ipady=5)
        tk.Frame(r, bg=TEAL, width=8).pack(side='left')
        self.btn(r, 'EXAMINAR...', self.browse_apk, 'blue', 130, 36).pack(side='left')
        r = self._row(p)
        self.apk_status = self.lbl(r, '', 'label', wraplength=660, justify='left')
        self.apk_status.pack(side='left')
        r = self._row(p)
        self.convert_var = tk.BooleanVar(value=self.st.get('music', True))
        self.check(r, 'Convertir la musica del juego (.m4a -> .ogg, necesita ffmpeg)', self.convert_var).pack(
            side='left')
        r = self._row(p, (16, 0))
        self.b_install = self.btn(r, 'INSTALAR DATOS DEL JUEGO', self.do_install, 'green', 260, 44)
        self.b_install.pack(side='left')
        r = self._row(p, (22, 0))
        self.lbl(r, 'Se extraen la libreria ARM64, base.apk y los 61 assets en port/game/.\n'
                    'Nada de esto va en el paquete del proyecto: sale siempre de tu APK.', 'small',
                 fg='#d8fff8', justify='left').pack(side='left')

    def _page_compilar(self):
        p = self.pages['compilar']
        tk.Frame(p, bg=TEAL, height=4).pack()
        r = self._row(p)
        self.tgt_var = tk.StringVar(value=self.st.get('target', L.HOST if L.HOST in L.TARGETS else 'linux'))
        for val, txt in (('windows', 'Windows (.exe)'), ('linux', 'Linux')):
            tk.Radiobutton(r, text=txt, value=val, variable=self.tgt_var, bg=TEAL, fg='white',
                           selectcolor=TEAL_DARK, activebackground=TEAL, activeforeground=YELLOW,
                           font=self.F['label'], bd=0, highlightthickness=0).pack(side='left', padx=(0, 16))
        self.mode_lbl = self.lbl(r, '', 'small', fg='#d8fff8')
        self.mode_lbl.pack(side='left')
        self.tgt_var.trace_add('write', lambda *a: self.refresh_tc())
        self.tc_frame = tk.Frame(p, bg=TEAL_DARK, padx=10, pady=8)
        self.tc_frame.pack(fill='x', padx=14, pady=(0, 8))
        r = self._row(p)
        self.b_fetch = self.btn(r, 'DESCARGAR LO QUE FALTA', self.do_fetch, 'orange', 250)
        self.b_fetch.pack(side='left')
        r = self._row(p, (6, 8))
        self.lbl(r, 'Configuracion').pack(side='left')
        self.cfg_var = tk.StringVar(value=self.st.get('config', 'Release'))
        self.combo(r, self.cfg_var, ['Release', 'RelWithDebInfo', 'Debug'], 14).pack(side='left', padx=8)
        self.lbl(r, 'Hilos').pack(side='left', padx=(10, 0))
        self.jobs_var = tk.IntVar(value=self.st.get('jobs', os.cpu_count() or 4))
        ttk.Spinbox(r, from_=1, to=64, textvariable=self.jobs_var, width=4, style='Game.TSpinbox').pack(
            side='left', padx=8)
        self.b_build = self.btn(r, 'COMPILAR', self.do_build, 'green', 170, 42)
        self.b_build.pack(side='right')
        r = self._row(p, (4, 0))
        self.prog = ttk.Progressbar(r, mode='determinate', maximum=100, style='Game.Horizontal.TProgressbar')
        self.prog.pack(fill='x')

    def _page_controles(self):
        p = self.pages['controles']
        self.ctl_path = os.path.join(L.PORT, 'controls.cfg')
        self.ctl_keys = sjf_controls.load(self.ctl_path)
        self.ctl_capture = None
        tk.Frame(p, bg=TEAL, height=4).pack()
        self.ctl_rows = {}
        for act, label in sjf_controls.ACTIONS:
            r = self._row(p, (0, 6))
            self.lbl(r, label, width=22, anchor='w').pack(side='left')
            chips = tk.Label(r, text='', bg=NAVY, fg='white', font=self.F['label'], padx=10, pady=4,
                             width=19, anchor='w')
            chips.pack(side='left', padx=(0, 8))
            self.btn(r, 'CAMBIAR', lambda a=act: self.capture_key(a, False), 'blue', 104, 32).pack(side='left')
            tk.Frame(r, bg=TEAL, width=6).pack(side='left')
            self.btn(r, '+ OTRA', lambda a=act: self.capture_key(a, True), 'purple', 96, 32).pack(side='left')
            self.ctl_rows[act] = chips
        r = self._row(p, (10, 4))
        self.ctl_msg = self.lbl(r, '', 'label', fg=YELLOW)
        self.ctl_msg.pack(side='left')
        r = self._row(p, (4, 4))
        self.btn(r, 'GUARDAR', self.save_controls, 'green', 150, 40).pack(side='left')
        tk.Frame(r, bg=TEAL, width=10).pack(side='left')
        self.btn(r, 'POR DEFECTO', self.reset_controls, 'orange', 160, 40).pack(side='left')
        r = self._row(p, (8, 0))
        self.lbl(r, 'Raton = tocar donde apuntas.  Alt+Enter = pantalla completa (fijo).\n'
                    'Mando: stick izq./cruceta = inclinar, stick der. = cursor, A = tocar, B/Start = atras.\n'
                    'Se guarda en port/controls.cfg (la version portable lo copia).', 'small', fg='#d8fff8',
                 justify='left').pack(side='left')

    def _page_partida(self):
        p = self.pages['partida']
        self.pv = {}
        tk.Frame(p, bg=TEAL, height=2).pack()
        top = tk.Frame(p, bg=TEAL)
        top.pack(fill='x', padx=14)
        for i, (k, label) in enumerate((('rings', 'Anillos'), ('redrings', 'Red Star Rings'),
                                        ('energy', 'Energia'))):
            self.lbl(top, label).grid(row=0, column=i * 2, sticky='w', padx=(0, 6))
            v = tk.IntVar(value=0)
            ttk.Spinbox(top, from_=0, to=9999999 if k == 'rings' else 99999, textvariable=v, width=9,
                        style='Game.TSpinbox').grid(row=0, column=i * 2 + 1, sticky='w', padx=(0, 22))
            self.pv[k] = v
        box = tk.Frame(p, bg=TEAL_DARK, padx=10, pady=6)
        box.pack(fill='x', padx=14, pady=(10, 6))
        self.lbl(box, 'Personajes desbloqueados', fg=YELLOW).grid(row=0, column=0, columnspan=5, sticky='w')
        self.pv_chars = {}
        for i, c in enumerate(L.CHARACTERS):
            v = tk.BooleanVar(value=(c == 'sonic'))
            cb = tk.Checkbutton(box, text=L.CHAR_LABELS[c], variable=v, bg=TEAL_DARK, fg='white',
                                selectcolor=NAVY, activebackground=TEAL_DARK, activeforeground=YELLOW,
                                font=self.F['label'], bd=0, highlightthickness=0, width=10, anchor='w')
            cb.grid(row=1 + i // 5, column=i % 5, sticky='w')
            if c == 'sonic':
                cb.configure(state='disabled', disabledforeground='#cfe')
            self.pv_chars[c] = v
        box2 = tk.Frame(p, bg=TEAL_DARK, padx=10, pady=6)
        box2.pack(fill='x', padx=14, pady=(0, 6))
        self.lbl(box2, 'Boosters', fg=YELLOW).grid(row=0, column=0, sticky='w')
        self.pv_boost = {}
        for n, (i, field, label) in enumerate(L.BOOSTERS):
            self.lbl(box2, label, 'small').grid(row=1 + n // 4, column=(n % 4) * 2, sticky='w', padx=(0, 4))
            v = tk.IntVar(value=0)
            ttk.Spinbox(box2, from_=0, to=999, textvariable=v, width=4, style='Game.TSpinbox').grid(
                row=1 + n // 4, column=(n % 4) * 2 + 1, sticky='w', padx=(0, 14), pady=2)
            self.pv_boost[i] = v
        r = self._row(p, (4, 2))
        self.b_save_prof = self.btn(r, 'GUARDAR EN LA PARTIDA', self.do_profile_save, 'green', 240, 40)
        self.b_save_prof.pack(side='left')
        tk.Frame(r, bg=TEAL, width=10).pack(side='left')
        self.btn(r, 'RECARGAR', self.refresh_profile, 'blue', 130, 40).pack(side='left')
        tk.Frame(r, bg=TEAL, width=10).pack(side='left')
        self.btn(r, 'COPIAS', self.open_backups, 'purple', 110, 40).pack(side='left')
        r = self._row(p, (2, 0))
        self.prof_msg = self.lbl(r, '', 'small', fg='#d8fff8', justify='left', wraplength=680)
        self.prof_msg.pack(side='left')

    def _page_registro(self):
        p = self.pages['registro']
        self.logbox = tk.Text(p, wrap='none', font=('TkFixedFont', 9), background='#0b1a2e', foreground='#cfe8ff',
                              insertbackground='white', relief='flat', padx=8, pady=6)
        self.logbox.pack(fill='both', expand=True, padx=8, pady=8)

    # --------------------------------------------------------------- refresh
    def refresh_all(self):
        self.refresh_apk()
        self.refresh_tc()
        self.refresh_zone()
        self.refresh_keys_hint()
        self.refresh_banner()

    def refresh_banner(self):
        if self.busy:
            return
        exe_ok = os.path.isfile(L.exe_path(self.tgt_var.get()))
        if not L.game_installed():
            self.set_banner('Falta instalar los datos del juego: ve a INSTALAR')
        elif not exe_ok:
            self.set_banner('Datos listos. Falta compilar: ve a COMPILAR')
        else:
            self.set_banner('Todo listo. Pulsa JUGAR!')

    def refresh_zone(self):
        cur, nxt = L.weekly_zone()
        if self.zone_key() == 'weekly':
            self.zone_info.configure(text='Esta semana: %s   |   proxima: %s' % (dict(L.ZONES)[cur], dict(L.ZONES)[nxt]))
        else:
            self.zone_info.configure(text='')

    def refresh_keys_hint(self):
        k = sjf_controls.load(os.path.join(L.PORT, 'controls.cfg'))
        self.keys_hint.configure(text='Teclas: inclinar %s / %s   tocar %s   atras %s   pantalla completa %s'
                                 % ('+'.join(k['tilt_left']), '+'.join(k['tilt_right']), '+'.join(k['tap']),
                                    '+'.join(k['back']), '+'.join(k['fullscreen'])))

    def refresh_apk(self):
        path = self.apk_var.get().strip()
        info = L.inspect_apk(path)
        txt = info['msg'] if path else 'Elige el APK de Sonic Jump Fever 1.6.1 (arm64).'
        if L.game_installed():
            txt += '\nDatos del juego instalados en port/game.'
        ok = info['ok'] and info.get('version')
        self.apk_status.configure(text=txt, fg=YELLOW if ok else ('white' if not path else '#ffd0d0'))

    def refresh_tc(self):
        t = self.tgt_var.get()
        mode = 'compilacion nativa' if t == L.HOST else ('compilacion cruzada (zig)' if t == 'windows'
                                                         else 'via WSL (experimental)')
        self.mode_lbl.configure(text='-> ' + mode)
        for w in self.tc_frame.winfo_children():
            w.destroy()
        for i, (name, path, hint) in enumerate(L.toolchain_status(t)):
            ok = bool(path)
            tk.Label(self.tc_frame, text='OK' if ok else 'FALTA', bg='#27c227' if ok else '#e53935', fg='white',
                     font=self.F['small'], width=6).grid(row=i, column=0, sticky='w', pady=1)
            tk.Label(self.tc_frame, text=name, bg=TEAL_DARK, fg='white', font=self.F['label'], width=24,
                     anchor='w').grid(row=i, column=1, sticky='w', padx=8)
            tk.Label(self.tc_frame, text=(path if ok else hint)[-62:], bg=TEAL_DARK, fg='#d8fff8',
                     font=self.F['small'], anchor='w').grid(row=i, column=2, sticky='w')
        self.refresh_banner()

    def refresh_controls(self):
        for act, chips in self.ctl_rows.items():
            chips.configure(text='  '.join('[%s]' % k for k in self.ctl_keys[act]))

    def refresh_profile(self):
        try:
            cur = L.read_profile()
        except Exception as e:  # noqa
            cur = None
            self.prof_msg.configure(text='No se pudo leer la partida: %s' % e)
        self.prof_cur = cur
        if not cur:
            self.prof_msg.configure(text='Todavia no hay partida guardada (port/game/data/profile0.dat). '
                                         'Juega una vez y vuelve.')
            self.b_save_prof.set_enabled(False)
            return
        self.b_save_prof.set_enabled(not self.busy)
        for k in ('rings', 'redrings', 'energy'):
            self.pv[k].set(int(cur[k]))
        for c, v in self.pv_chars.items():
            v.set(cur['chars'][c] or c == 'sonic')
        for i, v in self.pv_boost.items():
            v.set(int(cur['boosters'][i]))
        self.prof_msg.configure(text='Cream, Rouge y Vector: marcalos para jugar con ellos. Los cambios los guarda el PROPIO JUEGO (abre oculto, aplica y guarda), asi '
                                     'el control CRC del save es valido. Antes se hace una copia en '
                                     'port/game/save_backups/.')

    # --------------------------------------------------------------- helpers
    def zone_key(self):
        for k, v in L.ZONE_LABELS.items():
            if v == self.zone_var.get():
                return k
        return 'weekly'

    def aspect_key(self):
        for k, v in L.ASPECTS:
            if v == self.aspect_var.get():
                return k
        return '9:16'

    def persist(self):
        d = L.load_settings()
        d.update({'apk': self.apk_var.get().strip(), 'target': self.tgt_var.get(), 'config': self.cfg_var.get(),
                  'jobs': int(self.jobs_var.get() or 1), 'window': self.win_var.get(), 'fullscreen': self.fs_var.get(),
                  'music': self.convert_var.get(), 'zone': self.zone_key(), 'aspect': self.aspect_key(),
                  'page': self.cur_page, 'extra_chars': self.xchars_var.get(), 'menu_music': self.music.playing or (not self.music.available and
                                                                              self.st.get('menu_music', True))})
        L.save_settings(d)

    def all_buttons(self):
        return [self.b_install, self.b_fetch, self.b_build, self.b_portable, self.b_save_prof]

    def task(self, fn, done=None):
        if self.busy:
            return
        self.busy = True
        for b in self.all_buttons():
            b.set_enabled(False)
        self.cbs.update(self.start, enabled=False)
        self.persist()

        def worker():
            err = None
            try:
                fn()
            except Exception as e:  # noqa
                err = str(e)
                self.log('ERROR: %s' % err)
            self.q.put(('done', (err, done)))
        threading.Thread(target=worker, daemon=True).start()

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == 'log':
                    self.logbox.insert('end', val + '\n')
                    if int(self.logbox.index('end-1c').split('.')[0]) > 4000:
                        self.logbox.delete('1.0', '1000.0')
                    self.logbox.see('end')
                    self.cv.itemconfigure(self.status_txt, text=val[:110])
                elif kind == 'prog':
                    self.prog['value'] = val
                elif kind == 'banner':
                    self.set_banner(val)
                elif kind == 'done':
                    err, done = val
                    self.busy = False
                    for b in self.all_buttons():
                        b.set_enabled(True)
                    self.cbs.update(self.start, enabled=True)
                    self.refresh_all()
                    if done:
                        done()
                    if err:
                        messagebox.showerror('Jump Fever Recomp', err)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def tick(self):
        self.music.tick()
        if self.game_proc is not None and self.game_proc.poll() is not None:
            self.game_proc = None
            self.set_banner('Juego cerrado. Pulsa JUGAR para volver!')
            if self.st.get('menu_music', True) and self.resume_music:
                self.music.play()
                self._music_btn_update()
        self.root.after(1000, self.tick)

    # --------------------------------------------------------------- actions
    def toggle_music(self):
        if not self.music.available:
            messagebox.showinfo('Musica', 'No hay reproductor disponible (Linux: instala ffmpeg/ffplay o mpv).')
            return
        if self.music.playing:
            self.music.stop()
        else:
            self.music.play()
        self.st['menu_music'] = self.music.playing
        self._music_btn_update()

    def _music_btn_update(self):
        if not self.music.available:
            self.cbs.update(self.music_btn, text='MUSICA: N/D', color='grey')
        else:
            self.cbs.update(self.music_btn, text='MUSICA: SI' if self.music.playing else 'MUSICA: NO',
                            color='green' if self.music.playing else 'blue')

    def browse_apk(self):
        p = filedialog.askopenfilename(title='Selecciona tu APK de Sonic Jump Fever',
                                       filetypes=[('APK de Android', '*.apk'), ('Todos', '*.*')])
        if p:
            self.apk_var.set(p)
            self.refresh_apk()

    def do_install(self):
        self.q.put(('banner', 'Instalando datos del juego...'))
        self.task(lambda: L.install_apk(self.apk_var.get().strip(), self.log, self.convert_var.get()))

    def do_fetch(self):
        self.q.put(('banner', 'Descargando herramientas...'))
        self.task(lambda: L.fetch_missing(self.tgt_var.get(), self.log))

    def do_build(self):
        self.q.put(('banner', 'Compilando... (la primera vez tarda varios minutos)'))
        self.task(lambda: L.build(self.tgt_var.get(), self.log, int(self.jobs_var.get() or 1), self.cfg_var.get(),
                                  lambda i, n: self.q.put(('prog', i * 100.0 / max(n, 1)))))

    def do_portable(self):
        self.task(lambda: L.make_portable(self.tgt_var.get(), self.log))

    def do_play(self):
        holder = {}

        def run():
            holder['p'] = L.play(self.tgt_var.get(), self.log, self.win_var.get() or None, self.fs_var.get(),
                                 self.mute_var.get(), self.dbg_var.get(), zone=self.zone_key(),
                                 aspect=self.aspect_key(), extra_chars=self.xchars_var.get())

        def started():
            if 'p' in holder:
                self.game_proc = holder['p']
                self.resume_music = self.music.playing
                self.music.stop()  # the game has its own music
                self._music_btn_update()
                self.set_banner('Jugando...  (cierra el juego para volver al launcher)')
        self.q.put(('banner', 'Lanzando el juego...'))
        self.task(run, started)

    def capture_key(self, act, add):
        self.ctl_capture = (act, add)
        self.ctl_msg.configure(text='Pulsa una tecla para "%s"...  (clic derecho = cancelar)'
                                    % dict(sjf_controls.ACTIONS)[act])
        self.root.bind('<KeyPress>', self._on_capture)
        self.root.bind('<Button-3>', lambda e: self._end_capture('Cancelado.'))
        self.root.focus_force()

    def _on_capture(self, e):
        if not self.ctl_capture:
            return
        act, add = self.ctl_capture
        name = sjf_controls.tk_to_sdl(e.keysym)
        if not name:
            self.ctl_msg.configure(text='Tecla "%s" no soportada, prueba otra.' % e.keysym)
            return
        if add:
            if name not in self.ctl_keys[act]:
                self.ctl_keys[act].append(name)
        else:
            self.ctl_keys[act] = [name]
        for other, keys in self.ctl_keys.items():  # one key -> one action
            if other != act and name in keys and len(keys) > 1:
                keys.remove(name)
        self.refresh_controls()
        self._end_capture('Asignado [%s]. Pulsa GUARDAR para aplicarlo.' % name)

    def _end_capture(self, msg):
        self.ctl_capture = None
        self.root.unbind('<KeyPress>')
        self.root.unbind('<Button-3>')
        self.ctl_msg.configure(text=msg)

    def save_controls(self):
        sjf_controls.save(self.ctl_path, self.ctl_keys)
        self.ctl_msg.configure(text='Guardado en port/controls.cfg')
        self.log('controles guardados: %s' % self.ctl_path)
        self.refresh_keys_hint()

    def reset_controls(self):
        self.ctl_keys = {k: list(v) for k, v in sjf_controls.DEFAULTS.items()}
        self.refresh_controls()
        self.ctl_msg.configure(text='Teclas por defecto (pulsa GUARDAR para aplicarlo).')

    def do_profile_save(self):
        cur = getattr(self, 'prof_cur', None)
        if not cur:
            return
        try:
            new = {k: int(self.pv[k].get()) for k in ('rings', 'redrings', 'energy')}
            new['chars'] = {c: bool(v.get()) for c, v in self.pv_chars.items()}
            new['boosters'] = {i: int(v.get()) for i, v in self.pv_boost.items()}
        except (tk.TclError, ValueError):
            messagebox.showerror('Partida', 'Valores no validos (usa numeros enteros).')
            return
        cmds = L.profile_edit_commands(cur, new)
        if not cmds:
            self.prof_msg.configure(text='No hay cambios.')
            return
        if self.game_proc is not None:
            messagebox.showwarning('Partida', 'Cierra el juego antes de editar la partida.')
            return
        self.q.put(('banner', 'Guardando la partida con el juego...'))
        self.task(lambda: L.apply_profile_edits(self.tgt_var.get(), cmds, self.log),
                  lambda: (self.refresh_profile(), self.prof_msg.configure(
                      text='Hecho: %d cambio(s) guardados por el juego. Copia previa en save_backups/.'
                           % len(cmds))))

    def open_backups(self):
        d = os.path.join(L.GAME, 'save_backups')
        os.makedirs(d, exist_ok=True)
        if L.IS_WIN:
            os.startfile(d)  # noqa
        else:
            messagebox.showinfo('Copias de seguridad', d)

    def close(self):
        self.persist()
        self.music.close()
        self.root.destroy()

    def run(self):
        if os.environ.get('SJF_LAUNCHER_SCREENSHOT_EXIT'):
            self.root.after(int(os.environ['SJF_LAUNCHER_SCREENSHOT_EXIT']), self.close)
        self.root.mainloop()


def main():
    App().run()
