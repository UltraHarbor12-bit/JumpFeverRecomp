# Hito 2 — Ventana, GL y modelo Java (estado actual)

**Fecha:** 19 de octubre de 2026 · **Estado:** 🟡 en curso — ventana y puente GL operativos; bloqueo identificado en el hilo de trabajo del motor

---

## 1. Lo conseguido en este hito

| Pieza | Estado |
|---|---|
| **Modelo de objetos Java** | ✅ `getFilesDir()`/`getCacheDir()` → objeto `File` con `getPath()`/`getAbsolutePath()` reales (apuntan a `game/data`); `Loader.getRotation()` → 0; `getLanguage()` → "en"; `musicplayer.*` stubs con log; `HashMap`, `File.exists/mkdirs`, `isConnected`… |
| **Despacho JNI por nombre** | ✅ todas las variantes `Call*Method(V)/CallStatic*Method(V)` enrutan a un despachador que resuelve clase+método (17 clases del motor) |
| **`ALooper` real** | ✅ bloquea en `WaitForMultipleObjects` sobre los fds registrados (self-pipe del motor); entrega `ident`/`outFd`/`outEvents`/`outData`. Eliminó el busy-loop que colgaba `onResume` |
| **Ventana SDL2** | ✅ 540×960, contexto **OpenGL 4.6 (Intel UHD)** creado e informado en log |
| **Puente EGL** | ✅ `eglCreateWindowSurface`/`eglCreateContext`/`eglMakeCurrent`/`eglQuerySurface`/`eglSwapBuffers` sobre SDL |
| **GLES2 → OpenGL** | ✅ 66 funciones enrutadas a `opengl32` (`wglGetProcAddress` + fallback), incluidas 9 argumentos por pila (`glTexImage2D`) y arrays de shaders |
| **Saneado de shaders GLSL ES** | ✅ elimina `precision …;`, `#version`, `#extension` y calificadores `highp/mediump/lowp/invariant` para que GLSL 1.20 de escritorio los compile |
| **Captura de pantalla** | ✅ `--shot <bmp> --shot-swap N` (revisa el frame tras N swaps) |
| **Watchdog** | ✅ `--timeout N` para ejecuciones deterministas |

**Ciclo de vida completo y limpio** (sin cuelgues):

```
onCreate  → instance = 0x3008089f0
onStart   → getRotation, getFilesDir → File.getPath ✓, sensores ✓
onResume  → ok
onWindowFocusChanged(1) → musicplayer.setPause ✓
```

---

## 2. Bloqueo actual (preciso)

Inmediatamente después de `musicplayer.setPause()`, el **hilo de trabajo** creado en `onCreate` muere en:

```
PlayerProfile::triggerStartCount()          (símbolo más cercano: 0x32c7a8)
0x32c7a8: adrp x0, #0x5bd000
0x32c7ac: ldr  x0, [x0, #0x130]      ; global @0x5bd130 (singleton interno, sin símbolo exportado)
0x32c7b0: ldr  x0, [x0]              ; primer campo del singleton
0x32c7b4: ldr  x1, [x0, #0xb80]      ; ← FALLO: x0 == null → lectura de 0xb80
```

Backtrace huésped del hilo:

```
0x32c7a8 (fault)
 ← 0x28524c ← 0x4ff5c0 ← 0x28563c ← 0x4fefb0 (entrada del hilo)
```

Es un **subsistema de perfil/estadísticas que nunca se inicializó**: la cadena de punteros del singleton está a cero. Consecuencia: el hilo muere antes de crear el hilo de render, por lo que aún **no se ejecuta ninguna llamada EGL/GL** (el `onNativeWindowCreated` sí se invoca, pero queda esperando a que ese hilo exista).

---

## 3. Siguiente paso (Hito 2b)

1. **Identificar el singleton @0x5bd130** y quién lo escribe: con Ghidra sobre el proyecto ya importado (`extracted/ghidra_proj`) o con la tabla `.dynsym` + xrefs; buscar el `str` que lo inicializa y ver en qué condición se ejecuta.
2. **Hipótesis principal:** el objeto se crea con un `CallStaticObjectMethod` de Java (analytics/perfil) que devolvió `null` porque nuestro despachador no lo reconoce. Con la traza JNI ya activa (`JNI call …`) basta localizar la última llamada cuyo retorno se guarda.
3. **Arreglo esperado:** devolver un objeto no-nulo (handle opaco) para ese getter, o implementar el `PlayerProfile` local (las estadísticas no son críticas para renderizar).
4. Cuando el hilo de render arranque: verificar `eglCreateWindowSurface` → shaders (los logs `shader log:` mostrarán el GLSL saneado) → `--shot` para el **primer frame**.

---

## 4. Cómo reproducir

```powershell
C:\sjf\tools\cmake\cmake-4.4.4-windows-x86_64\bin\cmake.exe --build C:\sjf\port\build --parallel 8
C:\sjf\port\build\sjfport.exe C:\sjf\port\game\libsonicjumpfever.so --timeout 20 `
    --shot C:\sjf\extracted\analysis\first_frame.bmp --shot-swap 120
```

Log de referencia: `extracted/analysis/boot_run8.log`.
