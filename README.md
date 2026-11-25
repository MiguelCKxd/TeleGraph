# TeleGraph 3.2

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

## Novedades de la 3.2

En teléfono y tableta, el menú «+» abre la grabadora de voz. La galería permite ampliar, recorrer fotos y vídeos, ver las fotos de perfil anteriores y utilizar los menús del sistema para guardar y compartir los archivos permitidos. Puedes asignar acciones distintas a cada sentido del gesto sobre un chat, buscar ajustes y desactivar las previsualizaciones de fotos.

Los grupos reúnen los mensajes consecutivos de una persona y muestran su nombre y avatar. Cuando Telegram facilita la fecha, las herramientas del mensaje muestran cuándo se leyó o editó. La nueva versión también incorpora fuentes del sistema, más controles numéricos y búsquedas recientes por cuenta. Las llamadas en curso pueden continuar en segundo plano en los clientes con motor de llamadas. El vídeo utiliza PiP del sistema donde está disponible o una ventana compacta de escritorio.

## Instalación e inicio de sesión

En los paquetes de TeleGraph, abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión. [Descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases)

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta `TeleGraph-3.2.0-Setup.exe` o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El instalador carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae `TeleGraph-3.2.0-darwin-arm64.zip` y copia la aplicación a Aplicaciones. El paquete lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.2.0-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.2.0-linux-arm64.deb`. También hay un ZIP portátil para cada arquitectura. |
| Android | Instala `TeleGraph-Android-3.2.0-1.apk` en el teléfono o la tableta. |
| Wear OS | Instala `TeleGraph-WearOS-3.2.0-1.apk` en el reloj. Utiliza la edición Legacy para actualizar una instalación anterior con el identificador `org.tgas.wear`. |
| iPhone, iPad y Apple Watch | La compilación 3.2.0 (1) incluye el reloj. Para instalar el IPA por tu cuenta necesitas firma y perfiles de Apple válidos para tus dispositivos. La firma alternativa puede afectar al push y a las extensiones. Consulta los datos de compatibilidad en las notas de esta versión. |
| Apple Vision Pro | Usa la edición compatible de iPad. |
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

## Privacidad y soporte

Puedes consultar cómo se tratan los datos, administrar las sesiones y solicitar la eliminación de la cuenta. [Privacidad de TeleGraph](PRIVACIDAD.md) · [Soporte del proyecto](https://github.com/MiguelCKxd/TeleGraph/issues)
