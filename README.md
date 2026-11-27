# TeleGraph 3.4.2

TeleGraph es un cliente independiente de Telegram para ordenadores, teléfonos, tabletas y relojes. En Apple TV puedes leer las conversaciones que elijas compartir desde el iPhone.

La compilación **3.4.2 (1)** recibió un mismo mensaje de prueba en un iPhone y un iPad físicos con la aplicación cerrada: dos muestras previas y una posterior por dispositivo confirmaron la ausencia del proceso principal. Los avisos se observaron en el Centro de notificaciones. Es evidencia de esta versión y de la configuración comprobada; no garantiza todas las cuentas, redes o ajustes del sistema ni identifica por sí sola toda la ruta del proveedor. La foto del remitente y un defecto en los resultados de los diálogos nativos de iOS quedan pendientes para 3.4.2.1, como se detalla abajo.

Las fuentes Apple usan la compilación **1** de 3.4.2 para iOS, iPadOS, Apple Watch y la extensión de notificaciones. Android, Wear OS y tvOS usan también la compilación **1**. Las ramas y los recibos de 3.4.1 se conservan como referencia histórica; las fuentes Apple vigentes están en `apple-v3.4.2-build1`. Esta numeración no significa que los paquetes estén distribuidos.

## Novedades de 3.4.2

Se corrige una carrera de inicialización de los puentes Siri/TV que podía impedir el arranque en iOS. Al volver a la aplicación, la recuperación del servidor de la interfaz se serializa para evitar escuchas simultáneas. La recepción con la aplicación cerrada se ha comprobado en iPhone e iPad con esta compilación final.

El gestor de descargas muestra progreso y estados, permite cancelar y reintentar, y ofrece las acciones de abrir, guardar o compartir que admite cada plataforma. Limita las transferencias simultáneas y las colas, comprueba el contexto de la cuenta y respeta las restricciones de los archivos. Los reintentos empiezan desde cero; no se anuncia reanudación por bloques ni continuidad garantizada cuando el sistema suspende la aplicación.

Apariencia y Personalización incorporan controles independientes de tamaño de texto, espaciado, disposición y colores. En móviles también puedes ajustar zonas de texto, interlineado, altura de controles, líneas de previsualización, alineación de burbujas y visibilidad de avatares, horas y contadores. Se conservan las vistas previas, la persistencia y el restablecimiento de ajustes.

En iOS 26 o posterior, Liquid Glass nativo se amplía a más controles del compositor y de navegación. Sigue desactivado por defecto y respeta las preferencias de accesibilidad. Una opción independiente, también desactivada inicialmente, ofrece diálogos del sistema operativos en Android. En iOS esa opción tiene la incidencia de procesamiento de resultados descrita abajo; no se presenta como soporte completo. Los formularios que necesitan controles adicionales conservan su interfaz habitual.

El indicador de desconexión se integra en la cabecera sin reservar un hueco permanente y permite reintentar la conexión. Representa la conexión de la cuenta a Telegram, no el estado de APNs. La interfaz conserva mejor el texto, el foco y el desplazamiento durante las actualizaciones. En Android se corrige la reserva del espacio del teclado, tanto en la ventana principal como en las ventanas de chat.

La preparación de las fotos de notificaciones renueva copias antiguas sin sustituir una miniatura más reciente por una caducada. Una pausa acotada tras errores evita repetir la misma descarga fallida con cada actualización del chat; un cambio de foto invalida esa pausa. Sin embargo, la foto del remitente no apareció en la prueba física final aunque se había cargado en su perfil. La entrega del mensaje sí funcionó; la presentación de la foto se corregirá en 3.4.2.1.

La revisión reduce trabajo repetido en consultas, actualizaciones de geometría y progreso. Estas mejoras se han comprobado en recorridos y pruebas concretos; no equivalen a una reducción global medida de batería, CPU, memoria o tráfico de red.

El selector de logos conserva los diseños propios de TeleGraph y las imágenes del usuario. Se ha retirado el catálogo de imágenes oficiales de Telegram; las selecciones antiguas de ese catálogo usan el logo propio. Los avatares conservan su comportamiento.

Se mantienen los filtros de fotos/vídeos, originales opcionales, envío SD/HD o como archivo original, temas y debates vinculados, llamadas y demás funciones anteriores.

## Pendientes conocidos y alcance de verificación

Dos incidencias se han aplazado expresamente a **3.4.2.1**, conservando esta compilación:

