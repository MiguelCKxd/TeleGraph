// Run with Playwright and either its Chromium build or CHROME pointing to a browser.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const chats = [
  {id: 17, name: 'Alba', kind: 'user'}, {id: 22, name: 'Leo', kind: 'user'},
  {id: -1000000000045, name: 'Foro del valle', kind: 'group', forum: true},
  {id: -1000000000080, name: 'Excursiones', kind: 'channel'},
  {id: -1000000000041, name: 'Debate del valle', kind: 'group'}
];
const [alba, leo, forum, channel, group] = chats;
const topics = [{id: 1, title: 'General'}, {id: 7, title: 'Lagos'}, {id: 9, title: 'Caminos'}]
  .map(topic => ({...topic, can_send: true}));
topics[1].icon_emoji_id = '9000000000000000003';
const info = new Map(topics.map(topic => [topic.id, {...topic}]));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR42mP4z8DAwMDAxMDAwMDAAAANHgEDvH2IPAAAAABJRU5ErkJggg==', 'base64');
const account = 'sendero';
const calls = [];
const passed = [];
const promoted = new Set();
const drafts = new Map();
let nativeWindow = false;
let delayMethod, release, failMethod, pagedMedia = false;

function message(id, fields = {}) {
  return {id, text: 'Mensaje ' + id, sender: 'Nora', sender_id: 71, date: 1770000000 + id,
    time: '10:30', visual: false, kind: '', w: 3, h: 2, ...fields};
}
function photo(id, fields) {
  return message(id, {visual: true, kind: 'image', caption: 'Vista ' + id, ...fields});
}
function neighbors(id, fields) {
  return Array.from({length: 61}, (_, index) => index === 30 ? photo(id, fields) : message(id - 30 + index, fields));
}
function snapshot(key = account) {
  return {account: key, stage: 'ready', language: 'es', rtl: false, locked: false, connection: 'online',
    accounts: [], appearance: {}, lock: {}, settings: {font_size: 12, bubbles: true, inline_media: true, photo_previews: true}};
}
async function api(name, args) {
  calls.push({name, ...args});
  if (name === delayMethod) {
    delayMethod = null;
    await new Promise(resolve => {release = resolve;});
  }
  if (name === failMethod) { failMethod = null; throw new Error('Network unavailable'); }
  switch (name) {
    case 'state': return snapshot();
    case 'strings': return {'Go to message': 'Ir al mensaje', 'Shared media': 'Archivos compartidos'};
    case 'chats': return chats;
    case 'system_window': return {opened: nativeWindow};
    case 'window_open':
    case 'window_send': {
      const chat = chats.find(item => item.id === args.peer);
      if (chat.forum || promoted.has(chat.id)) return {forum: true, chat: {...chat, forum: true}};
      if (name === 'window_send') return {key: 'queue'};
      return {chat, messages: [message(809)], draft: drafts.get(args.account + ':' + args.peer) ||
        {text: '', files: [], formats: [], custom: [], reply: null}};
    }
    case 'appearance': return args.values || {};
    case 'window_close': return true;
    case 'draft':
      drafts.set(args.account + ':' + args.peer, {text: args.text, files: args.files || [],
        formats: args.formats || [], custom: args.custom || [], reply: args.reply, photo_quality: args.photo_quality});
      return true;
    case 'send': case 'send_files': return {key: 'queue'};
    case 'pick_files': return [{key: 'fixture-photo.png', name: 'photo.png', size: 100}];
    case 'open': {
      const chat = chats.find(item => item.id === args.peer);
      if (chat.forum) return {forum: true, chat};
      const rows = neighbors(515);
      rows[30] = photo(515, {album: '9000000000000000001'});
      rows[31] = photo(516, {album: '9000000000000000001', kind: 'video'});
      return {chat, messages: rows, outbox: {items: []}};
    }
    case 'shared_media':
      if (pagedMedia && args.peer === leo.id && args.kind === 'photos_only')
        return args.offset ? [photo(450), photo(449)] : Array.from({length: 50}, (_, i) => photo(500 - i));
      if (args.kind === 'photos_only') return [photo(515)];
      if (args.kind === 'videos') return [photo(80, {kind: 'video'})];
      if (args.peer === forum.id) return [photo(90, {topic_id: 1}), photo(70, {topic_id: 7})];
      if (args.peer === group.id) return [photo(85, {thread_root: 30, kind: 'video'})];
      return [photo(515), photo(80, {kind: 'video'})];
    case 'forum_topics': return {topics, next_cursor: null};
    case 'forum_topic_info': return info.get(args.topic_id) ?? null;
    case 'forum_open': return {topic: topics.find(topic => topic.id === args.topic_id),
      messages: neighbors(515, {topic_id: args.topic_id}), outbox: [], next: 485, more: false};
    case 'comments': return {peer: group.id, root_id: 30, root: message(30), messages: neighbors(515, {thread_root: 30}),
      outbox: [], next: 485, more: false};
    case 'gallery_origin': return {account, peer: group.id, id: args.id, source: channel.id,
      source_name: channel.name, post: 28, root: 30};
    case 'context': {
      if (args.topic_id || args.thread_root) {
        const scope = args.topic_id ? {topic_id: args.topic_id} : {thread_root: args.thread_root};
        return {messages: neighbors(args.id, scope), next: args.id - 30, more: true};
      }
      return neighbors(args.id);
    }
    case 'older': case 'forum_older': case 'comments_older': return {messages: [], more: false};
    case 'profile_photos': return {items: [{id: '9000000000000000001', kind: 'image', offset: 0}], next: null};
    case 'folders': case 'pinned': case 'contacts': return [];
    default: return null;
  }
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname === '/events') {
    res.writeHead(200, {'Content-Type': 'text/event-stream'});
    res.write(': ready\n\n'); return;
  }
  if (url.pathname.startsWith('/api/')) {
    let body = ''; for await (const part of req) body += part;
    try {
      const result = await api(url.pathname.slice(5), JSON.parse(body || '{}'));
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({ok: true, result}));
    } catch (error) {
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({ok: false, error: error.message}));
    }
    return;
  }
  if (['/avatar', '/media', '/profile-photo', '/logo', '/sticker'].includes(url.pathname)) {
    res.writeHead(200, {'Content-Type': 'image/png'}); res.end(png); return;
  }
  const file = path.join(web, url.pathname === '/' ? 'index.html' : url.pathname);
  if (!fs.existsSync(file)) {res.writeHead(404); res.end(); return;}
  res.writeHead(200, {'Content-Type': {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'}[path.extname(file)] || 'text/plain'});
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({executablePath: process.env.CHROME, headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    const faults = [];
    page.on('pageerror', error => faults.push(error.message));
    await page.goto('http://127.0.0.1:' + server.address().port + '/?platform=iOS&t=fixture');
    const dialog = page.locator('.media-viewer[open]');
    const jump = dialog.getByRole('button', {name: 'Ir al mensaje', exact: true});
    const shared = async (chat, index) => {
      await page.evaluate(chat => openShared(chat, 'photos'), chat);
      await page.locator('.grid .cell').nth(index).click();
    };
    const check = async (peer, id) => {
      await page.locator('#m' + id + '.flash').waitFor();
      await page.waitForFunction(id => {
        const node = document.getElementById('m' + id);
        if (!node || document.activeElement !== node) return false;
        const box = document.getElementById('scroll').getBoundingClientRect(), row = node.getBoundingClientRect();
        return Math.abs(row.top + row.bottom - box.top - box.bottom) <= 6;
      }, id, {timeout: 2500});
      const focused = await page.evaluate(id => {
        const node = document.getElementById('m' + id);
        const row = node.getBoundingClientRect(), view = document.getElementById('scroll').getBoundingClientRect();
        return {peer: state.open.peer, view: state.view, focus: document.activeElement === node,
          centerError: Math.abs((row.top + row.bottom - view.top - view.bottom) / 2),
          outline: getComputedStyle(node).outlineStyle};
      }, id);
      assert.equal(focused.peer, peer);
      assert.equal(focused.view, 'chat');
      assert.equal(focused.focus, true);
      assert.equal(focused.outline, 'solid');
      assert(focused.centerError <= 3, JSON.stringify(focused));
      assert.equal(await dialog.count(), 0);
      return focused.centerError;
    };

    await page.getByRole('button', {name: alba.name, exact: true}).click();
    await page.locator('#m515 .media').click();
    await dialog.locator('.gallery-strip button').nth(1).click();
    await dialog.locator('video').waitFor();
    await jump.click();
    passed.push({case: 'Álbum, vídeo elegido, misma conversación', centerErrorPx: await check(alba.id, 516)});
    assert(!calls.some(row => row.name === 'context'));

    await shared(leo, 0);
    await jump.click();
    passed.push({case: 'Mismo número de mensaje en dos chats', centerErrorPx: await check(leo.id, 515)});
    await shared(leo, 1);
    await jump.click();
    passed.push({case: 'Vídeo antiguo compartido por otro usuario', centerErrorPx: await check(leo.id, 80)});
    assert(calls.some(row => row.name === 'context' && row.account === account && row.peer === leo.id && row.id === 80));

    await page.evaluate(forum => openForumList(forum), forum);
    await page.waitForFunction(() => {
      const img = document.querySelector('.topic-emoji');
      return img?.naturalWidth > 0 && new URL(img.currentSrc).pathname === '/sticker';
    });
    passed.push({case: 'Emoji personalizado del tema por la ruta del servidor'});
    await page.locator('.topic-open', {hasText: 'Caminos'}).click();
    await page.waitForFunction(() => state.open?.topic?.id === 9 && !!document.getElementById('field'));
    await page.evaluate(forum => openShared(forum, 'photos'), forum);
    await page.locator('.grid').waitFor();
    const beforeUpdate = calls.filter(row => row.name === 'forum_open').length;
    await page.evaluate(peer => EVENTS.forum_topics({peer, topic_id: 7}), forum.id);
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(() => state.view), 'shared', 'Una actualización de otro tema interrumpió los archivos compartidos');
    assert.equal(calls.filter(row => row.name === 'forum_open').length, beforeUpdate);
    passed.push({case: 'Actualización de otro tema mientras se ven los archivos compartidos'});
    for (const [index, topic, id] of [[1, 7, 70], [0, 1, 90]]) {
      await shared(forum, index);
      await jump.click();
      passed.push({case: 'Foto compartida en ' + topics.find(row => row.id === topic).title,
        centerErrorPx: await check(forum.id, id)});
      assert.equal(await page.evaluate(() => state.open.topic.id), topic);
      assert(calls.some(row => row.name === 'context' && row.peer === forum.id && row.topic_id === topic && row.id === id));
    }
    await page.locator('#field').fill('Preparando la ruta del sábado');
    await page.evaluate(() => saveDraft());
    info.set(1, {...topics[0], title: 'Punto de encuentro'});
    const metadata = await page.evaluate(async peer => {
      const field = document.getElementById('field'), target = document.getElementById('m90');
      const history = state.open.messages, scroll = document.getElementById('scroll'), top = scroll.scrollTop;
      await EVENTS.forum_topics({peer, topic_id: 1});
      return {sameField: field === document.getElementById('field'), draft: field.value,
        samePhoto: target === document.getElementById('m90'), sameHistory: history === state.open.messages,
        samePosition: scroll.scrollTop === top, title: document.querySelector('.bar .title .names .label').textContent};
    }, forum.id);
    assert.deepEqual(metadata, {sameField: true, draft: 'Preparando la ruta del sábado', samePhoto: true,
      sameHistory: true, samePosition: true, title: 'Punto de encuentro'});
    info.get(1).can_send = false;
    await page.evaluate(peer => EVENTS.forum_topics({peer, topic_id: 1}), forum.id);
    assert(await page.locator('.composer').isHidden());
    info.get(1).can_send = true;
    await page.evaluate(peer => EVENTS.forum_topics({peer, topic_id: 1}), forum.id);
    assert.equal(await page.locator('#field').inputValue(), 'Preparando la ruta del sábado');
    passed.push({case: 'Cambio de nombre y permisos sin perder borrador, foto ni posición'});
    await page.evaluate(() => forumTopicMenu(state.open.chat, state.open.topic));
    await page.getByRole('button', {name: 'Compartir con Apple TV', exact: true}).click();
    await Promise.all([page.waitForResponse(res => new URL(res.url()).pathname === '/api/tv_share'),
      page.getByRole('button', {name: 'Confirm', exact: true}).click()]);
    assert(calls.some(row => row.name === 'tv_share' && row.peer === forum.id && row.topic_id === 1 && row.account === account));
    passed.push({case: 'Compartir sólo el tema elegido con Apple TV en iOS'});
    await shared(group, 0);
    await jump.click();
    passed.push({case: 'Vídeo en comentarios del grupo vinculado', centerErrorPx: await check(group.id, 85)});
    assert.deepEqual(await page.evaluate(() => [state.open.thread.source, state.open.thread.post, state.open.thread.root]),
      [channel.id, 28, 30]);
    assert.equal(await page.evaluate(() => state.open.messages[0].id), 30);
    assert(calls.some(row => row.name === 'context' && row.peer === group.id && row.thread_root === 30));
    await page.locator('#m85 .media').click();
    const lookups = calls.filter(row => row.name === 'gallery_origin').length;
    await jump.click();
    await check(group.id, 85);
    assert.equal(calls.filter(row => row.name === 'gallery_origin').length, lookups);
    passed.push({case: 'Comentario abierto directamente en su propio hilo'});

    await page.evaluate(() => avatarViewer({id: 17, name: 'Alba', has_photo: true}));
    await dialog.locator('.photo-stage img').waitFor();
    assert.equal(await jump.count(), 0);
    await dialog.getByRole('button', {name: 'Close', exact: true}).click();
    passed.push({case: 'Foto de perfil sin acción de mensaje'});

    for (const offline of [true, false]) {
      await shared(group, 0);
      const before = await page.evaluate(() => ({peer: state.open.peer, root: state.open.thread?.root,
        scroll: document.getElementById('scroll')?.scrollTop, view: state.view}));
      const start = calls.length;
      if (offline) await page.evaluate(() => {state.connection = 'offline';});
      else failMethod = 'gallery_origin';
      await jump.click();
      await page.waitForTimeout(80);
      assert.equal(await dialog.count(), 1, 'Resolver un origen sin conexión debe conservar el visor');
      assert.equal(await jump.isEnabled(), true);
      assert(await dialog.locator('.gallery-notice').isVisible());
      assert.deepEqual(await page.evaluate(() => ({peer: state.open.peer, root: state.open.thread?.root,
        scroll: document.getElementById('scroll')?.scrollTop, view: state.view})), before);
      assert(!calls.slice(start).some(row => ['open', 'comments', 'context'].includes(row.name)));
      if (offline) assert(!calls.slice(start).some(row => row.name === 'gallery_origin'));
      await page.evaluate(() => {state.connection = 'online';});
      await jump.click();
      await check(group.id, 85);
      passed.push({case: offline ? 'Sin conexión conserva vídeo y permite reintentar el hilo correcto' :
        'Fallo de red antes de actualizar estado conserva visor y navegación'});
    }
    await page.evaluate(chat => openShared(chat, 'photos'), leo);
    await page.locator('.shared-filters').waitFor();
    assert.equal(await page.locator('.grid .cell').count(), 2);
    await page.locator('.shared-filters').getByRole('button', {name: 'Photos', exact: true}).click();
    await page.waitForFunction(() => state.shared?.kind === 'photos_only' && state.shared.items?.length === 1);
    await page.locator('.grid .cell').click();
    assert.equal(await dialog.locator('video').count(), 0);
    assert.equal(await dialog.locator('.stage img').count(), 1);
    assert.equal(await dialog.locator('.stage img').getAttribute('src').then(value => new URL(value, 'http://local').searchParams.get('quality')), 'display');
    const originalImage = await dialog.locator('.stage img').elementHandle();
    await page.evaluate(() => document.dispatchEvent(new Event('appearancechange')));
    assert(await originalImage.evaluate(node => node.isConnected), 'Appearance updates must preserve the pinched image');
    await dialog.getByRole('button', {name: 'Close', exact: true}).click();
    await page.evaluate(() => {state.settings.advanced_features = {media_originals: true};});
    await page.locator('.grid .cell').click();
    assert.equal(await dialog.locator('.stage img').getAttribute('src').then(value => new URL(value, 'http://local').searchParams.get('quality')), null);
    await dialog.getByRole('button', {name: 'Close', exact: true}).click();
    await page.locator('.shared-filters').getByRole('button', {name: 'Videos', exact: true}).click();
    await page.waitForFunction(() => state.shared?.kind === 'videos' && state.shared.items?.length === 1);
    await page.locator('.grid .cell').click();
    const videoElement = await dialog.locator('video').elementHandle();
    assert(await videoElement.getAttribute('poster'));
    assert(new URL(await videoElement.getAttribute('src'), 'http://local').searchParams.get('stream'));
    await dialog.getByRole('button', {name: 'Close', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('.media-viewer'));
    assert.equal(await videoElement.getAttribute('src'), null, 'Closing the viewer must release the video download');
    assert(await videoElement.evaluate(node => node.paused));
    passed.push({case: 'Filtros fotos/vídeos, original opcional, miniaturas reducidas y liberación del reproductor'});
    pagedMedia = true;
    await page.locator('.shared-filters').getByRole('button', {name: 'Photos', exact: true}).click();
    await page.waitForFunction(() => state.shared.items?.length === 50);
    await page.locator('.grid .cell').last().click();
    await page.waitForFunction(() => state.shared.items?.length === 52);
    await dialog.getByRole('button', {name: 'Previous page', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('.media-viewer .caption')?.textContent === 'Vista 450');
    assert(calls.some(row => row.name === 'shared_media' && row.kind === 'photos_only' && row.offset === 451));
    assert.equal(await dialog.locator('video').count(), 0);
    assert(await dialog.locator('.gallery-strip button').count() <= 31);
    await dialog.getByRole('button', {name: 'Close', exact: true}).click();
    pagedMedia = false;
    passed.push({case: 'Filtro conservado al paginar y vecindario de miniaturas con límite'});
    await shared(group, 0);
    delayMethod = 'gallery_origin';
    await jump.click();
    const deadline = Date.now() + 3000;
    while (!release && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 5));
    assert(release, 'La consulta de origen debe estar pendiente');
    const count = calls.length;
    await page.evaluate(snapshot => {adopt(snapshot); render();}, snapshot('otra'));
    release();
    await page.waitForTimeout(80);
    assert.equal(await dialog.count(), 0);
    assert.equal(await page.evaluate(() => state.open), null);
    assert(!calls.slice(count).some(row => ['open', 'comments', 'context'].includes(row.name)));
    passed.push({case: 'Cambio de cuenta durante la resolución de origen'});
    const android = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    await android.goto('http://127.0.0.1:' + server.address().port + '/?platform=Android&t=fixture');
    await android.getByRole('button', {name: alba.name, exact: true}).waitFor();
    await android.evaluate(async ({forum, topic}) => {
      await openForumTopic(forum, topic); forumTopicMenu(state.open.chat, state.open.topic);
    }, {forum, topic: topics[0]});
    assert(await android.locator('#sheet-layer').isVisible());
    assert.equal(await android.getByRole('button', {name: 'Compartir con Apple TV'}).count(), 0);
    passed.push({case: 'Menú de tema en Android sin el destino Apple TV'});
    android.on('pageerror', error => faults.push(error.message));
    await android.evaluate(() => closeSheet(true));
    const windowsStart = calls.length;
    nativeWindow = true;
    await android.evaluate(chat => openChatWindow(chat), forum);
    assert.equal(await android.evaluate(() => state.open.topic.id), 1);
    assert.deepEqual(calls.slice(windowsStart).filter(row => ['system_window', 'window_open', 'forum_topics'].includes(row.name))
      .map(row => row.name), ['system_window']);
    nativeWindow = false;
    await android.evaluate(chat => openChatWindow(chat), forum);
    await android.locator('.topic-list').waitFor();
    assert.equal(await android.locator('.chatwin textarea, #field').count(), 0);
    assert(!calls.slice(windowsStart).some(row => row.name === 'window_open'));
    passed.push({case: 'Ventana nativa disponible y selector directo si falta la ventana nativa'});

    promoted.add(group.id);
    await android.evaluate(chat => openChatWindow(chat), group);
    await android.waitForFunction(peer => state.open?.peer === peer && !!state.open.forumList && !state.windows.length, group.id);
    assert.equal(await android.locator('.chatwin textarea, #field').count(), 0);
    await android.evaluate(({forum, group, account}) => {
      state.windowsRestored = false;
      state.appearance.windows = [forum, group].map(chat => ({peer: chat.id, name: chat.name, account}));
      restoreWindows();
    }, {forum, group, account});
    await android.waitForFunction(() => state.windows.length === 2 && state.windows.every(win => win.forumChat));
    assert.equal(await android.locator('.chatwin textarea, .chatwin .msg').count(), 0);
    await android.evaluate(peer => {
      EVENTS.message({peer, message: {id: 810, text: 'De otro tema', topic_id: 9}});
      EVENTS.history({peer, messages: [{id: 811, text: 'General', topic_id: 1}]});
    }, group.id);
    assert(await android.evaluate(() => state.windows.every(win => !win.messages.length)));
    const activeWindows = android.locator('.chatwin:not(.closing-window)');
    const restored = activeWindows.filter({hasText: group.name});
    await restored.getByRole('button', {name: 'Todos los temas'}).click();
    await android.waitForFunction(() => state.windows.length === 1);
    await android.evaluate(() => closeWindow(state.windows[0]));
    passed.push({case: 'Restaurar dos foros sin historial mezclado ni compositor, incluso con metadatos antiguos'});

    promoted.delete(group.id);
    await android.evaluate(chat => openChatWindow(chat), group);
    const floating = activeWindows.locator('textarea');
    await floating.fill('Ruta pendiente para el grupo');
    promoted.add(group.id);
    await android.evaluate(() => sendFromWindow(state.windows[0]));
    assert.equal(await android.locator('.chatwin textarea, .chatwin .msg').count(), 0);
    assert.equal(await android.evaluate(peer => state.drafts[peer].text, group.id), 'Ruta pendiente para el grupo');
    assert(!calls.slice(windowsStart).some(row => ['send', 'send_files'].includes(row.name)));
    await activeWindows.getByRole('button', {name: 'Todos los temas'}).click();
    await android.waitForFunction(() => !state.windows.length);
    for (const topic of [topics[0], topics[2]]) {
      await android.locator('.topic-open', {hasText: topic.title}).click();
      await android.locator('#field').fill('Envío explícito ' + topic.title);
      await android.evaluate(() => send());
      assert(calls.some(row => row.name === 'send' && row.peer === group.id && row.topic_id === topic.id && row.thread_root === topic.id));
      await android.evaluate(() => openForumList(state.open.chat));
    }
    passed.push({case: 'Conversión durante envío: conservar el borrador y enviar sólo al tema elegido, incluido General'});
    promoted.delete(group.id);
    await android.evaluate(chat => openChatWindow(chat), group);
    await floating.fill('Borrador de conversión en directo');
    await android.evaluate(chat => EVENTS.chat_patch({...chat, forum: true}), group);
    assert.equal(await floating.count(), 0);
    assert.equal(await android.evaluate(peer => state.drafts[peer].text, group.id), 'Borrador de conversión en directo');
    passed.push({case: 'Actualización de Telegram convierte una ventana abierta en selector y guarda el borrador'});
    await android.evaluate(chat => openChat(chat.id, true, chat), alba);
    await android.evaluate(() => chooseFiles('camera'));
    const quality = android.getByRole('combobox', {name: 'Photo quality', exact: true});
    assert.equal(await quality.inputValue(), 'sd');
    await quality.selectOption('hd');
    await android.evaluate(() => saveDraft());
    assert(calls.some(row => row.name === 'draft' && row.peer === alba.id && row.photo_quality === 'hd'));
    await android.evaluate(() => render());
    assert.equal(await quality.inputValue(), 'hd');
    failMethod = 'send_files';
    await android.evaluate(() => send());
    assert.equal(await quality.inputValue(), 'hd');
    assert.equal(await android.evaluate(() => state.attachments.length), 1);
    await android.evaluate(() => send());
    assert.equal(calls.filter(row => row.name === 'send_files' && row.peer === alba.id).at(-1).photo_quality, 'hd');
    assert.equal(await android.locator('.photo-quality').count(), 0);
    await android.evaluate(() => chooseFiles('any'));
    assert.equal(await quality.inputValue(), 'original');
    await android.evaluate(() => send());
    assert.equal(calls.filter(row => row.name === 'send_files' && row.peer === alba.id).at(-1).photo_quality, 'original');
    passed.push({case: 'Cámara SD, selector HD retenido en borrador y reintento, Archivo conserva original'});
    await android.evaluate(async ({forum, topic}) => {
      await openForumTopic(forum, topic); await chooseFiles('gallery');
      addAttachments([{key: 'fixture-second.png', name: 'second.png', size: 120}]);
    }, {forum, topic: topics[0]});
    await quality.selectOption('hd');
    await android.evaluate(() => send());
    const forumFile = calls.filter(row => row.name === 'send_files' && row.peer === forum.id).at(-1);
    assert.deepEqual([forumFile.photo_quality, forumFile.topic_id, forumFile.thread_root], ['hd', 1, 1]);
    assert.equal(forumFile.keys.length, 2);
    passed.push({case: 'Álbum de fotos usa la calidad seleccionada dentro del tema explícito'});
    await android.evaluate(async chat => {await openChat(chat.id, true, chat); await chooseFiles('gallery');}, alba);
    await quality.selectOption('hd');
    await android.evaluate(() => saveDraft());
    await android.evaluate(chat => openChatWindow(chat), alba);
    const floatingPhoto = android.locator('.chatwin').filter({hasText: alba.name});
    const floatingQuality = floatingPhoto.getByRole('combobox', {name: 'Photo quality', exact: true});
    await floatingQuality.waitFor();
    assert.equal(await floatingQuality.inputValue(), 'hd');
    await floatingQuality.selectOption('original');
    await android.evaluate(() => saveWindowDraft(state.windows.find(win => win.peer === 17)));
    assert.equal(await android.locator('#attachments').getByRole('combobox', {name: 'Photo quality', exact: true}).inputValue(), 'original');
    await android.evaluate(() => sendFromWindow(state.windows.find(win => win.peer === 17)));
    assert.equal(calls.filter(row => row.name === 'window_send' && row.peer === alba.id).at(-1).photo_quality, 'original');
    passed.push({case: 'Ventana flotante comparte la calidad del borrador y la envía sin perderla'});
    await android.close();
    assert.deepEqual(faults, []);
    console.log(JSON.stringify({browser: await browser.version(), viewport: [390, 844], passed, pageErrors: faults}, null, 2));
  } finally {
    await browser.close(); server.closeAllConnections(); server.close();
  }
})().catch(error => { console.error(error); server.closeAllConnections(); server.close(); process.exitCode = 1; });
