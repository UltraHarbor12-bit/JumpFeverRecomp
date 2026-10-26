# Hito 6 — Guardado entre sesiones, mando, botón Atrás, partida completa (25 oct 2026)

## Resumen

| Tema | Estado | Evidencia |
|---|---|---|
| **Guardado entre sesiones** | **Arreglado.** Antes cada arranque volvía a pedir la edad y rehacía el tutorial | Sesión 2 sin toques: salta el age gate. Tras terminar el tutorial, la sesión siguiente abre la Home |
| **Partida completa** | Tutorial → modo Fever → final → pantalla de resultados (5959 pts, "Best") → Home → Boosters | 160 s estables (~58 FPS), sin fallos |
| **Mando** (SDL GameController) | Stick izq./cruceta = inclinar, stick der. = cursor dibujado, A = tocar, B/Back/Start = atrás | Mando virtual de SDL (`SJF_VPAD`): age gate, popup y gameplay manejados solo con el mando |
| **Botón Atrás** | Esc / Retroceso / B: llama a `Loader.triggerBack()` igual que Android | Cierra el popup de Facebook ("No") y el juego continúa |
| Windows | El `.exe` sigue compilando con todo lo nuevo (build cruzado) | — |

## 1. Por qué no se guardaba el progreso (causa raíz)

- El flag de edad sí se fijaba en memoria (`[[perfil]+0xb88]+0x120`, bit 0 = edad fijada, bit 1 =
  menor), comprobado con una sonda en `--debug`.
- El problema era **cuándo se guarda**. `PlayerProfile::save()` (@0x32c8e8) se llama desde
  `appLostFocus()` (@0x33594c), que el motor ejecuta cuando Android le pasa el ciclo de vida de
  pausa. También lo llaman algunas pantallas (resultados, tienda…).
- El port terminaba el proceso de golpe (watchdog `_Exit` o cerrar la ventana) **sin `onPause`**,
  así que todo lo que no hubiera guardado una pantalla concreta se perdía.
- **Fix:** cierre ordenado en `boot.cpp`. Al salir del bucle (ventana cerrada, `--timeout` o
  `request_quit()`) se llama a `onWindowFocusChanged(0)`, `onPause`, `onSaveInstanceState` y
  `onStop` en un hilo auxiliar con un tope de 6 s; luego `_Exit`. El watchdog ya no mata el
  proceso: pide el cierre ordenado y solo fuerza la salida si se atasca 10 s.
  Log: `boot: shutdown lifecycle complete (profile saved)`.

## 2. Botón Atrás

`Java_com_sega_sonicjumpfever_Loader_triggerBack` (@0x28456c) solo escribe un flag que
`android_main` consulta para llamar a `appSystemBackButtonPressed()` → `ScreenManager`. El port
llama a esa función nativa desde el bucle principal cuando se pulsa Esc, Retroceso o B/Back/Start.
Nota: durante el tutorial y la cuenta atrás, `InGameHudOverlay::onBackButton` consume Atrás sin
pausar (solo pausa con estado 2). Es el comportamiento original, no un fallo.

## 3. Mando

- `SDL_INIT_GAMECONTROLLER`, conexión y desconexión en caliente.
- Inclinación: stick izquierdo analógico con zona muerta del 18 % (±7 m/s²) o cruceta (±5). El
  teclado tiene prioridad.
- Cursor virtual: stick derecho (600 px/s a fondo), dibujado como tres cuadrados anidados con
  `glScissor`+`glClear`, sin tocar shaders ni el estado del juego. Se oculta al mover el ratón.
- A = dedo abajo/arriba en el cursor; mover el cursor con A pulsado = arrastrar.
- Prueba sin hardware: `SJF_VPAD="<ms>:<ctl>=<valor>;..."` (ctl: `lx ly rx ry a b start`) crea un
  mando virtual de SDL que pasa por el mismo código que uno real.

## 4. Estado del modo offline

- Arriba de la Home y los menús aparece **"TRYING TO CONNECT TO SERVER..."**. Es solo visual: se
  juega, se guarda y se avanza. El servidor original (`https://prod.server.sjf.hla.sega.co.uk`)
  está muerto. El motor encola peticiones con `HTTPManager.queueRequest(J)` (puntero nativo a la
  petición) y espera respuesta por callbacks nativos. La máquina de estados está en
  `network::ConnectedProfileManager` (disconnected → handshaking → connecting → connected).
- "Ring Doubler: Item unavailable": la tienda no tiene backend (BillingPlay es un stub).

## 5. Pendiente

1. **Servidor local falso** (próximo hito grande): implementar `HTTPManager.queueRequest` en la
   capa JNI, leer la petición nativa, responder con JSON plausible (handshake, connect, perfil,
   ranking) y quitar el banner. Opcional: tienda local con monedas del juego.
2. Probar en Windows real: launcher, `.exe` nativo/cruzado, mando físico.
3. Revisar el resto de pantallas de la Home (Daily Spin, Chao, Store, Options) una por una.
