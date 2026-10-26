# HANDOFF — Sonic Jump Fever → PC (proyecto «Jump Fever Recomp»)

**Documento de entrega para delegación.** Fecha: 23 oct 2026. Léelo entero antes de tocar nada:
contiene el estado exacto, los comandos, las rutas y las trampas del entorno.

---

## 1. Qué es este proyecto

Port a PC de **Sonic Jump Fever 1.6.1** (Android, SEGA/Hardlight 2014) mediante:

- **dynarmic** (JIT ARM64→x86_64, el de yuzu) ejecutando el `libsonicjumpfever.so` ORIGINAL (ARM64, sin modificar), y
- **capa de compatibilidad nativa estilo Wine**: JNI fake, libc/libm/libandroid/OpenSL/GLES2 reimplementados como handlers nativos.

**Marco legal acordado con el usuario:** proyecto personal, sin ánimo de lucro, sin distribuir nada.
El port carga el `.so` y el APK del propio usuario (`port/game/`). Los servidores del juego están
muertos desde hace años: toda la red se responde en modo offline/connected.

**APK de referencia:** `sonic-jump-fever-1-6-1.apk` (raíz del repo, 43 MB).

---

## 2. ESTADO ACTUAL (verificado en `extracted/analysis/boot_run91.log`)

**EL MOTOR ARRANCA Y RENDERIZA A 60 FPS** (`eglSwapBuffers #720+`). Secuencia que ya funciona:

```
onCreate → ventana SDL + superficie EGL → hilo del motor (android_main)
  → initGame(): gate AppContext (0x5c4298) + ZipFile::openArchive("game/base.apk") ✓
     (initGame usa PATRÓN DE REINTENTO: 1ª pasada crea contexto+zip y devuelve false;
      el motor la reintenta hasta que todo está listo — NO la llames manualmente)
  ├─ appPreInitialise(): crea TODOS los managers con sus constructores reales
  ├─ createAudio(): OpenSL ES completo (OutputMix, AudioPlayers, SetPlayState(PLAYING))
  ├─ createNetwork() ✓
  ├─ slInitialise(): flag gráficos @0x5c4714=1 ✓ shaders compilados ✓
  └─ appInitialise() + ads::init()
→ AppLoadingScreen superada; 3 fuentes .sla; 804 partículas; store.json; savegames
  (profile0.dat, localsettings.dat en game/data/) ✓; 13 amigos cargados ✓
→ texturas subidas (RGBA4444/RGBA8888 + decodificador ETC1 software) ✓
→ BUCLE DE RENDER a 60 FPS: glBufferSubData → glDrawElements → eglSwapBuffers ✓
→ screenshots capturadas: extracted/analysis/shot_1.bmp, shot_300.bmp, shot_600.bmp
→ input: SJF_AUTOTAP_MS inyecta taps al centro (270,480) cada N ms (11 taps en run91)
```

Pantalla actual: banda azul (y≈446-534) con contenido blanco centrado, resto negro —
pantalla de carga/diálogo del motor. Los amigos ya cargan (frontend data).

### ⚠️ BLOQUEO ACTUAL (lo primero a resolver)

**Los taps se encolan pero el motor nunca los lee.** `AInputQueue_getEvent` tiene **0 llamadas**
en run91 pese a 11 autotaps. Causa: `AInputQueue_attachLooper` (libandroid.cpp ~línea 182)
guarda `g_input_ident/g_input_data` pero **`ALooper_pollAll` no consulta el estado del input**:
solo sondea los fds registrados vía `ALooper_addFd` (pipes) + sensores.

**Fix propuesto** (concreto): en `ALooper_pollAll` (libandroid.cpp, bucle PeekNamedPipe), llamar
también a `input_poll_ready(ident, data)` (función estática del mismo archivo, ya existe) y si
devuelve true → escribir outFd/outEvents/outData con esos valores y retornar `ident`. Con eso el
hilo del motor despertará, llamará `AInputQueue_getEvent` y consumirá el FIFO.
Verificar después en el log: `AInputQueue_getEvent` > 0 y `AMotionEvent_getAction` = 0 (DOWN).

