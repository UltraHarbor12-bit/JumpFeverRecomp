import io

p = 'docs/03b-hito2c-progreso.md'
s = io.open(p, 'r', encoding='utf-8', newline=None).read()

add = '''
### Addendum 2 — verificación del singleton y VFS de assets

**Verificación en runtime del mapeo** (descarta errores de interpretación):

```
probe: GOT[0x5bd130] = 0x1005cbed0   (objeto .bss)
       *objeto       = 0x0            (primer campo, nunca escrito)
       [objeto+0xb80]= 0x0
```

- Watchpoint de escritura del JIT (1/4/8 bytes) → **0 escrituras**.
- Watchpoint en `memcpy`/`memmove`/`memset` (destino dentro del objeto) → **0 accesos**.
- Los 404-405 constructores de `.init_array` se ejecutan y retornan limpios (sin fallos).
- `PlayerProfile::PlayerProfile()` (0x330798) solo escribe 10 bytes (bool/int/bool/bool): es una clase
  pequeña, **no** el objeto de 0xb80.

Conclusión: el objeto al que apunta el slot GOT nunca se inicializa en nuestra ejecución; la ruta que
lo hace (probablemente el despachador de comandos `APP_CMD_*` del hilo propio del motor, al recibir
`INIT_WINDOW`/`RESUME` con un estado concreto) no se dispara con nuestro shim actual.

**VFS de assets implementado**: `open`/`fopen` traducen cualquier ruta que contenga `assets/<X>` a
`game/assets/<X>`; los 61 assets del APK están copiados en `port/game/assets/`. Esto deja preparada
la carga real de `.sla`/`.snd` en cuanto el motor avance.

**Ghidra**: el headless funciona por la vía `bash` de MSYS (el `.bat` se colgaba y el error
"Failed to find a supported JDK" era en realidad `APPDATA` sin definir). El proyecto
`extracted/ghidra_proj` está analizado y el script `tools/DumpTargets.java` volcó la
decompilación, pero el análisis automático identifica mal varias funciones de este binario
(nombres desplazados) y no hay xrefs directas al singleton (acceso mediado por GOT).
'''
s = s.rstrip() + '\n' + add
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('doc updated')
