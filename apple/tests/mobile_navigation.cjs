// Integration checks against the actual phone page. No Telegram account needed.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = process.env.TELEGRAPH_WEB_ROOT || path.join(__dirname, '../src/tg_ascii_mobile/web');
const baseline = process.env.TELEGRAPH_BASELINE === '1';
const chat = {id: 17, name: 'Nora', kind: 'user'};
const draft = {text: 'Primera línea\nSegunda línea\nTercera línea', formats: [], custom: [], files: [], reply: null};
const messages = Array.from({length: 80}, (_, i) => ({id: i + 1, text: 'Mensaje ' + i,
  sender: 'Nora', sender_id: 17, date: 1770000000 + i, time: '10:30'}));
const result = {layout: [], gestures: [], nativeGlass: []};
const preferences = {font_size: 16, bubbles: true, reduce_animations: true, advanced_features: {native_liquid_glass: false}};
let appearance = {};
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname === '/events') {
    res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;
  }
  if (url.pathname.startsWith('/api/')) {
    let body = ''; for await (const chunk of req) body += chunk;
    const name = url.pathname.slice(5); let value = null;
    if (name === 'state') value = {account: 'test', stage: 'ready', language: 'es', connection: 'online',
      accounts: [], appearance, settings: preferences};
    else if (name === 'chats') value = [chat];
    else if (name === 'open') value = {chat, messages, draft, outbox: {items: []}};
    else if (name === 'older') value = {messages: [], more: false};
    else if (['folders', 'pinned', 'contacts', 'recent_searches'].includes(name)) value = [];
    else if (name === 'strings') value = {};
    else if (name === 'settings') {
      const args = JSON.parse(body || '{}').values || {};
      if (args.advanced_features) args.advanced_features = {...preferences.advanced_features, ...args.advanced_features};
      Object.assign(preferences, args); value = preferences;
    } else if (name === 'appearance') { Object.assign(appearance, JSON.parse(body || '{}').values || {}); value = appearance; }
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({ok: true, result: value})); return;
  }
  const file = path.join(web, url.pathname === '/' ? 'index.html' : url.pathname);
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {'Content-Type': {'.js': 'text/javascript', '.html': 'text/html', '.css': 'text/css'}[path.extname(file)] || 'text/plain'});
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  if (process.env.TELEGRAPH_FIXTURE_ONLY === '1') { console.log('fixture-port=' + server.address().port); return; }
  const browser = await chromium.launch({executablePath: process.env.CHROME, headless: true});
  try {
    for (const size of [{width: 390, height: 844}, {width: 820, height: 1180}]) {
      const page = await browser.newPage({viewport: size, isMobile: true, hasTouch: true});
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      await page.goto('http://127.0.0.1:' + server.address().port + '/?platform=iOS&t=fixture');
      await page.waitForFunction(() => state.started && state.chats.length);
      const mounted = await page.evaluate(async chat => {
        await openChat(chat.id, true, chat);
        const measure = () => ({composer: document.querySelector('.composer').getBoundingClientRect().height,
          text: document.getElementById('field').value, messages: document.querySelectorAll('#messages .msg').length,
          scroll: document.getElementById('scroll').scrollTop});
        const initial = measure();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        return {initial, settled: measure()};
      }, chat);
      result.layout.push({width: size.width, ...mounted});
      if (!baseline) {
        assert.equal(mounted.initial.text, draft.text, 'Draft is restored before the new screen is exposed');
        assert.equal(mounted.initial.messages, 80, 'Initial mounted history is populated');
        assert.equal(mounted.initial.composer, mounted.settled.composer, 'No deferred composer height correction');
        assert.equal(mounted.initial.scroll, mounted.settled.scroll, 'No deferred history jump');
      }
      await page.close(); assert.deepEqual(errors, []);
    }
    const page = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
    await page.goto('http://127.0.0.1:' + server.address().port + '/?platform=iOS&t=fixture');
    await page.waitForFunction(() => state.started && state.chats.length);
    const swipe = async ({x = 96, dx = 90, dy = 0, selector = '#settings-scroll', cancel = false, changeAccount = false}) => {
      await page.evaluate(() => { go('settings'); });
      return page.evaluate(async options => {
        const target = document.querySelector(options.selector);
        const touch = (x, y) => new Touch({identifier: 7, target, clientX: x, clientY: y});
        const fire = (type, point, ended = false) => target.dispatchEvent(new TouchEvent(type, {bubbles: true,
          cancelable: true, touches: ended ? [] : [point], changedTouches: [point]}));
        fire('touchstart', touch(options.x, 270));
        fire('touchmove', touch(options.x + options.dx / 2, 270 + options.dy / 2));
        if (options.changeAccount) state.accountRevision++;
        fire(options.cancel ? 'touchcancel' : 'touchend', touch(options.x + options.dx, 270 + options.dy), true);
        await new Promise(resolve => setTimeout(resolve, 20));
        return state.view;
      }, {x, dx, dy, selector, cancel, changeAccount});
    };
    const cases = [
      ['Back from a comfortable 96 px inset', {}, 'chats'],
      ['Quick 44 px flick', {dx: 44}, 'chats'],
      ['Vertical scrolling', {dx: 20, dy: 100}, 'settings'],
      ['Outside leading area', {x: 220}, 'settings'],
      ['System cancellation', {cancel: true}, 'settings'],
      ['Account changed during gesture', {changeAccount: true}, 'settings'],
      ['Left swipe', {dx: -90}, 'settings'],
    ];
    for (const [label, options, expected] of cases) {
      const actual = await swipe(options); result.gestures.push({label, actual});
      if (!baseline) assert.equal(actual, expected, label);
    }
    // An actual range input retains its horizontal gesture.
    await page.evaluate(() => {
      const slider = document.createElement('input'); slider.type = 'range'; slider.id = 'gesture-slider';
      document.getElementById('settings-scroll').append(slider);
    });
    const control = await page.evaluate(() => {
      const target = document.getElementById('gesture-slider');
      for (const [type, x] of [['touchstart', 96], ['touchmove', 140], ['touchend', 186]]) {
        const point = new Touch({identifier: 8, target, clientX: x, clientY: 270});
        target.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true,
          touches: type === 'touchend' ? [] : [point], changedTouches: [point]}));
      }
      return state.view;
    });
    if (!baseline) assert.equal(control, 'settings');
    result.gestures.push({label: 'Range input retains gesture', actual: control});
    await page.close();
    if (!baseline) {
      const glass = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
      await glass.addInitScript(() => {
        window.glassMessages = []; window.glassAllowed = true;
        window.webkit = {messageHandlers: {tgNativeGlass: {postMessage(payload) {
          window.glassMessages.push(payload);
          queueMicrotask(() => window.tgNativeGlass.acknowledge(payload.revision,
            window.glassAllowed && payload.enabled ? payload.controls.map(control => control.id) : [], payload.session));
        }}}};
      });
      await glass.goto('http://127.0.0.1:' + server.address().port + '/?platform=iOS&t=fixture');
      await glass.waitForFunction(() => state.started && state.chats.length);
      assert.equal(await glass.locator('.native-glass-control').count(), 0, 'Off by default');
      await glass.evaluate(() => {
        state.settings.advanced_features = {native_liquid_glass: true};
        window.tgNativeGlass.refresh();
      });
      await glass.waitForFunction(() => document.querySelector('.native-glass-control'));
      const mirrored = await glass.evaluate(() => ({packet: glassMessages.at(-1),
        hidden: [...document.querySelectorAll('.native-glass-control')].every(node => node.getAttribute('aria-hidden') === 'true' && node.tabIndex === -1)}));
      assert(mirrored.hidden, 'Native acknowledgement transfers accessibility exactly once');
      assert(mirrored.packet.controls.every(control => control.label && control.width >= 28));
      const stable = await glass.evaluate(() => glassMessages.length);
      await glass.waitForTimeout(300);
      assert.equal(await glass.evaluate(() => glassMessages.length), stable, 'No idle refresh or resize-observer loop');
      await glass.evaluate(() => {
        const packet = glassMessages.at(-1), id = packet.controls.at(-1).id;
        window.tgNativeGlass.activate(id, packet.revision - 1, packet.session);
        window.tgNativeGlass.activate(id, packet.revision, "0".repeat(32));
      });
      assert(await glass.locator('#sheet-layer').evaluate(node => node.hidden), 'Stale native action rejected');
      await glass.evaluate(() => {
        const packet = glassMessages.at(-1), id = packet.controls.at(-1).id;
        window.tgNativeGlass.activate(id, packet.revision, packet.session);
      });
      await glass.waitForFunction(() => !document.getElementById('sheet-layer').hidden);
      await glass.waitForFunction(() => !document.querySelector('.native-glass-control'));
      result.nativeGlass.push('Default off, acknowledged accessibility, idle stability, stale actions and modal handoff');
      await glass.evaluate(() => { closeSheet(true); window.glassAllowed = false; window.tgNativeGlass.environment(true); });
      await glass.waitForTimeout(80);
      assert.equal(await glass.locator('.native-glass-control').count(), 0, 'Reduce Transparency restores web controls');
      await glass.evaluate(() => { window.glassAllowed = true; window.tgNativeGlass.environment(false); });
      await glass.waitForFunction(() => document.querySelector('.native-glass-control'));
      await glass.evaluate(() => { state.settings.advanced_features.native_liquid_glass = false; window.tgNativeGlass.refresh(); });
      await glass.waitForFunction(() => !document.querySelector('.native-glass-control'));
      assert(await glass.locator('#app .bar button').evaluateAll(nodes => nodes.every(node => node.getAttribute('aria-hidden') !== 'true')));
      result.nativeGlass.push('System transparency fallback and disabling restore original web accessibility');
      await glass.close();
    }
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); server.closeAllConnections(); server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
