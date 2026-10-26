"""Key remapping: port/controls.cfg (read by sjfport at start-up).

Format, one action per line, SDL scancode names (what SDL_GetScancodeFromName accepts):
    tilt_left = Left, A
    tilt_right = Right, D
    tap = Space, Return
    back = Escape, Backspace
    fullscreen = F11
"""
import os

ACTIONS = [
    ('tilt_left', 'Inclinar a la izquierda'),
    ('tilt_right', 'Inclinar a la derecha'),
    ('tap', 'Tocar / saltar (centro)'),
    ('back', 'Atras / pausa'),
    ('fullscreen', 'Pantalla completa'),
]
DEFAULTS = {
    'tilt_left': ['Left', 'A'],
    'tilt_right': ['Right', 'D'],
    'tap': ['Space', 'Return'],
    'back': ['Escape', 'Backspace'],
    'fullscreen': ['F11'],
}

# Tk keysym -> SDL scancode name
_TK2SDL = {
    'Return': 'Return', 'KP_Enter': 'Keypad Enter', 'Escape': 'Escape', 'BackSpace': 'Backspace',
    'Tab': 'Tab', 'space': 'Space', 'Left': 'Left', 'Right': 'Right', 'Up': 'Up', 'Down': 'Down',
    'Shift_L': 'Left Shift', 'Shift_R': 'Right Shift', 'Control_L': 'Left Ctrl',
    'Control_R': 'Right Ctrl', 'Alt_L': 'Left Alt', 'Alt_R': 'Right Alt', 'Insert': 'Insert',
    'Delete': 'Delete', 'Home': 'Home', 'End': 'End', 'Prior': 'PageUp', 'Next': 'PageDown',
    'minus': '-', 'equal': '=', 'bracketleft': '[', 'bracketright': ']', 'semicolon': ';',
    'apostrophe': "'", 'comma': ',', 'period': '.', 'slash': '/', 'backslash': '\\', 'grave': '`',
    'Caps_Lock': 'CapsLock',
}
for _i in range(1, 13):
    _TK2SDL['F%d' % _i] = 'F%d' % _i
for _i in range(10):
    _TK2SDL['KP_%d' % _i] = 'Keypad %d' % _i
    _TK2SDL[str(_i)] = str(_i)


def tk_to_sdl(keysym):
    """Return the SDL scancode name for a Tk keysym, or None if unsupported."""
    if len(keysym) == 1 and keysym.isalpha():
        return keysym.upper()
    return _TK2SDL.get(keysym)


def load(path):
    keys = {k: list(v) for k, v in DEFAULTS.items()}
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0]
                if '=' not in line:
                    continue
                act, rest = line.split('=', 1)
                act = act.strip()
                if act in keys:
                    names = [n.strip() for n in rest.split(',') if n.strip()]
                    if names:
                        keys[act] = names
    return keys


def save(path, keys):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Jump Fever Recomp - teclas (generado por el launcher)\n'
                '# accion = Tecla, Tecla   (nombres de SDL; Alt+Enter siempre = pantalla completa)\n')
        for act, _ in ACTIONS:
            f.write('%s = %s\n' % (act, ', '.join(keys.get(act) or DEFAULTS[act])))
