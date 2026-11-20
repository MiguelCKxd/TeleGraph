# TeleGraph 3.1

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

## Instalación e inicio de sesión

En los paquetes de TeleGraph, abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión. [Descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases)

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta `TeleGraph-3.1.0-Setup.exe` o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El instalador carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae `TeleGraph-3.1.0-darwin-arm64.zip` y copia la aplicación a Aplicaciones. El paquete lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.1.0-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.1.0-linux-arm64.deb`. También hay un ZIP portátil para cada arquitectura. |
| Android | Instala `TeleGraph-Android-3.1.0-1.apk` en el teléfono o la tableta. |
| Wear OS | Instala `TeleGraph-WearOS-3.1.0-1.apk` en el reloj. Utiliza la edición Legacy para actualizar una instalación anterior con el identificador `org.tgas.wear`. |
| iPhone, iPad y Apple Watch | La compilación 3.1.0 (1) incluye el reloj. Para instalar el IPA por tu cuenta necesitas firma y perfiles de Apple válidos para tus dispositivos. La firma alternativa puede afectar al push y a las extensiones. El perfil de esta compilación aún carece del permiso de mensajería de CarPlay. |
| Apple Vision Pro | Se probó la aplicación de iPad en el simulador visionOS 27.2. |
| Apple TV | La edición de tvOS requiere un iPhone con TeleGraph. Abre «Conectar con el iPhone» en el televisor y selecciona en el iPhone los chats que quieres compartir. El IPA de tvOS se firma para Apple TV. |

## Compilar el proyecto

| Plataforma | Fuente |
| --- | --- |
| Windows y macOS | [Escritorio](desktop/) |
| Linux | [Edición Linux](linux/) |
| Android y Wear OS | [Teléfono y reloj](android-wear/) |
| iOS, iPadOS y watchOS | [Edición de Apple](apple/) |
| tvOS | [Proyecto para Apple TV](apple/tv/) |

Si creas una distribución propia, registra tu aplicación en Telegram e incorpora su identidad al compilar. Las guías de plataforma detallan las herramientas y dependencias. [Registro de aplicaciones en Telegram](https://core.telegram.org/api/obtaining_api_id)

## Licencias

Consulta la [licencia del proyecto móvil](android-wear/LICENSE) y los [avisos de componentes de escritorio](desktop/third-party/).
