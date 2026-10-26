## Actualización (Hito 2c) — 19 oct 2026, tarde

### Conseguido desde la versión anterior del documento

| Avance | Detalle |
|---|---|
| **Superficie temprana** | La ventana y `onNativeWindowCreated` se entregan **justo después de `onCreate`**. Esto eliminó el fallo del hilo de trabajo (carrera de orden) y desbloqueó el pipeline gráfico |
| **EGL alcanzado** | Ya se ejecutan `eglCreateWindowSurface`, `eglCreateContext` y `eglMakeCurrent` sobre la ventana SDL (GL 4.6 / Intel UHD) |
| **Deadlock de pipes corregido** | `read`/`write` mantenían `g_fd_mutex` durante I/O bloqueante → escritor bloqueado con el mutex tomado y lector sin poder entrar. Ahora el lock se suelta antes del I/O |
| **`ALooper_pollAll` correcto** | `WaitForMultipleObjects` no señaliza de forma fiable sobre *anonymous pipes*; se sustituyó por sondeo con `PeekNamedPipe` (1 ms). El flujo de comandos del motor ya funciona: `pipe write → pollAll ident=1 → pipe read` |
| **Diagnóstico de hilos** | Nuevo volcado en el watchdog: PC/LR/SP/FP de cada hilo huésped + nombre de la llamada host en curso (trampoline) |
| **Volcado de registros en fallo** | x0–x29 + backtrace por *frame pointers* |

### Bloqueo identificado con precisión

`PlayerProfile::triggerStartCount()` (0x32c7a8) — y todas las funciones de `PlayerProfile` — acceden a:

```
GOT[0x5bd130]  →  &sInstance (objeto estático en .bss, 0x5cbed0)
*(sInstance)   →  impl  == NULL          ← nunca se creó
[impl + 0xb80] →  puntero al dato
[.. + 0xb8]    →  contador (++/--)
```

`PlayerProfile::load()` **no** inicializa ese `impl` (lo consume: llama a `isSfxEnabled()`, `isMusicEnabled()` y `triggerStartCount()`, que fallan igual). Por tanto el `impl` lo crea el constructor/singleton de `PlayerProfile`, que o bien no se ejecutó, o bien salió antes de asignarlo (probable: inicialización estática local con *guard* que quedó marcada sin completar, o dependencia de una llamada Java que devolvió `null`).

### Siguiente paso

1. Localizar el constructor/`init` que asigna `*(0x5cbed0)` (Ghidra ya está analizando el binario en `extracted/ghidra_proj`; con el `.dynsym` se puede cruzar por xrefs al `str [x,#0]` con base `0x5cbed0`).
2. Si es un *static local* con guard: inspeccionar el byte de guard en `.bss` y forzar la reinicialización (o parchear el guard antes de llamar).
3. Alternativa de diagnóstico: pasar `--peek` y volcar los 64 bytes de `0x5cbed0` en varios momentos del arranque para ver si el primer campo cambia.

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

### Addendum 2 — verificación del singleton y VFS de assets

**Verificación en runtime del mapeo** (descarta errores de interpretación):

```
probe: GOT[0x5bd130] = 0x1005cbed0   (objeto .bss)
       *objeto       = 0x0            (primer campo, nunca escrito)
       [objeto+0xb80]= 0x0
```

- Watchpoint de escritura del JIT (1/4/8 bytes) → **0 escrituras**.
- Watchpoint en `memcpy`/`memmove`/`memset` (destino dentro del objeto) → **0 accesos**.
- Los 404-405 constructores de `.init_array` se ejecutan y retornan limpios (sin fallos).
- `PlayerProfile::PlayerProfile()` (0x330798) solo escribe 10 bytes (bool/int/bool/bool): es una clase
  pequeña, **no** el objeto de 0xb80.

Conclusión: el objeto al que apunta el slot GOT nunca se inicializa en nuestra ejecución; la ruta que
lo hace (probablemente el despachador de comandos `APP_CMD_*` del hilo propio del motor, al recibir
`INIT_WINDOW`/`RESUME` con un estado concreto) no se dispara con nuestro shim actual.

**VFS de assets implementado**: `open`/`fopen` traducen cualquier ruta que contenga `assets/<X>` a
`game/assets/<X>`; los 61 assets del APK están copiados en `port/game/assets/`. Esto deja preparada
la carga real de `.sla`/`.snd` en cuanto el motor avance.

**Ghidra**: el headless funciona por la vía `bash` de MSYS (el `.bat` se colgaba y el error
"Failed to find a supported JDK" era en realidad `APPDATA` sin definir). El proyecto
`extracted/ghidra_proj` está analizado y el script `tools/DumpTargets.java` volcó la
decompilación, pero el análisis automático identifica mal varias funciones de este binario
(nombres desplazados) y no hay xrefs directas al singleton (acceso mediado por GOT).
