// Browser contract tests; native geometry is exercised separately by Swift.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const checks = [];

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="app"></div><div id="sheet-layer" hidden></div><div id="call-layer" hidden></div><div id="group-call-layer" hidden></div>');
    await page.evaluate(() => {
      Object.assign(window, {PLATFORM: 'iOS', WINDOW_CHAT: null, state: {appearance: {}, settings: {}, stage: 'ready', locked: false,
        account: 'a', accountRevision: 1, view: 'chats'}, t: text => text, attempt: work => work(), calls: [], acted: [], fallback: 0});
      window.api = (name, params) => {
        calls.push({name, params});
        if (name === 'native_dialog_cancel') return window.rejectCancel ? Promise.reject(new Error('transport')) : Promise.resolve(true);
        return new Promise((resolve, reject) => { window.complete = resolve; window.fail = reject; });
      };
    });
    await page.addScriptTag({path: path.join(web, 'native_dialogs.js')});
    assert.equal(await page.evaluate(() => tgNativeDialogs.confirm('Pregunta', () => acted.push(1), 'danger', () => fallback++)), false);
    checks.push('disabled by default, no native request');
    await page.evaluate(() => {
      state.appearance.native_dialogs = true;
      tgNativeDialogs.confirm('Pregunta', () => acted.push(1), 'danger', () => fallback++);
      tgNativeDialogs.confirm('Pregunta', () => acted.push(2), 'danger', () => fallback++);
    });
    assert.equal(await page.evaluate(() => calls.length), 1);
    await page.evaluate(() => complete({handled: true, cancelled: false, index: 0}));
    assert.deepEqual(await page.evaluate(() => acted), [1]);
    checks.push('rapid duplicate tap opens one dialog and executes once');
    for (const change of ['account', 'backend-view', 'lock', 'preference']) {
      await page.evaluate(change => {
        state.account = 'a'; state.locked = false; state.view = 'chats'; state.appearance.native_dialogs = true;
        tgNativeDialogs.confirm('Pregunta', () => acted.push('stale'), 'danger', () => fallback++);
        if (change === 'account') { state.account = 'b'; state.accountRevision++; }
        if (change === 'backend-view') state.view = 'settings';
        if (change === 'lock') state.locked = true;
        if (change === 'preference') state.appearance.native_dialogs = false;
        tgNativeDialogs.sync(); complete({handled: true, cancelled: false, index: 0});
      }, change);
      assert.deepEqual(await page.evaluate(() => acted), [1]);
    }
    checks.push('account, view, lock and disabled preference reject late actions');
    await page.evaluate(() => {
      state.account = 'a'; state.locked = false; state.view = 'chats'; state.appearance.native_dialogs = true;
      tgNativeDialogs.menu('Acciones', [['Uno', () => acted.push('one')], ['Dos', () => acted.push('two'), 'danger']], null, () => fallback++);
      complete({handled: true, cancelled: false, index: 1});
    });
    assert.deepEqual(await page.evaluate(() => acted), [1, 'two']);
    checks.push('menu preserves item order and destructive role');
    await page.evaluate(() => {
      tgNativeDialogs.prompt('Nombre', {value: 'Viejo', maxlength: 12}, value => acted.push(value), () => fallback++);
      complete({handled: true, cancelled: false, index: 0, text: 'Nuevo'});
    });
    assert.deepEqual(await page.evaluate(() => acted), [1, 'two', 'Nuevo']);
    assert.equal(await page.evaluate(() => tgNativeDialogs.prompt('Número', {type: 'number'}, () => {}, () => {})), false);
    assert.equal(await page.evaluate(() => tgNativeDialogs.menu('Reacciones', [['Uno', () => {}]], [['👍', () => {}]], () => {})), false);
    checks.push('simple prompt accepts result; numeric fields and reactions keep web');
    await page.evaluate(() => {
      tgNativeDialogs.confirm('No disponible', () => acted.push('bad'), '', () => fallback++);
      complete({handled: false});
    });
    assert.equal(await page.evaluate(() => fallback), 1);
    await page.evaluate(() => {
      tgNativeDialogs.confirm('Cancelada', () => acted.push('bad'), '', () => fallback++);
      complete({handled: true, cancelled: true});
    });
    assert.equal(await page.evaluate(() => fallback), 1);
    checks.push('native unavailable falls back; cancellation never invokes fallback or action');

    for (const rejected of [false, true]) {
      const before = await page.evaluate(() => calls.length);
      await page.evaluate(rejected => {
        window.rejectCancel = rejected;
        tgNativeDialogs.prompt('Transporte', {}, () => acted.push('bad'), () => fallback++);
        fail(new Error('transport'));
      }, rejected);
      await page.waitForFunction(before => calls.length === before + 2, before);
      const result = await page.evaluate(before => ({
        calls: calls.slice(before).map(call => call.name),
        sameId: calls[before].params.request.id === calls[before + 1].params.request_id,
        fallback, acted,
      }), before);
      assert.deepEqual(result, {calls: ['native_dialog', 'native_dialog_cancel'], sameId: true,
        fallback: 1, acted: [1, 'two', 'Nuevo']});
    }
    checks.push('failed transport cancels its exact native request and never opens a second modal, even if cancellation fails');

    await page.evaluate(() => {
      document.getElementById('app').innerHTML = `<div class="bar" style="position:absolute;top:20px;left:0;display:flex">
        <button aria-label="Volver">&lt;</button><button class="title">Chat</button><button aria-label="Menú">⋯</button></div>
        <div id="composer-line" style="position:absolute;top:550px;display:flex"><button>+</button><button class="sticker-button">☺</button>
        <button class="format-button">Aa</button><button class="voice-button">Mic</button><button class="send-button">Enviar</button></div>
        <nav class="app-navigation" style="position:absolute;top:770px;display:flex"><button data-ui-icon="chats" aria-current="page">Chats</button><button data-ui-icon="settings">Ajustes</button></nav>`;
      const style = document.createElement('style'); style.textContent = 'button{width:60px;height:44px}.native-glass-control{opacity:0;pointer-events:none}'; document.head.append(style);
      window.fakeViewport = Object.assign(new EventTarget(), {width: 390, height: 844, offsetLeft: 0, offsetTop: 0});
      Object.defineProperty(window, 'visualViewport', {value: fakeViewport, configurable: true});
      window.glassMessages = []; window.unavailableWindow = () => false;
      window.webkit = {messageHandlers: {tgNativeGlass: {postMessage: payload => glassMessages.push(payload)}}};
      state.settings.advanced_features = {native_liquid_glass: true};
    });
    await page.addScriptTag({path: path.join(web, 'native_glass.js')});
    await page.evaluate(() => tgNativeGlass.refresh());
    const message = await page.evaluate(() => glassMessages.at(-1));
    assert.equal(message.controls.length, 7);
    assert.equal(message.controls.find(control => control.text === '+').symbol, 'paperclip');
    assert.equal(message.controls.find(control => control.text === 'Chats').selected, true);
    assert.equal(message.controls.find(control => control.text === 'Chats').showsText, true);
    assert(!message.controls.some(control => ['Mic', 'Enviar'].includes(control.text)));
    await page.evaluate(() => { const m = glassMessages.at(-1); tgNativeGlass.acknowledge(m.revision, m.controls.map(c => c.id), m.session); });
    assert.equal(await page.locator('.native-glass-control').count(), 7);
    assert.equal(await page.locator('.voice-button').getAttribute('aria-hidden'), null);
    checks.push('native fixed controls include composer and tabs, preserve hold/voice controls');
    await page.evaluate(() => { fakeViewport.offsetTop = 200; fakeViewport.height = 644; fakeViewport.dispatchEvent(new Event('scroll')); });
    await page.waitForFunction(() => glassMessages.at(-1).viewport?.offsetTop === 200);
    const moved = await page.evaluate(() => glassMessages.at(-1));
    assert.equal(moved.controls.length, 5);
    assert.equal(moved.controls.find(control => control.text === '+').y, 550);
    assert.equal(moved.viewport.height, 644);
    assert.equal(await page.locator('.bar .native-glass-control').count(), 0);
    checks.push('viewport scroll reports CSS coordinates and clipping without DOM movement');
    await page.evaluate(() => {
      Object.defineProperty(window, 'scrollY', {value: 200, configurable: true});
      fakeViewport.pageTop = 200;
      fakeViewport.dispatchEvent(new Event('scroll'));
    });
    await page.waitForFunction(() => glassMessages.at(-1).viewport?.offsetTop === 0);
    const webkit = await page.evaluate(() => glassMessages.at(-1));
    assert(webkit.controls.some(control => control.label === 'Volver'));
    assert(!webkit.controls.some(control => control.text === 'Chats'));
    checks.push('WebKit keyboard scroll is subtracted once using page origin minus document scroll');
    const idle = await page.evaluate(() => glassMessages.length);
    await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => glassMessages.length), idle);
    await page.evaluate(() => { const m = glassMessages.at(-1); tgNativeGlass.acknowledge(m.revision, [], m.session); });
    assert.equal(await page.locator('.native-glass-control').count(), 0);
    await page.evaluate(() => { state.settings.advanced_features.native_liquid_glass = false; tgNativeGlass.refresh(); });
    assert.equal(await page.evaluate(() => glassMessages.at(-1).enabled), false);
    assert.deepEqual(errors, []);
    checks.push('idle bridge deduplicates; transparency fallback and disabling restore accessible web controls');
    console.log(JSON.stringify({checks, passed: checks.length}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
