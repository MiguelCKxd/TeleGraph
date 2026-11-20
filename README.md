# TeleGraph

TeleGraph es un cliente independiente de Telegram para Windows, macOS, Linux, Android, iPhone, iPad, Wear OS y Apple Watch. Este repositorio publica las versiones de TeleGraph **desde la 3.0.0 en adelante**.

[Descargar TeleGraph 3.0.1](https://github.com/MiguelCKxd/TeleGraph/releases/tag/v3.0.1) · [Ver las publicaciones](https://github.com/MiguelCKxd/TeleGraph/releases)

## Instalar la versión 3.0.1

| Sistema | Archivo o canal | Instalación |
|---|---|---|
| Windows x64 | `TeleGraph-3.0.1-Setup.exe` o ZIP portátil | Cierra la app y abre el instalador. En la edición portátil, extrae el ZIP completo y abre `TG-ASCII.exe`. |
| macOS con Apple Silicon | `TeleGraph-3.0.1-darwin-arm64.zip` | Extrae el ZIP y copia `TG-ASCII.app` a Aplicaciones. Si ya usas la aplicación desde otra carpeta, ciérrala y sustituye esa copia en su ubicación habitual. |
| Linux ARM64 o x86-64 | Paquete Debian o ZIP de tu arquitectura | En Debian o Ubuntu ejecuta `sudo apt install ./TeleGraph-3.0.1-linux-arm64.deb` o `sudo apt install ./TeleGraph-3.0.1-linux-amd64.deb`. Para la edición portátil, extrae el ZIP y abre `TG-ASCII`. |
| Teléfonos y tabletas Android | `TeleGraph-Android-3.0.1-1.apk` | Abre el archivo en el dispositivo y sigue la instalación de Android. |
| Wear OS | `TeleGraph-WearOS-3.0.1-1.apk` o `TeleGraph-WearOS-Legacy-3.0.1-1.apk` | Instala el APK en el reloj. La edición principal comparte identificador con el teléfono. La edición Legacy permite conservar el acceso de una instalación con el identificador `org.tgas.wear`. |
| iPhone, iPad y Apple Watch | [TestFlight](https://testflight.apple.com/join/7MPAJP37) y [IPA 3.0.1 (2)](https://github.com/MiguelCKxd/TeleGraph/releases/download/v3.0.1/TeleGraph-iOS-3.0.1-2.ipa) | TestFlight gestiona la instalación de la beta. Para instalar el IPA de GitHub directamente, usa una firma y perfiles de Apple válidos para tus dispositivos. Incluye Apple Watch. Al abrir la app, inicia sesión con tu cuenta de Telegram. El IPA incorpora la identidad de aplicación de TeleGraph. Una firma alternativa puede afectar a las notificaciones y a los permisos de las extensiones. |

El paquete de macOS lleva firma ad hoc. El instalador de Windows se distribuye sin firma Authenticode. Puedes verificar la integridad de los archivos con la lista SHA-256 que acompaña a la descarga.

## Código fuente

El código fuente de la etiqueta 3.0.1 incluye las carpetas de escritorio, Android y Apple. El IPA de GitHub y la compilación de TestFlight se preparan desde la misma fuente de Apple. Los paquetes móviles utilizan la revisión del núcleo compartido [nucleo-movil-v3.0.1](https://github.com/MiguelCKxd/TeleGraph/tree/nucleo-movil-v3.0.1). Para ejecutar el sincronizador del núcleo, sigue las instrucciones de la guía de plataforma desde los clones Git.

| Entrega | Fuentes incluidas | Revisión publicada |
|---|---|---|
| Escritorio | [Guía y código de escritorio](desktop/) | [escritorio-v3.0.1](https://github.com/MiguelCKxd/TeleGraph/tree/escritorio-v3.0.1) |
| Android y Wear OS | [Guía y código del teléfono y del reloj](android-wear/) | [movil-v3.0.1-build1](https://github.com/MiguelCKxd/TeleGraph/tree/movil-v3.0.1-build1) |
| iPhone, iPad y Apple Watch | [Guía y código de la compilación para Apple](apple/) | [apple-v3.0.1-build2](https://github.com/MiguelCKxd/TeleGraph/tree/apple-v3.0.1-build2) |

Para preparar la demo de escritorio con datos de muestra, usa Python con Tk y sigue el README de escritorio. Para iniciar sesión en una compilación propia, configura el identificador y el hash de tu aplicación de Telegram. La guía móvil detalla los requisitos de Briefcase, las herramientas de Android y Apple y los componentes de llamadas.

## Licencias

Las condiciones del proyecto móvil están en el [archivo de licencia](android-wear/LICENSE). Las dependencias y los motores nativos conservan los avisos de sus respectivos autores. [Avisos de los componentes de escritorio](desktop/third-party/)
