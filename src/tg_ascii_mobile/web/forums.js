// Forum navigation shares the existing composer and discussion message view.
async function openForumList(chat, navigate = true, query = '') {
  const account = state.account;
  const request = state.openRequest = (state.openRequest || 0) + 1;
  if (state.open && !state.open.forumList && !(await saveDraft())) return;
  const data = await attempt(() => api('forum_topics', {peer: chat.id, query, account, open_view: true, window_peer: WINDOW_CHAT}));
  if (!data || state.account !== account || state.openRequest !== request || state.locked) return;
  state.open = {peer: chat.id, chat, forumList: {...data, query}, messages: [], outbox: []};
  state.reply = state.editing = state.selection = null;
  state.attachments = [];
  if (navigate && state.view !== 'chat') go('chat'); else {state.view = 'chat'; render();}
  return state.open;
}

function forumListView(open) {
  const chat = open.chat, list = open.forumList;
  const bar = h('div', {class: 'bar'}, backButton(),
    peerControl({class: 'title with-avatar peer-control', onclick: () => openProfile(chat)},
      avatar(chat.id, chat.name, 'small'), h('div', {class: 'names'}, nameWithStatus(chat.name, chat.emoji_status, true))),
    symbolButton('⋯', t('More options'), () => conversationMenu(chat)));
  const search = h('input', {type: 'search', value: list.query, placeholder: t('Buscar temas'),
    'aria-label': t('Buscar temas')});
  const results = h('div', {class: 'scroll topic-list'});
  let revision = 0;
  const fill = () => {
    results.replaceChildren();
    for (const topic of list.topics) {
      const status = [topic.closed ? t('Tema cerrado') : '', topic.hidden ? t('Oculto') : ''].filter(Boolean).join(' · ');
      const icon = topic.icon_emoji_id
        ? customEmoji(topic.icon_emoji_id, '#', false)
        : h('span', {class: 'topic-icon', style: '--topic-color:#' + (topic.icon_color || 0x6fb9f0).toString(16).padStart(6, '0')}, '#');
      if (topic.icon_emoji_id) icon.classList.add('topic-emoji');
      const row = h('div', {class: 'topic-row'},
        h('button', {class: 'topic-open', type: 'button', onclick: () => openForumTopic(chat, topic)},
          icon, h('span', {class: 'topic-name'}, topic.title, status ? h('small', {}, status) : null),
          topic.pinned ? h('span', {'aria-label': t('Fijar')}, '⌖') : null,
          topic.unread_count ? h('span', {class: 'unread'}, String(topic.unread_count)) : null),
        symbolButton('⋯', t('More options') + ' · ' + topic.title, () => forumTopicMenu(chat, topic)));
      results.append(row);
    }
    if (!list.topics.length) results.append(h('p', {class: 'muted'}, t('Sin resultados.')));
    if (list.next_cursor) results.append(button(t('Cargar más'), async () => {
      const token = ++revision;
      const page = await attempt(() => api('forum_topics', {peer: chat.id, query: list.query, cursor: list.next_cursor, account: state.account}));
      if (!page || state.open !== open || token !== revision) return;
      const seen = new Set(list.topics.map(item => item.id));
      list.topics.push(...page.topics.filter(item => !seen.has(item.id)));
      list.paged = true;
      list.next_cursor = page.next_cursor;
      fill();
    }));
  };
  let timer;
  search.oninput = () => {
    clearTimeout(timer);
    const token = ++revision, account = state.account;
    timer = setTimeout(async () => {
      const page = await attempt(() => api('forum_topics', {peer: chat.id, query: search.value, account}));
      if (!page || state.open !== open || token !== revision || state.account !== account) return;
      Object.assign(list, page, {query: search.value, paged: false});
      fill();
    }, 180);
  };
  open.refreshTopics = async () => {
    if (!results.isConnected || search.value !== list.query) return;
    const token = ++revision, query = list.query;
    let page;
    try { page = await api('forum_topics', {account: state.account, peer: chat.id, query}); }
    catch { return; }
    if (state.open !== open || token !== revision || !results.isConnected || state.locked) return;
    const ids = new Set(page.topics.map(topic => topic.id));
    const older = list.paged && page.next_cursor ? list.topics.filter(topic => !ids.has(topic.id)) : [];
    if (!older.length) {list.next_cursor = page.next_cursor; list.paged = false;}
    list.topics = [...page.topics, ...older];
    fill();
  };
  fill();
  const add = list.can_create ? button(t('Crear tema'), () => promptThen(t('Nombre del tema'), {}, async title => {
    if (!title.trim()) return false;
    const topic = await attempt(() => api('forum_manage', {peer: chat.id, action: 'create', title: title.trim(), account: state.account}));
    if (topic && state.open === open) await openForumTopic(chat, topic);
  })) : null;
  return [bar, h('div', {class: 'topic-toolbar'}, search, add), results];
}

