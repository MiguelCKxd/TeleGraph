// Real WebView script; transport errors, account races and SSE packets are controlled.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const snapshot = {account: 'a', stage: 'ready', language: 'en', rtl: false, locked: false,
  connection: 'online', accounts: [], appearance: {}, lock: {}, settings: {font_size: 12}};
const requests = [];
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/events') {
    res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;
  }
  if (pathname.startsWith('/api/')) {
    const name = pathname.slice(5);
    requests.push(name);
    const result = name === 'state' ? snapshot : name === 'strings' ? {} :
      name === 'premium_settings' ? {premium: false, name_colors: [], profile_colors: []} :
      ['chats', 'folders', 'windows', 'outbox', 'calls', 'languages', 'recent_searches'].includes(name) ? [] : null;
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({ok: true, result})); return;
  }
  const file = path.join(web, pathname === '/' ? 'index.html' : pathname);
  fs.readFile(file, (error, data) => {
    if (error) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const errors = []; page.on('pageerror', error => errors.push(error.stack));
  const checks = [];
  try {
    await page.addInitScript(() => {
      const NativeObserver = window.IntersectionObserver;
      window.qaImageObservers = [];
      window.IntersectionObserver = class extends NativeObserver {
        constructor(callback, options) {super(callback, options); this.targets = new Set(); window.qaImageObservers.push(this);}
        observe(target) {this.targets.add(target); super.observe(target);}
        unobserve(target) {this.targets.delete(target); super.unobserve(target);}
        disconnect() {this.targets.clear(); super.disconnect();}
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=fixture`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => {source.close();});
    requests.length = 0;
    await page.evaluate(() => {state.settingsTab = 'appearance'; go('settings');});
    const settingsSearch = page.getByRole('searchbox', {name: 'Buscar en ajustes', exact: true});
    await settingsSearch.fill('Liquid');
    await settingsSearch.fill('Emoji status');
    assert.equal(requests.filter(name => ['premium_settings', 'my_profile', 'cache_size'].includes(name)).length, 0);
    await page.getByRole('button', {name: 'Emoji status', exact: true}).click();
    await page.getByRole('button', {name: 'Choose', exact: true}).waitFor();
    assert.equal(requests.filter(name => name === 'premium_settings').length, 1);
    checks.push('settings search indexes remote options without fetching them; opening result fetches once');
    const staleProfile = await page.evaluate(async () => {
      const original = window.fetch;
      let finish;
      const pending = new Promise(resolve => {finish = resolve;});
      window.fetch = async url => url === '/api/my_profile' ? pending : original(url);
      state.me = null;
      try {
        myProfileSection();
        state.accountRevision++;
        state.account = 'b';
        finish({ok: true, json: async () => ({ok: true, result: {first: 'Old account'}})});
        await new Promise(resolve => setTimeout(resolve, 0));
        return state.me;
      } finally {window.fetch = original;}
    });
    assert.equal(staleProfile, null);
    checks.push('late profile response cannot populate another account');
    await page.evaluate(() => {state.settingsQuery = ''; state.view = 'chats'; render();});
    const lateLists = await page.evaluate(async () => {
      const original = window.fetch, output = {};
      for (const route of ['archived', 'pinned', 'scheduled']) {
        let finish;
        window.fetch = async url => url === '/api/' + route
          ? new Promise(resolve => {finish = resolve;}) : original(url);
        state.account = 'a'; state.view = route === 'archived' ? 'archived' : 'chats';
        state.archived = null; closeSheet(true);
        if (route === 'archived') EVENTS.chats([]);
        else if (route === 'pinned') pinnedList({id: 99});
        else scheduledList({id: 99});
        await Promise.resolve();
        state.account = 'b'; state.accountRevision++; state.archived = [];
        finish({ok: true, json: async () => ({ok: true, result: [{id: 88, name: 'Account A', text: 'Account A', scheduled: 1}]})});
        await new Promise(resolve => setTimeout(resolve, 0));
        output[route] = route === 'archived' ? state.archived.length : !document.getElementById('sheet-layer').hidden;
        closeSheet(true);
      }
      window.fetch = original;
      state.view = 'chats'; render();
      return output;
    });
    assert.deepEqual(lateLists, {archived: 0, pinned: false, scheduled: false});
    checks.push('archived, pinned and scheduled replies from a previous account are discarded');
    const globalReplies = await page.evaluate(async () => {
      const original = window.fetch, output = {};
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      for (const changeAccount of [false, true]) {
        let finish;
        window.fetch = async url => url === '/api/search_global'
          ? new Promise(resolve => {finish = resolve;}) : original(url);
        state.account = 'a'; state.view = state.list = 'chats'; state.search = 'shared'; state.global = null;
        state.chats = []; render(); drawChatList();
        await new Promise(resolve => setTimeout(resolve, 650));
        if (changeAccount) {
          state.account = 'b'; state.accountRevision++;
          state.global = {query: 'shared', data: null};
        }
        drawChatList();
        finish({ok: true, json: async () => ({ok: true, result: {chats: [{id: 999, name: 'Original account result'}], messages: []}})});
        await tick();
        output[changeAccount ? 'otherAccount' : 'redrawn'] = {
          cached: !!state.global.data,
          visible: document.getElementById('global').textContent.includes('Original account result')};
      }
      window.fetch = original; state.search = ''; state.global = null; render();
      return output;
    });
    assert.deepEqual(globalReplies, {redrawn: {cached: true, visible: true}, otherAccount: {cached: false, visible: false}});
    checks.push('global search survives a list redraw but cannot populate another account');
    const detachedImages = await page.evaluate(async () => {
      const pane = h('div', {class: 'scroll', style: 'height:40px;overflow:auto'}, h('div', {style: 'height:10000px'}));
      const pictures = Array.from({length: 40}, () => lazySrc(h('img', {width: 40, height: 40}), '/unread-preview'));
      pane.append(...pictures); document.body.append(pane); watchImagesNow();
      await new Promise(resolve => requestAnimationFrame(resolve));
      pane.remove();
      await new Promise(resolve => requestAnimationFrame(resolve));
      const count = () => qaImageObservers.reduce((sum, observer) => sum + [...observer.targets].filter(target => pictures.includes(target)).length, 0);
      const result = {observed: count(),
        roots: [...imageObservers.keys()].filter(root => root && !root.isConnected).length};
      document.body.append(pane); watchImages(pane); watchImagesNow();
      await new Promise(resolve => requestAnimationFrame(resolve));
      result.revived = count();
      pane.remove();
      return result;
    });
    assert.deepEqual(detachedImages, {observed: 0, roots: 0, revived: 40});
    checks.push('removed image panes release all 40 pending observations and roots; reused rows resume loading');
    const empty = await page.evaluate(() => {
      const box = document.createElement('div'); box.id = 'attachments'; document.body.append(box);
      const node = document.createElement('div'); node.innerHTML = '<div class="wincompose"><div class="context"></div></div>';
      document.body.append(node);
      state.attachments = []; drawAttachments();
      drawWindowContext({node, peer: 42, reply: null, draft: {files: []}});
      const result = [box.textContent, node.querySelector('.context').textContent];
      state.attachments = [{key: 'notes.txt', name: 'notes.txt', size: 8}]; drawAttachments();
      drawWindowContext({node, peer: 42, reply: null, draft: {files: state.attachments}});
      result.push(box.textContent, node.querySelector('.context').textContent);
      state.attachments = []; box.remove(); node.remove();
      return result;
    });
    assert.deepEqual(empty.slice(0, 2), ['', '']);
    assert(empty.slice(2).every(text => text.includes('notes.txt') && !text.includes('null')));
    checks.push('empty and non-photo attachments have no null row');
    for (const method of ['react', 'window_send', 'send_checklist', 'send_article', 'save_to_saved', 'bot_button', 'forum_create', 'forum_manage', 'contact_photo', 'suggest_birthday', 'reset_settings']) {
      const count = await page.evaluate(async method => {
        const original = window.fetch;
        let requests = 0;
        window.fetch = async () => {
          requests++;
          if (requests === 1) throw new TypeError('Answer lost after operation committed');
          return {ok: true, json: async () => ({ok: true, result: true})};
        };
        try {await api(method, {peer: 42});} catch {} finally {window.fetch = original;}
        return requests;
      }, method);
      assert.equal(count, 1, `${method}: a lost answer must not repeat a mutation`);
      checks.push('no duplicate ' + method);
    }
    const read = await page.evaluate(async () => {
      const original = window.fetch; let count = 0;
      window.fetch = async () => {
        if (++count === 1) throw new TypeError('Local server waking');
        return {ok: true, json: async () => ({ok: true, result: [42]})};
      };
      try {return {result: await api('chats'), count};} finally {window.fetch = original;}
    });
    assert.deepEqual(read, {result: [42], count: 2}); checks.push('read retries once');
    const switched = await page.evaluate(async () => {
      const original = window.fetch; let count = 0;
      window.fetch = async () => {
        count++; state.accountRevision++; state.account = 'b';
        throw new TypeError('Account changed during outage');
      };
      try {await api('chats');} catch {} finally {window.fetch = original;}
      return count;
    });
    assert.equal(switched, 1); checks.push('read cannot retry against another account');
    await page.evaluate(() => {
      state.chats = [{id: 2, name: 'Account B'}];
      source.onmessage({data: JSON.stringify({type: 'chats', account: 'a', data: [{id: 1, name: 'Account A'}]})});
    });
    assert.equal(await page.evaluate(() => state.chats[0].id), 2); checks.push('old SSE account discarded');
    const sync = await page.evaluate(async snapshot => {
      const original = window.fetch;
      let finish, count = 0;
      const entered = new Promise(resolve => {finish = resolve;});
      window.fetch = async url => {
        if (url === '/api/state') {
          count++; await entered;
          return {ok: true, json: async () => ({ok: true, result: snapshot})};
        }
        return original(url);
      };
      try {
        const first = resync(), second = resync();
        state.account = 'c'; state.accountRevision++;
        finish(); await Promise.all([first, second]);
        return {count, account: state.account};
      } finally {window.fetch = original;}
    }, snapshot);
    assert.deepEqual(sync, {count: 1, account: 'c'}); checks.push('resync coalesces and rejects stale snapshot');
    const unlock = await page.evaluate(async snapshot => {
      const original = window.fetch;
      let finish, count = 0;
      const entered = new Promise(resolve => {finish = resolve;});
      state.account = 'a'; state.locked = true;
      window.fetch = async (url, options) => {
        if (url === '/api/state') {
          const first = ++count === 1;
          if (first) await entered;
          return {ok: true, json: async () => ({ok: true, result: {...snapshot, locked: first}})};
        }
        return original(url, options);
      };
      try {
        const pending = resync();
        EVENTS.lock(false);
        finish(); await pending;
        return {count, locked: state.locked};
      } finally {window.fetch = original;}
    }, snapshot);
    assert.deepEqual(unlock, {count: 2, locked: false}); checks.push('unlock during resync starts a fresh snapshot');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({checks, browser: browser.version(), pageErrors: errors}, null, 2));
  } finally {await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
