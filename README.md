# TeleGraph 3.4

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

## Novedades de la 3.4

Compartido contigo permite ver fotos, vídeos o ambos y conserva ese filtro al recorrer la galería y cargar elementos anteriores. El visor reproduce vídeos por rangos, limita la memoria de sus cachés y cancela lecturas al cerrar. Si «Ir al mensaje» necesita conexión, conserva la imagen abierta y permite reintentarlo cuando vuelva la red.

En Funciones complejas puedes activar los originales del servidor en el visor; la opción empieza desactivada y las previsualizaciones siguen siendo reducidas. Los originales conservan los bytes disponibles en Telegram: no recuperan información que el remitente haya comprimido. Al enviar fotos puedes elegir SD, HD u Original como archivo; los vídeos conservan su archivo original, sin un nuevo selector de color HDR/SDR.

El gesto de volver en iOS admite empezar más adentro de la pantalla. Las transiciones mantienen el diseño estable al entrar en conversaciones y restaurar borradores. En iOS 26 o posterior puedes activar Liquid Glass nativo desde Funciones complejas; empieza apagado y respeta las opciones de accesibilidad del sistema.

Apariencia incorpora opciones de composición, controles, navegación, colores, cabeceras, separadores y tamaños. Personalización conserva los ajustes existentes de forma: las fotos de perfil móviles vuelven a ser cuadradas inicialmente y los avatares sin foto mantienen su tratamiento habitual. Puedes restablecer Apariencia, Personalización o todos los ajustes sin cerrar tus cuentas.

La revisión de recursos reduce conversiones de vídeo, limita las colas y elimina trabajo que seguía activo después de cerrar pantallas. También corrige respuestas tardías al cambiar de cuenta, transferencias canceladas, reintentos de mensajes secretos y la limpieza de medios temporales. Las notificaciones móviles reintentan el registro si falla, lo renuevan y permiten consultar su estado desde Ajustes.

Se conservan los temas, debates vinculados, llamadas, ventanas y demás funciones de la versión anterior.

## Instalación e inicio de sesión

En los paquetes de TeleGraph, abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión. [Descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases)

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta `TeleGraph-3.4.0-Setup.exe` o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El instalador carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae `TeleGraph-3.4.0-darwin-arm64.zip` y copia la aplicación a Aplicaciones. El paquete lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.4.0-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.4.0-linux-arm64.deb`. También hay un ZIP portátil para cada arquitectura. |
| Android | Instala `TeleGraph-Android-3.4.0-1.apk` en el teléfono o la tableta. |
| Wear OS | Instala `TeleGraph-WearOS-3.4.0-1.apk` en el reloj. Utiliza la edición Legacy para actualizar una instalación anterior con el identificador `org.tgas.wear`. |
| iPhone, iPad y Apple Watch | La compilación 3.4.0 (1) incluye el reloj. Para instalar el IPA por tu cuenta necesitas firma y perfiles de Apple válidos para tus dispositivos. La firma alternativa puede afectar al push y a las extensiones. Consulta los datos de compatibilidad en las notas de esta versión. |
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