async function openForumTopic(chat, topic, navigate = true) {
  const account = state.account;
  const request = state.openRequest = (state.openRequest || 0) + 1;
  if (state.open && !state.open.forumList && !(await saveDraft())) return;
  const data = await attempt(() => api('forum_open', {peer: chat.id, topic_id: topic.id, account, window_peer: WINDOW_CHAT}));
  if (!data || account !== state.account || request !== state.openRequest || state.locked) return;
  const previous = state.open;
  const open = {peer: chat.id, chat, topic: data.topic,
    thread: {root: topic.id, source: chat.id, channel: chat, topic: true, cursor: data.next},
    messages: data.messages, outbox: data.outbox, loadingOlder: false, done: !data.more,
    status: '', typing: '', translate: data.translate || null, translated: data.translated || {},
    translating: new Set(), originals: new Set()};
  if (navigate && previous && state.view === 'chat') history.pushState({view: 'chat', discussion: true}, '');
  state.open = open; state.view = 'chat';
  state.reply = state.editing = state.selection = null;
  state.attachments = [];
  const key = composerPeer(open);
  if (!draftWrites.has(draftKey(key)) && !failedDraftWrites.has(draftKey(key))) state.drafts[key] = data.draft;
  render();
  if (!data.topic.can_send) {
    document.querySelector('.composer')?.querySelectorAll('input, textarea, button').forEach(node => {node.disabled = true;});
    const field = document.getElementById('field');
    if (field) {field.disabled = true; field.placeholder = t('No puedes enviar mensajes a este tema');}
  }
  return open;
}

async function refreshOpenForum(peer, topicId) {
  const open = state.open, account = state.account, revision = state.accountRevision;
  if (!open || open.peer !== peer || state.locked) return;
  if (open.forumList) { await open.refreshTopics?.(); return; }
  if (!open.topic || (topicId != null && topicId !== open.topic.id) || !document.getElementById('messages')) return;
  const request = open.topicInfoRequest = (open.topicInfoRequest || 0) + 1;
  let info;
  try { info = await api('forum_topic_info', {account, peer, topic_id: open.topic.id}); }
  catch { return; }
  const pane = document.getElementById('scroll')?.parentElement;
  if (!pane || state.open !== open || state.account !== account || state.accountRevision !== revision ||
      state.locked || request !== open.topicInfoRequest) return;
  if (info) Object.assign(open.topic, info);
  else Object.assign(open.topic, {can_send: false, can_edit: false, can_hide: false, can_pin: false, can_delete: false});
  const label = pane.querySelector('.bar .title .names .label');
  if (label) label.textContent = open.topic.title;
  const editor = pane.querySelector(':scope > .composer');
  let notice = pane.querySelector(':scope > .readonly');
  if (open.topic.can_send) {
    if (editor) {editor.hidden = false; notice?.remove();}
    else if (notice) {notice.replaceWith(composer()); restoreComposer(document.getElementById('field'), state.drafts[composerPeer(open)]);}
  } else {
    if (editor && !editor.hidden) {saveDraft(); editor.hidden = true;}
    if (!notice) {notice = h('div', {class: 'readonly'}); pane.append(notice);}
    notice.textContent = info ? t('No puedes enviar mensajes a este tema') : t('This topic is no longer available.');
  }
}

function forumTopicMenu(chat, topic) {
  const account = state.account, open = state.open;
  const change = async (action, fields = {}) => {
    const result = await attempt(() => api('forum_manage', {peer: chat.id, topic_id: topic.id, action, account, ...fields}));
    if (result && account === state.account && state.open === open) {
      if (action === 'delete' && open.topic?.id === topic.id) await openForumList(chat, false);
      else await refreshOpenForum(chat.id, topic.id);
    }
  };
  sheet(topic.title, [
    [t('Abrir tema'), () => openForumTopic(chat, topic)],
    PLATFORM === 'iOS' ? [t('Compartir con Apple TV'), () => confirmThen(
      t('Compartir con Apple TV') + ' · ' + topic.title + '?',
      () => { if (state.account === account && !state.locked) return attempt(() => api('tv_share', {peer: chat.id, topic_id: topic.id, account})); })] : null,
    topic.can_edit ? [t('Cambiar nombre'), () => promptThen(t('Nombre del tema'), {value: topic.title}, title => change('edit', {title}))] : null,
    topic.can_edit ? [topic.closed ? t('Reabrir tema') : t('Cerrar tema'), () => change('edit', {closed: !topic.closed})] : null,
    topic.can_hide ? [topic.hidden ? t('Mostrar tema') : t('Ocultar tema'), () => change('edit', {hidden: !topic.hidden})] : null,
    topic.can_pin ? [topic.pinned ? t('Desfijar') : t('Fijar'), () => change('pin', {pinned: !topic.pinned})] : null,
    topic.can_delete ? [t('Eliminar tema'), () => confirmThen(t('Eliminar tema y todos sus mensajes'), () => change('delete'))] : null,
    [t('Todos los temas'), () => openForumList(chat, false)],
  ].filter(Boolean));
}

async function openLinkedDiscussion(chat) {
  const account = state.account;
  const linked = await attempt(() => api('linked_discussion', {peer: chat.id, account}));
  if (!linked || state.account !== account) return;
  return openChat(linked.peer, true, {id: linked.peer, name: linked.title, kind: linked.kind, forum: linked.forum});
}

async function chooseForumTarget(chat, action, cursor = null, query = '') {
  const account = state.account;
  const result = await attempt(() => api('forum_topics', {peer: chat.id, account, cursor, query}));
  if (!result || state.account !== account) return;
  sheet(t('Elegir tema'), [
    [t('Buscar temas'), () => promptThen(t('Buscar temas'), {value: query},
      value => chooseForumTarget(chat, action, null, value))],
    ...result.topics.filter(topic => topic.can_send).map(topic => [topic.title, () => {
      if (state.account === account) action(topic);
    }]),
    result.next_cursor ? [t('Cargar más'), () => chooseForumTarget(chat, action, result.next_cursor, query)] : null,
  ].filter(Boolean));
}
