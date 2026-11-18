# TeleGraph para escritorio

Esta rama contiene el código de escritorio de TeleGraph 3.0. La versión del árbol figura en `pyproject.toml`. Para instalar la aplicación, elige la descarga que corresponda a tu sistema. [Descargas](https://github.com/MiguelCKxd/TeleGraph/releases)

## Compilar la versión 3.0

En macOS, usa un Python con Tk y abre `Crear-Mac.command`. En Windows, usa `Crear-Windows.cmd` y elige la arquitectura del intérprete. El resultado queda en `releases/`. El empaquetador solicita el identificador y el hash de tu propia aplicación de Telegram. Guárdalos fuera de Git. También admite las variables de entorno `TG_APP_API_ID` y `TG_APP_API_HASH`.

Para trabajar con los tres chats de demostración, prepara un entorno virtual con Python 3.12 y Tk.

```sh
python -m pip install -r requirements-build.txt
python tools/prepare_renderers.py
python run.py --demo
```

Para empaquetar esa misma demo desde el entorno preparado, ejecuta `python tools/build_release.py --demo-only`. Puedes ejecutar las pruebas con `python -m unittest discover -s tests`. Las pruebas gráficas necesitan una sesión de escritorio. En Linux, los scripts de empaquetado documentan los paquetes del sistema para Tk, audio y notificaciones.

El motor de llamadas, sus componentes nativos y los avisos de sus autores se encuentran en `third-party/` y `tools/native-wheels/` en las versiones que los incluyen. [Información sobre el proyecto y sus versiones](https://github.com/MiguelCKxd/TeleGraph)
