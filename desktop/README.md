# TeleGraph para escritorio

Esta rama contiene el código de escritorio de TeleGraph 3.0. La versión del árbol figura en `pyproject.toml`. Para instalar la aplicación, elige la descarga que corresponda a tu sistema. [Descargas](https://github.com/MiguelCKxd/TeleGraph/releases)

## Primer inicio en las descargas de escritorio de GitHub

En Windows, macOS y Linux, abre TeleGraph e introduce el **API ID** y el **API hash** de tu aplicación de Telegram. El botón **my.telegram.org/apps** abre el sitio de Telegram donde puedes registrar o consultar tu aplicación. A continuación, inicia sesión en tu cuenta por el procedimiento habitual. [Administrar tu aplicación](https://my.telegram.org/apps)

La casilla para recordar las claves es opcional. Si la marcas, TeleGraph guarda la identidad de aplicación en un archivo privado de tu perfil local, sin cifrar, una vez completado el inicio de sesión. Si la dejas desmarcada tendrás que volver a introducir las claves la próxima vez que abras el programa.

En Debian o Ubuntu, instala el archivo de tu arquitectura con `sudo apt install ./TeleGraph-3.0.0.1-linux-amd64.deb` para un PC Intel/AMD o `sudo apt install ./TeleGraph-3.0.0.1-linux-arm64.deb` para ARM64. APT conserva las actualizaciones de instalaciones existentes.

## Compilar la versión 3.0

Usa un Python con Tk, instala las dependencias descritas abajo y ejecuta `python tools/build_release.py --user-api --output releases` para construir la edición pública. El empaquetador excluye el módulo con las credenciales del editor. Al iniciar la aplicación, el usuario introduce su propia API. En Windows, la arquitectura del intérprete determina la de la descarga.

Para trabajar con los tres chats de demostración, prepara un entorno virtual con Python 3.12 y Tk.

```sh
python -m pip install -r requirements-build.txt
python tools/prepare_renderers.py
python run.py --demo
```

Para empaquetar esa misma demo desde el entorno preparado, ejecuta `python tools/build_release.py --demo-only`. Puedes ejecutar las pruebas con `python -m unittest discover -s tests`. Las pruebas gráficas necesitan una sesión de escritorio. En Linux, los scripts de empaquetado documentan los paquetes del sistema para Tk, audio y notificaciones.

El motor de llamadas, sus componentes nativos y los avisos de sus autores se encuentran en `third-party/` y `tools/native-wheels/` en las versiones que los incluyen. [Información sobre el proyecto y sus versiones](https://github.com/MiguelCKxd/TeleGraph)
