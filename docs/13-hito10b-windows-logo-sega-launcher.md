# Hito 10b - Windows se quedaba en el logo de SEGA + informe del launcher

## Logo de SEGA (reproducido con Wine 10 en el sandbox)
- Causa: `clock()` del shim devolvia `std::clock()` del host. bionic usa CLOCKS_PER_SEC=1e6;
  MinGW/UCRT usa 1000 -> el tiempo del juego medido con clock() iba 1000x mas lento en Windows.
  Fix: escalar a microsegundos (libc.cpp). Verificado: Home, seleccion y partida en Green Hill.
- `rand()`: MinGW RAND_MAX=32767 (bionic 2^31-1) -> particulas en linea. Generador propio 31 bits.
- `guest_memory_init` (Windows): si 0x100000000 esta ocupado, reserva en cualquier direccion
  (todo pasa por guest_to_host). Necesario en Wine; en Windows real no deberia activarse.
- `ALooper_pollAll(0)`: en Windows yield en vez de sleep 500us (sleep minimo 1-15 ms).
- Diagnostico: `SJF_TIME_TRACE=1` registra llamadas clock/clock_gettime.

## Launcher (informe-errores-launcher.md, puntos 1-6)
1/3. find_cmake/find_ninja/find_zig: copias empaquetadas primero, PATH al final, y nunca
     binarios MSYS2/Cygwin (ruta msys/cygwin/usr\bin o msys-2.0.dll al lado).
2. pip con PIP_USER=0 (y sin PIP_TARGET/PIP_PREFIX).
4. pydeps: cmake+ninja siempre en una sola llamada pip.
5. fix_future_mtimes() al inicio de build().
6. El dialogo de error incluye las ultimas 15 lineas de la salida.
Test: tools/sandbox-linux/test_launcher_report.py (8/8 PASS).

## No probado en Windows real
Solo bajo Wine 10.0 (wow64). El .exe incluido en prebuilt/windows esta compilado con zig.
