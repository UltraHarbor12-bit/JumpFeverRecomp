# Hito 2c/2d — Progreso de arranque (21 oct 2026)

## Estado: el motor ejecuta su propia secuencia de inicialización completa

Con la cadena de arreglos de esta sesión, el motor **ya ejecuta su propio flujo de arranque**
(`android_main` → gate → `ZipFile::openArchive` → `appPreInitialise` → `createAudio` →
`slInitialise` → carga de texturas), y la capa de compatibilidad pasa de fase en fase.

## Arreglos de esta sesión (en orden de descubrimiento)

| # | Problema | Fix |
|---|---|---|
| 1 | **Carrera de orden**: el hilo del motor procesaba START sin superficie | Ventana + `onNativeWindowCreated` tempranos (justo tras onCreate) |
| 2 | **`wglGetProcAddress` sin contexto** (todas las GL 2.0 a NULL, cacheadas) | No cachear NULL + soltar el contexto tras crearlo (`MakeCurrent(w, nullptr)`) |
| 3 | **`wglMakeCurrent` rechaza el contexto** ("resource already in use") | Ídem: se libera en el hilo principal antes de que el hilo de render lo tome |
| 4 | **`vsnprintf` stub devolvía ""** → `fopen("")` → cadenas de fallos | `vsnprintf`/`vprintf`/`vfprintf` reales con **semántica va_list AArch64** (leer en `gr_top+offs` y avanzar) |
| 5 | **`fopen("game/base.apk")` fallaba por CWD** | Resolución relativa al directorio del ejecutable |
| 6 | **Deadlock pipe** (mutex tomado durante I/O bloqueante) | Lock solo para consultar el fd |
| 7 | **`ALooper_pollAll`** | `PeekNamedPipe` polling (WaitForMultipleObjects no señaliza sobre pipes anónimas) |
| 8 | **OpenSL ES**: "Cannot create audio engine" → abort | Modelo de objetos SL completo (vtables guest + trampolines por slot), despacho de interfaces por IID |
| 9 | **`SL_IID_*` con indirección extra**: el import es una *variable puntero* | El blob contiene un puntero a una SLInterfaceID única; el despacho la resuelve |
| 10 | **Slots SLEngineItf 2014**: CreateOutputMix en slot 7, CreateAudioPlayer en 2/3 (empírico) | Mapeo doble 2/3 y 7/8 |
| 11 | **Identidad GL**: el motor valida la versión | `glGetString(GL_VERSION/RENDERER/SHADING_LANGUAGE_VERSION)` devuelven GLES2 |
| 12 | **Unwinding**: los null-deref mataban los hilos | Desenredo en cascada por frame (FP chain) + re-entrada en el JIT; página nula shadow (lecturas→cascada, escrituras→absorbidas, código→`ret`) |
| 13 | **Red**: el juego esperaba `isConnectedCallBack(true)` | La capa Java dispara el callback nativo exportado directamente |

## Última ejecución (`boot_run65.log`)

```
init AppStoreBridge ok
JNI_OnLoad completed
[TRACE:31] / count = 582            ← las 582 cadenas localizadas cargan ✓
new localisation took 0.000019 s
GL first call: glCreateShader...    ← shaders compilando (sin errores GLSL) ✓
fopen("cache_splash.sla") → falla (esperado: es contenido de caché)
glCompressedTexImage2D ✓            ← textura subida
Loader.getLanguage() ✓
<cascadas null-page>                ← el arranque aún tropieza en la fase de conexión
Softlight.isConnected → isConnectedCallBack(true) ✓ disparado
```

## Pendiente inmediato (Hito 2e)

1. **Fase de conexión**: la cascada nula que mata `android_main` ocurre justo tras disparar
   `isConnectedCallBack(true)` — trazar `0x28442c` (nested call) y el flujo de
   `network::ConnectedProfileManager` (constructor ausente).
2. **Ruta de recursos**: `cache_splash.sla` falla; verificar si el motor necesita que la caché
   exista (`game/data/cache/`) o si el fallback al APK funciona.
3. **Audio real**: los AudioPlayers se crean y quedan en PLAYING; implementar `Enqueue` → SDL
   audio con los WAV de referencia (`extracted/assets/snd/`).
4. **Render**: cuando el flujo pase la fase de conexión, esperar `eglSwapBuffers` + screenshot
   (`--shot`).