---

## 3. Mapa exacto de archivos del port (`port/`)

| Archivo | Contenido | Notas |
|---|---|---|
| `src/runtime/jit.cpp` | Wrapper dynarmic A64: 1 JIT por hilo, SVC-trampolines, **cascade unwinder**, ExclusiveMonitor, pool `nested_pool` para llamadas anidadas, volcados de diagnóstico (`jit_dump_threads`, `jit_backtrace_here`) | `t_entry_sp`/`t_resilient`/`t_unwind_*` son thread_local declarados ANTES de `Callbacks` |
| `src/runtime/guest_memory.cpp` | Región huésped 32 GiB @0x100000000, **página nula shadow** (lecturas→cascada, escrituras→absorbidas, código→`ret`), heap guest next-fit O(1) (`g_heap_rover`), coalescido bidireccional | No tocar la semántica de `kHeapHeaderSize` (bug #4 del doc 04) |
| `src/runtime/guest_abi.cpp` | Motor varargs AAPCS64 (registros x/v + pila + **va_list struct**) usado por printf/logcat/vsnprintf | La va_list AArch64 se lee en `gr_top+offs` ANTES de `offs+=8` |
| `src/runtime/host_calls.cpp` | Registro nombre→handler; cada handler tiene un trampoline `svc #imm; ret` | |
| `src/runtime/elf_loader.cpp` | Carga ELF64 + relocalizaciones + binding de imports (hosts→trampolines, datos→blobs; `SL_IID_*` → `sl_bind_iid`) | |
| `src/dependencies/libc.cpp` | stdio/stdlib/unistd/time/fd-table (FILE* + pipes), **VFS** (`vfs_resolve`: assets/, fallback exe-dir, fallback `hd-`), errno por hilo, mmap, red offline, gmtime **con puntero deref** | `windows.h` incluido; `exe_dir()` vía GetModuleFileNameA |
| `src/dependencies/libandroid.cpp` | AConfiguration, ALooper (**PeekNamedPipe polling**), AInputQueue FIFO (TouchEvent deque), ASensor (tilt sintético), ANativeActivity/Window stubs | **AQUÍ ESTÁ EL FIX DEL BLOQUEO** (§2) |
| `src/dependencies/libgl.cpp` | EGL (surface/context handles reales+MakeCurrent), GLES2→OpenGL 2.1 (66 funcs), **decodificador ETC1**, saneador GLSL ES (precision/#version), glGetString identidad GLES2, screenshots glReadPixels→BMP | No cachear NULL en `glproc` |
| `src/dependencies/libopensl.cpp` | Modelo de objetos OpenSL (vtables guest): engine/outputmix/audioplayer + interfaces PLAY/BQ/VOLUME/RATE; slots empíricos 2014 (CreateOutputMix=7, CreateAudioPlayer=2/3) | `sl_bind_iid`: el import SL_IID_* es una VARIABLE puntero → blob contiene puntero a SLInterfaceID única |
| `src/dependencies/liblog.cpp` | `__android_log_print` + **`__android_log_vprint` con va_list** (los mensajes FATAL del motor se leen aquí) | |
| `src/dependencies/pthread.cpp` | pthread/mutex/cond/once/sem sobre primitivas host | |
| `src/dex/jni_env.cpp` | JNI fake: JavaVM + tabla de 233 slots; despacho de `Call*Method(V)` **por nombre de clase+método**; `Softlight.isConnected` dispara el callback nativo `isConnectedCallBack(true)` via `guest_call_nested` | `jni_table_names.h` generado por `tools/gen_jni_names.py` desde `port/third_party/ndk/jni.h` |
| `src/engine/boot.cpp` | Secuencia de arranque: carga ELF → módulos → JNI_OnLoad → onCreate (activity sintética) → **ventana temprana + onNativeWindowCreated** → onStart/onResume/onWindowFocusChanged → **autotap** → frame loop con muestreo de PCs y probes | Contiene el hook `SJF_AUTOTAP_MS` |
| `src/platform/window.cpp` | SDL2: ventana 540×960, contexto GL 2.1 compat, **suelta el contexto tras crearlo** (WGL no permite 2 hilos), screenshots glReadPixels→BMP | |
| `game/` | `libsonicjumpfever.so` (copia), `base.apk` (copia), `assets/` (61 archivos extraídos del APK), `data/` (savegames funcionales) | Rutas resueltas relativas al **exe** |

---

## 4. Toolchain y comandos exactos

**Entorno:** Windows, PowerShell 5.1 (sin `&&`, sin heredocs — escribir scripts Python como archivos),
usuario Administrator. Existe la unión `C:\sjf` → carpeta del proyecto (el linker MinGW no tolera
espacios en rutas).

```powershell
# Configurar (ya configurado; solo si se borra port/build)
C:\sjf\tools\cmake\cmake-4.4.4-windows-x86_64\bin\cmake.exe -S C:\sjf\port -B C:\sjf\port\build -G Ninja `
  -DCMAKE_C_COMPILER=C:/sjf-mingw/bin/gcc.exe -DCMAKE_CXX_COMPILER=C:/sjf-mingw/bin/g++.exe `
  -DCMAKE_ASM_COMPILER=C:/sjf-mingw/bin/gcc.exe -DCMAKE_MAKE_PROGRAM=C:/sjf/tools/ninja/ninja.exe `
  -DCMAKE_BUILD_TYPE=Release -DBoost_INCLUDE_DIR=C:/sjf-boost/boost_1_86_0

# Compilar
C:\sjf\tools\cmake\cmake-4.4.4-windows-x86_64\bin\cmake.exe --build C:\sjf\port\build --parallel 8

# Ejecutar (45 s con watchdog; screenshot en el swap 60; autotap cada 2000 ms)
C:\sjf\port\build\sjfport.exe C:\sjf\port\game\libsonicjumpfever.so --timeout 45 `
  --shot C:\sjf\extracted\analysis\shot.bmp --shot-swap 60
# (env SJF_AUTOTAP_MS=2000 activa el autotap; ejecutar con cwd=C:\sjf\port o rutas exe-relativas)
```

**Herramientas instaladas:** MinGW-w64 GCC 16.2 UCRT en `C:\sjf-mingw` (¡copiado ahí a propósito!),
CMake portable + Ninja + Boost headers en `tools/`, SDL2 2.32.10 en `tools/sdl2/...` (include/SDL2),
JADX 1.5.6 en `tools/jadx` (fuentes Java en `extracted/jadx`), Ghidra 12.1.4 en `tools/ghidra`
(lanzar **vía bash de MSYS** con `APPDATA`+`JAVA_HOME` exportados; proyecto analizado en
`extracted/ghidra_proj`), dynarmic 6.7 en `port/third_party/dynarmic` (mirror yuzu-mirror;
**merryhime/dynarmic ya no es público**).

---

## 5. Conocimiento de ingeniería inversa clave (confirmado en runtime)

### Formato `.sla` (contenedor universal)
```
magic "3D 4F 26 44"; u8 version(4); varint count;
entradas × count: varint name_len; name; varint payload_len; payload
```
- `.json/.xml` texto plano · `.tex`/`.snd` binarios · `.set/.ani/.par` serializador propio del motor.

### Formato `.tex` (verificado con `sl::loadTextureDataFromTex` @0x322d54)
```
varint magic (FNV1("SLTEX")=0x123ba722; bytes a2 fc e6 90 01)
u8 version; u8 format (0x0b RGBA4444, 0x0c RGBA5551, 0x0d RGB565, 0x0e RGBA8888, 0x0f ETC1);
u8 flags; u16 LE width; u16 LE height; varint (0x80000000|raw_size); varint zlib_len; zlib data
```

### FNV-1 32 bits (hash del motor): `h = (h*0x01000193) ^ byte`, h0=0x811c9dc5
IDs de strings `.loc`, eventos de UI, y `FNV1("SLTEX")`.

### `.loc` (localización): magic `D9 6D B1 FB`, u32 count, tabla {u32 hash, u32 off},
blob {u32 blob_len, strings NUL}; offsets relativos a blob+4. 582 strings × 7 idiomas ya extraídas.

### Direcciones/símbolos críticos (guest; base huésped = 0x100000000)
| Dirección | Qué es |
|---|---|
| 0x2852b8 | `android_main` (hilo del motor; su loop llama appUpdate/appRender) |
| 0x28478c | `initGame()` — MAESTRO: gate → appPreInitialise → createAudio → createNetwork → slInitialise → appInitialise → ads::init (PATRÓN DE REINTENTO, no llamar a mano) |
| 0x3363ec | `appPreInitialise()` — crea TODOS los managers (DownloadManager, SonicJumpConnectionManager→escribe el holder del perfil) |
| 0x2ffc5c | `slInitialise()` — gráficos; escribe flag 0x5c4714=1 y estado en 0x5c4718 |
| 0x603220 | `network::DownloadManager::s_instance` |
| 0x602fc0 | `network::ConnectedProfileManager::s_instance` |
| 0x5cbed0 | **holder del perfil** (PlayerProfile/ConnectedProfileManager; scaffold actual: impl zeroed con [impl+0xb78]→blobo tiempo, [impl+0xb80]→blobo contador) |
| 0x5c4298 | AppContext (gate de initGame; lo crea initGame mismo) |
| 0x5c4714 | flag "gráficos listos" (lo escribe slInitialise) |
| 0x2fa568 | `slCheckError(bool, const char*, ...)` — los aborts FATAL del motor pasan por aquí |

### Superficie JNI (exports `Java_com_sega_sonicjumpfever_*`)
32 métodos: Loader (buildType/triggerBack), checkNetwork.isConnectedCallBack(bool),
DownloadFilesTask.fetchFileTaskFinished, BillingServiceNativeCallbacks.* (10),
MoPubAdaptor.adActive, FacebookManager callbacks (7), LicenseListener/CryptoLib (RegisterNatives en
JNI_OnLoad), SJRewardDelegate.unlockedRewardCallBack, NetworkNativeCallbacks.fetchDownloadedImage.

### Clases Java que la capa fake debe servir (ya usadas por el motor)
Loader (getRotation/getLanguage/getFilesDir/getApkFileName/getPlayerName/isTabletDevice),
Softlight (isConnected/getData/startThread/rateThisApp), musicplayer.*,
AndroidAnalytics.logEvent*/logParametersHLSDK, HTTPManager/HTTPRequest, FacebookManager,
GooglePlayServices, push.*, BillingPlay/BillingServiceInterface, java/io/File,
java/util/HashMap, android/app/NativeActivity.

---

## 6. Próximos pasos (prioridad)

1. **Entregar el input al motor** (bloqueo actual, §2): en `ALooper_pollAll` llamar
   `input_poll_ready()` y retornar el ident del input cuando haya taps pendientes. Verificar:
   `AInputQueue_getEvent` > 0 en el log, y `AMotionEvent_getAction` 0/1 (DOWN/UP).
2. **Identificar la pantalla actual**: los 3 screenshots (shot_1/300/600.bmp) muestran una banda
   azul con contenido blanco centrado (y≈446-534). El reconocimiento vía API falló (token 403);
   alternativas: comparar screenshots consecutivos (¿hay animación?), correlacionar con el
   estado del logcat (friends=frontend data), o OCR offline (tesseract no instalado).
3. **Raton → táctil real**: `platform_pump()` (window.cpp) ya recibe SDL events; mapear
   SDL_MOUSEBUTTONDOWN/UP/MOTION → `g_input_fifo` (TouchEvent{action,x,y}) escalando 540×960.
   Con eso el usuario puede jugar de verdad y el autotap se jubila.
4. **Audio out**: `SL BufferQueue::Enqueue` traga el PCM (16-bit, rate del data source); conectar
   a SDL_Audio (o miniaudio). La música (m4a) va por `musicplayer` Java → decode AAC o usar los
   WAV de referencia en `extracted/assets/snd/`.
5. **Limpieza**: retirar watchpoints/probes de diagnóstico (WATCH/WATCH2/null-page logs/probe:)
   una vez el flujo sea estable; dejarlos tras un flag `--debug`.

---

## 7. Trampas del entorno (leer sí o sí)

1. **PowerShell 5.1**: sin `&&`, sin heredocs, los `python -c "..."` con comillas anidadas rompen
   → **escribir scripts Python como archivos** en `tools/` y ejecutarlos.
2. **CRLF**: los parches con replace deben leer con `io.open(..., newline=None)` y escribir con
   `newline='\n'`.
3. **MinGW linker + espacios**: el proyecto se compila vía la unión `C:\sjf` y el toolchain vive
   en `C:\sjf-mingw` (copiado). No mover ni renombrar.
4. **dynarmic**: clonar solo de `yuzu-mirror/dynarmic` (el original está privado). Externals
   bundled (`DYNARMIC_USE_BUNDLED_EXTERNALS=ON`), `CMAKE_POLICY_VERSION_MINIMUM` ya parcheado en
   los externals (cmake 4.x).
5. **El juego reintenta initGame**: no llamar `initGame`/`appPreInitialise`/`slInitialise` desde
   el shim (el doble-init aborta con "Invalid graphics operation").
6. **Los hilos guest**: 1 JIT por hilo; las llamadas anidadas usan el `nested_pool`; el volcado
   de hilos (`jit_dump_threads`) es el diagnóstico principal — los ThreadState anidados NO se
   registran en `g_threads` (solo los dos principales).
7. **La página nula**: lecturas → cascade unwind; escrituras → absorbidas; código → `ret`.
   Un "spin" infinito silencioso casi siempre es un bucle de lista en la página nula.
8. **logcat**: los FATAL del motor salen por `__android_log_vprint` (implementado con va_list).
   Si el juego aborta, leer SIEMPRE el mensaje logcat antes de hipotetizar.

---

## 8. Dónde están las cosas

```
port/                      ← el port (fuente C++, CMakeLists, game/, build/)
docs/01…04, 03b/03c/03e    ← documentación histórica por hitos (léelos en orden si dudas)
extracted/apk/             ← APK descomprimido íntegro
extracted/jadx/            ← fuentes Java decompiladas (5.790 clases)
extracted/assets/          ← assets extraídos (.sla entries, WAV, .loc txt, _index.json)
extracted/analysis/        ← símbolos ELF (.dynsym_*.txt), strings, logs boot_run*.log,
                             screenshots (shot_1/300/600.bmp, first_frame.bmp)
extracted/ghidra_proj/     ← proyecto Ghidra con el .so ya analizado
tools/                     ← scripts de análisis Python (elf_dump, xref_global,
                             find_singleton_writes, callers_of, list_calls, plt_map, …)
extracted/analysis/strings_arm64.txt            ← 15.665 strings del binario
extracted/analysis/.dynsym_exports.txt          ← 10.958 símbolos con dirección+tamaño
extracted/analysis/.dynsym_imports.txt          ← los 231 imports Android
```

**Log de referencia actual:** `extracted/analysis/boot_run91.log` (735 líneas, ejecución estable).

---

## 9. Resumen de una línea para el agente delegado

> Ejecuta `C:\sjf\port\build\sjfport.exe C:\sjf\port\game\libsonicjumpfever.so --timeout 45
> --shot ... --shot-swap 300` con `SJF_AUTOTAP_MS=2000`, lee
> `docs/04-hito3-texturas-fuentes-y-red.md` y este handoff, y resuelve PRIMERO el wiring
> input→looper de `libandroid.cpp` (§2), luego ratón→táctil, luego audio SDL.
