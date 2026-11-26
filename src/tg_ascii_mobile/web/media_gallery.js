// One fullscreen surface serves chat and profile galleries. A history update
// changes the strip and arrows without replacing the image being pinched.
function presentGallery({layer, title, items, selected, source, olderStep, hasMore, loadPage, exportItem, active, onSelected, goToMessage, allowSystemPlayer = false}) {
  let current = selected, pending = null, moveRevision = 0, exporting = false;
  const tiles = new Map();
  const titleNode = h('span', {});
  const info = h('span', {class: 'sub'});
  const caption = h('div', {class: 'caption', dir: 'auto'});
  const notice = h('div', {class: 'gallery-notice', role: 'status', hidden: true});
  const strip = h('div', {class: 'gallery-strip', 'aria-label': title});
  let stage = h('div', {class: 'stage'}), releaseGestures, releaseMedia;
  const retry = button(t('Reintentar'), () => select(current, true), 'gallery-retry');
  retry.hidden = true;
  const external = button(t('Open in system player'), () => send('open'), 'gallery-external');
  external.hidden = true;
  const previous = symbolButton('‹', t('Previous page'), () => go(-1));
  const next = symbolButton('›', t('Next page'), () => go(1));
  const save = symbolButton('↓', t('Save'), () => send('save'));
  const share = symbolButton('↗', t('Share'), () => send('share'));
  const jump = goToMessage ? button(t('Go to message'), reveal, 'gallery-jump') : null;
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
    save.disabled = share.disabled = external.disabled = exporting;
    titleNode.textContent = current.sender || title;
    info.textContent = [current.time, list.length > 1 ? (index + 1) + ' / ' + list.length : ''].filter(Boolean).join(' · ');
    const previews = state.settings?.photo_previews !== false;
    strip.hidden = !previews || list.length < 2;
    if (strip.hidden) { tiles.clear(); strip.replaceChildren(); return; }
    // Keep a useful neighbourhood without retaining thousands of thumbnail
    // elements after paging through a long history. Arrows still span it all.
    const start = Math.max(0, index - 15), visible = list.slice(start, Math.max(31, index + 16));
    const visibleIds = new Set(visible.map(item => item.id));
    for (const id of tiles.keys()) if (!visibleIds.has(id)) tiles.delete(id);
    const controls = visible.map((item, offset) => {
      const n = start + offset;
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
    if (center) {
      const tile = tiles.get(current.id);
      if (tile) {
        const item = tile.getBoundingClientRect(), rail = strip.getBoundingClientRect();
        strip.scrollLeft += item.left - rail.left - (rail.width - item.width) / 2;
      }
    }
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
  function select(item, force = false) {
    if (!live()) return;
    moveRevision++;
    if (!force && stage.firstElementChild && current.id === item.id) return;
    releaseGestures?.(); releaseMedia?.();
    releaseGestures = releaseMedia = null;
    retry.hidden = external.hidden = true;
    current = item;
    status(t('Cargando...'));
    const video = item.kind === 'video' || item.kind === 'gif';
    const media = video
      ? h('video', {src: source(item, false), poster: state.settings?.photo_previews === false ? '' : source(item, true),
        controls: true, autoplay: true, preload: 'auto', playsinline: true, loop: item.kind === 'gif'})
      : h('img', {src: source(item, false), decoding: 'async', alt: item.caption || title});
    const replacement = h('div', {class: 'stage'}, media);
    let ready = false;
    const failed = () => {
      if (media.isConnected && live()) {
        retry.hidden = false;
        external.hidden = !allowSystemPlayer || !video || !exportItem || !!item.protected;
        status(t('Media unavailable.'));
      }
    };
    const loaded = () => {
      if (!media.isConnected || !live()) return;
      ready = true; retry.hidden = external.hidden = true; status('');
    };
    if (video) {
      let touch = null;
      replacement.addEventListener('touchstart', event => {
        touch = event.touches.length === 1 ? event.touches[0] : null;
        // Leave the native seek/volume controls to the video player.
        if (touch && touch.clientY > media.getBoundingClientRect().bottom - 56) touch = null;
      }, {passive: true});
      replacement.addEventListener('touchcancel', () => { touch = null; });
      replacement.addEventListener('touchend', event => {
        if (!touch) return;
        const dx = event.changedTouches[0].clientX - touch.clientX, dy = event.changedTouches[0].clientY - touch.clientY;
        touch = null;
        if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) go(galleryStep(dx < 0));
      });
      media.addEventListener('error', failed);
      media.addEventListener('loadeddata', loaded);
      media.addEventListener('playing', loaded);
      media.addEventListener('waiting', () => { if (media.isConnected && live()) status(t('Cargando...')); });
      media.addEventListener('stalled', () => { if (!ready) failed(); });
      releaseMedia = () => {
        media.pause(); media.removeAttribute('src'); media.removeAttribute('poster'); media.load();
      };
    } else {
      media.addEventListener('load', loaded, {once: true});
      media.addEventListener('error', () => {
        if (!live() || !media.isConnected) return;
        const fallback = source(item, true);
        if (fallback === source(item, false)) { failed(); return; }
        failed();
        status(t('Showing a preview. Retry to load the selected quality.'));
        // A reduced fallback is useful, but is never presented as the original.
        media.addEventListener('error', failed, {once: true});
        media.removeEventListener('load', loaded);
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
  async function reveal() {
    if (!live() || jump.disabled) return;
    const item = current;
    jump.disabled = true;
    try {
      await goToMessage(item, () => {
        if (!live() || current !== item) return false;
        layer.close();
        return true;
      });
    } catch (error) {
      if (live() && current === item) status(error.message);
    } finally {
      jump.disabled = false;
    }
  }
  const settingsChanged = () => { if (live()) drawControls(); };
  document.addEventListener('appearancechange', settingsChanged);
  layer.addEventListener('close', () => {
    releaseGestures?.(); releaseMedia?.();
    tiles.clear();
    document.removeEventListener('appearancechange', settingsChanged);
  }, {once: true});
  layer.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (event.target.tagName === 'VIDEO') return;
      event.preventDefault(); go(galleryStep(event.key === 'ArrowRight'));
    }
  });
  layer.replaceChildren(bar, stage, caption, notice, retry, external, ...(jump ? [jump] : []), strip);
  if (!layer.open) layer.showModal();
  select(selected);
}

// A shared-media list spans the whole peer. Its active thumbnail can belong
// to a different forum topic or channel discussion than the chat underneath.
async function revealGalleryMessage(item, {account, peer, chat, thread, floating}, close) {
  let topic = thread?.topic ? thread.root : item.topic_id;
  let discussion = thread && !thread.topic ? thread : null;
  const needsOrigin = !thread && !topic &&
    (chat.forum || !chat.kind || (chat.kind === 'group' && (item.thread_root || item.forwarded)));
  if (needsOrigin) {
    // A missing connection must not turn a not-yet-resolved discussion into
    // the ordinary group. Keep the media and the previous chat untouched.
    if (state.connection === 'offline') throw new Error(t('Connect to go to the message.'));
    const origin = await api('gallery_origin', {account, peer, id: item.id});
    topic = origin.topic;
    if (origin.source) discussion = origin;
  }
  // Closing a gallery, changing its active photo, locking, or switching
  // accounts while resolving the route all cancel this particular tap.
  if (!close()) return;
  const revision = state.accountRevision, sourceView = state.view;
  const current = () => state.account === account && state.accountRevision === revision && !state.locked;
  const destinationOpen = () => {
    const open = state.open;
    if (open?.peer !== peer || open.forumList) return false;
    if (discussion) return !open.topic && open.thread?.root === discussion.root &&
      open.thread.source === discussion.source && open.thread.post === discussion.post;
    if (topic) return open.topic?.id === topic;
    return !open.thread;
  };
  if (!topic && !discussion && floating) {
    const node = floating.nodeCache?.nodes.get(item.id)?.node;
    if (node?.isConnected) { focusMessageNode(node); return; }
  }
  if (!destinationOpen()) {
    if (discussion) {
      const channel = discussion.channel || state.chats.find(row => row.id === discussion.source) ||
        {id: discussion.source, name: discussion.source_name || String(discussion.source), kind: 'channel'};
      await loadComments(discussion.source, discussion.post, channel);
    } else if (topic) {
      await openForumTopic(chat, {id: topic});
    } else {
      await openChat(peer, true, chat);
    }
  }
  if (!current() || !destinationOpen() || (state.view !== sourceView && state.view !== 'chat')) return;
  if (state.view !== 'chat') go('chat');
  await jumpTo(item.id);
}

function focusMessageNode(node) {
  node.focus({preventScroll: true});
  node.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  node.classList.add('flash');
  clearTimeout(node.flashTimer);
  node.flashTimer = setTimeout(() => node.classList.remove('flash'), 1600);
}
