// Real application and download controller; local synthetic transfer metadata.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const snapshot = {account: 'qa', stage: 'ready', language: 'es', rtl: false, locked: false,
  connection: 'online', accounts: [], appearance: {}, lock: {}, settings: {font_size: 12, notifications: true}};
let job = {id: 'download-fixture', account: 'qa', peer: 42, message_id: 7, name: 'fixture.bin',
  state: 'queued', bytes: 0, total: null, percent: null, error: null, attempt: 1, revision: 1};
let failStatus = false, delayedStart = null, delayStart = false, opened = true;
const requests = [];
const server = http.createServer(async (req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    const name = route.slice(5);
    let data = ''; for await (const chunk of req) data += chunk;
    const args = data ? JSON.parse(data) : {};
    requests.push({name, args});
    let result = name === 'state' ? snapshot : name === 'strings' ? {} : [];
    if (name === 'download_start') result = {...job};
    if (name === 'download_status') result = {account: args.account, revision: job.revision,
      items: args.account === job.account ? [job] : []};
    if (name === 'download_cancel') result = job = {...job, state: 'cancelled', revision: job.revision + 1};
    if (name === 'download_retry') result = job = {...job, state: 'queued', bytes: 0, total: null,
      percent: null, error: null, attempt: job.attempt + 1, revision: job.revision + 1};
    if (name === 'download_open') result = {opened, name: job.name};
    const deliver = () => {
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify(name === 'download_status' && failStatus
        ? {ok: false, error: 'synthetic failure'} : {ok: true, result}));
    };
    if (name === 'download_start' && delayStart) delayedStart = deliver; else deliver();
    return;
  }
  fs.readFile(path.join(web, route === '/' ? 'index.html' : route), (error, data) => {
    if (error) {res.writeHead(404); res.end(); return;}
    if (route === '/' && !data.toString().includes('src="downloads.js"')) {
      data = Buffer.from(data.toString().replace('<script src="app.js">', '<script src="downloads.js"></script><script src="app.js">'));
    }
    res.writeHead(200, {'Content-Type': route.endsWith('.js') ? 'text/javascript' : route.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const errors = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=fixture&platform=iOS`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => {source.close(); window.downloadFixture = downloads;});
    await page.evaluate(() => openFile({id: 7}, 42, 'file'));
    const panel = page.getByRole('dialog');
    await panel.getByText('fixture.bin', {exact: true}).waitFor();
    await panel.getByText('En cola', {exact: true}).waitFor();
    checks.push('start returns a queued job immediately instead of holding a download RPC');
    async function progress(value) {
      job = {...job, ...value, revision: job.revision + 1};
      await page.evaluate(payload => downloadFixture.update(payload), {account: 'qa', revision: job.revision, items: [job]});
    }
    await progress({state: 'downloading', bytes: 4096});
    assert.equal(await panel.locator('progress').getAttribute('value'), null);
    assert.doesNotMatch(await panel.innerText(), /0\s*\/\s*0|100%|undefined|NaN/);
    checks.push('unknown total shows transferred bytes and an indeterminate progress element');
    await progress({bytes: 5242880, total: 10485760, percent: 50});
    assert.match(await panel.innerText(), /50%/);
    const cancel = panel.getByRole('button', {name: 'Cancelar', exact: true});
    await cancel.focus();
    await progress({bytes: 6291456, percent: 60});
    assert.equal(await cancel.evaluate(node => document.activeElement === node), true);
    checks.push('progress updates preserve control identity and keyboard focus');
    await page.evaluate(payload => downloadFixture.update(payload), {account: 'qa', revision: job.revision - 1,
      items: [{...job, state: 'queued', bytes: 0, percent: 0, revision: job.revision - 1}]});
    assert.match(await panel.innerText(), /60%/);
    checks.push('an older status response cannot roll progress back over a newer event');
    assert.equal(await panel.evaluate(node => node.scrollWidth <= node.clientWidth), true);
    if (process.env.QA_SCREENSHOT) {
      await page.waitForTimeout(200);
      await page.screenshot({path: process.env.QA_SCREENSHOT});
    }
    const bounds = await panel.boundingBox();
    await panel.getByRole('button', {name: 'Close', exact: true}).click();
    const cancelledBefore = requests.filter(item => item.name === 'download_cancel').length;
    await progress({bytes: 7340032, percent: 70});
    assert.equal(requests.filter(item => item.name === 'download_cancel').length, cancelledBefore);
    await page.evaluate(() => downloadFixture.show());
    await panel.getByText('fixture.bin', {exact: true}).waitFor();
    checks.push('closing the panel preserves transfer state and does not cancel or auto-open it');
    await cancel.click();
    await panel.getByText('Descarga cancelada', {exact: true}).waitFor();
    await panel.getByRole('button', {name: 'Reintentar desde el principio', exact: true}).click();
    await panel.getByText('En cola', {exact: true}).waitFor();
    assert.equal(job.bytes, 0);
    checks.push('cancel and explicit retry invoke separate APIs and restart at zero');
    await progress({state: 'cancelling'});
    await panel.getByText('Cancelando…', {exact: true}).waitFor();
    assert.equal(await panel.getByRole('button', {name: 'Cancelar', exact: true}).isVisible(), false);
    assert.equal(await panel.getByRole('button', {name: 'Reintentar desde el principio', exact: true}).isVisible(), false);
    checks.push('cleanup in progress cannot be cancelled again or retried prematurely');
    await progress({state: 'failed', error: 'storage_full', bytes: 1});
    await panel.getByText('No hay espacio suficiente para guardar el archivo.', {exact: true}).waitFor();
    checks.push('disk exhaustion is visible and keeps a retry action');
    await progress({state: 'ready', error: null, bytes: 10485760, total: 10485760, percent: 100});
    for (const name of ['Open', 'Save', 'Share']) assert.equal(await panel.getByRole('button', {name, exact: true}).isVisible(), true);
    await panel.getByRole('button', {name: 'Save', exact: true}).click();
    await page.waitForTimeout(30);
    assert.ok(requests.some(item => item.name === 'download_open' && item.args.action === 'save' && item.args.account === 'qa'));
    checks.push('completed result offers open/save/share scoped to the owning account');
    opened = false;
    await panel.getByRole('button', {name: 'Open', exact: true}).click();
    await panel.getByText('No se pudo abrir el archivo. Puedes guardarlo o compartirlo.', {exact: true}).waitFor();
    checks.push('system open failure stays visible without claiming a successful save');
    await page.evaluate(() => {state.account = 'other'; state.accountRevision++; downloadFixture.reset(); downloadFixture.show();});
    await panel.getByText('No hay descargas.', {exact: true}).waitFor();
    await page.evaluate(payload => downloadFixture.update(payload), {account: 'qa', revision: 900, items: [job]});
    assert.doesNotMatch(await panel.innerText(), /fixture.bin/);
    checks.push('foreign-account events cannot populate the new account panel');
    await page.evaluate(() => {state.account = 'qa'; state.accountRevision++; downloadFixture.reset();});
    delayStart = true;
    await page.evaluate(() => {window.pendingDownloadStart = downloadFixture.start({id: 7}, 42);});
    while (!delayedStart) await new Promise(resolve => setTimeout(resolve, 5));
    await page.evaluate(() => {state.account = 'other'; state.accountRevision++; downloadFixture.reset();});
    delayedStart();
    assert.equal(await page.evaluate(() => pendingDownloadStart), false);
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    assert.equal(await page.evaluate(() => currentSheetPanel), null);
    checks.push('late start response after an account switch cannot reopen the panel or export');
    delayStart = false; opened = true;
    job = {...job, id: 'last-download', state: 'queued', bytes: 0, total: null, percent: null, error: null,
      revision: job.revision + 1};
    await page.evaluate(() => {state.account = 'qa'; state.accountRevision++; downloadFixture.reset();});
    const opensBefore = requests.filter(item => item.name === 'download_open').length;
    await page.evaluate(() => openFile({id: 7}, 42, 'file'));
    await progress({state: 'ready', bytes: 8, total: 8, percent: 100});
    await page.waitForTimeout(50);
    assert.equal(requests.filter(item => item.name === 'download_open').length, opensBefore + 1);
    await page.evaluate(payload => downloadFixture.update(payload), {account: 'qa', revision: job.revision, items: [job]});
    await page.waitForTimeout(30);
    assert.equal(requests.filter(item => item.name === 'download_open').length, opensBefore + 1);
    assert.equal(await page.evaluate(() => ['download_open', 'download_cancel', 'download_retry'].every(name => NO_RETRY.has(name))), true);
    checks.push('an explicit action opens the finished result once, with automatic POST replay disabled');
    await panel.getByRole('button', {name: 'Close', exact: true}).click();
    assert.equal(requests.filter(item => item.name === 'open_file').length, 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: checks.length, checks, viewport: {width: 390, height: 844}, bounds}, null, 2));
  } finally {await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
