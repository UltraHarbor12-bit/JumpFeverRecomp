# Hito 4 — Input, audio, build Linux y gameplay (25 oct 2026)

**Resultado:** el juego llega a jugarse. Secuencia verificada:
logo Hardlight → age gate ("25" tecleado + confirmar) → popup Facebook ("Later") →
título *Sonic Jump Fever* → cuenta atrás → **Green Hill Zone tutorial** ("Tilt Device to Steer!",
monedas, "Try Again!"), con **música** (frontend/act_start/green_hill_zone0) y **efectos** de sonido.
~52 FPS sostenidos en 40 s con render por software (Mesa llvmpipe); log de 387 líneas.

---

## 1. El "bloqueo de input" del doc 05 NO era el looper

- El fix propuesto (`input_poll_ready` dentro de `ALooper_pollAll`) **ya estaba en el código** y el
  `.exe` de run91 ya lo llevaba.
- "`AInputQueue_getEvent` = 0 llamadas" era un **falso negativo**: `getEvent` no tiene log, y los
  `LOGD` del looper se perdían porque se ejecutaba con logs `[D]` desactivados.
- Instrumentado: `pollAll` devuelve ident 2, el glue (`process_input` @0x4feb20, estándar) vacía
  el FIFO y llama `appTouchBegan` (@0x3352fc). **El input siempre funcionó.**
- Causa real de "no pasa nada": el autotap pulsa el centro (270,480), que cae **en el hueco entre
  el botón 2 y el 5** del teclado del age gate.

## 2. Bugs reales encontrados y corregidos

| # | Bug | Síntoma | Fix |
|---|---|---|---|
| 1 | **Fuga en JNI**: `GetStaticMethodID`/`GetMethodID`/`FindClass`/`NewStringUTF` asignaban un bloque nuevo en cada llamada. El motor re-resuelve IDs cada frame y el bucle `HTTPManager.callbackPump` + `AndroidAds.pollAdCaching` lo hace ~40.000 veces/s | La región de 16 MiB de *native data* se agotaba en segundos → `GetStaticMethodID` devolvía 0 → 1,1 M líneas `native data region exhausted`. **Probable causa del cuelgue en la pantalla de carga de run91** | IDs y clases **internados** (`make_fake_interned`); strings al heap guest (4 GiB) |
| 2 | `alloc_native_data` sin mutex | Carrera entre hilos guest | `std::mutex` |
| 3 | `SLPlayItf::GetPlayState` devolvía siempre PLAYING | `slPlayEffect` (@0x286434) busca un canal con estado != 3 → los 16 canales parecían ocupados → **nunca sonaba ningún efecto** | Estado real por player |
| 4 | `Enqueue` descartaba el PCM y nunca llamaba al callback | Sin audio; canales nunca liberados (el callback del motor @0x2f4b84 pone PAUSED y gestiona loops) | Mezclador SDL + hilo de callbacks |
| 5 | `musicplayer.PlayAudioFile` no coincidía con el stub (`P` mayúscula) | Sin música | Implementado (lee args del `va_list` AArch64) |
| 6 | DOWN y UP del tap en el mismo frame | Taps poco fiables | UP 100 ms después (autotap y guion) |

## 3. Audio (nuevo `src/platform/audio.cpp`)

- Salida SDL2 44,1 kHz estéreo S16, mezclador software (remuestreo lineal, 8/16 bit, mono/estéreo).
- **Efectos**: cada `CreateAudioPlayer` lee su `SLDataFormat_PCM` y crea una *voz*.
  `Enqueue` encola el puntero guest; `SetPlayState` (1 STOP=vaciar, 2 PAUSE, 3 PLAY),
  `GetPlayState`, `Clear`, `GetState`, `SetVolumeLevel` (mB→lineal), `SetMute`, `SetRate`.
  Al terminar cada buffer se llama `cb(bqItf, ctx)` del guest **en un hilo propio** (nunca en el
  hilo del dispositivo de audio).
