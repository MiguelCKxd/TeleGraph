// Header connection indicator: real web assets, synthetic state, no accounts or network service.
// Contract (3.4.1 regression, 27 Nov): online headers end at their usable edge (no reserved,
// invisible control), and going offline/reconnecting never moves the trailing controls.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const repo = path.join(__dirname, '..');
const web = path.join(repo, 'src/tg_ascii_mobile/web');
const BASE = '6127d82434f15f124dd4237a166cd8a90de246de';  // 3.4.0 (2): reference geometry online
const snapshot = {account:'qa', stage:'ready', language:'es', rtl:false, locked:false, connection:'online',
  accounts:[], appearance:{presentation:{}}, lock:{}, settings:{font_size:12, bubbles:true, reduce_animations:true}};

function serve(read) {
  const server = http.createServer((req, res) => {
    const route = new URL(req.url, 'http://127.0.0.1').pathname;
    if (route === '/events') {res.writeHead(200, {'Content-Type':'text/event-stream'}); res.write(': ready\n\n'); return;}
    if (route.startsWith('/api/')) {
      const result = route === '/api/state' ? snapshot : route === '/api/strings' ? {} : [];
      res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify({ok:true, result})); return;
    }
    const name = route === '/' ? 'index.html' : route.slice(1);
    const data = /^[\w.-]+$/.test(name) ? read(name) : null;
    if (!data) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {'Content-Type':name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(data);
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}
const fromTree = name => { try { return fs.readFileSync(path.join(web, name)); } catch { return null; } };
const fromBase = name => { try { return cp.execFileSync('git', ['show', `${BASE}:src/tg_ascii_mobile/web/${name}`],
  {cwd:repo, stdio:['ignore', 'pipe', 'ignore']}); } catch { return null; } };

const VIEWS = ['chats', 'chat', 'settings'];
const VARIANTS = {
  phone: {width:390},
  narrow: {width:320},
  rtl: {width:390, rtl:true},
  large: {width:390, font:22},
  buttons: {width:390, buttonHeight:64},
  safe: {width:390, safeLeft:30, safeRight:30},
  headerLarge: {width:390, headerFont:27},
  headerSmall: {width:390, font:22, headerFont:10},
  headerHuge: {width:320, headerFont:48},   // galeria34, 27 Nov: alert left the bar before 295072f's follow-up
};

async function open(browser, server, variant, view, showOnline) {
  const page = await browser.newPage({viewport:{width:variant.width, height:844}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/?t=fixture&platform=iOS`);
  await page.waitForFunction(() => state.started);
  await page.evaluate(({variant, view, showOnline}) => {
    source.close();
    const root = document.documentElement.style;
    if (variant.safeLeft) root.setProperty('--safe-left', variant.safeLeft + 'px');
    if (variant.safeRight) root.setProperty('--safe-right', variant.safeRight + 'px');
    state.rtl = !!variant.rtl;
    if (variant.font) state.settings.font_size = variant.font;
    state.appearance.presentation = {show_online:showOnline, ...(variant.buttonHeight ? {button_height:variant.buttonHeight} : {}),
      ...(variant.headerFont ? {header_font_size:variant.headerFont} : {})};
    state.view = view; state.settingsTab = 'notifications';
    state.open = view === 'chat' ? {peer:1, chat:{id:1, name:'Conversación de prueba', kind:'user'},
      messages:[{id:1, text:'Mensaje de prueba', sender:'QA', sender_id:1, date:1795680000, kind:'text', out:false}], done:true} : null;
    applySettings(); render();
  }, {variant, view, showOnline});
  return {page, errors};
}

const measure = page => page.evaluate(() => {
  const bar = document.querySelector('#app > .bar');
  const box = node => { if (!node || !node.getClientRects().length) return null; const r = node.getBoundingClientRect();
    return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height}; };
  const style = getComputedStyle(bar);
  const items = [...bar.children].filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
  const alert = document.getElementById('connection-alert');
  return {
    bar:{left:bar.getBoundingClientRect().left + parseFloat(style.paddingLeft) + parseFloat(style.borderLeftWidth),
         right:bar.getBoundingClientRect().right - parseFloat(style.paddingRight) - parseFloat(style.borderRightWidth)},
    controls:[...bar.querySelectorAll(':scope > button:not(.title):not(.peer-control)')].map(box),
    status:box(bar.querySelector(':scope > #status')), title:box(bar.querySelector(':scope > .title')),
    titleText:(() => { const title = bar.querySelector(':scope > .title'); if (!title) return null; const r = title.getBoundingClientRect(), c = getComputedStyle(title);
      return {left:r.left + parseFloat(c.paddingLeft), right:r.right - parseFloat(c.paddingRight)}; })(),
    hasClass:bar.classList.contains('connection-in-title'), barHeight:bar.getBoundingClientRect().height,
    barBox:{top:bar.getBoundingClientRect().top, bottom:bar.getBoundingClientRect().bottom},
    controlHeight:Math.max(0, ...[...bar.querySelectorAll(':scope > button:not(.title):not(.peer-control)')].map(node => node.getBoundingClientRect().height)),
    first:box(items[0]), last:box(items[items.length - 1]),
    alert:alert.hidden ? null : box(alert), alertInBar:bar.contains(alert), alertName:alert.getAttribute('aria-label'),
    alerts:document.querySelectorAll('#connection-alert').length, cells:document.querySelectorAll('.connection-cell').length,
    slots:document.querySelectorAll('.connection-slot').length, rtl:document.documentElement.dir === 'rtl',
  };
});
const setConnection = (page, value) => page.evaluate(value => { state.connection = value; updateStatus(); }, value);
const near = (a, b, what) => assert.ok(Math.abs(a - b) <= 0.5, `${what}: ${a} vs ${b}`);
const same = (a, b, what) => { assert.equal(!!a, !!b, what + ' presence');
  if (a) for (const key of ['left', 'right', 'top', 'width', 'height']) near(a[key], b[key], `${what}.${key}`); };
const overlaps = (a, b) => a && b && a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;

{
  const css = fs.readFileSync(path.join(web, 'app.css'), 'utf8');
  // The IPA's minimum is iOS 15.0: no :has() (Safari 15.4) or @property (16.4) in these rules, so
  // every engine resolves the same font-independent --bar-control.
  const block = css.slice(css.lastIndexOf('/*', css.indexOf('One connection cell, no reserved slot')), css.indexOf('body > #connection-alert'))
    .replace(/\/\*[\s\S]*?\*\//g, '');  // rules only, not their comments
  assert.ok(block.length > 200 && !block.includes(':has(') && !block.includes('@property'), 'connection rules avoid :has()/@property');
  assert.ok(!/--bar-control:[^;]*em\b/.test(block), '--bar-control is font-independent');
}
(async () => {
  const tree = await serve(fromTree), base = await serve(fromBase);
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME || undefined});
  const rows = [], errors = [];
  try {
    for (const [mode, server] of [['tree', tree]])
    for (const [name, variant] of Object.entries(VARIANTS)) for (const view of VIEWS) for (const showOnline of [true, false]) {
      const {page, errors: pageErrors} = await open(browser, server, variant, view, showOnline);
      try {
        const online = await measure(page);
        const where = `${mode}/${name}/${view}/status:${showOnline}`;
        // 1. Online: nothing invisible after the trailing item; it reaches the usable edge.
        assert.equal(online.alert, null, where + ' alert hidden online');
        assert.equal(online.cells + online.slots, 0, where + ' no reserved cell online');
        // The trailing item is the last one in DOM order; RTL draws it on the left.
        const edge = online.rtl ? online.last.left : online.last.right;
        near(edge, online.rtl ? online.bar.left : online.bar.right, where + ' trailing item at usable edge');
        // 2. Offline and reconnecting: same controls, same status box; alert visible, 44px+, no overlap.
        for (const state of ['offline', 'reconnecting', 'offline']) {
          await setConnection(page, state);
          const now = await measure(page);
          assert.equal(now.controls.length, online.controls.length, where + ' controls kept');
          now.controls.forEach((control, index) => same(control, online.controls[index], `${where} ${state} control ${index}`));
          if (online.status) same(now.status, online.status, `${where} ${state} status box`);
          same(now.title, online.title, `${where} ${state} title box`);
          assert.ok(now.alert && now.alertInBar, where + ' alert visible in the header');
          assert.ok(now.alert.width >= 44 && now.alert.height >= 44, where + ' alert keeps 44px');
          assert.ok(now.controls.every(control => !overlaps(control, now.alert)), where + ' alert overlaps no control');
          assert.ok(now.alertName && now.alertName.includes('·'), where + ' alert has an accessible name');
          near(now.barHeight, online.barHeight, where + ' bar height');
          // Same size as the bar's own controls, inside the bar, and the title keeps room for its text.
          if (now.controlHeight) near(now.alert.height, now.controlHeight, where + ' alert matches the bar controls');
          assert.ok(now.alert.top >= now.barBox.top - 0.5 && now.alert.bottom <= now.barBox.bottom + 0.5, where + ' alert inside the bar');
          if (now.titleText) assert.ok(now.titleText.right - now.titleText.left >= 40, where + ' title keeps room for text');
          if (!online.status || !showOnline) {
            // No visible status: the alert sits in the title's end padding, never over its text.
            assert.equal(now.hasClass, true, where + ' explicit title state class');
            assert.ok(now.rtl ? now.alert.right <= now.titleText.left + 0.5 : now.alert.left >= now.titleText.right - 0.5,
              where + ' alert clear of title text');
          }
          assert.equal(now.alerts, 1, where + ' one alert');
          assert.ok(now.cells <= 1 && now.slots === 0, where + ' at most one cell');
          rows.push({where, state, alertWidth:now.alert.width, controlWidth:Math.min(...now.controls.map(c => c.width)), titleDelta:online.title && now.title ? +(now.title.width - online.title.width).toFixed(2) : null});
        }
        // 3. Repeated renders keep a single alert and cell; back online leaves nothing behind.
        for (let i = 0; i < 4; i++) await page.evaluate(() => render());
        const repeated = await measure(page);
        assert.equal(repeated.alerts, 1); assert.ok(repeated.cells <= 1);
        await setConnection(page, 'online');
        const back = await measure(page);
        assert.equal(back.cells + back.slots, 0, where + ' nothing left online');
        assert.equal(back.hasClass, false, where + ' state class removed online');
        back.controls.forEach((control, index) => same(control, online.controls[index], `${where} back online control ${index}`));
        // 4. Locked: no visible alert.
        await setConnection(page, 'offline');
        await page.evaluate(() => { state.locked = true; updateConnectionIndicator(); });
        assert.equal((await measure(page)).alert, null, where + ' locked hides alert');
        errors.push(...pageErrors.map(error => `${where}: ${error}`));
      } finally { await page.close(); }
    }
    // 5. Online alignment equals 3.4 for the cases the regression was measured in.
    const reference = [];
    for (const view of VIEWS) {
      const now = await open(browser, tree, VARIANTS.phone, view, true), old = await open(browser, base, VARIANTS.phone, view, true);
      try {
        const [a, b] = [await measure(now.page), await measure(old.page)];
        near(a.last.right, b.last.right, `${view} trailing item matches 3.4`);
        if (a.status && b.status) near(a.status.right, b.status.right, `${view} status matches 3.4`);
        if (a.title && b.title) near(a.title.width, b.title.width, `${view} title width matches 3.4`);
        reference.push({view, trailingRight:a.last.right, base:b.last.right, titleWidth:a.title?.width, baseTitle:b.title?.width});
      } finally { await now.page.close(); await old.page.close(); }
    }
    // 6. Wide layout: the alert belongs to the main pane; the side list's status and both panes' controls stay put.
    for (const rtl of [false, true]) {
      const {page, errors: pageErrors} = await open(browser, tree, {width:1024, rtl}, 'chat', true);
      try {
        const wide = () => page.evaluate(() => {
          const box = node => { if (!node || !node.getClientRects().length) return null; const r = node.getBoundingClientRect(); return [r.left, r.right, r.top, r.width]; };
          const side = document.querySelector('#app.wide > .pane:first-child > .bar'), main = document.querySelector('#app.wide > .pane.main > .bar');
          const alert = document.getElementById('connection-alert');
          return {side:[...side.children].map(box), main:[...main.children].filter(n => !n.matches('.connection-cell')).map(box),
            sideStatus:box(side.querySelector('#status')), alert:alert.hidden ? null : box(alert), inMain:main.contains(alert),
            cells:document.querySelectorAll('.connection-cell, .connection-slot').length};
        });
        const online = await wide();
        assert.equal(online.cells, 0, 'wide: nothing reserved online'); assert.equal(online.alert, null);
        await setConnection(page, 'offline');
        const offline = await wide();
        assert.deepEqual(offline.main, online.main, `wide rtl:${rtl} main pane header unchanged`);
        assert.deepEqual(offline.sideStatus, online.sideStatus, `wide rtl:${rtl} side status box unchanged`);
        assert.ok(offline.alert && offline.inMain && offline.alert[3] >= 44, `wide rtl:${rtl} alert in the main pane header`);
        errors.push(...pageErrors.map(error => `wide: ${error}`));
      } finally { await page.close(); }
    }
    assert.deepEqual(errors, []);
    const sizes = {};
    for (const row of rows) { const key = row.where.split('/').slice(0, 2).join('/') + (row.where.includes('status:true') && !row.where.includes('/chat/') ? ' in status' : ' in title');
      const entry = sizes[key] ||= {alert:[Infinity, 0], controls:[Infinity, 0]};
      entry.alert = [Math.min(entry.alert[0], row.alertWidth), Math.max(entry.alert[1], row.alertWidth)];
      if (Number.isFinite(row.controlWidth)) entry.controls = [Math.min(entry.controls[0], row.controlWidth), Math.max(entry.controls[1], row.controlWidth)]; }
    console.log(JSON.stringify({sizes}, null, 1));
    console.log(JSON.stringify({cases:rows.length, reference, titleShrinkWithoutStatus:[...new Set(rows.filter(r => r.titleDelta).map(r => r.where + ' ' + r.titleDelta))].slice(0, 8)}, null, 2));
  } finally {
    await browser.close();
    for (const server of [tree, base]) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
