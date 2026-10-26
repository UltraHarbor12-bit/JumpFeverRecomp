# Sonic Jump Fever — Análisis de ingeniería inversa y plan de port a PC

**Proyecto:** Jump Fever Recomp · **Fecha:** 19 de octubre de 2026 · **APK analizado:** `sonic-jump-fever-1-6-1.apk` (v1.6.1, 43 MB)
**Alcance:** proyecto personal, sin ánimo de lucro, sin distribución de ningún material con copyright. El port final cargará los assets desde el APK propio del usuario.

---

## 1. Resumen ejecutivo

| Aspecto | Conclusión |
|---|---|
| Arquitectura del juego | **100 % nativo**: todo el motor y la lógica viven en `libsonicjumpfever.so` (C++ con EASTL, namespace `sl`). La capa Java es solo un shell de plataforma (anuncios, compras, red, logros). |
| De compilabilidad | **Muy favorable**: el ELF ARM64 exporta **10.958 símbolos C++ con nombres** (`.dynsym` sin depurar). No hay ofuscación ni anti-debug. |
| Assets | Contenedor `.sla` **rotado por completo** (spec abajo), banco de sonidos `.snd` **rotado**, localización `.loc` **rotada**, configs de gameplay en **texto plano**. Texturas `.tex`: contenedor zlib extraído; cabecera interna casi deducida (falta confirmar con el código del motor). |
| Estado | 1.161 archivos extraídos y verificables · 176 efectos de sonido convertidos a WAV · 7 idiomas decodificados · JADX decompilado (5.790 clases) · herramientas de extracción reproducibles en `tools/`. |
| Estrategia de port | Reimplementación del motor en C++ nativo **compatible con los assets originales** (mismo enfoque que los ports decomp de la comunidad Sonic), guiada por la decompilación Ghidra del binario original. |

---

## 2. Estructura del APK

```
AndroidManifest.xml        (binario; decodificado con JADX)
classes.dex (8.6 MB)       capa Java: com.sega.sonicjumpfever + librerías de terceros
classes2.dex (4.7 MB)      (MoPub, Fyber, Parse/Bolts, Dagger, GMS, Facebook, ExoPlayer…)
lib/arm64-v8a/libsonicfever.so  ← EL JUEGO (5.97 MB, ELF64 AArch64)
lib/armeabi-v7a/, lib/armeabi/  variantes 32-bit (no necesarias para el análisis)
assets/                    61 archivos, 38.4 MB: .sla, .snd, .loc, .m4a, png
res/, resources.arsc       iconos y recursos de UI Android
```

Permisos/manifest destacados: `glEsVersion 0x20000` (**OpenGL ES 2.0** obligatorio), soporte de texturas comprimidas **ETC1**, `touchscreen.multitouch.distinct`, **acelerómetro** (control por inclinación), INTERNET, BILLING, CHECK_LICENSE, GCM (push).

---

## 3. Capa Java (decompilada con JADX 1.5.6 → `extracted/jadx/`)

`Loader extends NativeActivity` y hace `System.loadLibrary("sonicjumpfever")`. El 100 % del gameplay es nativo; Java solo proporciona estos servicios:

| Servicio | Clases Java | Qué hacer en PC |
|---|---|---|
| Ciclo de vida / UI Android | `Loader` (immersive mode, orientación vertical forzada) | Reemplazar por la plataforma PC |
| Anuncios | `AndroidAds`, `mopub/MoPubAdaptor`, Fyber | Stub/desactivar |
| Compras | `BillingPlay`, `BillingServiceNativeCallbacks`, `playUtils/CryptoLib` | Stub (tienda local si se desea) |
| Google Play Games | `GooglePlayServices` (logros, leaderboards) | Stub offline |
| Facebook | `network/FacebookManager` (amigos, invitaciones) | Stub |
| HTTP | `network/HTTPRequest` (callbacks nativos por JNI), `URLReader`, `DownloadFilesTask`, `Softlight` | Stub local (el juego está muerto: los endpoints de SEGA ya no existen) |
| Música | `musicplayer` (MediaPlayer → `*.m4a` con crossfade/volumen) | Reproducir los m4a con miniaudio/similar |
| Push / notificaciones | `push/PushNotifications`, `LocalNotificationScheduler` | Eliminar |
| Red | `checkNetwork` | Devolver siempre conectado o configurable |

