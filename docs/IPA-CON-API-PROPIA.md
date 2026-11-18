# IPA para iPhone, iPad y Apple Watch con API propia

La descarga de GitHub incluye el teléfono y el reloj y permite utilizar tu propia aplicación de Telegram. TestFlight distribuye la compilación oficial con la identidad del proyecto ya configurada.

## Configurar la aplicación

1. Obtén el **API ID** y el **API hash** de tu aplicación en [Telegram](https://my.telegram.org/apps).
2. Abre TeleGraph en el iPhone o iPad. Introduce ambos valores en el primer formulario, pulsa **Guardar** y continúa con el inicio de sesión de Telegram. Desde la pantalla de teléfono puedes volver a editar las credenciales.
3. Si utilizas la conexión independiente de Apple Watch, abre la configuración de conexión en el reloj y rellena allí los mismos campos. En modo vinculado, el reloj accede a los datos mediante el iPhone.

Cada dispositivo guarda las credenciales en su propio Llavero mientras está desbloqueado. El secreto se oculta en el formulario. Al cambiar de firma o de identificador, Apple puede asignar un contenedor y un Llavero distintos. En ese caso hay que volver a configurar la API e iniciar sesión. Si se conserva el contenedor y su sesión, la aplicación comprueba con Telegram si esa sesión sigue autorizada.

Los avisos remotos dependen de que las credenciales de proveedor de Apple asociadas a tu aplicación en Telegram correspondan al identificador y entorno APNs de la aplicación firmada. Introducir el API ID y el API hash permite iniciar sesión. La entrega de avisos con otra identidad de aplicación requiere configurar también APNs.

## Firma e instalación

El IPA de GitHub se exportó con una firma de distribución de App Store. Para instalar directamente, firma el teléfono, el reloj y el código anidado con perfiles compatibles con tus dispositivos. Cuando cambies los identificadores, asigna uno propio al teléfono y a la app de reloj, y haz que `WKCompanionAppBundleIdentifier` apunte al del teléfono. Conserva los derechos que admitan tus perfiles. Para el proceso habitual de instalación de la beta, abre la invitación publicada de TestFlight.

## Compilar desde las fuentes

Utiliza macOS con Xcode, el entorno de Briefcase de este proyecto y las dependencias nativas de la versión. Configura el checkout de la fuente de escritorio en `TG_ASCII_DESKTOP`, su revisión de la 3.0 en `TG_ASCII_CORE_REF` y, si tienes los frameworks en otra ubicación, define `TELEGRAPH_WATCH_PYTHON_FRAMEWORK` y `TELEGRAPH_IOS_CALLS_FRAMEWORK`. La firma requiere identidades y perfiles locales para el par de aplicaciones.

Desde la raíz de [esta rama del IPA](https://github.com/MiguelCKxd/TeleGraph/tree/apple-ipa-v3.0.0), ejecuta el exportador.

```sh
tools/export_public_ios.sh dist/personal-api
```

El script activa `TG_ASCII_PUBLIC_API=1`, genera el proyecto, construye el archivo de Xcode y exporta el IPA a disco. Esa modalidad omite en el teléfono y en el reloj los módulos generados con credenciales del editor. La exportación limpia en una copia los recursos de pruebas de CPython, las herramientas de consola y las rutas privadas de compilación. Después vuelve a firmar los componentes afectados y comprueba las firmas finales. Al terminar muestra el SHA-256 del archivo. Las firmas de Apple y los metadatos de exportación pueden diferir entre equipos y fechas.

Para repetir la exportación desde un archivo existente compilado en la modalidad de API propia, pasa el directorio de destino y el `.xcarchive` como segundo argumento. El script rechaza los módulos de credenciales del editor y conserva el archivo original.

```sh
tools/export_public_ios.sh dist/nueva-exportacion /ruta/al/archivo.xcarchive
```
