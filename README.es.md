# JumpFeverRecomp

**Port a PC de *Sonic Jump Fever* (Android, ARM64): trae tu propio APK.**

🇬🇧 [Read in English](README.md)

> [!IMPORTANT]
> **Este repositorio no contiene datos del juego.** Ni APK, ni `libsonicjumpfever.so`, ni texturas, música o sprites.
> El launcher extrae todo lo necesario de **tu propio APK**, en tu máquina.
> No abras issues ni PRs con archivos del juego.

## Cómo funciona

No traduce el juego por adelantado: carga la librería nativa ARM64 original y la ejecuta con un JIT, reimplementando alrededor el entorno de Android (una capa de compatibilidad al estilo Wine):

- **Cargador ELF + [dynarmic](https://github.com/merryhime/dynarmic)**: ejecuta el código ARM64 del juego en x86-64.
- **Shims de Android**: JNI, `libc`/`libm`/`libdl`/`pthread` de bionic, `liblog`, `libandroid`, OpenGL ES (sobre GL de escritorio) y OpenSL ES (sobre audio de SDL2).
- **SDL2** para ventana, entrada (teclado, ratón como toque, mando) y audio.
- **Launcher en Python** (solo librería estándar + tkinter): instala los datos de tu APK, descarga lo que falte, compila y lanza el juego.

## Características

- Las 4 zonas jugables de principio a fin (Green Hill, Blue Sky, Jungle, Mechanical), menús, guardado y audio
- Widescreen: 9:16 original, 3:4, 4:3, 16:10, 16:9, 21:9 o automático
- Teclado, ratón y mando, con teclas remapeables
- Editor de partida (anillos, red rings, energía, personajes, boosters)
- Opcional: Cream, Rouge y Vector seleccionables. Su código, stats y retratos existen en el juego original, pero sus sprites nunca se publicaron, así que el launcher genera sprites provisionales **localmente a partir de tu APK** (Knuckles / Silver / Amy recoloreados)
- Selector de zona fija o rotación semanal

## Requisitos

- APK de **Sonic Jump Fever 1.6.1 arm64-v8a** que poseas. El `.so` debe tener SHA-256 `4bbe841e2068c389324414750ccd37ca8153a693643d1cd62e4377c5cb07bd3f` (las direcciones están fijadas para esta versión exacta).
- Python 3.8+ con `tkinter`
- GPU/driver con OpenGL
- Windows 10/11 x64 o Linux x64

## Inicio rápido

```text
Windows:  doble clic en Lanzador.bat
Linux:    ./lanzador.sh
```

1. **INSTALAR** → elige tu APK → *Instalar datos del juego*
2. **COMPILAR** → Windows o Linux → *Descargar lo que falta* → *Compilar*
3. **JUGAR** → zona y relación de aspecto → *JUGAR!*

Controles: ratón = toque · flechas / A-D = inclinar · Esc = atrás · F11 o Alt+Enter = pantalla completa · mando: stick/cruceta, A, B/Start.

## Compilar desde el código

Necesitas CMake ≥ 3.20, Ninja, compilador C++20, SDL2 y cabeceras de Boost. El launcher puede descargarlo todo; a mano:

```bash
# Linux
sudo apt install cmake ninja-build g++ libsdl2-dev libgl-dev libboost-dev
cmake -S port -B port/build-linux -G Ninja
cmake --build port/build-linux
# Windows desde Linux (cruzado con zig)
cmake -S port -B port/build-win -G Ninja -DCMAKE_TOOLCHAIN_FILE=port/cmake/zig-windows.cmake
```

## Estado

| Plataforma | Estado |
|---|---|
| Linux | Probado: todas las zonas, menús, guardado, audio, mando, widescreen, editor, remapeo y personajes extra |
| Windows | Compila y enlaza (MinGW y zig cruzado). Probado bajo Wine; **aún no validado en Windows real**: se agradecen reportes |

## Documentación técnica

La carpeta [`docs/`](docs/) tiene el análisis de formatos y el diario técnico por hitos (en español).

## Legal

Proyecto fan no oficial, con fines de interoperabilidad y preservación. No está afiliado ni respaldado por SEGA.
*Sonic*, *Sonic Jump Fever* y *SEGA* son marcas de SEGA Corporation. Debes poseer una copia legal del juego.
No distribuyas la carpeta portable que puede crear el launcher (`dist/`): contiene datos de tu APK.
El código original es MIT; el código de terceros conserva su licencia: ver [LICENSE](LICENSE) y [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
