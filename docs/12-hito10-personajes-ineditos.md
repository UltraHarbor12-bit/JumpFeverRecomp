# Hito 10: Cream, Rouge y Vector seleccionables (personajes inéditos)

## Qué hay de ellos en Sonic Jump Fever 1.6.1 (evidencia)

| Elemento | Cream / Rouge / Vector | Dónde |
|---|---|---|
| Clases de juego `PlayerCream`, `PlayerRouge`, `PlayerVector` (heredan de `Player`) | ✅ | `.dynsym`, vtables |
| Habilidad propia | **Rouge**: redefine `stateJumpEnter/Update` y `stateFallEnter/Update` (planeo, lee `hoverTime`). Cream y Vector solo `doInitalise` (piden `Player_Fly`/`Player_FlytoFall` y `Player_Attack`) | vtables comparadas con las de `Player` |
| Stats completos (salto, muelle, dirección, frenesí, power-ups, tokens) | ✅ `<vector>`, `<rouge>`, `<cream>` | `settings.sla/settings.xml` |
| Nombre, nombre corto, descripción | ✅ | `strings_*.loc` |
| Retrato de la selección, token, mini-token, avatar de ranking | ✅ | `frontend.set` (hashes FNV-1 de `Token_Cream`, `LeaderboardAvatar_Rouge`...) |
| Partícula `cream_love` (corazones) | ✅ | `particles.sla` |
| **Sprites y animaciones de juego** (`player_X.sla`, `playerextra_X.sla`) y **voces** (`sfx_X.sla`) | ❌ **no están en el APK** | El .so los pide por nombre, pero nunca se publicaron |
| `Character::isAvailable(Enum)` @0x3a35a4 | devuelve `0` fijo para 6 (Vector), 8 (Rouge) y 9 (Cream) | desensamblado |

Fuentes externas lo confirman. La wiki los lista como "planned, unreleased" y el mod de la comunidad (Furrican,
2022) solo los hace jugables **sustituyendo** a Tails, Shadow y Silver, con las habilidades del sustituido.
Este hito usa **sus clases y stats reales**: solo el arte de juego es prestado.

## Cambios

### 1. `Character::isAvailable` (boot.cpp, `patch_extra_characters`)
```
0x3a35d8  b.ls 0x3a3618   ; enum <= 5 -> comprobaciones
0x3a35dc  cmp  w20, #7    ; Silver -> comprobaciones; el resto (6/8/9) -> return 0
```
`0x3a35d8` pasa a `b 0x3a3618` (`0x14000010`). El resto de la función busca `<personaje>::enabled == "true"`
en los ajustes online; sin servidor no bloquea. Se verifica la codificación original antes de parchear.

### 2. Alias de animaciones (code cave en `getAnimation`)
`sl::AnimationSet::getAnimation` aborta si falta un hash. Ningún set publicado tiene `Player_Fly` ni
`Player_FlytoFall`, que pide Cream. La rama de fallo (`0x2f3344`) salta ahora (`ldr x16,#8; br x16; .quad`) a
una cueva en memoria nativa que reintenta con un alias:
`Fly→Jump, FlytoFall→JumpToFall, Hover→Jump, HovertoFall→JumpToFall, Attack→Jump, AttackToFall→JumpToFall,
LevelUp→Complete`.
Si no hay alias, se comporta como antes: aborta o, con `--anim-fallback`, devuelve la animación raíz.
Fuente: `tools/asm/anim_alias_cave.s` (`zig cc -target aarch64-linux-gnu -c`).

### 3. Paquetes de jugador (VFS + launcher)
* **VFS** (`libc.cpp`): si falta `player_/playerextra_/sfx_<vector|rouge|cream>.sla`, sirve el del donante.
  Se puede cambiar con `SJF_CHAR_DONORS="cream=tails,rouge=shadow"`.
* **Launcher** (`sjf_extra_chars.py`): al instalar el APK (o al jugar, si faltan) genera
  `hd-player_X.sla`, `hd-playerextra_X.sla` y `sfx_X.sla` con los sprites del donante **recoloreados**. Las
  hojas son RGBA4444 + zlib; el recoloreado usa una tabla de 64K por HSV, en Python puro y en ~1 s:

| Personaje | Donante (por las animaciones que pide su código) | Recoloreado |
|---|---|---|
| Vector | Knuckles (tiene `Player_Attack`) | rojo → verde |
| Rouge | Silver (único con `Player_Hover`/`HovertoFall`) | acentos cian → rosa |
| Cream | Amy | rosa → crema, rojo (vestido) → naranja |

Si alguien tiene o crea un `hd-player_cream.sla` propio y lo pone en `port/game/assets/`, se usa ese.

### 4. Opciones
* Activado por defecto. Para desactivarlo: `--no-extra-chars` o `SJF_NO_EXTRA_CHARS=1`. En el launcher es la
  casilla "Personajes inéditos" de la página JUGAR.
* Para desbloquearlos: página PARTIDA del launcher (casillas de personajes) o en el juego, con tokens o red
  rings, como el resto (Rouge 125 tokens / 375 red rings, Cream 185, Vector 400 / 1200).
* Editor: nuevo comando `select NOMBRE` (`PlayerProfile::setLastSelectedCharacter`): el carrusel abre en ese
  personaje.

## Pruebas (Linux)
* Carrusel bloqueado: aparecen Rouge (0/125, 375 red rings) y Vector (0/400, 1200) con silueta y token propios.
  Desbloqueados: retratos oficiales a color, nombre y descripción ("Rouge usa sus alas para planear...").
* Partidas completas con los tres en Green Hill, con su música: sin `FATAL` ni "Unable to find animation".
  Cream pasa por el alias Fly→Jump. Log: `vfs-fallbacks: 0` con los paquetes generados.
* `--no-extra-chars`: no se aplica ningún parche (vuelven a estar ocultos).
* Sonic (regresión): partida normal.

## Límites honestos
* El **arte de juego** de Cream, Rouge y Vector **no existe** en el juego: lo que ves es Knuckles, Silver y Amy
  recoloreados. Los retratos de la selección, los tokens, los stats y el código sí son los originales.
* Habilidades: la de Rouge (planeo) es código propio. Cream y Vector solo tienen la inicialización: sus
  animaciones especiales no existen, y lo que hagan de especial lo deciden el código base y sus stats.
* Voces: las del donante.
* No probado en Windows real; el `.exe` compila (zig cruzado).
