# Personaliza TG-ASCII / Customize TG-ASCII

Abre **Ajustes → Personalizar** para mover, redimensionar, duplicar, ocultar o
añadir controles. Los cambios de posición se guardan como proporciones, para
adaptarse al tamaño de la ventana. Mayús + arrastrar cambia el tamaño.

**Ajustes / recuperar**, en la barra superior, siempre queda fuera del editor.
Desde ahí puedes restaurar la interfaz predeterminada o abrir la carpeta de
diseños. Las cuentas y los mensajes se conservan.

Esta carpeta contiene:

- `active.json`: diseño que se carga al abrir la app.
- `layout.json`: ejemplo de la distribución inicial.
- `contact-card.json`: ejemplo importable de apariencia de las fichas de contacto.
- `motion.json`: duración, desplazamiento y recursos de las animaciones.
- `layouts/`: diseños guardados, seleccionables desde Ajustes.
- `history/`: copias anteriores de los diseños.
- `trash/`: recursos y diseños retirados que puedes recuperar.
- `resources/images/`, `icons/`, `animations/`, `menus/`, `buttons/` y `fonts/`:
  archivos propios para la interfaz. Los menús declarativos usan entradas
  `{"text": "Actualizar", "action": "refresh"}`.

`resources/fonts/` permite organizar tus archivos de fuentes. No se cargan
automáticamente: instala la fuente en el sistema y selecciónala en Ajustes.
La interfaz usa una fuente instalada de ancho fijo si la elegida no está disponible.

Tras editar los archivos, usa **Recargar archivos**. Importar un recurso crea
una copia propia. Los archivos son datos, no scripts: la personalización no
ejecuta Python ni JavaScript. Las posiciones y los menús propios son locales;
la sincronización de Telegram sólo se aplica a las opciones que admite su API.

**Ajustes → Personalización → Apariencia de la ficha de contacto** permite
cambiar densidad, ancho preferido (320–1200 px), avatar (48–192 px), alineación,
colores y borde (0–8 px). Los colores vacíos heredan el tema de la app; los
botones heredan sus efectos globales. También puedes ordenar u ocultar secciones
y acciones. Ajustes y Gestionar siguen accesibles para recuperar la ficha.
**Restaurar ficha predeterminada** repone sólo estas opciones; **Restaurar interfaz
predeterminada** repone también el resto del diseño.

Estas opciones `contact_*` se guardan en `preferences.json`, junto a esta carpeta,
y en `appearance` al guardar un diseño. Puedes editar `contact-card.json` e
importarlo desde Diseños, o añadir las mismas claves a `active.json` y pulsar
**Recargar archivos**. Usa Guardar diseño para conservar la distribución actual
junto a la ficha: el ejemplo comienza con la distribución predeterminada.
Los identificadores admitidos están en el ejemplo. Ocultar una sección cambia
su presentación local; no consulta información oculta ni modifica los datos del
contacto. Son opciones locales incluso con la sincronización activada.

---

Open **Settings → Customize** to move, resize, duplicate, hide or add controls.
Positions are proportional to the containing panel. Hold Shift while dragging
to resize. **Settings / recovery** remains outside the editable area; restoring
defaults keeps accounts and messages.

`active.json` is the active design, `layout.json` is the default example, and
`motion.json` controls movement. Saved designs live in `layouts/`, previous
designs in `history/`, and recoverable removed files in `trash/`. Place images,
icons, animations, declarative menus, buttons and fonts inside their respective
`resources/` folders. Menu entries use objects such as
`{"text": "Refresh", "action": "refresh"}`.

`resources/fonts/` stores your font files for convenience. Fonts are not loaded
automatically: install the font in your operating system, then choose it in
Settings. Unavailable font families fall back to an installed fixed-width font.

Choose **Reload files** after editing. Imported resources become owned copies.
Files are data and cannot execute Python or JavaScript. Widget positions and
custom menus remain local; Telegram synchronization covers supported API
settings only.

**Settings → Customization → Contact card appearance** changes density, preferred
width (320–1200 px), avatar (48–192 px), alignment, colors, border (0–8 px), and
section/action order and visibility. Blank colors inherit the app theme; buttons
keep global effects. Settings and Manage remain accessible. The dedicated reset
restores just the card; the global interface reset includes these choices.

`contact_*` choices live in the adjacent `preferences.json` and saved designs'
`appearance`. Import `contact-card.json` as an editable example, or add its keys
to `active.json` then reload files. Save a design first to keep your current
layout: the example starts with the default layout. These settings remain local
regardless of the synchronization toggle and never reveal unavailable data.
