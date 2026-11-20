// Active stories are fetched only when the section is opened.
function openStories() {
  go('stories');
  refreshStories();
}

async function refreshStories() {
  const revision = state.accountRevision;
  const feed = state.storyFeed = { revision, rows: null };
  render();
  try { feed.rows = await api('stories', { account: state.account }); }
  catch (error) { feed.error = error.message; }
  if (state.view === 'stories' && state.storyFeed === feed && state.accountRevision === revision) render();
}

function storiesView() {
  const feed = state.storyFeed?.revision === state.accountRevision ? state.storyFeed : null;
  const list = h('div', { class: 'scroll' });
  if (feed?.error) list.append(h('div', { class: 'empty error' }, feed.error));
  else if (!feed?.rows) list.append(h('div', { class: 'empty spinner' }, t('Cargando...')));
  else if (!feed.rows.length) list.append(h('div', { class: 'empty' }, t('No active stories.')));
  else feed.rows.forEach((item, index) => list.append(h('button', { class: 'row', onclick: () => storyViewer(feed.rows, index) },
    avatar(item.peer, item.name), h('div', { class: 'body' }, h('div', { class: 'name' }, item.name),
      h('div', { class: 'preview' }, item.caption || t('Story'))))));
  return [h('div', { class: 'bar' }, backButton(), h('div', { class: 'title' }, t('Stories')),
    button(t('Refresh'), refreshStories)), button(t('Publish story'), composeStory), list];
}

function storyViewer(items, index) {
  const account = state.account;
  const layer = mediaDialog(t('Story'));
  const seen = new Set();
  function show() {
    const item = items[index];
    const identity = item.peer + '/' + item.id;
    const url = '/story?' + resourceAuth() + '&' + new URLSearchParams({ account, peer: item.peer, id: item.id, view: crypto.getRandomValues(new Uint32Array(4)).join('-') });
    const read = () => {
      if (!layer.open || !media.isConnected || state.account !== account || seen.has(identity)) return;
      seen.add(identity);
      attempt(() => api('story_read', {account, peer: item.peer, id: item.id}));
    };
    const media = item.video ? h('video', { src: url, controls: true, playsinline: true, autoplay: true, onplaying: read })
      : h('img', { src: url, alt: item.caption || item.name, onload: read });
    media.addEventListener('error', () => media.replaceWith(h('div', {class: 'error'}, t('Media unavailable.'))));
    const previous = button(t('Previous'), () => { index--; show(); });
    const next = button(t('Next'), () => { index++; show(); });
    previous.disabled = index === 0;
    next.disabled = index === items.length - 1;
    layer.replaceChildren(h('div', {class: 'bar'}, h('div', {class: 'title'}, item.name),
      button(t('Cerrar'), () => layer.close())), h('div', {class: 'stage'}, media),
      h('div', {}, item.caption), h('div', {class: 'bar'}, previous, index + 1 + ' / ' + items.length, next));
  }
  layer.showModal();
  show();
}

function composeStory() {
  const account = state.account, revision = state.accountRevision;
  chooseFiles('media', {limit: 1, accept: 'image/jpeg,image/png,video/mp4', receive: ([file]) => {
    if (!file) return;
    if (state.accountRevision !== revision || state.view !== 'stories') {
      api('discard_files', {keys: [file.key]}).catch(() => {});
      return;
    }
    const caption = h('textarea', { rows: 2 });
    const audience = h('select', {}, h('option', {value: 'contacts'}, t('Contacts only')),
      h('option', {value: 'close'}, t('Close friends')), h('option', {value: 'everyone'}, t('Everyone')));
    let submitting = false, panel;
    formSheet(t('Publish story'), [h('div', {}, file.name), labelled(t('Caption'), caption),
      labelled(t('Audience'), audience), h('div', {class: 'muted'}, t('Visible for 24 hours. Telegram applies your account’s posting limits.'))],
    t('Publish story'), async () => {
      if (submitting || revision !== state.accountRevision || state.locked) return false;
      submitting = true;
      try {
        await api('publish_story', {account, key: file.key, caption: caption.value, audience: audience.value});
      } catch (error) {
        toast(error.message, 'error');
        submitting = false;
        if (!panel.isConnected) api('discard_files', {keys: [file.key]}).catch(() => {});
        return false;
      }
      if (revision === state.accountRevision && state.view === 'stories') {
        toast(t('Story published.'));
        refreshStories();
      }
      return panel === currentSheetPanel;
    });
    panel = currentSheetPanel;
    panel.onDismiss = () => { if (!submitting) api('discard_files', {keys: [file.key]}).catch(() => {}); };
  }});
}
