// The interface background and the message surface are independent.
const remoteWallpapers = new Map();
function wallpaperUrl(file, preview = false) {
  return '/chat-wallpaper?' + resourceAuth() + '&' + new URLSearchParams({
    account: state.account, name: file, preview: preview ? '1' : '0'
  });
}

function resolveChatBackdrop(peer) {
  const look = state.appearance || {}, choices = look.chat_wallpapers || {};
  const key = String(peer), local = choices[key];
  const legacy = look.chats?.[key];
  let chosen = local || choices.all;
  const follow = local ? !!local.sync : !legacy && choices._follow;
  if (follow && state.account && state.connection === 'online') {
    const account = state.account, cacheKey = account + '/' + key;
    let entry = remoteWallpapers.get(cacheKey);
    if (!entry || entry.until < Date.now()) {
      entry = {until: Date.now() + 60000, result: entry?.result};
      remoteWallpapers.set(cacheKey, entry);
      api('remote_chat_wallpaper', {account, peer}).then(result => {
        if (state.account !== account || state.locked || remoteWallpapers.get(cacheKey) !== entry) return;
        entry.result = result;
        for (const node of document.querySelectorAll('[data-wallpaper-peer]')) {
          if (node.dataset.wallpaperPeer === key) paintChatWallpaper(node, peer);
        }
      }).catch(() => { entry.until = Date.now() + 10000; });
    }
    if (entry.result !== undefined) chosen = entry.result || choices.all;
  }
  if (!local && legacy) return {background: backdrop(legacy === 'interface' ? look.background : legacy)};
  if (chosen?.interface) return {background: backdrop(look.background)};
  if (!chosen?.file) return {background: ''};
  const url = wallpaperUrl(chosen.file);
  return {background: 'url("' + url + '")', motion: chosen.motion};
}

