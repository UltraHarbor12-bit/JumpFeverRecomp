# Hito 8 — Widescreen (pantalla panorámica) + paquete consolidado

## Resumen

| Cambio | Qué hace | Estado |
|---|---|---|
| `sjfport --aspect W:H\|auto` | El juego ve una superficie más ancha (alto fijo 960, ancho = 960·W/H). La UI y el nivel se adaptan solos: **widescreen real, sin bandas negras ni estirado** | Probado en Linux: 3:4, 1:1, 4:3, 16:9, 21:9 (Home), partidas completas en 4:3 y 16:9 (Green Hill, Jungle) |
| `sjfport --surface WxH` | Igual pero con tamaño exacto de superficie (experimentos) | Probado |
| Ventana por defecto | Si la superficie no cabe, la ventana inicial se reduce al 90 % del escritorio manteniendo proporción (antes 540x960 fijo podía salirse de pantallas de 1080 px con barra de tareas) | Probado (Xvfb) |
| Launcher: campo **Pantalla** | Vertical original 9:16 / Tablet 3:4 / 4:3 / 16:10 / 16:9 / 21:9 / Automática (monitor). También `--aspect` en CLI y en `Jugar.bat`/`jugar.sh` | Probado en Linux (GUI + CLI) |
| `SJF_TIME_OFFSET=<s>` | Desplaza el reloj de pared del guest (`time`, `gettimeofday`). Solo para pruebas: recarga energía / fuerza la recompensa diaria sin tocar saves | Probado |
| `sjf_save.py` | Lee los tipos `0x00` (null) y `0x09` (int64, timestamps). Ya decodifica `profile0.dat` completo. **Solo lectura** (ver abajo) | Probado |
| Zip consolidado | Handoff original + hitos 4–8 en un único árbol, sin datos del juego | — |

## Por qué funciona sin parchear el juego (evidencia)

El motor pide el tamaño de la superficie por EGL (`eglQuerySurface` → `platform_width/height`)
y construye con él la proyección ortográfica: con 540 de ancho la matriz tiene `m[0]=2/540≈0.0037`,
con 1706 baja a `≈0.0012` (log `glUniformMatrix4fv loc=0`). No hay ningún 540 fijo en el camino:

* **UI**: los elementos están anclados a esquinas/bordes (HUD arriba a izquierda/derecha, Start/Shop/Spin
  abajo a la derecha, “More Games” abajo a la izquierda, pop-ups centrados). Se verificó en 3:4, 1:1, 4:3,
  16:9 y 21:9: nada se estira ni se corta.
* **Nivel**: la escala del mundo depende del alto (Sonic y las plataformas miden lo mismo que en 9:16), así
  que en panorámico se ve **el mismo recorrido vertical** y más escenario a los lados.
* El juego original corría en tablets (`isTabletDevice`, layouts 3:4), lo que explica que el motor ya sea
  agnóstico de la proporción. Seguimos devolviendo `isTabletDevice=0`: no hace falta para esto.

Coordenadas de entrada: el mapeo ratón/mando → guest ya usaba `g_w/g_h` + letterbox (hito 5),
así que se adapta solo. Los toques guionizados (`SJF_TAPS`) van en coordenadas de superficie; como
los botones van anclados a la derecha, en los tests se usa `x = W - 93` (Start) y `x = W - 59` (flecha).

## Diferencia de jugabilidad a tener en cuenta

El generador de niveles coloca las plataformas en una franja central, pero **Sonic puede desplazarse
hasta el borde de la pantalla** (el “wrap” lateral se calcula con el ancho visible). En 16:9/21:9 el
recorrido lateral es mayor que en el móvil. Es jugable (partidas completas sin incidencias), pero no
es idéntico al original: para la experiencia exacta, 9:16; 3:4 es el término medio “oficial” (tablet).

## Advertencia: `profile0.dat` tiene control de integridad

Para recargar energía en los tests se probó a reescribir `profile0.dat` cambiando solo `energyCount`
(codificación byte a byte idéntica, round-trip verificado). Resultado: el juego **descartó el perfil
entero** y creó uno nuevo (`ftueState=1`, `startCount=2`, pantalla “Please enter your age” del primer
arranque). Conclusión: hay un checksum/firma (probable candidato `ftueStats`, int64 que cambia en cada
guardado). Por eso `sjf_save.py` queda de solo lectura para el perfil y se añadió `SJF_TIME_OFFSET`.
(Se restauró el save de pruebas desde copia; tu save real no se tocó.)

## Pruebas realizadas (Linux, Xvfb + Mesa llvmpipe)

* Home en 720x960, 960x960, 1280x960, 1706x960 → UI correcta.
* Partidas completas: 4:3 Green Hill, 16:9 Green Hill (hasta `last_hurrah_end`), 16:9 Jungle con audio
  9:16 Blue Sky (regresión) → sin `FATAL`, música de zona correcta.
* Recompensa diaria y pop-ups en 16:9: centrados y operables.
* `--aspect auto` bajo Xvfb 1024x1024 → 960x960 (proporción del “monitor”), `21:9` → 2240x960.
* Launcher CLI: `--aspect 16:9 --window 540x960` → avisa que la ventana vertical se ignora y ajusta sola.
* Windows: `sjfport.exe` compila y enlaza con zig (cross). **No ejecutado en Windows real**: falta
  confirmar `SDL_GetDisplayUsableBounds`/`SDL_GetDesktopDisplayMode` con DPI escalado (125–150 %); si
  la ventana sale rara, `--window 1600x900` la fija a mano.

## Archivos tocados

`port/include/sjfport/platform.h`, `port/src/platform/window.cpp` (aspect, surface, ventana inicial),
`port/src/engine/boot.cpp`, `port/src/dependencies/libgl.cpp` (crean la ventana con la superficie
configurada), `port/src/main.cpp` (`--aspect`, `--surface`), `port/src/dependencies/libc.cpp`
(`SJF_TIME_OFFSET`), `tools/launcher/sjf_launcher.py` (campo Pantalla, CLI, scripts portables),
`tools/launcher/sjf_save.py` (tipos 0x00/0x09, solo lectura), `tools/sandbox-linux/record3.sh`.
Patch: `patches/hito8.patch` (sobre el árbol del hito 7).
