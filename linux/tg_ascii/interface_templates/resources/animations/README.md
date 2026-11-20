# Animaciones de interfaz / Interface animations

Desde **Ajustes → Movimiento y animaciones → Importar animación** puedes elegir
un GIF, APNG, PNG o WebP propio. La app guarda una copia en la carpeta
`interface/resources/animations` de tus datos. El archivo original se conserva.

Abre **Ajustes → Abrir carpeta de diseños** para encontrar esta carpeta.
Puedes añadir tus archivos allí y escribir, por ejemplo,
`animations/mi-indicador.webp` en el campo del indicador de respuesta.
En `interface/motion.json`, el campo correspondiente es
`events.swipe_reply.asset`. Usa **Recargar archivos** después de editarlo.

El archivo `motion.json` de este ejemplo conserva el movimiento predeterminado.
`enabled` activa las animaciones de interfaz; `events.swipe_reply.enabled`
activa sólo su movimiento de respuesta; `gesture_enabled` permite desactivar
el gesto por separado. `duration_ms` cambia la duración del regreso,
`distance` la distancia visual y `threshold` el recorrido necesario para
responder. `easing` acepta `linear`, `ease-out` o `ease-in-out`.
El archivo se interpreta como datos: no admite scripts.

**Restaurar valores iniciales** recupera el movimiento original sin borrar
los archivos importados. El gestor de archivos de personalización permite
retirar recursos y recuperarlos desde la papelera.

---

Use **Settings → Motion and animations → Import animation** to choose a GIF,
APNG, PNG or WebP. An owned copy goes into your data folder under
`interface/resources/animations`; the original remains intact.

Open **Settings → Open design folder** to locate it. You can add a file there
and enter a relative path such as `animations/my-indicator.webp` in the reply
indicator field or `events.swipe_reply.asset` in `interface/motion.json`.
Choose **Reload files** after editing.

This example's `motion.json` preserves the default movement. `enabled` controls
interface animation; `events.swipe_reply.enabled` controls reply feedback;
`gesture_enabled` controls the swipe gesture separately. `duration_ms` sets
return duration, `distance` sets visual travel, and `threshold` sets how far
to swipe to reply. Supported `easing` values are `linear`, `ease-out` and
`ease-in-out`. Files are interpreted as data and cannot run scripts.

**Restore defaults** keeps imported files. The customization file manager can
move resources to recoverable trash.