**Superficie JNI completa** (los métodos `native` que el binario exporta — grep exacto en `extracted/jadx/sources/com/sega/sonicjumpfever/`):

- `Loader.buildType()`, `Loader.triggerBack()`
- `BillingServiceNativeCallbacks.` { `PaymentFailed`, `ProductInfoFail`, `ProductInfoSuccess`, `ProvideContent`, `ProvideReward`, `RemoveContent`, `RestorePurchaseFailed`, `RestorePurchaseSuccess`, `checkBillingSupportCallback`, `requestDirectPayment` }
- `HTTPRequest.` { `prepareRequestNative`, `requestSentNative`, `dataReceivedNative`, `responseReceivedNative`, `requestCompletedNative`, `requestFailedNative`, `releaseRequestNative` } (todos con `long handle` → objeto C++ `HTTPRequest` en el lado nativo)
- `FacebookManager.` { `onGetFriendCallback`, `onGetFriendsCompleteCallback`, `onGetUserDetailsCallback`, `onInviteFriendsCompleteCallback`, `onInviteSentCallback`, `onSDKInitialisedCallback`, `onSessionStateCallback` }
- `checkNetwork.isConnectedCallBack`, `DownloadFilesTask.fetchFileTaskFinished`, `MoPubAdaptor.adActive`, `NetworkNativeCallbacks.fetchDownloadedImage`, `LicenseListener.{getListenerName,sendData}`, `CryptoLib.addPurchase`, `SJRewardDelegate.unlockedRewardCallBack`

Conclusiones: (a) la lógica de red/tienda vive en C++ y llama a Java solo como transporte — en PC se implementa directamente en C++; (b) no hay nada crítico del gameplay en Java.

---

## 4. Binario nativo `libsonicjumpfever.so` (ARM64)

**ELF64 AArch64, ET_DYN (shared object).** Secciones clave: `.text` 4.20 MB, `.rodata` 129 KB, `.eh_frame` 405 KB, `.rela.dyn` 209 KB.

- **`.dynsym`: 10.958 símbolos definidos + 231 imports.** Nombres C++ completos (mangled). El `.symtab` está ausente, pero `.dynsym` cubre prácticamente todas las funciones del motor.
- **Bibliotecas requeridas (DT_NEEDED):** `liblog, libandroid, libEGL, libGLESv2, libGLESv1_CM, libOpenSLES, libstdc++, libm, libc, libdl`.
- **APIs Android usadas (imports) = inventario exacto del shim de plataforma para PC:**
  - Gráficos: **EGL** (`eglGetDisplay/Initialize/ChooseConfig/CreateWindowSurface/MakeCurrent/SwapBuffers?/QuerySurface/Destroy*`), **GLESv2** (+ `GLESv1_CM` — probablemente camino legacy no usado en HD)
  - Audio: **OpenSL ES** (`slCreateEngine`, `SL_IID_ENGINE/PLAY/BUFFERQUEUE/VOLUME/PLAYBACKRATE`)
  - Input: `AInputQueue_*`, `AMotionEvent_*` (multitáctil), `ALooper_*`
  - Ventana: `ANativeActivity_*`, `ANativeWindow_setBuffersGeometry`
  - Sensores: `ASensorManager_*`, `ASensorEventQueue_*` (**acelerómetro** = inclinar en PC → teclado)
  - Config: `AConfiguration_*` (idioma/país → para `.loc`)
  - Logs: `__android_log_print`
