# Hito 5 — Launcher, build Windows verificado, inclinación, letterbox (25 oct 2026)

## Resumen

| Tema | Estado | Evidencia |
|---|---|---|
| **Launcher** (`tools/launcher/sjf_launcher.py`) | Nuevo: GUI tkinter + CLI. Pide tu APK, lo valida, extrae datos, elige Windows/Linux, descarga herramientas, compila, juega, crea portable | Probado desde una copia limpia: APK → deps → build → jugar (Linux) y APK → deps → build cruzado (Windows) |
| **Build de Windows** | `sjfport.exe` **compila y enlaza** (cruzado con zig/clang 19 → x86_64-windows-gnu) | PE32+ x86-64; solo importa DLLs de sistema + UCRT; SDL2 estático |
| **Inclinación** | Verificada en juego: ← va a la izquierda, → a la derecha; el tutorial pasa el paso "Tilt Device to Steer" | prueba A/B con `SJF_TILT` |
| **Redimensionar / pantalla completa** | Letterbox: la superficie del juego queda fija en 540×960 y se escala centrada con bandas negras. F11 o Alt+Enter = pantalla completa. `--window WxH`, `--fullscreen` | Clics de ratón X11 reales (XTest) en una ventana de 960×720 llegan al gameplay |
| **CPU** | El bucle de paso fijo del motor sondeaba `pollAll(0)` ~27k veces/s (+2 llamadas JNI cada vez) | 542k → 14k llamadas en 20 s, sin perder FPS (~52 en software) |
| **Audio** | Ganancia maestra 0,85 + limitador suave (tanh) por encima de 0,8 | Pico −0,8 dBFS (antes +0,5 dBFS con clipping) |

**No probado en Windows real:** ejecutar el `.exe` (no hay Windows ni Wine en el sandbox), la
compilación nativa con tu MinGW GCC 16.2, las descargas de WinLibs/Boost/ffmpeg en Windows, la
unión `C:\sjf` automática y el camino Windows→Linux por WSL.

---

## 1. Launcher

```
python tools/launcher/sjf_launcher.py            # GUI
python tools/launcher/sjf_launcher.py --cli --apk TU.apk --target linux --fetch --build --run
python tools/launcher/sjf_launcher.py --cli --status --target windows
```

Pasos de la GUI:
1. **Tu APK**: comprueba que es un ZIP con `AndroidManifest.xml`, que el paquete es
   `com.sega.sonicjumpfever` y que trae `lib/arm64-v8a/libsonicjumpfever.so`. Compara el SHA-256 de
   la librería con la 1.6.1 conocida (`4bbe841e…`). Si no coincide avisa, porque el port usa
   direcciones fijas. "Instalar datos del juego" extrae `.so`, `base.apk` y los 61 assets en
   `port/game/` y, si hay ffmpeg, convierte la música a `.ogg`.
2. **Plataforma**: Windows o Linux. Muestra cada herramienta como OK/FALTA. "Descargar lo que
   falta" las instala dentro de `tools/` (no toca el sistema):

   | Host → destino | Compilador | Lo que descarga si falta |
   |---|---|---|
   | Windows → Windows | MinGW-w64 GCC (WinLibs 14.2 UCRT; detecta también `C:\sjf-mingw`) | WinLibs, SDL2-devel-mingw 2.32.10, Boost 1.86 (solo cabeceras), cmake+ninja por pip, ffmpeg |
   | Linux → Linux | g++/clang++ del sistema | cmake+ninja (pip; si no hay pip, conda-forge), entorno micromamba `tools/env-linux` con SDL2+Boost+GL |
   | Linux → Windows | zig (clang 19) cruzado | ziglang (pip o conda-forge), SDL2-devel-mingw, Boost |
   | Windows → Linux | WSL (experimental) | ejecuta el launcher en modo CLI dentro de WSL |

   Si la ruta del proyecto tiene espacios (el linker de MinGW no los soporta), crea la unión
   `C:\sjf` automáticamente.
3. **Compilar**: CMake + Ninja con barra de progreso. Directorios: `port/build` (Windows nativo,
   el mismo de siempre), `port/build-win-cross`, `port/build-linux`.
4. **Jugar**: tamaño de ventana, pantalla completa, sin sonido, depuración. El log queda en
   `port/sjfport_last.log`. "Crear versión portable" genera `dist/<plataforma>/` con `bin/`,
   `game/` y `Jugar.bat` / `jugar.sh`. En Linux, si se compiló con el SDL2 de micromamba, incluye
   `bin/lib/libSDL2` y `jugar.sh` solo lo usa si el sistema no tiene SDL2. Esa carpeta contiene
   datos de tu APK: no la distribuyas.

Ajustes guardados en `tools/launcher/launcher.json`.

## 2. Cambios para compilar con clang/zig (inocuos en GCC)

- `port/cmake/zig-windows.cmake` + wrappers `port/cmake/zig/zig-*` (el launcher los genera con la
  ruta absoluta de zig). Añade `-DFMT_CONSTEVAL=`: fmt 10.1 falla con `consteval` en clang ≥ 17.
- `dynarmic/externals/mcl/.../lift_sequence.hpp`: especialización explícita para
  `std::integer_sequence` (clang ≥ 19 ya no deduce la genérica).
- `dynarmic/externals/fmt/include/fmt/ostream.h`: `<__std_stream>` y `std::__stdoutbuf` ya no
  existen en libc++ reciente; ahora se incluyen solo si están disponibles.

## 3. Cambios en el port

- **Inclinación**: el teclado ya iba bien (← = +X = inclinar a la izquierda). El hook `SJF_TILT`
  inicial fallaba porque `platform_pump()` lo pisaba con 0 en cada frame. Ahora usa
  `input_set_tilt_override()`, que tiene prioridad sobre el teclado.
  `SJF_TILT="16000:-7;19000:7;28000:0"` (ms : m/s²; negativo = derecha).
- **Letterbox** (`window.cpp`, `libgl.cpp`): `eglQuerySurface` devuelve siempre la superficie fija.
  `glViewport`/`glScissor` del juego (no usa FBOs) se reescalan a un rectángulo centrado y se
  reaplican cuando cambia el tamaño. Las bandas se limpian en negro antes del swap. Ratón ventana →
  superficie, con soporte HiDPI. Las capturas recogen solo la imagen del juego.
- **Opciones nuevas**: `--window WxH`, `--fullscreen`, F11 / Alt+Enter.
- **Windows**: `timeBeginPeriod(1)` para que las esperas cortas duren ~1 ms y no 15,6 ms.
- **Looper**: espera de 0,5 ms cuando `pollAll(0)` no tiene nada.

## 4. Herramientas de prueba (Linux/Xvfb)

- `xclick.py "t:x,y;..."`: clics X11 reales mediante XTest, en coordenadas de pantalla.
- `record2.sh`: vídeo (x11grab) + audio (`SDL_AUDIODRIVER=disk`) con letterbox, ratón e inclinación.

## 5. Pendiente

1. Probar en Windows real: launcher (GUI, descargas, unión `C:\sjf`) y el `.exe`, tanto el nativo
   como el cruzado de `port/build-win-cross`.
2. El camino Windows→Linux por WSL no está probado.
3. Mandos (SDL GameController): stick → inclinación, botón A → toque.
4. Guardado: `game/data/` funciona; falta comprobar progreso y tienda entre sesiones largas.
5. Las pantallas que dependen de red (Facebook, ranking, tienda) responden en modo offline:
   revisar cada una.
