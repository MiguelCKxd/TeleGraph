# TeleGraph 3.0 para iPhone, iPad y Apple Watch con API propia

Esta rama contiene las fuentes del IPA descargable de TeleGraph 3.0.0 (1). El iPhone o iPad solicita el **API ID** y el **API hash** de tu aplicación de Telegram la primera vez que abres TeleGraph. Si eliges la conexión independiente en Apple Watch, introduce ambas claves también en el reloj. [Descarga del IPA](https://github.com/MiguelCKxd/TeleGraph/releases/download/v3.0.0/TeleGraph-iOS-3.0.0-1.ipa) · [Configuración e instalación](docs/IPA-CON-API-PROPIA.md)

## Compilar

Usa un Mac con Xcode e instala Briefcase y las dependencias nativas que se describen en la guía. Prepara un clon de la aplicación y otro de su núcleo de escritorio.

```sh
git clone --branch escritorio-v3.0.0 https://github.com/MiguelCKxd/TeleGraph escritorio
git clone --branch apple-ipa-v3.0.0 https://github.com/MiguelCKxd/TeleGraph movil
export TG_ASCII_DESKTOP="$PWD/escritorio"
export TG_ASCII_CORE_REF=escritorio-v3.0.0
cd movil
```

Indica tu equipo de firma con `TELEGRAPH_APPLE_TEAM`, el intérprete que contiene PyTgCalls 3.0.0 con `TG_ASCII_DESKTOP_PYTHON` y los frameworks de dispositivo con `TELEGRAPH_WATCH_PYTHON_FRAMEWORK` y `TELEGRAPH_IOS_CALLS_FRAMEWORK`. El proyecto busca Briefcase en `../beeware-venv/`. Configura los identificadores y perfiles de Apple para tu propia distribución.

```sh
tools/export_public_ios.sh dist/personal-api
```

El exportador genera un IPA firmado en el directorio indicado. Las compilaciones iOS de esta rama también activan la configuración con API propia cuando se usa `tools/build.sh iOS debug`. La variante oficial que se distribuye mediante TestFlight tiene su propia revisión. [Fuentes de TestFlight](https://github.com/MiguelCKxd/TeleGraph/tree/apple-v3.0.0-build1)

## Ejecutar las pruebas

Desde la raíz del clon móvil, activa un entorno Python 3.12 con las dependencias del escritorio y ejecuta el módulo de pruebas. La variable `TG_ASCII_DESKTOP` debe apuntar al clon preparado arriba.

```sh
python -m pip install -r "$TG_ASCII_DESKTOP/requirements-build.txt"
PYTHONPATH="$PWD/src:$TG_ASCII_DESKTOP" python -m unittest discover -s tests -p 'test_public_credentials.py' -v
```

Las pruebas usan datos sintéticos para comprobar la configuración inicial, la edición de las claves, el arranque posterior y el acceso al Llavero. La prueba de CoreFoundation requiere macOS. El archivo [LICENSE](LICENSE) recoge las condiciones del proyecto.
