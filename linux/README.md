# TeleGraph para escritorio

Esta rama contiene el código de escritorio de TeleGraph 3.1.0. La versión del árbol figura en `pyproject.toml`. Para instalar la aplicación, elige la descarga que corresponda a tu sistema. [Descargas](https://github.com/MiguelCKxd/TeleGraph/releases)

## Primer inicio en las descargas de escritorio de GitHub

Abre TeleGraph, introduce tu número con prefijo internacional y el código que te envíe Telegram. Si activaste la verificación en dos pasos, introduce también tu contraseña. Cada instalación guarda su propia sesión.

En Debian o Ubuntu, instala el archivo de tu arquitectura con `sudo apt install ./TeleGraph-3.1.0-linux-amd64.deb` para un PC Intel/AMD o `sudo apt install ./TeleGraph-3.1.0-linux-arm64.deb` para ARM64. APT conserva las actualizaciones de instalaciones existentes.

## Compilar la versión 3.1

Para crear tu distribución, registra tu aplicación en Telegram, prepara el entorno Python y ejecuta `python tools/build_release.py --output releases`. El empaquetador incorpora la identidad que le proporciones al compilar. Las personas que instalen tu distribución accederán con su cuenta. [Registrar una aplicación](https://core.telegram.org/api/obtaining_api_id).

Para trabajar con los tres chats de demostración, prepara un entorno virtual con Python 3.12 y Tk.

```sh
python -m pip install -r requirements-build.txt
python tools/prepare_renderers.py
python run.py --demo
```

Para empaquetar esa misma demo desde el entorno preparado, ejecuta `python tools/build_release.py --demo-only`. Puedes ejecutar las pruebas con `python -m unittest discover -s tests`. Las pruebas gráficas necesitan una sesión de escritorio. En Linux, los scripts de empaquetado documentan los paquetes del sistema para Tk, audio y notificaciones.

El motor de llamadas, sus componentes nativos y los avisos de sus autores se encuentran en `third-party/` y `tools/native-wheels/` en las versiones que los incluyen. [Información sobre el proyecto y sus versiones](https://github.com/MiguelCKxd/TeleGraph)
