// Shared controls for the phone and tablet views.
const swipeOptions = [
  ['menu', 'Menú del chat'], ['read', 'Marcar como leído o no leído'], ['archive', 'Archivar o desarchivar'],
  ['mute', 'Silenciar'], ['pin', 'Fijar o desfijar'], ['folders', 'Add to folder'], ['profile', 'Profile'], ['none', 'Sin acción'],
];

function performChatSwipe(chat, action) {
  switch (action) {
    case 'menu': return chatMenu(chat);
    case 'profile': return openProfile(chat);
    case 'folders': return folderSheet([chat.id]);
    case 'mute': return muteSheet(chat);
    case 'pin': return chat.pinFolder != null ? folderPin(chat, {pinned: !chat.pinned}) :
      attempt(() => api('pin_chat', {peer: chat.id, pinned: !chat.pinned}), queuedNote);
    case 'archive': return attempt(() => api('archive_chat', {peer: chat.id, archived: !chat.archived}), result => {
      queuedNote(result);
      if (state.view === 'archived') { state.archived = null; render(); }
    });
    case 'read': return chat.unread || chat.unread_mark ? attempt(() => api('mark_read_chat', {peer: chat.id}), queuedNote) :
      attempt(() => api('mark_unread', {peer: chat.id, unread: true}), queuedNote);
  }
}

// A row yields to vertical scrolling, selection, and the system's edge gesture.
function swipeChatRow(row, chat) {
  row.classList.add('swipe-chat');
  let start = null, shift = 0, blockClickUntil = 0;
  const reset = () => {
    start = null; shift = 0;
    row.style.removeProperty('transform');
    row.classList.remove('swiping');
    row.removeAttribute('data-swipe');
  };
  row.addEventListener('touchstart', event => {
    reset();
    const point = event.touches[0];
    if (event.touches.length === 1 && point.clientX > 28 && point.clientX < innerWidth - 28)
      start = {x: point.clientX, y: point.clientY};
  }, {passive: true});
  row.addEventListener('touchmove', event => {
    if (!start || event.touches.length !== 1) { reset(); return; }
    const point = event.touches[0], dx = point.clientX - start.x, dy = point.clientY - start.y;
    if (Math.abs(dy) > 12 && Math.abs(dx) < Math.abs(dy) * 1.4) { reset(); return; }
    if (Math.abs(dx) < 12 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    const action = dx > 0 ? state.appearance.swipe_right : state.appearance.swipe_left;
    shift = dx;
    if (action === 'none') return;
    row.classList.add('swiping');
    row.dataset.swipe = t(swipeOptions.find(([key]) => key === action)?.[1] || 'Menú del chat');
    row.style.transform = 'translateX(' + Math.max(-68, Math.min(68, dx * .55)) + 'px)';
  }, {passive: true});
  row.addEventListener('touchcancel', reset);
  row.addEventListener('touchend', () => {
    const distance = shift;
    reset();
    if (Math.abs(distance) < 56) return;
    blockClickUntil = performance.now() + 500;
    performChatSwipe(chat, distance > 0 ? state.appearance.swipe_right : state.appearance.swipe_left);
  });
  row.addEventListener('click', event => {
    if (performance.now() < blockClickUntil) { event.stopImmediatePropagation(); event.preventDefault(); }
  }, true);
  return row;
}

function installEdgeBack() {
  if (PLATFORM === 'Android') return;
  let start = null;
  document.addEventListener('touchstart', event => {
    const point = event.touches[0], target = event.target;
    start = event.touches.length === 1 && point.clientX <= 28 &&
      !target.closest('dialog, input, textarea, select, video, .tabs, .photo-album, .stage, .swatches') ?
      {x: point.clientX, y: point.clientY} : null;
  }, {passive: true});
  document.addEventListener('touchmove', event => {
    if (!start) return;
    if (event.touches.length !== 1 || Math.abs(event.touches[0].clientY - start.y) > 46) {
      start = null;
    } else if (event.cancelable && event.touches[0].clientX - start.x > 12 &&
               event.touches[0].clientX - start.x > 1.75 * Math.abs(event.touches[0].clientY - start.y)) {
      event.preventDefault();
    }
  }, {passive: false});
  document.addEventListener('touchcancel', () => { start = null; });
  document.addEventListener('touchend', event => {
    const origin = start;
    start = null;
    if (!origin || event.touches.length) return;
    const dx = event.changedTouches[0].clientX - origin.x, dy = event.changedTouches[0].clientY - origin.y;
    if (dx >= 65 && dx > Math.abs(dy) * 1.75) window.tgBack();
  });
}

function numericSlider(label, value, min, max, save, sliderMax = max) {
  const number = h('input', {type: 'number', inputmode: 'numeric', min, max, step: 1, value, 'aria-label': label});
  const slider = h('input', {type: 'range', min, max: sliderMax, step: 1, value: Math.min(value, sliderMax), 'aria-label': label});
  slider.oninput = () => { number.value = slider.value; };
  slider.onchange = () => save(Number(slider.value));
  number.onchange = () => {
    if (!number.value || !number.reportValidity()) { number.value = value; return; }
    slider.value = Math.min(number.valueAsNumber, sliderMax);
    save(number.valueAsNumber);
  };
  number.onkeydown = e => { if (e.key === 'Enter') number.blur(); };
  return h('span', {class: 'numeric-slider'}, slider, number);
}

const searchText = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();

function installSearchHistory(input) {
  let panel = null, generation = 0;
  const scope = () => input.dataset.searchScope || (input.id || (state.view + '/' + (input.placeholder || 'search'))).slice(0, 98);
  const close = () => { generation++; panel?.remove(); panel = null; };
  const remember = () => {
    if (input.value.trim() && state.account && !state.locked)
      api('recent_searches', {account: state.account, scope: scope(), query: input.value}).catch(() => {});
  };
  const show = async () => {
    close();
    if (input.value || !state.account || state.locked) return;
    const account = state.account, section = scope(), request = generation;
    const current = () => request === generation && input.isConnected && document.activeElement === input &&
      !input.value && !state.locked && account === state.account;
    const queries = await api('recent_searches', {scope: section, account}).catch(() => []);
    if (!current()) return;
    panel = h('div', {class: 'search-history', role: 'group', 'aria-label': t('Recent')});
    panel.addEventListener('pointerdown', event => { event.preventDefault(); });
    input.insertAdjacentElement('afterend', panel);
    if (queries.length) panel.append(h('strong', {}, t('Búsquedas recientes')), ...queries.map(query => button(query, () => {
      close(); input.value = query; input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); remember();
    })), button(t('Borrar búsquedas recientes'), () => {
      api('recent_searches', {scope: section, account, clear: true}).catch(() => {});
      close();
    }));
    if (section === 'chats') {
      const peers = await api('frequent_peers', {account}).catch(() => []);
      if (current() && peers.length) panel.append(h('strong', {}, t('Chats frecuentes')), ...peers.map(peer =>
        button(peer.name, () => { close(); openChat(peer.id, true, peer); })));
    }
  };
  input.addEventListener('focus', show);
  input.addEventListener('blur', () => { setTimeout(() => { if (!panel?.contains(document.activeElement)) close(); }, 0); });
  input.addEventListener('change', remember);
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { remember(); close(); } else if (event.key === 'Escape') close(); });
  input.addEventListener('input', () => { if (input.value) close(); else if (document.activeElement === input) show(); });
}

