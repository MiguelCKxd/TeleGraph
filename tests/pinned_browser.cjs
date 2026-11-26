// Actual renderer and HTTP contract, with isolated messages and controlled replies.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), http = require('node:http'), path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
let pins = [{id:11, text:'Initial pinned message'}], requests = 0, hold = false, held = null;
const snapshot = {account:'qa', stage:'ready', language:'es', connection:'online', accounts:[],
  appearance:{}, settings:{font_size:12}, lock:{}, locked:false};
const server = http.createServer((req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type':'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    let result = route === '/api/state' ? snapshot : route === '/api/strings' ? {} : [];
    if (route === '/api/pinned') {requests++; result = pins;}
    const send = () => {res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify({ok:true, result}));};
    if (route === '/api/pinned' && hold) {hold = false; held = send;} else send();
    return;
  }
  fs.readFile(path.join(web, route === '/' ? 'index.html' : route), (error, data) => {
    res.writeHead(error ? 404 : 200, {'Content-Type':route.endsWith('.js') ? 'text/javascript' : route.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(error ? '' : data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME || undefined});
  const page = await browser.newPage({viewport:{width:390, height:844}});
  const errors = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  async function settle() {await page.evaluate(() => loadPinned());}
  async function waitHeld() {
    for (let i=0; i<100 && !held; i++) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(held, 'the delayed request reached the local HTTP server');
  }
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=qa&platform=iOS`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => {
      source.close(); state.view = 'chat';
      window.qaOpen = peer => {state.open = {peer, chat:{id:peer, name:'QA', kind:'user'}, messages:[], done:true}; render();};
      qaOpen(1);
    });
    await settle(); assert.match(await page.locator('#pinned').textContent(), /Initial pinned message/);
    const beforeBurst = requests;
    const stable = await page.evaluate(async () => {
      const bar = document.getElementById('pinned'), child = bar.lastChild, field = document.getElementById('field');
      field.focus(); let mutations = 0;
      const observer = new MutationObserver(records => {mutations += records.length;});
      observer.observe(bar, {childList:true, subtree:true, attributes:true});
      for (let i=0; i<50; i++) render();
      await loadPinned(); await Promise.resolve(); observer.disconnect();
      return {sameBar:bar === document.getElementById('pinned'), sameChild:child === bar.lastChild,
        focused:document.activeElement === field, visible:!bar.hidden, mutations};
    });
    assert.equal(requests - beforeBurst, 1);
    assert.deepEqual(stable, {sameBar:true, sameChild:true, focused:true, visible:true, mutations:0});
    checks.push('50 same-chat renders coalesce into one request and cause zero mutations in the visible pinned bar');
    pins = [{id:11, text:'Edited pinned message'}];
    await page.evaluate(async () => {EVENTS.edit({peer:1, message:{id:11, text:'Edited pinned message'}}); render(); await loadPinned();});
    assert.match(await page.locator('#pinned').textContent(), /Edited pinned message/);
    checks.push('the next render refreshes changed server content without replacing the pinned bar');
    pins = [];
    await page.evaluate(async () => {EVENTS.delete({peer:1, ids:[11]}); render(); await loadPinned();});
    assert.deepEqual(await page.locator('#pinned').evaluate(node => ({hidden:node.hidden, children:node.childNodes.length, onclick:node.onclick})),
      {hidden:true, children:0, onclick:null});
    checks.push('an empty response removes content and click action and hides the bar');
    pins = [{id:21, text:'Late previous chat'}]; hold = true;
    await page.evaluate(() => {qaOpen(2); window.qaOldPin = state.open.pinnedRequest.promise;}); await waitHeld();
    pins = [{id:31, text:'Current chat'}];
    await page.evaluate(async () => {qaOpen(3); await loadPinned();});
    held(); held = null; await page.evaluate(() => qaOldPin);
    assert.match(await page.locator('#pinned').textContent(), /Current chat/);
    assert.doesNotMatch(await page.locator('#pinned').textContent(), /Late previous/);
    checks.push('a delayed response for the previous chat cannot replace the current pinned bar');
    pins = [{id:41, text:'Previous account revision'}]; hold = true;
    await page.evaluate(() => {loadPinned(); window.qaOldPin = state.open.pinnedRequest.promise;}); await waitHeld();
    pins = [{id:51, text:'Current account revision'}];
    await page.evaluate(async () => {state.account = 'qb'; state.accountRevision++; render(); await loadPinned();});
    held(); held = null; await page.evaluate(() => qaOldPin);
    assert.match(await page.locator('#pinned').textContent(), /Current account revision/);
    assert.doesNotMatch(await page.locator('#pinned').textContent(), /Previous account/);
    checks.push('changing account revision discards an older reply even if a caller reuses the conversation object');
    pins = [{id:61, text:'Late lock response'}]; hold = true;
    await page.evaluate(() => {loadPinned(); window.qaOldPin = state.open.pinnedRequest.promise;}); await waitHeld();
    await page.evaluate(() => EVENTS.lock(true)); held(); held = null; await page.evaluate(() => qaOldPin);
    assert.equal(await page.locator('#pinned').count(), 0);
    checks.push('a response received after locking cannot restore conversation content');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed:checks.length, checks, totalRequests:requests, burst:stable}, null, 2));
  } finally {if (held) held(); await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
