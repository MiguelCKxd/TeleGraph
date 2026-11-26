// Delay real UI helper responses across account changes, using synthetic data only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const initial = {account: 'a', stage: 'ready', language: 'es', locked: false, connection: 'online',
  accounts: [], chats: [], appearance: {}, lock: {}, settings: {font_size: 12}};
const server = http.createServer((req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    const result = route === '/api/state' ? initial : route === '/api/strings' ? {} : [];
    res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify({ok: true, result})); return;
  }
  const file = route === '/app.js' && process.env.APP_JS_OVERRIDE ? process.env.APP_JS_OVERRIDE : path.join(web, route === '/' ? 'index.html' : route);
  fs.readFile(file, (error, data) => {
    res.writeHead(error ? 404 : 200, {'Content-Type': route.endsWith('.js') ? 'text/javascript' : route.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(error ? '' : data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=qa&platform=iOS`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => {source.close();});
    const results = await page.evaluate(async () => {
      const originalApi = api, originalPicker = pickImage;
      const results = {};
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      const reset = () => {
        closeSheet(true); state.account = 'a'; state.accountRevision++; state.locked = false;
        state.view = 'chats'; state.appearance = {}; state.settings = {font_size: 12}; state.chats = []; state.open = null;
        render();
      };
      const switchAccount = () => {state.account = 'b'; state.accountRevision++; state.appearance = {marker: 'b'}; state.settings = {font_size: 12, marker: 'b'};};
      try {
        reset();
        let first;
        api = method => method === 'devices' ? new Promise(resolve => {first = resolve;}) : Promise.resolve([]);
        document.getElementById('app').replaceChildren(...devicesView());
        switchAccount();
        api = method => Promise.resolve(method === 'devices' ? {sessions: [{current: true, device: 'SESSION_B'}], ttl_days: 30} : []);
        document.getElementById('app').replaceChildren(...devicesView());
        await tick();
        first({sessions: [{current: true, device: 'PRIVATE_SESSION_A', ip: '192.0.2.1'}], ttl_days: 30});
        await tick();
        const sessions = document.getElementById('devicelist').textContent;
        results.device_sessions_stay_with_owner = sessions.includes('SESSION_B') && !sessions.includes('PRIVATE_SESSION_A');

        for (const kind of ['background', 'logo']) {
          for (const stage of ['picker', 'response']) {
            reset(); let resolvePicker, resolveSave, saveParams; const calls = [];
            pickImage = () => stage === 'picker' ? new Promise(resolve => {resolvePicker = resolve;}) : Promise.resolve('qa-key');
            api = (name, params) => {
              calls.push(name);
              if (name === 'set_background' || name === 'set_logo_photo') {
                saveParams = params; return new Promise(resolve => {resolveSave = resolve;});
              }
              return Promise.resolve([]);
            };
            let holder;
            let operation;
            if (kind === 'background') operation = chooseBackground('interface');
            else {
              state.logoCatalogue = {variants: [['qa', 'QA']], colors: ['default']};
              holder = h('div', {}, logoSettings()); document.body.append(holder);
              [...holder.querySelectorAll('button')].find(button => button.textContent === 'Image').click();
            }
            await tick(); switchAccount();
            if (stage === 'picker') resolvePicker('qa-key'); else resolveSave({marker: 'a'});
            await tick();
            if (stage === 'picker' && resolveSave) resolveSave({marker: 'a'});
            await operation; await tick();
            results[`${kind}_${stage}_cannot_change_other_account`] = stage === 'picker'
              ? !calls.includes(kind === 'background' ? 'set_background' : 'set_logo_photo') && calls.includes('discard_files')
              : state.appearance.marker === 'b' && saveParams.account === 'a';
            holder?.remove();
          }
        }

        reset(); let resolveNotice;
        api = method => method === 'save_notify_preferences' ? new Promise(resolve => {resolveNotice = resolve;}) : Promise.resolve([]);
        notificationForm('Synthetic chat', 7, {mute_until: 0}, 'a', []);
        const select = document.querySelector('#sheet-layer select'); select.value = '3600';
        document.querySelector('#sheet-layer .actions .primary').click();
        await tick(); switchAccount(); state.chats = [{id: 7, muted: false, name: 'Chat B'}];
        state.open = {peer: 7, chat: state.chats[0]}; resolveNotice(true); await tick();
        results.notification_response_cannot_mute_same_peer_in_other_account = !state.chats[0].muted;

        reset(); let resolveName;
        api = method => method === 'settings' ? new Promise(resolve => {resolveName = resolve;}) : Promise.resolve([]);
        editDisplayName();
        document.querySelector('#sheet-layer input').value = 'Name A';
        document.querySelector('#sheet-layer .actions .primary').click();
        await tick(); switchAccount(); resolveName({font_size: 12, marker: 'a'}); await tick();
        results.display_name_response_cannot_replace_other_account_settings = state.settings.marker === 'b';
      } finally {api = originalApi; pickImage = originalPicker; closeSheet(true);}
      return results;
    });
    console.log(JSON.stringify({checks: results, errors}, null, 2));
    assert.deepEqual(errors, []);
    if (!process.env.REPRODUCE_OLD) assert.equal(Object.values(results).every(Boolean), true);
  } finally {if (browser) await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
