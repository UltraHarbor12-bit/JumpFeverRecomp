# Hito 3 — Carga completa de assets, texturas, fuentes y llegada al menú principal (23 oct 2026)

## 🎉 Hito alcanzado: carga íntegra de `AppLoadingScreen` y bucle principal a 60 FPS

```
[sjf][I] glCompressedTexImage2D: decoded ETC1 1024x1024 (524288 B) -> RGBA8
[sjf][I] glTexImage2D: 256x256 fmt=0x1908 type=0x8033 data=0x30005b7a0
[sjf][I] glTexImage2D: 512x256 fmt=0x1908 type=0x8033 data=0x3000892a0
[sjf][I] glTexImage2D: 512x512 fmt=0x1908 type=0x8033 data=0x300100020
[sjf][I] glTexImage2D: 2048x2048 fmt=0x1908 type=0x1401 data=0x300200020
[sjf][I] glTexImage2D: 2048x2048 fmt=0x1908 type=0x8033 data=0x300200020
[sjf][I] glTexImage2D: 512x1024 fmt=0x1908 type=0x8033 data=0x30018bfd0
[sjf][W] logcat[SonicJump][I] store init complete
[sjf][W] logcat[SonicJump][I] loadState
[sjf][W] logcat[SonicJump][I] **********************ADS INIT*********************
[sjf][I] glCompressedTexImage2D: decoded ETC1 2048x2048 (2097152 B) -> RGBA8
[sjf][I] glCompressedTexImage2D: decoded ETC1 1024x2048 (1048576 B) -> RGBA8
[sjf][W] logcat[SonicJump][I] Adding friend #boss_metal_sonic ... #character_name_short_vector
[sjf][I] eglSwapBuffers #60
[sjf][I] eglSwapBuffers #120
[sjf][I] eglSwapBuffers #180
```

El motor supera por completo la pantalla de carga (`AppLoadingScreen`), descomprime y sube a OpenGL todas las texturas (`.tex` en formatos RGBA4444, RGBA8888 y ETC1), carga las 3 fuentes (`fonts-efigsb.sla`), parsea las 804 definiciones de partículas XML (`particles.sla`) y configuraciones (`settings.xml`, `store.json`), inicializa la tienda, el estado del perfil y la lista de amigos/rivales (`Metal Sonic`, `Eggman`, `Big the Cat`, `Sonic`… `Vector`), y entra en el bucle de renderizado continuo a 60 FPS (`eglSwapBuffers #180+`).

---

## 🛠️ Bugs críticos resueltos en esta sesión (9 en total)