- **Música**: `musicplayer.PlayAudioFile(path, loop, ?)`, `setVolume(F)`, `setPause(Z)`, `stop*`.
  El juego pide `.m4a` (AAC); el port reproduce el gemelo **`.ogg`** (stb_vorbis) o `.wav`.
  Generarlos una vez: `python tools/convert_music.py` (necesita ffmpeg; el paquete ya incluye los
  `.ogg` en `port/game/assets/`).
- Sin dispositivo de audio, los buffers se completan al instante (el juego sigue funcionando).

## 4. Build Linux (para depurar sin Windows)

El port compila y corre en Linux x86_64 sin cambiar el comportamiento de Windows:
- `include/sjfport/host_compat.h`: `host_ticks_ms`, `host_sleep_ms`, `host_exe_path`,
  `host_path_exists`, `host_pipe_available` (PeekNamedPipe / FIONREAD).
- `guest_memory.cpp`: `mprotect` necesita páginas alineadas (VirtualAlloc redondea solo).
- `libgl.cpp`: `SDL_GL_GetProcAddress` en POSIX; **ya no cachea NULL** (también en Windows).
- `CMakeLists.txt`: rama `if(WIN32)` idéntica a la anterior + rama Linux (find_package SDL2/OpenGL).
- `third_party/ndk/jni.h` (faltaba en el paquete): copiado de AOSP libnativehelper.

Entorno headless usado: micromamba (conda-forge: `xorg-xvfb-server boost-cpp sdl2 mesalib`),
Xvfb `:99` con GLX, Mesa llvmpipe. Scripts: `run.sh`, `record.sh` (vídeo x11grab + audio vía
`SDL_AUDIODRIVER=disk`).

## 5. Herramientas nuevas

- **`SJF_TAPS="<ms>:<x>,<y>;..."`**: taps guionizados en coordenadas exactas de ventana (540×960).
  Guion que llega al gameplay desde un perfil nuevo:
  `SJF_TAPS="5000:268,438;6000:268,537;7500:390,739;11000:160,774"`
  (2, 5, confirmar → edad 25; "Later" en el popup de Facebook).
- **`--verbose`** activa logs `[D]` (ahora **desactivados por defecto**: inundaban 4 M líneas/25 s
  y frenaban el juego). `--quiet` sigue aceptado.
- **`--debug`** activa watchpoints WATCH/WATCH2, sonda GOT y muestreo de PCs cada 2 s
  (antes siempre activos).
- `tools/sjfdis.py <símbolo|0xaddr> [n]`: desensamblador ARM64 con símbolos **y nombres PLT**.
- `tools/convert_music.py`, `tools/port_linux.py` (parche idempotente, ya aplicado).

Mapa de botones (ventana 540×960): teclado age gate — columnas x≈146/268/390,
filas y≈438/537/639/739 (fila 4: borrar, 0, confirmar). Facebook "Later" ≈ (160,774).

## 6. Pendiente / siguientes pasos

1. **Compilar y probar en Windows** con la toolchain del doc 05. Los cambios se comprobaron
   compilando cada fuente para `x86_64-windows-gnu` (zig/clang, sin enlazar), no con MinGW GCC 16.2
   ni ejecutando en Windows. Archivos nuevos en el target: `src/platform/audio.cpp`,
   `third_party/stb/stb_vorbis.c`.
2. **Inclinación (tilt)**: el tutorial pide inclinar; el teclado (←/→, A/D) ya alimenta
   `ASensorEventQueue_getEvents`. Verificar el signo jugando (`SJF_TILT_INVERT`).
3. **Redimensionar ventana**: el tamaño de superficie sigue al tamaño de ventana, pero el juego no
   recibe `onNativeWindowResized`. Opción robusta: superficie fija 540×960 + FBO escalado.
4. El volumen de pico llega a ~0 dBFS cuando coinciden música y efectos; si satura, bajar la
   ganancia maestra en `device_cb`.
5. El bucle caliente `callbackPump`/`pollAdCaching` (~40k JNI/s) ya no tiene fugas, pero gasta CPU:
   se podría dormir 1 ms en ese hilo o devolver antes desde el stub.
