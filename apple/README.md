# TeleGraph para móviles y relojes

Esta rama reúne la interfaz de Android, iPhone y iPad, la app de Wear OS y el código de Apple Watch de TeleGraph 3.0.1. Consulta la versión en `pyproject.toml`. El número de compilación está en `build-number`. [Instalación y descargas](https://github.com/MiguelCKxd/TeleGraph)

## Preparar la versión 3.0.1 en macOS

El proyecto utiliza Briefcase, un entorno de Python para el núcleo, Android SDK y Xcode. El núcleo de escritorio se obtiene desde un clon Git. Desde el directorio que contiene los dos clones, prepara las rutas.

```sh
git clone --branch nucleo-movil-v3.0.1 https://github.com/MiguelCKxd/TeleGraph escritorio
git clone --branch apple-v3.0.1-build2 https://github.com/MiguelCKxd/TeleGraph movil
export TG_ASCII_DESKTOP="$PWD/escritorio"
export TG_ASCII_CORE_REF=nucleo-movil-v3.0.1
cd movil
```

- Usa un entorno que contenga PyTgCalls 3.0.0 y fija `TG_ASCII_DESKTOP_PYTHON` a su intérprete. Prepara Briefcase en `../beeware-venv/`. Configura en `tools/build.sh` la ubicación de `ANDROID_HOME` y del intérprete para tu máquina. Las ruedas Android incluidas están en el directorio `wheels/`.
- Crea tu propia identidad de aplicación de Telegram. El sincronizador lee los campos `id` y `hash` desde `~/.tg-ascii-lite/api.json`. Restringe los permisos de ese archivo a tu usuario. La compilación genera localmente la configuración que necesita el cliente. Para usar otra identidad de iOS elige un archivo privado con `TELEGRAPH_IOS_API_CONFIG`.
- Ejecuta `tools/build.sh android debug` para Android, `APP=tg_ascii_watch tools/build.sh android debug` para Wear OS o `tools/build.sh iOS debug` para el simulador. Para el funcionamiento independiente de watchOS también hace falta un framework Python compatible con reloj.
- Las llamadas avanzadas del teléfono usan `TELEGRAPH_ANDROID_CALLS_AAR` o `TELEGRAPH_IOS_CALLS_FRAMEWORK`, según la plataforma. El archivo de iOS con reloj independiente requiere además `TELEGRAPH_WATCH_PYTHON_FRAMEWORK`. La generación completa de esos frameworks precisa herramientas y dependencias adicionales.
- Para firmar tus propias compilaciones, configura una clave Android o un equipo de Apple y tus identificadores de aplicación. El equipo para iOS se indica con `TELEGRAPH_APPLE_TEAM`. La entrega oficial para iPhone y Apple Watch usa TestFlight.

Los pasos anteriores describen la preparación de la versión 3.0.1. El archivo `LICENSE` recoge las condiciones del proyecto móvil. Los componentes externos mantienen sus avisos de licencia.
