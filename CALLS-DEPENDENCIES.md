# Dependencias opcionales de llamadas

La señalización grupal usa py-tgcalls 3.0.0 (Lauren Iraci), con licencia LGPL 3 incluida en `third-party/py-tgcalls-3.0.0-LICENSE.txt`. Repositorio original: https://github.com/pytgcalls/pytgcalls . La aplicación fija la versión y adapta su interfaz mediante `GroupMediaEngine`; no modifica los archivos instalados de la biblioteca.

La parte multimedia usa NTgCalls 3.0.5 en Windows y macOS y 3.0.7 en Linux. El motor se ejecuta en un proceso auxiliar que no recibe sesiones ni claves de Telegram. Los identificadores de llamada y participantes son metadatos necesarios para el transporte multimedia.

En macOS se consulta AVFoundation para obtener formatos reales de cámara y solicitar permisos del sistema. Los efectos se abren desde el proceso que captura la cámara. La compatibilidad efectiva de cada efecto depende del dispositivo y del motor nativo; todavía no se ha verificado toda la interfaz de efectos de macOS.

El empaquetador incluye py-tgcalls y sus metadatos y licencia mediante `collect-all` y `copy-metadata`. Las llamadas grupales se cargan al usarlas; no se inicia un capturador al abrir la aplicación.

NTgCalls 3.0.5 incluye su licencia en `third-party/ntgcalls-3.0.5-LICENSE.txt`. Repositorio original: https://github.com/pytgcalls/ntgcalls . PyTgCalls conserva su código original. Para el volumen local por participante se incluye el fork de NTgCalls `3.0.5+tgascii.volume1`, con ganancia por SSRC antes de la mezcla nativa. Su código fuente completo seleccionado, licencias e instrucciones están en `third-party/ntgcalls-volume1-source.zip`; las ruedas y sus SHA-256 están en `tools/native-wheels/manifest.json`. El audio sigue dentro del motor nativo y no cruza el IPC de Python.
