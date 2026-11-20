# Motor nativo de volumen individual

Estas ruedas son para Python 3.12/macOS ARM64 y Python 3.13/Windows x64.
El creador selecciona por ABI y plataforma y comprueba SHA-256 antes de instalar.
En otros intérpretes busca la rueda oficial compatible; el volumen local solo se
muestra cuando el motor lo soporta. No se afirma soporte del fork para otras ABI.
El código para recompilar está en ../../third-party/ntgcalls-volume1-source.zip,
con la licencia y los avisos de terceros. No hay datos de cuentas ni claves.

La versión es 3.0.5+tgascii.volume1, derivada del tag oficial v3.0.5.
No se transmiten muestras de audio por el IPC de producción. Se mantiene el
mezclador nativo; solo se aplica ganancia a la fuente seleccionada antes de él.
