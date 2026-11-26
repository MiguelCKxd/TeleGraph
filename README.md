# TeleGraph 3.4.1 — candidato local

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

**La 3.4.1 está retenida y no se ha publicado.** Falta confirmar la recepción real de notificaciones push con la aplicación cerrada en el iPhone. Las mejoras del registro y del diagnóstico no demuestran por sí solas que esa recepción funcione. La compilación iOS enviada para diagnóstico interno no se ofrece aquí como descarga ni como distribución externa. Este snapshot permite revisar y compilar las fuentes; no anuncia una versión lista para entregar.

## Novedades del candidato 3.4.1

El gestor de descargas muestra progreso y estados, permite cancelar y reintentar, y ofrece las acciones de abrir, guardar o compartir que admite cada plataforma. Limita las transferencias simultáneas y las colas, comprueba el contexto de la cuenta y respeta las restricciones de los archivos. Los reintentos empiezan desde cero; no se anuncia reanudación por bloques ni continuidad garantizada cuando el sistema suspende la aplicación.

Apariencia y Personalización incorporan controles independientes de tamaño de texto, espaciado, disposición y colores. En móviles también puedes ajustar zonas de texto, interlineado, altura de controles, líneas de previsualización, alineación de burbujas y visibilidad de avatares, horas y contadores. Se conservan las vistas previas, la persistencia y el restablecimiento de ajustes.

En iOS 26 o posterior, Liquid Glass nativo se amplía a más controles del compositor y de navegación. Sigue desactivado por defecto y respeta las preferencias de accesibilidad. Una opción independiente, también desactivada inicialmente, permite usar diálogos nativos compatibles en iOS y Android; los formularios que necesitan controles adicionales conservan su interfaz habitual.

El indicador de desconexión ocupa un espacio estable en la cabecera y permite reintentar la conexión. Representa la conexión de la cuenta a Telegram, no el estado de APNs. La interfaz conserva mejor el texto, el foco y el desplazamiento durante las actualizaciones. En Android se corrige la reserva del espacio del teclado, tanto en la ventana principal como en las ventanas de chat.

La revisión reduce trabajo repetido en consultas, actualizaciones de geometría y progreso. Estas mejoras se han comprobado en recorridos y pruebas concretos; no equivalen a una reducción global medida de batería, CPU, memoria o tráfico de red.

El selector de logos conserva los diseños propios de TeleGraph y las imágenes del usuario. Se ha retirado el catálogo de imágenes oficiales de Telegram; las selecciones antiguas de ese catálogo usan el logo propio. Los avatares conservan su comportamiento.

Se mantienen los filtros de fotos/vídeos, originales opcionales, envío SD/HD o como archivo original, temas y debates vinculados, llamadas y demás funciones anteriores.

## Instalación e inicio de sesión

Los candidatos 3.4.1 de este snapshot todavía no se distribuyen. Las instrucciones siguientes sirven para una distribución compilada y firmada con la configuración correspondiente. Las versiones ya publicadas se consultan en las [descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases).

Abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión.

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta el instalador Setup o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El candidato actual carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae el ZIP `darwin-arm64` y copia la aplicación a Aplicaciones. El candidato actual lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.4.1-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.4.1-linux-arm64.deb`. También se puede generar un ZIP portátil para cada arquitectura. |
| Android | Instala el APK de teléfono o tableta que hayas compilado. Las actualizaciones requieren conservar la firma y el identificador de la aplicación. |
| Wear OS | Instala el APK de reloj correspondiente. La edición Legacy permite actualizar una instalación anterior con el identificador `org.tgas.wear`, conservando su firma. |
| iPhone, iPad y Apple Watch | El proyecto incluye la aplicación de reloj. Para instalar tu propia compilación necesitas firma y perfiles de Apple válidos para tus dispositivos. La configuración de firma y de APNs afecta a las notificaciones y a las extensiones. No se ofrece la IPA diagnóstica interna. |
| Apple Vision Pro | Usa la edición compatible de iPad. |
| Apple TV | La edición de tvOS requiere un iPhone con TeleGraph. Abre «Conectar con el iPhone» en el televisor y selecciona en el iPhone los chats que quieres compartir. La compilación de tvOS se firma para Apple TV. |

## Compilar el proyecto

Las cuatro carpetas proceden exclusivamente de las revisiones públicas indicadas en [SOURCE-REVISIONS.json](SOURCE-REVISIONS.json). Las guías de cada plataforma explican herramientas, dependencias y configuración de compilación.

| Plataforma | Fuente y guía |
| --- | --- |
| Windows y macOS | [Escritorio](desktop/README.md) |
| Linux | [Edición Linux](linux/README.md) |
| Android y Wear OS | [Teléfono y reloj](android-wear/README.md) |
| iOS, iPadOS y watchOS | [Edición de Apple](apple/README.md) |
| tvOS | [Proyecto para Apple TV](apple/tv/) y [guía de Apple](apple/README.md#apple-tv) |

Si creas una distribución propia, registra tu aplicación en Telegram e incorpora su identidad al compilar. Guarda las credenciales, las claves de firma y la configuración del proveedor push fuera del repositorio. Las ramas de este candidato todavía son locales; para compilar antes de su publicación utiliza las carpetas del snapshot en lugar de intentar clonarlas desde el remoto. [Registro de aplicaciones en Telegram](https://core.telegram.org/api/obtaining_api_id)

## Licencias

Consulta la [licencia del proyecto móvil](android-wear/LICENSE) y los [avisos de componentes de escritorio](desktop/third-party/). Las licencias y los avisos de las cuatro ediciones se conservan en sus carpetas.

## Privacidad y soporte

Puedes consultar cómo se tratan los datos, administrar las sesiones y solicitar la eliminación de la cuenta. [Privacidad de TeleGraph](PRIVACIDAD.md) · [Soporte del proyecto](https://github.com/MiguelCKxd/TeleGraph/issues)
