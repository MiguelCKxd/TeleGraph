# TeleGraph 3.3

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

## Novedades de la 3.3

Los grupos con temas permiten abrir General o una conversación concreta, consultar los no leídos y mantener cada mensaje y borrador en su tema. Según tus permisos, puedes crear, renombrar, fijar, cerrar, reabrir u ocultar temas. Las búsquedas, los mensajes programados y los reenvíos respetan el tema elegido. Desde un canal puedes acceder a su grupo de debate vinculado y a los comentarios de sus publicaciones.

El botón «Ir al mensaje» de la galería abre y destaca la foto o vídeo original, incluso fuera del historial cargado, en un tema o en un comentario. Añadir una reacción ya no muestra una edición nueva del mensaje y conserva la fecha de una edición real que el cliente haya recibido.

Las transiciones entre pantallas, menús y ventanas son breves y respetan la preferencia de animaciones y la reducción de movimiento del sistema. En móvil, la señal de desconexión queda integrada en la cabecera, sin el aviso inferior duplicado. Apple Watch y Wear OS permiten elegir un tema; el iPhone puede compartir un tema concreto con el Apple TV.

Se han retirado la interfaz de terminal antigua y las funciones sustituidas sin uso en las aplicaciones actuales. Las funciones de la versión 3.2 se conservan.

## Instalación e inicio de sesión

En los paquetes de TeleGraph, abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión. [Descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases)

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta `TeleGraph-3.3.0-Setup.exe` o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El instalador carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae `TeleGraph-3.3.0-darwin-arm64.zip` y copia la aplicación a Aplicaciones. El paquete lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.3.0-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.3.0-linux-arm64.deb`. También hay un ZIP portátil para cada arquitectura. |
| Android | Instala `TeleGraph-Android-3.3.0-1.apk` en el teléfono o la tableta. |
| Wear OS | Instala `TeleGraph-WearOS-3.3.0-1.apk` en el reloj. Utiliza la edición Legacy para actualizar una instalación anterior con el identificador `org.tgas.wear`. |
| iPhone, iPad y Apple Watch | La compilación 3.3.0 (1) incluye el reloj. Para instalar el IPA por tu cuenta necesitas firma y perfiles de Apple válidos para tus dispositivos. La firma alternativa puede afectar al push y a las extensiones. Consulta los datos de compatibilidad en las notas de esta versión. |
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