- **Motor propio** (namespace `sl`, con EASTL = Electronic Arts STL, herencia Hardlight/ex-EA):
  - `slCreateTexture(unsigned, unsigned, sl::Colour)` — creación de texturas (¡firma con ancho/alto/tipo — con esto se confirma la cabecera `.tex`!)
  - `slSetResourcePath`, `slGetLocalStoragePath`, `slIsLowMemoryDevice`, `slGetDeviceFormFactor`, `slGetSystemTimer`, `slSystemTimerDeltaToSeconds`
  - Subsistemas visibles por símbolos/strings: `Global::leaderboardManager`, `StatTracker` (leaderboards, rewards), `ThreadNetworkTask`, `FetchFileThreadTask`, `HTTPRequest` C++, `openURL/fetchURLTo`, `moveImageToCameraRoll`, `performCheckConnectedToNetwork`
  - Existe un `main()` (0x113820, 0x6bc bytes) — herencia multiplataforma del motor (probable compilación no-Android del mismo código base)
  - Créditos embebidos: `<h>HARDLIGHT</h>`, `<t>To all at SEGA</t>` (formato de texto enriquecido propio)
  - Formato de física/serialización con strings tipo `jd.localAnchorA.Set(%.15le…)` (juntas tipo motor físico; confirmar en Ghidra)
  - Contenido descargable referenciado: `playerextra_vector.sla`, `playerextra_rouge.sla`, `player.snd` (Vector y Rouge no vienen en el APK — eran DLC/servidor)

**Volcados listos para Ghidra:** `extracted/analysis/.dynsym_exports.txt` (símbolo→dirección→tamaño), `.dynsym_imports.txt`, `strings_arm64.txt` (15.665 strings únicas).

---

## 5. Formatos de asset — especificaciones reversadas

Todas las herramientas en `tools/` (Python 3, sin dependencias más allá de pyelftools para el ELF). Varints = **LEB128** little-endian base-128 en todos los formatos.

### 5.1 `.sla` — contenedor universal (SPEC COMPLETA, verificada al 100 %: 27/27 archivos, 0 bytes residuales)

```
Offset  Campo
0x00    magic  3D 4F 26 44  ("=O&D")
0x04    u8     version (4)
0x05    varint entry_count
        entradas × entry_count:
          varint name_len
          bytes  name          (p.ej. "zone.0.tex", "player.ani", "events.json")
          varint payload_len
          bytes  payload       (len exacta — verifica el parseo)
```

El payload depende de la extensión:
- `.json` / `.xml` → **texto plano crudo** (sin zlib)
- `.tex` → registro binario (§5.4)
- `.snd` → contenedor de sonido embebido (§5.2)
- `.set` / `.ani` / `.par` → serializador de objetos del motor (empieza con varint timestamp `a3 31 26 06…` + refs por nombre a otros entries; **pendiente de mapear con Ghidra** — es el formato que define sprites, animaciones y plataformas)

### 5.2 `.snd` — banco de efectos de sonido (SPEC COMPLETA)

```
magic E2 06 B1 5B
u8 version (1)
registros hasta EOF:
  [varios bytes: id/hash del sonido — pendiente de nombrar]
  81 22                       (tag de registro)
  varint sample_rate          (vistos 11025 y 22050 Hz)
  varint 0x80000000|dsize     (bit 31 = flag; dsize = bytes PCM)
  varint zlib_len
  bytes zlib → PCM 16-bit mono (little-endian, signed)
```

Extraídos: **176 WAV** en `extracted/assets/snd/` (sfx.snd 76, sfx-game.snd 56, sfx-frontend.snd 44, 6 por personaje en sfx_*.sla). Un registro final de sfx-frontend usa otra codificación (error "unknown compression method") — pendiente menor.

### 5.3 `.loc` — localización (SPEC COMPLETA + HASH CONFIRMADO)

```
magic D9 6D B1 FB
u32 count                    (582)
tabla × count: { u32 hash_id, u32 offset }
blob: { u32 blob_len, strings UTF-8 terminadas en NUL }
offsets relativos a blob+4 (blob[0:4] = "loc:missingEntry" es la cadena 0)
```