| # | Subsistema | Causa raíz | Solución aplicada |
|---|---|---|---|
| 1 | **JIT / llamadas anidadas** (`port/src/runtime/jit.cpp`) | `guest_call_nested` creaba un `ThreadState ts` en la pila local y llamaba a `run_on`, que hacía `Callbacks::instance().bind(&*ts.jit)` y sobrescribía `t_entry_sp`. Al retornar el callback anidado (p.ej. `isConnectedCallBack(true)` dentro de `CallSVC`), `ts.jit` se destruía dejando `Callbacks::jit_` apuntando a memoria liberada (*use-after-free* → `0xC0000005`). | Pool `thread_local` de `ThreadState` (`nested_pool`) para llamadas anidadas + guardado y restauración de `Callbacks::bound()`, `t_entry_sp` y `t_unwind_*` en `run_on`. |
| 2 | **VFS / resolución de `.sla`** (`port/src/dependencies/libc.cpp`) | `vfs_resolve` buscaba nombres desnudos (`splash.sla`, `fonts-efigsb.sla`) solo relativos al CWD (`game/assets/`), fallando al lanzar desde la raíz del repo. | Añadidos candidatos relativos a `exe_dir() + "/../game/assets/[hd-]" + guest_path`. |
| 3 | **Corrupción de heap al coalescer** (`port/src/runtime/guest_memory.cpp`) | `guest_heap_free` coalescía hacia delante y atrás sin actualizar `prev_size` del bloque siguiente ni limpiar `magic` en cabeceras absorbidas; `guest_heap_alloc` no dividía bloques recién extendidos y `guest_heap_realloc` leía cabeceras sin mutex. Esto sobrescribía en mitad de uso la tabla hash de `sl::Font::load` (`0x2fe1d4`). | Coalescido hacia atrás primero y luego hacia delante, limpieza de `magic = 0`, actualización invariante de `after->prev_size`, división tras `heap_extend` y protección con `g_mem_mutex`. |
| 4 | **Extensión de heap exacta a 1 MiB** (`port/src/runtime/guest_memory.cpp`) | `heap_extend(need)` redondeaba `need` (en lugar de `need + kHeapHeaderSize`) a múltiplos de 1 MiB. Para texturas de exactamente 1 MiB (`0x100000` B), `usable = chunk - 32 = 0xFFFFE0 < need`, haciendo que `malloc` devolviese `nullptr` y `_Znwm` lanzase `std::bad_alloc` (`abort()`). | Redondear `total_need = need + kHeapHeaderSize` en `heap_extend`. |
| 5 | **Cuello de botella $O(N^2)$ en `malloc`** (`port/src/runtime/guest_memory.cpp`) | Al cargar los 804 XML de `particles.sla`, TinyXML realiza >50.000 asignaciones pequeñas. El escaneo *first-fit* desde `kHeapBase` recorría los 50.000 bloques en cada `malloc` (~18 s). | Cursor *next-fit* (`g_heap_rover`) en el asignador de heap: convierte la asignación en $O(1)$ amortizado (< 0,2 s para toda la carga). |
| 6 | **Monitor exclusivo ARM64** (`port/src/runtime/jit.cpp`) | Instrucciones atómicas ARM64 (`ldaxr`/`stlxr`) disparaban `assertion failed: conf.global_monitor != nullptr` en Dynarmic. | Configurado `Dynarmic::ExclusiveMonitor g_exclusive_monitor{64}` compartido con `processor_id` por hilo e implementados `MemoryWriteExclusive8/16/32/64/128` con *compare-and-swap*. |
| 7 | **Lectura fuera de rango en `glTexImage2D`** (`port/src/dependencies/libgl.cpp`) | `glTexImage2D` leía el 9.º argumento (`pixels`) con `c.x[8]`, que leía `c.v[0]` fuera del array `u64 x[8]`, pasando una dirección inválida al driver OpenGL (`igxelpicd64.dll`). | Lectura directa del 9.º argumento desde `[c.sp]` según AAPCS64. |
| 8 | **Decodificador ETC1 + ABI de `glTexParameterf`** (`port/src/dependencies/libgl.cpp`) | 1) OpenGL 2.1 de escritorio no soporta `GL_ETC1_RGB8_OES` (`0x8D64`). 2) `glTexParameterf` tenía el 3.er parámetro tipado como `GLenum` (`R8D`) en vez de `GLfloat` (`XMM2`), provocando `GL_INVALID_ENUM` (`0x500`) y dejando todas las texturas con `GL_NEAREST_MIPMAP_LINEAR` sin mipmaps (texturas incompletas = muestreo negro). | 1) Decodificador ETC1 → RGBA8 por software en `glCompressedTexImage2D`. 2) Firma corregida a `void (*)(GLenum, GLenum, GLfloat)`. |
| 9 | **`sscanf` + ABI AAPCS64 de coma flotante en `libm` / `libc`** (`port/src/dependencies/libc.cpp`, `libm.cpp`, `jit.cpp`) | 1) `sscanf` era un stub que devolvía `0`, impidiendo a TinyXML (`TiXmlAttribute::QueryIntValue`/`QueryDoubleValue`) leer todos los números de los XML. 2) `libm` (`cosf`, `sinf`, `sqrtf`, `powf`, `atan2f`, `fmodf`, `modf`, `frexp`, `pow`) y `atof` leían de `x0` y devolvían el resultado en `x0` (`c.ret`) en lugar de `s0`/`d0` (`v0`). En consecuencia, `slDrawTile` (`0x302908`) obtenía `cosf(0) = 0` y `sinf(0) = 0`, colapsando la matriz de rotación 2D de todos los sprites a área 0 (`v0 == v3`). | 1) Implementado `sscanf` completo con traducción de punteros guest→host y normalización LP64→LLP64. 2) Añadido soporte de retorno vectorial `v0` (`set_f32`/`set_f64` → `jit_->SetVector(0, ...)`) en `CallSVC` y migradas todas las funciones de `libm` y `atof` a registros `v0..v7`. |

---

