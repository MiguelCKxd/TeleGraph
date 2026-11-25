// One fullscreen surface serves chat and profile galleries. A history update
// changes the strip and arrows without replacing the image being pinched.
function presentGallery({layer, title, items, selected, source, olderStep, hasMore, loadPage, exportItem, active, onSelected}) {
  let current = selected, pending = null, moveRevision = 0, exporting = false;
  const tiles = new Map();
  const titleNode = h('span', {});
  const info = h('span', {class: 'sub'});
  const caption = h('div', {class: 'caption', dir: 'auto'});
  const notice = h('div', {class: 'gallery-notice', role: 'status', hidden: true});
  const strip = h('div', {class: 'gallery-strip', 'aria-label': title});
  let stage = h('div', {class: 'stage'}), releaseGestures;
  const previous = symbolButton('‹', t('Previous page'), () => go(-1));
  const next = symbolButton('›', t('Next page'), () => go(1));
  const save = symbolButton('↓', t('Save'), () => send('save'));
  const share = symbolButton('↗', t('Share'), () => send('share'));
  const bar = h('div', {class: 'bar gallery-bar'}, symbolButton('×', t('Close'), () => layer.close()),
    h('div', {class: 'title'}, titleNode, info), previous, next, save, share);
  const live = () => layer.open && active();
  const indexOfCurrent = () => items().findIndex(item => item.id === current.id);
  function status(message) {
    if (!live()) return;
    notice.textContent = message;
    notice.hidden = !message;
  }
  function drawControls(center = false) {
    const list = items(), index = indexOfCurrent(), more = hasMore();
    previous.disabled = index <= 0 && !(olderStep === -1 && more);
    next.disabled = index >= list.length - 1 && !(olderStep === 1 && more);
    previous.hidden = next.hidden = list.length <= 1 && !more;
    save.hidden = share.hidden = !!current.protected || !exportItem;
    save.disabled = share.disabled = exporting;
    titleNode.textContent = current.sender || title;
    info.textContent = [current.time, list.length > 1 ? (index + 1) + ' / ' + list.length : ''].filter(Boolean).join(' · ');
    const previews = state.settings?.photo_previews !== false;
    strip.hidden = !previews || list.length < 2;
    if (strip.hidden) { tiles.clear(); strip.replaceChildren(); return; }
    const controls = list.map((item, n) => {
      let tile = tiles.get(item.id);
      if (!tile) {
        tile = h('button', {type: 'button', onclick: () => select(item)},
          h('img', {src: source(item, true), alt: '', loading: 'lazy', decoding: 'async'}));
        tiles.set(item.id, tile);
      }
      tile.setAttribute('aria-label', (item.kind === 'video' ? t('Vídeo') : t('Foto')) + ' ' + (n + 1));
      tile.setAttribute('aria-current', String(item.id === current.id));
      return tile;
    });
    reconcile(strip, controls);
    if (center) tiles.get(current.id)?.scrollIntoView({inline: 'center', block: 'nearest', behavior: 'instant'});
  }
  function fetchPage() {
    if (!pending) {
      pending = (async () => {
        try {
          await loadPage();
          return true;
        } catch (error) {
          status(error.message || t('Media unavailable.'));
          return false;
        } finally {
          pending = null;
          if (live()) drawControls();
        }
      })();
    }
    return pending;
  }
  function select(item) {
    if (!live()) return;
    moveRevision++;
    if (stage.firstElementChild && current.id === item.id) return;
    releaseGestures?.();
    releaseGestures = null;
    current = item;
    status('');
    const video = item.kind === 'video' || item.kind === 'gif';
    const media = video
      ? h('video', {src: source(item, false), controls: true, autoplay: true, playsinline: true, loop: item.kind === 'gif'})
      : h('img', {src: source(item, false), alt: item.caption || title});
    const replacement = h('div', {class: 'stage'}, media);
    const failed = () => { if (media.isConnected && live()) status(t('Media unavailable.')); };
    if (video) {
      let touch = null;
      replacement.addEventListener('touchstart', event => {
        touch = event.touches.length === 1 ? event.touches[0] : null;
      }, {passive: true});
      replacement.addEventListener('touchcancel', () => { touch = null; });
      replacement.addEventListener('touchend', event => {
        if (!touch) return;
        const dx = event.changedTouches[0].clientX - touch.clientX, dy = event.changedTouches[0].clientY - touch.clientY;
        touch = null;
        if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) go(galleryStep(dx < 0));
      });
      media.addEventListener('error', failed, {once: true});
    } else {
      media.addEventListener('error', () => {
        if (!live() || !media.isConnected) return;
        const fallback = source(item, true);
        if (fallback === source(item, false)) { failed(); return; }
        media.addEventListener('error', failed, {once: true});
        media.src = fallback;
      }, {once: true});
      releaseGestures = photoGestures(replacement, media, right => go(galleryStep(right)));
    }
    stage.replaceWith(replacement);
    stage = replacement;
    caption.textContent = item.caption || '';
    caption.hidden = !item.caption;
    drawControls(true);
    if (onSelected) onSelected(item, live);
    const index = indexOfCurrent(), distance = olderStep < 0 ? index : items().length - index - 1;
    if (distance <= 2 && hasMore()) fetchPage();
  }
  async function go(step) {
    const revision = ++moveRevision;
    while (live() && revision === moveRevision) {
      const list = items(), index = indexOfCurrent(), target = list[index + step];
      if (target) { select(target); return; }
      if (step !== olderStep || !hasMore()) { status(''); return; }
      status(t('Cargando...'));
      // A whole history page may contain only text. Continue on explicit
      // navigation, and stop immediately if this viewer or its account changes.
      if (!await fetchPage()) return;
    }
  }
  async function send(action) {
    if (!live() || exporting || !exportItem || current.protected) return;
    exporting = true; drawControls();
    try { await exportItem(current, action, status); }
    finally { exporting = false; if (live()) drawControls(); }
  }
  const settingsChanged = () => { if (live()) drawControls(); };
  document.addEventListener('appearancechange', settingsChanged);
  layer.addEventListener('close', () => {
    releaseGestures?.();
    document.removeEventListener('appearancechange', settingsChanged);
  }, {once: true});
  layer.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (event.target.tagName === 'VIDEO') return;
      event.preventDefault(); go(galleryStep(event.key === 'ArrowRight'));
    }
  });
  layer.replaceChildren(bar, stage, caption, notice, strip);
  if (!layer.open) layer.showModal();
  select(selected);
}
