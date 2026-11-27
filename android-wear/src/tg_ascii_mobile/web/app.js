'use strict';
/* TeleGraph mobile interface. All Telegram work happens in the Python core
   (the desktop's tg_ascii package); this file only draws it and forwards
   taps. Interface texts are the desktop's Spanish keys, translated by the
   core's i18n (34 languages) through /api/strings. */

const Q = new URLSearchParams(location.search);
const TOKEN = Q.get('t') || '';
const PLATFORM = Q.get('platform') || '';
// Desktop "Complex features" (on by default on mobile): Ajustes › Funciones complejas.
const feature = (key) => !(typeof state !== 'undefined' && state.settings && state.settings.advanced_features
  && state.settings.advanced_features[key] === false);
// A chat in its own system window (iPadOS scene, Android task): only that chat.
const WINDOW_CHAT = Q.get('window') === '1' && /^-?\d+$/.test(Q.get('chat') || '') ? Number(Q.get('chat')) : null;
const WINDOW_ACCOUNT = WINDOW_CHAT === null ? null : Q.get('account') || '!';
const resourceAuth = () => 't=' + encodeURIComponent(TOKEN) +
  (WINDOW_ACCOUNT === null ? '' : '&window_account=' + encodeURIComponent(WINDOW_ACCOUNT));
const unavailableWindow = () => WINDOW_ACCOUNT !== null && WINDOW_ACCOUNT !== state.account;
// The iOS app running on a Mac: pointer, keyboard and resizable windows.
const MAC = Q.get('mac') === '1';
const TOUCH = (PLATFORM === 'Android' || PLATFORM === 'iOS') && !MAC;
// iPad, Mac and wide windows: chat list beside the conversation.
// View setting (Settings › Appearance › View): automatic, single or double.
const WIDE = () => {
  if (WINDOW_CHAT !== null) return false;  // a system window shows only its chat
  const layout = (typeof state !== 'undefined' && state.appearance && state.appearance.layout) || 'auto';
  if (layout === 'single') return false;
  return innerWidth >= (layout === 'double' ? 560 : 760);
};
// The list covers the whole width (dragged over the chat): chats open full screen.
const listCoversAll = () => { const width = Number((state.appearance || {}).side_width) || 0; return width >= 2 && width >= innerWidth - 160; };
// Safe areas measured by the native shell (iOS); CSS env() is the fallback.
for (const [name, value] of [['--top', Q.get('top')], ['--bottom', Q.get('bottom')]]) {
  if (value && Number(value) > 0) document.documentElement.style.setProperty(name, Number(value) + 'px');
}
const QUICK = ['👍', '❤', '😂', '😮', '😢', '🔥', '👏', '🎉'];

const KEYS = [
  'Photos and videos', 'All', 'Videos', 'SD · Standard', 'HD · High quality', 'Original as file',
  'Share screen', 'Stop sharing screen', 'Picture in Picture', 'Picture in Picture is unavailable.',
  'Conectando...', 'Sin conexion', 'En linea', 'Reintentar', 'Iniciar sesion', 'Numero de telefono',
  'Include + and your country calling code. Example: +1 202 555 0123', 'Continuar',
  'Entrar con codigo QR', 'Codigo de Telegram', 'Te hemos enviado el codigo a Telegram o por SMS.',
  'Contraseña de verificacion en dos pasos', 'Escanea este codigo desde Telegram en otro dispositivo: Ajustes > Dispositivos > Vincular dispositivo.',
  'Volver', 'Chats', 'Buscar', 'Ajustes', 'Archivados', 'Cuentas', 'No hay chats.', 'No hay mensajes en este chat.', 'Cargando...',
  'Escribe un mensaje', 'Enviar', 'Responder', 'Copiar', 'Editar', 'Eliminar', 'Eliminar para todos',
  'Reenviar', 'Fijar', 'Desfijar', 'Silenciar', 'Activar sonido', 'Archivar', 'Desarchivar',
  'Marcar como no leido', 'Marcar como leido', 'Cancelar', 'Copiado.', 'Editando mensaje', 'Respondiendo a',
  'Mensaje', 'Chat', 'Reenviar a...', 'Enviado.', 'Pendiente de envio', 'No enviado', 'Quitar',
  'Mensajes anteriores', 'Idioma', 'Tema', 'Oscuro', 'Claro', 'Sistema', 'Tamaño de letra',
  'Enter envia mensajes', 'Mostrar el texto solo en ASCII', 'Mostrar segundos en la hora',
  'Guardar una copia para usar sin conexion', 'Burbujas', 'Apariencia', 'Mensajes', 'Datos de la app',
  'Borrar caché', 'Borrar todos los datos', 'Caché', 'Liberado: {size}', 'Añadir cuenta', 'Cerrar sesion',
  'Alias', 'Usar', 'Subir', 'Acerca de', 'Version', '¿Cerrar la sesion de esta cuenta en este dispositivo?',
  '¿Borrar todos los datos? Se cerraran todas las sesiones de este dispositivo.', 'Activado', 'Desactivado',
  'Hoy', 'Ayer', 'Tu', 'editado', 'reenviado', 'Error', 'Accion guardada; se enviara al volver la conexion.',
  'Buscar en el chat', 'Sin resultados.', 'Nombre visible solo en este dispositivo', 'Guardar',
  'Este chat es de solo lectura.', 'Reaccionar', 'Más', 'Adjuntar', 'Foto', 'Vídeo', 'Archivo', 'Enviando...',
  'Contactos', 'Nuevo chat', 'Carpetas', 'Todos los chats', 'Saved Messages', 'Search in Telegram', 'Profile',
  'Phone number', 'Username', 'Bio', 'Members', 'Member', 'Owner', 'Administrator', 'Open chat', 'Open', 'Play', 'Typing…', 'Draft',
  'Send without sound', 'Schedule message', 'Open link', 'Copy link', 'Introduce un @usuario o telefono internacional.', 'Join',
  'Accent color', 'Unlimited local pins (device only)', 'Move pin up', 'Move pin down', 'Monochrome', 'Audio',
  'Select', 'Clear history', 'Delete chat', 'Leave', 'Vote', 'Retract vote', 'Pinned messages', 'App lock', 'Lock now',
  'Unlock', 'My profile', 'First name', 'Last name', 'Notificaciones', 'Reactions', 'Poll', 'Go to message', 'Save',
  'Saved.', 'Contraseña incorrecta', 'PIN o contraseña', 'Repetir',
  'Preview', 'Mark as read', 'Preview: not marked as read', 'Gallery', 'Camera', 'Contact', 'Block', 'Unblock',
  'Add contact', 'Edit contact', 'Delete contact', 'Groups in common', 'Shared media', 'Photos', 'Files', 'Links',
  'Voice messages', 'Save to Saved Messages', 'Question', 'Answer', 'Add answer', 'Multiple answers', 'Quiz',
  'Anonymous', 'Correct answer', 'Share contact', 'Create', 'Information',
  'Text color', 'Background color', 'Bubble corners', 'Button corners', 'Menu corners', 'Interface background image',
  'Chat background', 'Remove background', 'Custom app icon', 'Image', 'Default', 'Light', 'Orange', 'Blue', 'Red', 'Pink',
  'Brightness', 'Typeface', 'Use the interface background', 'Remove', 'Reconnect', 'Restart the app', 'Quit Tg-As',
  'Use device authentication', 'Change app password', 'Enable app lock', 'Disable app lock', 'The passwords do not match.',
  'Incorrect app password.', 'Unlock your messages', 'Remember this password. It is separate from your Telegram password and cannot be recovered.',
  'Confirm', 'Close chat', 'Open chat in new window', 'Windows', 'Choose account',
  'Choose account at startup when several are saved', 'Lock after', 'Immediately', '1 minute', '5 minutes', '1 hour',
  'Single view', 'Double view', 'Automatic', 'Reset panel sizes', 'Dock to the side', 'Float', 'Minimize', 'View',
  'Funciones complejas', 'Watch with its own connection',
  'The watch connects to Telegram by itself, with its own session approved by this app, and keeps working with the phone off. Off: the watch shows what this app receives.',
  'Android keeps TG-ASCII connected with a permanent notification, so new messages arrive with the app closed. Uses more battery.',
  'Iniciar chat secreto', 'Clave de cifrado y autodestrucción',
  'Rotar clave ahora (PFS)', 'Cerrar chat secreto', 'Desactivado',
  'Unmute microphone', 'Mute microphone', 'Stop camera', 'Start camera', 'Stop sharing screen', 'Share screen',
  'Disable reminder', 'Remind me', 'Lower hand', 'Raise hand', 'Conference call', 'Group call',
  'Search results', 'Recent', 'Favorites', 'Pack saved', 'Save pack', 'Verified', 'Bot', 'Scam', 'Fake',
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
  'Group', 'Channel', 'User', 'Biografia', 'Description', 'Linked discussion / channel',
  'Accept calls', 'Accept secret chats',
  'Unirse / salir', 'Diseño del perfil',
];

const S = {};
const t = (key, vars) => {
  let text = S[key] || key;
  // Keep existing translation keys and the actual Downloads folder name.
  if (key !== 'Saved to Downloads/TG-ASCII.' && /TG-ASCII|Tg-As/.test(key)) {
    text = text.replace(/TG-ASCII|Tg-As/g, 'TeleGraph');
  }
  if (vars) for (const [name, value] of Object.entries(vars)) text = text.replace('{' + name + '}', value);
  return text;
};

const state = {
  stage: 'loading', error: '', connection: 'connecting', accounts: [], settings: {}, version: '',
  chats: [], archived: null, view: 'chats', open: null, reply: null, editing: null, search: '',
  qr: null, busy: false, selected: null, forwarding: null, results: null, attachments: [], uploading: 0, formats: {}, formatBar: false,
  folders: [], folder: null, global: null, contacts: null, profile: null, drafts: {},
  customEmoji: {}, locked: false, lock_enabled: false, selection: null, accountRevision: 0, me: null, keepUnlocked: false,
  list: 'chats', shared: null, appearance: {}, lock: {}, windows: [],
};

// -- plumbing -----------------------------------------------------------------
// Calls that create something are not repeated (a lost answer could mean done).
const NO_RETRY = new Set(['native_dialog', 'download_open', 'download_cancel', 'download_retry', 'react', 'window_send', 'send_article', 'send_checklist', 'save_to_saved', 'share_contacts', 'bot_button', 'forum_create', 'forum_manage', 'contact_photo', 'suggest_birthday', 'forum_send', 'forum_forward', 'move_pin', 'scheduled_action', 'account.add', 'login.qr', 'restart', 'reset_settings', 'report_message', 'apply_chat_wallpaper', 'publish_story', 'voice_start', 'voice_stop', 'notify_reset', 'group_call_action', 'group_call_manage', 'send', 'send_files', 'send_voice', 'send_sticker', 'send_poll', 'poll_answer', 'poll_close', 'send_contact', 'forward', 'forward_many', 'create_group', 'create_community', 'member_admin', 'member_restrict', 'members_add', 'set_discussion', 'group_change', 'call_action', 'secret_start', 'secret_ttl', 'secret_rekey', 'secret_screenshot', 'secret_discard']);
async function api(method, params = {}) {
  const revision = state.accountRevision;
  let response;
  for (let attempt = 0; ; attempt++) {
    try {
      if (attempt && state.accountRevision !== revision) throw new Error(t('Reconnecting…'));
      response = await fetch('/api/' + method.replace(/\./g, '_'), {
        method: 'POST', headers: {'X-TG-Token': TOKEN, 'Content-Type': 'application/json',
          ...(WINDOW_ACCOUNT === null ? {} : {'X-TG-Window-Account': WINDOW_ACCOUNT})},
        body: JSON.stringify(params),
      });
      break;
    } catch (error) {
      // The app's local server is being restored (back from the background): wait and retry.
      if (attempt >= 6 || NO_RETRY.has(method) || state.accountRevision !== revision) throw new Error(t('Reconnecting…'));
      await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)));
    }
  }
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || t('Error'));
  return data.result;
}

// None of these handlers cancels the gesture. Passive listeners let the browser
// scroll at once instead of waiting for the page's script on every touch.
const PASSIVE_EVENTS = new Set(['touchstart', 'touchmove', 'wheel', 'scroll']);
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key.startsWith('on')) {
      const type = key.slice(2);
      node.addEventListener(type, value, PASSIVE_EVENTS.has(type) ? { passive: true } : undefined);
    }
    else if (key === 'html') node.innerHTML = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  if (tag === 'input' && attrs?.type === 'search') installSearchHistory(node);
  const role = attrs?.role;
  if ((role === 'button' || role === 'link') && attrs.onclick && tag !== 'button' && tag !== 'a') {
    if (attrs.tabindex == null) node.tabIndex = 0;
    node.addEventListener('keydown', (event) => {
      if (event.target !== node || (event.key !== 'Enter' && (role !== 'button' || event.key !== ' '))) return;
      event.preventDefault();
      if (!event.repeat) node.click();
    });
  }
  return node;
}

// Pictures served by the app (avatars, previews, custom emoji) load a few at a
// time, the ones on screen (or about to be) first. The web view opens only six
// connections to the app and one is the event stream: without a limit, slow
// first downloads took them all and every tap waited behind them.
const IMAGE_SLOTS = 3;
const imageQueue = new Set();
const imagesToWatch = new Set();
const imageObservers = new Map();
let imagesLoading = 0, imageWatchFrame = 0;
function pumpImages() {
  const ready = [...imageQueue].reverse();  // the most recently shown first
  for (const img of ready) {
    if (imagesLoading >= IMAGE_SLOTS) return;
    imageQueue.delete(img);
    const src = img.dataset.src;
    if (!src || !img.isConnected) continue;
    img.lazyObserver?.unobserve(img);
    delete img.dataset.src;
    imagesLoading++;
    let released = false;
    const release = () => {
      if (released) return;
      released = true; clearTimeout(timer); imagesLoading--;
      img.removeEventListener('load', release); img.removeEventListener('error', release);
      pumpImages();
    };
    const timer = setTimeout(release, 15000);  // a stuck download frees its turn
    img.addEventListener('load', release); img.addEventListener('error', release);
    img.src = src;
  }
}
function imageObserver(root) {
  let observer = imageObservers.get(root);
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) imageQueue.add(entry.target); else imageQueue.delete(entry.target);
      }
      pumpImages();
    }, { root, rootMargin: keepLoaded() ? '1800px 0px' : '900px 0px' });
    imageObservers.set(root, observer);
    for (const [key, pending] of imageObservers) if (key && !key.isConnected) {
      pending.disconnect(); imageObservers.delete(key);
    }
  }
  return observer;
}
function watchImagesNow() {
  imageWatchFrame = 0;
  for (const img of imagesToWatch) {
    imagesToWatch.delete(img);
    if (!img.dataset.src || !img.isConnected) continue;
    const root = img.closest('.scroll, .winbody') || null;
    if (img.lazyObserver && img.lazyRoot === root) continue;
    img.lazyObserver?.unobserve(img);
    img.lazyRoot = root; img.lazyObserver = imageObserver(root);
    img.lazyObserver.observe(img);
  }
}
function watchImage(img) {
  imagesToWatch.add(img);
  if (!imageWatchFrame) imageWatchFrame = requestAnimationFrame(watchImagesNow);
}
// Pictures still waiting inside redrawn content (rows reused in a new list).
function watchImages(scope) {
  if (!scope) return;
  for (const img of scope.querySelectorAll('img[data-src]')) watchImage(img);
}
// Complex features › Keep more loaded (off by default): work like an installed
// messaging app. Pictures stay in the web view, the core asks Telegram only
// for what is new, each chat reopens where it was left.
const keepLoaded = () => !!(state.settings?.advanced_features?.keep_loaded);
const photoIds = new Map();      // chat -> its current photo id (from the list)
const chatPlaces = new Map();    // chat -> distance from the newest message when it was left
function rememberChatPlace() {
  const open = state.open, box = document.getElementById('scroll');
  if (!open || !box || open.thread || !keepLoaded()) return;
  const distance = box.scrollHeight - box.scrollTop - box.clientHeight;
  if (distance > 120) chatPlaces.set(state.account + ':' + open.peer, distance);
  else chatPlaces.delete(state.account + ':' + open.peer);
  while (chatPlaces.size > 50) chatPlaces.delete(chatPlaces.keys().next().value);
}

function lazySrc(img, src) {
  if (!('IntersectionObserver' in window)) { img.src = src; return img; }
  img.dataset.src = src;
  watchImage(img);
  return img;
}

const button = (label, action, extra = '') => h('button', { class: 'btn ' + extra, onclick: action }, label);
function symbolButton(symbol, label, action, disabled = false) {
  const node = h('button', { class: 'btn', 'aria-label': label, onclick: action, disabled }, symbol);
  return window.tgPresentation?.iconize(node, symbol) || node;
}
const backButton = () => symbolButton('<', t('Volver'), back);

// Line icons in the style of Telegram's own (sticker with a peeled corner, smiley, microphone).
const ICON_PATHS = {
  sticker: '<path d="M6 3h8.5L21 9.5V18a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z"/><path d="M14.5 3v3.5a3 3 0 0 0 3 3H21"/><path d="M8.5 14.5c1.6 1.8 4.4 1.8 6 0"/><circle cx="9" cy="10" r=".6" fill="currentColor"/><circle cx="14" cy="10" r=".6" fill="currentColor"/>',
  emoji: '<circle cx="12" cy="12" r="9"/><path d="M8.3 14.2c2 2.3 5.4 2.3 7.4 0"/><circle cx="9" cy="10" r=".7" fill="currentColor"/><circle cx="15" cy="10" r=".7" fill="currentColor"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v3"/>',
  format: '<path d="M4 19 9.5 5h1L16 19"/><path d="M6.3 14h7.4"/><path d="M17.5 19v-6.5a2.2 2.2 0 0 1 4.4 0V19"/>',
};
const icon = (name) => h('span', { class: 'icon', 'aria-hidden': 'true', html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + ICON_PATHS[name] + '</svg>' });
const iconButton = (name, label, action, extra = '') => h('button', { class: 'btn bare icon-button ' + extra, onclick: action, title: label, 'aria-label': label }, icon(name));
let toastTimer = null;
function toast(text, kind = '') {
  const node = document.getElementById('toast');
  node.textContent = text; node.className = kind; node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 3200);
}
async function attempt(work, done) {
  try { const result = await work(); if (done) done(result); return result; }
  catch (error) { toast(error.message, 'error'); }
}

// The desktop's palettes (themes.py) and custom colours (appearance.app_palette).
const PALETTES = {
  dark: { bg: '#08100c', panel: '#0e1b13', text: '#8cf5a6', muted: '#80a98c', line: '#294d34', selected: '#284f35', strong: '#bdffcd' },
  light: { bg: '#f4f8f3', panel: '#ffffff', text: '#14532d', muted: '#4a6854', line: '#b2c9b7', selected: '#d4ebd9', strong: '#0b4521' },
};
function blend(a, b, weight) {
  return '#' + [1, 3, 5].map((i) => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - weight) + parseInt(b.slice(i, i + 2), 16) * weight)
    .toString(16).padStart(2, '0')).join('');
}
const FONTS = { courier: '"Courier New", Courier, monospace', sans: 'system-ui, -apple-system, Roboto, "Segoe UI", sans-serif',
  serif: 'Georgia, "Times New Roman", serif', system: 'system-ui, sans-serif', sf: '-apple-system, BlinkMacSystemFont, system-ui, sans-serif',
  rounded: 'ui-rounded, -apple-system, system-ui, sans-serif', humanist: '"Trebuchet MS", Roboto, sans-serif',
  classic: 'Palatino, "Palatino Linotype", serif', book: 'Georgia, "Noto Serif", serif', mono: 'ui-monospace, Menlo, "Roboto Mono", monospace',
  // 3.2 · Apple system faces (San Francisco and New York), shown on Apple devices.
  sf_rounded: 'ui-rounded, "SF Pro Rounded", -apple-system, system-ui, sans-serif',
  sf_mono: 'ui-monospace, "SF Mono", Menlo, monospace', new_york: 'ui-serif, "New York", Georgia, serif',
  sf_compact: '"SF Compact", "SF Compact Text", -apple-system, system-ui, sans-serif',
  // 3.2 · Android system families (fonts.xml aliases): no download needed.
  condensed: '"sans-serif-condensed", "Roboto Condensed", "Arial Narrow", sans-serif',
  light: '"sans-serif-light", "Roboto Light", system-ui, sans-serif', medium: '"sans-serif-medium", "Roboto Medium", system-ui, sans-serif',
  noto_serif: '"Noto Serif", serif', typewriter: '"serif-monospace", "Cutive Mono", "Courier New", monospace',
  casual: 'casual, "Coming Soon", "Comic Sans MS", cursive', handwriting: '"Dancing Script", cursive',
  smallcaps: '"sans-serif-smallcaps", "Carrois Gothic SC", sans-serif' };
// Which typefaces each system offers in Appearance (all keys stay valid everywhere).
// SF Compact ships with Apple Watch only; elsewhere it exists if the user installed it.
// Measured once: a different width than the fallback means the family is present.
function fontInstalled(family) {
  try {
    const context = document.createElement('canvas').getContext('2d');
    const sample = 'mmmmmmmmmmlli WW 0123';
    return ['monospace', 'serif'].some(fallback => {
      context.font = '32px ' + fallback;
      const plain = context.measureText(sample).width;
      context.font = '32px "' + family + '", ' + fallback;
      return context.measureText(sample).width !== plain;
    });
  } catch (error) { return false; }
}
const COMPACT_INSTALLED = typeof document !== 'undefined' && (fontInstalled('SF Compact') || fontInstalled('SF Compact Text'));
const APPLE_FONTS = [['sf', 'SF Pro'], ['sf_rounded', 'SF Pro Rounded'], ['sf_mono', 'SF Mono'], ['new_york', 'New York'],
  ['sf_compact', 'SF Compact']];
// Shown at selection time, when the interface strings are loaded.
const appleFontLabel = ([value, text]) => value === 'sf_compact' && !COMPACT_INSTALLED
  ? [value, text + ' (' + t('Sistema') + ': SF Pro)'] : [value, text];
const ANDROID_FONTS = [['condensed', 'Roboto Condensed'], ['light', 'Roboto Light'], ['medium', 'Roboto Medium'], ['noto_serif', 'Noto Serif'],
  ['typewriter', 'Cutive Mono'], ['casual', 'Coming Soon'], ['handwriting', 'Dancing Script'], ['smallcaps', 'Carrois Gothic SC']];
const backgroundUrl = (name) => '/background?' + resourceAuth() + '&name=' + encodeURIComponent(name);
function backdrop(name) {
  if (!name) return '';
  const dim = Number((state.appearance || {}).dim ?? 55);
  const veil = 'color-mix(in srgb, var(--bg) ' + dim + '%, transparent)';
  return 'linear-gradient(' + veil + ', ' + veil + '), url("' + backgroundUrl(name) + '")';
}
function applySettings() {
  updateConnectionIndicator();
  const settings = state.settings || {};
  const theme = settings.theme === 'system'
    ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : (settings.theme || 'dark');
  document.documentElement.dataset.theme = theme;
  const style = document.documentElement.style;
  const colors = { ...PALETTES[theme] };
  if (settings.text_color) colors.text = settings.text_color;
  if (settings.background_color) colors.bg = settings.background_color;
  if (settings.text_color || settings.background_color) {
    const fg = colors.text, bg = colors.bg;
    Object.assign(colors, { panel: blend(bg, fg, .05), selected: blend(bg, fg, .19), muted: blend(bg, fg, .70), line: blend(bg, fg, .30), strong: fg });
    for (const [name, value] of Object.entries(colors)) style.setProperty('--' + name, value);
  } else for (const name of Object.keys(colors)) style.removeProperty('--' + name);
  if (settings.accent_color) {
    style.setProperty('--accent', settings.accent_color);
    style.setProperty('--strong', settings.accent_color);
    style.setProperty('--selected', blend(colors.bg, settings.accent_color, .35));
  } else style.removeProperty('--accent');
  document.title = settings.app_display_name || 'TeleGraph';
  for (const direction of ['in', 'out']) {
    const color = settings['bubble_' + direction + '_color'];
    const prefix = '--bubble-' + direction;
    document.documentElement.toggleAttribute('data-bubble-' + direction, !!color);
    if (!color) {
      style.removeProperty(prefix);
      style.removeProperty(prefix + '-ink');
      continue;
    }
    const rgb = color.slice(1).match(/../g).map(hex => parseInt(hex, 16) / 255)
      .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
    style.setProperty(prefix, color);
    style.setProperty(prefix + '-ink', luminance > .179 ? '#000' : '#fff');
  }
  // 0 keeps each element's usual shape.
  for (const [key, name] of [['bubble_radius', '--bubble-radius'], ['button_radius', '--button-radius'], ['menu_radius', '--menu-radius']]) {
    if (Number(settings[key]) > 0) style.setProperty(name, Number(settings[key]) + 'px'); else style.removeProperty(name);
  }
  const look = state.appearance || {};
  if (FONTS[look.font]) style.setProperty('--font', FONTS[look.font]); else style.removeProperty('--font');
  // Text and control effects (Settings › Personalization).
  const fx = look.effects || {}, rootClasses = document.documentElement.classList;
  for (const key of ['text_bold', 'text_italic', 'text_strike', 'text_uppercase']) rootClasses.toggle('fx-' + key.slice(5), !!fx[key]);
  // Personalization › Disable all animations: transitions stop and animated emoji stay still.
  const still = !!settings.reduce_animations;
  if (rootClasses.contains('no-motion') !== still) {
    rootClasses.toggle('no-motion', still);
    if (still) {
      stopInterfaceAnimations();
      for (const node of document.querySelectorAll('.animated')) PLAYING.get(node)?.pause();
    }
  }
  const effect = (name, value) => { if (value) style.setProperty(name, value); else style.removeProperty(name); };
  effect('--fx-underline', fx.text_underline ? fx.text_underline + 'px' : '');
  effect('--fx-underline-color', fx.text_underline_color || '');
  effect('--fx-text-shadow', fx.text_shadow ? '0 0 ' + fx.text_shadow + 'px ' + (fx.text_shadow_color || 'var(--bg)') + ', 1px 1px ' + Math.ceil(fx.text_shadow / 2) + 'px ' + (fx.text_shadow_color || 'var(--bg)') : '');
  effect('--fx-text-border', fx.text_border ? fx.text_border / 2 + 'px ' + (fx.text_border_color || 'var(--bg)') : '');
  effect('--fx-button-border', fx.button_border ? fx.button_border + 'px solid ' + (fx.button_border_color || 'var(--line)') : '');
  effect('--fx-button-shadow', fx.button_shadow ? '0 0 ' + fx.button_shadow + 'px ' + (fx.button_shadow_color || 'var(--line)') : '');
  effect('--fx-menu-border', fx.menu_border ? fx.menu_border + 'px solid ' + (fx.menu_border_color || 'var(--line)') : '');
  effect('--fx-menu-shadow', fx.menu_shadow ? '0 0 ' + fx.menu_shadow + 'px ' + (fx.menu_shadow_color || 'var(--line)') : '');
  document.getElementById('app').style.backgroundImage = backdrop(look.background);
  const scroll = document.getElementById('scroll');
  if (scroll && state.open) paintChatWallpaper(scroll, state.open.peer);
  for (const win of state.windows) {
    const body = win.node?.querySelector('.winbody');
    if (body) paintChatWallpaper(body, win.peer);
  }
  const size = Number(settings.font_size) || 12;
  document.documentElement.classList.toggle('large-type', size > 19);
  document.documentElement.style.setProperty('--size', Math.round(size * 1.25) + 'px');
  document.documentElement.dir = state.rtl ? 'rtl' : 'ltr';
  document.documentElement.lang = state.language || 'en';
  document.dispatchEvent(new Event('appearancechange'));
  window.tgPresentation?.apply();
  window.tgNativeGlass?.refresh();
  window.tgNativeDialogs?.sync();
}

async function loadStrings() {
  const language = state.language;
  const keys = [
    ...(window.tgPresentation?.labels || []),
    ...swipeOptions.map(([, label]) => label), 'Al deslizar un chat hacia la derecha', 'Al deslizar un chat hacia la izquierda',
    ...Object.values(CALL_STATUS), ...MOBILE_FEATURES.flatMap(([, label, note]) => [label, note]),
    ...[...PROFILE_SECTIONS, ...SETTINGS_SECTIONS, ...SHARED_KINDS].map(([, label]) => label),
    ...FORMAT_BUTTONS.map(([, , label]) => label),
  ];
  const labels = await api('strings', {keys, include_web: true});
  if (state.language === language) Object.assign(S, labels);
}

// -- events from the core ------------------------------------------------------
let source = null;
function listen() {
  source = new EventSource('/events?' + resourceAuth());
  source.onmessage = (event) => {
    let packet; try { packet = JSON.parse(event.data); } catch { return; }
    const account = WINDOW_ACCOUNT ?? state.account;
    if (account != null && packet.account !== account && !['stage', 'lock'].includes(packet.type)) return;
    const handler = EVENTS[packet.type];
    if (handler) handler(packet.data, packet.account);
  };
  source.onerror = () => { /* EventSource reconnects by itself; resync when it does. */ };
  source.onopen = () => { if (state.started) resync().catch(() => {}); };
}
// Back from the background: the event stream may have been closed meanwhile.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || !state.started) return;
  if (!source || source.readyState === EventSource.CLOSED) { try { source && source.close(); } catch (error) {} listen(); }
  else resync().catch(() => setTimeout(() => resync().catch(() => {}), 3000));
});

let notificationRoute = null;
let checkingNotificationRoute = false;
async function openAndroidNotification() {
  if (PLATFORM !== 'Android' || WINDOW_CHAT !== null || !state.started || document.hidden ||
      state.locked || checkingNotificationRoute || !['choose_account', 'ready'].includes(state.stage)) return;
  checkingNotificationRoute = true;
  try {
    const route = await api('take_notification_chat');
    if (route) notificationRoute = route;
    if (!notificationRoute || state.locked) return;
    const {account, peer} = notificationRoute;
    if (!state.accounts.some(item => item.key === account)) { notificationRoute = null; return; }
    if (state.stage === 'choose_account') {
      await api('choose_account', {key: account, ask: state.settings.ask_account_startup !== false});
      return;
    }
    if (state.account !== account) {
      if (!(await flushOpenDrafts())) return;
      await api('account.select', {key: account});
      await resync();
    }
    if (!state.locked && state.stage === 'ready' && state.account === account) {
      notificationRoute = null;
      await openChat(peer);
    }
  } finally { checkingNotificationRoute = false; }
}

const downloads = createDownloadController();

const EVENTS = {
  downloads(payload) { downloads.update(payload); },
  notification_route() { openAndroidNotification().catch(() => {}); },
  // A draft changed on another device (or was sent from there).
  draft({ account, peer, thread_root, record }) {
    const composer = thread_root == null ? peer : peer + '/' + thread_root;
    if (account !== state.account || draftWrites.has(draftKey(composer)) || failedDraftWrites.has(draftKey(composer))) return;
    state.drafts[composer] = record;
    if (thread_root != null) {
      if (state.open && composerPeer() === composer && !state.editing && !state.open.sending)
        restoreComposer(document.getElementById('field'), record);
      return;
    }
    for (const win of state.windows) if (win.peer === peer && !win.sending) restoreWindowDraft(win, record);
    if (state.open?.peer === peer && !state.open.thread && !state.editing && !state.open.sending) {
      restoreComposer(document.getElementById('field'), record);
    }
    queueChatList();
  },
  stage(data) {
    if (state.stage !== data.stage) state.accountRevision++;
    const wasReady = state.stage === 'ready' && state.account === data.account && !unavailableWindow();
    adopt(data);
    if (unavailableWindow()) { render(); return; }
    if (state.stage === 'ready' && !state.locked && !wasReady) {
      state.view = 'chats'; state.open = null;
      const account = state.account, revision = state.accountRevision;
      api('chats').then((chats) => {
        if (state.account !== account || revision !== state.accountRevision || state.locked) return;
        state.chats = chats; drawChatList();
        if (WINDOW_CHAT === null) restoreWindows();
      }, () => {});
      if (WINDOW_CHAT === null) refreshCallState(); else openChat(WINDOW_CHAT, true);
    }
    if (!(wasReady && state.stage === 'ready')) render();
    openAndroidNotification().catch(() => {});
  },
  connection(value) { state.connection = value; updateStatus(); drawHeaderStatus(); },
  accounts(list) { state.accounts = list; if (state.view === 'settings') render(); },
  settings(values) { state.settings = values; applySettings(); },
  appearance(values) { state.appearance = values; applySettings(); if (state.view === 'settings') render(); },
  native_call(snapshot) { receiveCall(snapshot); },
  group_call(snapshot) { receiveGroupCall(snapshot); },
  chats(list) {
    state.chats = list;
    for (const win of state.windows) {
      const forum = list.find(chat => chat.id === win.peer && chat.forum);
      if (forum) showFloatingForum(win, forum);
    }
    if (state.open && !state.open.thread) {
      const current = list.find(item => item.id === state.open.peer);
      if (current) Object.assign(state.open.chat, current);
    }
    if (state.view === 'archived') fetchArchived().catch(() => {});
    queueChatList();
    // Folder membership changes rarely: ask for it at most every few seconds.
    if (state.folders.length && Date.now() - (state.foldersAt || 0) > 4000) {
      state.foldersAt = Date.now();
      fetchFolders(false).catch(() => {});
    }
  },
  // A chat changed without moving (read receipts, pending messages).
  chat_patch(chat) {
    if (chat.forum) showFloatingForum(state.windows.find(win => win.peer === chat.id), chat);
    const index = state.chats.findIndex((item) => item.id === chat.id);
    if (index < 0) return;
    state.chats[index] = chat;
    if (state.open && !state.open.thread && state.open.peer === chat.id) Object.assign(state.open.chat, chat);
    queueChatList();
  },
  chat(chat) {
    if (chat.forum) showFloatingForum(state.windows.find(win => win.peer === chat.id), chat);
    const index = state.chats.findIndex((item) => item.id === chat.id);
    if (index >= 0) state.chats.splice(index, 1);
    const pinned = state.chats.filter((item) => item.pinned).length;
    if (!chat.archived) state.chats.splice(chat.pinned ? (index >= 0 ? index : 0) : pinned, 0, chat);
    if (state.open && !state.open.thread && state.open.peer === chat.id) Object.assign(state.open.chat, chat);
    queueChatList();
  },
  forum_topics({peer, topic_id}) { return refreshOpenForum(peer, topic_id); },
  emoji_status({peer, status}) {
    for (const list of [state.chats, state.archived, state.contacts, state.global?.chats]) {
      if (!Array.isArray(list)) continue;
      const matching = list.find(item => item.id === peer);
      if (matching) matching.emoji_status = status;
    }
    if (state.open?.peer === peer && !state.open.thread) {
      state.open.chat.emoji_status = status;
      const title = document.querySelector('.bar .title.with-avatar .names > .name');
      if (title) {
        title.querySelector('.emoji-status')?.remove();
        if (status) title.append(emojiStatusBadge(status));
      }
    }
    for (const win of state.windows) if (win.peer === peer) {
      win.emojiStatus = status;
      const name = win.node?.querySelector('.winbar .name');
      name?.replaceWith(nameWithStatus(win.name, status));
    }
    if (state.profile?.id === peer) {
      state.profile.emoji_status = status;
      if (state.view === 'profile') render();
    }
    if (state.view === 'contacts') drawContacts();
    else queueChatList();
  },
  message({ peer, message }) {
    for (const win of state.windows) if (win.peer === peer && !win.forumChat && message && !win.messages.some((item) => item.id === message.id)) {
      win.messages.push(message); drawWindowMessages(win, true);
    }
    const open = state.open;
    if (open && open.peer === peer && message && (!open.thread || (open.topic ? message.topic_id === open.topic.id : message.thread_root === open.thread.root)) && !open.messages.some((item) => item.id === message.id)) {
      open.messages.push(message);
      appendMessage(message);
    }
  },
  header({ peer, status }) {
    if (state.open && state.open.peer === peer) { state.open.status = status; drawHeaderStatus(); }
  },
  typing({ peer, status }) {
    // "Activity in the chat list": ··· while someone is typing.
    state.listTyping = state.listTyping || {};
    if (status) state.listTyping[peer] = Date.now() + 6000; else delete state.listTyping[peer];
    if (state.view === 'chats' && feature('chat_list_activity')) {
      queueChatList();
      // One timer clears the expired ··· marks (not one per typing update).
      clearTimeout(state.listTypingTimer);
      state.listTypingTimer = setTimeout(() => { if (state.view === 'chats') queueChatList(); }, 6100);
    }
    if (!state.open || state.open.peer !== peer) return;
    state.open.typing = status;
    clearTimeout(state.open.typingTimer);
    if (status) state.open.typingTimer = setTimeout(() => { if (state.open) { state.open.typing = ''; drawHeaderStatus(); } }, 6000);
    drawHeaderStatus();
  },
  chat_translation({account, peer, thread_root, ...translation}) {
    if (account !== state.account) return;
    const open = state.open;
    if (open?.peer === peer && (open.thread?.root ?? null) === thread_root) {
      applyChatTranslation(open, translation);
      drawMessages(false);
    }
    if (thread_root === null) {
      for (const win of state.windows) if (win.peer === peer) {
        applyChatTranslation(win, translation);
        drawWindowMessages(win, false);
      }
    }
  },
  history(update, account) {
    const {peer, messages, translate, translated} = update;
    if (state.openingChat?.peer === peer && state.openingChat.account === account) {
      state.openingChat.history = update;
    }
    const open = state.open;
    if (open && open.peer === peer && !open.thread) {
      if (open.translate) {
        const previous = new Map(open.messages.map((message) => [message.id, translationText(message)]));
        for (const message of messages) {
          if (previous.get(message.id) !== translationText(message)) delete open.translated[message.id];
        }
        if (open.translate === translate) Object.assign(open.translated, translated);
      }
      const scroll = document.getElementById('scroll');
      const atEnd = !scroll || nearBottom(scroll) || Date.now() < (open.stickUntil || 0) || !open.historyLoaded;
      const oldest = messages.length ? messages[0].id : null;
      if (!atEnd && oldest !== null) {
        // Someone reading further up keeps their place and the older pages already loaded.
        open.messages = [...open.messages.filter((item) => item.id < oldest), ...messages];
      } else {
        open.messages = messages;
        open.done = false;
      }
      open.historyLoaded = true;
      drawMessages(atEnd);
    }
    for (const win of state.windows) if (win.peer === peer && !win.forumChat) {
      if (win.translate) {
        const previous = new Map(win.messages.map(message => [message.id, translationText(message)]));
        for (const message of messages) {
          if (previous.get(message.id) !== translationText(message)) delete win.translated[message.id];
        }
      }
      applyChatTranslation(win, {translate, translated});
      win.messages = messages;
      win.historyLoaded = true;
      drawWindowMessages(win, false);
    }
  },
  edit({ peer, message }) {
    for (const win of state.windows) if (win.peer === peer && message) {
      const at = win.messages.findIndex((item) => item.id === message.id);
      if (at >= 0) {
        if (win.translate && translationText(win.messages[at]) !== translationText(message)) delete win.translated[message.id];
        win.messages[at] = message;
        drawWindowMessages(win, false);
      }
    }
    const open = state.open;
    if (!open || open.peer !== peer || !message) return;
    const index = open.messages.findIndex((item) => item.id === message.id);
    if (index >= 0) {
      const before = open.messages[index];
      open.messages[index] = message;
      if (open.translate && translationText(before) !== translationText(message)) {
        delete open.translated[message.id];
        translatePending();
      }
      replaceMessage(message);
    }
  },
  delete({ peer, ids }) {
    for (const win of state.windows) if (win.peer === peer) {
      const gone = new Set(ids); win.messages = win.messages.filter((item) => !gone.has(item.id)); drawWindowMessages(win, false);
    }
    const open = state.open;
    if (!open || open.peer !== peer) return;
    const gone = new Set(ids);
    const before = open.messages.length;
    open.messages = open.messages.filter((item) => !gone.has(item.id));
    if (open.messages.length !== before) drawMessages(false);  // Also drops empty day separators.
  },
  read({ peer, max_id }) {
    const open = state.open;
    if (!open || open.peer !== peer) return;
    for (const message of open.messages) if (message.out && message.id <= max_id && !message.read) {
      message.read = true; replaceMessage(message);
    }
  },
  outbox(data) {
    if (state.open?.peer === data.peer && state.account === data.account) {
      state.open.outbox = data.items.filter(item => item.thread_root === (state.open.thread?.root ?? null));
      drawOutbox();
    }
  },
  qr(data) { state.qr = data; if (state.stage === 'qr') render(); },
  lock(value) {
    if (value === state.locked) return;
    if (value) document.getElementById('message-notice')?.remove();
    state.accountRevision++;
    if (value) notificationRoute = null;
    if (value) document.querySelector('.media-viewer[open]')?.close();
    state.locked = value;
    if (value) downloads.reset();
    drawNativeCall();
    drawGroupCall();
    if (value) { flushOpenDrafts(); state.bioTried = false; render(); } else resync();
  },
  message_notice(data) {
    if (WINDOW_CHAT !== null || document.hidden || state.locked) return;
    document.getElementById('message-notice')?.remove();
    const notice = h('button', {id: 'message-notice', type: 'button', 'aria-live': 'polite',
      onclick: () => attempt(async () => {
        notice.remove();
        if (state.locked) return;
        if (state.account !== data.account) {
          if (!(await flushOpenDrafts())) return;
          await api('account.select', {key: data.account});
          await resync();
        }
        if (!state.locked && state.account === data.account) await openChat(data.peer);
      })},
      data.sender && data.account === state.account ? avatar(data.sender, data.title) : null,
      h('span', {}, h('strong', {}, data.title), data.conversation ? h('small', {}, data.conversation) : null, h('span', {}, data.body)));
    document.body.append(notice);
    setTimeout(() => notice.remove(), 5500);
  },
  toast(data) { toast(data.text, data.kind); },
  status(data) { if (data.text) toast(data.text); },
};

function adopt(snapshot) {
  const downloadContextChanged = state.account !== snapshot.account || snapshot.locked;
  if (snapshot.locked || state.account !== snapshot.account) document.getElementById('message-notice')?.remove();
  if (snapshot.locked || state.account !== snapshot.account || snapshot.stage !== 'ready')
    document.querySelector('.media-viewer[open]')?.close();
  if (snapshot.locked && !state.locked) state.accountRevision++;
  if (!snapshot.locked && state.account !== snapshot.account) {
    state.accountRevision++;
    state.contacts = state.contactSelection = state.forwarding = null;
    state.visibleContacts = [];
    state.folders = []; state.folder = null; state.foldersLoaded = false; state.foldersAt = 0;
    state.settingsQuery = ''; state.listTyping = {}; state.list = 'chats'; state.me = null;
    state.premiumInfo = null; state.shared = null; state.visibleChats = [];
    photoIds.clear(); chatPlaces.clear();
    state.chats = []; state.archived = state.global = state.results = null;
    state.search = ''; state.selection = state.chatSelection = null;
    state.account = snapshot.account;
    for (const win of state.windows) win.node?.remove();
    state.windows = [];
    state.windowsRestored = false;
    windowLayer.querySelectorAll('.closing-window').forEach(node => node.remove());
    closeSheet(true);
    state.open = state.reply = state.editing = null;
    state.profile = null;
    state.profileTabs = {};
    receiveCall(null);
    state.attachments = [];
    state.drafts = {}; state.formats = {}; state.customEmoji = {};
    state.view = 'chats';
  }
  Object.assign(state, {
    stage: snapshot.stage, error: snapshot.error, connection: snapshot.connection,
    accounts: snapshot.accounts, settings: snapshot.settings, version: snapshot.version,
    language: snapshot.language, rtl: snapshot.rtl, locked: snapshot.locked, lock_enabled: snapshot.lock_enabled,
    appearance: snapshot.appearance || {}, lock: snapshot.lock || {},
  });
  if (downloadContextChanged) downloads.reset();
  applySettings();
}

let resyncing = null, resyncRevision = null, resyncAgain = false;
function resync() {
  if (resyncing) {
    if (resyncRevision !== state.accountRevision) resyncAgain = true;
    return resyncing;
  }
  resyncRevision = state.accountRevision;
  resyncing = syncState().finally(() => {
    resyncing = null;
    if (resyncAgain) {resyncAgain = false; return resync();}
  });
  return resyncing;
}
async function syncState() {
  const revision = state.accountRevision;
  const snapshot = await api('state');
  if (revision !== state.accountRevision) return;
  const languageChanged = snapshot.language !== state.language;
  adopt(snapshot);
  const adopted = state.accountRevision;
  if (state.locked) render();
  if (languageChanged) await loadStrings();
  if (adopted !== state.accountRevision) return;
  if (state.stage === 'ready' && !state.locked && !unavailableWindow()) {
    const account = state.account;
    const chats = await api('chats');
    if (state.account !== account || adopted !== state.accountRevision || state.locked) return;
    state.chats = chats;
    if (WINDOW_CHAT === null) {
      if (state.windowsRestored) {
        await Promise.all(state.windows.map(async (win) => {
          if (failedDraftWrites.has(draftKey(win.peer))) await saveWindowDraft(win);
          if (state.account === account && adopted === state.accountRevision && !state.locked && state.windows.includes(win)) {
            await refreshFloatingWindow(win, false);
          }
        }));
        if (state.account !== account || adopted !== state.accountRevision || state.locked) return;
      } else restoreWindows();
    }
    refreshCallState();
    if (state.open && !state.editing && !state.open.sending) {
      const open = state.open;
      if (open.topic) await openForumTopic(open.chat, open.topic, false);
      else if (open.forumList) await openForumList(open.chat, false, open.forumList.query);
      else if (open.thread) await loadComments(open.thread.source, open.thread.post, open.thread.channel, false);
      else await openChat(open.peer, false, null, open.preview);
    } else if (WINDOW_CHAT !== null && !state.open) {
      await openChat(WINDOW_CHAT, true);
    }
  }
  if (adopted === state.accountRevision) render();
}

// -- navigation (history: Android back gesture / button) -----------------------
function go(view, extra = {}) {
  Object.assign(state, extra, { view });
  history.pushState({ view }, '');
  render();
}
let synchronizingHistory = false;
window.addEventListener('popstate', () => {
  if (synchronizingHistory) synchronizingHistory = false;
  else back(false);
});
// Native back button (Android): true when the interface went back a step.
window.tgBack = () => {
  if (window.tgNativeDialogs?.cancel()) return true;
  const sheetOpen = !document.getElementById('sheet-layer').hidden;
  const shown = document.querySelector('.media-viewer[open]');
  if (shown) { shown.close(); return true; }
  if (state.stage === 'qr') { api('login.qr_cancel'); state.stage = 'phone'; render('back'); return true; }
  if (!sheetOpen && (state.stage !== 'ready' || state.view === 'chats')) return false;
  back();
  return true;
};
async function back(pop = true) {
  if (window.tgNativeDialogs?.cancel()) return;
  if (pop && synchronizingHistory) return;
  if (!document.getElementById('sheet-layer').hidden) { closeSheet(); return; }
  if (WINDOW_CHAT !== null && state.view === 'chat' && !state.open?.thread) return;  // the system closes this window
  if (state.view === 'chat' && state.open?.thread) {
    if (pop && history.state?.discussion) { history.back(); return; }
    const open = state.open;
    saveDraft().then(saved => {
      if (!saved || state.open !== open) return;
      if (open.topic) openForumList(open.chat, false);
      else openChat(open.thread.source, false, open.thread.channel);
    });
    return;
  }
  if (state.view === 'chat') {
    const open = state.open;
    rememberChatPlace();
    if (!(await saveDraft()) || state.open !== open || state.view !== 'chat') return;
    state.openRequest = (state.openRequest || 0) + 1;
    api('close', { peer: open?.peer }).catch(() => {});
    state.open = null; state.reply = state.editing = null; state.attachments = []; state.selection = null;
  }
  const list = LISTS.includes(state.list) ? state.list : 'chats';
  const from = state.view;
  if (from === 'forward') state.forwarding = null;
  state.view = from === 'forward' ? (state.open ? 'chat' : list)
    : from === 'shared' ? 'profile'
    : from === 'devices' ? 'settings'
    : from === 'profile' ? (state.open ? 'chat' : list)
    : from === 'chat' ? list : 'chats';
  if (LISTS.includes(state.view)) state.list = state.view;
  state.results = null;
  if (pop && history.state && history.length > 1) {
    // The view and its draft have already been handled above.
    synchronizingHistory = true;
    history.back();
  }
  render('back');
}

// -- rendering -------------------------------------------------------------------
const root = document.getElementById('app');
function listView(view) {
  if (view === 'stories') return storiesView();
  if (view === 'settings') return settingsView();
  if (view === 'forward') return chatListView(true);
  if (view === 'archived') return chatListView(false, true);
  if (view === 'contacts') return contactsView();
  if (view === 'devices') return devicesView();
  return chatListView();
}
function render(direction = 'forward') {
  const open = state.open;
  const screen = [state.accountRevision, state.locked, state.stage, state.view, open?.peer, open?.thread?.root,
    open?.topic?.id, !!open?.forumList, state.view === 'profile' ? state.profile?.id : '', state.view === 'shared' ? state.shared?.kind : ''].join('|');
  const section = state.view === 'settings' ? state.settingsTab || 'appearance' : state.view === 'profile' ? state.profileSection || 'info' : '';
  const changed = screen !== state.lastScreen, sectionChanged = section !== state.lastSection;
  const previous = state.lastScreen;
  if (changed) closeSheet(true);
  state.lastScreen = screen;
  state.lastSection = section;
  const listTop = document.getElementById('chatlist')?.scrollTop || 0;
  const settingsTop = document.getElementById('settings-scroll')?.scrollTop || 0;
  const previousScroll = document.getElementById('scroll');
  const sameChat = !changed && state.view === 'chat' && !open?.forumList && root.mountedConversation === open;
  const position = sameChat && previousScroll ? {top:previousScroll.scrollTop,
    bottom:previousScroll.scrollHeight - previousScroll.clientHeight - previousScroll.scrollTop} : null;
  // A preference refresh must not detach an active mobile composer: WebKit would dismiss its keyboard.
  const kept = sameChat && !root.classList.contains('wide') && (!WIDE() || listCoversAll())
    ? {scroll:previousScroll, composer:root.querySelector(':scope > .composer'),
       pinned:root.querySelector(':scope > #pinned')} : null;
  renderContent(kept);
  mountChatView(kept);
  root.mountedConversation = state.locked || state.stage !== 'ready' ? null : open;
  if (position) {
    const box = document.getElementById('scroll');
    if (box) box.scrollTop = position.bottom <= 4 ? box.scrollHeight : position.top;
    if (position.bottom > 4) open.stickUntil = 0;
  }
  window.tgPresentation?.mount();
  const list = document.getElementById('chatlist'), settings = document.getElementById('settings-scroll');
  if (list && listTop) list.scrollTop = listTop;
  if (settings && settingsTop) settings.scrollTop = settingsTop;
  updateConnectionIndicator();
  window.tgNativeDialogs?.sync();
  if (!previous || state.locked || unavailableWindow() || (!changed && !sectionChanged)) return;
  let surface = root;
  if (!changed) surface = document.getElementById(state.view === 'settings' ? 'settings-scroll' : 'profile-scroll');
  else if (root.classList.contains('wide')) surface = root.querySelector(LISTS.includes(state.view) || ['devices', 'forward'].includes(state.view) ? '.pane.side' : '.pane.main');
  animateSurface(surface, direction === 'back' ? 'back' : 'forward');
}
function renderContent(kept = null) {
  const paint = (...nodes) => {
    const next = nodes.map(node => {
      if (kept?.pinned && node.id === 'pinned') return kept.pinned;
      if (kept?.scroll && node.id === 'scroll') {
        kept.scroll.className = node.className;
        kept.scroll.style.cssText = node.style.cssText;
        return kept.scroll;
      }
      if (kept?.composer && node.classList.contains('composer')) {
        const existing = kept.composer.querySelector('#field'), updated = node.querySelector('#field');
        if (existing && updated) {
          existing.readOnly = updated.readOnly;
          existing.placeholder = updated.placeholder;
          existing.setAttribute('aria-label', updated.getAttribute('aria-label'));
        }
        const prompt = kept.composer.querySelector('.composer-prompt');
        if (prompt) prompt.textContent = node.querySelector('.composer-prompt').textContent;
        const controls = '.line > button, .format-bar > button';
        const updatedButtons = [...node.querySelectorAll(controls)];
        kept.composer.querySelectorAll(controls).forEach((button, index) => {
          const replacement = updatedButtons[index];
          for (const name of ['title', 'aria-label']) {
            if (replacement?.hasAttribute(name)) button.setAttribute(name, replacement.getAttribute(name));
            else button.removeAttribute(name);
          }
        });
        return kept.composer;
      }
      return node;
    });
    const retained = new Set(next);
    // Remove obsolete siblings first. Moving the retained composer before an old
    // sibling via insertBefore would still blur its field, even within one parent.
    for (const child of [...root.children]) if (!retained.has(child)) child.remove();
    reconcile(root, next);
  };
  root.className = '';
  windowLayer.hidden = state.locked || state.stage !== 'ready';
  if (windowLayer.hidden || unavailableWindow()) windowLayer.querySelectorAll('.closing-window').forEach(node => node.remove());
  if (state.locked) return paint(...lockView().filter(Boolean));
  if (unavailableWindow()) return paint(h('div', {class: 'center'}, t('The active account changed.')));
  if (state.stage === 'choose_account') return paint(...chooserView().filter(Boolean));
  if (state.stage !== 'ready') return paint(...loginView().filter(Boolean));
  if (WINDOW_CHAT !== null && state.view === 'chats' && !state.open)
    return paint(h('div', {class: 'center'}, t('Cargando...')));
  if (LISTS.includes(state.view)) state.list = state.view;
  const detail = (state.view === 'chat' && state.open) || state.view === 'profile' || state.view === 'shared';
  if (!WIDE() || (listCoversAll() && detail)) {
    syncWindows(false);
    if (state.view === 'chat' && state.open) return paint(...chatView(kept).filter(Boolean));
    if (state.view === 'profile') return paint(...profileView().filter(Boolean));
    if (state.view === 'shared' && state.shared) return paint(...sharedView().filter(Boolean));
    return paint(...listView(state.view).filter(Boolean));
  }
  // Wide (iPad, Mac, landscape tablets): list on the side, chat or profile beside it.
  root.className = 'wide';
  const width = Number((state.appearance || {}).side_width) || 0;
  const side = h('div', { class: 'pane side' + (width === 1 ? ' collapsed' : ''),
    style: width >= 2 ? 'width:' + Math.min(width, innerWidth - 7) + 'px' : null }, ...listView(listMode()));
  const divider = h('div', { class: 'divider', title: t('Reset panel sizes'), onpointerdown: (event) => resizePanes(event, side),
    ondblclick: () => saveLook({ side_width: 0 }) });
  let main;
  if (state.view === 'profile') main = profileView();
  else if (state.view === 'shared' && state.shared) main = sharedView();
  else if (state.open) main = chatView();
  else main = [h('div', { class: 'placeholder' }, logo(), h('div', { class: 'muted' }, t('Chats')))];
  paint(side, divider, h('div', { class: 'pane main' }, ...main), ...syncWindows(true));
}
let wasWide = WIDE();
window.addEventListener('resize', () => {
  const wide = WIDE();
  if (wide === wasWide) return;
  wasWide = wide;
  if (state.stage === 'ready' && !state.locked) render();
});

function statusNode() {
  const offline = state.connection === 'offline' || state.connection === 'reconnecting';
  const online = state.connection === 'online';
  const label = t(online || offline ? 'En linea' : 'Conectando...');
  // Offline, the status keeps its own width (its wording is hidden) and hosts
  // the connection alert stacked in the same cell: the header geometry is the
  // same in both states and nothing is reserved while online.
  if (offline) return h('span', {id: 'status', class: 'status connection-host'},
    h('span', {class: 'connection-label', 'aria-hidden': 'true'}, h('span', {}, '●'), h('span', {class: 'status-word'}, label)));
  return h(online ? 'span' : 'button', {id: 'status', class: 'status', title: label,
    'aria-label': online ? label : label + ' · ' + t('Reconnect'), onclick: online ? null : reconnect},
    h('span', {'aria-hidden': 'true'}, online ? '●' : '◌'), h('span', {class: 'status-word'}, label));
}
function connectionHost(bar) {
  // A visible status hosts the alert in place. Without one (a chat, or the
  // status hidden by Presentation) a zero-width cell after the title places it
  // in the title's own end padding: the title box and the controls never move.
  const status = bar.querySelector(':scope > #status.connection-host');
  if (status && status.getClientRects().length) return status;
  const title = bar.matches('.bar') && bar.querySelector(':scope > .title');
  if (!title) return bar;  // e.g. a floating window bar: the alert ends the bar
  let cell = bar.querySelector(':scope > .connection-cell');
  if (!cell) cell = h('span', {class: 'connection-cell'});
  if (cell.previousElementSibling !== title) title.after(cell);
  // Explicit state class (not :has(), unavailable before Safari 15.4): the title
  // reserves its end padding only while the cell holds the alert.
  bar.classList.add('connection-in-title');
  return cell;
}
function updateConnectionIndicator() {
  const badge = connectionAlert;
  badge.hidden = state.locked || unavailableWindow() || state.stage !== 'ready' || !['offline', 'reconnecting'].includes(state.connection);
  const label = t(state.connection === 'reconnecting' ? 'Conectando...' : 'Sin conexion') + ' · ' + t('Reconnect');
  badge.title = label;
  badge.setAttribute('aria-label', label);
  const pane = root.classList.contains('wide') ? root.querySelector(':scope > .pane.main') : root;
  const bar = !badge.hidden && pane?.querySelector(':scope > .bar, :scope > .winbar');
  const host = bar ? connectionHost(bar) : document.body;
  if (badge.parentElement !== host) host.append(badge);
  // A cell exists only while it holds the alert: never an empty reserved slot.
  for (const cell of document.querySelectorAll('.connection-cell')) if (cell !== host) cell.remove();
  for (const other of document.querySelectorAll('.connection-in-title'))
    if (!other.querySelector(':scope > .connection-cell')) other.classList.remove('connection-in-title');
}
function updateStatus() {
  document.getElementById('status')?.replaceWith(statusNode());
  updateConnectionIndicator();
}

const brandUrl = (options) => '/logo?' + new URLSearchParams(
  options.t ? (WINDOW_ACCOUNT !== null ? {...options, window_account: WINDOW_ACCOUNT} : options)
    : {...options, face: 3}).toString();

function logo() {
  const look = state.appearance;
  const src = look?.brand_photo && !state.locked ? brandUrl({photo: look.brand_photo, t: TOKEN})
      : brandUrl(look?.brand_logo || {variant: 'title-short', color: 'default',
        theme: document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'});
  return h('img', {class: 'logo', src, alt: state.settings?.app_display_name || 'TeleGraph'});
}

function loginView() {
  const wrap = h('div', { class: 'center' }, logo());
  const submit = async (method, field) => {
    const input = document.getElementById(field);
    state.busy = true; render();
    try { await api(method, { [field]: input?.value || '' }); }
    catch (error) { state.error = error.message; }
    finally { state.busy = false; if (state.stage !== 'ready') render(); }
  };
  const form = (id, label, type, method, help, autocomplete) => {
    const input = h('input', { id, type, autocomplete, inputmode: type === 'tel' ? 'tel' : type === 'text' ? 'numeric' : null,
      onkeydown: (event) => { if (event.key === 'Enter') submit(method, id); } });
    return [h('div', { class: 'field' }, h('label', { for: id }, label), input, help ? h('small', { class: 'muted' }, help) : null),
      button(t('Continuar'), () => submit(method, id), 'primary')];
  };
  if (state.busy || state.stage === 'loading') {
    wrap.append(h('h2', {}, state.settings?.app_display_name || 'TeleGraph'), h('div', { class: 'spinner' }, t('Conectando...') + ' '));
  } else if (state.stage === 'phone') {
    wrap.append(h('h2', {}, t('Iniciar sesion')), ...form('phone', t('Numero de telefono'), 'tel', 'login.phone',
      t('Include + and your country calling code. Example: +1 202 555 0123'), 'tel'),
      button(t('Entrar con codigo QR'), () => { state.qr = null; api('login.qr').then(() => { state.stage = 'qr'; render(); }, (e) => toast(e.message, 'error')); }),
      button(t('New account'), () => attempt(() => api('login.signup_help'))));
  } else if (state.stage === 'code') {
    wrap.append(...form('code', t('Codigo de Telegram'), 'text', 'login.code', t('Te hemos enviado el codigo a Telegram o por SMS.'), 'one-time-code'));
  } else if (state.stage === 'signup') {
    wrap.append(h('h2', {}, t('New account')),
      h('p', {}, t('Create your account in the official Telegram app for iPhone or Android, then return here to sign in.')),
      button(t('Open') + ' Telegram (Android / iOS)', () => openUrl('https://telegram.org/apps'), 'primary'),
      button(t('Sign in again'), () => attempt(() => api('login.back'))));
  } else if (state.stage === 'password') {
    wrap.append(...form('password', t('Contraseña de verificacion en dos pasos'), 'password', 'login.password', '', 'current-password'));
  } else if (state.stage === 'qr') {
    wrap.append(h('p', {}, t('Escanea este codigo desde Telegram en otro dispositivo: Ajustes > Dispositivos > Vincular dispositivo.')),
      state.qr ? h('div', { class: 'qr', html: state.qr.svg }) : h('div', { class: 'spinner' }, ''),
      button(t('Volver'), () => { api('login.qr_cancel'); state.stage = 'phone'; render(); }));
  } else {
    wrap.append(h('p', { class: 'error' }, state.error || t('Error')), button(t('Reintentar'), () => api('retry'), 'primary'));
  }
  if (state.error && state.stage !== 'error' && !state.busy) wrap.append(h('p', { class: 'error' }, state.error));
  const accounts = state.accounts.filter((item) => item.label && !item.current);
  if (accounts.length && ['phone', 'qr', 'signup'].includes(state.stage)) {
    wrap.append(h('div', { class: 'muted' }, t('Cuentas')), ...accounts.map((item) =>
      button(item.alias || item.label, () => attempt(() => api('account.select', { key: item.key })))));
  }
  return [wrap];
}

// chat list -----------------------------------------------------------------------
// Telegram's seven default avatar gradients, indexed by the unmarked peer id.
const avatarColors = [['#ff845e','#d45246'], ['#febb5b','#f68136'], ['#b694f9','#6c61df'], ['#9ad164','#46ba43'],
  ['#5bcbe3','#359ad4'], ['#5caffa','#408acf'], ['#ff8aac','#d95574']];
function initials(name) {
  const words = String(name || '?').trim().split(/\s+/u).filter(Boolean);
  const first = word => {
    if (!word) return '';
    return typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, {granularity: 'grapheme'}).segment(word)[Symbol.iterator]().next().value.segment : Array.from(word)[0];
  };
  return (first(words[0]) + (words.length > 1 ? first(words.at(-1)) : '')).toLocaleUpperCase() || '?';
}
function avatar(id, name, extra = '', owner = null, color = null) {
  const numeric = Number(id) || 0;
  const raw = numeric <= -1000000000000 ? -numeric - 1000000000000 : Math.abs(numeric);
  const colors = avatarColors[Number.isInteger(color) && color >= 0 && color < avatarColors.length ? color : raw % avatarColors.length];
  const box = h('div', {class: 'avatar' + (extra ? ' ' + extra : ''), 'aria-hidden': 'true',
    style: 'background:linear-gradient(' + colors.join(',') + ')'}, h('span', {}, initials(name)));
  if (id != null && id !== '') {
    const photo = photoIds.get(numeric);
    const url = owner != null ? '/account-avatar?' + resourceAuth() + '&account=' + encodeURIComponent(owner) :
      '/avatar?' + resourceAuth() + '&peer=' + numeric + '&account_key=' + encodeURIComponent(state.account || '') +
      (state.avatarVersion ? '&v=' + state.avatarVersion : '') + (photo ? '&p=' + photo : '');
    const img = lazySrc(h('img', {alt: '', decoding: 'async'}), url);
    img.onload = () => box.classList.add('photo');
    img.onerror = () => img.remove();
    box.append(img);
  }
  return box;
}
function shortTime(seconds) {
  if (!seconds) return '';
  const date = new Date(seconds * 1000), now = new Date();
  if (date.toDateString() === now.toDateString()) return date.toTimeString().slice(0, 5);
  const days = (now - date) / 86400000;
  if (days < 7) return date.toLocaleDateString(state.language, { weekday: 'short' });
  return date.toLocaleDateString(state.language, { day: '2-digit', month: '2-digit', year: '2-digit' });
}

function chatListView(forwarding = false, archived = false) {
  const title = forwarding ? (state.forwarding?.people ? t('Share contact') : t('Reenviar a...')) : archived ? t('Archivados') : (state.appearance?.presentation?.list_title || state.settings?.app_display_name || 'TeleGraph');
  const bar = h('div', { class: 'bar' },
    forwarding || archived ? backButton() : null,
    h('div', { class: 'title' }, title), statusNode(),
    forwarding || archived ? null : (state.appearance?.presentation?.primary_action === 'compose'
      ? symbolButton('✎', t('Nuevo chat'), newChat) : symbolButton('≡', t('More options'), chatsMenu)),
    !forwarding && !archived && state.appearance?.presentation?.primary_action === 'compose'
      ? symbolButton('⋯', t('More options'), chatsMenu) : null);
  const search = h('div', { class: 'search' }, h('input', {
    type: 'search', 'data-search-scope': forwarding ? 'forward' : archived ? 'archived' : 'chats', placeholder: t('Buscar'), value: state.search,
    oninput: (event) => { state.search = event.target.value; drawChatList(); },
  }));
  const list = h('div', { class: 'scroll', id: 'chatlist' });
  const tabs = forwarding || archived ? null : h('div', { class: 'tabs', id: 'tabs', role: 'tablist', 'aria-label': t('Carpetas') });
  const selectionBar = forwarding ? null : h('div', { class: 'selection-bar', id: 'chat-selection-bar', hidden: true });
  setTimeout(() => { drawFolderTabs(); drawChatList(); drawChatSelection(); }, 0);
  if (!forwarding && !archived && !state.foldersLoaded) {
    state.foldersLoaded = true;
    const revision = state.accountRevision;
    fetchFolders(true).catch(() => { if (revision === state.accountRevision) state.foldersLoaded = false; });
  }
  if (archived && state.archived === null) attempt(fetchArchived);
  return [bar, selectionBar, search, tabs, list];
}

async function fetchArchived() {
  const account = state.account, revision = state.accountRevision;
  const chats = await api('archived');
  if (account !== state.account || revision !== state.accountRevision || state.locked) return;
  state.archived = chats; queueChatList();
}

// Which list is on screen (on wide screens it stays beside an open chat).
const LISTS = ['stories', 'chats', 'archived', 'contacts', 'settings'];
function listMode() {
  if (LISTS.includes(state.view) || state.view === 'forward' || state.view === 'devices') return state.view;
  return state.list || 'chats';
}

// A folder name with its custom emoji (animated unless the folder asks not to).
function folderTitle(folder) {
  if (!folder.emojis || !folder.emojis.length) return folder.title;
  const parts = richText(folder.title, folder.emojis, false);
  const box = h('span', {}, ...parts);
  if (folder.still && animationObserver) box.querySelectorAll('[data-anim]').forEach((node) => { animationObserver.unobserve(node); delete node.dataset.anim; });
  return box;
}

async function fetchFolders(refresh) {
  const account = state.account, revision = state.accountRevision;
  const folders = await api('folders', {refresh, account});
  if (revision !== state.accountRevision || account !== state.account || state.locked) return null;
  state.folders = folders; drawFolderTabs(); queueChatList();
  return folders;
}

function drawFolderTabs() {
  const tabs = document.getElementById('tabs');
  if (!tabs) return;
  if (!state.folders.some(folder => folder.id === state.folder)) state.folder = null;
  if (!state.folders.length) { tabs.replaceChildren(); return; }
  const restoreFocus = tabs.contains(document.activeElement);
  const tab = (id, label) => h('button', { class: 'tab' + (state.folder === id ? ' on' : ''),
    role: 'tab', 'aria-controls': 'chatlist', 'aria-selected': String(state.folder === id), tabindex: state.folder === id ? 0 : -1,
    onclick: event => {
      state.folder = id;
      for (const item of tabs.children) {
        const active = item === event.currentTarget;
        item.classList.toggle('on', active);
        item.setAttribute('aria-selected', String(active));
        item.tabIndex = active ? 0 : -1;
      }
      drawChatList();
    }, onkeydown: event => {
      const choices = Array.from(tabs.children), index = choices.indexOf(event.currentTarget);
      const forward = getComputedStyle(tabs).direction === 'rtl' ? -1 : 1;
      const next = { Home: 0, End: choices.length - 1, ArrowLeft: index - forward, ArrowRight: index + forward }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      const target = choices[(next + choices.length) % choices.length];
      target.focus(); target.click();
    } }, label);
  tabs.replaceChildren(tab(null, t('Todos los chats')), ...state.folders.map((folder) => tab(folder.id, folderTitle(folder))));
  if (restoreFocus) tabs.querySelector('[aria-selected="true"]').focus({preventScroll: true});
}

// Last message of a chat: waiting to be sent, sent, read (as in Telegram).
const TICKS = { pending: '◷', failed: '⚠', sent: '✓', read: '✓✓' };

// Puts exactly `nodes` in `parent`, in this order, touching only what changed.
// Rows and messages that stay keep their pictures, players and animations
// (no reload, no flicker, no lost scroll position).
function reconcile(parent, nodes) {
  let cursor = parent.firstChild;
  for (const node of nodes) {
    if (node === cursor) { cursor = cursor.nextSibling; continue; }
    parent.insertBefore(node, cursor);
  }
  while (cursor) { const next = cursor.nextSibling; cursor.remove(); cursor = next; }
}

// Several updates in the same frame (typing, new messages, read receipts) draw the list once.
let chatListFrame = 0;
function queueChatList() {
  if (chatListFrame) return;
  chatListFrame = requestAnimationFrame(() => { chatListFrame = 0; drawChatList(); });
}

// Rows already drawn, by chat: reused while what they show is the same.
const chatRows = { context: '', rows: new Map() };
function chatRow(chat, mode, selecting) {
  const unread = chat.unread || (chat.unread_mark ? '•' : '');
  let timer = null, held = false;
  const chosen = selecting && state.chatSelection.has(chat.id);
  const activity = feature('chat_list_activity');
  const actions = !selecting && mode !== 'forward';
  const row = peerControl({ class: 'row peer-control' + (state.open && state.open.peer === chat.id && mode !== 'forward' ? ' on' : '') + (chosen ? ' selected' : ''),
    onclick: () => { if (held) return; if (selecting) { toggleChatSelected(chat.id); return; } mode === 'forward' ? forwardTo(chat) : openChat(chat.id); },
    oncontextmenu: (event) => { event.preventDefault(); if (mode !== 'forward') chatMenu(chat); },
    ontouchstart: () => { held = false; timer = setTimeout(() => { held = true; if (mode !== 'forward') chatMenu(chat); }, 550); },
    ontouchcancel: () => clearTimeout(timer), ontouchend: () => clearTimeout(timer), ontouchmove: () => clearTimeout(timer) },
    selecting ? h('span', { class: 'mark' }, chosen ? '☑' : '☐') : null,
    actions ? h('button', {type: 'button', class: 'chat-avatar-button', 'aria-label': t('Menú del chat') + ' · ' + chat.name,
      onclick: event => { event.stopPropagation(); if (!held) chatMenu(chat); }}, avatar(chat.id, chat.name, '', null, chat.color)) : avatar(chat.id, chat.name, '', null, chat.color),
    h('div', { class: 'body' },
      h('div', { class: 'top' }, nameWithStatus(chat.name, chat.emoji_status, true, selecting ? !!chosen : null),
        activity && (state.listTyping || {})[chat.id] > Date.now() ? h('span', { class: 'activity' }, '···')
          : activity && chat.online ? h('span', { class: 'activity online', title: t('Online') }, '●') : null,
        chat.status ? h('span', { class: 'tick ' + chat.status }, TICKS[chat.status]) : null,
        h('span', { class: 'when' }, shortTime(chat.date))),
      h('div', { class: 'bottom' },
        state.drafts[chat.id]?.text ? h('span', { class: 'preview draft' }, t('Draft') + ': ' + state.drafts[chat.id].text)
          : chat.draft && !state.drafts[chat.id]
            ? h('span', { class: 'preview draft' }, t('Draft') + ': ' + chat.draft)
            : h('span', { class: 'preview' }, (chat.out ? t('Tu') + ': ' : ''), richText(chat.preview || '', chat.emojis || [], false)),
        chat.pinned || chat.muted ? h('span', { class: 'flags' }, (chat.pinned ? '*' : '') + (chat.muted ? '~' : '')) : null,
        unread ? h('span', { class: 'badge' + (chat.muted ? ' muted' : '') }, unread) : null)));
  return actions && TOUCH ? swipeChatRow(row, chat) : row;
}

function drawChatList() {
  const list = document.getElementById('chatlist');
  if (!list) return;
  const query = state.search.trim().toLowerCase();
  const mode = listMode();
  let source = mode === 'archived' ? (state.archived || []) : state.chats;
  for (const chat of source) if (chat.photo) photoIds.set(chat.id, chat.photo);
  const folder = mode === 'chats' && state.folder !== null ? state.folders.find((item) => item.id === state.folder) : null;
  if (folder) {
    const ids = new Set(folder.chats);
    source = source.filter(chat => ids.has(chat.id));
    if (!state.settings.local_pins) {
      const rank = new Map((folder.pins || []).map((peer, index) => [peer, index]));
      source = source.map(chat => ({...chat, pinFolder: folder.id, pinned: rank.has(chat.id)}))
        .sort((a, b) => (rank.get(a.id) ?? rank.size) - (rank.get(b.id) ?? rank.size));
    }
  }
  const chats = source.filter((chat) => !query || chat.name.toLowerCase().includes(query));
  state.visibleChats = chats.map(chat => chat.id);
  if (!chats.length) {
    const loading = !source.length && !folder && state.connection !== 'offline' && (mode !== 'archived' || state.archived === null);
    list.replaceChildren(h('div', { class: 'empty' }, loading ? t('Cargando...') : t('No hay chats.')));
    if (query.length >= 2 && mode === 'chats') drawGlobal(list, query);
    return;
  }
  const top = list.scrollTop;
  const selecting = mode !== 'forward' && state.chatSelection;
  const activity = feature('chat_list_activity');
  const context = [state.account, mode, !!selecting, state.language, state.rtl, state.avatarVersion || 0, activity,
    state.settings?.ascii_text, state.settings?.photo_previews, animationEnabled(), new Date().toDateString()].join('|');
  if (context !== chatRows.context) { chatRows.context = context; chatRows.rows.clear(); }
  const now = Date.now(), kept = new Map();
  const rows = chats.map((chat) => {
    const key = JSON.stringify(chat) + '\u0001' + (state.open?.peer === chat.id) + (selecting ? state.chatSelection.has(chat.id) : '') +
      (activity && (state.listTyping || {})[chat.id] > now) + '\u0001' + (state.drafts[chat.id]?.text ?? '\u0002') + '\u0001' + shortTime(chat.date);
    const known = chatRows.rows.get(chat.id);
    const row = known && known.key === key && !kept.has(chat.id) ? known.node : chatRow(chat, mode, selecting);
    kept.set(chat.id, { key, node: row });
    return row;
  });
  chatRows.rows = kept;
  reconcile(list, rows);
  watchImages(list);
  reviveAnimations(list);
  if (list.scrollTop !== top) list.scrollTop = top;
  if (query.length >= 2 && mode === 'chats') drawGlobal(list, query);
}

// global search (chats, people and messages on Telegram) -----------------------------
let globalTimer = null;
function drawGlobal(list, query) {
  const account = state.account, revision = state.accountRevision;
  const current = () => account === state.account && revision === state.accountRevision && !state.locked &&
    listMode() === 'chats' && state.search.trim().toLowerCase() === query;
  const section = h('div', { class: 'global', id: 'global' }, h('div', { class: 'section-title' }, t('Search in Telegram')));
  list.append(section);
  const show = (data) => {
    const shown = document.getElementById('global');
    if (!shown || !current()) return;
    const rows = [];
    for (const chat of data.chats) rows.push(peerControl({ class: 'row peer-control', onclick: () => openChat(chat.id, true, chat) },
      avatar(chat.id, chat.name), h('div', { class: 'body' }, h('div', { class: 'top' }, nameWithStatus(chat.name, chat.emoji_status, true)))));
    for (const item of data.messages) rows.push(h('div', { class: 'row', role: 'button',
      onclick: () => openChat(item.peer, true, { id: item.peer, name: item.name }) },
      avatar(item.peer, item.name),
      h('div', { class: 'body' }, h('div', { class: 'top' }, h('span', { class: 'name' }, item.name), h('span', { class: 'when' }, shortTime(item.message && item.message.date))),
        h('div', { class: 'bottom' }, h('span', { class: 'preview' }, (item.message && item.message.text) || '')))));
    shown.replaceChildren(shown.firstChild, ...(rows.length ? rows : [h('div', { class: 'empty' }, t('Sin resultados.'))]));
  };
  if (state.global && state.global.query === query) { if (state.global.data) show(state.global.data); return; }
  section.append(h('div', { class: 'empty spinner' }, ''));
  clearTimeout(globalTimer);
  globalTimer = setTimeout(() => {
    if (!current()) return;
    const pending = state.global = { query, data: null };
    api('search_global', { query }).then((data) => {
      if (!current() || state.global !== pending) return;
      pending.data = data; show(data);
    }, () => {});
  }, 600);
}

function chatsMenu() {
  sheet(t('Chats'), [
    [t('Descargas'), () => downloads.show()],
    [t('Contactos'), () => go('contacts', { contacts: null, search: '' })],
    ...(feature('stories') ? [[t('Stories'), openStories]] : []),
    ...(feature('call_history') ? [[t('Calls'), () => callsView(false)]] : []),
    [t('Saved Messages'), () => attempt(() => api('saved_messages'), (me) => openChat(me.id, true, { id: me.id, name: t('Saved Messages') }))],
    [t('Nuevo chat'), newChat],
    [t('Nuevo grupo'), () => createCommunity(false)],
    [t('New channel'), () => createCommunity(true)],
    [t('Archivados'), () => go('archived', { archived: null, search: '' })],
    [t('Ajustes'), () => go('settings')],
    ...state.accounts.filter((item) => !item.current && item.label).map((item) =>
      [t('Usar') + ': ' + (item.alias || item.label), () => switchAccount(item.key)]),
    [t('Añadir cuenta'), async () => { if (await flushOpenDrafts()) await attempt(() => api('account.add')); }],
    ...appLifeItems(),
  ]);
}

// Reconnect now, restart everything, quit (Android only: iOS apps may not quit themselves).
function appLifeItems() {
  return [
    [t('Reconnect'), reconnect],
    [t('Restart the app'), restartApp],
    PLATFORM === 'Android' ? [t('Quit Tg-As'), () => attempt(() => api('quit')), 'danger'] : null,
  ].filter(Boolean);
}
function reconnect() {
  state.connection = 'reconnecting'; updateStatus();
  attempt(() => api('reconnect'), (value) => { state.connection = value; updateStatus(); drawHeaderStatus(); });
}
async function restartApp() {
  if (!(await saveDraft())) return;
  state.locked = false;
  root.replaceChildren(h('div', { class: 'center' }, logo(), h('div', { class: 'spinner muted' }, t('Cargando...') + ' ')));
  try { await api('restart'); } catch (error) { /* the page reloads either way */ }
  setTimeout(() => location.reload(), 300);
}

function folderPin(chat, changes) {
  const revision = state.accountRevision;
  return attempt(() => api('folder_pin', {folder: chat.pinFolder, peer: chat.id, account: state.account, ...changes}),
    folders => { if (revision === state.accountRevision) { state.folders = folders; queueChatList(); } });
}

function pinMoves(chat) {
  if (!chat.pinned || (chat.kind === 'secret' && !state.settings.local_pins)) return [];
  return [[-1, 'Move pin up'], [1, 'Move pin down']].map(([direction, label]) =>
    [t(label), () => chat.pinFolder != null ? folderPin(chat, {direction}) : attempt(() => api('move_pin', {peer: chat.id, direction, account: state.account}), async () => {
      if (chat.archived) await attempt(fetchArchived);
    })]);
}

function chatMenu(chat) {
  const read = chat.unread || chat.unread_mark;
  sheet(nameWithStatus(chat.name, chat.emoji_status), [
    [t('Preview'), () => openChat(chat.id, true, chat, true)],
    [t('Select'), () => toggleChatSelected(chat.id)],
    [read ? t('Marcar como leido') : t('Marcar como no leido'), () => read
      ? attempt(() => api('mark_read_chat', { peer: chat.id }), queuedNote)
      : attempt(() => api('mark_unread', { peer: chat.id, unread: true }), queuedNote)],
    [chat.pinned ? t('Desfijar') : t('Fijar'), () => chat.pinFolder != null ? folderPin(chat, {pinned: !chat.pinned}) : attempt(() => api('pin_chat', { peer: chat.id, pinned: !chat.pinned }), queuedNote)],
    [chat.muted ? t('Activar sonido') : t('Silenciar'), () => muteSheet(chat)],
    [t('Notifications'), () => chatNotifications(chat)],
    [chat.archived ? t('Desarchivar') : t('Archivar'), () => attempt(() => api('archive_chat', { peer: chat.id, archived: !chat.archived }), (result) => {
      queuedNote(result); if (state.view === 'archived') { state.archived = null; render(); }
    })],
    [t('Add to folder'), () => folderSheet([chat.id])],
    ...pinMoves(chat),
    ...chatTools(chat, false),
    ...leaveItems(chat, false),
  ]);
}

// Tools of a chat shared by the list menu and the in-chat ⋯ menu (desktop: chat_menus.in_chat_entries).
function chatTools(chat, inChat) {
  const dial = state.callsAvailable && feature('calls') && chat.kind === 'user' && !chat.self;
  const community = state.groupCallsAvailable && feature('calls') && (chat.kind === 'group' || chat.kind === 'channel');
  const isSecret = chat.kind === 'secret';
  return [
    dial ? [t('Call'), () => nativeCallAction('start', {peer: chat.id})] : null,
    dial ? [t('Video call'), () => nativeCallAction('start', {peer: chat.id, video: true})] : null,
    dial && state.groupCallsAvailable ? [t('Conference call'), () => groupCallAction('conference', {peer: chat.id})] : null,
    community ? [t('Group call'), () => groupCallSheet(chat)] : null,
    chat.kind === 'user' && !chat.self && !chat.bot ? ['🔒 ' + t('Iniciar chat secreto'), () => startSecretChat(chat.id)] : null,
    isSecret ? ['🔒 ' + t('Clave de cifrado y autodestrucción'), () => secretChatSheet(chat)] : null,
    [t('Profile'), () => openProfile(chat)],
    [t('Buscar en el chat'), async () => { if (!inChat) await openChat(chat.id, true, chat); searchInChat(); }],
    PLATFORM === 'iOS' && !isSecret ? ['Mostrar en Apple TV', () => confirmThen(
      '¿Mostrar en el Apple TV conectado los textos recientes de «' + chat.name + '»?',
      () => attempt(() => api('tv_share', {peer: chat.id, account: state.account})))] : null,
    PLATFORM === 'iOS' ? ['Desconectar Apple TV', () => attempt(() => api('tv_disconnect'))] : null,
    [t('Shared media'), () => openShared(chat, 'photos')],
    !isSecret ? [t('Pinned messages'), () => pinnedList(chat)] : null,
    !isSecret ? [t('Scheduled messages'), () => scheduledList(chat)] : null,
    [t('Chat background'), () => chatBackgroundMenu(chat)],
    !isSecret && inChat && feature('chat_translation') ? [(state.open && state.open.translate ? '✓ ' : '') + t('Automatic translation (Premium)'), translateChat] : null,
    [t('Open chat in new window'), () => openChatWindow(chat)],
  ].filter(Boolean);
}

// Clear history, leave a group or channel, delete a chat (asks first).
function leaveItems(chat, inChat) {
  const after = (result) => { queuedNote(result); if (inChat) back(); };
  const items = [[t('Clear history'), () => confirmThen(t('Clear history') + '?', () => attempt(() => api('clear_chat', { peer: chat.id }), (result) => {
    queuedNote(result); if (state.open && state.open.peer === chat.id) { state.open.messages = []; state.open.historyLoaded = true; drawMessages(true); }
  })), 'danger']];
  if (chat.kind === 'secret') items.push([t('Cerrar chat secreto'), () => confirmThen(t('Cerrar chat secreto') + ': ' + chat.name + '?',
    () => attempt(() => api('secret_discard', { peer: chat.id, delete_history: true }), after)), 'danger']);
  else if (chat.kind === 'channel' || chat.kind === 'group') items.push([t('Leave'), () => confirmThen(t('Leave') + ': ' + chat.name + '?',
    () => attempt(() => api('leave_chat', { peer: chat.id }), after)), 'danger']);
  else items.push([t('Delete chat'), () => confirmThen(t('Delete chat') + ': ' + chat.name + '?',
    () => attempt(() => api('delete_chat', { peer: chat.id }), after)), 'danger']);
  return items;
}

function startSecretChat(peer) {
  const revision = state.accountRevision;
  toast(t('Iniciando chat secreto...'));
  attempt(() => api('secret_start', { peer }), (chat) => {
    if (revision === state.accountRevision && !state.locked && chat && chat.id) openChat(chat.id, true, chat);
  });
}

function secretKeyGrid(rows) {
  if (!rows.length) return null;
  const grid = h('canvas', { width: 144, height: 144, 'aria-hidden': 'true',
    style: 'display:block;margin:6px auto;max-width:100%;height:auto' });
  const paint = grid.getContext('2d');
  if (!paint) return h('pre', { dir: 'ltr' }, rows.join('\n'));
  const colors = { '□': '#ffffff', '▤': '#d5e6f3', '▦': '#2d5775', '■': '#2f99c9' };
  rows.forEach((row, y) => Array.from(row).forEach((cell, x) => {
    paint.fillStyle = colors[cell];
    paint.fillRect(x * 12, y * 12, 12, 12);
  }));
  return grid;
}

function secretChatSheet(chat) {
  const revision = state.accountRevision;
  attempt(() => api('secret_info', { peer: chat.id }), (info) => {
    if (revision !== state.accountRevision) return;
    const layer = document.getElementById('sheet-layer');
    const emojis = (info.emojis || '').split(' ').join('  ') || '🔒';
    const grid = secretKeyGrid(info.grid || []);
    let confirmedTtl = Number(info.ttl) || 0;
    const ttlValues = [...new Set([...info.ttl_choices, confirmedTtl])].sort((a, b) => a - b);
    const ttlLabel = (seconds) => {
      if (!seconds) return t('Desactivado');
      const [size, unit] = [[604800, 'week'], [86400, 'day'], [3600, 'hour'], [60, 'minute'], [1, 'second']]
        .find(([size]) => seconds % size === 0);
      return new Intl.NumberFormat(state.language || 'en', {style: 'unit', unit}).format(seconds / size);
    };
    const ttlSelect = h('select', { onchange: async (event) => {
      const select = event.target;
      const seconds = Number(select.value);
      select.disabled = true;
      try {
        const result = await attempt(() => api('secret_ttl', { peer: chat.id, seconds }));
        if (result) {
          confirmedTtl = Number(result.ttl) || 0;
          if (![...select.options].some((option) => Number(option.value) === confirmedTtl)) {
            select.append(h('option', { value: confirmedTtl }, ttlLabel(confirmedTtl)));
          }
          toast(t('Temporizador de autodestrucción (TTL)') + ': ' + ttlLabel(confirmedTtl));
        }
        select.value = String(confirmedTtl);
      } finally {
        select.disabled = false;
      }
    } }, ttlValues.map((seconds) => h('option', { value: seconds, selected: confirmedTtl === seconds }, ttlLabel(seconds))));
    const close = () => closeSheet();
    layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
      h('h3', {}, '🔒 ' + (chat.name || t('Cifrado de extremo a extremo'))),
      h('div', { class: 'muted small' }, t('Cifrado de extremo a extremo') + (info.layer ? ' · MTProto ' + info.layer : '')),
      h('div', { dir: 'ltr', style: 'font-size:1.6em;text-align:center;margin:8px 0;letter-spacing:4px' }, emojis),
      grid,
      info.hex ? h('div', { class: 'muted small', style: 'word-break:break-all;text-align:center;margin:4px 0' }, 'HEX · ', h('bdi', { dir: 'ltr' }, info.hex)) :
        info.state === 'active' ? h('div', { class: 'muted small' }, 'HEX · ', t('Unavailable')) : null,
      grid ? h('div', { class: 'muted small', style: 'margin:6px 0' },
        t('Si estos 5 emojis y la cuadrícula coinciden con los del teléfono de {name}, el cifrado de extremo a extremo está garantizado.',
          {name: info.user_name || t('tu contacto')})) : null,
      labelled(t('Temporizador de autodestrucción (TTL)'), ttlSelect),
      h('button', { class: 'item', onclick: () => attempt(() => api('secret_rekey', { peer: chat.id }), () => { close(); toast(t('Rotación de clave solicitada (PFS).')); }) }, t('Rotar clave ahora (PFS)')),
      h('button', { class: 'item', onclick: () => attempt(() => api('secret_screenshot', { peer: chat.id }), () => { close(); toast(t('Enviado.')); }) }, t('Enviar aviso de captura de pantalla')),
      h('button', { class: 'item danger', onclick: () => { close(); confirmThen(t('Cerrar chat secreto') + ': ' + chat.name + '?',
        () => attempt(() => api('secret_discard', { peer: chat.id, delete_history: true }), () => { if (state.open && state.open.peer === chat.id) back(); })); } }, t('Cerrar chat secreto')),
      h('button', { class: 'item', onclick: close }, t('Cancelar'))));
    activateSheet(layer);
    layer.onclick = close;
  });
}

// Mute for a while or until turned back on (desktop: Mute menu with a duration).
function muteSheet(chat, done) {
  const finish = (muted) => (result) => { chat.muted = muted; queuedNote(result); if (done) done(); drawChatList(); };
  if (chat.muted) return attempt(() => api('mute_chat', { peer: chat.id, muted: false }), finish(false));
  const mute = (duration) => attempt(() => api('mute_chat', { peer: chat.id, muted: true, duration }), finish(true));
  sheet(t('Silenciar') + ': ' + chat.name, [
    [t('For 1 hour'), () => mute(3600)], [t('For 8 hours'), () => mute(8 * 3600)], [t('For 1 day'), () => mute(86400)],
    [t('For 7 days'), () => mute(7 * 86400)], [t('Forever'), () => mute(null)],
  ]);
}

// Telegram folders: add or remove one chat, or add the selected chats.
function folderSheet(peers, done) {
  const revision = state.accountRevision, account = state.account;
  attempt(() => fetchFolders(true), (folders) => {
    if (!folders || revision !== state.accountRevision) return;
    if (!folders.length) { toast(t('No folders yet. Create one in Folders.')); return; }
    sheet(t('Add to folder'), folders.map((folder) => {
      const inside = peers.length === 1 && folder.chats.includes(peers[0]);
      return [(inside ? '✓ ' : '') + folder.title, () => attempt(() => peers.length === 1
        ? api('folder_membership', { account, folder: folder.id, peer: peers[0], include: !inside })
        : api('chats_batch', { peers, action: 'folder', value: folder.id, account }), (result) => {
        if (revision !== state.accountRevision) return;
        if (Array.isArray(result)) state.folders = result;
        drawFolderTabs(); drawChatList(); toast(t('Saved.')); if (done) done();
      })];
    }));
  });
}

// Pinned messages of a chat: tap one to go to it.
async function pinnedList(chat, thread_root) {
  const revision = state.accountRevision;
  const list = await attempt(() => api('pinned', {peer: chat.id, thread_root}));
  if (!list || revision !== state.accountRevision || state.locked) return;
  if (!list.length) { toast(t('Sin resultados.')); return; }
  sheet(t('Pinned messages'), list.map((message) => [((message.visual ? message.caption : message.text) || message.kind || '').replace(/\s+/g, ' ').slice(0, 90) || '…',
    async () => { if (!state.open || state.open.peer !== chat.id) await openChat(chat.id, true, chat); jumpTo(message.id); }]));
}

// Scheduled messages: send now or delete (desktop: Scheduled messages).
async function scheduledList(chat, thread_root) {
  const revision = state.accountRevision;
  const list = await attempt(() => api('scheduled', {peer: chat.id, thread_root}));
  if (!list || revision !== state.accountRevision || state.locked) return;
  if (!list.length) { toast(t('No scheduled messages.')); return; }
  const when = (seconds) => seconds ? new Date(seconds * 1000).toLocaleString(state.language || undefined, { dateStyle: 'short', timeStyle: 'short' }) : '';
  sheet(t('Scheduled messages'), list.map((message) => [when(message.scheduled) + ' · ' + ((message.visual ? message.caption : message.text) || message.kind || '').replace(/\s+/g, ' ').slice(0, 70),
    () => sheet(when(message.scheduled), [
      [t('Send now'), () => attempt(() => api('scheduled_action', { peer: chat.id, id: message.id, send_now: true }), () => toast(t('Enviado.')))],
      [t('Delete'), () => confirmThen(t('Delete') + '?', () => attempt(() => api('scheduled_action', { peer: chat.id, id: message.id, send_now: false }), () => toast(t('Saved.')))), 'danger'],
    ])]));
}

// Selecting several chats in the list (desktop: Select, then the selection's Actions).
function toggleChatSelected(id) {
  if (!state.chatSelection) state.chatSelection = new Set();
  if (state.chatSelection.has(id)) state.chatSelection.delete(id); else state.chatSelection.add(id);
  if (!state.chatSelection.size) state.chatSelection = null;
  drawChatSelection(); drawChatList();
}
function drawChatSelection() {
  const bar = document.getElementById('chat-selection-bar');
  if (!bar) return;
  if (!state.chatSelection) { bar.hidden = true; bar.replaceChildren(); return; }
  const clear = () => { state.chatSelection = null; drawChatSelection(); drawChatList(); };
  bar.replaceChildren(h('span', { class: 'count' }, t('Selected') + ': ' + state.chatSelection.size),
    bulkButtons(() => { state.chatSelection = new Set(state.visibleChats || []); drawChatSelection(); drawChatList(); }, clear),
    button(t('Actions'), () => chatSelectionMenu(clear), 'primary'), symbolButton('x', t('Cancelar'), clear));
  bar.hidden = false;
}
function chatSelectionMenu(clear) {
  const peers = [...state.chatSelection];
  const run = (action, value = true) => attempt(() => api('chats_batch', { peers, action, value, account: state.account }), () => {
    toast(t('Saved.')); clear();
    if (state.view === 'archived') { state.archived = null; render(); }
  });
  sheet(t('Selected') + ': ' + peers.length, [
    [t('Select all'), () => { state.chatSelection = new Set(state.visibleChats || peers); drawChatSelection(); drawChatList(); }],
    [t('Archivar'), () => run('archive', true)], [t('Desarchivar'), () => run('archive', false)],
    [t('Silenciar'), () => run('mute', true)], [t('Activar sonido'), () => run('mute', false)],
    [t('Marcar como leido'), () => run('read', true)], [t('Marcar como no leido'), () => run('read', false)],
    [t('Fijar'), () => run('pin', true)], [t('Desfijar'), () => run('pin', false)],
    [t('Add to folder'), () => folderSheet(peers, clear)],
    [t('Delete chat'), () => confirmThen(t('Delete chat') + ' (' + peers.length + ')?', () => run('delete')), 'danger'],
  ]);
}
const queuedNote = (result) => {
  if (result && result.queued) toast(t('Accion guardada; se enviara al volver la conexion.'));
  // Apply Telegram's answer at once: own edits do not always come back as updates.
  const message = result && result.message;
  if (message && state.open) EVENTS.edit({ peer: state.open.peer, message });
};

async function flushOpenDrafts() {
  const account = state.account;
  const results = await Promise.all([saveDraft(), ...state.windows.filter(win => win.opened && win.draftReady)
    .map(win => saveWindowDraft(win))]);
  return state.account === account && results.every(Boolean);
}

async function switchAccount(key) {
  if (!(await flushOpenDrafts())) return;
  state.open = null; state.chats = []; state.view = 'chats';
  render();
  await attempt(() => api('account.select', { key }));
}

// conversation --------------------------------------------------------------------
async function openChat(peer, navigate = true, known = null, preview = false) {
  if (known?.forum) return openForumList(known, navigate);
  const account = state.account;
  const request = state.openRequest = (state.openRequest || 0) + 1;
  const current = () => account === state.account && request === state.openRequest && !state.locked && !unavailableWindow();
  rememberChatPlace();
  if (state.open && !(await saveDraft())) return;
  if (!current()) return;
  // The fresh history event can arrive before the request returns its cached page.
  const pending = state.openingChat = {account, peer, history: null};
  let data;
  try { data = await api('open', {peer, read: !preview, window: WINDOW_CHAT === peer}); }
  catch (error) { if (current()) toast(error.message, 'error'); return; }
  finally { if (state.openingChat === pending) state.openingChat = null; }
  if (!data || !current()) return;
  if (data.forum) return openForumList(data.chat, navigate);
  if (pending.history) Object.assign(data, pending.history);
  state.open = { peer, chat: data.chat || state.chats.find((item) => item.id === peer) || known || { id: peer, name: String(peer) },
    messages: data.messages, historyLoaded: !!pending.history || data.messages.length > 0, outbox: data.outbox.items.filter(item => item.thread_root == null), loadingOlder: false, done: false, status: '', typing: '', preview,
    // Automatic translation kept for this account and chat (shown from the saved translations).
    translate: data.translate || null, translated: data.translated || {}, translating: new Set(), originals: new Set() };
  state.selection = null;
  // On wide screens the list stays; opening another chat replaces the open one.
  if (navigate && WIDE() && state.view === 'chat') navigate = false;
  state.reply = state.editing = null;
  if (!draftWrites.has(draftKey(peer)) && !failedDraftWrites.has(draftKey(peer))) state.drafts[peer] = data.draft;
  if (navigate) go('chat'); else render();
  if (state.open && state.open.translate) translatePending();
  return state.open;
}

const draftWrites = new Map();
const failedDraftWrites = new Set();
const draftSends = new Set();
const composerPeer = (open = state.open) => open.thread ? open.peer + '/' + open.thread.root : open.peer;
const sendDestination = (open = state.open) => ({
  peer: open.peer, account: state.account, thread_root: open.thread?.root, topic_id: open.topic?.id, reply_to: state.reply?.id ?? null,
});
function consumeReply(open, id) {
  if (id !== null && state.open === open && state.reply?.id === id) {
    state.reply = null;
    drawContext();
    saveDraft();
  }
}
const draftKey = (peer) => state.account + ':' + peer;
const emptyDraft = () => ({text: '', formats: [], custom: [], files: [], reply: null});
const codePointOffset = (text, index) => [...text.slice(0, index)].length;

function draftContents(peer, text) {
  const formats = (state.formats[peer] || []).map(({start, end, style, argument}) =>
    [codePointOffset(text, start), codePointOffset(text, end), style, argument || '']);
  let cursor = 0;
  const custom = [];
  for (const [id, alt, offset] of state.customEmoji[peer] || []) {
    const at = offset ?? text.indexOf(alt, cursor);
    if (at < 0 || !alt || text.slice(at, at + alt.length) !== alt) continue;
    custom.push([codePointOffset(text, at), codePointOffset(text, at + alt.length), id, alt]);
    cursor = at + alt.length;
  }
  custom.sort((left, right) => left[0] - right[0]);
  return { text, formats, custom, reply: state.reply?.id || null,
    files: state.attachments.map(file => file.key),
    ...(state.attachments.length ? {photo_quality: selectedPhotoQuality(state)} : {}) };
}

function updateDraftEmoji(peer, text, inserted) {
  const previous = state.drafts[peer]?.text || '';
  let prefix = 0, oldEnd = previous.length, newEnd = text.length;
  while (prefix < oldEnd && prefix < newEnd && previous[prefix] === text[prefix]) prefix++;
  while (oldEnd > prefix && newEnd > prefix && previous[oldEnd - 1] === text[newEnd - 1]) {
    oldEnd--; newEnd--;
  }
  const emojis = (state.customEmoji[peer] || []).flatMap(([id, alt, at]) => {
    if (at == null || at + alt.length <= prefix) return [[id, alt, at]];
    return at >= oldEnd ? [[id, alt, at + newEnd - oldEnd]] : [];
  });
  if (inserted) emojis.push(inserted);
  state.customEmoji[peer] = emojis;
}

function insertDraftEmoji(field, item) {
  if (!field || state.editing) return;
  const at = field.selectionStart;
  field.setRangeText(item.emoji, at, field.selectionEnd, 'end');
  field.dispatchEvent(new CustomEvent('input', {detail: {emoji: [item.id, item.emoji, at]}}));
}

function restoreComposer(field, record) {
  if (!field || !state.open) return;
  record = record || emptyDraft();
  const peer = composerPeer();
  const chars = [...record.text];
  const offset = (index) => chars.slice(0, index).join('').length;
  if (field.value !== record.text) field.value = record.text;
  resizeComposer(field);
  state.formats[peer] = record.formats.map(([start, end, style, argument]) =>
    ({ start: offset(start), end: offset(end), style, argument, text: chars.slice(start, end).join('') }));
  state.customEmoji[peer] = record.custom.map(([start, , id, alt]) => [id, alt, offset(start)]);
  state.reply = record.reply ? state.open.messages.find(item => item.id === record.reply) ||
    {id: record.reply, sender: '', text: t('Mensaje')} : null;
  state.photo_quality = selectedPhotoQuality(record);
  state.attachments = record.files.map(file => typeof file === 'string'
    ? {key: file, name: file.slice(file.indexOf('-') + 1), size: 0} : file);
  drawContext(); drawAttachments(); drawFormatPreview();
}

function saveDraft() {
  const field = document.getElementById('field');
  if (!state.open || !field || state.editing || state.open.sending) return Promise.resolve(true);
  const open = state.open, peer = composerPeer(open);
  const record = {...draftContents(peer, field.value), files: [...state.attachments]};
  return writeDraft(peer, record, {peer: open.peer, thread_root: open.thread?.root, window_peer: WINDOW_CHAT});
}

function writeDraft(peer, record, destination, sourceWindow = null) {
  const account = state.account, key = draftKey(peer);
  if (draftSends.has(key)) return Promise.resolve(false);
  const current = state.drafts[peer];
  const payload = {...record, files: record.files.map(file => file.key || file)};
  const known = current && {...current, files: current.files.map(file => file.key || file)};
  const previous = draftWrites.get(key);
  if (!failedDraftWrites.has(key) && known && JSON.stringify(known) === JSON.stringify(payload)) return previous || Promise.resolve(true);
  if (!known && !record.text && !record.files.length && !record.reply) return Promise.resolve(true);
  state.drafts[peer] = record;
  if (!destination.thread_root) {
    for (const win of state.windows) if (win.peer === peer && win !== sourceWindow && !win.sending) restoreWindowDraft(win, record);
    if (sourceWindow && state.open?.peer === peer && !state.open.thread && !state.editing && !state.open.sending) {
      restoreComposer(document.getElementById('field'), record);
    }
  }
  const write = (previous || Promise.resolve()).then(async () => {
    try {
      await api('draft', {account, ...destination, ...payload});
      failedDraftWrites.delete(key);
      return true;
    } catch (error) {
      if (state.account === account && draftWrites.get(key) === write) {
        failedDraftWrites.add(key);
        toast(error.message, 'error');
      }
      return false;
    }
  }).finally(() => { if (draftWrites.get(key) === write) draftWrites.delete(key); });
  draftWrites.set(key, write);
  return write;
}

function newChat() {
  promptThen(t('Nuevo chat'), { value: '@', note: t('Introduce un @usuario o telefono internacional.') }, (value) => {
    if (!value || value.trim() === '@') return false;
    const revision = state.accountRevision;
    attempt(() => api('resolve', { value: value.trim() }), (chat) => {
      if (revision === state.accountRevision && !state.locked) openChat(chat.id, true, chat);
    });
  });
}

function chatView(kept = null) {
  const open = state.open;
  if (open.forumList) return forumListView(open);
  const {chat, thread} = open;
  const wide = WIDE() && !listCoversAll();
  const bar = h('div', { class: 'bar' }, WINDOW_CHAT !== null && !thread ? null
      : wide ? symbolButton('x', t('Close chat'), back) : backButton(),
    peerControl({ class: 'title with-avatar peer-control', onclick: () => openProfile(chat) }, avatar(chat.id, chat.name, 'small'),
      h('div', { class: 'names' }, nameWithStatus(open.topic?.title || (thread ? t('Comments') : chat.name), thread ? null : chat.emoji_status, true), h('span', { class: 'sub', id: 'chat-status' }, thread?.channel.name || ''))),
    wide && !thread && WINDOW_CHAT === null ? h('button', { class: 'btn', title: t('Open chat in new window'), onclick: () => openChatWindow(chat) }, '⧉') : null,
    chat.kind === 'secret' && !thread ? h('button', { class: 'btn', title: t('Clave de cifrado y autodestrucción'), onclick: () => secretChatSheet(chat) }, '🔒') : null,
    symbolButton('⋯', t('More options'), () => conversationMenu(chat)));
  const peer = state.open.peer;
  const previewBar = state.open.preview ? h('div', { class: 'preview-bar', id: 'preview-bar' },
    h('span', {}, '👁 ' + t('Preview: not marked as read')),
    button(t('Mark as read'), () => attempt(() => api('read', { peer }), (result) => {
      queuedNote(result); if (state.open && state.open.peer === peer) state.open.preview = false;
      document.getElementById('preview-bar')?.remove();
    }))) : null;
  const scroll = h('div', { class: 'scroll chat-scroll' + (state.settings.bubbles ? ' bubbles' : ''), id: 'scroll',
    onscroll: (event) => chatScrolled(event.target),
    // The person scrolls: stop keeping the newest message in view.
    ontouchmove: () => { if (state.open) state.open.stickUntil = 0; },
    onwheel: () => { if (state.open) state.open.stickUntil = 0; } },
    h('div', { class: 'messages', id: 'messages' }), h('div', { class: 'messages', id: 'outbox' }));
  paintChatWallpaper(scroll, state.open.peer);
  const pinned = h('div', { class: 'pinned', id: 'pinned', hidden: true });
  const down = h('button', { class: 'btn down', id: 'down', hidden: true, onclick: () => {
    const box = document.getElementById('scroll'); box.scrollTop = box.scrollHeight; } }, 'v');
  loadPinned();
  const readonly = !!open.topic && !open.topic.can_send;
  const selectionBar = h('div', { class: 'selection-bar', id: 'selection-bar', hidden: true });
  return [bar, previewBar, pinned, selectionBar, scroll, down, readonly ? h('div', { class: 'readonly' }, t('Este chat es de solo lectura.')) : composer()].filter(Boolean);
}

// Complete the mounted conversation in the same task as the new DOM. Restoring
// a multiline draft or scroll on a later timer exposed an intermediate layout.
function mountChatView(kept = null) {
  const open = state.open, box = document.getElementById('scroll');
  if (!open || open.forumList || !box || !document.getElementById('messages')) return;
  const field = document.getElementById('field');
  if (field && !kept?.composer && !state.editing && !open.sending) restoreComposer(field, state.drafts[composerPeer(open)]);
  if (field) { drawContext(); drawAttachments(); drawFormatPreview(); resizeComposer(field); composerMode(); }
  if (!open.thread) drawHeaderStatus();
  drawMessages(!kept?.scroll); drawOutbox();
  // Once per opening, not when a preference or an event redraws the same chat.
  const key = state.account + ':' + open.peer;
  const place = keepLoaded() && !open.thread && !open.placed ? chatPlaces.get(key) : undefined;
  open.placed = true;
  if (place !== undefined) {
    chatPlaces.delete(key);
    box.scrollTop = Math.max(0, box.scrollHeight - box.clientHeight - place);
    open.stickUntil = 0;
  }
  drawSelection();
}

// At most once per frame: ask for older messages well before the top is reached
// (about two screens ahead), so scrolling up never stops at an empty edge.
let chatScrollFrame = 0;
function chatScrolled(box) {
  if (chatScrollFrame) return;
  chatScrollFrame = requestAnimationFrame(() => {
    chatScrollFrame = 0;
    if (!box.isConnected) return;
    if (box.scrollTop < Math.max(600, box.clientHeight * 2)) loadOlder();
    updateDownButton();
  });
}

function updateDownButton() {
  const box = document.getElementById('scroll'), down = document.getElementById('down');
  if (box && down) down.hidden = nearBottom(box);
}

async function loadPinned() {
  const open = state.open;
  if (!open || open.chat?.kind === 'secret') return;
  const account = state.account, revision = state.accountRevision;
  const pending = open.pinnedRequest;
  if (pending?.account === account && pending.revision === revision) return pending.promise;
  const request = {account, revision};
  open.pinnedRequest = request;
  request.promise = (async () => {
    try {
      const list = await api('pinned', {peer: open.peer, thread_root: open.thread?.root});
      const bar = document.getElementById('pinned');
      if (!bar || state.open !== open || state.account !== account || state.accountRevision !== revision || state.locked) return;
      if (!list.length) {
        if (!bar.hidden) bar.hidden = true;
        if (bar.childNodes.length) bar.replaceChildren();
        bar.onclick = null;
        delete bar.dataset.pinnedSignature;
        return;
      }
      const latest = list[0];
      const label = '📌 ' + t('Pinned messages') + (list.length > 1 ? ' (' + list.length + ')' : '') + ': ';
      const text = ((latest.visual ? latest.caption : latest.text) || '').replace(/\s+/g, ' ').slice(0, 120);
      const signature = JSON.stringify([latest.id, label, text]);
      if (bar.dataset.pinnedSignature !== signature) {
        bar.replaceChildren(h('span', {class: 'muted'}, label), h('span', {}, text));
        bar.onclick = () => jumpTo(latest.id);
        bar.dataset.pinnedSignature = signature;
      }
      if (bar.hidden) bar.hidden = false;
    } catch (error) { /* Keep the last known pinned message while offline. */ }
    finally { if (open.pinnedRequest === request) delete open.pinnedRequest; }
  })();
  return request.promise;
}

async function jumpTo(id) {
  const open = state.open;
  if (!open || open.forumList) return;
  const account = state.account, revision = state.accountRevision;
  const request = open.jumpRequest = (open.jumpRequest || 0) + 1;
  const active = () => state.open === open && state.account === account && revision === state.accountRevision &&
    open.jumpRequest === request && state.view === 'chat' && !state.locked;
  const target = () => document.getElementById('m' + id);
  // chatView schedules its initial drawing and bottom scroll when opening a chat.
  await new Promise(resolve => setTimeout(resolve, 0));
  if (!active()) return;
  if (!target() && open.olderRequest) await open.olderRequest;
  if (!active()) return;
  if (!target()) {
    const params = {account, peer: open.peer, id, window_peer: WINDOW_CHAT};
    if (open.topic) params.topic_id = open.topic.id;
    else if (open.thread) params.thread_root = open.thread.root;
    let page;
    try { page = await api('context', params); }
    catch (error) { if (active()) toast(error.message, 'error'); return; }
    if (!active()) return;
    const messages = open.thread ? page.messages : page;
    if (!messages.some(item => item.id === id)) {
      toast(t('This message is no longer available in this chat.'), 'error');
      return;
    }
    if (open.thread) {
      const root = !open.topic && open.messages.find(item => item.id === open.thread.root);
      open.messages = root ? [root, ...messages.filter(item => item.id !== root.id)] : messages;
      open.thread.cursor = page.next;
      open.done = !page.more;
      if (open.translate === page.translate && open.translated) Object.assign(open.translated, page.translated);
    } else {
      open.messages = messages;
      open.done = false;
    }
    open.historyLoaded = true;
    drawMessages(false);
  }
  open.stickUntil = 0;
  const node = target();
  if (node) focusMessageNode(node);
}

// selecting several messages ------------------------------------------------------
function toggleSelected(message) {
  if (!state.selection) state.selection = new Set();
  if (state.selection.has(message.id)) state.selection.delete(message.id); else state.selection.add(message.id);
  if (!state.selection.size) state.selection = null;
  const entering = state.selection && state.selection.size === 1 && state.selection.has(message.id);
  if (entering || !state.selection) drawMessages(false);  // show / hide the ☐ markers
  else {
    const node = document.getElementById('m' + message.id);
    node?.classList.toggle('selected', state.selection.has(message.id));
    const mark = node?.querySelector('.mark'); if (mark) mark.textContent = state.selection.has(message.id) ? '☑ ' : '☐ ';
  }
  drawSelection();
}

function drawSelection() {
  const bar = document.getElementById('selection-bar');
  if (!bar) return;
  if (!state.selection) { bar.hidden = true; bar.replaceChildren(); return; }
  const ids = [...state.selection];
  const clear = () => {
    state.selection = null; drawSelection(); drawMessages(false);
  };
  bar.replaceChildren(h('span', { class: 'count' }, t('Selected') + ': ' + ids.length),
    bulkButtons(() => { state.selection = new Set(state.open.messages.filter(m => !m.service).map(m => m.id)); drawMessages(false); drawSelection(); }, clear),
    button(t('Actions'), () => selectionMenu(ids, clear), 'primary'), symbolButton('x', t('Cancelar'), clear));
  bar.hidden = false;
}

// The tools for the selected messages (desktop: interactions.selection_actions).
function selectionMenu(ids, clear) {
  const peer = state.open.peer;
  const chosen = state.open.messages.filter((item) => ids.includes(item.id));
  const isSecret = state.open.chat?.kind === 'secret';
  const protectedOne = isSecret || chosen.some((item) => item.protected);
  const own = chosen.every((item) => item.out);
  const items = [
    [t('Select all'), () => { state.selection = new Set(state.open.messages.filter((m) => !m.service).map((m) => m.id)); drawMessages(false); drawSelection(); }],
    [t('Copy text'), () => { copy(chosen.map((m) => m.sender + ': ' + (m.text || '')).join('\n\n')); clear(); }],
  ];
  if (!protectedOne) items.push(
    [t('Forward message'), () => { clear(); chooseForwardTarget({peer, ids}); }],
    [t('Save to Saved Messages'), () => attempt(() => api('forward_many', { account: state.account, peer, ids, destination: 'me' }), (result) => { queuedNote(result); clear(); })]);
  items.push([t('Delete for me'), () => confirmThen(t('Delete this message for you?') + ' (' + ids.length + ')',
    () => { attempt(() => api('delete_many', { peer, ids, everyone: false }), queuedNote); clear(); }), 'danger']);
  if (own || state.open.chat.kind !== 'user') items.push([t('Delete for everyone'), () => confirmThen(t('Delete this message for everyone?') + ' (' + ids.length + ')',
    () => { attempt(() => api('delete_many', { peer, ids, everyone: true }), queuedNote); clear(); }), 'danger']);
  sheet(t('Selected') + ': ' + ids.length, items);
}

function drawHeaderStatus() {
  const node = document.getElementById('chat-status');
  if (!node || !state.open) return;
  const discussion = state.open.thread;
  node.className = 'sub' + (state.open.typing ? ' typing' : '');
  node.textContent = state.open.typing || discussion?.channel.name || state.open.status || '';
}

function conversationMenu(chat) {
  if (state.open?.thread) {
    const open = state.open;
    if (open.topic) { forumTopicMenu(open.chat, open.topic); return; }
    const group = {id: open.peer, name: t('Comments')};
    sheet(t('Comments'), [
      [t('Buscar en el chat'), searchInChat],
      [t('Pinned messages'), () => pinnedList(group, open.thread.root)],
      [t('Scheduled messages'), () => scheduledList(group, open.thread.root)],
      feature('chat_translation') ? [(state.open.translate ? '✓ ' : '') + t('Automatic translation (Premium)'), translateChat] : null,
      [t('Chat background'), () => chatBackgroundMenu(group)],
    ]);
    return;
  }
  const person = chat.kind === 'user' && !(state.open && state.open.isSelf) && !chat.self;
  sheet(chat.name, [
    ...chatTools(chat, true),
    chat.has_link ? [t('Debate vinculado'), () => openLinkedDiscussion(chat)] : null,
    chat.forum ? [t('Todos los temas'), () => openForumList(chat, false)] : null,
    WINDOW_CHAT !== null ? [t('Nombre visible de la app'), editDisplayName] : null,
    person ? [t('Share contact'), () => shareContacts([chat.id])] : null,
    [chat.muted ? t('Activar sonido') : t('Silenciar'), () => muteSheet(chat)],
    [t('Notifications'), () => chatNotifications(chat)],
    [chat.pinned ? t('Desfijar') : t('Fijar'), () => attempt(() => api('pin_chat', { peer: chat.id, pinned: !chat.pinned }), (result) => { queuedNote(result); })],
    [chat.archived ? t('Desarchivar') : t('Archivar'), () => attempt(() => api('archive_chat', { peer: chat.id, archived: !chat.archived }), (result) => { chat.archived = !chat.archived; queuedNote(result); })],
    [t('Add to folder'), () => folderSheet([chat.id])],
    ...leaveItems(chat, true),
  ].filter(Boolean));
}

function searchInChat(query = '') {
  const layer = document.getElementById('sheet-layer');
  const input = h('input', { type: 'search', 'data-search-scope': 'messages:' + state.open.peer, placeholder: t('Buscar en el chat'), value: typeof query === 'string' ? query : '' });
  const today = new Date();
  const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
  const day = h('input', { type: 'date', 'aria-label': t('Date'), max: localToday.toISOString().slice(0, 10) });
  const results = h('div', {});
  let revision = 0;
  const run = async () => {
    const open = state.open, request = ++revision;
    const text = input.value.trim(), date = day.value;
    if (!open || (!text && !date)) { results.replaceChildren(); return; }
    let dayBounds = null;
    if (date) {
      const start = new Date(date + 'T00:00:00');
      const end = new Date(start);
      end.setDate(end.getDate() + 1);
      dayBounds = [start.getTime() / 1000, end.getTime() / 1000];
    }
    const found = await attempt(() => api('search_messages', {peer: open.peer, query: text,
      thread_root: open.thread?.root, date: date || null, day_bounds: dayBounds}));
    if (!found || state.open !== open || request !== revision || !results.isConnected || layer.hidden) return;
    if (!text && date && found.length) {
      closeSheet(); jumpTo(found[0].id); return;
    }
    results.replaceChildren(...(found.length ? found.map((message) => h('button', { class: 'item', onclick: () => {
      closeSheet(); jumpTo(message.id);
    } }, (message.time || '') + ' ' + message.sender + ': ' + (message.text || '').slice(0, 120))) : [h('div', { class: 'empty' }, t('Sin resultados.'))]));
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') run(); });
  day.addEventListener('change', run);
  layer.replaceChildren(h('div', { class: 'sheet', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Buscar en el chat')), h('div', { class: 'quick' }, input, button(t('Buscar'), run)),
    labelled(t('Date'), day), results));
  activateSheet(layer);
  layer.onclick = closeSheet;
  input.focus();
  if (input.value) run();
}

function dayLabel(seconds) {
  const date = new Date(seconds * 1000), now = new Date();
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === now.toDateString()) return t('Hoy');
  if (date.toDateString() === yesterday.toDateString()) return t('Ayer');
  return date.toLocaleDateString(state.language, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

const lastTap = { id: null, at: 0 };
function quickReact(message, node) {
  const value = (state.settings && state.settings.quick_reaction) || '👍';
  node.classList.add('reacted'); setTimeout(() => node.classList.remove('reacted'), 400);
  react(message, value);
}

function messageActionKey(event, action) {
  if (event.target !== event.currentTarget) return;
  if (event.key !== 'Enter' && event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
  event.preventDefault();
  if (!event.repeat) action();
}

function messageNode(message) {
  const open = state.open;
  if (message.service) return h('div', { class: 'msg service', id: 'm' + message.id }, message.text);
  const replied = message.reply_to ? open.messages.find((item) => item.id === message.reply_to) : null;
  let timer = null, held = false;
  // Swipe a message to the side (left; right in RTL languages) to reply.
  let startX = 0, startY = 0, shift = 0, swiping = false, scrolling = false;
  const direction = state.rtl ? 1 : -1;
  const node = h('article', { tabindex: 0, 'aria-haspopup': 'dialog', class: 'msg' + (message.out ? ' out' : '') + (state.selection && state.selection.has(message.id) ? ' selected' : ''), id: 'm' + message.id,
    // As on the desktop: a tap selects (in selection mode), a double tap sends the
    // quick reaction, a long press (or right click) opens the message's tools.
    onclick: () => {
      if (held) return;
      if (state.selection) { toggleSelected(message); return; }
      const now = Date.now();
      if (lastTap.id === message.id && now - lastTap.at < 350) { lastTap.id = null; quickReact(message, node); }
      else { lastTap.id = message.id; lastTap.at = now; }
    },
    onkeydown: (event) => messageActionKey(event, () => {
      if (state.selection) toggleSelected(message);
      else messageMenu(message);
    }),
    oncontextmenu: (event) => { event.preventDefault(); if (!state.selection) messageMenu(message); },
    ontouchstart: (event) => {
      held = false; swiping = scrolling = false; shift = 0;
      const point = event.touches[0]; startX = point.clientX; startY = point.clientY;
      if (!state.selection) timer = setTimeout(() => { held = true; if (navigator.vibrate) navigator.vibrate(12); messageMenu(message); }, 500);
    },
    ontouchmove: (event) => {
      const point = event.touches[0], dx = point.clientX - startX, dy = point.clientY - startY;
      if (Math.abs(dx) > 8 || Math.abs(dy) > 8) clearTimeout(timer);
      if (scrolling || state.selection || state.editing) return;
      if (!swiping) {
        if (Math.abs(dy) > 10 && Math.abs(dy) >= Math.abs(dx)) { scrolling = true; return; }
        if (dx * direction > 14) { swiping = true; node.style.transition = 'none'; } else return;
      }
      shift = Math.max(0, Math.min(90, dx * direction));
      node.style.transform = 'translateX(' + (shift * direction) + 'px)';
      node.classList.toggle('swipe-ready', shift > 60);
    },
    ontouchend: () => {
      clearTimeout(timer);
      if (!swiping) return;
      node.style.transition = ''; node.style.transform = ''; node.classList.remove('swipe-ready');
      if (shift > 60) { held = true; startReply(message); setTimeout(() => { held = false; }, 400); }
      swiping = false;
    } },
    h('div', { class: 'head' }, state.selection ? h('span', { class: 'mark' }, state.selection.has(message.id) ? '☑ ' : '☐ ') : null,
      h('span', { class: 'who' }, message.sender), h('time', {class: 'header-clock'}, message.time)),
    message.forwarded ? h('div', { class: 'meta' }, '» ' + t('reenviado')) : null,
    message.reply_to ? h('div', { class: 'reply', role: 'button', onclick: (event) => { event.stopPropagation(); jumpTo(message.reply_to); } },
      replied ? [replied.sender + ': ', richText((replied.text || '').replace(/\s+/g, ' '), replied.custom_emojis || [], false)] : '↩ ' + t('Go to message')) : null,
    message.visual ? mediaNode(message) : null,
    !message.poll && (message.visual ? message.caption : message.text) ? messageText(message) : null,
    fileNode(message),
    message.webpage ? webpageNode(message) : null,
    message.poll ? pollNode(message) : null,
    message.keyboard ? keyboardNode(message) : null,
    message.kind === 'conference' && state.groupCallsAvailable ? h('button', { class: 'comments-button', onclick: (event) => { event.stopPropagation(); if (!state.selection) conferenceInvitation(message); } }, '📞 ' + t('Join call')) : null,
    message.kind === 'article' ? h('button', { class: 'comments-button', onclick: (event) => { event.stopPropagation(); if (!state.selection) articleView(message); } }, '📰 ' + t('Read article')) : null,
    typeof message.comments === 'number' ? h('button', { class: 'comments-button', onclick: (event) => { event.stopPropagation(); if (!state.selection) openComments(message); } },
      '💬 ' + (message.comments ? message.comments + ' ' + t('Comments') : t('Leave a comment'))) : null,
    messageReactions(message, open.peer),
    messageFooter(message));
  return node;
}

function reactionEmoji(value) {
  return /^\d+$/.test(String(value)) ? customEmoji(String(value), '◆', false) : value;
}
function messageReactions(message, peer) {
  if (!message.reactions?.length) return null;
  return h('div', {class: 'reactions'}, message.reactions.map(([value, count, chosen]) =>
    h('button', {class: 'reaction' + (chosen ? ' chosen' : ''), 'aria-pressed': String(!!chosen),
      onclick: (event) => { event.stopPropagation(); react(message, value, peer); }}, reactionEmoji(value), ' ' + count)));
}

// The message's text, or its translation while the chat is being translated.
function messageText(message, open = state.open) {
  const translated = open && open.translate && open.translated && open.translated[message.id];
  const toggle = (label) => h('div', { class: 'meta translation-toggle', dir: document.documentElement.dir, role: 'button',
    onclick: (event) => { event.stopPropagation(); if (open !== state.open || !state.selection) toggleOriginal(message, open); } }, '⇄ ' + label);
  if (translated && translated.text.trim() && !(open.originals && open.originals.has(message.id))) return h('div', { class: 'text translated', dir: 'auto' },
    formatText(translated.text, translated.formats, translated.emojis), toggle(t('Translation') + ' · ' + t('Show original')));
  const original = h('div', { class: 'text', dir: 'auto' }, formatText(message.visual ? message.caption : message.text, message.formats, message.custom_emojis));
  if (translated && translated.text.trim()) original.append(toggle(t('Translation')));
  return original;
}

// translation and Telegram AI (desktop: Message tools, Telegram AI) -------------------
const TRANSLATE_LANGS = [['es', 'Español'], ['en', 'English'], ['ca', 'Català'], ['gl', 'Galego'], ['eu', 'Euskara'], ['pt', 'Português'],
  ['fr', 'Français'], ['de', 'Deutsch'], ['it', 'Italiano'], ['nl', 'Nederlands'], ['pl', 'Polski'], ['ru', 'Русский'], ['uk', 'Українська'],
  ['ro', 'Română'], ['el', 'Ελληνικά'], ['tr', 'Türkçe'], ['ar', 'العربية'], ['he', 'עברית'], ['hi', 'हिन्दी'], ['zh', '中文'],
  ['ja', '日本語'], ['ko', '한국어'], ['vi', 'Tiếng Việt'], ['th', 'ไทย'], ['id', 'Bahasa Indonesia']];
const interfaceLanguage = () => (state.language || 'en').split('-')[0].replace('oc', 'ca').replace('an', 'es');
function chooseLanguage(title, done) {
  const mine = interfaceLanguage();
  const list = [...TRANSLATE_LANGS.filter(([code]) => code === mine), ...TRANSLATE_LANGS.filter(([code]) => code !== mine)];
  sheet(title, list.map(([code, name]) => [name, () => done(code)]));
}
function resultSheet(title, result, apply = null) {
  const layer = document.getElementById('sheet-layer');
  layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
    h('h3', {}, title), h('div', { class: 'result-text' }, formatText(result.text || '', result.formats, result.emojis || [])),
    h('div', { class: 'actions' },
      apply ? button(t('Use in draft'), () => { closeSheet(); apply(result); }, 'primary') : null,
      button(t('Copy'), () => copy(result.text || '')), button(t('Cancelar'), closeSheet))));
  activateSheet(layer); layer.onclick = closeSheet;
}
function translateMessage(message) {
  const open = state.open, revision = state.accountRevision, peer = open.peer;
  const current = () => state.open === open && state.accountRevision === revision && !state.locked;
  chooseLanguage(t('Translation'), (language) => current() && attempt(() => api('translate', { peer, ids: [message.id], language }), (result) => {
    if (!current()) return;
    const value = result[String(message.id)];
    if (value) resultSheet(t('Translation'), value); else toast(t('Sin resultados.'));
  }));
}
function summarizeMessage(message) {
  const open = state.open, revision = state.accountRevision, peer = open.peer;
  toast(t('Cargando...'));
  attempt(() => api('summarize', { peer, id: message.id, language: interfaceLanguage() }), (result) => {
    if (state.open === open && state.accountRevision === revision && !state.locked) resultSheet(t('Summarize with Telegram AI'), result);
  });
}
function transcribeMessage(message) {
  const open = state.open, revision = state.accountRevision, peer = open.peer;
  toast(t('Cargando...'));
  attempt(() => api('transcribe', { peer, id: message.id }), (result) => {
    if (state.open !== open || state.accountRevision !== revision || state.locked) return;
    resultSheet(t('Transcribe audio'), result);
    if (result.pending) toast(t('Transcription pending. Open this action again later.'));
  });
}
// Translate the whole chat (Telegram Premium): every message is shown translated.
function translationViewActive(open) {
  return !state.locked && (state.open === open || state.windows.includes(open));
}
function applyChatTranslation(open, result) {
  if (open.translate !== result.translate || !open.translating) {
    open.translate = result.translate;
    open.translated = {};
    open.translating = new Set();
    open.originals = new Set();
  }
  Object.assign(open.translated, result.translated);
}
function translateChat(open = state.open) {
  if (!open) return;
  const persist = async (language) => {
    if (!translationViewActive(open)) return;
    const result = await attempt(() => api('set_chat_translation', {peer: open.peer, thread_root: open.thread?.root, window_peer: WINDOW_CHAT, language}));
    if (!result || !translationViewActive(open)) return;
    applyChatTranslation(open, result);
    if (open === state.open) drawMessages(false); else drawWindowMessages(open, false);
  };
  if (open.translate) return persist(null);
  chooseLanguage(t('Automatic translation (Premium)'), persist);
}

// One message in its original language (or back to the translation).
function toggleOriginal(message, open) {
  if (!open?.translate) return;
  if (open.originals.has(message.id)) open.originals.delete(message.id); else open.originals.add(message.id);
  if (open === state.open) replaceMessage(message); else drawWindowMessages(open, false);
}
const translationText = (message) => message.visual ? message.caption : message.text;
function translatePending(open = state.open) {
  if (!open?.translate) return;
  clearTimeout(open.translateTimer);
  open.translateTimer = setTimeout(async () => {
    if (!translationViewActive(open) || !open.translate) return;
    const translating = open.translating;
    if (translating.size) return;
    const messages = open.messages.filter((m) => !m.service && translationText(m) && !(m.id in open.translated)).slice(-60);
    if (!messages.length) return;
    const ids = messages.map((m) => m.id);
    ids.forEach((id) => translating.add(id));
    const language = open.translate;
    const current = () => translationViewActive(open) && open.translating === translating;
    try {
      const result = await api('translate', {peer: open.peer, thread_root: open.thread?.root, window_peer: WINDOW_CHAT, ids, language, chat: true});
      if (!current()) return;
      for (const before of messages) {
        const message = open.messages.find((item) => item.id === before.id);
        if (message && translationText(message) === translationText(before)) {
          open.translated[message.id] = result[String(message.id)] || {text: '', emojis: []};
          if (open === state.open) replaceMessage(message);
        }
      }
      if (open === state.open) translatePending(open); else drawWindowMessages(open, false);
    } catch (error) {
      if (current()) toast(error.message, 'error');
    } finally {
      translating.clear();
    }
  }, 300);
}
// Telegram AI on the text being written: proofread, add emoji, translate.
function composeAI() {
  const field = document.getElementById('field');
  if (!state.open || !field || !field.value.trim()) { toast(t('Escribe un mensaje')); return; }
  const open = state.open, revision = state.accountRevision, original = field.value;
  const current = () => state.open === open && state.accountRevision === revision && !state.locked && field.isConnected;
  const key = composerPeer();
  const emojis = (state.customEmoji[key] || []).filter(([, alt]) => original.includes(alt));
  const run = (mode, language = interfaceLanguage()) => current() && attempt(() => api('compose_ai', { text: original, mode, language, emojis }), (result) => {
    if (!current()) return;
    resultSheet(t('Telegram AI'), result, (value) => {
      if (!current()) return;
      if (field.value !== original) { toast(t('Draft changed. The result was not applied.')); return; }
      field.value = value.text; state.customEmoji[key] = value.emojis.map(([id, alt]) => [id, alt]);
      field.dispatchEvent(new Event('input')); field.focus();
    });
  });
  sheet(t('Telegram AI'), [
    [t('Proofread'), () => run('proofread')],
    [t('Add emojis'), () => run('emojify')],
    [t('Translation'), () => chooseLanguage(t('Translation'), (language) => run('translate', language))],
  ]);
}

// channel comments (desktop: the post's discussion thread) ------------------------------
function openComments(post) {
  const {peer, chat} = state.open;
  return loadComments(peer, post.id, chat);
}

async function loadComments(source, post, channel, openThread = true) {
  const account = state.account;
  const request = state.openRequest = (state.openRequest || 0) + 1;
  const current = () => account === state.account && request === state.openRequest && !state.locked && !unavailableWindow();
  if (!(await saveDraft()) || !current()) return;
  let data;
  try { data = await api('comments', {peer: source, id: post, window_peer: WINDOW_CHAT}); }
  catch (error) { if (current()) toast(error.message, 'error'); return; }
  if (!data || !current()) return;
  const previous = state.open;
  const thread = {source, post, channel, root: data.root_id, cursor: data.next};
  const open = {peer: data.peer, chat: channel, thread,
    messages: [data.root, ...data.messages].filter(Boolean),
    outbox: data.outbox,
    loadingOlder: false, done: !data.more, status: '', typing: '',
    translate: data.translate || null, translated: data.translated || {}, translating: new Set(), originals: new Set()};
  if (openThread && previous && !previous.thread) history.pushState({view: 'chat', discussion: true}, '');
  state.open = open;
  state.reply = state.editing = state.selection = null;
  const peer = composerPeer(open);
  if (!draftWrites.has(draftKey(peer)) && !failedDraftWrites.has(draftKey(peer))) state.drafts[peer] = data.draft;
  render();
}

const CALL_STATUS = {
  incoming: 'Incoming call', preparing: 'Calling…', ringing: 'Ringing…',
  connecting: 'Connecting…', active: 'Connected',
};
let frameTimer = null;

async function refreshCallState() {
  const account = state.account;
  try {
    const result = await api('call_state');
    if (account !== state.account) return;
    state.callsAvailable = result.available;
    receiveCall(result.call);
    const group = await api('group_call_state');
    if (account !== state.account) return;
    state.groupCallsAvailable = group.available;
    receiveGroupCall(group.call);
  } catch (error) {}
}

function receiveCall(snapshot) {
  if (snapshot?.state === 'incoming') document.querySelector('.media-viewer[open]')?.close();
  const was = state.nativeCall;
  state.nativeCall = snapshot && snapshot.token && !['idle', 'ended'].includes(snapshot.state) ? snapshot : null;
  if (was && !state.nativeCall && snapshot?.error) toast(snapshot.error, 'error');
  drawNativeCall();
}

async function nativeCallAction(action, params = {}) {
  const account = state.account;
  const call = state.nativeCall;
  const result = await attempt(() => api('call_action', {action, token: call?.token, ...params}));
  if (result && account === state.account && state.nativeCall === call) receiveCall(result);
}

function callPipButton(call, group = false) {
  return button(t('Picture in Picture'), async () => {
    const opened = await attempt(() => api('call_pip', {token: call.token, group}));
    if (opened === false) toast(t('Picture in Picture is unavailable.'), 'error');
  });
}

function drawNativeCall() {
  const layer = document.getElementById('call-layer');
  if (!layer) return;
  clearTimeout(frameTimer);
  const call = state.nativeCall;
  layer.hidden = state.locked || state.stage !== 'ready' || !call;
  if (layer.hidden) {
    layer.replaceChildren();
    return;
  }
  const peer = state.chats.find(item => item.id === call.peer);
  const name = peer?.name || String(call.peer);
  const remote = h('img', {class: 'call-remote', alt: '', hidden: true});
  const local = h('img', {class: 'call-local', alt: '', hidden: true});
  const active = call.state === 'active';
  const actions = call.state === 'incoming'
    ? [button(t('Answer'), () => nativeCallAction('accept'), 'primary'),
       call.video ? button(t('Answer with video'), () => nativeCallAction('accept', {video: true})) : null,
       button(t('Decline'), () => nativeCallAction('end'), 'danger')]
    : [active && call.can_pip && (call.video || call.remote_video || call.screen) ? callPipButton(call) : null,
       active ? button(t(call.muted ? 'Unmute microphone' : 'Mute microphone'), () => nativeCallAction('mute', {value: !call.muted})) : null,
       active && !call.screen ? button(t(call.video ? 'Stop camera' : 'Start camera'), () => nativeCallAction('camera', {value: !call.video})) : null,
       active && call.can_share_screen ? button(t(call.screen ? 'Stop sharing screen' : 'Share screen'),
         () => nativeCallAction('screen', {value: !call.screen})) : null,
       button(t('Hang up'), () => nativeCallAction('end'), 'danger')];
  layer.replaceChildren(h('section', {class: 'sheet call-sheet', 'aria-label': t('Call')},
    h('h3', {}, name), h('div', {class: 'muted'}, t(CALL_STATUS[call.state] || 'Call')),
    call.emojis ? h('div', {class: 'call-fingerprint'}, call.emojis) : null,
    remote, local, h('div', {class: 'line'}, ...actions.filter(Boolean))));
  if (!active || !(call.remote_video || call.video)) return;

  const readFrames = async () => {
    try {
      const frames = await api('call_frames', {token: call.token});
      if (state.nativeCall !== call || state.locked || !local.isConnected) return;
      for (const [image, frame] of [[remote, frames.remote], [local, frames.local]]) {
        if (frame) {
          image.src = 'data:image/jpeg;base64,' + frame;
          image.hidden = false;
        }
      }
    } catch (error) {}
    if (state.nativeCall === call && !state.locked && local.isConnected) frameTimer = setTimeout(readFrames, 160);
  };
  readFrames();
}

// group voice/video chats and conferences (desktop: calls_group) ---------------------------
let groupTimer = null;
let groupFrameTimer = null;

function receiveGroupCall(snapshot) {
  const was = state.groupCall;
  state.groupCall = snapshot && snapshot.token && !['idle', 'ended'].includes(snapshot.state) ? snapshot : null;
  if (was && !state.groupCall && snapshot?.error) toast(snapshot.error, 'error');
  if (!state.groupCall || state.groupCall.token !== was?.token) state.groupDetails = null;
  drawGroupCall();
}

async function groupCallAction(action, params = {}) {
  const account = state.account;
  const call = state.groupCall;
  if (['join', 'create', 'conference', 'invitation'].includes(action)) {
    state.groupCall = {state: 'preparing', token: '', peer: params.peer, name: ''};
    drawGroupCall();
  }
  const result = await attempt(() => api('group_call_action', {action, token: call?.token, ...params}));
  if (account !== state.account) return;
  if (result) receiveGroupCall(result);
  else if (!state.groupCall?.token) { state.groupCall = null; drawGroupCall(); }
  return result;
}

// The group or channel's voice/video chat: join it, or start one as an administrator.
async function groupCallSheet(chat) {
  const account = state.account;
  if (state.groupCall?.token && state.groupCall.peer === chat.id) { drawGroupCall(); return; }
  const info = await attempt(() => api('group_call_info', {peer: chat.id}));
  if (!info || account !== state.account) return;
  const items = [];
  const manage = (action, value) => attempt(() => api('group_call_manage', {peer: chat.id, call_id: info.call_id, action, value}), () => toast(t('Saved.')));
  if (info.active && info.scheduled) {
    if (info.admin) {
      items.push([t('Start now'), () => manage('start')]);
      items.push([t('Cancelar'), () => manage('cancel'), 'danger']);
    } else items.push([t(info.subscribed ? 'Disable reminder' : 'Remind me'), () => manage('subscribe', !info.subscribed)]);
  } else if (info.active && !info.rtmp) {
    items.push([t('Join call'), () => groupCallAction('join', {peer: chat.id})]);
    items.push([t('Video call'), () => groupCallAction('join', {peer: chat.id, video: true})]);
  } else if (!info.active && info.admin) {
    items.push([t('Start now'), () => groupCallAction('create', {peer: chat.id})]);
  }
  if (info.active && info.admin && !info.scheduled)
    items.push([t('End call for everyone'), () => confirmThen(t('End call for everyone') + '?', () => manage('end')), 'danger']);
  const lines = [info.title || chat.name];
  if (info.active) lines.push(t('Participants') + ': ' + (info.participants_count || 0));
  else if (!info.admin) lines.push(t('No active call'));
  if (info.scheduled) lines.push(new Date(info.scheduled * 1000).toLocaleString());
  sheet(lines.join(' · '), items);
}

function drawGroupCall() {
  const layer = document.getElementById('group-call-layer');
  if (!layer) return;
  clearTimeout(groupTimer); clearTimeout(groupFrameTimer);
  const call = state.groupCall;
  layer.hidden = state.locked || state.stage !== 'ready' || !call || state.groupMinimised;
  const pill = document.getElementById('group-call-pill');
  if (pill) {
    pill.hidden = state.locked || state.stage !== 'ready' || !call?.token || !state.groupMinimised;
    pill.replaceChildren(call?.token ? h('button', {class: 'btn primary', onclick: () => { state.groupMinimised = false; drawGroupCall(); }},
      '◉ ' + (call.name || t('Group call'))) : '');
  }
  if (layer.hidden) { layer.replaceChildren(); return; }
  const active = call.state === 'active';
  const details = state.groupDetails;
  const control = details?.control || {};
  const remote = h('img', {class: 'call-remote', alt: '', hidden: true});
  const local = h('img', {class: 'call-local', alt: '', hidden: true});
  const previousGrid = layer.querySelector('.call-video-grid');
  const grid = previousGrid?.dataset.token === call.token
    ? previousGrid : h('div', {class: 'call-video-grid', hidden: true});
  grid.dataset.token = call.token;
  const mine = details?.items?.find(item => item.is_self);
  const actions = active ? [
    call.can_pip && (call.video || call.remote_video || call.screen || details?.items?.some(item => item.video || item.screen)) ? callPipButton(call, true) : null,
    call.view_only ? null : button(t(call.muted ? 'Unmute microphone' : 'Mute microphone'), () => groupCallAction('mute', {value: !call.muted}), call.muted ? '' : 'primary'),
    call.view_only || call.screen ? null : button(t(call.video ? 'Stop camera' : 'Start camera'), () => groupCallAction('camera', {value: !call.video})),
    !call.view_only && call.can_share_screen ? button(t(call.screen ? 'Stop sharing screen' : 'Share screen'),
      () => groupCallAction('screen', {value: !call.screen})) : null,
    !call.conference && !call.view_only && mine ? button(t(mine.raised_hand ? 'Lower hand' : 'Raise hand'), () =>
      groupCallAction('raise_hand', {value: !mine.raised_hand}).then(refreshGroupDetails)) : null,
    call.conference || call.can_manage ? button(t('Add members'), () => inviteToGroupCall(call)) : null,
    button(t('Minimize'), () => { state.groupMinimised = true; drawGroupCall(); }),
    button(t('Hang up'), () => groupCallAction('leave'), 'danger'),
    call.can_manage && !call.conference ? button(t('End call for everyone'), () => confirmThen(t('End call for everyone') + '?',
      () => groupCallAction('end_all'))) : null,
  ] : [button(t('Cancelar'), () => call.token ? groupCallAction('leave') : null, 'danger')];
  const people = (details?.items || []).map(person => h('div', {class: 'call-person', onclick: () => groupParticipantMenu(call, person)},
    avatar(person.id, person.name),
    h('span', {class: 'grow'}, (person.name || String(person.id)) + (person.is_self ? ' · ' + t('You') : '')),
    h('span', {class: 'muted'}, [person.invitation ? t('Invited') : '', person.raised_hand ? '✋' : '',
      person.video ? '▣' : '', person.screen ? '▭' : '', person.muted ? '🔇' : '🎙'].filter(Boolean).join(' '))));
  layer.replaceChildren(h('section', {class: 'sheet call-sheet group-call-sheet', 'aria-label': t('Group call')},
    h('h3', {}, control.title || call.name || t(call.conference ? 'Conference call' : 'Group call')),
    h('div', {class: 'muted'}, t(CALL_STATUS[call.state] || 'Group call') +
      (details ? ' · ' + t('Participants') + ': ' + (details.items || []).filter(item => !item.invitation).length : '')),
    control.recording ? h('div', {class: 'muted'}, '● ' + t('Record call')) : null,
    remote, grid, local,
    h('div', {class: 'call-people'}, ...people),
    h('div', {class: 'line'}, ...actions.filter(Boolean))));
  if (!active) return;
  if (!details) refreshGroupDetails();
  else groupTimer = setTimeout(refreshGroupDetails, 4000);
  const readFrames = async () => {
    try {
      const frames = await api('group_call_frames', {token: call.token});
      if (state.groupCall !== call || state.locked || !local.isConnected) return;
      if (frames.tiles) {
        const activeIds = new Set(frames.tiles);
        const images = new Map();
        for (const image of [...grid.children]) {
          if (!activeIds.has(image.dataset.ssrc)) image.remove();
          else images.set(image.dataset.ssrc, image);
        }
        for (const [ssrc, frame] of Object.entries(frames.cameras || {})) {
          if (!activeIds.has(ssrc)) continue;
          const image = images.get(ssrc) || h('img', {alt: ''});
          image.dataset.ssrc = ssrc;
          image.src = 'data:image/jpeg;base64,' + frame;
          if (!images.has(ssrc)) grid.append(image);
        }
        grid.hidden = !grid.childElementCount;
      }
      for (const [image, frame] of [[remote, frames.remote], [local, frames.local]]) {
        if (frame) { image.src = 'data:image/jpeg;base64,' + frame; image.hidden = false; }
      }
    } catch (error) {}
    if (state.groupCall === call && !state.locked && local.isConnected) groupFrameTimer = setTimeout(readFrames, 200);
  };
  if (call.video || call.remote_video || details?.items?.some(item => item.video || item.screen)) readFrames();
}

async function refreshGroupDetails() {
  const call = state.groupCall;
  if (!call?.token || call.state !== 'active') return;
  try {
    const details = await api('group_call_details', {token: call.token});
    if (state.groupCall?.token !== call.token) return;
    state.groupDetails = details;
  } catch (error) {}
  if (state.groupCall?.token === call.token) drawGroupCall();
}

function groupParticipantMenu(call, person) {
  const items = [];
  if (person.video) items.push([t('Show'), () => groupCallAction('view', {user: person.id})]);
  if (person.screen) items.push([t('View screen'), () => groupCallAction('view', {user: person.id, value: true})]);
  if (person.can_set_volume && !person.is_self && !person.invitation) {
    items.push([t('Volume (%)'), () => {
      const input = h('input', {type: 'number', min: 0, max: 200, step: 1, inputmode: 'numeric', required: true,
        value: Math.max(0, Math.min(200, person.volume ?? 100))});
      formSheet(person.name || String(person.id), [labelled(t('Volume (%)'), input)], t('Save'), async () => {
        if (!input.reportValidity() || state.groupCall?.token !== call.token) return false;
        const saved = await groupCallAction('participant_volume',
          {token: call.token, user: person.id, value: input.valueAsNumber});
        if (!saved) return false;
        refreshGroupDetails();
        return true;
      });
    }]);
  }
  if (call.can_manage && !person.is_self && !person.invitation)
    items.push([t(person.muted ? 'Unmute microphone' : 'Mute microphone'), () => groupCallAction('mute_participant', {user: person.id, value: !person.muted}).then(refreshGroupDetails)]);
  if (call.can_manage && person.raised_hand && !person.is_self)
    items.push([t('Lower hand'), () => groupCallAction('mute_participant', {user: person.id, value: false}).then(refreshGroupDetails)]);
  if (person.invitation) items.push([t('Send invitation again'), () => groupCallAction('invite', {user: person.id})]);
  items.push([t('Profile'), () => openProfile({id: person.id, name: person.name, kind: 'user'})]);
  sheet(person.name || String(person.id), items);
}

// A conference call invitation in a private chat (desktop: desktop_conference).
async function conferenceInvitation(message, peer = state.open?.peer) {
  const account = state.account;
  const info = await attempt(() => api('conference_invitation', {peer, message: message.id}));
  if (!info || account !== state.account) return;
  if (!info.joinable) {
    sheet(info.state === 'missed' ? t('Perdida') : t('This invitation is no longer available.'), []);
    return;
  }
  sheet(info.title + ' · ' + t('Participants') + ': ' + info.count + (info.participants.length ? ' (' + info.participants.join(', ') + ')' : ''), [
    [t('Join call'), () => groupCallAction('invitation', {peer, message: message.id})],
    [t('Video call'), () => groupCallAction('invitation', {peer, message: message.id, video: true})],
  ]);
}

async function inviteToGroupCall(call) {
  const account = state.account;
  const contacts = await attempt(() => api('contacts'));
  if (!contacts || account !== state.account) return;
  const search = h('input', {type: 'search', 'aria-label': t('Search contacts'), placeholder: t('Search contacts')});
  const list = h('div', {});
  const draw = () => {
    const query = search.value.trim().toLowerCase();
    list.replaceChildren(...contacts.filter(person => (person.name + ' ' + (person.username || '')).toLowerCase().includes(query))
      .slice(0, 100).map(person => h('button', {class: 'item', onclick: async () => {
        closeSheet();
        if (await groupCallAction('invite', {user: person.id})) { toast(t('Invited') + ': ' + person.name); refreshGroupDetails(); }
      }}, person.name)));
  };
  search.addEventListener('input', draw);
  draw();
  formSheet(t('Add members'), [search, list], t('Cancelar'), () => true);
}

// call history (desktop: Calls) -----------------------------------------------------------
async function callsView(missed = false) {
  const layer = document.getElementById('sheet-layer');
  const account = state.account;
  const list = h('div', { class: 'scroll calls' }, h('div', { class: 'empty spinner' }, t('Cargando...')));
  const status = h('div', { class: 'muted small', role: 'status' });
  let next = null, items = [], loading = false;
  const more = button(t('More'), () => load(true)); more.hidden = true;
  const when = (seconds) => seconds ? new Date(seconds * 1000).toLocaleString(state.language || undefined, { dateStyle: 'short', timeStyle: 'short' }) : '';
  const draw = () => list.replaceChildren(...(items.length ? items.map((call) => h('div', { class: 'row', role: 'button',
      onclick: () => {
        closeSheet();
        if (call.conference && state.groupCallsAvailable && feature('calls')) conferenceInvitation(call, call.peer);
        else openChat(call.peer, true, { id: call.peer, name: call.name });
      } },
    avatar(call.peer, call.name),
    h('div', { class: 'body' },
      h('div', { class: 'top' }, h('span', { class: 'name' + (call.missed ? ' missed' : '') }, call.name), h('span', { class: 'when' }, when(call.date))),
      h('div', { class: 'bottom' }, h('span', { class: 'preview' }, [
        call.outgoing ? t('Outgoing call') : t('Incoming call'),
        call.conference ? t('Conference call') : call.video ? t('Video call') : t('Call'),
        call.outcome_label || (call.missed ? t('Missed') : ''),
        call.duration ? clockTime(call.duration) : '',
      ].filter(Boolean).join(' · ')))))) : [h('div', { class: 'empty' }, t('Sin resultados.'))]));
  const load = async (page = false) => {
    if (loading || (page && more.hidden)) return;
    loading = more.disabled = true;
    status.textContent = '';
    try {
      const result = await api('calls', { offset: page ? next : null, missed });
      if (!list.isConnected || account !== state.account) return;
      const unique = new Map((page ? items : []).map((call) => [call.peer + ':' + call.id, call]));
      for (const call of result.items) unique.set(call.peer + ':' + call.id, call);
      items = [...unique.values()];
      next = result.next;
      more.hidden = !result.more;
      draw();
    } catch (error) {
      if (!list.isConnected || account !== state.account) return;
      if (!page) list.replaceChildren();
      status.textContent = error.message;
    } finally {
      loading = more.disabled = false;
    }
  };
  layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Calls')),
    h('div', { class: 'tabs' }, h('button', { class: 'tab' + (missed ? '' : ' on'), onclick: () => callsView(false) }, t('All')),
      h('button', { class: 'tab' + (missed ? ' on' : ''), onclick: () => callsView(true) }, t('Missed'))),
    list, status, more, h('button', { class: 'item', onclick: closeSheet }, t('Cancelar'))));
  activateSheet(layer); layer.onclick = closeSheet;
  load();
}

// articles (Telegram rich messages: Markdown or HTML) and checklists ---------------------
function articleSheet() {
  const destination = sendDestination();
  const source = h('textarea', { rows: 10, placeholder: '# ' + t('Title') + '\n\n' + t('Text') + ' **' + t('Bold') + '** _' + t('Italic') + '_\n\n![](https://…)' });
  const format = h('select', {}, h('option', { value: 'markdown' }, 'Markdown'), h('option', { value: 'html' }, 'HTML'));
  const [rtlRow, rtl] = check(t('Right to left'));
  const [linksRow, noLinks] = check(t('Do not turn addresses into links'));
  formSheet(t('Article'), [source, labelled(t('Format'), format), rtlRow, linksRow], t('Enviar'), async () => {
    if (!source.value.trim()) return false;
    const ok = await attempt(() => api('send_article', { ...destination, source: source.value, format: format.value, rtl: rtl.checked, noautolink: noLinks.checked }));
    return ok ? undefined : false;
  });
}
function checklistSheet() {
  const destination = sendDestination();
  const title = h('input', { type: 'text', maxlength: 255 });
  const items = h('textarea', { rows: 6, placeholder: t('One task per line') });
  formSheet(t('Checklist'), [labelled(t('Title'), title), labelled(t('Tasks'), items)], t('Enviar'), async () => {
    const list = items.value.split('\n').map((line) => line.trim()).filter(Boolean);
    if (!title.value.trim() || !list.length) return false;
    const ok = await attempt(() => api('send_checklist', { ...destination, title: title.value, items: list }));
    return ok ? undefined : false;
  });
}
// Next lies to the left in a right-to-left gallery. A swipe moves the content
// in the opposite direction to the arrow that selects the same item.
const galleryStep = (towardRight) => towardRight !== Boolean(state.rtl) ? 1 : -1;

// An article on its own page, with its photos as a carousel.
async function articleView(message) {
  const revision = state.accountRevision;
  const peer = state.open.peer;
  const data = await attempt(() => api('article', { peer, id: message.id }));
  if (!data || revision !== state.accountRevision) return;
  const layer = document.getElementById('sheet-layer');
  let index = 0;
  const photoUrl = (i) => mediaUrl(peer, message.id, false) + '&photo=' + i;
  const carousel = data.photos ? h('div', { class: 'carousel' }) : null;
  const drawCarousel = () => {
    if (!carousel) return;
    const previousFocus = carousel.querySelector('button:focus')?.getAttribute('aria-label');
    let startX = null;
    carousel.replaceChildren(
      state.settings?.photo_previews === false ? button(t('Foto'), () => imageViewer(photoUrl(index), t('Article'))) :
      h('img', { src: photoUrl(index), alt: t('Foto'), role: 'button', onclick: () => imageViewer(photoUrl(index), t('Article')),
        ontouchstart: (event) => { startX = event.touches[0].clientX; },
        ontouchend: (event) => { if (startX === null) return; const dx = event.changedTouches[0].clientX - startX; startX = null;
          if (Math.abs(dx) > 40) { index = Math.max(0, Math.min(data.photos - 1, index + galleryStep(dx < 0))); drawCarousel(); } } }),
      h('div', { class: 'carousel-nav' }, symbolButton('‹', t('Previous page'), () => { index--; drawCarousel(); }, index === 0),
        h('bdi', { class: 'muted', dir: 'ltr' }, (index + 1) + '/' + data.photos),
        symbolButton('›', t('Next page'), () => { index++; drawCarousel(); }, index === data.photos - 1)));
    if (previousFocus) {
      const buttons = [...carousel.querySelectorAll('button:not(:disabled)')];
      (buttons.find(node => node.getAttribute('aria-label') === previousFocus) || buttons[0])?.focus();
    }
  };
  drawCarousel();
  layer.replaceChildren(h('div', { class: 'sheet tall article', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Article')), carousel, h('div', { class: 'result-text' }, linkify(data.text)),
    h('div', { class: 'actions' }, button(t('Copy'), () => copy(data.text)), button(t('Cancelar'), closeSheet))));
  activateSheet(layer); layer.onclick = closeSheet;
}

// polls and bot buttons ---------------------------------------------------------------
function pollNode(message) {
  const poll = message.poll;
  const box = h('div', { class: 'poll', onclick: (event) => event.stopPropagation() },
    h('div', { class: 'question' }, (poll.quiz ? '? ' : '≡ ') + poll.question));
  const open = state.open;
  const destination = {peer: open.peer, id: message.id, account: state.account};
  const attachment = (kind, part) => {
    const url = mediaUrl(open.peer, message.id, kind !== 'video') + '&poll=' + part;
    if (kind === 'photo' && state.settings?.photo_previews === false)
      return button(t('Foto'), () => imageViewer(url, t('Foto')));
    if (kind === 'photo') return h('img', {class: 'poll-attachment', src: url, alt: t('Attachment'), loading: 'lazy'});
    if (kind === 'video') return h('video', {class: 'poll-attachment', src: url, controls: true, playsinline: true, preload: 'none'});
    return null;
  };
  const attached = attachment(poll.attached_media, 'attached');
  if (attached) box.append(attached);
  const votedOrClosed = poll.voted || poll.closed;
  const showResults = poll.closed || (poll.voted && !poll.hidden_results);
  const picked = new Set();
  const answers = [...poll.answers];
  if (poll.shuffle) {
    open.pollOrder ||= new Map();
    if (!open.pollOrder.has(message.id)) open.pollOrder.set(message.id, new Map());
    const order = open.pollOrder.get(message.id);
    for (const {option} of answers) if (!order.has(option)) order.set(option, Math.random());
    answers.sort((a, b) => order.get(a.option) - order.get(b.option));
  }
  for (const answer of answers) {
    const share = poll.total ? Math.round(answer.voters * 100 / poll.total) : 0;
    const row = h('button', { class: 'answer' + (answer.chosen ? ' chosen' : '') + (answer.correct ? ' correct' : ''),
      disabled: votedOrClosed || null, onclick: () => {
        if (poll.multiple) { if (picked.has(answer.option)) picked.delete(answer.option); else picked.add(answer.option); row.classList.toggle('picked'); }
        else vote([answer.option]);
      } },
      h('span', { class: 'label' }, (answer.chosen ? '[x] ' : '[ ] ') + answer.text),
      showResults ? h('span', { class: 'share' }, share + '%') : null,
      showResults ? h('span', { class: 'fill', style: 'width:' + share + '%' }) : null);
    box.append(row);
  }
  const apply = (result) => {
    if (result.message && state.open === open) EVENTS.edit({peer: open.peer, message: result.message});
    queuedNote(result);
  };
  const vote = (options) => attempt(() => api('vote', {...destination, options}), apply);
  box.append(h('div', { class: 'meta' }, t(poll.quiz ? 'Quiz' : 'Poll') +
    (poll.hidden_results && !poll.closed ? '' : ' · ' + poll.total)));
  if (!votedOrClosed && poll.multiple) {
    const selectAnswers = checked => {
      picked.clear();
      if (checked) answers.forEach(answer => picked.add(answer.option));
      box.querySelectorAll('button.answer').forEach(row => row.classList.toggle('picked', checked));
    };
    box.append(bulkButtons(() => selectAnswers(true), () => selectAnswers(false)),
      button(t('Vote'), () => picked.size && vote([...picked]), 'primary'));
  }
  if (poll.voted && !poll.closed && poll.revoting) box.append(button(t('Retract vote'), () => vote([])));
  if (votedOrClosed || poll.creator) {
    if (poll.solution) box.append(h('div', {class: 'text'}, poll.solution));
    const solution = attachment(poll.solution_media, 'solution');
    if (solution) box.append(solution);
  }
  if (!poll.closed && poll.open_answers) box.append(button(t('Add answer'), () => {
    const input = h('input', {type: 'text', maxlength: 100});
    formSheet(t('Add answer'), [labelled(t('Answer'), input)], t('Add answer'), async () => {
      if (state.open !== open) return false;
      return !!(await attempt(() => api('poll_answer', {...destination, answer: input.value}), apply));
    });
  }));
  if (!poll.closed && (message.out || poll.creator)) box.append(button(t('Close poll'), () =>
    confirmThen(t('Close poll') + '?', () => {
      if (state.open === open) attempt(() => api('poll_close', destination), apply);
    })));
  return box;
}

function keyboardNode(message) {
  const box = h('div', { class: 'keyboard', onclick: (event) => event.stopPropagation() });
  for (const row of message.keyboard) box.append(h('div', { class: 'krow' }, row.map((key) =>
    h('button', { class: 'key', disabled: key.supported ? null : true, onclick: () => pressButton(message, key) }, key.text))));
  return box;
}

async function pressButton(message, key) {
  const open = state.open, revision = state.accountRevision;
  const answer = await attempt(() => api('bot_button', { peer: open.peer, id: message.id, row: key.row, column: key.column, signature: key.signature }));
  if (!answer || state.open !== open || revision !== state.accountRevision || state.locked) return;
  if (answer.notice) { if (answer.alert) alert(answer.notice); else toast(answer.notice); }
  if (answer.copy) copy(answer.copy);
  if (answer.url) openUrl(answer.url);
  if (answer.profile) openProfile({ id: answer.profile, name: '' });
}

// links and files ------------------------------------------------------------------
const LINK = /\b(?:https?:\/\/|t\.me\/|www\.)[^\s<>"]+[^\s<>".,;:!?)\]'»]|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?<![\w@])@[A-Za-z][\w]{3,31}\b|(?<![\w#&])#[\p{L}\p{N}_]{1,64}/giu;
// Text with Telegram's custom emoji drawn as images (each one replaces its fallback emoji, in order).
// Text with its formatting (bold, italic, underline, strikethrough, spoiler, code,
// links, quotes) and custom emoji, as Telegram shows it.
const FORMAT_TAGS = { bold: 'b', italic: 'i', underline: 'u', strike: 's', code: 'code' };
function formatText(text, formats, emojis, open = true) {
  if (!formats || !formats.length || (state.settings && state.settings.ascii_text)) return richText(text, emojis, open);
  const placed = [];
  let from = 0;
  for (const [id, alt] of emojis || []) {
    const at = text.indexOf(alt, from);
    if (at < 0) continue;
    placed.push([at, at + alt.length, id, alt]); from = at + alt.length;
  }
  const cuts = new Set([0, text.length]);
  for (const [a, b] of formats) { cuts.add(Math.max(0, Math.min(text.length, a))); cuts.add(Math.max(0, Math.min(text.length, b))); }
  for (const [a, b] of placed) { cuts.add(a); cuts.add(b); }
  const points = [...cuts].sort((x, y) => x - y);
  const parts = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    if (a >= b) continue;
    const emoji = placed.find(([x, y]) => x <= a && y >= b);
    const link = open && feature('links') && formats.find(([x, y, style]) => style === 'link' && x <= a && y >= b);
    let node = emoji ? (emoji[0] === a ? customEmoji(emoji[2], emoji[3], open && !link) : null)
      : h('span', {}, ...(open && !link ? linkify(text.slice(a, b)) : [text.slice(a, b)]));
    if (!node) continue;
    for (const [x, y, style, argument] of formats) {
      if (x > a || y < b) continue;
      if (FORMAT_TAGS[style]) node = h(FORMAT_TAGS[style], {}, node);
      else if (style === 'spoiler') node = h('span', { class: 'spoiler', onclick: (event) => { if (!event.currentTarget.classList.contains('shown')) { event.stopPropagation(); event.currentTarget.classList.add('shown'); } } }, node);
      else if (style === 'quote' || style === 'collapsed_quote') node = h('span', { class: 'quote' + (style === 'collapsed_quote' ? ' collapsed' : ''),
        onclick: style === 'collapsed_quote' ? (event) => { event.stopPropagation(); event.currentTarget.classList.toggle('collapsed'); } : null }, node);
    }
    const url = link && messageBrowserUrl(link[3]);
    parts.push(url ? messageLink(url, node) : node);
  }
  return parts;
}

// Text with its custom emoji as pictures. open=false: no links and no pack on tap
// (chat list, reply quotes, reactions), so the tap goes to the row itself.
function richText(text, emojis, open = true) {
  const plain = open ? linkify : (value) => [value];
  if (!emojis || !emojis.length || (state.settings && state.settings.ascii_text)) return plain(text);
  const parts = [];
  let from = 0;
  for (const [id, alt] of emojis) {
    const at = text.indexOf(alt, from);
    if (at < 0) continue;
    if (at > from) parts.push(...plain(text.slice(from, at)));
    parts.push(customEmoji(id, alt, open));
    from = at + alt.length;
  }
  if (from < text.length) parts.push(...plain(text.slice(from)));
  return parts;
}
function stickerUrl(id) { return '/sticker?' + resourceAuth() + '&id=' + id; }
// Keep the button in place when the image is replaced by an animation or a fallback.
function emojiStatusBadge(status) {
  if (!status) return null;
  const label = t('Emoji status') + ' · ' + t('View pack');
  return h('button', {type: 'button', class: 'emoji-status', title: label, 'aria-label': label,
    onclick: (event) => {
      event.stopPropagation();
      if (!state.selection) packView({id: status}, true);
    }}, customEmoji(status, '★', false));
}
function peerControl({ onclick, ...attrs }, ...children) {
  const node = h('div', { ...attrs, role: 'group' }, ...children);
  node.querySelector('.peer-open').addEventListener('click', onclick);
  return node;
}
function nameWithStatus(name, status, action = false, pressed = null) {
  if (!status && !action) return h('span', { class: 'name', dir: 'auto' }, name);
  // A primary action and an emoji pack need sibling controls in WebKit's accessibility tree.
  const label = action ? h('button', { type: 'button', class: 'label peer-open', dir: 'auto',
    'aria-pressed': pressed == null ? null : String(pressed) }, name) : h('bdi', { class: 'label' }, name);
  return h('span', { class: 'name with-status' }, label, status ? emojiStatusBadge(status) : null);
}

function customEmoji(id, alt, open = true) {
  const img = lazySrc(h('img', { class: 'custom-emoji', alt, title: alt, decoding: 'async',
    onerror: () => img.replaceWith(document.createTextNode(alt)) }), stickerUrl(id));
  animated(img, id);
  if (!open) return img;
  // The animation and its fallback may replace the image while the control has focus.
  return h('button', { type: 'button', class: 'inline-emoji-pack',
    'aria-label': [alt, t('View pack')].filter(Boolean).join(' · '),
    onclick: event => {
      if (state.selection) return;
      event.stopPropagation();
      packView({id}, true);
    } }, img);
}

// Animated stickers and custom emoji (Lottie from TGS, or WebM): the still picture
// first, the animation once it is on screen; paused again when it scrolls away.
const ANIMATION_DATA = new Map();   // id -> Promise of {kind, data|url} (null: still picture)
const PLAYING = new WeakMap();      // element -> {play, pause}
const WEBKIT = PLATFORM === 'iOS' || MAC;
let alphaDecodeQueue = Promise.resolve();
const animationObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const player = PLAYING.get(entry.target);
    if (player) { if (entry.isIntersecting && animationEnabled()) player.play(); else player.pause(); continue; }
    if (entry.isIntersecting) startAnimation(entry.target);
  }
}, { rootMargin: '80px' }) : null;
function animationEnabled() {
  const settings = state.settings || {};
  return settings.animated_emoji !== false && !settings.reduce_animations;
}
// The Lottie player (about 150 KB of script) loads the first time an animated
// sticker or emoji is shown, not with the app.
let lottieLoading = null;
function ensureLottie() {
  if (window.lottie) return Promise.resolve(window.lottie);
  lottieLoading ||= new Promise((resolve) => {
    const script = h('script', { src: 'vendor/lottie_light.min.js' });
    script.onload = () => resolve(window.lottie || null);
    script.onerror = () => { lottieLoading = null; resolve(null); };
    document.head.append(script);
  });
  return lottieLoading;
}
function animated(img, id) {
  if (!animationObserver || !id) return;
  img.dataset.anim = id;
  animationObserver.observe(img);
}
function loadAnimation(id) {
  if (!ANIMATION_DATA.has(id)) {
    ANIMATION_DATA.set(id, fetch(stickerUrl(id) + '&anim=1').then(async (response) => {
      if (response.status === 204) return null;
      if (!response.ok) throw new Error('Sticker unavailable');
      const type = response.headers.get('content-type') || '';
      if (type.includes('json')) return { kind: 'lottie', data: await response.json() };
      if (!type.includes('webm')) return null;
      if (!WEBKIT) return {kind: 'video', url: stickerUrl(id) + '&anim=1'};
      const buffer = await response.arrayBuffer();
      const job = alphaDecodeQueue.then(() => decodeWebmAlpha(buffer));
      alphaDecodeQueue = job.catch(() => null);
      const animation = await job;
      if (animation?.opaque) return {kind: 'video', url: stickerUrl(id) + '&anim=1'};
      return animation ? {kind: 'alpha', ...animation} : null;
    }).catch(() => { ANIMATION_DATA.delete(id); return null; }));
    // Decoded canvases are much larger than the downloaded sticker.
    while (ANIMATION_DATA.size > (WEBKIT ? 8 : 128)) ANIMATION_DATA.delete(ANIMATION_DATA.keys().next().value);
  }
  return ANIMATION_DATA.get(id);
}
function playWebmAlpha(box, animation) {
  const {width, height, times, frames} = animation;
  const canvas = h('canvas', {width, height, 'aria-hidden': 'true'});
  box.append(canvas);
  const context = canvas.getContext('2d');
  const last = times.length - 1;
  const period = times[last] + (times[last] - (times[last - 1] ?? -33) || 33);
  let since = null, current = -1, task = null;
  const draw = (now) => {
    if (since === null) since = now;
    const position = (now - since) % period;
    let next = 0;
    while (next < last && times[next + 1] <= position) next++;
    if (next !== current) {
      current = next;
      context.putImageData(frames[next], 0, 0);
    }
    task = requestAnimationFrame(draw);
  };
  const play = () => { if (task === null) task = requestAnimationFrame(draw); };
  const pause = () => { if (task !== null) cancelAnimationFrame(task); task = null; };
  context.putImageData(frames[0], 0, 0);
  return {play, pause, destroy: pause};
}
async function startAnimation(img) {
  const id = img.dataset.anim;
  if (!id || img.dataset.started || !animationEnabled()) return;
  img.dataset.started = '1';
  const animation = await loadAnimation(id);
  if (!animation || !img.isConnected) { animationObserver.unobserve(img); return; }
  const box = h('span', { class: img.className + ' animated', title: img.title,
    role: img.alt ? 'img' : null, 'aria-label': img.alt || null, 'data-anim-id': id });
  const lottie = animation.kind === 'lottie' ? await ensureLottie() : null;
  if (animation.kind === 'lottie' && (!lottie || !img.isConnected)) { animationObserver.unobserve(img); return; }
  if (animation.kind === 'lottie') {
    const player = lottie.loadAnimation({ container: box, renderer: 'svg', loop: true, autoplay: true,
      animationData: animation.data, rendererSettings: { preserveAspectRatio: 'xMidYMid meet', progressiveLoad: true } });
    PLAYING.set(box, { play: () => player.play(), pause: () => player.pause(), destroy: () => player.destroy() });
  } else if (animation.kind === 'alpha') {
    const player = playWebmAlpha(box, animation);
    PLAYING.set(box, player);
    player.play();
  } else {
    const video = h('video', { src: animation.url, autoplay: true, loop: true, muted: true, playsinline: true });
    video.muted = true;
    box.append(video);
    PLAYING.set(box, { play: () => video.play().catch(() => {}), pause: () => video.pause(), destroy: () => video.pause() });
  }
  animationObserver.unobserve(img);
  img.replaceWith(box);
  animationObserver.observe(box);
}

// Intersection observations do not keep detached images or animations alive.
const animationCleanup = new MutationObserver(records => {
  for (const record of records) for (const node of record.removedNodes) {
    if (!(node instanceof Element) || node.isConnected) continue;
    const elements = [...node.querySelectorAll('img, .animated, [data-anim]')];
    if (node.matches('img, .animated, [data-anim]')) elements.push(node);
    for (const element of elements) {
      if (element.isConnected) continue;
      if (element.tagName === 'IMG') {
        element.lazyObserver?.unobserve(element);
        delete element.lazyObserver; delete element.lazyRoot;
        imageQueue.delete(element); imagesToWatch.delete(element);
      }
      PLAYING.get(element)?.destroy();
      PLAYING.delete(element);
      animationObserver?.unobserve(element);
    }
  }
  for (const [root, observer] of imageObservers) if (root && !root.isConnected) {
    observer.disconnect(); imageObservers.delete(root);
  }
});
animationCleanup.observe(document.body, {subtree: true, childList: true});

// Rows and messages reused after a redraw: animations stopped while they were
// off the page start again (from the still picture, as the first time).
function reviveAnimations(scope) {
  if (!animationObserver || !scope) return;
  for (const element of scope.querySelectorAll('.animated, [data-anim]')) {
    if (!element.classList.contains('animated')) { animationObserver.observe(element); continue; }
    if (PLAYING.has(element)) { animationObserver.observe(element); continue; }
    const id = element.dataset.animId;
    if (!id) continue;
    const alt = element.getAttribute('aria-label') || '';
    const img = lazySrc(h('img', { class: element.className.replace(/\banimated\b/, '').trim(), alt, title: element.title || null,
      decoding: 'async', onerror: () => img.replaceWith(document.createTextNode(alt)) }), stickerUrl(id));
    element.replaceWith(img);
    animated(img, id);
  }
}

function messageBrowserUrl(value) {
  if (!value || /[\s\u0000-\u001f\u007f]/u.test(value)) return null;
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:/i.test(value) ? value : 'https://' + value);
    if (['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password) return url.href;
  } catch (error) {}
  return null;
}
function messageLink(url, label) {
  return h('a', {href: url, target: '_blank', rel: 'noopener',
    onclick: event => { event.preventDefault(); event.stopPropagation(); if (!state.selection) openUrl(url); }}, label);
}
function linkify(text) {
  if (!feature('links')) return text ? [text] : [];
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(LINK)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const value = match[0];
    const mention = value[0] === '@';
    if (mention || value[0] === '#') {
      parts.push(h('a', {href: '#', onclick: event => {
        event.preventDefault(); event.stopPropagation();
        if (state.selection) return;
        if (mention) openTelegramName(value.slice(1)); else searchInChat(value);
      }}, value));
    } else {
      const target = /^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$/i.test(value) ? 'mailto:' + value : messageBrowserUrl(value);
      parts.push(target ? messageLink(target, value) : value);
    }
    last = match.index + value.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

async function openTelegramName(name) {
  const account = state.account;
  try {
    const chat = await api('resolve', {value: '@' + name});
    if (account === state.account) await openChat(chat.id, true, chat);
  } catch (error) { if (account === state.account) toast(error.message, 'error'); }
}

async function openUrl(url) {
  try {
    const result = await api('open_url', { url });
    if (!result.opened) window.open(url, '_blank', 'noopener');
  } catch (error) { toast(error.message, 'error'); }
}

// A link preview: site, title, description and photo; tap opens the link.
function webpageNode(message) {
  const page = message.webpage, peer = state.open?.peer;
  const card = h('div', { class: 'webpage', role: 'link', tabindex: 0,
    onclick: (event) => {
      event.stopPropagation();
      const url = messageBrowserUrl(page.url);
      if (url && !state.selection) openUrl(url);
    } },
    page.site ? h('div', { class: 'site' }, page.site) : null,
    page.title ? h('div', { class: 'title' }, page.title) : null,
    page.description ? h('div', { class: 'description' }, page.description) : null);
  if (page.photo && peer != null && state.settings?.photo_previews !== false) card.append(h('img', { alt: '', loading: 'lazy', decoding: 'async',
    src: '/media?' + resourceAuth() + '&peer=' + peer + '&id=' + message.id + '&thumb=1',
    onerror: (event) => event.target.remove() }));
  return card;
}

function fileNode(message) {
  if (message.visual || !['file', 'audio'].includes(message.kind) || message.service) return null;
  const peer = state.open.peer;
  const box = h('div', { class: 'file', onclick: (event) => event.stopPropagation() });
  if (message.kind === 'audio') box.append(h('audio', { controls: true, preload: message.voice ? 'metadata' : 'none', src: audioUrl(peer, message.id) }));
  const label = message.voice ? t('Voice message') + (message.duration ? ' · ' + clockTime(message.duration) : '')
    : message.kind === 'audio' && (message.title || message.performer) ? [message.performer, message.title].filter(Boolean).join(' – ')
    : (message.filename || t('File')) + (message.size ? ' · ' + humanSize(message.size) : '');
  box.append(h('span', { class: 'name' }, label),
    button(t('Open'), () => openFile(message)), button(t('Save'), () => openFile(message, state.open.peer, 'save')),
    button(t('Share'), () => openFile(message, state.open.peer, 'share')));
  return box;
}

// Downloads the file once (the core keeps it), then opens, saves or shares it.
function openFile(message, peer = state.open.peer, action = 'file', report = toast) {
  return downloads.start(message, peer, action);
}
async function openNativeMedia(request, action, report) {
  keepUnlocked(action === 'save' ? 30 : 120);
  report(t('Downloading…'));
  try {
    const result = await request();
    if (!result.opened) { report(t('Could not open the file.'), 'error'); return false; }
    const saved = action === 'save' && PLATFORM === 'Android';
    if (saved || report !== toast) report(saved ? t('Saved to Downloads/TG-ASCII.') : '');
    return true;
  } catch (error) { report(error.message, 'error'); return false; }
}

// Voice messages are Ogg/Opus; WebKit (iOS, Mac) plays the same audio from CAF.
const audioUrl = (peer, id) => mediaUrl(peer, id, false) + (PLATFORM === 'iOS' || MAC ? '&play=caf' : '');
const stagedUrl = (key) => '/staged?' + resourceAuth() + '&key=' + encodeURIComponent(key);
const clockTime = (seconds) => { seconds = Math.max(0, Math.round(seconds)); return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0'); };

// voice messages (desktop: Attach › Record voice message) ---------------------------
// Tap ◉: record; Stop to listen before sending, Send, or Cancel.
async function voiceRecorder() {
  if (!state.open || state.voice) return;
  const open = state.open;
  const destination = sendDestination(open);
  const capture = crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  state.voice = {peer: open.peer, capture};
  const layer = document.getElementById('sheet-layer');
  const clock = h('div', { class: 'voice-clock' }, '0:00');
  const meter = h('div', { class: 'voice-meter' }, '');
  const status = h('div', { class: 'muted small' }, t('Preparing the microphone…'));
  const actions = h('div', { class: 'voice-actions' });
  const panel = h('div', { class: 'sheet voice', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Voice message')), status, clock, meter, actions);
  layer.replaceChildren(panel); activateSheet(layer);
  let timer = null, recorded = null, finished = false, recording = false;
  const close = () => {
    finished = true; recording = false; clearTimeout(timer);
    if (state.voice?.capture === capture) state.voice = null;
    panel.onDismiss = null;
    if (layer.contains(panel)) closeSheet();
  };
  const cancel = () => {
    api('voice_cancel', { capture, keys: recorded && !sending ? [recorded.key, recorded.preview] : [] }).catch(() => {});
    close();
  };
  layer.onclick = () => {};  // a stray tap outside must not throw the recording away
  let sending = false;
  panel.onDismiss = cancel;
  const sendNow = async (result) => {
    if (sending) return false;
    if (state.open !== open || state.account !== destination.account) { cancel(); return true; }
    sending = true;
    const sent = await attempt(() => api('send_voice', {...destination, key: result.key, preview: result.preview, duration: result.duration}));
    sending = false;
    if (!sent) return false;
    close();
    consumeReply(open, destination.reply_to);
    return true;
  };
  const stop = async (andSend) => {
    recording = false; clearTimeout(timer);
    actions.replaceChildren();
    status.textContent = t('Saving…');
    try {
      recorded = await api('voice_stop', {capture});
    } catch (error) { if (!finished) { toast(error.message, 'error'); close(); } return; }
    if (finished) { api('voice_cancel', { capture, keys: [recorded.key, recorded.preview] }).catch(() => {}); return; }
    if (andSend && await sendNow(recorded)) return;
    status.textContent = t('Listen before sending');
    clock.textContent = clockTime(recorded.duration);
    meter.replaceChildren(h('audio', { controls: true, preload: 'auto', src: stagedUrl(PLATFORM === 'iOS' || MAC ? recorded.preview : recorded.key) }));
    actions.replaceChildren(
      h('button', { class: 'btn primary', onclick: () => sendNow(recorded) }, t('Enviar')),
      h('button', { class: 'btn', onclick: () => { api('voice_cancel', { capture, keys: [recorded.key, recorded.preview] }).catch(() => {}); close(); voiceRecorder(); } }, t('Record again')),
      h('button', { class: 'btn danger', onclick: cancel }, t('Delete')));
  };
  actions.append(h('button', { class: 'btn', onclick: cancel }, t('Cancelar')));
  try {
    await api('voice_start', {capture, account: destination.account});
  } catch (error) { if (!finished) { toast(error.message, 'error'); close(); } return; }
  if (finished) { api('voice_cancel', {capture}).catch(() => {}); return; }
  status.textContent = t('Recording…');
  actions.replaceChildren(
    h('button', { class: 'btn primary', onclick: () => stop(true) }, t('Enviar')),
    h('button', { class: 'btn', onclick: () => stop(false) }, t('Stop')),
    h('button', { class: 'btn danger', onclick: cancel }, t('Cancelar')));
  recording = true;
  const readLevel = async () => {
    try {
      const info = await api('voice_level', {capture});
      if (finished || !recording || !info.recording) return;
      clock.textContent = '● ' + clockTime(info.seconds);
      const bars = Math.round(info.level * 20);
      meter.textContent = '█'.repeat(bars) + '░'.repeat(20 - bars);
    } catch (error) { /* the next tick tries again */ }
    finally {
      if (!finished && recording) timer = setTimeout(readLevel, 250);
    }
  };
  timer = setTimeout(readLevel, 250);
}

// media (phase 2) ---------------------------------------------------------------
function mediaUrl(peer, id, thumb, viewing = false, stream = '') {
  const owner = WINDOW_ACCOUNT === null && state.account ? '&window_account=' + encodeURIComponent(state.account) : '';
  const quality = viewing && !thumb && !state.settings?.advanced_features?.media_originals ? '&quality=display' : '';
  return '/media?' + resourceAuth() + owner + '&peer=' + peer + '&id=' + id + '&thumb=' + (thumb ? 1 : 0) +
    quality + (!thumb && stream ? '&stream=' + encodeURIComponent(stream) : '');
}

// A preview picture that takes its final size before it arrives (the core sends
// the media's proportions), so loading it never pushes the conversation around.
function mediaImage(message, src) {
  const img = lazySrc(h('img', { decoding: 'async', alt: '' }), src);
  const ratio = message.w > 0 && message.h > 0 ? message.w / message.h : 0;
  if (ratio) {
    img.classList.add('sized');
    img.style.setProperty('--ar', Math.min(4, Math.max(0.25, ratio)).toFixed(4));
  }
  return img;
}

function mediaNode(message) {
  const peer = state.open.peer;
  const wrap = h('div', { class: 'media ' + message.kind,
    onclick: (event) => {
      event.stopPropagation();
      if (state.selection) return;
      // Desktop: a sticker opens its whole pack (send one, or save the pack).
      if (message.kind === 'sticker') { if (message.sticker_id) packView({ id: message.sticker_id }, false); }
      else viewer(message, peer);
    } });
  if ((state.settings?.inline_media === false || state.settings?.photo_previews === false) && message.kind !== 'sticker') {
    // "Show media in the chat" off: a placeholder; the photo opens in the viewer.
    wrap.append(h('span', { class: 'meta media-placeholder' }, (message.kind === 'video' ? '▶ ' : '▣ ') + t(message.kind === 'video' ? 'Vídeo' : 'Foto')));
    return wrap;
  }
  const img = mediaImage(message, mediaUrl(peer, message.id, true));
  img.addEventListener('error', () => { wrap.replaceChildren(h('span', { class: 'meta' }, '[' + (message.filename || message.kind) + ']')); });
  wrap.append(img);
  if (message.kind === 'sticker' && message.sticker_id) animated(img, message.sticker_id);
  if (message.kind === 'video') wrap.append(h('span', { class: 'play' }, '▶'));
  return wrap;
}

function mediaDialog(title) {
  document.querySelector('.media-viewer[open]')?.close();
  const layer = h('dialog', { class: 'media-viewer', 'aria-label': title, onclose: () => layer.remove() });
  document.body.append(layer);
  return layer;
}


// Photo/video viewer. Swipe left or right (or ‹ ›, arrow keys) for the other
// photos and videos of the same chat or shared-media list.
function viewer(message, peer = state.open.peer, shared = null, floating = null) {
  const revision = state.accountRevision, account = state.account;
  const layer = mediaDialog(t('Shared media'));
  const initialOpen = floating || (state.open?.peer === peer ? state.open : null);
  const chat = (initialOpen?.chat?.id === peer && initialOpen.chat) || state.chats.find(row => row.id === peer) ||
    {id: peer, name: shared?.name || floating?.name || String(peer), kind: floating?.kind};
  const origin = {account, peer, chat, thread: shared ? null : initialOpen?.thread, floating};
  const currentOpen = () => {
    if (floating) return state.windows.includes(floating) ? floating : null;
    const open = state.open;
    return open?.peer === peer && open.thread?.root === initialOpen?.thread?.root &&
      open.thread?.source === initialOpen?.thread?.source && open.thread?.post === initialOpen?.thread?.post &&
      open.topic?.id === initialOpen?.topic?.id ? open : null;
  };
  const active = () => account === state.account && revision === state.accountRevision && !state.locked &&
    (shared ? state.shared === shared && state.view === 'shared' : !!currentOpen());
  const visual = item => item.visual && ['image', 'video', 'gif'].includes(item.kind) &&
    (!shared || shared.kind !== 'photos_only' || item.kind === 'image') &&
    (!shared || shared.kind !== 'videos' || item.kind === 'video');
  const images = new Map([[message.id, message]]);
  const stream = globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
  let entries;
  function collect() {
    for (const item of (shared?.items || currentOpen()?.messages || [])) if (visual(item)) images.set(item.id, item);
    entries = [...images.values()].sort((a, b) => a.id - b.id);
  }
  collect();
  const more = () => active() && state.connection !== 'offline' &&
    (shared ? !shared.galleryDone : !currentOpen().done);
  async function load() {
    if (shared) {
      await loadSharedPage(shared);
    } else if (!await loadOlder(true, currentOpen())) {
      throw new Error(t('Media unavailable.'));
    }
    if (active()) collect();
  }
  let historyTarget = null;
  async function syncChat(item, live) {
    if (!shared) return;
    historyTarget = item.id;
    const open = currentOpen();
    while (live() && historyTarget === item.id && open && open === currentOpen() && !open.thread &&
      !open.done && open.messages.length && open.messages[0].id > item.id) {
      if (!await loadOlder(false, open)) break;
    }
  }
  presentGallery({layer, title: t('Shared media'), items: () => entries, selected: message,
    source: (item, thumb) => mediaUrl(peer, item.id, thumb, true,
      item.kind === 'video' || item.kind === 'gif' ? stream : ''), olderStep: -1, hasMore: more, loadPage: load,
    goToMessage: (item, close) => revealGalleryMessage(item, origin, close), allowSystemPlayer: true,
    exportItem: (initialOpen?.chat || state.chats.find(chat => chat.id === peer))?.protected ? null :
      (item, action, report) => openFile(item, peer, action, report), active, onSelected: syncChat});
}

function imageViewer(url, title, onError) {
  const layer = mediaDialog(title);
  const close = () => layer.close();
  const img = h('img', { src: url, alt: title });
  if (onError) img.onerror = () => { if (layer.open) { close(); onError(); } };
  const stage = h('div', { class: 'stage' }, img);
  const releaseGestures = photoGestures(stage, img);
  layer.addEventListener('close', releaseGestures, {once: true});
  layer.append(h('div', { class: 'bar' }, symbolButton('x', t('Close'), close), h('div', { class: 'title' }, title)), stage);
  layer.showModal();
}

async function avatarViewer(data) {
  const revision = state.accountRevision, account = state.account, peer = data.id;
  const title = [t('Profile photo'), data.name].filter(Boolean).join(' · ');
  const layer = mediaDialog(title);
  const current = () => !state.locked && revision === state.accountRevision && layer.open;
  layer.append(h('div', {class: 'bar'}, symbolButton('×', t('Close'), () => layer.close()), h('div', {class: 'title'}, title)),
    h('div', {class: 'stage'}, t('Cargando...')));
  layer.showModal();
  const entries = [], ids = new Set();
  let cursor = 0;
  async function load() {
    const offset = cursor;
    const page = await api('profile_photos', {peer, account, offset});
    if (!current()) return;
    for (const item of page.items) {
      if (!ids.has(item.id)) { ids.add(item.id); entries.push(item); }
    }
    cursor = page.next !== null && page.next > offset ? page.next : null;
  }
  try {
    if (state.connection !== 'offline') await load();
    else cursor = null;
  } catch { cursor = null; }
  if (!current()) return;
  // Telegram can expose a personal or public fallback photo to this account
  // while omitting it from the history. Keep it as the first visible entry.
  if ((data.photo_id && !ids.has(data.photo_id)) || (!entries.length && data.has_photo !== false)) {
    entries.unshift({id: data.photo_id || 'current', current: true, kind: 'image'});
  }
  if (!entries.length) { layer.close(); toast(t('No photo.')); return; }
  const owner = WINDOW_ACCOUNT === null ? '&window_account=' + encodeURIComponent(account) : '';
  const base = resourceAuth() + owner + '&peer=' + peer;
  const url = (item, thumb) => item.current ? '/avatar?' + base + (thumb ? '' : '&big=1') +
    '&v=' + encodeURIComponent(state.avatarVersion || item.id) :
    '/profile-photo?' + base + '&' + new URLSearchParams({account, photo: item.id, offset: item.offset, thumb: thumb ? 1 : 0});
  presentGallery({layer, title, items: () => entries, selected: entries[0], source: url,
    olderStep: 1, hasMore: () => cursor !== null && state.connection !== 'offline', loadPage: load, active: current,
    exportItem: (item, action, report) => openNativeMedia(() => api('open_profile_photo',
      {account, peer, action, photo: item.current ? null : item.id, offset: item.offset || 0}), action, report)});
}

function nearBottom(scroll) { return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120; }

function emptyHistory(view) {
  const label = view.historyLoaded ? 'No hay mensajes en este chat.' : state.connection === 'offline' ? 'Sin conexion' : 'Cargando...';
  return h('div', { class: 'empty' }, t(label));
}

// Message nodes already drawn for the open chat, reused while the message and
// everything its node shows stay the same: refreshing the history or loading
// older pages does not rebuild (and reload) the pictures already on screen.
function messageContext(open) {
  const settings = state.settings || {};
  return [state.language, state.rtl, !!state.selection, !!state.groupCallsAvailable, settings.inline_media, settings.photo_previews,
    settings.ascii_text, animationEnabled(), open.translate || ''].join('|');
}
function messageKey(message, open, replied) {
  return JSON.stringify(message) + '\u0001' + (replied ? JSON.stringify([replied.sender, replied.text, replied.custom_emojis]) : '') +
    '\u0001' + (state.selection?.has(message.id) ? 1 : 0) + '\u0001' + JSON.stringify(open.translated?.[message.id] ?? null) +
    '\u0001' + (open.originals?.has(message.id) ? 1 : 0);
}
function messageCache(open) {
  const context = messageContext(open);
  if (!open.nodeCache || open.nodeCache.context !== context) open.nodeCache = { context, nodes: new Map() };
  return open.nodeCache;
}
function cachedMessageNode(message, open, replied, kept) {
  const cache = messageCache(open);
  const key = messageKey(message, open, replied);
  const known = cache.nodes.get(message.id);
  const node = known && known.key === key && !kept?.has(message.id) ? known.node : messageNode(message);
  (kept || cache.nodes).set(message.id, { key, node });
  return node;
}

function drawMessages(toBottom) {
  const container = document.getElementById('messages');
  const scroll = document.getElementById('scroll');
  if (!container || !state.open) return;
  const open = state.open;
  const nodes = [];
  if (open.olderFailed) nodes.push(button(t('Reintentar'), () => loadOlder(true)));
  const byId = new Map(open.messages.map((message) => [message.id, message]));
  const cache = messageCache(open), kept = new Map();
  const days = open.dayNodes || new Map(), keptDays = new Map();
  const previousAlbums = open.albumNodes || new Map(), albums = new Map();
  let lastDay = '';
  for (const [index, message] of open.messages.entries()) {
    if (message.date) {
      const day = new Date(message.date * 1000).toDateString();
      if (day !== lastDay) {
        const label = dayLabel(message.date);
        const known = days.get(day);
        const node = known && known.textContent === label && !keptDays.has(day) ? known : h('div', { class: 'day' }, label);
        keptDays.set(day, node);
        nodes.push(node); lastDay = day;
      }
    }
    const node = cachedMessageNode(message, open, message.reply_to ? byId.get(message.reply_to) : null, kept);
    groupSender(node, message, open.messages[index-1], open.messages[index+1], open.chat?.kind === 'group');
    if (message.album && message.visual && ['image','video','gif'].includes(message.kind)) {
      let album = albums.get(message.album);
      if (!album) {
        const strip = previousAlbums.get(message.album) || h('div', {class: 'photo-album', role: 'group', 'aria-label': t('Álbum')});
        albums.set(message.album, album = {strip, children: []});
        nodes.push(strip);
      }
      album.children.push(node);
    } else nodes.push(node);
  }
  open.albumNodes = new Map();
  for (const [id, album] of albums) {
    reconcile(album.strip, album.children); open.albumNodes.set(id, album.strip);
  }
  cache.nodes = kept; open.dayNodes = keptDays;
  if (!nodes.length) nodes.push(emptyHistory(open));
  const previous = scroll.scrollHeight - scroll.scrollTop;
  reconcile(container, nodes);
  watchImages(container);
  reviveAnimations(container);
  if (open.translate) translatePending();
  if (toBottom) { scroll.scrollTop = scroll.scrollHeight; open.stickUntil = Date.now() + 5000; }
  else {
    // Keep the same messages in view (older pages are added above them).
    const target = scroll.scrollHeight - previous;
    if (Math.abs(scroll.scrollTop - target) >= 1) scroll.scrollTop = target;
  }
}
// Pictures load after the chat is drawn: stay at the newest message meanwhile.
document.addEventListener('load', (event) => {
  if (event.target.tagName !== 'IMG' || !state.open || Date.now() > (state.open.stickUntil || 0)) return;
  const scroll = document.getElementById('scroll');
  if (scroll && scroll.contains(event.target)) scroll.scrollTop = scroll.scrollHeight;
}, true);

function appendMessage(message) {
  const container = document.getElementById('messages');
  const scroll = document.getElementById('scroll');
  if (!container) return;
  const open = state.open;
  const stick = nearBottom(scroll) || message.out;
  if (message.album || open.chat?.kind === 'group') { drawMessages(stick); return; }
  container.querySelector('.empty')?.remove();
  const replied = message.reply_to ? open.messages.find((item) => item.id === message.reply_to) : null;
  container.append(cachedMessageNode(message, open, replied));
  if (open.translate) translatePending();
  if (stick) { scroll.scrollTop = scroll.scrollHeight; open.stickUntil = Date.now() + 5000; }
}

function replaceMessage(message) {
  const node = document.getElementById('m' + message.id);
  if (!node || !state.open) return;
  const open = state.open;
  if (open.chat?.kind === 'group') { drawMessages(false); return; }
  const replied = message.reply_to ? open.messages.find((item) => item.id === message.reply_to) : null;
  messageCache(open).nodes.delete(message.id);
  node.replaceWith(cachedMessageNode(message, open, replied));
}

function drawOutbox() {
  const container = document.getElementById('outbox');
  if (!container || !state.open) return;
  const scroll = document.getElementById('scroll');
  const stick = nearBottom(scroll);
  container.replaceChildren(...(state.open.outbox || []).map((item) => h('div', { class: 'msg out ' + (item.state === 'failed' ? 'failed' : 'pending') },
    h('div', { class: 'head' }, h('span', { class: 'who' }, t('Tu'))),
    h('div', { class: 'text' }, item.text),
    h('div', { class: 'meta message-footer' }, h('time', {class: 'bubble-clock'}, item.created ? new Date(item.created * 1000).toLocaleTimeString(state.language || undefined, {hour: '2-digit', minute: '2-digit'}) : ''), item.state === 'failed' ? '⚠ ' + t('No enviado') + (item.error ? ': ' + item.error : '') : '◷ ' + t('Pendiente de envio')),
    item.state === 'sending' ? null : h('div', {},
      item.state === 'failed' ? button(t('Reintentar'), () => api('outbox.retry', { peer: state.open.peer, key: item.key })) : null,
      item.files ? null : button(t('Editar'), () => editPending(item)),
      button(t('Eliminar'), () => api('outbox.remove', { peer: state.open.peer, key: item.key }), 'danger')))));
  if (stick) scroll.scrollTop = scroll.scrollHeight;
}

// A message still waiting to be sent (no connection): change its text first.
function editPending(item) {
  const peer = state.open.peer;
  const field = h('textarea', { rows: 5, maxlength: 4096 }); field.value = item.full ?? item.text;
  formSheet(t('Editar'), [field], t('Guardar'), async () => {
    const text = field.value.trim();
    if (!text) return false;
    try { await api('outbox.edit', { peer, key: item.key, text }); }
    catch (error) { toast(error.message, 'error'); return false; }
  });
}

function loadOlder(retry = false, open = state.open) {
  if (!open) return false;
  if (open.olderRequest) return open.olderRequest;
  if ((open.olderFailed && !retry) || open.done || !open.messages.length || state.connection === 'offline') return false;
  const revision = state.accountRevision, account = state.account;
  const active = () => revision === state.accountRevision && !state.locked && (state.open === open || state.windows.includes(open));
  const redraw = () => { if (state.open === open) drawMessages(false); else drawWindowMessages(open, false); };
  open.loadingOlder = true;
  open.olderRequest = (async () => {
    try {
      const thread = open.thread;
      const page = open.topic
        ? await api('forum_older', {peer: open.peer, topic_id: open.topic.id, before: thread.cursor, account, window_peer: WINDOW_CHAT})
        : thread ? await api('comments_older', {peer: open.peer, root_id: thread.root, offset: thread.cursor, window_peer: WINDOW_CHAT})
        : await api('older', {peer: open.peer, before: open.messages[0].id, account});
      if (!active()) return false;
      const known = new Set(open.messages.map(item => item.id));
      const fresh = page.messages.filter(item => !known.has(item.id));
      if (thread) {
        open.done = !page.more || thread.cursor === page.next;
        thread.cursor = page.next;
        open.messages.splice(open.topic ? 0 : 1, 0, ...fresh);
      } else {
        if (!fresh.length) open.done = true;
        open.messages = [...fresh, ...open.messages];
      }
      if (open.translate === page.translate && open.translated) Object.assign(open.translated, page.translated);
      open.olderFailed = false;
      redraw();
      return true;
    } catch {
      if (active()) { open.olderFailed = true; redraw(); }
      return false;
    } finally { open.loadingOlder = false; open.olderRequest = null; }
  })();
  return open.olderRequest;
}

function resizeComposer(field) {
  field.style.height = 'auto';
  if (field.value) {
    const borders = field.offsetHeight - field.clientHeight;
    field.style.height = (field.scrollHeight + borders) + 'px';
  }
}

function composer() {
  const context = h('div', { class: 'context', id: 'context' });
  const prompt = t('Escribe un mensaje');
  const field = h('textarea', { id: 'field', dir: 'auto', rows: 1, placeholder: prompt, 'aria-label': prompt,
    readonly: !!state.open && draftSends.has(draftKey(composerPeer())),
    oninput: (event) => {
      resizeComposer(event.target);
      composerMode();
      if (state.open && !state.editing) updateDraftEmoji(composerPeer(), event.target.value, event.detail?.emoji);
      if (state.open && !state.editing && state.formats[composerPeer()]) { refreshFormats(event.target.value); drawFormatPreview(); }
      saveDraft();
      const now = Date.now();
      if (state.open && event.target.value && now - (state.open.typingSent || 0) > 5000 && state.connection !== 'offline') {
        state.open.typingSent = now; api('typing', { peer: state.open.peer }).catch(() => {});
      }
    },
    onkeydown: (event) => {
      if (event.key === 'Enter' && !event.shiftKey && state.settings.enter_send && !TOUCH) {
        event.preventDefault(); send();
      }
    } });
  return h('div', { class: 'composer' }, context, h('div', { class: 'attachments', id: 'attachments' }),
    h('div', { class: 'format-bar', id: 'format-bar', hidden: !state.formatBar }, FORMAT_BUTTONS.map(([style, label, title]) =>
      h('button', { class: 'btn', title: t(title), 'aria-label': t(title),
        onmousedown: (event) => event.preventDefault(), onclick: () => applyFormat(style) },
      h('span', { 'data-format': style }, label)))),
    h('div', { class: 'format-preview', id: 'format-preview', hidden: true }),
    h('div', { class: 'line', id: 'composer-line' }, symbolButton('+', t('Adjuntar'), attachMenu),
      iconButton('emoji', t('Custom emoji') + ' / ' + t('Stickers'), () => stickerPicker(true), 'sticker-button'),
      iconButton('format', t('Formatting'), () => { state.formatBar = !state.formatBar; document.getElementById('format-bar').hidden = !state.formatBar; composerMode(); }, 'format-button'),
      h('div', { class: 'composer-field' }, field, h('span', { class: 'composer-prompt', 'aria-hidden': 'true' }, prompt)),
      iconButton('mic', t('Voice message'), voiceRecorder, 'voice-button'), sendButton()));
}

// Formatting while writing (desktop: editor formats): select text, then a style.
const FORMAT_BUTTONS = [['bold', 'B', 'Bold'], ['italic', 'I', 'Italic'], ['underline', 'U', 'Underline'], ['strike', 'S', 'Strikethrough'],
  ['spoiler', '▒', 'Spoiler'], ['code', '</>', 'Monospace'], ['link', '🔗', 'Link'], ['quote', '❝', 'Quote'],
  ['collapsed_quote', '❝…', 'Collapsed quote'], ['clear', '✕', 'Clear formatting']];
function applyFormat(style) {
  const field = document.getElementById('field');
  if (!field || !state.open) return;
  const open = state.open, peer = composerPeer(open);
  const start = field.selectionStart, end = field.selectionEnd;
  const list = state.formats[peer] = state.formats[peer] || [];
  if (style === 'clear') {
    state.formats[peer] = start === end ? [] : list.filter((span) => span.end <= start || span.start >= end);
    drawFormatPreview(); saveDraft(); return;
  }
  if (start === end) { toast(t('Select the text to format first.')); return; }
  const add = (argument = '') => {
    if (state.open !== open || document.getElementById('field') !== field) return;
    const text = field.value.slice(start, end);
    if (!text) return;
    const same = list.findIndex((span) => span.start === start && span.end === end && span.style === style);
    if (same >= 0) list.splice(same, 1); else list.push({ start, end, style, argument, text });
    drawFormatPreview(); saveDraft(); field.focus(); field.setSelectionRange(end, end);
  };
  if (style === 'link') promptThen(t('Link'), { value: 'https://', inputmode: 'url' }, (url) => {
    if (!/^(https?|tg):\/\/\S+$/i.test(url.trim())) { toast(t('Use an https://, http:// or tg:// link.'), 'error'); return false; }
    add(url.trim());
  });
  else add();
}
// After an edit, each span follows its text (or is dropped if that text is gone).
function refreshFormats(value) {
  const peer = composerPeer();
  state.formats[peer] = (state.formats[peer] || []).flatMap((span) => {
    if (!span.text) return [];
    if (value.slice(span.start, span.end) === span.text) return [span];
    let best = -1;
    for (let at = value.indexOf(span.text); at >= 0; at = value.indexOf(span.text, at + 1))
      if (best < 0 || Math.abs(at - span.start) < Math.abs(best - span.start)) best = at;
    return best < 0 ? [] : [{ ...span, start: best, end: best + span.text.length }];
  });
  if (!state.formats[peer].length) delete state.formats[peer];
}
function drawFormatPreview() {
  const box = document.getElementById('format-preview');
  const field = document.getElementById('field');
  if (!box || !field || !state.open) return;
  const spans = state.formats[composerPeer()] || [];
  box.hidden = !spans.length;
  if (spans.length) box.replaceChildren(h('span', { class: 'muted' }, t('Preview') + ': '),
    ...formatText(field.value, spans.map((span) => [span.start, span.end, span.style, span.argument]), [], false));
}

// Like Telegram: an empty composer offers stickers and the microphone; while
// writing (or with attachments, or editing) the formatting and send buttons
// take their place, so the text field keeps room for its prompt.
function composerMode() {
  const line = document.getElementById('composer-line');
  const field = document.getElementById('field');
  if (!line || !field) return;
  const writing = Boolean(field.value.trim() || state.attachments.length || state.editing || state.formatBar);
  line.classList.toggle('writing', writing);
  fitPrompt();
}

// The full prompt when it fits; otherwise Telegram's short "Message", never cut.
function fitPrompt() {
  const prompt = document.querySelector('.composer-prompt');
  if (!prompt) return;
  // Some translations end in "…", which reads as cut-off text in a prompt.
  const plain = (text) => text.replace(/\s*(…|\.\.\.)\s*$/, '');
  prompt.textContent = plain(t('Escribe un mensaje'));
  if (prompt.offsetParent && prompt.scrollWidth > prompt.clientWidth + 1) prompt.textContent = plain(t('Message'));
}
window.addEventListener('resize', () => fitPrompt());

function sendButton() {
  // Tap: send. Hold (or right click): send without sound / schedule.
  let timer = null, held = false;
  return h('button', { class: 'btn primary send-button', onclick: () => { if (!held) send(); },
    oncontextmenu: (event) => { event.preventDefault(); sendOptions(); },
    ontouchstart: () => { held = false; timer = setTimeout(() => { held = true; sendOptions(); }, 550); },
    ontouchend: () => clearTimeout(timer), ontouchmove: () => clearTimeout(timer) }, '>');
}

function sendOptions() {
  const isSecret = state.open && state.open.chat && state.open.chat.kind === 'secret';
  sheet(t('Enviar'), [
    !isSecret ? [t('Telegram AI'), composeAI] : null,
    [t('Send without sound'), () => send({ silent: true })],
    !isSecret ? [t('Schedule message'), scheduleSheet] : null,
  ].filter(Boolean));
}

function scheduleSheet() {
  const layer = document.getElementById('sheet-layer');
  const soon = new Date(Date.now() + 3600000);
  const local = new Date(soon.getTime() - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const input = h('input', { type: 'datetime-local', value: local });
  layer.replaceChildren(h('div', { class: 'sheet', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Schedule message')), h('div', { class: 'quick' }, input),
    h('button', { class: 'item', onclick: () => { closeSheet(); send({ schedule: input.value }); } }, t('Enviar')),
    h('button', { class: 'item', onclick: closeSheet }, t('Cancelar'))));
  activateSheet(layer);
  layer.onclick = closeSheet;
}

function drawContext() {
  const context = document.getElementById('context');
  if (!context) return;
  const target = state.editing || state.reply;
  if (!target) { context.replaceChildren(); return; }
  context.replaceChildren(h('span', {}, (state.editing ? t('Editando mensaje') : t('Respondiendo a') + ' ' + target.sender) + ': ' + (target.text || '').replace(/\s+/g, ' ')),
    button('x', () => { if (state.editing) {
        const field = document.getElementById('field');
        field.value = '';
        resizeComposer(field);
      }
      state.reply = state.editing = null;
      drawContext(); }));
}

// attachments (phase 2) --------------------------------------------------------------
function attachMenu() {
  const chat = state.open.chat;
  const isSecret = chat.kind === 'secret';
  const items = [
    [t('Gallery'), () => chooseFiles('gallery')],
    [t('Camera'), () => chooseFiles('camera')],
    [t('Audio') + ' · ' + t('Voice message'), voiceRecorder],
    [t('Archivo de audio'), () => chooseFiles('audio', {accept: 'audio/*'})],
    [t('Archivo'), () => chooseFiles('any')],
  ];
  // Telegram accepts polls in groups and channels (and bots / Saved Messages).
  if (!isSecret && (chat.kind !== 'user' || state.open.isSelf) && feature('polls')) items.push([t('Poll'), pollSheet]);
  if (!isSecret && feature('contacts')) items.push([t('Contact'), shareContactSheet]);
  if (!isSecret && feature('articles')) items.push([t('Article'), articleSheet]);
  if (!isSecret && feature('checklists')) items.push([t('Checklist'), checklistSheet]);
  sheet(t('Adjuntar'), items);
}

// panes and chat windows (desktop: resizable panes, chats in their own windows) -------
let appearanceWrites = Promise.resolve();
const saveLook = (values) => {
  const account = state.account, revision = state.accountRevision;
  appearanceWrites = appearanceWrites.catch(() => {}).then(() => {
    if (state.account !== account || state.accountRevision !== revision || state.locked) return;
    const patch = typeof values === 'function' ? values(state.appearance || {}) : values;
    return attempt(() => api('appearance', { values: patch, account }), (result) => {
      if (state.account !== account || state.accountRevision !== revision) return;
      state.appearance = result; applySettings(); render();
    });
  });
  return appearanceWrites;
};

function resizePanes(event, side) {
  event.preventDefault();
  const divider = event.currentTarget;
  divider.setPointerCapture(event.pointerId);
  divider.classList.add('active');
  let width = side.getBoundingClientRect().width;
  const move = (moved) => {
    width = Math.max(0, Math.min(innerWidth - 7, moved.clientX));
    side.classList.toggle('collapsed', width < 80);
    side.style.width = (width < 80 ? 0 : width) + 'px';
  };
  const done = () => {
    divider.removeEventListener('pointermove', move);
    divider.classList.remove('active');
    // 1 = the list is hidden; a width close to the screen hides the chat instead.
    saveLook({ side_width: width < 80 ? 1 : Math.round(width) });
  };
  divider.addEventListener('pointermove', move);
  divider.addEventListener('pointerup', done, { once: true });
  divider.addEventListener('pointercancel', done, { once: true });
}

const windowLayer = document.body.appendChild(h('div', { id: 'windows' }));
function saveWindows() {
  const windows = state.windows.map((win) => ({ peer: win.peer, name: win.name, docked: win.docked,
    x: Math.round(win.x), y: Math.round(win.y), w: Math.round(win.w), h: Math.round(win.h) }));
  const account = state.account;
  api('appearance', { values: { windows }, account }).then((result) => {
    if (state.account === account) state.appearance = result;
  }, () => {});
}
function defaultGeometry(index) {
  const w = Math.min(400, innerWidth - 24), h = Math.min(560, innerHeight - 90);
  return { x: Math.max(8, innerWidth - w - 24 - 28 * index), y: 70 + 28 * index, w, h };
}
// A system window when the device has them (iPad, Android split screen and
// free-form windows), the in-app floating window otherwise.
async function openChatWindow(chat) {
  const account = state.account;
  try {
    const result = await api('system_window', { peer: chat.id, account });
    if (result.opened) return;
  } catch (error) {}
  if (state.account === account && !state.locked) return openWindow(chat);
}

async function openWindow(chat, docked = false, restore = null) {
  const account = state.account;
  let win = state.windows.find((item) => item.peer === chat.id);
  const current = state.chats.find(item => item.id === chat.id);
  const forum = current?.forum ? current : chat.forum ? chat : win?.forumChat;
  if (forum && !restore) {
    if (win) showFloatingForum(win, forum);
    return openFloatingForum(forum, win);
  }
  const entering = !win || win.minimized;
  if (!win) {
    win = { peer: chat.id, name: chat.name || String(chat.id), docked, messages: [], reply: null,
      ...defaultGeometry(state.windows.length), ...(restore || {}), account, forumChat: forum };
    state.windows.push(win);
    restoreWindowDraft(win, state.drafts[win.peer]);
    if (!restore) saveWindows();
  }
  win.minimized = false;
  if (win.docked && WIDE()) render(); else drawWindow(win);
  if (entering && !restore) animateSurface(win.node, 'window');
  if (!forum) await refreshFloatingWindow(win, true, !restore);
}
async function openFloatingForum(chat, win) {
  if (await openForumList(chat) && win) await closeWindow(win);
}
function showFloatingForum(win, chat) {
  if (!win || !chat.forum || win.account !== state.account) return;
  const changed = !win.forumChat || win.forumChat.name !== chat.name;
  if (win.opened && !win.sending) saveWindowDraft(win);
  win.forumChat = chat;
  win.name = chat.name;
  win.opened = false;
  win.messages = [];
  win.nodeCache = null;
  if (changed) { if (win.docked && WIDE()) render(); else drawWindow(win); }
}
async function refreshFloatingWindow(win, read = true, navigateForum = false) {
  if (win.forumChat) return;
  const account = win.account;
  const request = win.request = (win.request || 0) + 1;
  const initialDraft = state.drafts[win.peer];
  const initialMessages = win.messages, initialCount = win.messages.length;
  const initialTranslation = win.translating;
  let data;
  try { data = await api('window_open', { peer: win.peer, account, read }); }
  catch (error) {
    if (!win.opened && !win.forumChat && state.account === account && !state.locked && state.windows.includes(win) && win.request === request) {
      win.loadFailed = true;
      if (win.docked && WIDE()) render(); else drawWindow(win);
    }
    return;
  }
  if (data && state.account === account && !state.locked && state.windows.includes(win) && win.request === request) {
    if (data.forum || win.forumChat) {
      if (data.forum) showFloatingForum(win, data.chat);
      if (navigateForum) await openFloatingForum(win.forumChat, win);
      return;
    }
    let redraw = !win.opened;
    win.opened = true;
    win.loadFailed = false;
    if (win.messages === initialMessages && win.messages.length === initialCount && (data.messages.length || !initialCount)) {
      win.messages = data.messages;
      if (data.messages.length) win.historyLoaded = true;
    }
    if (data.chat) {
      redraw ||= win.kind !== data.chat.kind || win.name !== data.chat.name || win.emojiStatus !== data.chat.emoji_status;
      win.name = data.chat.name; win.kind = data.chat.kind; win.emojiStatus = data.chat.emoji_status;
    }
    if (redraw) { if (win.docked && WIDE()) render(); else drawWindow(win); }
    const key = draftKey(win.peer);
    if (state.drafts[win.peer] === initialDraft && !draftWrites.has(key) && !failedDraftWrites.has(key) && !draftSends.has(key)) {
      state.drafts[win.peer] = data.draft;
    }
    if (win.translating === initialTranslation) applyChatTranslation(win, data);
    if (!win.sending) restoreWindowDraft(win, state.drafts[win.peer]);
    drawWindowMessages(win, read);
  }
}
async function closeWindow(win) {
  if (win.sending || (win.opened && win.draftReady && !(await saveWindowDraft(win))) || !state.windows.includes(win)) return;
  const node = win.node;
  if (node && !win.docked) {
    node.inert = true;
    node.classList.add('closing-window');
    animateSurface(node, 'window', true, () => node.remove());
  } else node?.remove();
  state.windows = state.windows.filter((item) => item !== win);
  api('window_close', {peer: win.peer, account: win.account}).catch(() => {});
  saveWindows();
  if (win.docked && WIDE()) render();
}
// Docked windows are columns of the wide layout (returned to render); the rest float.
function syncWindows(wide) {
  const docked = [];
  for (const win of state.windows) {
    if (win.docked && wide) { win.node?.remove(); win.node = null; docked.push(drawWindow(win, true)); }
    else if (!win.node || !win.node.isConnected || win.node.classList.contains('docked')) drawWindow(win);
  }
  return docked;
}
function drawWindow(win, asColumn = false) {
  const docked = asColumn;
  const prompt = t('Escribe un mensaje');
  const field = h('textarea', { dir: 'auto', rows: 1, placeholder: prompt, 'aria-label': prompt,
    oninput: () => saveWindowDraft(win),
    onkeydown: (event) => { if (event.key === 'Enter' && !event.shiftKey && !TOUCH) { event.preventDefault(); sendFromWindow(win); } } });
  field.value = win.draft?.text || '';
  field.readOnly = !win.opened || !win.draftReady || draftSends.has(draftKey(win.peer));
  const tool = (label, title, action, attrs = {}) => h('button', { class: 'btn bare wintool', title, 'aria-label': title,
    onclick: (event) => { event.stopPropagation(); action(); }, ...attrs }, label);
  const bar = h('div', { class: 'winbar', onpointerdown: (event) => { if (!docked) dragWindow(event, win); } },
    avatar(win.peer, win.name, 'small'), nameWithStatus(win.name, win.emojiStatus),
    docked ? null : tool(win.minimized ? '▢' : '_', t('Minimize'), () => { win.minimized = !win.minimized; drawWindow(win); }),
    WIDE() ? tool(win.docked ? '⧉' : '⇥', win.docked ? t('Float') : t('Dock to the side'), () => {
      win.docked = !win.docked; win.node?.remove(); win.node = null; saveWindows(); render(); }) : null,
    win.opened && win.kind && win.kind !== 'secret' && feature('chat_translation')
      ? tool('⇄', t('Automatic translation (Premium)'), () => translateChat(win), {'data-translation-toggle': ''}) : null,
    tool('↗', t('Open chat'), () => win.forumChat ? openFloatingForum(win.forumChat, win) : openChat(win.peer, true, { id: win.peer, name: win.name })),
    tool('x', t('Close chat'), () => closeWindow(win)));
  const node = h('div', { class: 'chatwin ' + (docked ? 'docked pane' : 'floating') + (win.minimized && !docked ? ' min' : '') },
    bar, h('div', { class: 'winbody' }, win.forumChat ? button(t('Todos los temas'), () => openFloatingForum(win.forumChat, win))
      : win.opened ? null : win.loadFailed ? button(t('Reintentar'), () => refreshFloatingWindow(win, true, true)) : t('Cargando...')),
    win.opened ? h('div', { class: 'wincompose' }, h('div', { class: 'context' }),
      h('div', { class: 'line' }, field, h('button', { class: 'btn primary', onclick: () => sendFromWindow(win) }, '>'))) : null,
    docked ? null : h('div', { class: 'grip', onpointerdown: (event) => resizeWindow(event, win) }));
  if (!docked) {
    win.x = Math.max(0, Math.min(win.x, innerWidth - 120)); win.y = Math.max(0, Math.min(win.y, innerHeight - 50));
    Object.assign(node.style, { left: win.x + 'px', top: win.y + 'px', width: win.w + 'px', height: win.minimized ? 'auto' : win.h + 'px' });
  }
  const old = win.node;
  win.node = node;
  paintChatWallpaper(node.querySelector('.winbody'), win.peer);
  if (!docked) { if (old && old.isConnected && !old.classList.contains('docked')) old.replaceWith(node); else { old?.remove(); windowLayer.append(node); } }
  drawWindowMessages(win, true);
  drawWindowContext(win);
  return node;
}
function drawWindowMessages(win, toBottom) {
  const body = win.node?.querySelector('.winbody');
  if (!body || !win.opened || win.forumChat) return;
  const stick = toBottom || body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  // Same reuse as the main chat: unchanged messages keep their node and picture.
  const context = [state.language, state.settings?.ascii_text, state.settings?.photo_previews, win.translate || ''].join('|');
  body.classList.toggle('bubbles', !!state.settings?.bubbles);
  if (!win.nodeCache || win.nodeCache.context !== context) win.nodeCache = { context, nodes: new Map() };
  const kept = new Map();
  const nodes = win.messages.slice(-200).map((message, index, visible) => {
    const key = JSON.stringify(message) + '\u0001' + JSON.stringify(win.translated?.[message.id] ?? null) + (win.originals?.has(message.id) ? 1 : 0);
    const known = win.nodeCache.nodes.get(message.id);
    const node = known && known.key === key && !kept.has(message.id) ? known.node : windowMessage(win, message);
    groupSender(node, message, visible[index-1], visible[index+1], win.kind === 'group');
    kept.set(message.id, { key, node });
    return node;
  });
  win.nodeCache.nodes = kept;
  reconcile(body, nodes.length ? nodes : [emptyHistory(win)]);
  watchImages(body);
  reviveAnimations(body);
  if (stick) body.scrollTop = body.scrollHeight;
  win.node.querySelector('[data-translation-toggle]')?.setAttribute('aria-pressed', String(!!win.translate));
  translatePending(win);
}
function windowMessage(win, message) {
  if (message.service) return h('div', { class: 'msg service' }, message.text);
  const text = message.visual ? message.caption : message.text;
  return h('article', { tabindex: 0, 'aria-haspopup': 'dialog', class: 'msg' + (message.out ? ' out' : ''),
    onkeydown: (event) => messageActionKey(event, () => windowMessageMenu(win, message)),
    onclick: () => windowMessageMenu(win, message), oncontextmenu: (event) => { event.preventDefault(); windowMessageMenu(win, message); } },
    h('div', { class: 'head' }, h('span', { class: 'who' }, message.sender), h('time', {class: 'header-clock'}, message.time)),
    message.visual ? h('div', { class: 'media ' + message.kind, onclick: (event) => { event.stopPropagation(); if (message.kind !== 'sticker') viewer(message, win.peer, null, win); } },
      state.settings?.photo_previews === false && message.kind !== 'sticker' ? t(message.kind === 'video' ? 'Vídeo' : 'Foto') : mediaImage(message, mediaUrl(win.peer, message.id, true))) : null,
    text ? messageText(message, win) : null,
    !message.visual && ['file', 'audio'].includes(message.kind)
      ? h('div', { class: 'file' }, h('button', { class: 'btn', onclick: (event) => { event.stopPropagation(); openFile(message, win.peer); } }, t('Open'))) : null,
    messageReactions(message, win.peer),
    messageFooter(message));
}
function windowMessageMenu(win, message) {
  sheet(t('Mensaje'), [
    [t('Responder'), () => {
      if (!win.opened || !win.draftReady || draftSends.has(draftKey(win.peer))) return;
      win.reply = message; drawWindowContext(win); saveWindowDraft(win); win.node?.querySelector('textarea')?.focus();
    }],
    [t('Copiar'), () => copy(message.visual ? message.caption || '' : message.text || '')],
    [t('Eliminar'), () => attempt(() => api('delete', { peer: win.peer, id: message.id, everyone: false }), queuedNote), 'danger'],
  ], [...new Set([state.settings?.quick_reaction || '👍', ...QUICK])]
    .map(value => [reactionEmoji(value), () => react(message, value, win.peer)]));
  showMessageDates(message, win.peer, win.kind, false);
}
function drawWindowContext(win) {
  const context = win.node?.querySelector('.wincompose .context');
  if (!context) return;
  context.replaceChildren(...(win.reply ? [h('span', {}, t('Respondiendo a') + ' ' + win.reply.sender + ': ' + (win.reply.text || '').replace(/\s+/g, ' ')),
    button('x', () => {
      if (draftSends.has(draftKey(win.peer))) return;
      win.reply = null; drawWindowContext(win); saveWindowDraft(win);
    })] : []),
    ...(win.draft?.files || []).map((file) => h('span', {}, file.name || file)),
    ...((win.draft?.files || []).some(isPhotoAttachment) ? [photoQualityControl(win.draft, value => {
      if (draftSends.has(draftKey(win.peer))) return;
      win.draft = {...win.draft, photo_quality: value};
      saveWindowDraft(win);
    }, draftSends.has(draftKey(win.peer)))] : []));
}
function restoreWindowDraft(win, record) {
  win.draftReady = !!record;
  win.draft = record || emptyDraft();
  win.reply = win.draft.reply ? win.messages.find(item => item.id === win.draft.reply)
    || {id: win.draft.reply, sender: '', text: t('Mensaje')} : null;
  const field = win.node?.querySelector('textarea');
  if (field) {
    if (field.value !== win.draft.text) field.value = win.draft.text;
    field.readOnly = !win.opened || !win.draftReady || draftSends.has(draftKey(win.peer));
  }
  drawWindowContext(win);
}
function saveWindowDraft(win) {
  if (!win.opened || !win.draftReady || win.account !== state.account || !state.windows.includes(win)
      || draftSends.has(draftKey(win.peer))) return Promise.resolve(false);
  const field = win.node?.querySelector('textarea');
  if (!field) return Promise.resolve(true);
  const previous = win.draft || emptyDraft();
  const text = field.value;
  const before = [...previous.text], after = [...text];
  let start = 0, oldEnd = before.length, newEnd = after.length;
  while (start < oldEnd && start < newEnd && before[start] === after[start]) start++;
  while (oldEnd > start && newEnd > start && before[oldEnd - 1] === after[newEnd - 1]) {
    oldEnd--; newEnd--;
  }
  const rebase = (spans) => spans.flatMap(([a, b, ...rest]) => {
    if (b <= start) return [[a, b, ...rest]];
    if (a >= oldEnd) return [[a + newEnd - oldEnd, b + newEnd - oldEnd, ...rest]];
    return [];
  });
  win.draft = {...previous, text, formats: rebase(previous.formats), custom: rebase(previous.custom),
    reply: win.reply?.id ?? null};
  return writeDraft(win.peer, win.draft, {peer: win.peer}, win);
}
async function sendFromWindow(win) {
  const field = win.node?.querySelector('textarea');
  const key = draftKey(win.peer);
  if (!field || !win.opened || !win.draftReady || win.account !== state.account || draftSends.has(key)
      || (!field.value.trim() && !win.draft?.files.length)) return;
  const write = saveWindowDraft(win);
  const {text, reply, files, formats, custom} = win.draft;
  const photo_quality = selectedPhotoQuality(win.draft);
  win.sending = true;
  draftSends.add(key);
  syncDraftReadOnly(win.peer);
  const params = {peer: win.peer, account: win.account, reply_to: reply, spans: formats, custom};
  try {
    if (!(await write) || state.account !== win.account || !state.windows.includes(win)) return;
    const result = await api('window_send', {...params, keys: files.map(file => file.key || file), text, photo_quality});
    if (result && state.account === win.account && state.windows.includes(win)) {
      if (result.forum) { showFloatingForum(win, result.chat); return; }
      state.drafts[win.peer] = emptyDraft();
      restoreWindowDraft(win, state.drafts[win.peer]);
      drawChatList();
    }
  } catch (error) { toast(error.message, 'error'); }
  finally {
    win.sending = false;
    draftSends.delete(key);
    if (win.account === state.account) syncDraftReadOnly(win.peer);
  }
}
function syncDraftReadOnly(peer) {
  const sending = draftSends.has(draftKey(peer));
  for (const win of state.windows) {
    const field = win.peer === peer && win.node?.querySelector('textarea');
    if (field) field.readOnly = !win.opened || !win.draftReady || sending;
    const quality = win.peer === peer && win.node?.querySelector('.photo-quality select');
    if (quality) quality.disabled = sending;
  }
  const field = state.open && composerPeer() === peer && document.getElementById('field');
  if (field) {
    field.readOnly = sending;
    const quality = field.closest('.composer')?.querySelector('.photo-quality select');
    if (quality) quality.disabled = sending;
  }
}
function dragWindow(event, win) {
  if (event.target.closest('button')) return;
  event.preventDefault();
  const bar = event.currentTarget, node = win.node;
  bar.setPointerCapture(event.pointerId);
  const startX = event.clientX - win.x, startY = event.clientY - win.y;
  windowLayer.append(node);  // to the front
  const move = (moved) => {
    win.x = Math.max(-win.w + 80, Math.min(innerWidth - 80, moved.clientX - startX));
    win.y = Math.max(0, Math.min(innerHeight - 40, moved.clientY - startY));
    node.style.left = win.x + 'px'; node.style.top = win.y + 'px';
  };
  bar.addEventListener('pointermove', move);
  const done = () => { bar.removeEventListener('pointermove', move); saveWindows(); };
  bar.addEventListener('pointerup', done, { once: true });
  bar.addEventListener('pointercancel', done, { once: true });
}
function resizeWindow(event, win) {
  event.preventDefault();
  const grip = event.currentTarget, node = win.node;
  grip.setPointerCapture(event.pointerId);
  const move = (moved) => {
    win.w = Math.max(260, Math.min(innerWidth - win.x, moved.clientX - win.x));
    win.h = Math.max(200, Math.min(innerHeight - win.y, moved.clientY - win.y));
    node.style.width = win.w + 'px'; node.style.height = win.h + 'px';
  };
  grip.addEventListener('pointermove', move);
  const done = () => { grip.removeEventListener('pointermove', move); saveWindows(); };
  grip.addEventListener('pointerup', done, { once: true });
  grip.addEventListener('pointercancel', done, { once: true });
}
function restoreWindows() {
  if (state.windowsRestored) return;
  state.windowsRestored = true;
  for (const item of (state.appearance || {}).windows || []) {
    if (item.account === state.account) openWindow({ id: item.peer, name: item.name }, item.docked, item);
  }
}

// one picture from the gallery (backgrounds) -----------------------------------------
async function pickImage() {
  const file = await pickOnePhoto();
  return file?.key || null;
}

async function chooseBackground(target, sync = '') {
  const account = state.account, revision = state.accountRevision;
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  let key;
  try { key = await pickImage(); } catch (error) { if (current()) toast(error.message, 'error'); return; }
  if (!key) return;
  if (!current()) { api('discard_files', {keys: [key]}).catch(() => {}); return; }
  toast(t('Cargando...'));
  try {
    const look = await api('set_background', {key, target, sync, account});
    if (current()) { state.appearance = look; applySettings(); if (state.view === 'settings') render(); }
  } catch (error) { if (current()) toast(error.message, 'error'); }
}
// Where a new background applies: this device, all your devices, or (private chats) also the other person.
function backgroundSync(done, general = false, chat = null) {
  const items = [[t('Only on this device'), () => done('')],
    [general ? t('On all my TG-ASCII devices') : t('On all my devices (Telegram)'), () => done('devices')]];
  if (chat && chat.kind === 'user' && !chat.self) items.push([t('Also for {name}').replace('{name}', chat.name), () => done('both')]);
  sheet(t('Background'), items);
}

function chatBackgroundMenu(chat) {
  openWallpaperMenu(chat);
}

function appearanceSection(save) {
  const settings = state.settings, look = state.appearance || {};
  const theme = document.documentElement.dataset.theme || 'dark';
  const color = (key, label, fallback) => h('div', { class: 'setting' }, h('span', {}, label),
    h('input', { type: 'color', 'aria-label':label,
      value: settings[key] || getComputedStyle(document.documentElement).getPropertyValue('--' + fallback).trim() || PALETTES[theme][fallback],
      onchange: (event) => save({ [key]: event.target.value }) }),
    settings[key] ? button('x', () => save({ [key]: '' })) : null);
  const slider = (key, label) => h('div', {class: 'setting effect-setting'}, h('span', {}, label),
    numericSlider(label, settings[key] || 0, 0, settings.radius_max || 48, value => save({[key]: value}), 48));
  const choices = [['', t('Default')], ['courier', 'Courier'], ['sans', 'Sans'], ['serif', 'Serif'], ['system', t('Sistema')],
    ['rounded', 'Rounded'], ['humanist', 'Trebuchet / Roboto'], ['classic', 'Palatino'], ['book', 'Georgia'], ['mono', 'Monospace']];
  if (PLATFORM === 'iOS' || MAC || PLATFORM === 'macOS') choices.push(...APPLE_FONTS.map(appleFontLabel));
  else if (PLATFORM === 'Android') choices.push(...ANDROID_FONTS);
  // A choice made on another device stays selected and named here.
  if (look.font && !choices.some(([value]) => value === look.font)) {
    const known = [...APPLE_FONTS, ...ANDROID_FONTS].find(([value]) => value === look.font);
    if (known) choices.push(known);
  }
  const fonts = h('select', {'aria-label': t('Typeface'), onchange: event => saveLook({font: event.target.value})},
    choices.map(([value, text]) => h('option', {value, selected: (look.font || '') === value,
      style: 'font-family:' + (FONTS[value] || 'inherit')}, text)));
  const brightness = numericSlider(t('Brightness'), 100 - Number(look.dim ?? 55), 0, 100, value => saveLook({dim: 100 - value}));
  return {
    colors: [color('text_color', t('Text color'), 'text'), color('background_color', t('Background color'), 'bg'), color('accent_color', t('Accent color'), 'strong'),
      color('bubble_in_color', t('Color de burbujas recibidas'), 'panel'),
      color('bubble_out_color', t('Color de burbujas enviadas'), 'selected')],
    corners: [slider('bubble_radius', t('Bubble corners')), slider('button_radius', t('Button corners')), slider('menu_radius', t('Menu corners'))],
    typeface: h('div', { class: 'setting' }, h('span', {}, t('Typeface')), fonts),
    backgrounds: [
      h('div', { class: 'setting' }, h('span', {}, t('All chats in this app')),
        button(t('Chat background'), () => openWallpaperMenu(null))),
      switchSetting(t('Use Telegram chat backgrounds when available'), !!look.chat_wallpapers?._follow,
        () => setWallpaperFollowing(!look.chat_wallpapers?._follow)),
      h('div', { class: 'setting' }, h('span', {}, t('Interface background image')),
        button(t('Image'), () => backgroundSync((sync) => chooseBackground('interface', sync), true)),
        look.background ? button(t('Remove'), () => attempt(() => api('clear_background'), (result) => { state.appearance = result; applySettings(); render(); }), 'danger') : null),
      look.background ? h('div', { class: 'setting' }, h('span', {}, t('Brightness')), brightness) : null,
      switchSetting(t('Sync the background with my other TG-ASCII devices'), look.background_sync, () => saveLook({ background_sync: !look.background_sync })),
      h('div', { class: 'muted small' }, t('Chat backgrounds: ⋯ in each chat › Chat background. They can stay on this device, appear on all your devices, or also for the other person.'))],
    view: h('div', { class: 'setting' }, h('span', {}, t('View')), h('select', { onchange: (event) => saveLook({ layout: event.target.value }) },
      [['auto', t('Automatic')], ['single', t('Single view')], ['double', t('Double view')]].map(([value, label]) =>
        h('option', { value, selected: (look.layout || 'auto') === value }, label)))),
    reset: button(t('Reset panel sizes'), () => {
      state.windows.forEach((win, index) => Object.assign(win, defaultGeometry(index)));
      saveLook({ side_width: 0, windows: state.windows.map((win) => ({ peer: win.peer, name: win.name, docked: win.docked, x: win.x, y: win.y, w: win.w, h: win.h })) });
    }),
  };
}

// Confirm / ask for text inside the app: WebViews do not show prompt() / confirm().
function confirmThen(text, action, kind = 'danger', native = true) {
  if (native && window.tgNativeDialogs?.confirm(text, action, kind, () => confirmThen(text, action, kind, false))) return;
  sheet(text, [[t('Confirm'), action, kind]], null, false);
}
function promptThen(title, options, action, native = true) {
  if (native && window.tgNativeDialogs?.prompt(title, options, action, () => promptThen(title, options, action, false))) return;
  const input = h('input', { type: options.type || 'text', value: options.value || '', maxlength: options.maxlength || null, placeholder: options.placeholder || '',
    autocomplete: 'off', inputmode: options.inputmode || null });
  formSheet(title, [input, options.note ? h('div', { class: 'muted small' }, options.note) : null].filter(Boolean),
    options.submit || t('Continuar'), () => action(input.value));
}
// Marks that a system screen (picker, viewer, other app) is about to cover ours.
function keepUnlocked(seconds = 120) {
  state.keepUnlocked = true;
  clearTimeout(state.keepTimer);
  state.keepTimer = setTimeout(() => { state.keepUnlocked = false; }, seconds * 1000);
  api('expect_external', { seconds }).catch(() => {});
}

// forms in a sheet ---------------------------------------------------------------------
function formSheet(title, nodes, submitLabel, submit) {
  const layer = document.getElementById('sheet-layer');
  let panel;
  const run = async () => {
    const ok = await submit();
    if (ok !== false && currentSheetPanel === panel) closeSheet();
  };
  layer.replaceChildren(h('div', { class: 'sheet form', onclick: (event) => event.stopPropagation() },
    h('h3', {}, title), ...nodes,
    h('div', { class: 'actions' }, button(submitLabel, run, 'primary'), button(t('Cancelar'), closeSheet))));
  activateSheet(layer);
  panel = currentSheetPanel;
  layer.onclick = closeSheet;
  layer.querySelector('input')?.focus();
}
const labelled = (label, input) => h('label', { class: 'field wide' }, h('span', {}, label), input);
const check = (label, checked = false) => {
  const input = h('input', { type: 'checkbox' }); input.checked = checked;
  return [h('label', { class: 'check' }, input, h('span', {}, label)), input];
};

function pollSheet() {
  const open = state.open;
  const destination = sendDestination(open);
  const question = h('input', {type: 'text', maxlength: 300});
  const answers = h('div', {class: 'answers'});
  const options = [];
  const [quizRow, quiz] = check(t('Quiz'));
  const [anonymousRow, anonymous] = check(t('Anonymous votes'), true);
  const [multipleRow, multiple] = check(t('Multiple answers'));
  const [openRow, openAnswers] = check(t('Participants can add answers'));
  const [revotingRow, revoting] = check(t('Allow changing the vote'), true);
  const [shuffleRow, shuffle] = check(t('Shuffle answer order'));
  const [hiddenRow, hidden] = check(t('Hide results until the poll closes'));
  const [subscribersRow, subscribers] = check(t('Only eligible subscribers can vote'));
  const explanation = h('textarea', {maxlength: 200, rows: 2});
  const files = {};
  const attachment = (slot) => {
    const name = h('span', {}, t('Attachment'));
    const removeFile = button(t('Remove file'), () => {
      if (!files[slot]) return;
      api('discard_files', {keys: [files[slot]]}).catch(() => {});
      delete files[slot];
      name.textContent = t('Attachment');
      removeFile.hidden = true;
    });
    removeFile.hidden = true;
    return h('div', {class: 'actions'}, name, button(t('Choose file'), () => {
      chooseFiles('media', {limit: 1, accept: '.jpg,.jpeg,.png,.mp4', receive: ([file]) => {
        if (!file || !name.isConnected) return;
        if (files[slot]) api('discard_files', {keys: [files[slot]]}).catch(() => {});
        files[slot] = file.key;
        name.textContent = file.name;
        removeFile.hidden = false;
      }});
    }), removeFile);
  };
  const explanationRow = h('div', {}, labelled(t('Quiz explanation'), explanation), attachment('solution_media'));
  const countries = h('input', {type: 'text'});
  const duration = h('input', {type: 'number', min: 5, step: 1});
  const add = button(t('Add answer'), addAnswer);
  const remove = button(t('Remove last answer'), () => {
    if (options.length <= 2) return;
    options.pop().row.remove();
    refresh();
  });
  function addAnswer() {
    if (options.length >= 12) return;
    const label = t('Answer') + ' ' + (options.length + 1);
    const input = h('input', {type: 'text', maxlength: 100, placeholder: label, 'aria-label': label});
    const [correctRow, correct] = check(t('Correct answer'));
    const row = h('div', {}, input, correctRow);
    options.push({row, input, correctRow, correct});
    answers.append(row);
    refresh();
  }
  function refresh() {
    for (const {correctRow} of options) correctRow.hidden = !quiz.checked;
    explanationRow.hidden = !quiz.checked;
    openRow.hidden = revotingRow.hidden = quiz.checked;
    remove.disabled = options.length <= 2;
    add.disabled = options.length >= 12;
  }
  quiz.addEventListener('change', refresh);
  addAnswer();
  addAnswer();
  let submitting = false;
  formSheet(t('Poll'), [labelled(t('Question'), question), attachment('attached_media'), quizRow, answers,
    h('div', {class: 'actions'}, add, remove), explanationRow, anonymousRow, multipleRow,
    h('details', {}, h('summary', {}, t('More options')), openRow, revotingRow, shuffleRow, hiddenRow,
      subscribersRow, labelled(t('Allowed country codes, comma-separated (optional)'), countries),
      labelled(t('Close after this many seconds (optional)'), duration))], t('Create'), async () => {
    if (submitting || state.uploading || state.open !== open) return false;
    submitting = true;
    try {
      const attachments = {...files};
      if (!quiz.checked) delete attachments.solution_media;
      const result = await attempt(() => api('send_poll', {...destination, question: question.value,
        answers: options.map(({input}) => input.value.trim()),
        quiz: quiz.checked, correct: options.flatMap(({correct}, index) => correct.checked ? [index] : []),
        solution: explanation.value, anonymous: anonymous.checked, multiple: multiple.checked,
        open_answers: !quiz.checked && openAnswers.checked, revoting: !quiz.checked && revoting.checked,
        shuffle: shuffle.checked, hidden_results: hidden.checked, subscribers_only: subscribers.checked,
        countries: countries.value.split(',').map((value) => value.trim()).filter(Boolean),
        close_period: duration.value ? Number(duration.value) : null, files: attachments}));
      if (!result || state.open !== open) return false;
      if (result.message) EVENTS.message({peer: open.peer, message: result.message});
      consumeReply(open, destination.reply_to);
      queuedNote(result);
    } finally { submitting = false; }
  });
}

async function shareContactSheet() {
  const open = state.open;
  const destination = sendDestination(open);
  const sendCard = (first, last, phone) => {
    if (state.open !== open) return;
    return attempt(() => api('send_contact', {...destination, first, last, phone}), (result) => {
      consumeReply(open, destination.reply_to);
      queuedNote(result);
    });
  };
  const manual = () => {
    const first = h('input', { type: 'text' }), last = h('input', { type: 'text' }), phone = h('input', { type: 'tel', placeholder: '+34…' });
    formSheet(t('Share contact'), [labelled(t('First name'), first), labelled(t('Last name'), last), labelled(t('Phone number'), phone)],
      t('Enviar'), async () => (await sendCard(first.value, last.value, phone.value)) ? true : false);
  };
  const revision = state.accountRevision;
  if (state.contacts === null) await loadContacts();
  if (state.accountRevision !== revision || state.locked || state.open !== open) return;
  const people = (state.contacts || []).filter((item) => item.phone);
  sheet(t('Share contact'), [[t('First name') + ' / ' + t('Phone number') + '…', manual],
    ...people.map((item) => [item.name + ' · +' + item.phone, () => sendCard(item.first || item.name, item.last || '', item.phone)])]);
}

async function chooseFiles(kind, {receive = addAttachments, limit = 10 - state.attachments.length, accept = null} = {}) {
  const open = state.open, revision = state.accountRevision, panel = currentSheetPanel;
  const current = () => state.open === open && revision === state.accountRevision && !state.locked &&
    (receive === addAttachments || !panel || currentSheetPanel === panel);
  const discard = files => files?.length && api('discard_files', {keys: files.map(file => file.key)}).catch(() => {});
  if (open?.sending) return;
  const received = files => {
    if (receive === addAttachments && files?.length) {
      if (kind === 'any') state.photo_quality = 'original';
      else if (!state.attachments.length) state.photo_quality = selectedPhotoQuality(state);
    }
    receive(files);
  };
  keepUnlocked(120);
  if (PLATFORM === 'Android') {
    state.uploading += 1; drawAttachments();
    try {
      const files = await api('pick_files', {kind});
      const keep = current() ? (files || []).slice(0, limit) : [];
      discard((files || []).slice(keep.length));
      if (current()) received(keep);
    }
    catch (error) { toast(error.message, 'error'); }
    finally { state.uploading -= 1; drawAttachments(); }
    return;
  }
  const camera = kind === 'camera';
  const input = h('input', { type: 'file', multiple: !camera && limit > 1, hidden: true,
    accept: accept || (camera ? 'image/*' : ['media', 'gallery'].includes(kind) ? 'image/*,video/*' : null),
    capture: camera && !MAC ? 'environment' : null });
  input.addEventListener('cancel', () => input.remove(), {once: true});
  input.addEventListener('change', async () => {
    if (!current()) { input.remove(); return; }
    const files = [...input.files].slice(0, limit);
    input.remove();
    for (const file of files) {
      if (!current()) break;
      state.uploading += 1; drawAttachments();
      try {
        const response = await fetch('/upload?' + resourceAuth() + '&name=' + encodeURIComponent(file.name),
          { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        if (current()) received([{...data.result,
          preview: receive === addAttachments && file.type.startsWith('image/') ? URL.createObjectURL(file) : null}]);
        else discard([data.result]);
      } catch (error) { toast(error.message, 'error'); }
      finally { state.uploading -= 1; drawAttachments(); }
    }
  });
  document.body.append(input);
  input.click();
}

function addAttachments(files) {
  for (const file of files || []) if (state.attachments.length < 10) state.attachments.push(file);
  drawAttachments(); saveDraft();
}

function humanSize(bytes) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes, unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return (unit ? value.toFixed(1) : value) + ' ' + units[unit];
}

const PHOTO_QUALITY_CHOICES = [['sd', 'SD · Standard'], ['hd', 'HD · High quality'], ['original', 'Original as file']];
const selectedPhotoQuality = record => PHOTO_QUALITY_CHOICES.some(([value]) => value === record?.photo_quality)
  ? record.photo_quality : 'sd';
const isPhotoAttachment = file => /\.(jpe?g|png|webp)$/i.test(typeof file === 'string' ? file : file.name || file.key || '');
function photoQualityControl(record, changed, disabled = false) {
  const select = h('select', {'aria-label': t('Photo quality'), disabled,
    onchange: event => changed(event.target.value)}, PHOTO_QUALITY_CHOICES.map(([value, label]) =>
      h('option', {value}, t(label))));
  select.value = selectedPhotoQuality(record);
  return h('label', {class: 'photo-quality'}, h('span', {}, t('Photo quality') + ' '), select);
}

function drawAttachments() {
  const box = document.getElementById('attachments');
  if (!box) return;
  box.replaceChildren(...state.attachments.map((file, index) => h('div', { class: 'chip' },
    file.preview ? h('img', { src: file.preview, alt: '' }) : null,
    h('span', {}, file.name + ' · ' + humanSize(file.size)),
    button('x', () => {
      if (state.open?.sending) return;
      const removed = state.attachments.splice(index, 1)[0];
      if (removed.preview?.startsWith('blob:')) URL.revokeObjectURL(removed.preview);
      drawAttachments(); saveDraft();
    }))),
    ...(state.uploading ? [h('div', { class: 'chip' }, h('span', { class: 'spinner' }, t('Enviando...') + ' '))] : []),
    ...(state.attachments.some(isPhotoAttachment) ? [photoQualityControl(state, value => {
      if (state.open?.sending) return;
      state.photo_quality = value; saveDraft();
    }, !!state.open?.sending)] : []));
  composerMode();
}

async function send(options = {}) {
  const field = document.getElementById('field');
  const open = state.open;
  if (!field || !open || open.sending || state.uploading) return;
  const peer = composerPeer(open), key = draftKey(peer), account = state.account;
  if (draftSends.has(key)) return;
  const text = field.value;
  if (!text.trim() && !state.attachments.length) return;
  if (state.editing) {
    const target = state.editing;
    const result = await attempt(() => api('edit', {peer: open.peer, id: target.id, text}), queuedNote);
    if (result !== undefined && state.open === open && state.editing === target) {
      state.editing = null;
      restoreComposer(field, state.drafts[composerPeer(open)]);
    }
    return;
  }
  const write = saveDraft();
  open.sending = true;
  draftSends.add(key);
  syncDraftReadOnly(peer);
  const {formats, custom, reply, files, photo_quality} = draftContents(composerPeer(open), text);
  const params = {peer: open.peer, account: state.account, reply_to: reply, thread_root: open.thread?.root, topic_id: open.topic?.id, ...options};
  try {
    if (!(await write) || state.open !== open) return;
    const result = files.length
      ? await api('send_files', {...params, keys: files, caption: text, spans: formats, custom, photo_quality})
      : await api('send', {...params, text, spans: formats, custom});
    if (result && state.open === open) {
      for (const file of state.attachments) if (file.preview?.startsWith('blob:')) URL.revokeObjectURL(file.preview);
      state.drafts[peer] = emptyDraft();
      restoreComposer(document.getElementById('field'), state.drafts[peer]);
      drawChatList();
      if (options.schedule) toast(t('Schedule message') + ' ✓');
    }
  } catch (error) { toast(error.message, 'error'); }
  finally {
    open.sending = false;
    draftSends.delete(key);
    if (state.account === account) syncDraftReadOnly(peer);
  }
}

// Stickers and custom emoji (desktop: sticker_picker.open_picker): packs, recent,
// search by name / keyword / emoji, send or insert, view and save a pack.
function stickerPicker(custom, onChoose = null) {
  const open = state.open, revision = state.accountRevision;
  if (!open && !onChoose) return;
  const layer = document.getElementById('sheet-layer');
  const search = h('input', { type: 'search', placeholder: t('Search packs, keywords or an emoji') });
  const chooser = h('select', {});
  const status = h('div', { class: 'muted small' }, t('Cargando...'));
  const grid = h('div', { class: 'sticker-grid' + (custom ? ' emoji' : '') });
  const current = () => grid.isConnected && !layer.hidden && !state.locked && revision === state.accountRevision;
  const more = button(t('More'), () => runSearch(true)); more.hidden = true;
  let packs = [], choices = [], results = [], next = null, timer = null, version = 0;
  const use = (doc) => {
    if (!current()) return;
    if (!onChoose && state.open !== open) return;
    if (doc.standard) {  // a standard emoji from "Recently used"
      if (onChoose) return;
      const field = document.getElementById('field');
      const at = field.selectionStart ?? field.value.length;
      field.value = field.value.slice(0, at) + doc.emoji + field.value.slice(field.selectionEnd ?? at);
      field.dispatchEvent(new Event('input')); closeSheet(); field.focus();
      return;
    }
    if (onChoose) { closeSheet(); onChoose(doc); return; }
    if (custom) {
      const field = document.getElementById('field');
      insertDraftEmoji(field, doc);
      closeSheet(); field.focus();
    } else {
      const destination = sendDestination(open);
      closeSheet();
      attempt(() => api('send_sticker', {...destination, id: doc.id}), () => consumeReply(open, destination.reply_to));
    }
  };
  const cell = (doc) => {
    if (doc.standard) return h('button', { class: 'sticker-cell standard-emoji', title: doc.emoji, onclick: () => use(doc) }, doc.emoji);
    let timer = null, held = false;
    return h('button', { class: 'sticker-cell', title: doc.emoji,
      onclick: () => { if (!held) use(doc); },
      oncontextmenu: (event) => { event.preventDefault(); packView(doc, custom); },
      ontouchstart: () => { held = false; timer = setTimeout(() => { held = true; packView(doc, custom); }, 500); },
      ontouchend: () => clearTimeout(timer), ontouchmove: () => clearTimeout(timer) },
      (() => {
        const img = h('img', { src: stickerUrl(doc.id), alt: doc.emoji, onerror: (event) => {
          const img = event.target;  // one retry (first downloads of a pack can queue)
          if (!img.dataset.retried) { img.dataset.retried = 1; setTimeout(() => { if (current() && img.isConnected) img.src = stickerUrl(doc.id) + '&r=1'; }, 1500); }
          else img.replaceWith(doc.emoji);
        } });
        if (doc.animated || doc.video) animated(img, doc.id);
        return img;
      })());
  };
  const show = (docs) => {
    grid.replaceChildren(...docs.map(cell));
    status.textContent = docs.length + ' · ' + t(custom ? 'Custom emoji' : 'Stickers');
  };
  // Like Telegram: open on the recent / most used ones, then favourites, then each pack.
  const SPECIAL = { recent_emoji: 'Recent', favourites: 'Favorites' };
  const options = (list, searching) => {
    choices = (searching ? [null] : custom ? ['recent_emoji'] : [null, 'favourites']).concat(list);
    chooser.replaceChildren(...choices.map((pack, i) => h('option', { value: i },
      pack === null ? t(searching ? 'Search results' : 'Recent') : typeof pack === 'string' ? t(SPECIAL[pack]) : pack.title)));
  };
  const change = () => {
    if (!current()) return;
    const pack = choices[Number(chooser.value) || 0];
    if (pack === undefined) return show([]);
    if (pack === null && search.value.trim()) { show(results); more.hidden = next === null; return; }
    const mine = ++version; status.textContent = t('Cargando...'); more.hidden = true;
    api('sticker_documents', { pack: pack === null ? null : typeof pack === 'string' ? pack : pack.id }).then((docs) => {
      if (mine !== version || !current()) return;
      // Nothing used yet: start on the first pack instead of an empty page.
      if (!docs.length && typeof pack === 'string' && pack === 'recent_emoji' && choices.length > 1) { chooser.value = 1; change(); return; }
      show(docs);
    },
      () => { if (mine === version) status.textContent = t('Search failed.'); });
  };
  const runSearch = (page = false) => {
    if (!current()) return;
    const value = search.value.trim();
    if (!value) { options(packs, false); change(); return; }
    const mine = ++version; status.textContent = t('Cargando...');
    api('sticker_search', { query: value, custom, offset: page ? next : 0 }).then((found) => {
      if (mine !== version || !current()) return;
      results = page ? results.concat(found.documents) : found.documents; next = found.next;
      if (!page) options(found.packs, true);
      show(results); more.hidden = next === null;
    }, () => { if (mine === version) status.textContent = t('Search failed.'); });
  };
  search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => runSearch(false), 350); };
  chooser.onchange = change;
  layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
    onChoose ? h('h3', {}, t(custom ? 'Custom emoji' : 'Stickers')) : h('div', { class: 'tabs' },
      h('button', { class: 'tab' + (custom ? ' on' : ''), onclick: () => { if (!custom) stickerPicker(true); } }, t('Custom emoji')),
      h('button', { class: 'tab' + (custom ? '' : ' on'), onclick: () => { if (custom) stickerPicker(false); } }, t('Stickers'))),
    search, chooser, status, grid, more,
    custom ? h('div', { class: 'muted small' }, t('Some emoji require Telegram Premium.')) : null,
    h('button', { class: 'item', onclick: closeSheet }, t('Cancelar'))));
  activateSheet(layer); layer.onclick = closeSheet;
  if (currentSheetPanel) currentSheetPanel.onDismiss = () => {clearTimeout(timer); version++;};
  api('sticker_packs', { custom }).then((list) => { if (!current()) return; packs = list; options(packs, false); change(); },
    () => { status.textContent = t('Search failed.'); });
}

// The pack of a sticker / custom emoji, with Save pack (desktop: show_pack).
function packView(doc, custom) {
  const open = state.open, revision = state.accountRevision;
  const layer = document.getElementById('sheet-layer');
  const status = h('div', { class: 'muted small' }, t('Cargando...'));
  const grid = h('div', { class: 'sticker-grid' + (custom ? ' emoji' : '') });
  const save = button(t('Save pack'), () => {}, 'primary'); save.hidden = true;
  layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('View pack')), status, grid, save, h('button', { class: 'item', onclick: closeSheet }, t('Cancelar'))));
  activateSheet(layer); layer.onclick = closeSheet;
  api('sticker_pack_of', { id: doc.id }).then((data) => {
    if (!grid.isConnected || layer.hidden || state.locked || revision !== state.accountRevision) return;
    status.textContent = data.pack.title + ' · ' + data.documents.length + ' · ' + t(data.pack.emoji ? 'Custom emoji' : 'Stickers');
    const use = (item) => {
      if (!open || state.open !== open) return;
      closeSheet();
      if (data.pack.emoji) {
        const field = document.getElementById('field');
        if (!field) return;
        insertDraftEmoji(field, item);
      } else {
        const destination = sendDestination(open);
        attempt(() => api('send_sticker', {...destination, id: item.id}), () => consumeReply(open, destination.reply_to));
      }
    };
    grid.replaceChildren(...data.documents.map((item) => h('button', { class: 'sticker-cell', title: item.emoji, onclick: () => use(item) },
      (() => { const img = h('img', { src: stickerUrl(item.id), alt: item.emoji, loading: 'eager' }); if (item.animated || item.video) animated(img, item.id); return img; })())));
    save.textContent = t(data.installed ? 'Pack saved' : 'Save pack'); save.disabled = data.installed; save.hidden = false;
    save.onclick = () => attempt(() => api('install_pack', { id: data.pack.id }), (result) => {
      save.textContent = t('Pack saved'); save.disabled = true;
      if (result.archived) toast(t('Telegram archived older packs to make room for this pack.'));
    });
  }, (error) => { status.textContent = error.message || t('Pack unavailable.'); });
}

function react(message, value, peer = state.open?.peer) {
  if (peer != null) return attempt(() => api('react', {peer, id: message.id, value}), queuedNote);
}

function startReply(message) {
  if (state.editing) restoreComposer(document.getElementById('field'), state.drafts[composerPeer()]);
  state.editing = null; state.reply = message; drawContext(); saveDraft();
  document.getElementById('field')?.focus();
}

// Long press does not select text; this sheet shows it selectable (desktop: copy / select).
function selectTextSheet(message) {
  const area = h('textarea', { readonly: true, rows: 10, class: 'select-text' }); area.value = message.text || '';
  formSheet(t('Select text'), [area], t('Copy text'), async () => {
    const start = area.selectionStart, end = area.selectionEnd;
    await copy(end > start ? area.value.slice(start, end) : area.value);
  });
  setTimeout(() => { area.focus(); area.setSelectionRange(0, 0); }, 50);
}

function messageMenu(message) {
  const isSecret = state.open && state.open.chat && state.open.chat.kind === 'secret';
  const items = [
    [t('Responder'), () => startReply(message)],
    [t('Copy text'), () => copy(message.text)],
    [t('Select text'), () => selectTextSheet(message)],
  ];
  if (message.kind === 'sticker' && message.sticker_id) items.push([t('View pack'), () => packView({ id: message.sticker_id }, false)]);
  if (!isSecret && !message.service && (message.visual ? message.caption : message.text) && message.kind !== 'poll') items.push(
    [t('Translation'), () => translateMessage(message)], [t('Summarize with Telegram AI'), () => summarizeMessage(message)]);
  if (!isSecret && (message.voice || message.round)) items.push([t('Transcribe audio'), () => transcribeMessage(message)]);
  if (message.kind && !message.service && message.kind !== 'poll') items.push(
    [t('Open'), () => openFile(message)], [t('Save'), () => openFile(message, state.open.peer, 'save')],
    [t('Share'), () => openFile(message, state.open.peer, 'share')]);
  if (!isSecret && message.out && !message.service) items.push([t('Editar'), () => {
    state.reply = null; state.editing = message;
    const field = document.getElementById('field'); field.value = message.text; field.focus(); drawContext();
  }]);
  const links = (message.text || '').match(LINK) || [];
  if (links.length) {
    const url = /^https?:/i.test(links[0]) ? links[0] : 'https://' + links[0];
    items.push([t('Open link'), () => openUrl(url)], [t('Copy link'), () => copy(url)]);
  }
  const thread = state.open.thread;
  if (thread) {
    const source = String(thread.source);
    const location = thread.channel.username || (source.startsWith('-100') ? 'c/' + source.slice(4) : '');
    if (location) {
      const url = 'https://t.me/' + location + '/' + thread.post + (message.id === thread.root ? '' : '?comment=' + message.id);
      items.push([t('Copy link'), () => copy(url)]);
    }
  }
  if (!isSecret && !message.protected) items.push([t('Reenviar'), () => chooseForwardTarget({peer: state.open.peer, id: message.id})],
    [t('Save to Saved Messages'), () => attempt(() => api('save_to_saved', { peer: state.open.peer, id: message.id }), (result) => {
      if (result && result.queued) queuedNote(result); else toast(t('Saved.'));
    })]);
  if (!isSecret) items.push([t('Fijar'), () => attempt(() => api('pin_message', { peer: state.open.peer, id: message.id }), queuedNote)]);
  if (!isSecret && !message.out && !message.service)
    items.push([t('Denunciar mensaje'), () => reportMessage(state.account, state.open.peer, message.id)]);
  items.push([t('Select'), () => toggleSelected(message)]);
  if (!isSecret) items.push([t('Reactions'), () => reactionPicker(message)]);
  items.push([t('Eliminar'), () => remove(message, false), 'danger']);
  if (message.out || state.open.chat.kind !== 'user') items.push([t('Eliminar para todos'), () => remove(message, true), 'danger']);
  sheet(t('Mensaje'), items, isSecret ? [] : QUICK.map((emoji) => [emoji, () => react(message, emoji)]));
  showMessageDates(message, state.open.peer, state.open.chat.kind, state.open.chat.self || state.open.isSelf);
}

async function reportMessage(account, peer, id, option = '', comment = '') {
  if (account !== state.account || state.locked) return;
  const result = await attempt(() => api('report_message', {account, peer, id, option, comment}));
  if (!result || state.account !== account || state.locked) return;
  if (result.reported) { closeSheet(); toast(t('Denuncia enviada a Telegram.')); }
  else if (result.options) {
    sheet(result.title || t('Denunciar mensaje'), result.options.map(item =>
      [item.text, () => reportMessage(account, peer, id, item.option)]));
  } else if (result.comment) {
    const field = h('textarea', {maxlength: 1024, placeholder: t('Comentario'), 'aria-label': t('Comentario')});
    formSheet(t('Denunciar mensaje'), [field], t('Enviar'), async () => {
      if (!field.value.trim() && !result.optional) { field.focus(); return false; }
      await reportMessage(account, peer, id, result.option, field.value.trim());
      return false;
    });
  }
}

async function reactionPicker(message) {
  const revision = state.accountRevision, open = state.open;
  const current = () => revision === state.accountRevision && open === state.open && !state.locked;
  const reactHere = value => current() && react(message, value, open.peer);
  const data = await attempt(() => api('reactions', { peer: open.peer, id: message.id }));
  if (!data || !current()) return;
  sheet(t('Reactions'), [], data.standard.map((emoji) => [emoji, () => reactHere(emoji)]));
  // Custom emoji reactions (Telegram Premium): recent ones, and any custom emoji.
  const panel = document.querySelector('#sheet-layer .sheet');
  if (!panel) return;
  const row = h('div', { class: 'quick custom-reactions' }, (data.custom || []).map((id) =>
    h('button', { onclick: () => { closeSheet(); reactHere(id); } }, customEmoji(id, '◆', false))),
    h('button', { title: t('Custom emoji'), onclick: () => stickerPicker(true, (doc) => reactHere(doc.id)) }, '+'));
  panel.insertBefore(row, panel.querySelector('.item'));
}

function remove(message, everyone) {
  attempt(() => api('delete', { peer: state.open.peer, id: message.id, everyone }), queuedNote);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const area = h('textarea', {}, text); document.body.append(area); area.select();
    document.execCommand('copy'); area.remove();
  }
  toast(t('Copiado.'));
}

function chooseForwardTarget(payload) {
  state.forwarding = {account: state.account, ...payload};
  go('forward', {search: ''});
}

async function forwardTo(chat, topic_id = null) {
  const request = state.forwarding;
  if (state.view !== 'forward' || !request || request.account !== state.account || state.locked) return;
  if (chat.forum && topic_id === null) {
    return chooseForumTarget(chat, topic => {
      if (state.forwarding === request && state.account === request.account) forwardTo(chat, topic.id);
    });
  }
  state.forwarding = null;
  back();
  if (request.people) {
    return attempt(() => api('share_contacts', {...request, target: chat.id, topic_id}), () => toast(t('Contact shared.')));
  }
  return attempt(() => api(request.ids ? 'forward_many' : 'forward', {...request, destination: chat.id, topic_id}), (result) => {
    if (result && result.queued) queuedNote(result); else toast(t('Enviado.'));
  });
}

// sheets ---------------------------------------------------------------------------
let sheetReturnFocus = null, currentSheetPanel = null;
function activateSheet(layer) {
  const previous = currentSheetPanel;
  const replacing = !!previous || layer.classList.contains('closing-sheet');
  layer.classList.remove('closing-sheet');
  layer.inert = false;
  if (previous && previous !== layer.firstElementChild) previous.onDismiss?.();
  currentSheetPanel = layer.firstElementChild;
  if (state.locked || unavailableWindow()) {
    layer.replaceChildren();
    closeSheet(true);
    return;
  }
  if (layer.hidden) sheetReturnFocus = document.activeElement;
  const panel = layer.firstElementChild;
  const title = panel.querySelector('h3');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  if (title) {
    title.id = 'sheet-title';
    panel.setAttribute('aria-labelledby', title.id);
  }
  panel.tabIndex = -1;
  layer.hidden = false;
  panel.focus({ preventScroll: true });
  if (!previous || previous.querySelector('h3')?.textContent !== title?.textContent) animateSurface(panel, replacing ? 'forward' : 'sheet');
  document.getElementById('app').inert = true;
  layer.onkeydown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      layer.click();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = [...panel.querySelectorAll('button, a[href], input, textarea, select, [tabindex]')]
      .filter((item) => item.tabIndex >= 0 && !item.matches(':disabled') && item.getClientRects().length);
    const current = items.indexOf(document.activeElement);
    if (current === -1 || (event.shiftKey ? current === 0 : current === items.length - 1)) {
      event.preventDefault();
      (items[event.shiftKey ? items.length - 1 : 0] || panel).focus();
    }
  };
}

function sheet(title, items, quick = null, native = true) {
  if (native && window.tgNativeDialogs?.menu(title, items, quick, () => sheet(title, items, quick, false))) return;
  const layer = document.getElementById('sheet-layer');
  const panel = h('div', { class: 'sheet', onclick: (event) => event.stopPropagation() }, h('h3', {}, title));
  if (quick) panel.append(h('div', { class: 'quick' }, quick.map(([label, action]) =>
    h('button', { onclick: () => { closeSheet(); action(); } }, label))));
  for (const [label, action, kind] of items) panel.append(h('button', { class: 'item' + (kind ? ' ' + kind : ''),
    onclick: () => { closeSheet(); action(); } }, label));
  panel.append(h('button', { class: 'item', onclick: closeSheet }, t('Cancelar')));
  layer.replaceChildren(panel);
  activateSheet(layer);
  layer.onclick = closeSheet;
}
function closeSheet(immediate = false) {
  window.tgNativeDialogs?.cancel();
  const layer = document.getElementById('sheet-layer');
  if (layer.hidden) {
    if (immediate === true && layer.classList.contains('closing-sheet')) {
      layer.classList.remove('closing-sheet');
      layer.replaceChildren();
    }
    return;
  }
  const dismissed = currentSheetPanel;
  currentSheetPanel = null;
  layer.hidden = true;
  layer.inert = true;
  dismissed?.onDismiss?.();
  document.getElementById('app').inert = false;
  if (sheetReturnFocus?.isConnected) sheetReturnFocus.focus({ preventScroll: true });
  sheetReturnFocus = null;
  if (immediate === true || !dismissed) { layer.replaceChildren(); return; }
  layer.classList.add('closing-sheet');
  animateSurface(dismissed, 'sheet', true, () => {
    if (layer.hidden && layer.firstElementChild === dismissed) {
      layer.classList.remove('closing-sheet');
      layer.replaceChildren();
    }
  });
}

// contacts ---------------------------------------------------------------------------
async function loadContacts() {
  const revision = state.accountRevision;
  const contacts = await attempt(() => api('contacts'));
  if (contacts && revision === state.accountRevision && !state.locked) {
    state.contacts = contacts;
    drawContacts();
  }
}

function contactsView() {
  const bar = h('div', { class: 'bar' }, backButton(), h('div', { class: 'title' }, t('Contactos')), statusNode(),
    symbolButton('+', t('Actions'), () => sheet(t('Contactos'), [
      [t('Add contact'), () => contactForm(null)],
      [t('Add by username'), addByUsername],
      [t('Nuevo grupo'), () => newGroup([])],
    ])));
  const search = h('div', { class: 'search' }, h('input', { type: 'search', placeholder: t('Search contacts'), value: state.search,
    oninput: (event) => { state.search = event.target.value; drawContacts(); } }));
  const selection = h('div', { class: 'selection-bar', id: 'contact-selection-bar', hidden: true });
  const list = h('div', { class: 'scroll', id: 'contactlist' });
  if (state.contacts === null) loadContacts();
  setTimeout(drawContacts, 0);
  return [bar, selection, search, list];
}

// Desktop contact list: search by name, @username or phone; select several to
// share them, start a group with them or open their cards.
function drawContacts() {
  const list = document.getElementById('contactlist');
  if (!list) return;
  drawContactSelection();
  if (state.contacts === null) { list.replaceChildren(h('div', { class: 'empty' }, t('Cargando...'))); return; }
  const query = state.search.trim().toLowerCase().replace(/^@/, '');
  const digits = query.replace(/[^\d]/g, '');
  const contacts = state.contacts.filter((item) => !query || item.name.toLowerCase().includes(query) || item.username.toLowerCase().includes(query)
    || (digits.length >= 3 && String(item.phone || '').includes(digits)));
  state.visibleContacts = contacts.map((item) => item.id);
  const chosen = state.contactSelection;
  const menu = (item) => sheet(item.name, [
    [t('Open chat'), () => openChat(item.id, true, { id: item.id, name: item.name, kind: 'user' })],
    [t('Contact card'), () => openProfile({ id: item.id, name: item.name })],
    [t('Select'), () => toggleContactSelected(item.id)],
    [t('Share contact'), () => shareContacts([item.id])],
    [t('Edit contact'), () => contactForm({ id: item.id, first: item.first, last: item.last, phone: item.phone })],
    [t('Delete contact'), () => deleteContact({ id: item.id, name: item.name }), 'danger'],
  ]);
  list.replaceChildren(...(contacts.length ? contacts.map((item) => { let timer = null, held = false; const on = chosen && chosen.has(item.id);
    return peerControl({ class: 'row peer-control' + (on ? ' selected' : ''),
    onclick: () => { if (held) return; if (chosen) toggleContactSelected(item.id); else openChat(item.id, true, { id: item.id, name: item.name, kind: 'user' }); },
    oncontextmenu: (event) => { event.preventDefault(); menu(item); },
    ontouchstart: () => { held = false; timer = setTimeout(() => { held = true; menu(item); }, 550); },
    ontouchend: () => clearTimeout(timer), ontouchmove: () => clearTimeout(timer) },
    chosen ? h('span', { class: 'mark' }, on ? '☑' : '☐') : null,
    feature('contact_list_details') ? avatar(item.id, item.name) : null,
    h('div', { class: 'body' }, h('div', { class: 'top' }, nameWithStatus(item.name, item.emoji_status, true, chosen ? !!on : null)),
      h('div', { class: 'bottom' }, h('span', { class: 'preview' }, (item.username ? '@' + item.username : '') + (feature('contact_list_details') && item.status ? (item.username ? ' · ' : '') + item.status : ''))))); })
    : [h('div', { class: 'empty' }, t('Sin resultados.'))]));
}

function toggleContactSelected(id) {
  if (!state.contactSelection) state.contactSelection = new Set();
  if (state.contactSelection.has(id)) state.contactSelection.delete(id); else state.contactSelection.add(id);
  if (!state.contactSelection.size) state.contactSelection = null;
  drawContacts();
}
function drawContactSelection() {
  const bar = document.getElementById('contact-selection-bar');
  if (!bar) return;
  if (!state.contactSelection) { bar.hidden = true; bar.replaceChildren(); return; }
  const ids = [...state.contactSelection];
  const clear = () => { state.contactSelection = null; drawContacts(); };
  bar.replaceChildren(h('span', { class: 'count' }, t('Selected') + ': ' + ids.length),
    bulkButtons(() => { state.contactSelection = new Set(state.visibleContacts || []); drawContacts(); }, clear),
    button(t('Actions'), () => sheet(t('Selected') + ': ' + ids.length, [
      [t('Select all'), () => { state.contactSelection = new Set(state.visibleContacts || ids); drawContacts(); }],
      [t('Share contact'), () => { clear(); shareContacts(ids); }],
      [t('Nuevo grupo con seleccionados'), () => newGroup(ids, clear)],
      ids.length === 1 ? [t('Contact card'), () => openProfile(state.contacts.find((item) => item.id === ids[0]) || { id: ids[0], name: '' })] : null,
    ].filter(Boolean)), 'primary'), symbolButton('x', t('Cancelar'), clear));
  bar.hidden = false;
}

// Send contact cards to a chat chosen from the list.
function shareContacts(ids) {
  chooseForwardTarget({people: ids});
}

function createCommunity(channel) {
  const title = h('input', {type: 'text', maxlength: 128, required: true});
  const about = h('textarea', {rows: 3, maxlength: 255});
  const account = state.account;
  let creating = false;
  const titleLabel = channel ? t('Title') : t('Nombre del grupo:');
  const [forumRow, forumOption] = check(t('Organizar el grupo por temas'));
  formSheet(channel ? t('New channel') : t('Nuevo grupo'),
    [labelled(titleLabel, title), labelled(t('Description'), about), ...(channel ? [] : [forumRow])], t('Create'), async () => {
      if (!title.reportValidity() || !title.value.trim() || creating || account !== state.account) return false;
      creating = true;
      try {
        const chat = await api('create_community', {title: title.value.trim(), about: about.value, channel, account, forum: !channel && forumOption.checked});
        if (account === state.account) {
          closeSheet();
          await openChat(chat.id, true, chat);
        }
        return true;
      } catch (error) {
        toast(error.message, 'error');
        return false;
      } finally {
        creating = false;
      }
    });
}

function newGroup(ids, done) {
  const revision = state.accountRevision;
  if (!ids.length) {
    toast(t('Selecciona participantes en la lista.'));
    if (state.view !== 'contacts') go('contacts', { contacts: null, search: '' });
    state.contactSelection = new Set(); drawContacts();
    return;
  }
  promptThen(t('Nuevo grupo'), { placeholder: t('Nombre del grupo:') }, (title) => {
    if (!title.trim()) return false;
    attempt(() => api('create_group', { title, people: ids }), (chat) => {
      if (revision !== state.accountRevision || state.locked) return;
      if (done) done();
      if (chat.missing) toast(t('Grupo creado; algunos usuarios no pudieron ser invitados.'));
      openChat(chat.id, true, chat);
    });
  });
}

function addByUsername() {
  promptThen(t('Add by username'), { value: '@', placeholder: '@username' }, (value) => {
    if (!value || value.trim() === '@') return false;
    attempt(() => api('resolve', { value: value.trim() }), (chat) => {
      if (chat.kind !== 'user') { toast(t('Choose a person, not a channel or group.'), 'error'); return; }
      openProfile(chat);
    });
  });
}

// New contact (by phone) or save / edit the person shown (by id).
function contactForm(person) {
  const revision = state.accountRevision;
  const first = h('input', { type: 'text', value: person ? person.first || '' : '' });
  const last = h('input', { type: 'text', value: person ? person.last || '' : '' });
  const phone = h('input', { type: 'tel', placeholder: '+34…', value: person && person.phone ? '+' + String(person.phone).replace(/^\+/, '') : '' });
  formSheet(person ? (person.contact === false ? t('Add contact') : t('Edit contact')) : t('Add contact'),
    [labelled(t('First name'), first), labelled(t('Last name'), last), labelled(t('Phone number'), phone)], t('Save'), async () => {
      const result = await attempt(() => api('add_contact', { first: first.value, last: last.value, phone: phone.value, peer: person ? person.id : null }));
      if (!result || revision !== state.accountRevision || state.locked) return false;
      toast(t('Saved.'));
      state.contacts = null;
      if (state.view === 'contacts') { loadContacts(); }
      if (state.view === 'profile' && state.profile && person && state.profile.id === person.id) { state.profile.contact = true; refreshProfile(); }
      if (!person && result.id) openChat(result.id, true, { id: result.id, name: (first.value + ' ' + last.value).trim(), kind: 'user' });
    });
}

function deleteContact(person) {
  confirmThen(t('Delete contact') + ': ' + person.name + '?', () => attempt(() => api('delete_contact', { peer: person.id }), (result) => {
    queuedNote(result); state.contacts = null;
    if (state.view === 'contacts') loadContacts();
    if (state.profile && state.profile.id === person.id) { state.profile.contact = false; if (state.view === 'profile') render(); }
  }));
}

function refreshProfile() {
  const profile = state.profile, account = state.account;
  if (!profile) return;
  const request = profile.request = (profile.request || 0) + 1;
  attempt(() => api('profile', {peer: profile.id}), (data) => {
    if (state.account !== account || state.profile !== profile || profile.request !== request) return;
    state.profile = data;
    if (state.view === 'profile') render();
    if (data.personal_channel && data.personal_channel_message) {
      api('personal_channel_preview', {peer: data.personal_channel, id: data.personal_channel_message}).then(preview => {
        if (!preview || state.account !== account || state.profile !== data) return;
        data.personal_channel_preview = preview;
        if (state.view === 'profile' && state.profileSection === 'info') {
          const top = document.getElementById('profile-scroll')?.scrollTop || 0;
          render();
          const scroll = document.getElementById('profile-scroll');
          if (scroll) scroll.scrollTop = top;
        }
      }, () => {});
    }
  });
}

// profile ----------------------------------------------------------------------------
function openProfile(chat) {
  if (!state.profile || state.profile.id !== chat.id) state.profileSection = 'info';
  state.profile = {id: chat.id, name: chat.name, loading: true};
  go('profile');
  refreshProfile();
}

const PROFILE_SECTIONS = [['info', 'Informacion'], ['photos', 'Photos'], ['files', 'Files'], ['audio', 'Audio'], ['voice', 'Voice messages'],
  ['links', 'Links'], ['gifs', 'GIF'], ['polls', 'Encuestas'], ['posts', 'Publicaciones'], ['gifts', 'Regalos'],
  ['profile_music', 'Música del perfil'], ['similar', 'Canales similares'], ['settings', 'Ajustes']];
const PROFILE_TABS = new Set(['posts', 'gifts', 'profile_music', 'similar']);

const PROFILE_ACTIONS = {message: 'Abrir chat', call: 'Call', video_call: 'Video call', notifications: 'Notifications',
  edit_contact: 'Edit contact', share: 'Share contact', add_username: 'Add by username', membership: 'Unirse / salir',
  edit_self: 'Editar mi perfil', profile_design: 'Diseño del perfil', refresh: 'Actualizar', manage: 'Ajustes'};

async function contactCardAppearance(data) {
  const account = state.account;
  const active = () => state.account === account && state.view === 'profile' && state.profile?.id === data.id && !state.locked;
  const config = await attempt(() => api('contact_card_appearance', {account}));
  if (!config || !active()) return;
  const editable = values => Object.fromEntries(Object.entries(values).map(([key, value]) =>
    [key, Array.isArray(value) ? value.slice() : value]));
  let draft = editable(config.values);
  const draw = () => {
    const select = (key, label, choices) => labelled(label, h('select', {onchange: e => { draft[key] = e.target.value; }},
      choices.map(([value, name]) => h('option', {value, selected: draft[key] === value}, name))));
    const size = (key, label, min, max) => labelled(label, h('input', {type: 'number', value: draft[key], min, max, step: 1, required: true,
      oninput: e => { draft[key] = e.target.valueAsNumber; }}));
    const color = (key, label) => {
      const input = h('input', {type: 'color', value: draft[key] || '#808080',
        'aria-label': label, oninput: e => { draft[key] = e.target.value; inherit.disabled = false; }});
      const inherit = h('button', {type: 'button', class: 'btn', disabled: !draft[key], onclick: () => {
        draft[key] = ''; inherit.disabled = true; input.value = '#808080';
      }}, t('Default'));
      return h('div', {class: 'setting'}, h('span', {}, label), input, inherit);
    };
    function orderControls(group, names, protectedKey) {
      const order = draft['contact_' + group + '_order'], hidden = draft['contact_hidden_' + group + 's'];
      const list = h('div', {class: 'card-order'});
      function rows(focusKey, action) {
        list.replaceChildren(...order.map((key, i) => {
          const move = delta => {
            order.splice(i, 1); order.splice(i + delta, 0, key);
            rows(key, delta < 0 ? 0 : 1);
          };
          const [label, visible] = check(t(names[key]), !hidden.includes(key));
          visible.disabled = key === protectedKey;
          visible.onchange = () => {
            if (visible.checked) hidden.splice(hidden.indexOf(key), 1);
            else hidden.push(key);
          };
          return h('div', {class: 'setting', 'data-key': key}, label,
            symbolButton('↑', t('Subir') + ' · ' + t(names[key]), () => move(-1), i === 0),
            symbolButton('↓', t('Bajar') + ' · ' + t(names[key]), () => move(1), i === order.length - 1));
        }));
        if (focusKey) {
          const controls = list.querySelector('[data-key="' + focusKey + '"]').querySelectorAll('button');
          (controls[action].disabled ? controls[1 - action] : controls[action]).focus();
        }
      }
      rows();
      return h('details', {}, h('summary', {}, group === 'section' ? t('Secciones') : t('Botones')), list);
    }
    const [round, checkbox] = check(t('Avatar circular'), draft.contact_round_avatar);
    checkbox.onchange = () => { draft.contact_round_avatar = checkbox.checked; };
    formSheet(t('Apariencia'), [
      select('contact_density', t('Densidad'), [['compact', t('Compacta')], ['comfortable', t('Normal')], ['spacious', t('Amplia')]]),
      select('contact_alignment', t('Alineación'), [['left', t('Al inicio')], ['center', t('Centrada')]]),
      size('contact_card_width', t('Ancho de la tarjeta (px)'), 320, 1200),
      size('contact_avatar_size', t('Tamaño del avatar (px)'), 48, 192),
      size('contact_border_width', t('Grosor del borde (px)'), 0, 8), round,
      color('contact_background', t('Fondo de cabecera')), color('contact_text', t('Texto de cabecera')),
      color('contact_accent', t('Acento del avatar')), color('contact_border_color', t('Borde de cabecera')),
      orderControls('section', Object.fromEntries(PROFILE_SECTIONS), 'settings'),
      orderControls('action', PROFILE_ACTIONS, 'manage'),
      button(t('Restaurar ficha predeterminada'), () => { draft = editable(config.defaults); draw(); }),
    ], t('Guardar'), async () => {
      if (!active()) return false;
      const invalid = document.querySelector('#sheet-layer input[type=number]:invalid');
      if (invalid) { invalid.reportValidity(); return false; }
      const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) =>
        JSON.stringify(value) !== JSON.stringify(config.values[key])));
      const saved = await attempt(() => api('contact_card_appearance', {account, changes}));
      if (!saved || !active()) return false;
      state.profile.card = saved.values;
      render();
      return true;
    });
  };
  draw();
}

function profileHeaderContrast(head, colors, patterned) {
  const rgb = hex => [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16) / 255);
  const luminance = channels => {
    const [r, g, b] = channels.map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    return .2126 * r + .7152 * g + .0722 * b;
  };
  const palette = colors.map(rgb);
  const opacity = patterned ? .22 : 0;
  // Bound every colour in the gradient, including a black or white pattern.
  const darkest = luminance([0, 1, 2].map(i => Math.min(...palette.map(c => c[i])) * (1 - opacity)));
  const lightest = luminance([0, 1, 2].map(i => Math.max(...palette.map(c => c[i])) * (1 - opacity) + opacity));
  let ink = '#fff';
  if ((darkest + .05) / (luminance(rgb('#101820')) + .05) >= 4.5) ink = '#101820';
  else if (1.05 / (lightest + .05) < 4.5) {
    if ((darkest + .05) / .05 >= 4.5) ink = '#000';
    else head.classList.add('caption-background');
  }
  head.style.setProperty('--profile-ink', ink);
}

// The contact card (desktop: contact_profile): header with the Telegram profile
// colour, actions, then one section at a time (information, shared media, tabs).
function profileView() {
  const data = state.profile || {};
  const person = data.kind === 'user' && !data.is_self && !data.loading;
  const community = ['group', 'channel'].includes(data.kind);
  const rights = data.rights || {};
  const canManage = community && (rights.can_edit_info || rights.can_ban || rights.can_set_ttl ||
    rights.can_manage_reactions || rights.can_change_username || rights.can_invite || data.can_add_members || data.can_link_discussion);
  function selectSection(key) {
    state.profileSection = key;
    render();
    document.querySelector('.profile-section')?.focus({preventScroll: true});
  }
  const badges = [['premium', 'Premium'], ['verified', 'Verified'], ['bot', 'Bot'], ['scam', 'Scam'], ['fake', 'Fake'], ['blocked', 'Block']]
    .filter(([key]) => data[key]).map(([, label]) => t(label));
  const bar = h('div', { class: 'bar' }, backButton(), h('div', { class: 'title' }, t('Profile')), statusNode());
  const copyField = (label, value) => value ? h('div', { class: 'setting copyable', role: 'button', onclick: () => copy(value) },
    h('span', { class: 'muted' }, label), h('span', { class: 'value' }, value), h('span', { class: 'copy-hint' }, t('Copy'))) : null;
  const field = (label, value, action) => value ? h('div', { class: 'setting', role: action ? 'button' : null, onclick: action || null },
    h('span', { class: 'muted' }, label), h('span', { class: 'value' }, value)) : null;

  // Header band: the profile colour (gradient) and its emoji pattern, as on desktop.
  const banner = data.banner || {};
  const card = data.card || {};
  const headerColors = banner.colors?.length ? banner.colors : card.contact_background ? [card.contact_background] : [];
  const head = h('div', { class: 'profile-head' + (banner.colors && banner.colors.length ? ' coloured' : '') },
    h('div', { role: data.loading ? null : 'button', 'aria-label': t('Profile photo'), onclick: data.loading ? null : () => avatarViewer(data) }, avatar(data.id, data.name || '', 'big')),
    h('div', { class: 'profile-names' }, h('div', { class: 'name with-status' },
      h('bdi', { class: 'label', role: data.name ? 'button' : null, 'aria-label': data.name ? t('Copy') + ' · ' + data.name : null, onclick: data.name ? () => copy(data.name) : null }, data.name || ''),
      emojiStatusBadge(data.emoji_status)),
      h('div', { class: 'muted' }, data.loading ? t('Cargando...') : data.deleted ? t('Deleted account') : (data.status || ''))));
  if (headerColors.length) {
    head.style.background = headerColors.length > 1
      ? 'linear-gradient(135deg, ' + headerColors.join(', ') + ')' : headerColors[0];
    if (!card.contact_text) profileHeaderContrast(head, headerColors, !!banner.pattern);
  }
  if (banner.pattern) head.append(h('div', { class: 'profile-pattern', 'aria-hidden': 'true',
    style: 'background-image: url("' + stickerUrl(banner.pattern) + '")' }));

  const dial = state.callsAvailable && feature('calls') && person && !data.is_self && !data.bot;
  const available = {
    message: state.open?.peer === data.id ? null : button(t('Abrir chat'), () => openChat(data.id, true, { id: data.id, name: data.name })),
    call: dial && data.phone_calls_available ? button(t('Call'), () => nativeCallAction('start', { peer: data.id })) : null,
    video_call: dial && data.video_calls_available ? button(t('Video call'), () => nativeCallAction('start', { peer: data.id, video: true })) : null,
    notifications: button(t('Notifications'), () => chatNotifications(data)),
    edit_contact: person ? button(data.contact ? t('Edit contact') : t('Add contact'), () => contactForm(data)) : null,
    add_username: button(t('Add by username'), addByUsername),
    refresh: button(t('Actualizar'), refreshProfile),
    manage: button(t('Ajustes'), () => selectSection('settings')),
    share: person ? button(t('Share contact'), () => shareContacts([data.id])) : null,
    membership: (data.can_join || data.member === false) && community ? button(t('Unirse'), () => attempt(() => api('join', { peer: data.id }), (result) => {
      queuedNote(result); data.member = !(result && result.joined === false); data.can_join = false; render();
    }), 'primary') : null,
    edit_self: data.is_self ? button(t('Editar mi perfil'), () => { state.settingsTab = 'account'; go('settings'); }) : null,
    profile_design: data.is_self ? button(t('Diseño del perfil'), () => { state.settingsTab = 'premium'; go('settings'); }) : null,
  };
  const actions = data.loading ? null : h('div', {class: 'profile-actions'},
    ...(card.contact_action_order || Object.keys(available)).filter(key => !card.contact_hidden_actions?.includes(key)).map(key => available[key]),
    person && !data.bot ? button('🔒 ' + t('Iniciar chat secreto'), () => startSecretChat(data.id)) : null,
    data.is_secret ? button('🔒 ' + t('Clave de cifrado y autodestrucción'), () => secretChatSheet({id: data.id, name: data.name, kind: 'secret'})) : null,
    community && state.groupCallsAvailable && feature('calls') ? button(t('Group call'), () => groupCallSheet(data)) : null,
    button(t('Apariencia'), () => contactCardAppearance(data)));

  const gated = { polls: 'polls', posts: 'stories', gifts: 'stars_gifts', links: 'links' };
  const sections = PROFILE_SECTIONS.filter(([key]) => !card.contact_hidden_sections?.includes(key) &&
    (!gated[key] || feature(gated[key])) && (key !== 'similar' || data.kind === 'channel') &&
    (key !== 'profile_music' || data.kind === 'user') && !(data.loading && key !== 'info'));
  const order = card.contact_section_order;
  if (order) sections.sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
  const current = sections.some(([key]) => key === state.profileSection) ? state.profileSection :
    sections.find(([key]) => key === 'info' || key === 'settings' || PROFILE_TABS.has(key))?.[0] || 'info';
  const selector = h('select', { class: 'profile-section', 'aria-label': t('Informacion'), onchange: (event) => {
    const key = event.target.value;
    if (PROFILE_TABS.has(key) || key === 'info' || key === 'settings') selectSection(key);
    else { event.target.value = current; openShared(data, key); }
  } }, sections.map(([key, label]) => h('option', { value: key, selected: key === current }, t(label))));

  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const weekdayMinute = (value) => {
    const day = days[Math.floor(value / 1440) % 7];
    const hours = String(Math.floor(value / 60) % 24).padStart(2, '0');
    const minutes = String(value % 60).padStart(2, '0');
    return t(day) + ' ' + hours + ':' + minutes;
  };
  const relatedProfile = (peer, label) => peer ? button(t(label), () => openProfile({id: peer, name: t(label)})) : null;
  const intro = data.business_intro;
  const verification = data.bot_verification;
  const profileLinks = new Set((data.usernames || []).map(name => 'https://t.me/' + name));
  if (data.link) profileLinks.add(data.link);
  const info = h('div', { class: 'section' },
    copyField(t({ user: 'Contact', bot: 'Bot', group: 'Group', channel: 'Channel' }[data.kind] || 'Contact'), data.name || ''),
    ...(data.usernames || []).map((name) => copyField(t('Nombre de usuario'), '@' + name)),
    copyField('Telegram ID', data.telegram_id ? String(data.telegram_id) : ''),
    copyField(t('Telefono internacional'), data.phone ? '+' + String(data.phone).replace(/^\+/, '') : ''),
    copyField(t('Birthday'), data.birthday || ''),
    person ? copyField(t('Type'), t(data.contact ? 'Contact' : 'User')) : null,
    field(t('Members'), data.members ? data.members.toLocaleString(state.language) + (data.online ? ' · ' + data.online + ' ' + t('Online') : '') : ''),
    field(t('Administrators'), data.admins ? String(data.admins) : ''),
    copyField(t('Address'), data.address),
    data.work_hours ? field(t('Time zone'), data.work_hours.timezone) : null,
    ...(data.work_hours?.periods || []).map(([from, to]) =>
      field(t('Opening hours'), weekdayMinute(from) + ' — ' + weekdayMinute(to))),
    relatedProfile(data.linked_peer, 'Linked discussion / channel'),
    relatedProfile(data.personal_channel, 'Personal channel'),
    data.personal_channel_preview ? h('button', {
      class: 'item personal-channel-preview', onclick: async () => {
        const open = await openChat(data.personal_channel, true, {id: data.personal_channel, name: t('Personal channel'), kind: 'channel'});
        if (open && state.open === open && open.peer === data.personal_channel) await jumpTo(data.personal_channel_message);
      },
    }, ...richText(data.personal_channel_preview.text || t('Go to message'), data.personal_channel_preview.emojis, false)) : null,
    intro ? h('div', {class: 'about'},
      h('div', {class: 'muted'}, intro.title || t('Description')),
      intro.sticker ? customEmoji(intro.sticker, '', true) : null,
      h('div', {class: 'text'}, linkify(intro.description))) : null,
    verification ? h('div', {class: 'setting'},
      customEmoji(verification.icon, '✓', false), h('span', {class: 'value'}, verification.description)) : null,
    data.about ? h('div', { class: 'about' }, h('div', { class: 'muted' }, t(data.kind === 'user' ? 'Biografia' : 'Description')), h('div', { class: 'text' }, linkify(data.about))) : null,
    badges.length ? field(t('Status'), badges.join(' · ')) : null,
    data.share_link && !profileLinks.has(data.share_link) ? copyField(t('Link'), data.share_link) : null,
    ...Array.from(profileLinks, url => h('button', {class: 'btn wide-link', onclick: () => copy(url)}, url)),
    person && data.contact ? field(t('Note (only you can see it)'), data.note || '+', () => editNote(data)) : null);

  const more = data.loading ? null : h('div', { class: 'section' },
    button(data.muted ? t('Activar sonido') : t('Silenciar'), () => muteSheet(data, () => render())),
    data.rights?.can_view_members ? button(t('Members'), () => communityMembers(data)) : null,
    person && data.common ? button(t('Groups in common') + ' (' + data.common + ')', () => commonGroups(data)) : null,
    person && data.contact ? button(t('Delete contact'), () => deleteContact(data), 'danger') : null,
    person && data.contact && !data.birthday ? button(t('Suggest a birthday'), () => suggestBirthday(data)) : null,
    person && !data.has_photo ? button(t('Suggest a photo'), () => contactPhoto(data, true)) : null,
    person ? button(t('Set a photo for this contact'), () => contactPhoto(data, false)) : null,
    person && data.personal_photo ? button(t('Remove the photo you set'), () => confirmThen(t('Remove the photo you set') + '?',
      () => attempt(() => api('contact_photo', { peer: data.id }), () => { toast(t('Photo removed.')); state.avatarVersion = Date.now(); refreshProfile(); }))) : null,
    data.can_leave && data.member !== false && community
      ? button(t('Leave'), () => confirmThen(t('Leave') + ': ' + data.name + '?', () => attempt(() => api('leave_chat', { peer: data.id }), (result) => {
        queuedNote(result); data.member = false; data.can_join = true; render(); })), 'danger') : null,
    person ? button(data.blocked ? t('Unblock') : t('Block'), () => {
      const run = () => attempt(() => api('block', { peer: data.id, blocked: !data.blocked }), (result) => { queuedNote(result); data.blocked = !data.blocked; render(); });
      if (data.blocked) run(); else confirmThen(t('Block') + ': ' + data.name + '?', run);
    }, data.blocked ? '' : 'danger') : null);

  const settings = () => h('div', {class: 'section'},
    button(t('Notifications'), () => chatNotifications(data)),
    canManage ? button(t('Ajustes'), () => manageCommunity(data)) : null,
    more);
  const content = current === 'info' ? [info, more] : current === 'settings' ? [settings()] : [profileTab(data, current)];
  const body = h('div', { class: 'scroll', id: 'profile-scroll' }, head,
    badges.length ? h('div', { class: 'badges' }, badges.map((label) => h('span', { class: 'badge-tag' }, label))) : null,
    actions, data.loading ? null : selector, ...content);
  if (card.contact_card_width) {
    body.style.maxInlineSize = card.contact_card_width + 'px';
    body.style.inlineSize = '100%';
    body.style.alignSelf = 'center';
    const space = {compact: 8, comfortable: 16, spacious: 24}[card.contact_density];
    head.style.padding = space + 'px';
    head.style.gap = (space / 2) + 'px';
    head.classList.toggle('centered', card.contact_alignment === 'center');
    if (card.contact_border_width) head.style.border = card.contact_border_width + 'px solid ' + (card.contact_border_color || 'var(--line)');
    if (card.contact_text) head.style.setProperty('--profile-ink', card.contact_text);
    const face = head.querySelector('.avatar');
    face.style.inlineSize = face.style.blockSize = card.contact_avatar_size + 'px';
    face.style.borderRadius = card.contact_round_avatar ? '50%' : '0';
    if (card.contact_accent) face.style.background = card.contact_accent;
  }
  return [bar, body];
}

// Publicaciones, Regalos, Música del perfil, Canales similares (desktop: profile_tabs).
function profileTab(data, kind) {
  const box = h('div', { class: 'section profile-tab' }, h('div', { class: 'muted' }, t('Cargando...')));
  const key = data.id + ':' + kind, account = state.account;
  const cache = state.profileTabs = state.profileTabs || {};
  const draw = () => {
    const page = cache[key];
    if (!page) return;
    const rows = page.items.map((item) => {
      if (kind === 'similar') return peerControl({ class: 'row peer-control', onclick: () => openProfile({ id: item.id, name: item.name, kind: 'channel' }) },
        avatar(item.id, item.name), h('div', { class: 'body' }, h('div', { class: 'top' }, nameWithStatus(item.name, item.emoji_status, true)),
          h('div', { class: 'bottom' }, h('span', { class: 'preview' }, item.member ? t('Joined') : t('Channel')))));
      if (kind === 'gifts') return h('div', { class: 'setting gift' }, item.sticker ? h('img', { class: 'custom-emoji gift-sticker', src: stickerUrl(item.sticker), alt: '' }) : null,
        h('span', {}, [item.title || t('Gift'), item.from ? '· ' + item.from : '', item.stars ? '· ★ ' + item.stars : ''].filter(Boolean).join(' ')),
        h('span', { class: 'muted' }, item.date ? new Date(item.date * 1000).toLocaleDateString(state.language) : ''));
      if (kind === 'profile_music') return h('div', { class: 'setting' }, h('span', {}, '♪ ' + ([item.performer, item.title].filter(Boolean).join(' – ') || t('Audio'))),
        h('span', { class: 'muted' }, item.duration ? clockTime(item.duration) : ''));
      return h('div', { class: 'setting' }, h('span', {}, (item.kind === 'video' ? '▶ ' : '▣ ') + (item.caption || t('Story'))),
        h('span', { class: 'muted' }, item.date ? new Date(item.date * 1000).toLocaleDateString(state.language) : ''));
    });
    box.replaceChildren(...(rows.length ? rows : [h('div', { class: 'empty' }, t('No results.'))]),
      page.next != null ? button(t('More'), () => load(page.next)) : null);
  };
  const load = (offset = 0) => attempt(() => api('profile_tab', { peer: data.id, kind, offset }), (result) => {
    const previous = offset && cache[key] ? cache[key].items : [];
    cache[key] = { items: [...previous, ...result.items], next: result.next };
    if (state.account === account && state.profile?.id === data.id && state.profileSection === kind) draw();
  });
  if (cache[key]) setTimeout(() => { if (state.account === account) draw(); }, 0); else load();
  return box;
}

function manageCommunity(chat) {
  const account = state.account;
  const rights = chat.rights;
  let busy = false;
  const update = async (method, fields) => {
    if (state.account !== account || busy) return undefined;
    busy = true;
    try {
      const result = await api(method, {peer: chat.id, account, ...fields});
      if (state.account !== account) return undefined;
      refreshProfile();
      return result;
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy = false;
    }
  };
  const change = (field, value, key) => update('group_change', {field, value, key});
  const textForm = (field, label, value, limit) => {
    const input = field === 'about' ? h('textarea', {rows: 3, maxlength: limit}, value)
      : h('input', {type: 'text', maxlength: limit, value});
    formSheet(label, [labelled(label, input)], t('Guardar'), async () => Boolean(await change(field, input.value)));
  };
  const choose = (field, label, values) => sheet(label, values.map(([value, text]) =>
    [(chat[field] === value ? '✓ ' : '') + text, () => change(field, value)]));
  const permissions = async () => {
    const fields = await attempt(() => api('community_permissions', {peer: chat.id}));
    if (!fields || state.account !== account) return;
    const rows = fields.map(([key, label, enabled]) => {
      const [node, input] = check(label, enabled);
      return {key, node, input, enabled};
    });
    formSheet(t('Permissions'), [bulkCheckRows(rows), ...rows.map(row => row.node)], t('Guardar'), async () => {
      const changes = Object.fromEntries(rows.filter(row => row.enabled !== row.input.checked)
        .map(row => [row.key, row.input.checked]));
      return !Object.keys(changes).length || Boolean(await change('permissions', changes));
    });
  };
  sheet(chat.name, [
    chat.creator && chat.kind === 'group' ? [chat.forum ? t('Desactivar temas') : t('Activar temas'), () =>
      confirmThen(chat.forum ? t('Volver a mostrar todos los mensajes juntos') : t('Organizar este grupo por temas. Un grupo básico se convertirá en supergrupo.'), async () => {
        const changed = await update('forum_toggle', {enabled: !chat.forum, migrate: !chat.is_channel});
        if (changed) {closeSheet(); openChat(changed.id, true, changed);}
      }, 'primary')] : null,
    rights.can_edit_info ? [t('Edit title'), () => textForm('title', t('Edit title'), chat.name, 128)] : null,
    rights.can_edit_info ? [t('Description'), () => textForm('about', t('Description'), chat.about, 255)] : null,
    rights.can_edit_info ? [t('Change photo'), async () => {
      const photo = await attempt(() => pickOnePhoto());
      if (photo && await change('photo', null, typeof photo === 'string' ? photo : photo.key)) {
        state.avatarVersion = Date.now();
        refreshProfile();
      }
    }] : null,
    rights.can_edit_info && chat.has_photo ? [t('Remove photo'), () => confirmThen(t('Remove photo') + '?', async () => {
      if (await change('photo', null)) { state.avatarVersion = Date.now(); refreshProfile(); }
    })] : null,
    rights.can_change_username ? [t('Change username'), () => textForm('username', t('Change username'), chat.usernames[0] || '', 32)] : null,
    rights.can_set_ttl ? [t('Auto-delete messages'), () => choose('ttl', t('Auto-delete messages'),
      [[0, t('Off')], [86400, t('1 day')], [604800, t('1 week')], [2678400, t('1 month')]])] : null,
    rights.can_ban && chat.kind === 'group' ? [t('Permissions'), permissions] : null,
    rights.can_ban && chat.kind === 'group' && chat.is_channel ? [t('Slow mode'), () => choose('slowmode', t('Slow mode'),
      [[0, t('Off')], ...[10, 30, 60, 300, 900, 3600].map(seconds =>
        [seconds, new Intl.NumberFormat(state.language || 'en', {style: 'unit', unit: 'second'}).format(seconds)])])] : null,
    rights.can_manage_reactions ? [t('Reactions'), () => choose('reactions', t('Reactions'),
      [['all', t('All')], ['none', t('Off')]])] : null,
    chat.can_add_members ? [t('Add members'), () => inviteCommunityMembers(chat, update)] : null,
    rights.can_invite ? [t('Invite link'), async () => {
      const result = await change('invite');
      if (result?.link) sheet(result.link, [[t('Copy link'), () => copy(result.link)]]);
    }] : null,
    chat.can_link_discussion ? [t('Manage linked chats'), () => discussionGroups(chat, update)] : null,
  ].filter(Boolean));
}

async function inviteCommunityMembers(chat, update) {
  const account = state.account;
  const contacts = await attempt(() => api('contacts'));
  if (!contacts || account !== state.account) return;
  const search = h('input', {type: 'search', 'aria-label': t('Search contacts'), placeholder: t('Search contacts')});
  const list = h('div', {});
  const selected = new Set();
  const draw = () => {
    const query = search.value.trim().toLowerCase();
    list.replaceChildren(...contacts.filter(person => (person.name + ' ' + (person.username || '')).toLowerCase().includes(query))
      .slice(0, 100).map(person => {
        const [label, input] = check(person.name, selected.has(person.id));
        input.addEventListener('change', () => {
          if (input.checked && (chat.is_channel ? selected.size >= 50 : selected.size >= 1)) {
            input.checked = false;
            return;
          }
          if (input.checked) selected.add(person.id); else selected.delete(person.id);
        });
        return label;
      }));
  };
  search.addEventListener('input', draw);
  draw();
  const controls = chat.is_channel ? bulkButtons(() => {
    const filter = searchText(search.value);
    for (const person of contacts) {
      if (selected.size >= 50) break;
      if (searchText(person.name + ' ' + (person.username || '')).includes(filter)) selected.add(person.id);
    }
    draw();
  }, () => { selected.clear(); draw(); }) : null;
  formSheet(t('Add members'), [search, controls, list], t('Confirm'), async () => {
    if (!selected.size) { toast(t('Selecciona participantes en la lista.')); return false; }
    const result = await update('members_add', {users: [...selected]});
    if (result) toast(result.missing ? t('Add members') + ' · ' + (selected.size - result.missing) + '/' + selected.size : t('Saved.'));
    return Boolean(result);
  });
}

async function discussionGroups(chat, update) {
  const account = state.account;
  const data = await attempt(() => api('discussion_groups', {peer: chat.id}));
  if (!data || state.account !== account) return;
  const existing = data.linked == null ? null : -1000000000000 - data.linked;
  const set = (group, expose = false, migrate = false) => update('set_discussion', {
    group, expose, migrate, expected: data.linked,
  });
  sheet(t('Link discussion group'), [
    existing ? [t('Open linked group'), () => openChat(existing)] : null,
    existing ? [t('Unlink discussion group'), () => confirmThen(t('Unlink discussion group') + '?', () => set(null))] : null,
    ...data.items.filter(group => group.id !== existing).map(group => [group.name,
      () => confirmThen(group.name + ' · ' + (group.basic
        ? t('Linking makes the discussion history visible to new members. A basic group must be upgraded first.')
        : t('Link this discussion group and make its history visible?')),
      () => set(group.id, true, group.basic))]),
  ].filter(Boolean));
}

function communityMembers(data, selectedMode = 'members') {
  const account = state.account;
  const layer = document.getElementById('sheet-layer');
  const search = h('input', {type: 'search', placeholder: t('Buscar'), 'aria-label': t('Buscar')});
  const list = h('div', {class: 'scroll'});
  const tabs = [
    ['members', t('Members')], ['admins', t('Administrators')],
    ...(data.is_channel && data.rights.can_ban ? [
      ['restricted', t('Restricted')], ['removed', t('Removed')],
    ] : []),
  ];
  let mode = selectedMode, generation = 0, timer;
  search.hidden = mode === 'admins';
  const tabButtons = tabs.map(([key, label]) => h('button', {
    class: 'btn', 'aria-pressed': key === mode ? 'true' : 'false',
    onclick: () => {
      mode = key;
      tabButtons.forEach((tab, index) => tab.setAttribute('aria-pressed', tabs[index][0] === mode));
      search.hidden = mode === 'admins';
      reload();
    },
  }, label));
  const panel = h('div', {class: 'sheet tall', onclick: event => event.stopPropagation()},
    h('h3', {}, data.name), h('div', {class: 'quick'}, tabButtons), search, list,
    button(t('Cancelar'), closeSheet));
  layer.replaceChildren(panel);
  activateSheet(layer);
  layer.onclick = closeSheet;

  function reload() {
    clearTimeout(timer);
    const current = ++generation;
    list.replaceChildren(h('div', {class: 'muted', role: 'status'}, t('Cargando...')));
    timer = setTimeout(() => load(0, current), 220);
  }

  async function load(offset, current) {
    const active = () => generation === current && state.account === account && panel.isConnected;
    if (!active()) return;
    const params = {
      peer: data.id, offset, query: mode === 'admins' ? '' : search.value.trim(),
      admins: mode === 'admins', mode: mode === 'admins' ? 'members' : mode,
    };
    try {
      const result = await api('members', params);
      if (!active()) return;
      if (!offset) list.replaceChildren();
      if (!result.items.length && !offset && !result.more) {
        list.append(h('div', {class: 'muted'}, t('Sin resultados.')));
      }
      for (const member of result.items) {
        const role = [t(member.role), member.rank, member.status].filter(Boolean).join(' · ');
        list.append(h('button', {class: 'row', onclick: () => {
          if (data.add_admins || data.rights.can_ban) {
            communityMember(data, member, panel, () => communityMembers(data, mode));
          } else {
            closeSheet(); openProfile(member);
          }
        }},
          avatar(member.id, member.name, 'small'), h('div', {class: 'body'},
            h('span', {class: 'name'}, member.name), h('div', {class: 'muted'}, role))));
      }
      if (result.more && result.next > offset) {
        const more = button(t('Más'), () => {
          more.remove();
          load(result.next, current);
        });
        list.append(more);
      }
    } catch (error) {
      if (!active()) return;
      if (!offset) list.replaceChildren();
      list.append(h('div', {class: 'muted', role: 'alert'}, error.message),
        button(t('Reintentar'), event => {
          const retry = event.currentTarget;
          retry.previousElementSibling?.remove();
          retry.remove();
          load(offset, current);
        }));
    }
  }

  search.addEventListener('input', reload);
  reload();
}

async function communityMember(chat, member, source, backToMembers) {
  const account = state.account;
  const target = {account, peer: chat.id, user: member.id};
  const details = await attempt(() => api('member', target));
  if (!details || account !== state.account || !source.isConnected) return;

  let saving = false;
  const save = async (method, values) => {
    if (saving || account !== state.account) return false;
    saving = true;
    try {
      await api(method, {...target, ...values});
      if (account === state.account && state.view === 'profile' && state.profile?.id === chat.id) backToMembers();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      saving = false;
    }
    return false;
  };

  const rightsForm = () => {
    const rank = h('input', {type: 'text', maxlength: 16, value: details.rank});
    const fields = details.basic
      ? [['administrator', t('Administrator'), details.role === 'Administrator', true]]
      : details.admin_rights;
    const rows = fields.map(([key, label, enabled, grantable]) => {
      const [node, input] = check(label, enabled);
      input.disabled = !grantable && !enabled;
      return {key, node, input, enabled};
    });
    formSheet(t('Administrator permissions'), [
      bulkCheckRows(rows), ...rows.map(row => row.node),
      details.basic ? null : labelled(t('Administrator title'), rank),
    ], t('Guardar'), () => {
      const changes = Object.fromEntries(rows.filter(row => row.input.checked !== row.enabled)
        .map(row => [row.key, row.input.checked]));
      const title = !details.basic && rank.value !== details.rank ? rank.value : null;
      if (!Object.keys(changes).length && title === null) { backToMembers(); return false; }
      return save('member_admin', {changes, rank: title});
    });
  };

  const restrictions = (action) => {
    const rows = action === 'restrict' ? details.permissions.map(([key, label, enabled]) => {
      const [node, input] = check(label, enabled);
      return {key, node, input, enabled};
    }) : [];
    const remaining = Math.floor((details.until || 0) - Date.now() / 1000);
    const durations = [['', t('Forever')], [3600, t('For 1 hour')], [86400, t('For 1 day')], [604800, t('For 7 days')]];
    if (remaining >= 60 && action === 'restrict') {
      durations.unshift(['current', new Date(details.until * 1000).toLocaleString(state.language)]);
    }
    const period = h('select', {}, durations.map(([value, label]) => h('option', {value}, label)));
    const title = action === 'ban' ? t('Ban member') + ': ' + member.name : t('Apply member permissions');
    formSheet(title, [bulkCheckRows(rows), ...rows.map(row => row.node), labelled(t('Duration'), period)], t('Confirm'), () => {
      const changes = Object.fromEntries(rows.filter(row => row.input.checked !== row.enabled)
        .map(row => [row.key, row.input.checked]));
      const duration = period.value === 'current' ? Math.max(60, Math.floor(details.until - Date.now() / 1000))
        : period.value ? Number(period.value) : null;
      return save('member_restrict', {action, changes, duration});
    });
  };
  const confirm = (label, action) => confirmThen(label + ': ' + member.name + '?',
    () => save('member_restrict', {action}));
  const banned = details.role === 'Removed';
  sheet(member.name + ' · ' + t(details.role), [
    [t('Contact card'), () => openProfile(member)],
    details.can_admin && !banned ? [t('Administrator permissions'), rightsForm] : null,
    details.can_restrict && !banned ? [t('Apply member permissions'), () => restrictions('restrict')] : null,
    details.can_ban && details.role === 'Restricted'
      ? [t('Remove restrictions'), () => confirm(t('Remove restrictions'), 'unban')] : null,
    details.can_ban && !banned ? [t('Remove member'), () => confirm(t('Remove member'), 'remove'), 'danger'] : null,
    details.can_ban && !details.basic && !banned ? [t('Ban member'), () => restrictions('ban'), 'danger'] : null,
    details.can_ban && banned ? [t('Unban member'), () => confirm(t('Unban member'), 'unban')] : null,
    [t('Members'), backToMembers],
  ].filter(Boolean));
}

// Suggest a profile photo (they decide whether to use it) or set one only you see.
async function contactPhoto(data, suggest) {
  const revision = state.accountRevision;
  let file;
  try { file = await pickOnePhoto(); } catch (error) { toast(error.message, 'error'); return; }
  if (!file) return;
  const key = typeof file === 'string' ? file : file.key;
  if (revision !== state.accountRevision || state.locked) {
    api('discard_files', {keys: [key]}).catch(() => {});
    return;
  }
  const question = suggest ? t('Suggest this photo to {name}? They decide whether to use it.') : t('Set this photo for {name}? Only you will see it.');
  sheet(question.replace('{name}', data.name || ''), [
    [suggest ? t('Suggest') : t('Save'), () => attempt(() => api('contact_photo', { peer: data.id, key, suggest }), () => {
      if (revision !== state.accountRevision || state.locked) return;
      toast(suggest ? t('Photo suggested.') : t('Photo saved.'));
      if (!suggest) { state.avatarVersion = Date.now(); refreshProfile(); }
    })],
  ]);
  // Cancel throws the picture away.
  const layer = document.getElementById('sheet-layer');
  const cancel = [...layer.querySelectorAll('.item')].pop();
  if (cancel) cancel.addEventListener('click', () => api('discard_files', { keys: [key] }).catch(() => {}));
}

function editNote(data) {
  const area = h('textarea', { rows: 4, maxlength: 4096 }, data.note || '');
  formSheet(t('Note (only you can see it)'), [area], t('Save'), async () => {
    const ok = await attempt(() => api('contact_note', { peer: data.id, text: area.value }));
    if (!ok) return false;
    data.note = area.value; render();
  });
}

function suggestBirthday(data) {
  const input = h('input', { type: 'date' });
  formSheet(t('Suggest a birthday'), [input], t('Suggest'), async () => {
    const [year, month, day] = (input.value || '').split('-').map(Number);
    if (!day || !month) { toast(t('Invalid date.'), 'error'); return false; }
    const ok = await attempt(() => api('suggest_birthday', { peer: data.id, day, month, year }));
    if (!ok) return false;
    toast(t('Birthday suggested.'));
  });
}

async function commonGroups(data) {
  const revision = state.accountRevision;
  const chats = await attempt(() => api('common_chats', { peer: data.id }));
  if (!chats || revision !== state.accountRevision) return;
  sheet(t('Groups in common'), chats.map((chat) => [chat.name, () => openChat(chat.id, true, chat)]));
}

// shared media of a chat ----------------------------------------------------------------
const SHARED_KINDS = [['photos', 'Photos and videos'], ['files', 'Files'], ['audio', 'Audio'], ['voice', 'Voice messages'], ['links', 'Links'], ['gifs', 'GIF'], ['polls', 'Encuestas']];
function openShared(data, kind) {
  state.shared = { peer: data.id, name: data.name, kind, items: null, account: state.account, revision: state.accountRevision };
  if (state.view === 'shared') render(); else go('shared');
  const shared = state.shared, revision = state.accountRevision;
  attempt(() => api('shared_media', {peer: data.id, kind, account: state.account}), (items) => {
    if (state.shared === shared && revision === state.accountRevision) {
      shared.items = items; shared.galleryDone = items.length < 50;
      if (state.view === 'shared') render();
    }
  });
}

function loadSharedPage(shared) {
  if (shared.loading) return shared.loading;
  if (shared.galleryDone || !shared.items?.length) return Promise.resolve();
  const before = shared.items[shared.items.length - 1].id;
  shared.loading = (async () => {
    const found = await api('shared_media', {account: shared.account, peer: shared.peer, kind: shared.kind, offset: before});
    if (state.shared !== shared || state.accountRevision !== shared.revision || state.locked) return;
    const older = found.filter(item => item.id < before);
    shared.items.push(...older);
    shared.galleryDone = !older.length || found.length < 50;
  })().finally(() => {shared.loading = null;});
  return shared.loading;
}

function sharedView() {
  const shared = state.shared;
  const bar = h('div', { class: 'bar' }, backButton(),
    h('div', { class: 'title' }, t('Shared media'), h('span', { class: 'sub' }, shared.name)), statusNode());
  const visual = ['photos', 'photos_only', 'videos'].includes(shared.kind);
  const tabs = h('div', { class: 'tabs' }, SHARED_KINDS.map(([kind, label]) => h('button', { class: 'tab' +
    (shared.kind === kind || (kind === 'photos' && visual) ? ' on' : ''),
    onclick: () => openShared({ id: shared.peer, name: shared.name }, kind) }, t(label))));
  let content;
  if (shared.items === null) content = h('div', { class: 'empty spinner' }, t('Cargando...') + ' ');
  else if (!shared.items.length) content = h('div', { class: 'empty' }, t('Sin resultados.'));
  else if (visual || shared.kind === 'gifs') content = h('div', { class: 'grid' }, shared.items.map((message) =>
    h('button', { class: 'cell', onclick: () => viewer(message, shared.peer, shared), 'aria-label': t(message.kind === 'video' ? 'Vídeo' : 'Foto') + ' ' + (message.time || '') },
      state.settings?.photo_previews === false ? t(message.kind === 'video' ? 'Vídeo' : 'Foto') :
        h('img', { loading: 'lazy', alt: '', src: mediaUrl(shared.peer, message.id, true) }))));
  else content = h('div', {}, shared.items.map((message) => {
    const text = (message.filename || message.caption || message.text || '').replace(/\s+/g, ' ');
    const links = shared.kind === 'links' ? (message.text || '').match(LINK) || [] : [];
    return h('div', { class: 'row', role: 'button', onclick: () => {
      if (links.length) openUrl(/^https?:/i.test(links[0]) ? links[0] : 'https://' + links[0]);
      else openFile(message, shared.peer);
    } }, h('div', { class: 'body' }, h('div', { class: 'top' }, h('span', { class: 'name' }, text || message.kind),
      h('span', { class: 'when' }, shortTime(message.date))), h('div', { class: 'bottom' }, h('span', { class: 'preview' }, message.sender))));
  }));
  const filters = visual ? h('div', {class: 'tabs shared-filters', role: 'group', 'aria-label': t('Media type')},
    [['photos', 'All'], ['photos_only', 'Photos'], ['videos', 'Videos']].map(([kind, label]) =>
      h('button', {type: 'button', class: 'tab' + (shared.kind === kind ? ' on' : ''),
        'aria-pressed': String(shared.kind === kind),
        onclick: () => openShared({id: shared.peer, name: shared.name}, kind)}, t(label)))) : null;
  const more = shared.items?.length && !shared.galleryDone ? button(t('Load more'), async () => {
    more.disabled = true;
    const scroll = more.closest('.scroll'), top = scroll?.scrollTop;
    await attempt(() => loadSharedPage(shared));
    if (state.shared === shared && state.view === 'shared') {
      render();
      const replacement = document.getElementById('shared-scroll');
      if (replacement && top !== undefined) replacement.scrollTop = top;
    }
  }) : null;
  return [bar, tabs, filters, h('div', { class: 'scroll', id: 'shared-scroll' }, content, more)];
}

// settings -------------------------------------------------------------------------
// devices (Settings › Accounts) --------------------------------------------------------
function devicesView() {
  const account = state.account, revision = state.accountRevision;
  const list = h('div', { class: 'scroll', id: 'devicelist' }, h('div', { class: 'empty' }, t('Cargando...')));
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  const when = (stamp) => stamp ? new Date(stamp * 1000).toLocaleString(state.language || undefined,
    { dateStyle: 'short', timeStyle: 'short' }) : '—';
  const draw = (data) => {
    const box = list;
    if (!current() || !box.isConnected || document.getElementById('devicelist') !== box) return;
    const row = (item) => h('div', { class: 'device' + (item.current ? ' current' : '') },
      h('div', { class: 'name' }, item.device || item.app || t('Devices')),
      h('div', { class: 'muted small' }, [item.app, [item.platform, item.system].filter(Boolean).join(' '), item.place, item.ip].filter(Boolean).join(' · ')),
      h('div', { class: 'muted small' }, t('Last active: {time}', { time: when(item.active) }) + ' · ' + t('Signed in: {time}', { time: when(item.created) })),
      item.current ? null : h('div', { class: 'device-actions' },
        ...[['calls', 'Accept calls'], ['secret_chats', 'Accept secret chats']].map(([key, label]) => {
          const [node, input] = check(t(label), item[key]);
          input.onchange = () => attempt(() => api('device_flags', { hash: item.hash, [key]: input.checked }))
            .then((ok) => { if (ok === undefined) input.checked = !input.checked; });
          return node;
        }),
        button(t('End session'), () => confirmThen((item.device || item.app) + ' — ' + t('Sign this device out of Telegram?'),
          () => attempt(() => api('device_end', { hash: item.hash }), () => { toast(t('Session ended.')); reload(); })), 'danger')));
    const mine = data.sessions.filter((item) => item.current), others = data.sessions.filter((item) => !item.current);
    const ttl = h('select', { onchange: (event) => attempt(() => api('devices_ttl', { days: Number(event.target.value) })) },
      [7, 30, 90, 183, 365].map((days) => h('option', { value: days, selected: days === data.ttl_days }, t('{days} days', { days }))));
    box.replaceChildren(
      h('div', { class: 'section' }, h('h4', {}, t('This device')), ...mine.map(row)),
      h('div', { class: 'section' }, h('h4', {}, t('Other sessions')),
        others.length ? others.map(row) : h('div', { class: 'muted' }, t('No other sessions.')),
        others.length ? button(t('End all other sessions'), () => confirmThen(t('Sign out every other device? Only this one stays signed in.'),
          () => attempt(() => api('devices_end_others'), () => { toast(t('Session ended.')); reload(); })), 'danger') : null),
      h('div', { class: 'section' }, h('div', { class: 'setting' }, h('span', {}, t('End inactive sessions after')), ttl)),
      h('div', { class: 'section' }, h('div', { class: 'muted small' }, t('Scan the login QR code shown on another device to sign it in with this account.')),
        button(t('Scan QR code'), () => scanLogin(reload), 'primary'), button(t('From a photo'), () => scanLoginPhoto(reload))));
  };
  const reload = () => current() && attempt(() => api('devices'), draw);
  reload();
  return [h('div', { class: 'bar' }, backButton(), h('div', { class: 'title' }, t('Devices')), statusNode()), list];
}

// A Telegram login QR (another phone, a computer, a watch): sign that device in here.
function approveScanned(result, done) {
  if (!result || !result.text) return;
  if (!result.login) { toast(t('This is not a Telegram login code.'), 'error'); return; }
  const account = state.accounts.find((item) => item.current) || {};
  confirmThen(t('Sign in the device showing this code with {account}? Only scan codes from your own devices.',
    { account: account.alias || account.label || '' }), () => attempt(() => api('approve_login', { url: result.text }), () => {
    toast(t('Device signed in.')); if (done) done();
  }), 'primary');
}
function scanLogin(done) {
  keepUnlocked(180);
  const params = new URLSearchParams(location.search);
  const origin = params.get('platform') === 'iOS' && params.get('window') === '1'
    ? { window_peer: Number(params.get('chat')), window_account: params.get('account') } : {};
  attempt(() => api('scan_qr', origin), (result) => approveScanned(result, done));
}
async function pickOnePhoto() {
  const revision = state.accountRevision;
  const current = () => revision === state.accountRevision && !state.locked;
  keepUnlocked(120);
  const accept = files => {
    const keep = current() ? files.slice(0, 1) : [];
    const discarded = files.slice(keep.length);
    if (discarded.length) api('discard_files', {keys: discarded.map(file => file.key)}).catch(() => {});
    return keep[0] || null;
  };
  if (PLATFORM === 'Android') return accept(await api('pick_files', {kind: 'gallery'}));
  return new Promise((resolve, reject) => {
    const input = h('input', {type: 'file', accept: 'image/*', hidden: true});
    input.addEventListener('cancel', () => {input.remove(); resolve(null);}, {once: true});
    input.addEventListener('change', async () => {
      const file = input.files[0]; input.remove();
      if (!file || !current()) return resolve(null);
      try {
        const response = await fetch('/upload?' + resourceAuth() + '&name=' + encodeURIComponent(file.name),
          {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file});
        if (!response.ok) throw new Error('HTTP ' + response.status);
        resolve(accept([(await response.json()).result]));
      } catch (error) { reject(error); }
    }, {once: true});
    document.body.append(input); input.click();
  });
}

async function scanLoginPhoto(done) {
  try {
    const file = await pickOnePhoto();
    if (!file) return;
    const result = await api('scan_qr_photo', { key: file.key });
    if (!result.text) { toast(t('No QR code found in this photo.'), 'error'); return; }
    approveScanned(result, done);
  } catch (error) { toast(error.message, 'error'); }
}

// Settings in sections, as on the desktop (Settings › category list).
// The reaction of a double tap on a message (desktop: quick reaction), standard
// or custom emoji; also Telegram's default reaction for the official apps.
function defaultReactionSetting() {
  const value = String((state.settings && state.settings.quick_reaction) || '👍');
  const shown = reactionEmoji(value);
  return h('div', { class: 'setting' }, h('span', {}, t('Default reaction')),
    h('button', { class: 'btn', onclick: chooseDefaultReaction }, shown));
}

async function chooseDefaultReaction() {
  const account = state.account;
  const data = await attempt(() => api('default_reaction_choices'));
  if (!data || account !== state.account) return;
  const choose = (value) => {
    if (state.account !== account) return;
    return attempt(() => api('set_default_reaction', {value, account}), (result) => {
      if (state.account !== account) return;
      state.settings.quick_reaction = result.current;
      closeSheet();
      if (state.view === 'settings') render();
      toast(result.synced ? t('Saved.') : t('Saved.') + ' · ' + t('This device'));
    });
  };
  const layer = document.getElementById('sheet-layer');
  const grid = h('div', { class: 'sticker-grid emoji' }, ...data.standard.map((emoji) =>
    h('button', { class: 'sticker-cell standard-emoji' + (emoji === data.current ? ' on' : ''), onclick: () => choose(emoji) }, emoji)),
    ...data.custom.map((id) => h('button', { class: 'sticker-cell' + (id === data.current ? ' on' : ''), onclick: () => choose(id) }, customEmoji(id, '◆', false))));
  layer.replaceChildren(h('div', { class: 'sheet tall', onclick: (event) => event.stopPropagation() },
    h('h3', {}, t('Default reaction')), grid,
    h('button', { class: 'item', onclick: () => stickerPicker(true, (doc) => choose(String(doc.id))) }, t('Custom emoji') + '…'),
    h('button', { class: 'item', onclick: closeSheet }, t('Cancelar'))));
  activateSheet(layer);
  layer.onclick = closeSheet;
}

// Ajustes › Funciones complejas (desktop: advanced_features.FEATURES), same store.
const MOBILE_FEATURES = [
  ['media_originals', 'Original media in the viewer', 'Show photos at the highest quality available from Telegram, without recompression. Previews stay small. Uses more data and memory.'],
  ['native_liquid_glass', 'Native Liquid Glass', 'Use native Apple glass controls on iOS 26 or later. Respects Reduce Transparency and Reduce Motion. Off by default.'],
  ['polls', 'Encuestas y cuestionarios', 'Crear, votar y consultar resultados.'],
  ['checklists', 'Listas de tareas', 'Crear y editar listas compartidas; requiere Premium para crearlas.'],
  ['contacts', 'Compartir contactos', 'Elegir los datos de contacto que se enviarán.'],
  ['articles', 'Artículos', 'Crear y abrir publicaciones largas.'],
  ['stars_gifts', 'Estrellas y regalos', 'Catálogo, regalos, reacciones de pago y enlaces oficiales de compra.'],
  ['links', 'Enlaces, menciones y etiquetas', 'Abrir enlaces de Telegram, perfiles y búsquedas de hashtags.'],
  ['stories', 'Historias y publicaciones del perfil', 'Consultar y publicar historias sólo al abrir su sección.'],
  ['chat_translation', 'Traducción de chats', 'Traducir el historial del chat seleccionado con Telegram Premium.'],
  ['call_history', 'Registro de llamadas', 'Consultar el historial de llamadas al abrir su pestaña.'],
  ['calls', 'Calls and video', 'Enable calls in Complex features. Microphone and camera start only when you call or answer.'],
  ['chat_list_activity', 'Activity in the chat list', 'Shows ● when a contact is online and ··· while someone is typing, between the chat name and its unread counter.'],
  ['contact_list_details', 'Contact list details', 'Shows profile photo, activity status and Premium emoji status in the contact list.'],
  // 3.0.0.2, off by default.
  ['keep_loaded', 'Keep more loaded', 'TeleGraph works like an installed messaging app: profile photos, recent messages, previews and contact details stay ready on this device and screens open from them at once. Only what is really new is asked again. Uses more storage and memory.'],
  ['preload_startup', 'Prepare content at startup', 'Once the chat list loads, profile photos, the latest messages of your first chats, their previews and emoji are prepared in the background. Uses more data and battery at startup.'],
];
function switchSetting(label, enabled, change) {
  return h('div', { class: 'setting' }, h('span', {}, label),
    h('button', { class: 'btn toggle', role: 'switch', 'aria-label': label,
      'aria-checked': String(Boolean(enabled)), onclick: change }, enabled ? 'x' : ' '));
}

// Off unless turned on (the rest are on unless turned off).
const FEATURES_OFF = new Set(['keep_loaded', 'preload_startup', 'media_originals', 'native_liquid_glass']);
function complexFeatures(save) {
  const enabled = (state.settings && state.settings.advanced_features) || {};
  const on = (key) => FEATURES_OFF.has(key) ? enabled[key] === true : enabled[key] !== false;
  return h('div', { class: 'section' }, ...MOBILE_FEATURES.filter(([key]) => key !== 'native_liquid_glass' || PLATFORM === 'iOS').map(([key, label, note]) => h('div', { class: 'setting column' },
    switchSetting(t(label), on(key), () => save({ advanced_features: { [key]: !on(key) } })),
    h('div', { class: 'muted small' }, t(note)))));
}

const SETTINGS_SECTIONS = [['appearance', 'Apariencia'], ['customization', 'Customization'], ['chats', 'Chats'],
  ['notifications', 'Notifications'], ['account', 'Cuenta'], ['premium', 'Telegram Premium'], ['logos', 'App logos'],
  ['advanced', 'Funciones complejas'], ['data', 'App data']];
function logoSettings() {
  const account = state.account, revision = state.accountRevision;
  const isCurrent = () => state.account === account && state.accountRevision === revision && !state.locked;
  const look = state.appearance;
  const holder = h('div', {class: 'setting column'}, t('Cargando...'));
  const load = async () => {
    const catalogue = state.logoCatalogue || await attempt(() => api('logo_catalogue'));
    if (!catalogue) {
      holder.replaceChildren(button(t('Reintentar'), load));
      return;
    }
    state.logoCatalogue = catalogue;
    if (!holder.isConnected) return;
    const current = look.brand_logo || {};
    const select = (choices, value) => h('select', {onchange: draw}, choices.map(([key, label]) =>
      h('option', {value: key, selected: key === value}, label)));
    const paletteLabels = {default: t('Default'), light: t('Light'), orange: t('Orange'),
      blue: t('Blue'), red: t('Red'), pink: t('Pink'), monochrome: t('Monochrome')};
    const variant = select(catalogue.variants, current.variant);
    const color = select(catalogue.colors.map(key => [key, paletteLabels[key]]), current.color);
    const theme = select([['dark', t('Oscuro')], ['light', t('Claro')]], current.theme);
    const preview = h('img', {class: 'logo logo-preview', alt: 'TeleGraph'});
    const settings = () => ({variant: variant.value, color: color.value, theme: theme.value});
    function draw() {
      preview.src = brandUrl(settings());
      preview.alt = variant.options[variant.selectedIndex].text;
    }
    holder.replaceChildren(h('h4', {}, 'TeleGraph'), variant, color, theme, preview,
      button(t('Apply'), () => saveLook({brand_logo: settings(), apply_native_logo: TOUCH})),
      h('span', {class: 'muted'}, t('Selected') + ': ' +
        (look.brand_photo ? t('Image') :
          (catalogue.variants.find(([key]) => key === current.variant)?.[1] || 'Tg-Gr') + ' · ' +
          (paletteLabels[current.color] || t('Default')) + ' · ' + t(current.theme === 'light' ? 'Claro' : 'Oscuro'))));
    draw();
  };
  setTimeout(load, 0);
  const photo = async () => {
    if (!isCurrent()) return;
    let key;
    try { key = await pickImage(); } catch (error) { if (isCurrent()) toast(error.message, 'error'); return; }
    if (!key) return;
    if (!isCurrent()) { api('discard_files', {keys: [key]}).catch(() => {}); return; }
    try {
      const result = await api('set_logo_photo', {key, account});
      if (isCurrent()) { state.appearance = result; render(); }
    } catch (error) { if (isCurrent()) toast(error.message, 'error'); }
  };
  return [holder, h('div', {class: 'setting'}, button(t('Image'), photo),
    look.brand_photo ? button(t('Remove'), () => saveLook({brand_photo: ''})) : null)];
}

async function notificationOptions(params = {}) {
  const revision = state.accountRevision;
  const [current, ringtones] = await Promise.all([
    attempt(() => api('notify_preferences', params)),
    api('ringtones').catch(() => []),
  ]);
  if (current && revision === state.accountRevision && !state.locked) return {current, ringtones};
}

async function chatNotifications(chat) {
  const account = state.account;
  const options = await notificationOptions({peer: chat.id});
  if (options) notificationForm(chat.name, chat.id, options.current, account, options.ringtones);
}

function notificationFailureDetails(status, kind = 'error') {
  // Never render an exception message or an arbitrary value from the bridge.
  const causes = {
    permission_denied: 'El sistema no ha autorizado los avisos.',
    permission_not_requested: 'Falta solicitar el permiso de notificaciones.',
    permission_query_failed: 'No se pudo consultar el permiso de notificaciones del sistema.',
    privacy_registration: 'Telegram no confirmó los ajustes de privacidad de los avisos.',
    registration_rejected: 'Telegram no confirmó el registro de este dispositivo.',
    registration_error: 'La activación falló por un error no identificado.',
    TimeoutError: 'No se recibió a tiempo una respuesta a la solicitud.',
    ConnectionError: 'La conexión falló durante la solicitud.',
    ConnectionResetError: 'La conexión falló durante la solicitud.',
    ConnectionAbortedError: 'La conexión falló durante la solicitud.',
    BrokenPipeError: 'La conexión falló durante la solicitud.',
    OSError: 'La conexión falló durante la solicitud.',
    TypeError: 'La app no pudo preparar o procesar la solicitud.',
    ValueError: 'La app no pudo preparar o procesar la solicitud.',
    RuntimeError: 'La app no pudo preparar o procesar la solicitud.',
    RPCError: 'Telegram devolvió un error al procesar la solicitud.',
    BadRequestError: 'Telegram devolvió un error al procesar la solicitud.',
    ServerError: 'Telegram devolvió un error al procesar la solicitud.',
    RpcCallFailError: 'Telegram devolvió un error al procesar la solicitud.',
    TokenInvalidError: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TokenEmptyError: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TokenTypeInvalidError: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TokenWasInvalidatedError: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TOKEN_EMPTY: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TOKEN_INVALID: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TOKEN_TYPE_INVALID: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    TOKEN_WAS_INVALIDATED: 'Telegram rechazó el identificador de notificaciones del dispositivo.',
    AppPushApiKeyMissingError: 'Falta la configuración del proveedor de notificaciones de esta app en Telegram.',
    APP_PUSH_APIKEY_MISSING: 'Falta la configuración del proveedor de notificaciones de esta app en Telegram.',
    AuthKeyUnregisteredError: 'Telegram no pudo validar la sesión de esta cuenta.',
    AuthKeyInvalidError: 'Telegram no pudo validar la sesión de esta cuenta.',
    AuthKeyDuplicatedError: 'Telegram no pudo validar la sesión de esta cuenta.',
    SessionRevokedError: 'Telegram no pudo validar la sesión de esta cuenta.',
    SessionExpiredError: 'Telegram no pudo validar la sesión de esta cuenta.',
    FloodWaitError: 'Telegram ha limitado temporalmente estas solicitudes.',
    FloodPremiumWaitError: 'Telegram ha limitado temporalmente estas solicitudes.',
  };
  const raw = typeof status.error === 'string' ? status.error : '';
  const appleCode = /^APNs_-?\d{1,10}$/.test(raw);
  const code = appleCode || Object.prototype.hasOwnProperty.call(causes, raw) ? raw : null;
  const phases = {
    permission: 'Paso: permiso de notificaciones del sistema.',
    native: status.provider === 'APNs' ? 'Paso: registro del dispositivo con Apple.'
      : 'Paso: registro del dispositivo con el sistema.',
    privacy: 'Paso: privacidad de los avisos en Telegram.',
    telegram: 'Paso: registro con Telegram.',
  };
  const fallback = code?.startsWith('permission_') ? 'permission'
    : code === 'privacy_registration' ? 'privacy' : appleCode ? 'native' : code ? 'telegram' : null;
  const phase = Object.prototype.hasOwnProperty.call(phases, status.phase) ? status.phase : fallback;
  return [
    h('p', {}, t(phases[phase] || 'Paso: activación de las notificaciones.')),
    h('p', {class: kind}, t(appleCode ? 'Apple no pudo registrar el dispositivo para recibir avisos.'
      : code ? causes[code] : 'No hay un código de error disponible para esta comprobación.')),
    code ? h('p', {class: 'muted small'}, t('Código: {code}.', {code})) : null,
  ].filter(Boolean);
}

function checkNotificationStatus() {
  const account = state.account, revision = state.accountRevision;
  const layer = document.getElementById('sheet-layer');
  const result = h('div', {'aria-live': 'polite'});
  const refresh = button(t('Actualizar'), load);
  const panel = h('div', {class: 'sheet form', onclick: event => event.stopPropagation()},
    h('h3', {}, t('Comprobar notificaciones')), result,
    h('p', {class: 'muted small'}, t('Esta comprobación consulta el registro. No envía una notificación de prueba.')),
    h('div', {class: 'actions'}, refresh, button(t('Close'), closeSheet)));
  layer.replaceChildren(panel); activateSheet(layer); layer.onclick = closeSheet;
  async function load() {
    refresh.disabled = true;
    result.replaceChildren(h('p', {}, t('Cargando...')));
    const current = () => currentSheetPanel === panel && state.account === account &&
      state.accountRevision === revision && !state.locked;
    try {
      const status = await api('notification_status');
      if (!current()) return;
      const registered = Number.isInteger(status.registered_accounts) ? status.registered_accounts : 0;
      const connected = Number.isInteger(status.connected_accounts) ? status.connected_accounts : 0;
      const disabled = state.settings.notifications === false || status.state === 'disabled';
      const accepted = status.state === 'registered' && registered > 0 && connected > 0 && registered >= connected;
      const failed = !disabled && ['retrying', 'unavailable'].includes(status.state);
      const text = disabled ? t('Las notificaciones están desactivadas en esta app.')
        : accepted ? t('Telegram ha aceptado el registro de {count} cuenta(s).', {count: registered})
        : status.state === 'retrying' ? t('La activación de las notificaciones no se ha completado. La app volverá a intentarlo automáticamente.')
        : connected === 0 ? t('Conecta una cuenta para comprobar el registro de notificaciones.')
        : status.state === 'unavailable' ? t('No se pudo completar la activación de las notificaciones.')
        : t('Esperando a que se complete el registro de notificaciones.');
      result.replaceChildren(h('p', {}, text));
      if (failed) {
        result.append(h('p', {class: 'muted'}, t('Cuentas registradas en Telegram: {registered}. Cuentas conectadas: {connected}.',
          {registered, connected})), ...notificationFailureDetails(status));
      }
      const privacyWarning = !disabled && typeof status.privacy_warning === 'string' && status.privacy_warning;
      if (privacyWarning) {
        result.append(h('div', {class: 'notification-warning'},
          h('p', {}, t('Pendiente de confirmar la privacidad de los avisos. La app volverá a intentarlo; esto no anula los registros que Telegram ya ha aceptado.')),
          ...notificationFailureDetails({phase: 'privacy', error: privacyWarning}, 'muted')));
      }
      const permission = status.permission || (status.error === 'permission_denied' ? 'denied'
        : status.error === 'permission_not_requested' ? 'not_requested' : 'unknown');
      result.append(h('p', {class: permission === 'denied' ? 'error' : 'muted'},
        permission === 'denied' ? t('Permiso denegado. Activa las notificaciones en Ajustes del sistema.')
        : permission === 'not_requested' ? t('Todavía no se ha concedido permiso para las notificaciones.')
        : permission === 'granted' ? t('Permiso de notificaciones concedido por el sistema.')
        : t('Permiso del sistema: sin comprobar.')));
      if (status.provider === 'APNs' && status.token_received) {
        result.append(h('p', {class: 'muted'}, status.sandbox
          ? t('Entorno de Apple: desarrollo.') : t('Entorno de Apple: distribución.')));
      }
      if (accepted && !disabled && !privacyWarning && permission !== 'denied' && permission !== 'not_requested') {
        result.append(h('p', {class: 'muted'}, t('Si no aparecen avisos, revisa el permiso de notificaciones y los modos de concentración en Ajustes del sistema.')));
      }
    } catch (_) {
      if (current()) result.replaceChildren(h('p', {class: 'error'}, t('No se pudo consultar el estado. Vuelve a intentarlo.')));
    } finally {
      if (current()) refresh.disabled = false;
    }
  }
  load();
}

async function telegramNotifications() {
  const account = state.account;
  const revision = state.accountRevision;
  const options = await notificationOptions();
  if (!options) return;
  const {current, ringtones} = options;
  sheet(t('Telegram settings (synchronized)'), [
    [t('Private chats'), () => notificationForm(t('Private chats'), 'private', current.private, account, ringtones)],
    [t('Groups'), () => notificationForm(t('Groups'), 'groups', current.groups, account, ringtones)],
    [t('Channels'), () => notificationForm(t('Channels'), 'channels', current.channels, account, ringtones)],
    [t('Exceptions'), async () => {
      const chats = await attempt(() => api('notify_exceptions'));
      if (!chats || revision !== state.accountRevision || state.locked) return;
      if (!chats.length) toast(t('Sin resultados.'));
      else sheet(t('Exceptions'), chats.map(chat => [chat.name, () => chatNotifications(chat)]));
    }],
    [t('Reactions'), () => reactionNotifications(account, ringtones)],
    [t('Reset all notifications'), () => confirmThen(t('Reset every notification setting, exceptions included, to Telegram’s defaults?'),
      () => attempt(() => api('notify_reset', { account }), () => toast(t('Saved.'))))],
  ]);
}

function notificationForm(title, target, current, account, ringtones) {
  const revision = state.accountRevision;
  const isCurrent = () => state.account === account && state.accountRevision === revision && !state.locked;
  const custom = h('input', {type: 'datetime-local', 'aria-label': t('Date')});
  const customField = labelled(t('Date'), custom);
  customField.hidden = true;
  const muteOptions = [
    ['keep', current.mute_until > Date.now() / 1000 && current.mute_until < 2147483647
      ? new Date(current.mute_until * 1000).toLocaleString(state.language)
      : current.mute_until >= 2147483647 ? t('Forever') : t('Settings')],
    ['0', t('Activar sonido')], ['3600', t('For 1 hour')], ['86400', t('For 1 day')],
    ['604800', t('For 7 days')], ['forever', t('Forever')], ['date', t('Date')],
  ];
  const mute = h('select', {onchange: () => { customField.hidden = mute.value !== 'date'; }},
    muteOptions.map(([value, text]) => h('option', {value}, text)));
  const rows = [
    ['show_previews', t('Preview'), true],
    ['silent', t('Silent'), false],
    ['stories_muted', t('Mute stories'), false],
    ['stories_hide_sender', t('Hide sender'), false],
  ].map(([key, label, fallback]) => {
    const original = current[key] ?? fallback;
    const [node, input] = check(label, original);
    return {node, input, key, original};
  });
  const sounds = [['sound', t('Sound')], ['stories_sound', t('Stories') + ' · ' + t('Sound')]]
    .map(([key, label]) => {
      const select = notificationSound(current[key], ringtones);
      return {key, select, node: labelled(label, select)};
    });
  let saving = false;
  formSheet(title, [labelled(t('Mute until'), mute), customField,
    ...rows.map(row => row.node), ...sounds.map(sound => sound.node)], t('Guardar'), async () => {
    if (saving || !isCurrent()) return false;
    const changes = Object.fromEntries(rows.filter(row => row.input.checked !== row.original)
      .map(row => [row.key, row.input.checked]));
    for (const {key, select} of sounds) if (select.value) changes[key] = select.value;
    if (mute.value === 'forever') changes.mute_until = 2147483647;
    else if (mute.value === 'date') {
      const stamp = Math.floor(new Date(custom.value).getTime() / 1000);
      if (!Number.isFinite(stamp) || stamp <= Date.now() / 1000 || stamp > 2147483647) {
        toast(t('Invalid date'), 'error');
        return false;
      }
      changes.mute_until = stamp;
    } else if (mute.value !== 'keep') {
      changes.mute_until = Number(mute.value) ? Math.floor(Date.now() / 1000) + Number(mute.value) : 0;
    }
    if (!Object.keys(changes).length) return true;
    saving = true;
    try {
      const result = await attempt(() => api('save_notify_preferences', {target, changes, account}));
      if (!isCurrent()) return false;
      if (result && typeof target === 'number' && 'mute_until' in changes) {
        const chat = state.chats.find(item => item.id === target);
        if (chat) chat.muted = changes.mute_until > 0;
        if (state.open?.peer === target) state.open.chat.muted = changes.mute_until > 0;
        if (state.profile?.id === target) refreshProfile();
        drawChatList();
      }
      return Boolean(result);
    } finally {
      saving = false;
    }
  });
}

function notificationSound(current, ringtones) {
  const label = {none: t('Off'), default: t('Default'), custom: t('Custom')};
  const named = ringtones.find(item => item.id === current);
  return h('select', {},
    h('option', {value: ''}, named ? '♪ ' + named.title : label[current] || t('Settings')),
    current !== 'default' ? h('option', {value: 'default'}, t('Default')) : null,
    current !== 'none' ? h('option', {value: 'none'}, t('Off')) : null,
    // The account's saved Telegram ringtones.
    ...ringtones.filter(item => item.id !== current).map(item => h('option', {value: item.id}, '♪ ' + item.title)));
}

async function reactionNotifications(account, ringtones) {
  const revision = state.accountRevision;
  const current = await attempt(() => api('notify_reactions_and_contacts'));
  if (!current || state.account !== account || revision !== state.accountRevision || state.locked) return;
  const scopes = [['off', t('Off')], ['contacts', t('Contacts only')], ['all', t('Everyone')]];
  const rows = [['messages', t('Messages')], ['stories', t('Stories')], ['poll_votes', t('Polls')]].map(([key, label]) => {
    const select = h('select', {}, scopes.map(([value, name]) =>
      h('option', {value, selected: current.reactions[key] === value}, name)));
    return {key, select, node: labelled(label, select)};
  });
  const [previewLabel, preview] = check(t('Preview'), current.reactions.show_previews);
  const [contactsLabel, contacts] = check(t('Contact joined Telegram'), current.contacts_joining);
  const sound = notificationSound(current.reactions.sound, ringtones);
  let saving = false;
  formSheet(t('Reactions'), [...rows.map(row => row.node), previewLabel, labelled(t('Sound'), sound), contactsLabel],
    t('Guardar'), async () => {
      if (saving || state.account !== account) return false;
      saving = true;
      try {
        const changes = Object.fromEntries(rows.filter(row => row.select.value !== current.reactions[row.key])
          .map(row => [row.key, row.select.value]));
        if (preview.checked !== current.reactions.show_previews) changes.show_previews = preview.checked;
        if (sound.value) changes.sound = sound.value;
        if (Object.keys(changes).length) {
          if (!await attempt(() => api('save_notify_reactions', {changes, account}))) return false;
          Object.assign(current.reactions, changes);
        }
        return contacts.checked === current.contacts_joining ||
          Boolean(await attempt(() => api('save_notify_contacts', {enabled: contacts.checked, account})));
      } finally {
        saving = false;
      }
    });
}

function editDisplayName() {
  const account = state.account, revision = state.accountRevision;
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  promptThen(t('Nombre visible de la app'), {value: state.settings?.app_display_name || '', placeholder: 'TeleGraph', maxlength: 64}, async value => {
    if (!current()) return false;
    const result = await attempt(() => api('settings', {values: {app_display_name: value.trim()}}));
    if (!result || !current()) return false;
    state.settings = result;
    applySettings();
    render();
  });
}

async function chooseSiriChats() {
  const account = state.account;
  const chats = await attempt(() => api('siri_chats', {account}));
  if (!chats || account !== state.account) return;
  const selected = new Set(chats.filter(chat => chat.selected).map(chat => chat.id));
  const search = h('input', {type: 'search', placeholder: t('Buscar'), 'aria-label': t('Buscar')});
  const list = h('div', {});
  const draw = () => {
    const query = search.value.trim().toLocaleLowerCase();
    list.replaceChildren(...chats.filter(chat => searchText(chat.name).includes(searchText(query))).map(chat => {
      const [row, checkbox] = check(chat.name, selected.has(chat.id));
      checkbox.onchange = () => checkbox.checked ? selected.add(chat.id) : selected.delete(chat.id);
      return row;
    }));
  };
  search.oninput = draw;
  draw();
  const controls = bulkButtons(() => { chats.forEach(chat => selected.add(chat.id)); draw(); }, () => { selected.clear(); draw(); });
  formSheet(t('Nombres de chats para Siri'), [
    h('p', {}, t('Siri podrá usar los nombres de los chats que selecciones en esta cuenta.')), search, controls, list,
  ], t('Guardar'), async () => {
    if (state.account !== account || state.locked) return false;
    return Boolean(await attempt(() => api('siri_chats', {account, peers: [...selected]})));
  });
}

function settingsView() {
  const settings = state.settings;
  const account = state.account, revision = state.accountRevision;
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  const tab = SETTINGS_SECTIONS.some(([key]) => key === state.settingsTab) ? state.settingsTab : 'appearance';
  const save = (values) => attempt(() => api('settings', { values }), async (result) => {
    if (!current()) return;
    const languageChanged = values.language && values.language !== state.language;
    state.settings = result; applySettings();
    if (languageChanged) { await resync(); go('settings'); } else render();
  });
  const toggle = (key, label) => switchSetting(label, settings[key], () => save({ [key]: !settings[key] }));
  const lookToggle = (key, label) => switchSetting(label, (state.appearance || {})[key], () => saveLook({ [key]: !(state.appearance || {})[key] }));
  const select = (key, label, options) => {
    const node = h('select', { 'aria-label': label, onchange: (event) => save({ [key]: isNaN(options[0][0]) ? event.target.value : Number(event.target.value) }) },
      options.map(([value, text]) => h('option', { value, selected: String(settings[key]) === String(value) }, text)));
    return h('div', { class: 'setting' }, h('span', {}, label), node);
  };
  const section = (title, ...children) => h('div', { class: 'section' }, title ? h('h4', {}, title) : null, ...children);
  const note = (text) => h('div', { class: 'muted small' }, text);
  const openSection = key => { state.settingsQuery = ''; state.settingsTab = key; render(); };
  const searchLinks = (key, title, labels) => section(t(title), ...labels.map(label => button(t(label), () => openSection(key))));
  const reset = (scope, label) => button(t(label), () => {
    const account = state.account, revision = state.accountRevision;
    confirmThen(
    t(scope === 'all'
      ? 'Se restablecerán todos los ajustes de esta app en este dispositivo. Tus cuentas, sesiones, mensajes y bloqueo de seguridad se conservarán. Los ajustes guardados en Telegram no cambiarán.'
      : 'Se restablecerán los ajustes de esta sección en este dispositivo. Tus cuentas, sesiones, mensajes y bloqueo de seguridad se conservarán. Los ajustes guardados en Telegram no cambiarán.'),
    async () => {
      await appearanceWrites;
      if (state.account !== account || state.accountRevision !== revision || state.locked) return;
      await attempt(() => api('reset_settings', {scope, account}), async result => {
        if (state.account !== account || state.accountRevision !== revision) return;
        state.settings = result.settings; state.appearance = result.appearance;
        state.language = result.settings.language;
        if (scope !== 'customization') state.windows.forEach((win, index) => Object.assign(win, defaultGeometry(index)));
        await loadStrings(); applySettings(); render();
      });
    });
  });
  const pages = {
    appearance: () => {
      const languages = h('div', { class: 'setting' }, h('span', {}, t('Idioma')), h('span', { class: 'muted' }, '...'));
      api('languages').then((list) => languages.replaceWith(select('language', t('Idioma'), list)));
      const look = appearanceSection(save);
      return [section(null, languages,
        h('div', {class: 'setting display-name-setting'}, h('span', {}, t('Nombre visible de la app')),
          button(settings.app_display_name || 'TeleGraph', editDisplayName),
          button(t('Restablecer nombre'), () => save({app_display_name: ''}))),
        select('theme', t('Tema'), [['dark', t('Oscuro')], ['light', t('Claro')], ['system', t('Sistema')]]),
        h('div', {class: 'setting effect-setting'}, h('span', {}, t('Tamaño de letra')),
          numericSlider(t('Tamaño de letra'), settings.font_size || 12, settings.font_min || 8, settings.font_max || 40, value => save({font_size: value}))),
        ...look.colors, look.typeface, toggle('bubbles', t('Burbujas')), look.view, look.reset), window.tgPresentation?.settings(),
        section(null, reset('appearance', 'Restablecer ajustes de apariencia'))];
    },
    customization: () => {
      const look = appearanceSection(save);
      return [section(null, button(t('App logos'), () => { state.settingsTab = 'logos'; render(); }),
          ['Android', 'iOS'].includes(PLATFORM) ? lookToggle('native_dialogs', t('Usar más diálogos del sistema')) : null,
          toggle('reduce_animations', t('Disable all animations')),
          note(t('Animated emoji, stickers, transitions and effects stay still, so the app runs smoothly on slower devices. Off by default.'))),
        section(t('Corners'), ...look.corners), section(t('Backgrounds'), ...look.backgrounds), effectsSection(),
        section(null, reset('customization', 'Restablecer ajustes de personalización'))];
    },
    chats: () => [section(null, defaultReactionSetting(), toggle('bubbles', t('Burbujas')), toggle('ascii_text', t('Mostrar el texto solo en ASCII')),
      toggle('local_pins', t('Unlimited local pins (device only)')),
      toggle('show_seconds', t('Mostrar segundos en la hora')), toggle('animated_emoji', t('Animated emoji')),
      toggle('inline_media', t('Show media previews inside chats')), toggle('photo_previews', t('Previsualizar las fotos')),
      ...[['swipe_right', 'Al deslizar un chat hacia la derecha'], ['swipe_left', 'Al deslizar un chat hacia la izquierda']]
        .map(([key, title]) => h('label', {class: 'setting'}, h('span', {}, t(title)),
          h('select', {onchange: e => saveLook({[key]: e.target.value})}, swipeOptions.map(([value, label]) =>
            h('option', {value, selected: state.appearance[key] === value}, t(label)))))),
      toggle('offline_copy', t('Guardar una copia para usar sin conexion')))],
    notifications: () => [section(null, toggle('notifications', t('Notificaciones')),
      toggle('notify_preview', t('Preview')),
      toggle('notify_sound', t('Play a sound')),
      toggle('notify_active', t('Notify for the open chat')),
      ['Android', 'iOS'].includes(PLATFORM) ? button(t('Comprobar notificaciones'), checkNotificationStatus) : null,
      button(t('Telegram settings (synchronized)'), telegramNotifications),
      ['Android', 'iOS'].includes(PLATFORM) ? lookToggle('keep_connected', t('Keep connected in the background')) : null,
      PLATFORM === 'Android' ? note(t('Android keeps TG-ASCII connected with a permanent notification, so new messages arrive with the app closed. Uses more battery.')) : null)],
    account: (searching = false) => [searching ? searchLinks('account', 'My profile', ['First name', 'Last name', 'Username', 'Bio']) : myProfileSection(), accountsSection(toggle), lockSection(),
      PLATFORM === 'iOS' ? section('Siri', button(t('Nombres de chats para Siri'), chooseSiriChats)) : null],
    premium: (searching = false) => [searching ? searchLinks('premium', 'Telegram Premium', [
      'Emoji status', 'Name color', 'Profile color', 'Privacy', 'Hide read time',
      'Only contacts and Premium users can message me', 'Archive and mute new chats from non-contacts',
      'Automatic translation (Premium)', 'Transcribe audio', 'Custom emoji', 'Custom reactions', 'Read time', 'Show folder tags (Premium)']) : premiumSection()],
    logos: () => [section(null, ...logoSettings())],
    advanced: () => [complexFeatures(save), section(null, lookToggle('watch_own', t('Watch with its own connection')),
      note(t('The watch connects to Telegram by itself, with its own session approved by this app, and keeps working with the phone off. Off: the watch shows what this app receives.')))],
    data: (searching = false) => {
      const cache = h('span', { class: 'muted' }, '');
      if (!searching) api('cache_size').then((size) => { if (current()) cache.textContent = size; }).catch(() => {});
      return [section(null, h('div', { class: 'setting' }, h('span', {}, t('Caché')), cache),
        button(t('Borrar caché'), () => attempt(() => api('clear_cache'), (freed) => { toast(t('Liberado: {size}', { size: freed })); render(); })),
        ...appLifeItems().map(([label, action, kind]) => button(label, action, kind || '')),
        reset('all', 'Restablecer todos los ajustes'),
        button(t('Borrar todos los datos'), () => confirmThen(t('¿Borrar todos los datos? Se cerraran todas las sesiones de este dispositivo.'), () => attempt(() => api('delete_all'))), 'danger')),
        section(t('Acerca de'), h('div', { class: 'muted' }, 'TeleGraph ' + state.version + ' · ' + PLATFORM),
          button(t('Política de privacidad'), () => openUrl('https://github.com/MiguelCKxd/TeleGraph/blob/main/PRIVACIDAD.md')))];
    },
  };
  const tabs = h('div', {class: 'tabs settings-tabs'}, SETTINGS_SECTIONS.map(([key, label]) =>
    h('button', {class: 'tab' + (key === tab ? ' on' : ''), onclick: () => openSection(key)}, t(label))));
  const scroll = h('div', {class: 'scroll', id: 'settings-scroll'});
  const search = h('input', {type: 'search', 'data-search-scope': 'settings', placeholder: t('Buscar en ajustes'),
    'aria-label': t('Buscar en ajustes'), value: state.settingsQuery || ''});
  const sections = new Map();
  const content = (key, searching = false) => {
    // Index server-backed options by their labels. Searching local settings
    // must not request account/Premium data or recursively measure the cache.
    const indexOnly = searching && ['account', 'premium', 'data'].includes(key);
    const cacheKey = (indexOnly ? 'search:' : '') + key;
    if (!sections.has(cacheKey)) sections.set(cacheKey, pages[key](indexOnly).filter(Boolean));
    return sections.get(cacheKey);
  };
  function filter() {
    const terms = searchText(search.value).split(/\s+/).filter(Boolean);
    state.settingsQuery = search.value;
    tabs.hidden = !!terms.length;
    if (!terms.length) {
      const nodes = content(tab);
      for (const node of nodes) {
        node.hidden = false;
        for (const row of node.children) row.hidden = false;
      }
      scroll.replaceChildren(...nodes);
      return;
    }
    const matches = [];
    for (const [key, label] of SETTINGS_SECTIONS) {
      for (const section of content(key, true)) {
        let hit = false;
        const title = section.querySelector('h4')?.textContent || '';
        for (const row of section.children) {
          if (row.matches('h4')) continue;
          const text = searchText([t(label), title, row.textContent, row.getAttribute('aria-label')].join(' '));
          row.hidden = !terms.every(term => text.includes(term));
          if (!row.hidden) hit = true;
        }
        if (hit) matches.push(section);
      }
    }
    scroll.replaceChildren(...(matches.length ? matches : [h('p', {class: 'empty'}, t('Sin resultados.'))]));
  }
  search.addEventListener('input', filter);
  filter();
  requestAnimationFrame(() => {
    if (!tabs.isConnected || tabs.hidden) return;
    const selected = tabs.querySelector('.on');
    if (!selected) return;
    const item = selected.getBoundingClientRect(), strip = tabs.getBoundingClientRect();
    // Only the tab strip should move; scrollIntoView can also pan the iOS page/keyboard.
    tabs.scrollLeft += item.left - strip.left - (strip.width - item.width) / 2;
  });
  return [h('div', {class: 'bar'}, backButton(), h('div', {class: 'title'}, t('Ajustes')), statusNode()),
    h('div', {class: 'search'}, search), tabs, scroll];
}

function accountsSection(toggle) {
  return h('div', { class: 'section' }, h('h4', {}, t('Cuentas')),
    state.accounts.map((item, index) => h('div', { class: 'account' + (item.current ? ' current' : '') },
      h('span', { class: 'label' }, (item.alias ? item.alias + ' (' + item.label + ')' : item.label || '…') + (item.failure ? ' · ' + item.failure : '')),
      item.current ? null : button(t('Usar'), () => switchAccount(item.key)),
      index ? button('↑', () => { const keys = state.accounts.map((a) => a.key); keys.splice(index - 1, 0, keys.splice(index, 1)[0]);
        attempt(() => api('account.reorder', { keys }), (list) => { state.accounts = list; render(); }); }) : null,
      button(t('Alias'), () => aliasPrompt(item)),
      button(t('Cerrar sesion'), () => confirmThen(t('¿Cerrar la sesion de esta cuenta en este dispositivo?'), () => attempt(() => api('logout', { key: item.key }))), 'danger'))),
    button(t('Añadir cuenta'), async () => { if (await flushOpenDrafts()) await attempt(() => api('account.add')); }),
    button(t('Eliminar mi cuenta de Telegram'), () => sheet(t('Eliminar mi cuenta de Telegram'), [
      [t('Continuar en Telegram para confirmar la eliminación definitiva'), () => openUrl('https://my.telegram.org/auth?to=delete')],
      [t('Cancelar'), closeSheet],
    ])),
    button(t('Devices'), () => go('devices')),
    button(t('Scan QR code'), () => scanLogin()),
    state.accounts.length > 1 ? toggle('ask_account_startup', t('Choose account at startup when several are saved')) : null);
}

// Text and control effects (desktop: Personalization › effects) plus bold, italic,
// strikethrough and capitals for message text.
function effectsSection() {
  const effects = (state.appearance || {}).effects || {};
  const saveEffects = (values) => saveLook({ effects: values });
  const size = (key, label, max) => {
    return h('div', {class: 'setting effect-setting'}, h('span', {}, label),
      numericSlider(label, effects[key] || 0, 0, max * 4, value => saveEffects({[key]: value}), max * 2),
      h('input', { type: 'color', 'aria-label': label + ' · ' + t('Color'), value: effects[key + '_color'] || '#000000', onchange: (event) => saveEffects({ [key + '_color']: event.target.value }) }),
      effects[key + '_color'] ? button('↺', () => saveEffects({ [key + '_color']: '' })) : null);
  };
  const flag = (key, label) => switchSetting(label, effects[key], () => saveEffects({ [key]: !effects[key] }));
  return h('div', { class: 'section' }, h('h4', {}, t('Message text')),
    flag('text_bold', t('Bold')), flag('text_italic', t('Italic')), flag('text_strike', t('Strikethrough')), flag('text_uppercase', t('Capitals')),
    size('text_underline', t('Underline') + ' (px)', 8), size('text_shadow', t('Shadow') + ' (px)', 8), size('text_border', t('Border') + ' (px)', 4),
    h('h4', {}, t('Buttons')), size('button_border', t('Border') + ' (px)', 12), size('button_shadow', t('Shadow') + ' (px)', 12),
    h('h4', {}, t('Panels and controls')), size('menu_border', t('Border') + ' (px)', 12), size('menu_shadow', t('Shadow') + ' (px)', 12),
    h('div', { class: 'muted small' }, t('Zero disables the effect. Empty colors follow the theme. Text outlines and shadows apply to messages; controls keep their native interactions.')));
}

// Telegram Premium: emoji status, name and profile colours, privacy (desktop: profile customization).
function premiumSection() {
  const account = state.account, revision = state.accountRevision;
  const box = h('div', { class: 'section' }, h('h4', {}, t('Telegram Premium')), h('div', { class: 'empty spinner' }, t('Cargando...')));
  const fill = (data) => {
    if (state.account !== account || state.accountRevision !== revision || state.locked) return;
    state.premiumInfo = data;
    const status = data.emoji_status;
    const colorRow = (field, label, options, current) => h('div', { class: 'setting column' }, h('span', {}, label),
      h('div', { class: 'swatches' },
        h('button', { class: 'swatch none' + (current === null || current === undefined ? ' on' : ''), title: t('Default'),
          onclick: () => attempt(() => api('set_color', { field, color: null }), fill) }, '∅'),
        options.map((option) => h('button', { class: 'swatch' + (current === option.id ? ' on' : ''),
          style: 'background:' + (option.colors.length > 1 ? 'linear-gradient(135deg,' + option.colors.join(',') + ')' : option.colors[0] || 'transparent'),
          onclick: () => attempt(() => api('set_color', { field, color: option.id }), fill) }))));
    const privacy = data.privacy || {};
    const privacyToggle = (key, label) => switchSetting(label, privacy[key], () => attempt(() => api('global_privacy', { changes: { [key]: !privacy[key] } }), fill));
    box.replaceChildren(h('h4', {}, t('Telegram Premium')),
      h('div', { class: 'setting' }, h('span', {}, t('Telegram Premium')), h('span', { class: data.premium ? 'value' : 'muted' }, data.premium ? '✓' : '—')),
      data.premium ? null : h('div', { class: 'muted small' }, t('Some of these options need Telegram Premium; Telegram decides what your account can use.')),
      h('div', { class: 'setting' }, h('span', {}, t('Emoji status')),
        status ? emojiStatusBadge(status.id) : h('span', { class: 'muted' }, '—'),
        button(t('Choose'), () => chooseEmojiStatus(fill)),
        status ? button('x', () => attempt(() => api('set_emoji_status', {}), fill)) : null),
      colorRow('name_color', t('Name color'), data.name_colors, data.name_color),
      colorRow('profile_color', t('Profile color'), data.profile_colors, data.profile_color),
      data.privacy ? h('h4', {}, t('Privacy')) : null,
      data.privacy ? privacyToggle('hide_read_marks', t('Hide read time')) : null,
      data.privacy ? privacyToggle('new_noncontact_peers_require_premium', t('Only contacts and Premium users can message me')) : null,
      data.privacy ? privacyToggle('archive_and_mute_new_noncontact_peers', t('Archive and mute new chats from non-contacts')) : null,
      h('h4', {}, t('Included in this app')),
      h('div', { class: 'muted small' }, [t('Automatic translation (Premium)'), t('Transcribe audio'), t('Custom emoji'),
        t('Custom reactions'), t('Read time'), t('Show folder tags (Premium)')].join(' · ')));
  };
  attempt(() => api('premium_settings'), fill);
  return box;
}
function chooseEmojiStatus(done) {
  // The custom emoji picker in "choose" mode, then how long.
  stickerPicker(true, (doc) => sheet(t('Emoji status'), [
    [t('Forever'), () => attempt(() => api('set_emoji_status', { id: doc.id }), done)],
    [t('For 1 hour'), () => attempt(() => api('set_emoji_status', { id: doc.id, duration: 3600 }), done)],
    [t('For 8 hours'), () => attempt(() => api('set_emoji_status', { id: doc.id, duration: 8 * 3600 }), done)],
    [t('For 1 day'), () => attempt(() => api('set_emoji_status', { id: doc.id, duration: 86400 }), done)],
    [t('For 7 days'), () => attempt(() => api('set_emoji_status', { id: doc.id, duration: 7 * 86400 }), done)],
  ]));
}

function myProfileSection() {
  const account = state.account, revision = state.accountRevision;
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  const section = h('div', { class: 'section' }, h('h4', {}, t('My profile')));
  const fill = (me) => {
    if (!current()) return;
    const input = (key, label) => h('div', { class: 'field wide' }, h('label', {}, label), h('input', { type: 'text', value: me[key] || '', 'data-key': key }));
    const about = h('div', { class: 'field wide' }, h('label', {}, t('Bio')), h('textarea', { rows: 2, 'data-key': 'about' }, me.about || ''));
    section.append(input('first', t('First name')), input('last', t('Last name')), input('username', t('Username')), about,
      button(t('Save'), () => {
        const values = {};
        for (const node of section.querySelectorAll('[data-key]')) values[node.dataset.key] = node.value;
        attempt(() => api('save_my_profile', values), (saved) => { if (current()) { state.me = saved; toast(t('Saved.')); } });
      }, 'primary'));
  };
  if (state.me) fill(state.me);
  else api('my_profile').then((me) => { if (current()) { state.me = me; fill(me); } }, () => {});
  return section;
}

// app lock: PIN (stored as a hash by the core), device authentication, auto-lock
const pinInput = (placeholder) => h('input', { type: 'password', autocomplete: 'new-password', placeholder });
function enableLock() {
  const first = pinInput(t('PIN o contraseña')), again = pinInput(t('Repetir'));
  formSheet(t('Enable app lock'), [first, again,
    h('div', { class: 'muted small' }, t('Remember this password. It is separate from your Telegram password and cannot be recovered.'))],
    t('Enable app lock'), async () => {
      if (first.value !== again.value) { toast(t('The passwords do not match.'), 'error'); return false; }
      const info = await attempt(() => api('lock_set', { pin: first.value }));
      if (!info) return false;
      state.lock = info; state.lock_enabled = true; render();
    });
}
function changeLock() {
  const current = pinInput(t('PIN o contraseña')), first = pinInput('••••'), again = pinInput(t('Repetir'));
  formSheet(t('Change app password'), [current, first, again], t('Save'), async () => {
    if (first.value !== again.value) { toast(t('The passwords do not match.'), 'error'); return false; }
    const info = await attempt(() => api('lock_set', { pin: first.value, current: current.value }));
    if (!info) return false;
    state.lock = info; toast(t('Saved.'));
  });
}
function disableLock() {
  const current = pinInput(t('PIN o contraseña'));
  formSheet(t('Disable app lock'), [current], t('Disable app lock'), async () => {
    const info = await attempt(() => api('lock_remove', { pin: current.value }));
    if (!info) return false;
    state.lock = info; state.lock_enabled = false; render();
  });
}
function lockSection() {
  const lock = state.lock || {};
  const options = (values) => attempt(() => api('lock_options', values), (info) => { state.lock = info; render(); });
  if (!lock.enabled) return h('div', { class: 'section' }, h('h4', {}, t('App lock')), button(t('Enable app lock'), enableLock, 'primary'));
  const delay = h('select', { onchange: (event) => options({ delay: Number(event.target.value) }) },
    [[0, t('Immediately')], [60, t('1 minute')], [300, t('5 minutes')], [3600, t('1 hour')]].map(([value, label]) =>
      h('option', { value, selected: Number(lock.delay || 0) === value }, label)));
  return h('div', { class: 'section' }, h('h4', {}, t('App lock')),
    lock.biometric_available ? switchSetting(t('Use device authentication'), lock.biometric, () => options({ biometric: !lock.biometric })) : null,
    h('div', { class: 'setting' }, h('span', {}, t('Lock after')), delay),
    button(t('Lock now'), async () => {
      await flushOpenDrafts();
      await attempt(() => api('lock_now'), (locked) => { if (locked) { state.locked = true; render(); } });
    }),
    button(t('Change app password'), changeLock),
    button(t('Disable app lock'), disableLock, 'danger'));
}

function aliasPrompt(item) {
  promptThen(t('Alias'), { value: item.alias || '', note: t('Nombre visible solo en este dispositivo') }, (value) => {
    attempt(() => api('alias', { key: item.key, alias: value }), (list) => { state.accounts = list; render(); });
  });
}

// -- start ----------------------------------------------------------------------------
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    // The core locks now or after the chosen delay (never for our own pickers).
    flushOpenDrafts();
    api('app_hidden', { keep: state.keepUnlocked }).then((locked) => { if (locked && !state.locked) { state.locked = true; state.bioTried = false; render(); } }, () => {});
    return;
  }
  api('app_visible').then((result) => {
    if (result.locked) { if (!state.locked) { state.locked = true; state.bioTried = false; drawNativeCall(); drawGroupCall(); render(); } }
    else if (state.started) resync().then(openAndroidNotification).catch(() => {});
  }, () => {});
});

function lockView() {
  const input = h('input', { type: 'password', id: 'pin', autocomplete: 'off',
    onkeydown: (event) => { if (event.key === 'Enter') unlock(); } });
  const unlock = () => attempt(() => api('unlock', { pin: input.value }), () => { state.locked = false; resync(); });
  const lock = state.lock || {};
  const device = lock.biometric && lock.biometric_available;
  const useDevice = () => attempt(() => api('unlock_biometric'), () => { state.locked = false; resync(); });
  if (device && !state.bioTried) { state.bioTried = true; setTimeout(useDevice, 350); }
  else setTimeout(() => input.focus(), 50);
  return [h('div', { class: 'center' }, logo(), h('div', { class: 'muted' }, t('Unlock your messages')),
    h('div', { class: 'field' }, h('label', { for: 'pin' }, t('PIN o contraseña')), input),
    button(t('Unlock'), unlock, 'primary'),
    device ? button(t('Use device authentication'), useDevice) : null)];
}

// several accounts: choose which one to open (desktop: startup_accounts.py)
function chooserView() {
  let ask = state.settings.ask_account_startup !== false;
  const askNode = h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: ask, onchange: (event) => { ask = event.target.checked; } }),
    h('span', {}, t('Choose account at startup when several are saved')));
  return [h('div', { class: 'center chooser' }, logo(), h('h3', {}, t('Choose account')),
    h('div', { class: 'accounts-list' }, state.accounts.map((item) => h('button', { class: 'row account-choice', onclick: () =>
      attempt(() => api('choose_account', { key: item.key, ask }), () => { state.stage = 'loading'; render(); }) },
      avatar(item.user_id, item.alias || item.label, '', item.key), h('div', { class: 'body' }, h('div', { class: 'top' }, h('span', { class: 'name' }, item.alias || item.label || '…')),
        item.alias ? h('div', { class: 'bottom' }, h('span', { class: 'preview' }, item.label)) : null)))),
    askNode)];
}
installEdgeBack();
const connectionAlert = document.getElementById('connection-alert');
connectionAlert.onclick = reconnect;
(async function start() {
  listen();
  for (let attemptNumber = 0; attemptNumber < 50; attemptNumber++) {
    try {
      const snapshot = await api('state', { locale: navigator.language || '' });
      adopt(snapshot);
      await loadStrings();
      break;
    } catch (error) { await new Promise((resolve) => setTimeout(resolve, 200)); }
  }
  history.replaceState({ view: 'chats' }, '');
  if (state.stage === 'ready' && !state.locked && !unavailableWindow()) {
    attempt(() => api('chats'), (chats) => { state.chats = chats; drawChatList(); if (WINDOW_CHAT === null) restoreWindows(); });
    if (WINDOW_CHAT === null) refreshCallState();
  }
  state.started = true;
  render();
  if (WINDOW_CHAT === null) api('launch_ready').catch(() => {});
  openAndroidNotification().catch(() => {});
  if (WINDOW_CHAT !== null) {
    document.documentElement.classList.add('system-window');
    if (state.stage === 'ready' && !state.locked && !unavailableWindow()) openChat(WINDOW_CHAT, true);
    // The main app keeps counting this chat as open while the window lives.
    addEventListener('pagehide', () => fetch('/api/close', { method: 'POST', keepalive: true,
      headers: {'content-type': 'application/json', 'x-tg-token': TOKEN, 'x-tg-window-account': WINDOW_ACCOUNT},
      body: JSON.stringify({peer: WINDOW_CHAT, window: true}) }).catch(() => {}));
  }
})();
