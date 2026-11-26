// Explicit downloads survive navigation; only this account's rows are rendered.
// The controller is created by app.js after its plumbing has been initialized.
function createDownloadController() {
  let owner = null, accountRevision = -1, revision = -1, panel = null, timer = null;
  let list = null, notice = null, polling = false;
  const items = new Map(), rows = new Map(), badges = new Set(), pendingActions = new Map();
  const errors = {
    permission: 'Este archivo está protegido o la cuenta ya no está disponible.',
    timeout: 'La descarga se interrumpió por falta de respuesta. Puedes reintentarla.',
    network: 'La descarga se interrumpió. Comprueba la conexión y vuelve a intentarlo.',
    storage_full: 'No hay espacio suficiente para guardar el archivo.',
    rate_limited: 'Telegram ha limitado temporalmente las descargas. Espera antes de volver a intentarlo.',
    unavailable: 'El archivo ya no está disponible.',
    unexpected: 'No se pudo completar la descarga. Puedes reintentarla.',
    open_failed: 'No se pudo abrir el archivo. Puedes guardarlo o compartirlo.',
  };
  const labels = {queued: 'En cola', downloading: 'Descargando…', ready: 'Descarga completada',
    failed: 'Descarga fallida', cancelling: 'Cancelando…', cancelled: 'Descarga cancelada', opening: 'Abriendo…'};
  const live = () => panel && currentSheetPanel === panel && panel.isConnected && !state.locked &&
    state.account === owner && state.accountRevision === accountRevision;
  const context = () => !state.locked && state.account === owner && state.accountRevision === accountRevision;
  function announce(message) {
    if (notice) {notice.textContent = message; notice.hidden = !message;}
  }
  function reset() {
    clearTimeout(timer); timer = null; polling = false;
    pendingActions.clear(); items.clear(); rows.clear(); revision = -1;
    owner = state.account; accountRevision = state.accountRevision;
    if (panel && currentSheetPanel === panel) closeSheet();
    panel = list = notice = null;
    drawBadges();
  }
  function ensureContext() {
    if (!context()) reset();
  }
  function drawBadges() {
    const count = [...items.values()].filter(item => ['queued', 'downloading', 'cancelling', 'opening'].includes(item.state)).length;
    for (const node of badges) {
      if (!node.isConnected) {badges.delete(node); continue;}
      node.textContent = t('Descargas') + (count ? ' · ' + count : '');
    }
  }
  function accept(item) {
    if (!item || item.account !== owner || typeof item.id !== 'string') return;
    const previous = items.get(item.id);
    if (previous && Number(item.revision || 0) < Number(previous.revision || 0)) return;
    revision = Math.max(revision, Number(item.revision || 0));
    items.set(item.id, item);
  }
  function update(payload) {
    ensureContext();
    if (!context() || !payload || payload.account !== owner || !Array.isArray(payload.items)) return;
    const incoming = Number(payload.revision || 0);
    if (incoming < revision) return;
    revision = incoming;
    const present = new Set(payload.items.map(item => item.id));
    for (const id of items.keys()) if (!present.has(id)) {items.delete(id); pendingActions.delete(id);}
    for (const item of payload.items) accept(item);
    draw();
  }
  function formatProgress(item) {
    const bytes = Number.isFinite(item.bytes) && item.bytes >= 0 ? item.bytes : 0;
    return Number.isFinite(item.total) && item.total > 0
      ? humanSize(bytes) + ' / ' + humanSize(item.total) +
        (Number.isFinite(item.percent) ? ' · ' + item.percent + '%' : '')
      : humanSize(bytes);
  }
  function row(item) {
    const name = h('strong', {class: 'download-name'});
    const status = h('span', {class: 'muted small'});
    const amount = h('span', {class: 'small download-bytes'});
    const progress = h('progress', {max: 100, 'aria-label': t('Progreso de descarga')});
    const error = h('p', {class: 'error small', hidden: true});
    const cancel = button(t('Cancelar'), () => control(item.id, 'cancel'));
    const retry = button(t('Reintentar desde el principio'), () => control(item.id, 'retry'));
    const open = button(t('Open'), () => openResult(item.id, 'file'));
    const save = button(t('Save'), () => openResult(item.id, 'save'));
    const share = button(t('Share'), () => openResult(item.id, 'share'));
    const node = h('article', {class: 'download-row', 'data-download': item.id}, name, status,
      progress, amount, error, h('div', {class: 'actions'}, cancel, retry, open, save, share));
    return {node, name, status, amount, progress, error, cancel, retry, open, save, share};
  }
  function draw() {
    drawBadges();
    if (!live()) return;
    for (const [id, entry] of rows) if (!items.has(id)) {entry.node.remove(); rows.delete(id);}
    for (const item of items.values()) {
      let entry = rows.get(item.id);
      if (!entry) {entry = row(item); rows.set(item.id, entry); list.prepend(entry.node);}
      entry.name.textContent = item.name || t('File');
      entry.status.textContent = t(item.state === 'opening' && item.action === 'save' ? 'Guardando…'
        : item.state === 'opening' && item.action === 'share' ? 'Preparando para compartir…'
        : labels[item.state] || 'En cola');
      entry.amount.textContent = formatProgress(item);
      entry.progress.hidden = !['queued', 'downloading'].includes(item.state);
      if (Number.isFinite(item.percent)) entry.progress.value = Math.min(99, Math.max(0, item.percent));
      else entry.progress.removeAttribute('value');
      entry.progress.setAttribute('aria-valuetext', entry.amount.textContent);
      entry.cancel.hidden = !['queued', 'downloading'].includes(item.state);
      entry.retry.hidden = !['failed', 'cancelled'].includes(item.state);
      entry.open.hidden = entry.save.hidden = entry.share.hidden = item.state !== 'ready';
      entry.error.hidden = !item.error;
      entry.error.textContent = item.error ? t(errors[item.error] || errors.unexpected) : '';
      if (item.state === 'ready' && pendingActions.has(item.id)) {
        const action = pendingActions.get(item.id); pendingActions.delete(item.id);
        openResult(item.id, action);
      }
    }
    list.hidden = !items.size;
    if (!items.size) announce(t('No hay descargas.'));
    else if (notice.textContent === t('No hay descargas.')) announce('');
  }
  async function poll() {
    clearTimeout(timer); timer = null;
    if (!live() || polling) return;
    const account = owner, generation = accountRevision, target = panel;
    polling = true;
    try {
      const result = await api('download_status', {account});
      if (target === panel && live() && account === owner && generation === accountRevision) update(result);
    } catch (_) {
      if (target === panel && live()) announce(t('No se pudo consultar la descarga. Vuelve a intentarlo.'));
    } finally {
      if (target === panel && live() && account === owner && generation === accountRevision) {
        polling = false;
        timer = setTimeout(poll, 1000);
      }
    }
  }
  function show() {
    ensureContext();
    if (state.locked) return;
    if (live()) {draw(); return;}
    const layer = document.getElementById('sheet-layer');
    list = h('div', {class: 'download-list'});
    notice = h('p', {class: 'muted small', role: 'status', hidden: true});
    rows.clear(); polling = false;
    panel = h('div', {class: 'sheet form downloads-sheet', onclick: event => event.stopPropagation()},
      h('h3', {}, t('Descargas')), notice, list,
      h('p', {class: 'muted small'}, t('Puedes cerrar este panel. Las descargas continuarán mientras la app esté activa.')),
      h('div', {class: 'actions'}, button(t('Actualizar'), poll), button(t('Close'), closeSheet)));
    panel.onDismiss = () => {clearTimeout(timer); timer = null; pendingActions.clear();};
    layer.replaceChildren(panel); activateSheet(layer); layer.onclick = closeSheet;
    draw(); poll();
  }
  async function start(message, peer, action = 'file') {
    ensureContext(); show();
    if (!live()) return false;
    const account = owner, generation = accountRevision, target = panel;
    try {
      const item = await api('download_start', {peer, id: message.id, account});
      if (!context() || target !== panel || !live() || generation !== accountRevision) return false;
      pendingActions.set(item.id, action);
      accept(item); draw();
      return true;
    } catch (_) {
      if (target === panel && live() && generation === accountRevision)
        announce(t('No se pudo iniciar la descarga. Comprueba la conexión y vuelve a intentarlo.'));
      return false;
    }
  }
  async function control(id, action) {
    const account = owner, generation = accountRevision;
    const attempt = items.get(id)?.attempt;
    pendingActions.delete(id);
    try {
      const item = await api('download_' + action, {id, account, attempt});
      if (!context() || generation !== accountRevision) return;
      accept(item); draw();
    } catch (_) {
      if (live() && generation === accountRevision) announce(t('No se pudo completar esta acción. Vuelve a intentarlo.'));
    }
  }
  async function openResult(id, action) {
    if (!live()) return;
    const account = owner, generation = accountRevision;
    keepUnlocked(120);
    try {
      const result = await api('download_open', {id, action, account});
      if (!context() || generation !== accountRevision || !live()) return;
      if (!result.opened) announce(t(errors.open_failed));
      else if (action === 'save' && PLATFORM === 'Android') announce(t('Saved to Downloads/TG-ASCII.'));
      poll();
    } catch (_) {
      if (live() && generation === accountRevision) announce(t('No se pudo completar esta acción. Vuelve a intentarlo.'));
    }
  }
  function launcher() {
    const node = button(t('Descargas'), show); badges.add(node);
    return node;
  }
  return {start, show, update, reset, launcher};
}
