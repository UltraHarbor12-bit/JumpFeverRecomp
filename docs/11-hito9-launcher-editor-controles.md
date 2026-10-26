# Hito 9: launcher con estilo del juego, editor de partida, remapeo de teclas, música y fix de ninja

## Resumen

| Cambio | Estado |
|---|---|
| **Fix ninja** ("Descargar lo que falta" no dejaba compilar) | Causa reproducida y corregida. Además hay descarga directa de respaldo |
| **Launcher con el estilo del menú del juego** (`sjf_gui.py`) | Probado en Linux (capturas + clics/teclas reales con XTest) |
| **Editor de partida** (página PARTIDA + `sjfport --profile-edit`) | Probado: cambia anillos, red rings, energía, personajes y boosters; el juego acepta el save |
| **Remapeo de teclas** (página CONTROLES + `controls.cfg`) | Probado con eventos de teclado reales |
| **Música del launcher** (opcional, `assets/menu_music.mp3` aportado por el usuario) | Linux probado (ffplay, salida de audio verificada). Windows (MCI) **no probado** |

## 1. Por qué fallaba ninja

`fetch_missing()` hace `pip install --target tools/pydeps ninja` y luego `find_ninja()` buscaba
`tools/pydeps/ninja/data/bin/ninja(.exe)`. Desde **ninja 1.13** el wheel ya no trae ese archivo: el
binario viaja como "data script" (`ninja-1.13.2.data/scripts/ninja.exe`, comprobado bajando el wheel
`win_amd64`). Con `--target`, pip lo deja en `tools/pydeps/bin/`. Resultado: pip terminaba bien, pero el
launcher seguía marcando ninja como FALTA y no dejaba compilar. Reproducido con el launcher anterior:
`Successfully installed ninja-1.13.2` → `find_ninja() = None`.

Arreglo (`sjf_launcher.py`):
* `find_ninja()` busca también en `pydeps/bin`, `pydeps/Scripts` y `tools/ninja/`.
* Si pip falla (proxy, SSL, permisos) o el binario sigue sin aparecer, descarga directa de los binarios
  oficiales: `ninja-win.zip` / `ninja-linux.zip` 1.13.1 de GitHub y, en Windows, el zip de CMake 4.1.2.
* Test: `tools/sandbox-linux/test_fetch_ninja.py pip|win_nopip` (simula un host sin ninja; el escenario
  `win_nopip` simula Windows con pip roto y descarga los zips reales).

## 2. Editor de partida (sin romper el CRC)

`profile0.dat` lleva un **CRC32 calculado campo a campo**: hay símbolos `PlayerState::updateCRC`,
`SynchronizedPlayerState::updateCRC`, `ChaoState::updateCRC`, `sl::ObjectSerializer::updateCRC`... Por eso,
en el hito 8, el juego descartó un perfil editado a mano. En vez de reimplementar el CRC, **el propio juego
escribe el save**:

1. `sjfport --profile-edit FILE` carga una lista de comandos.
2. Cuando suena la música del frontend (perfil cargado, Home), espera 1,5 s y, **en el hilo del juego**
   (dentro de `ALooper_pollAll`, entre frames), llama con `guest_call_nested` a los setters exportados sobre
   `*Global::playerProfile`:
   `getRings/addRings`, `getRedStarRings/addRedStarRings`, `setEnergyCount`, `setCharacterLocked`,
   `setBoosterCount` y, al final, `PlayerProfile::save()`.
3. Con `exit` en el archivo, sale al terminar. El launcher lo usa con `--hidden`: ventana oculta y sin sonido.

Los enums se sacaron de los jump tables y se verificaron aplicando valores distintos y leyendo el save:

| `Character::Enum` (setCharacterLocked @0x32ce28, límite `cmp w1,#9`) | 0 sonic, 1 tails, 2 knuckles, 3 amy, 4 blaze, 5 shadow, 6 vector, 7 silver, 8 rouge, 9 cream |
|---|---|
| `BoosterSpecification::Enum` (setBoosterCount @0x32b83c, límite `cmp w1,#6`) | 0 numGoldTotem, 1 numHoopBoost, 2 numPowerDoubler, 3 numQuickFrenzy, 4 numRingStreak, 5 numTimeExtend, 6 numAnimalDoubler |

