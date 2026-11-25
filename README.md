# TeleGraph 3.2 para móviles, relojes y Apple TV

Las aplicaciones de teléfono y reloj comparten el núcleo de escritorio de TeleGraph. El proyecto tvOS muestra los chats que se eligen en un iPhone o iPad vinculado. Esta rama corresponde a la versión 3.2.0, compilación 1.

## Preparar el código

Desde una misma carpeta, clona el escritorio y esta rama. El sincronizador selecciona la revisión de núcleo usada por esta versión.

```sh
git clone --branch escritorio-v3.2 https://github.com/MiguelCKxd/TeleGraph escritorio
git clone --branch movil-v3.2-build1 https://github.com/MiguelCKxd/TeleGraph movil
cd movil
export TG_ASCII_DESKTOP="$PWD/../escritorio"
```

Prepara Briefcase en `../beeware-venv/`. Indica con `TG_ASCII_DESKTOP_PYTHON` el intérprete que contiene PyTgCalls 3.0.0. El sincronizador copia el núcleo y esa dependencia al directorio de compilación. Para contribuir al proyecto desde otro clon del escritorio, usa `TG_ASCII_DESKTOP`. La revisión predeterminada es `32a1d27580b49cc50107e11c355c4af9d6afb82e`.

Para generar tu propio cliente, registra tu aplicación en Telegram y guarda los campos `id` y `hash` en un JSON privado. El sincronizador lo lee desde `TELEGRAPH_API_CONFIG` o desde `~/.tg-ascii-lite/api.json`. Para configurar otra identidad en iPhone, usa `TELEGRAPH_IOS_API_CONFIG`. Quien instala la aplicación compilada introduce su teléfono, el código de Telegram y, si procede, su contraseña de verificación en dos pasos. [Registro de aplicaciones en Telegram](https://core.telegram.org/api/obtaining_api_id)

## Android y Wear OS

Configura `ANDROID_HOME` con la ubicación del Android SDK y comprueba que `python3.22` está en el `PATH` para Chaquopy. Las ruedas adicionales de Python están en `wheels/`. Puedes compilar los dos destinos desde la carpeta móvil.

```sh
tools/build.sh android debug
APP=tg_ascii_watch tools/build.sh android debug
```

Para recibir notificaciones mediante Firebase, indica tu configuración con `TELEGRAPH_FIREBASE_CONFIG`. Para las funciones de llamada que dependen del AAR personalizado, indica su archivo con `TELEGRAPH_ANDROID_CALLS_AAR`. Para empaquetar una edición de distribución con tu firma, indica en `TELEGRAPH_ANDROID_SIGNING_CONFIG` un archivo privado de shell que defina `TGAS_KEYSTORE`, `TGAS_KEY_ALIAS`, `TGAS_STORE_PASSWORD` y `TGAS_KEY_PASSWORD`. Ejecuta `tools/package_android.sh`. La variante anterior de Wear OS se selecciona con `APP=tg_ascii_watch WEAR_LEGACY=1`.

## iPhone, iPad y Apple Watch

Genera el proyecto con `tools/build.sh iOS prepare` o compila para el simulador con `tools/build.sh iOS debug`. Para las llamadas configura `TELEGRAPH_IOS_CALLS_FRAMEWORK` y para el reloj independiente `TELEGRAPH_WATCH_PYTHON_FRAMEWORK`. Para firmar, establece `TELEGRAPH_APPLE_TEAM` y configura tus identificadores y perfiles. La mensajería en CarPlay requiere aprobación de Apple para tu aplicación y se activa durante la compilación con `TELEGRAPH_CARPLAY=1`.

## Apple TV

Abre `tv/TeleGraphTV.xcodeproj` en Xcode, selecciona el esquema `TeleGraphTV` y un simulador de Apple TV. El proyecto Swift de tvOS se compila directamente con Xcode. Este comando comprueba el destino de simulador con Xcode y el SDK tvOS instalados.

```sh
xcodebuild -project tv/TeleGraphTV.xcodeproj -scheme TeleGraphTV \
  -configuration Debug -destination 'generic/platform=tvOS Simulator' build
```

Para usar el vínculo en tus dispositivos, firma tvOS e iOS con el mismo equipo e identificador de aplicación y conserva la declaración del servicio `telegraph-companion` en las dos plataformas. Abre TeleGraph en el iPhone o iPad desbloqueado. En el Apple TV elige **Conectar con el iPhone**. En el menú de un chat en el teléfono, elige **Mostrar en Apple TV** y confirma. El televisor permite leer los textos recientes compartidos. Los chats secretos, mensajes protegidos y mensajes temporales quedan excluidos. Puedes desconectar desde cualquiera de las dos aplicaciones.

Para generar el Android App Bundle de Google Play junto al APK de teléfono, añade `--aab` a la invocación de `tools/package_android.sh`.