## 🔬 Especificaciones de ingeniería inversa confirmadas en el binario

### 1. Función de hash del motor (`0x2fb3f8` y `0x322e40`)
El motor utiliza **FNV-1 de 32 bits estándar** (multiplicación antes del XOR):
$$\text{hash}_0 = \text{0x811c9dc5}, \qquad \text{hash}_{i+1} = ((\text{hash}_i \times \text{0x01000193}) \bmod 2^{32}) \oplus \text{byte}_i$$
Se emplea para:
- IDs de cadenas de localización en archivos `.loc`
- Identificadores de controles de UI y eventos
- Magic de cabeceras (p.ej. `FNV1("SLTEX") = 0x123ba722`)

> **Fe de erratas (hito 10):** en las hojas de personaje (`player.0.tex`, `playerextra.0.tex`) el magic
> varint vale `0x1219be22` y **no hay byte de versión**: tras el magic van `format` (u8, `0x0b` = RGBA4444),
> `flags` (u8), `width` (u16 LE), `height` (u16 LE), `0x80000000|raw_size` (varint), `zlib_size` (varint) y
> el stream zlib. Verificado al recodificar las texturas (ver docs/12).

### 2. Formato de texturas `.tex` (`sl::loadTextureDataFromTex` @ `0x322d54` y `sl::loadTextureData` @ `0x322a0c`)
| Offset / Tipo | Campo | Descripción |
|---|---|---|
| `varint u32` | `magic` | `0x123ba722` (`FNV1("SLTEX")`, codificado en LEB128 como `a2 fc e6 90 01`) |
| `u8` | `version` | `1` |
| `u8` | `format` | `0x0b` = RGBA4444 (`0x8033`), `0x0c` = RGBA5551 (`0x8034`), `0x0d` = RGB565 (`0x8363`), `0x0e` = RGBA8888 (`0x1401`), `0x0f` = ETC1 (`0x8D64`) |
| `u8` | `flags` | Bits `0..2`: orientación/rotación del atlas (transformada en CPU por `0x322764` y en UV por `slSetTextureTransform`) |
| `u16` (LE) | `width` | Ancho en píxeles (`uint16_t` little-endian directo, p.ej. `256`, `512`, `1024`, `2048`) |
| `u16` (LE) | `height` | Alto en píxeles (`uint16_t` little-endian directo) |
| `varint u64` | `raw_size_flag` | `0x80000000 \| raw_size` (bit 31 indica payload comprimido con zlib) |
| `varint u64` | `zlib_size` | Tamaño del stream comprimido |
| `bytes` | `zlib_stream` | Datos comprimidos con zlib que producen `raw_size` bytes de texels |

---

## 📊 Estado actual de los subsistemas

| Subsistema | Estado | Notas |
|---|---|---|
| **JIT ARM64→x64 (Dynarmic)** | ✅ Completo | `ExclusiveMonitor` activo, llamadas anidadas seguras (`nested_pool`), retorno escalar (`x0`) y coma flotante (`s0`/`d0`) |
| **Memoria y Heap del guest** | ✅ Completo | Coalescido bidireccional verificado + cursor *next-fit* $O(1)$ (`g_heap_rover`) |
| **VFS y carga de archivos `.sla`** | ✅ Completo | Resolución relativa al ejecutable + fallback automático `hd-<archivo>.sla` |
| **OpenGL / EGL / Texturas** | ✅ Completo | Shaders GLSL ES → 1.20, RGBA4444/RGBA8888, decodificador software ETC1, `glTexParameterf` XMM2 |
| **Fuentes y XML / JSON** | ✅ Completo | `sl::Font::load` (3 fuentes), `sscanf` variádico AAPCS64 para TinyXML, 804 partículas cargadas |
| **Red / Tienda / Amigos offline** | ✅ Completo | `isConnectedCallBack(true)` funcional, `FriendsManager::addFakeFriends` carga los 13 amigos/rivales |
| **Audio (OpenSL ES + música)** | 🟡 Stub activo | 13 reproductores OpenSL ES creados y en estado `PLAYING`; falta conectar la cola PCM/m4a al dispositivo de salida de audio |
| **Input (ratón → táctil / teclado → inclinación)** | 🟡 Pendiente | Conectar eventos de ratón/teclado de SDL2 en `window.cpp` a `AInputQueue` / `ASensorEventQueue` |
