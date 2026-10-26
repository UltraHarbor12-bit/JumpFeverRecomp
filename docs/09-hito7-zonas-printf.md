# Hito 7 — Selector de zonas + bug de printf (25 oct 2026)

## Resultado

Las **4 zonas se juegan de principio a fin** y se eligen desde el launcher (o con `--zone`):

| Zona | `--zone` | Verificado |
|---|---|---|
| Green Hill | `green_hill_zone` | partida completa |
| Blue Sky | `blue_sky_zone` | partida completa (antes abortaba) |
| Jungle | `jungle_zone` | partida completa (antes abortaba) |
| Mechanical | `mechanical_zone` | partida completa |

En el launcher: **Zona** = *Rotación semanal (como el original)*, *La del juego (Green Hill)* o una
zona fija. La rotación semanal cambia de zona cada semana ISO y muestra "esta semana / próxima".
El orden histórico exacto lo decidía el servidor; aquí se recorren las cuatro en ciclo.
CLI: `sjf_launcher.py --run --zone weekly|game|<zona>`. Versión portable:
`Jugar.bat --zone jungle_zone` / `./jugar.sh --zone jungle_zone`.

## 1. Por qué solo había Green Hill

`AppLoadingScreen::update` (@0x3c8204) lee `currentZone` de los ajustes locales (objeto
`[perfil]+0xb78`, string en `+0x38`). Ese valor lo enviaba el servidor cada semana. Offline está
vacío, y el juego cae en la rama por defecto (@0x3c8c6c), que construye el literal
`"green_hill_zone"` (@0x51a748) y llama a `LevelResources::setZone()`.

Editar `currentZone` en `localsettings.dat` **no sirve**: el juego lo vacía al no conectar
(probado; queda `tools/launcher/sjf_save.py`, un editor de saves que hace la ida y vuelta exacta y
se niega a escribir si no la hace).

**Solución (`--zone`, en `boot.cpp`):** antes de que se traduzca ningún código guest se re-apuntan
las 3 instrucciones de esa rama (`adrp` + 2×`add`) a otro literal de zona que ya existe en
`.rodata` (`blue_sky_zone` @0x51b690, `jungle_zone` @0x51b670, `mechanical_zone` @0x51b6b0). Antes
de parchear se comprueban las codificaciones originales (`d0000a81 911d2022 911d2021`); si no
coinciden (otra versión) no toca nada. El literal original no se modifica, porque también lo usa
0x1d21b0.

## 2. El bug de verdad: `printf` ignoraba la precisión (`%.2d`)

Con Jungle y Blue Sky el juego abortaba:
- Jungle: `Unable to find animation ed5084c5` (`PlatformCrumbleBehaviour`, nombre
  `"%sPlatform_Piece_%.2d"`).
- Blue Sky: `Unable to open stream for file 'floaterpop_4.eff'` (el pack trae `floaterpop_04.eff`).

Primero parecía contenido descargable que faltaba, pero el formato del propio juego es
`floaterpop_%.2d.eff`, y en C `%.2d` con 4 da `04`. **El `printf` reimplementado en el port
(`guest_abi.cpp`) ignoraba la precisión en los enteros.** También fallaban `-` (alinear a la
izquierda), `+`/espacio, los modificadores `h`/`hh` y `%06d` con negativos (ponía `   -42` en vez de
`-00042`).

**Fix:** `emit_int` reescrito según C99 (ancho, precisión y flags `0 - + espacio #`, `h/hh/l/ll/z/t/j`);
`emit_fp` y `%c` respetan los flags. **Test: 316 de 316 casos idénticos al `snprintf` del sistema**
(23 formatos enteros × 12 valores + 8 formatos float × 5 valores). Este bug probablemente afectaba a
más textos o recursos con `%.Nd` o `%-Ns` en cualquier zona.

`--anim-fallback` queda como red de seguridad opcional: si de verdad falta una animación, usa la
primera del set en vez de abortar. Ya no se activa sola.

## 3. Observado jugando (funciona offline)

- **Daily Reward**: el calendario de recompensas diarias aparece y se cobra.
- **Energía**: se gasta por partida y se recarga con el tiempo, o con anillos rojos.
- Subida de nivel del jugador (Lv1 → Lv3), anillos y anillos rojos acumulados y guardados.

## 4. Pendiente

- Servidor local (banner "TRYING TO CONNECT", ranking, tienda), ya documentado en el doc 08.
- Probar en Windows real (el `.exe` cruzado compila con todo lo nuevo).
