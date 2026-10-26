# Hito 2e — ¡El motor renderiza! (22 oct 2026)

## 🎉 Hito alcanzado: pipeline de renderizado activo

```
[Sjf] GL first call: glDrawElements (fn=00007ffc...)
[Sjf] eglSwapBuffers #1
[Sjf] platform: screenshot saved to first_frame.bmp (540x960)
```

El juego ejecuta su bucle, llama a `glDrawElements`, intercambia buffers y la
captura de pantalla funciona. Los frames salen **negros** porque el juego está
atascado en la fase de conexión (ver abajo), pero **todo el pipeline funciona**.

## Arreglos de esta sesión

| # | Bloqueo | Fix |
|---|---|---|
| 1 | `slmkgmtime` con struct nulo → cascada → muerte del hilo | `gmtime(ptr)`: POSIX pasa un **puntero** a time_t — desreferenciar (el motor leía año+1900 = 0x76c de la página nula) |
| 2 | `fopen("fonts-efigsb.sla")` falla (busca sin prefijo) | VFS: fallback `game/assets/hd-<nombre>` para recursos sin ruta |
| 3 | "Invalid graphics operation" (doble init) | Eliminado el initGame manual: el motor ejecuta su propia secuencia completa |

## Cadena de inicialización del motor (verificada en runtime)

```
android_main (hilo propio, ret devuelve año+1900 leído de tm — cosmético)
  └─ initGame():
       gate *(0x5c4298): crea AppContext (0x38 B) + ZipFile::openArchive(base.apk) ✓
       ├─ appPreInitialise(): crea TODOS los managers con constructores reales
       │    ├─ DownloadManager ✓  ├─ SonicJumpConnectionManager ✓
       │    └─ (escribe el holder del perfil 0x5cbed0) ✓
       ├─ createAudio(): OpenSL ES completo ✓
       │    ├─ CreateOutputMix ✓  ├─ CreateAudioPlayer ×N ✓
       │    └─ GetInterface(PLAY/BUFFERQUEUE/VOLUME/PLAYBACKRATE) ✓
       │       SetPlayState(PLAYING) ✓  RegisterCallback ✓
       ├─ createNetwork() ✓
       └─ slInitialise(): flag 0x5c4714=1 ✓ shaders compilados ✓ glTexImage2D ✓
```

## Bloqueo actual

**Fase de conexión**: `isConnectedCallBack(true)` (nested call) se cuelga — probablemente
girando en una estructura del `ConnectedProfileManager` (cuyo constructor no existe como
símbolo: se crea inline en `createNetwork` vía `0x28fb6c`). El hilo de render no dibuja
más frames mientras tanto (estado "connecting").

**Siguiente paso**: muestrear el PC del nested call (registrar los ThreadState anidados en
el volcado) para localizar el giro exacto, o interceptar `ConnectedProfileManager` para un
modo "perfil local" (los servidores llevan años muertos).

## Estado de los subsistemas

| Subsistema | Estado |
|---|---|
| JIT ARM64→x64 (dynarmic) | ✅ |
| ELF loader + relocalizaciones | ✅ |
| JNI fake (233 slots) + modelo Java | ✅ |
| GL: shaders/texturas/buffers/draw | ✅ |
| EGL sobre SDL2 + ventana | ✅ |
| OpenSL ES (objetos+interfaces) | ✅ (audio out pendiente) |
| Zip del APK + VFS assets (fallback hd-) | ✅ |
| Guardado (profile0.dat, localsettings.dat) | ✅ |
| Fase de conexión → menú | 🔴 bloqueo actual |
