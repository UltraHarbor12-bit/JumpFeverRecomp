import io

p = 'docs/03b-hito2c-progreso.md'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

add = '''
### Addendum — watchpoint de escritura

Se instaló un **watchpoint en runtime** en `0x1005cbed0` (el singleton): se registran todas las
escrituras de 1/4/8 bytes a esa dirección junto con el PC que las ejecuta.

**Resultado: cero escrituras durante todo el arranque.** Es decir, la ruta de inicialización de
`PlayerProfile` nunca se ejecuta (no es que falle a medias). Además:

- El constructor en `0x330798` (`_ZN13PlayerProfileC1Ev`) solo pone a cero 10 bytes y hace un
  *tail-call* condicional a `0x330424`; **no asigna ningún puntero**.
- No hay llamadas directas (`bl`) a ese constructor ni a `0x330424`: se invoca de forma indirecta.
- `PlayerProfile::load()` (0x32c7c8) también **consume** el `impl` (llama antes a `isSfxEnabled()`),
  así que tampoco lo crea.

Conclusión: el motor inicializa ese singleton desde una ruta de arranque que nuestro shim aún no
dispara (probablemente el despachador de comandos `APP_CMD_*` del hilo propio del motor).

### Ghidra

El análisis headless fallaba por una causa trivial: **`APPDATA` no estaba definida** en el shell
(`LaunchSupport` no podía crear su configuración y reportaba "Failed to find a supported JDK").
Con `APPDATA`, `LOCALAPPDATA` y `JAVA_HOME` exportados, el análisis de `libsonicjumpfever.so`
queda lanzado en `extracted/ghidra_proj`.
'''

s = s.rstrip() + '\n' + add
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('doc updated')
