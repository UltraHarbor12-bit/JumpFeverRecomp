# Hito 1 — Andamiaje y primer arranque del juego original en PC

**Fecha:** 19 de octubre de 2026 · **Estado:** ✅ completado (con hallazgos que redefinen el Hito 2)

---

## 1. Qué se ha construido

Se adoptó la arquitectura de PvZ2Native: **solo la CPU se traduce** (dynarmic, ARM64→x86_64) y **todo lo demás se reimplementa de forma nativa** (estilo Wine). El resultado es un ejecutable Windows que carga el `libsonicjumpfever.so` original y ejecuta su código ARM64 real.

```
port/
├── src/runtime/        guest_memory, guest_abi (varargs AAPCS64), elf_loader,
│                       host_calls (trampolines svc), jit (dynarmic, 1 JIT/hilo)
├── src/dependencies/   libc, libm, liblog, libdl, libandroid, libgl (EGL/GLES/OpenSL), pthread
├── src/dex/            jni_env (JavaVM + JNINativeInterface de 233 slots), tabla de nombres generada
├── src/engine/         boot (init_array → JNI_OnLoad → ANativeActivity_onCreate → ciclo de vida)
└── src/game/           (reservado para la lógica del port en fases futuras)
```

**Toolchain:** WinLibs MinGW-w64 GCC 16.2 (UCRT, posix) + CMake 4.4.4 + Ninja 1.13.2 + Boost 1.86 (headers) + dynarmic 6.7 (mirror público, frontend A64).
Compilación reproducible: `cmake --build port/build --parallel 8` → `sjfport.exe`.

> Nota: el toolchain vive en `C:\sjf-mingw` y el proyecto se compila desde la unión `C:\sjf` porque el *linker* de MinGW no tolera espacios en rutas (bug conocido de `default-manifest.o`).

---

## 2. Resultado del arranque (ejecución real, `extracted/analysis/boot_run5.log`)

| Etapa | Resultado |
|---|---|
| Mapeo del ELF | ✅ imagen `0x100000000`–`0x10060b000`, **11.192 símbolos, 10.958 exports** |
| Relocalizaciones | ✅ 8.714 `.rela.dyn` + 224 `.rela.plt` aplicadas (AArch64 RELATIVE/GLOB_DAT/JUMP_SLOT) |
| **405 constructores `.init_array`** | ✅ todos ejecutados y retornados |
| **`JNI_OnLoad`** | ✅ devuelve **0x10006 = JNI_VERSION_1_6** (¡el juego acepta nuestra JVM falsa!) |
| Clases Java pedidas por JNI | ✅ 17 `FindClass` (Loader, musicplayer, Billing, HTTP, Facebook, Push, PlayServices, Chartboost, Ads, License, CryptoLib, LicenseListener, HashMap…) + 2 `RegisterNatives` |
| **`ANativeActivity_onCreate`** | ✅ retorna y **`activity->instance = 0x3008089f0`** (estado del motor creado) |
| Callbacks instalados | ✅ 13 de 16 (`onStart/onResume/onPause/onStop/onDestroy/onWindowFocusChanged/onNativeWindow{Created,Destroyed}/onInputQueue{...}/onConfigurationChanged/onLowMemory`) |
| Hilo de eventos del motor | ✅ `pthread_create` → thread huésped con su propio JIT; registra el self-pipe en `ALooper_addFd(fd=100)` |
| **`onStart`** | ⚠️ ejecuta y llega a la capa Java: `Loader.getRotation()`, `NativeActivity.getFilesDir()` → **`getPath()` sobre `null` → fallo** |
| `onResume` | ⏸️ entra en el bucle del motor (watchdog a 15 s) |

**Traza del punto exacto donde se detiene hoy:**

```
JNI GetStaticMethodID(Loader, "getRotation", "()I")   → CallStaticIntMethodV (stub → 0)   OK
JNI FindClass("android/app/NativeActivity")           → GetMethodID("getFilesDir")        OK
JNI CallObjectMethodV(getFilesDir)                    → stub devuelve null                 ✗
JNI GetMethodID(java/io/File, "getPath", "()Ljava/lang/String;")
guest memory Read8 at 0x0  ← el motor hace File.getPath() sobre null
```

Conclusión: el motor **ya depende de un pequeño modelo de objetos Java** (File/getPath, Loader/rotación). Es el siguiente paso natural.

---

## 3. Bugs y decisiones que costaron el hito (documentados para no repetirlos)

1. **`Elf64_Sym` mal declarado** (`st_info`/`st_other` como `u32` → struct de 30 B en vez de 24 B): toda la tabla de símbolos se leía desalineada → 0 exports y blobs de tamaño basura. *Fix: `u8`/`u8`/`u16`.*
2. **`Callbacks` de dynarmic era singleton global**: con dos hilos huésped se pisaban los registros (el hilo del motor leía los registros del hilo principal). *Fix: `thread_local`.*
3. **`pipe()` no implementado**: `ANativeActivity_onCreate` crea un self-pipe (patrón looper) y **aborta antes de guardar `activity->instance`** si falla → todos los callbacks revientan con `null+0xc4`. *Fix: `_pipe` + tabla de fds con soporte de pipes; entonces `instance` se guarda correctamente.*
4. **Centinela de retorno**: las funciones huésped se llaman con `LR = 0xDEAD0000`; dynarmic señala `NoExecuteFault` que tratamos como "retornó". Rango aceptado `0xDEAD0000..0xDEADFFFF`.
5. **`svc`-trampolines**: cada función host vive en un stub de 8 B (`svc #imm; ret`) en memoria huésped; `CallSVC` despacha al handler nativo, que lee x0–x7/v0–v7 y devuelve x0. Funciona con llamadas anidadas (cada una en su JIT).
6. **Varargs AAPCS64**: `__android_log_print`/`printf` de 3–4 argumentos exigen emular `va_arg` (registros x/v + pila) — implementado en `guest_abi.cpp` con parser de formato completo.

---

## 4. Siguiente hito (Hito 2) — ya con el mapa exacto

1. **Modelo de objetos Java falso** (lo que bloquea hoy): `getFilesDir()` → objeto `File` con `getPath()`/`getAbsolutePath()` reales apuntando a `port/game/data`; `Loader.getRotation()` → 0; `musicplayer` (play/pause con m4a); `HTTPManager` (fallo controlado, servidores muertos).
2. **`ALooper_pollAll` real**: hoy devuelve `ALOOPER_POLL_TIMEOUT` inmediato → busy-loop. Debe bloquear en los fds registrados (self-pipe) con timeout y repartir eventos — es el corazón del hilo de eventos del motor.
3. **EGL + SDL2** (primer frame): `eglCreateWindowSurface`/`eglMakeCurrent` sobre una ventana SDL, GLES2→OpenGL 2.1 compat, `ANativeWindow` sintético, y disparar `onNativeWindowCreated`.
4. **Input**: `AInputQueue`/`AMotionEvent` desde ratón/táctil de SDL (tap izq/der para girar).
5. **OpenSL ES → miniaudio** con los WAV ya extraídos como referencia de validación.

---

## 5. Reproducir

```powershell
# compilar
C:\sjf\tools\cmake\cmake-4.4.4-windows-x86_64\bin\cmake.exe --build C:\sjf\port\build --parallel 8

# ejecutar (con watchdog de 15 s; el .so se copia a port/game/)
C:\sjf\port\build\sjfport.exe C:\sjf\port\game\libsonicjumpfever.so --timeout 15
```

Logs de referencia: `extracted/analysis/boot_run5.log` (mejor ejecución hasta la fecha).