- En iOS, los resultados de Cancelar y también Confirmar/Continuar en diálogos nativos pueden interpretarse como no soportados y abrir después el formulario HTML de respaldo. Los diálogos nativos son opcionales y pueden desactivarse desde Ajustes; no se anuncia un soporte completo libre de este defecto.
- La foto del remitente no se mostró en los avisos de la prueba física final, pese a haberla preparado desde el perfil. La recepción con la app cerrada se comprobó por separado y sí funcionó.

La prueba de recepción utilizó un único mensaje autorizado observado en ambos dispositivos. No acredita por separado banners ni una nueva prueba con el proceso vivo solo en segundo plano. El teclado software físico y el recorrido final de exportación de archivos en iPhone no quedaron comprobados. Las pruebas anteriores de navegador, emulador y simulador conservan su alcance original; no se presentan como nuevas pruebas físicas.

El login y el cierre normal del portátil Windows se verificaron. El Setup extraído tiene el mismo contenido y mostró el login, pero su cierre normal no quedó acreditado; la limpieza posterior de su proceso de QA no cuenta como esa comprobación. Tampoco hay prueba física de Apple TV ni cobertura completa de VoiceOver, paisaje y todas las versiones antiguas del sistema.

## Instalación e inicio de sesión

Los paquetes y versiones publicados se consultan en las [descargas del proyecto](https://github.com/MiguelCKxd/TeleGraph/releases). La disponibilidad en TestFlight depende del estado del canal de Apple; la recepción interna y la revisión externa son pasos diferentes. Las instrucciones siguientes describen la instalación de los paquetes de cada plataforma.

Abre la aplicación, introduce tu número con prefijo internacional y escribe el código que te envíe Telegram. Si tienes activada la verificación en dos pasos, introduce también tu contraseña. Cada dispositivo mantiene su propia sesión.

| Plataforma | Paquete e instalación |
| --- | --- |
| Windows x64 | Ejecuta el instalador Setup o extrae el ZIP portátil completo y abre `TG-ASCII.exe`. El paquete actual carece de firma Authenticode. |
| Mac con Apple Silicon | Extrae el ZIP `darwin-arm64` y copia la aplicación a Aplicaciones. El paquete actual lleva firma ad hoc. |
| Linux | Para Debian y Ubuntu, instala el DEB de tu arquitectura con `sudo apt install ./TeleGraph-3.4.2-linux-amd64.deb` o `sudo apt install ./TeleGraph-3.4.2-linux-arm64.deb`. También hay un ZIP portátil para cada arquitectura. |
| Android | Instala el APK de teléfono o tableta de la versión publicada. Las actualizaciones requieren conservar la firma y el identificador de la aplicación. |
| Wear OS | Instala el APK de reloj correspondiente. La edición Legacy permite actualizar una instalación anterior con el identificador `org.tgas.wear`, conservando su firma. |
| iPhone, iPad y Apple Watch | El proyecto incluye la aplicación de reloj. Usa TestFlight cuando la compilación esté habilitada en ese canal. La IPA de distribución permite conservar y verificar el paquete; no sustituye la instalación gestionada por Apple. Para una compilación propia necesitas firma y perfiles válidos. La configuración de firma y de APNs afecta a notificaciones y extensiones. |
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

Si creas una distribución propia, registra tu aplicación en Telegram e incorpora su identidad al compilar. Guarda las credenciales, las claves de firma y la configuración del proveedor push fuera del repositorio. El estado de verificación de esta versión se resume en este README; las guías de cada carpeta conservan también notas del momento en que se prepararon sus fuentes. Puedes compilar desde las carpetas del snapshot o desde las ramas indicadas en SOURCE-REVISIONS cuando estén disponibles en el remoto. [Registro de aplicaciones en Telegram](https://core.telegram.org/api/obtaining_api_id)

## Licencias

Consulta la [licencia del proyecto móvil](android-wear/LICENSE) y los [avisos de componentes de escritorio](desktop/third-party/). Las licencias y los avisos de las cuatro ediciones se conservan en sus carpetas.

## Privacidad y soporte

Puedes consultar cómo se tratan los datos, administrar las sesiones y solicitar la eliminación de la cuenta. [Privacidad de TeleGraph](PRIVACIDAD.md) · [Soporte del proyecto](https://github.com/MiguelCKxd/TeleGraph/issues)