7 idiomas decodificados (`extracted/assets/loc/*.txt`): de, en, es, fr, it, pt-br, ru.
**Función de hash confirmada en el binario (`0x2fb3f8` / `0x322e40`):** **FNV-1 de 32 bits estándar** (multiplicar por la prima antes del XOR):
- `offset_basis = 0x811c9dc5` (`2166136261`)
- `prime = 0x01000193` (`16777619`)
- Por cada byte `c` de la cadena ASCII: `h = ((h * 0x01000193) & 0xFFFFFFFF) ^ c`
- Esta misma función FNV-1 se usa en todo el motor (`sl`) para IDs de localización (`.loc`), nombres de controles UI, eventos y constantes mágicas de formatos (`"SLTEX"` → `0x123ba722`).

### 5.4 `.tex` — texturas (SPEC COMPLETA, verificada contra `sl::loadTextureDataFromTex` @ `0x322d54` y `sl::loadTextureData` @ `0x322a0c`)

```
Offset / Tipo        Campo
varint u32           magic = 0x123ba722 (FNV-1("SLTEX"), codificado en LEB128 como: a2 fc e6 90 01)
u8                   version = 1
u8                   format (TextureFormat::Enum, 0..15):
                       0x0b (11) = RGBA4444 16-bit (GL_RGBA / GL_UNSIGNED_SHORT_4_4_4_4 = 0x8033)
                       0x0c (12) = RGBA5551 16-bit (GL_RGBA / GL_UNSIGNED_SHORT_5_5_5_1 = 0x8034)
                       0x0d (13) = RGB565   16-bit (GL_RGB  / GL_UNSIGNED_SHORT_5_6_5   = 0x8363)
                       0x0e (14) = RGBA8888 32-bit (GL_RGBA / GL_UNSIGNED_BYTE          = 0x1401)
                       0x0f (15) = ETC1     4-bpp  (GL_ETC1_RGB8_OES                    = 0x8D64)
u8                   flags (bits 0..2 = orientación/rotación del atlas aplicada por 0x322764)
u16 (LE)             width  (uint16_t little-endian directo, p.ej. 0x0100 = 256, 0x0200 = 512, 0x0400 = 1024)
u16 (LE)             height (uint16_t little-endian directo)
varint u64           0x80000000 | raw_size (bit 31 indica compresión zlib; bits 0..30 = tamaño descomprimido)
varint u64           zlib_size (solo presente si bit 31 estaba activo)
bytes[zlib_size]     stream zlib → texels crudos (ETC1 o RGBA según format)
```

Nota clave descubierta al decompilar `sl::StreamReader` (`0x320f84`..`0x321088`): `readUInt8` y `readUInt16` leen **1 y 2 bytes crudos little-endian**, mientras que `readUInt32`, `readUInt64` y `readLength` usan codificación **LEB128 (varint)**. Por eso `width` y `height` (ambos `u16`) aparecían en los volcados previos como pares `(0x00, 0x01/0x02/0x04)`.

### 5.5 `.m4a` — música (sin trabajo): contenedor MP4/AAC estándar (`ftyp mp42`), 10 pistas (frontend, fever, 4 zonas ×2 actos aprox., fanfarrias, resultados).

---

## 6. Contenido extraído y datos de gameplay

`extracted/assets/` — inventario: 4 zonas (green_hill, blue_sky, jungle, mechanical) con texturas de fondo en 4 capas de parallax + enemigos (crabmeat, buzzer, buzz_sniper, motobug, batbrain, spinner, mine, nebula, bubbles, bom, spikes, bigbom, batbot…) y sus `.ani`; 7 personajes (player + playerextra: sonic, tails, knuckles, amy, blaze, shadow, silver); frontend; fever; partículas (**804** efectos `.par` nombrados); fuentes (3 por idioma); splash; settings.

**Configs de gameplay en texto plano** (`extracted/assets/settings/`) — el diseño del juego entero:

- `settings.xml` (51 KB): puntuación (scoreRing=5, perfectBonus=5000, multiplicador máx 32…), frenzy (timeTotal=40, multiplicador 1.5), cámara, energía (5, recarga 1500 s), exaltaciones (Nice→Awesome), telequinesis de Silver (radios/velocidades), modo infinito, audio (volúmenes, crossfade)…
- `store.json` (36 KB): catálogo completo de la tienda (productos, precios, páginas)
- `ranks.xml`: rangos y recompensas por puntuación
- `spin.json`: ruleta de premios con pesos
- `competition.json`: torneos semanales (configuración de ligas)
- `frenzy.xml` / `events.json`: niveles de frenzy / eventos

Esto permite reimplementar el balance del juego **exactamente igual al original** leyendo las mismas configs.

---

## 7. Arquitectura del port propuesta

**Enfoque recomendado: motor C++ nuevo compatible con los assets originales** (estilo Sonic 1/2 decomp-port). Motivos frente a las alternativas:

| Alternativa | Veredicto |
|---|---|
| Recompilación estática ARM64→x64 | Máxima fidelidad, pero requiere escribir un recompilador ARM64→C (meses de tooling) y una shim de Android/bionic enorme. No existe tooling maduro off-the-shelf para ARM64 estático. |
| Emulación dinámica (qemu-user/unicorn) | Arranque rápido, rendimiento y depuración pobres para un juego de acción. |
| **Reimplementación guiada por decomp (elegida)** | El binario está sin ofuscar con 10.958 símbolos, las configs son texto plano y los assets ya se extraen → se puede reconstruir por subsistemas con verificación continua (render→audio→assets→gameplay). Es el estándar de la comunidad para ports personales. |

**Capas del port (carpeta `port/` en fases futuras):**

1. **Plataforma PC**: SDL2 (ventana/input/tiempo) + OpenGL 4.x core con carga de shaders equivalentes a los GLES2 del original + miniaudio (PCM + m4a/AAC vía decoder). Input: teclado ←→ touch (el juego original: tap izq/der para girar, inclinación opcional por acelerómetro).
2. **Carga de assets**: parsers `.sla/.snd/.loc/.tex` (portar los de `tools/` a C++), lectura directa desde el APK del usuario (zip) o carpeta extraída.
3. **Runtime del motor**: texturas/atlas, sprites y animaciones (`.ani/.set` — spec tras Ghidra), partículas (`.par`), audio posicional simple, localización, configs XML/JSON.
4. **Lógica de juego**: estados (frontend, juego, fever, resultados), física de plataformas verticales, enemigos, power-ups, progreso/guardado local (sustituyendo el guardado en la nube).
5. **Stubs online**: leaderboard local, tienda desactivada o local, sin anuncios/login.

**Dependencia clave por delante:** decompilación Ghidra de (a) `slCreateTexture` + cargador `.tex`, (b) serializador `.set/.ani/.par`, (c) game loop y máquina de estados, (d) hash de `.loc`.

---

## 8. Estado del entorno y próximos pasos

- **Listo:** REA CLI 6.7.0 (npx) · JADX 1.5.6 (`tools/jadx/`) · JDK 21 (`tools/jdk/`) · Ghidra 12.1.4 (`tools/ghidra/`, descargándose al redactar esto) · pyelftools · extractores Python (`tools/sla_extract.py`, `tools/sla_probe.py`, `tools/elf_dump.py`, `tools/tex_analyze.py`)
- **Siguiente sesión:** importar `libsonicjumpfever.so` a Ghidra headless (proyecto en `extracted/ghidra_proj/`), exportar pseudocódigo de los subsistemas anteriores, confirmar spec `.tex`, romper `.set/.ani/.par` y el hash `.loc`, y arrancar el esqueleto C++ del port (ventana + carga de assets + render de una textura como primer hito verificable).

### Mapa de directorios de trabajo

```
extracted/apk/          APK descomprimido íntegro
extracted/jadx/         fuentes Java decompiladas (5.790 clases)
extracted/assets/       assets extraídos y convertidos (1.161 archivos + índice _index.json)
extracted/analysis/     volcados: símbolos ELF, imports, strings
tools/                  herramienta de análisis (Python) + jadx + jdk + ghidra
docs/                   esta documentación
```