function paintChatWallpaper(node, peer) {
  const look = resolveChatBackdrop(peer);
  node.dataset.wallpaperPeer = String(peer);
  node.style.backgroundImage = look.background;
  node.classList.toggle('moving-wallpaper', !!look.motion);
  if (!node.dataset.wallpaperAttached) {
    node.dataset.wallpaperAttached = '1';
    node.addEventListener('pointermove', event => {
      if (!node.classList.contains('moving-wallpaper') || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const box = node.getBoundingClientRect();
      node.style.setProperty('--wall-x', (40 + 20 * (event.clientX - box.left) / box.width) + '%');
      node.style.setProperty('--wall-y', (40 + 20 * (event.clientY - box.top) / box.height) + '%');
    }, {passive: true});
  }
}

function updateWallpapers(look, revision) {
  if (state.accountRevision !== revision || state.locked) return;
  remoteWallpapers.clear();
  state.appearance = look;
  applySettings();
  if (state.view === 'settings') render();
}
function setWallpaperFollowing(enabled) {
  const revision = state.accountRevision;
  attempt(() => api('follow_chat_wallpapers', {account: state.account, enabled}), look => updateWallpapers(look, revision));
}

function openWallpaperMenu(chat) {
  const target = chat ? String(chat.id) : 'all';
  const account = state.account, revision = state.accountRevision;
  const alive = () => revision === state.accountRevision && !state.locked;
  const choices = state.appearance?.chat_wallpapers || {};
  const current = choices[target] || (chat && state.appearance?.chats?.[target]);
  const edit = (source, params = {}, record = {}) => {
    if (alive()) editWallpaper(chat, {account, target, source, ...params}, record);
  };
  const gallery = async () => {
    const records = await attempt(() => api('wallpaper_gallery', {account}));
    if (!records || !alive()) return;
    if (!records.length) return toast(t('No backgrounds available'));
    sheet(t('Telegram backgrounds'), records.map(record => [record.name,
      () => edit('gallery', {catalog_id: record.id}, record)]));
  };
  const reset = (sync) => attempt(() => api('apply_chat_wallpaper', {account, target, source: 'reset', sync}),
    look => updateWallpapers(look, revision));
  const actions = [
    [t('Image'), async () => {
      const key = await attempt(pickImage);
      if (key && alive()) edit('image', {key});
    }],
    [t('Color / gradient'), () => edit('fill')],
    [t('Telegram backgrounds'), gallery],
  ];
  if (current?.source) actions.unshift([t('Preview and edit'), async () => {
    let record = {};
    if (current.source === 'gallery') {
      const rows = await attempt(() => api('wallpaper_gallery', {account}));
      record = rows?.find(row => row.id === current.catalog_id);
      if (!record) return toast(t('No backgrounds available'));
    }
    edit(current.source, {catalog_id:current.catalog_id}, {...record, ...current.options, sync:current.sync});
  }]);
  if (chat && state.appearance?.background) actions.push([t('Use the interface background'), () =>
    attempt(() => api('apply_chat_wallpaper', {account, target, source: 'interface'}),
      look => updateWallpapers(look, revision))]);
  if (current) actions.push([t('Restore default'), () => current.sync ?
    sheet(t('Restore default'), [[t('Only on this device'), () => reset('')],
      [t('Also in Telegram'), () => reset(current.sync)]]) : reset('')]);
  sheet(chat?.name || t('All chats in this app'), actions);
}

function editWallpaper(chat, request, record) {
  const revision = state.accountRevision;
  const editableColors = request.source === 'fill' || record.pattern || record.colors?.length;
  const colors = (record.colors?.length ? record.colors : ['#d6e2d1']).map(value => h('input', {type:'color', value}));
  const colorList = h('div', {class: 'wallpaper-colors'});
  const redraw = () => colorList.replaceChildren(...colors,
    colors.length < 4 ? button('+', () => { colors.push(h('input', {type:'color',value:'#79a9ba'})); redraw(); }) : '',
    colors.length > 1 ? button('−', () => { colors.pop(); redraw(); }) : '');
  redraw();
  const angle = h('input', {type:'range', min:0, max:315, step:45, value:record.rotation || 0});
  const intensity = h('input', {type:'range', min:-100, max:100, value:record.intensity ?? 50});
  const [moveRow, motion] = check(t('Motion'), !!record.motion);
  const [blurRow, blur] = check(t('Blur'), !!record.blur);
  const sync = h('select', {}, h('option', {value:''}, t('Only on this device')),
    (chat || !(request.source === 'fill' || (request.source === 'gallery' && !record.has_file))) && (!chat || (chat.kind !== 'secret' && !chat.self))
      ? h('option', {value:'devices'}, t('On all my devices (Telegram)')) : null,
    chat?.kind === 'user' && !chat.self ? h('option', {value:'both'}, t('Also for {name}').replace('{name}',chat.name)) : null);
  if (record.sync && [...sync.options].some(option => option.value === record.sync)) sync.value = record.sync;
  const options = () => ({motion: motion.checked, blur: blur.checked,
    ...(editableColors ? {colors:colors.map(node=>node.value),rotation:Number(angle.value)} : {}),
    ...(record.pattern ? {intensity:Number(intensity.value)} : {})});
  const preview = h('img', {class:'wallpaper-preview', alt:t('Preview'), hidden:true});
  let busy = false, panel;
  const showPreview = async () => {
    const result = await attempt(() => api('apply_chat_wallpaper', {...request, options:options(), preview:true}));
    if (result && panel?.isConnected && revision === state.accountRevision) {
      preview.src = wallpaperUrl(result.file, true); preview.hidden = false;
    }
  };
  formSheet(t('Preview and edit'), [preview,
    editableColors ? colorList : null, editableColors ? labelled(t('Rotation'),angle) : null,
    record.pattern ? labelled(t('Intensity'),intensity) : null,
    moveRow, !(request.source === 'fill' || record.pattern) ? blurRow : null,
    labelled(t('Apply to'),sync), button(t('Preview'),showPreview)].filter(Boolean), t('Apply'), async () => {
      if (busy || revision !== state.accountRevision) return false;
      busy = true;
      try {
        const look = await api('apply_chat_wallpaper', {...request, options:options(), sync:sync.value});
        updateWallpapers(look, revision);
        return currentSheetPanel === panel;
      } catch (error) { toast(error.message,'error'); busy = false; return false; }
    });
  panel = currentSheetPanel;
  panel.onDismiss = () => {
    if (!busy && request.key) api('discard_files', {keys:[request.key]}).catch(()=>{});
  };
  showPreview();
}
