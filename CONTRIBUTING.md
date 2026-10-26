# Contributing / Contribuir

Thanks for helping! / ¡Gracias por ayudar!

## Hard rules / Reglas innegociables
1. **Never upload game data**: no APK, no `libsonicjumpfever.so`, no extracted assets (`.sla`, `.tex`, `.snd`, `.loc`),
   no screenshots/recordings of gameplay, no logs that dump game strings.
   Nunca subas datos del juego: ni APK, ni `.so`, ni assets extraídos, ni capturas de juego.
2. Bug reports must not attach the APK. Use the SHA-256 of your `.so` instead (see README).
3. Don't ask for or share links to pirated APKs.

## Workflow
- Fork → branch → PR using the PR template.
- Keep PRs focused. Mention which OS you tested on (Windows / Linux) and the game version (1.6.1 arm64-v8a).
- Code style: match the surrounding C++20 / Python 3.8+ style. The launcher must stay dependency-free (stdlib + tkinter).

## Build
See the *Build from source* section of the README.