function bulkButtons(select, clear) {
  return h('span', {class: 'bulk-buttons'}, button(t('Select all'), select), button(t('Desmarcar todos'), clear));
}

function bulkCheckRows(rows) {
  const available = rows.filter(row => !row.input.disabled);
  if (available.length < 2) return null;
  const choose = checked => available.forEach(row => {
    if (row.input.checked !== checked) {
      row.input.checked = checked;
      row.input.dispatchEvent(new Event('change', {bubbles: true}));
    }
  });
  return bulkButtons(() => choose(true), () => choose(false));
}

function joinedGroupMessages(left, right) {
  if (!left || !right || left.service || right.service || left.sender_id == null ||
      left.sender_id !== right.sender_id || left.out !== right.out) return false;
  if (!left.date || !right.date) return true;
  return Math.abs(right.date - left.date) <= 900 &&
    new Date(left.date * 1000).toDateString() === new Date(right.date * 1000).toDateString();
}

function groupSender(node, message, previous, next, group) {
  if (!group || message.service || message.out) return;
  const name = node.querySelector('.head .who');
  if (name) name.hidden = joinedGroupMessages(previous, message);
  node.classList.add('group-entry');
  const last = !joinedGroupMessages(message, next);
  const existing = node.querySelector('.sender-avatar');
  if (existing && !last) existing.remove();
  if (last && !existing) node.prepend(avatar(message.sender_id, message.sender, 'sender-avatar', null, message.color));
}

function messageFooter(message) {
  const ticks = message.out ? message.read ? '✓✓' : '✓' : '';
  return h('div', {class: 'meta message-footer'},
    message.edited ? h('span', {}, t('editado')) : null,
    h('time', {class: 'bubble-clock'}, message.time || ''), ticks ? h('span', {class: 'ticks'}, ticks) : null);
}

function showMessageDates(message, peer, kind, self) {
  if (state.selection?.size > 1) return;
  const panel = document.querySelector('#sheet-layer:not([hidden]) .sheet');
  if (!panel) return;
  const meta = h('div', {class: 'message-dates', 'aria-live': 'polite'});
  const formatted = seconds => new Date(seconds * 1000).toLocaleString(state.language || undefined,
    {dateStyle: 'medium', timeStyle: state.settings.show_seconds ? 'medium' : 'short'});
  if (message.edited_at) meta.append(h('div', {}, t('Editado el') + ' ' + formatted(message.edited_at)));
  panel.insertBefore(meta, panel.querySelector('.item'));
  if (!message.out || message.service || self || !message.date || !['user','group'].includes(kind) ||
      Date.now() / 1000 - message.date > 7 * 86400 || (kind === 'user' && !message.read)) return;
  const revision = state.accountRevision;
  api('message_read_details', {account: state.account, peer, id: message.id, group: kind === 'group'}).then(details => {
    if (revision !== state.accountRevision || !meta.isConnected || state.locked) return;
    if (details.read) meta.prepend(h('div', {}, '✓✓ ' + t('Read time') + ' · ' + details.read));
    if (details.readers?.length) {
      const first = details.readers[0];
      meta.prepend(h('div', {}, '✓✓ ' + t('Read time') + ' · ' + formatted(first.date) + ' (' + details.readers.length + ')'));
    }
  }).catch(() => {});
}