En el save, el bit 0 del campo de cada personaje (`sonic`, `tails`...) indica si está desbloqueado.

Comandos: `rings N`, `redrings N`, `energy N`, `unlock NOMBRE|all`, `lock NOMBRE` (Sonic nunca se bloquea),
`booster I N`, `exit`.

**Prueba.** Editado 329→5000 anillos, 7→50 red rings, energía 5, Tails desbloqueado y los 7 boosters a 10..16.
Al reiniciar, el juego **acepta** el perfil: `startCount` sigue subiendo (94→96), `ftueState=7`, y la Home
muestra 50 y 5000. Segunda prueba desde la página PARTIDA del launcher (anillos 12345, Knuckles, Doble
animales 3): correcta. Antes de cada cambio, el launcher guarda una copia de `port/game/data/` en
`port/game/save_backups/data_FECHA.zip`.

Limitación: si la partida es nueva (sin tutorial terminado), puede no llegar a la Home y el editor avisa.

## 3. Remapeo de teclas

`port/controls.cfg` (lo lee sjfport al arrancar; `--controls RUTA` para otro archivo):

```
tilt_left = Left, A
tilt_right = Right, D
tap = Space, Return
back = Escape, Backspace
fullscreen = F11
```

Usa nombres de scancode de SDL (`SDL_GetScancodeFromName`) e independientes del layout. Alt+Enter siempre
alterna la pantalla completa. En la página CONTROLES, **CAMBIAR** captura la siguiente tecla, **+ OTRA** añade
una segunda tecla y **GUARDAR** escribe el archivo. Si una tecla ya estaba asignada a otra acción, se le quita a
esa. La versión portable copia `controls.cfg`.
Prueba (XTest, teclas reales): con `tilt_left=J, tilt_right=L, back=Q`, J da inclinación +5, L da −5, Q da
"back"; Left y Escape ya no hacen nada. El log del juego lanzado desde el launcher muestra
`controls: controls.cfg -> left=[J] ...`.

## 4. Launcher con estilo del juego

`tools/launcher/sjf_gui.py`, solo tkinter, sin Pillow:
* Fondo `assets/bg.png`: arte original generado con `make_assets.py` (cielo, brillo, rayos y destellos).
* Barra HUD con el título en amarillo con contorno, banner verde de estado (como "TRYING TO CONNECT TO
  SERVER...") y botones azules con borde blanco (como Shop/Spin).
* Panel con cabecera morada y cuerpo turquesa (como el pop-up "Daily Reward!") y botón redondo verde
  **JUGAR!** (como "Start!").
* Páginas: JUGAR, INSTALAR, COMPILAR, CONTROLES, PARTIDA y REGISTRO.
* El launcher anterior sigue disponible con `--classic`.

## 5. Música

`assets/menu_music.mp3` (opcional, NO incluido en el repositorio por derechos de autor): si colocas ahi tu propia pista, el launcher la reproduce; si falta, el boton de musica se oculta.
`sjf_music.py`: en Windows usa MCI de winmm vía ctypes (reproduce mp3 sin dependencias; para el bucle
consulta el estado cada segundo). En Linux usa ffplay, mpv o mpg123, el primero que encuentre. El botón
**MÚSICA: SÍ/NO** recuerda la elección. La música se para al lanzar el juego (que tiene la suya) y vuelve al
cerrarlo. Probado en Linux: suena (RMS 1557 con el driver de disco de SDL) y se para/reanuda con los clics.

## No probado en Windows real

* MCI (música), `os.startfile` (botón COPIAS) y la GUI con fuentes de Windows (busca Arial Rounded MT
  Bold, Segoe UI Black o Arial Black).
* `--hidden` con WGL: el editor crea la ventana oculta. Si en Windows falla, se puede quitar `--hidden` en
  `apply_profile_edits` (se verá la ventana unos segundos).
* La descarga de ninja/CMake en Windows se probó simulando Windows desde Linux (descargando los zips reales),
  no en un Windows de verdad.
