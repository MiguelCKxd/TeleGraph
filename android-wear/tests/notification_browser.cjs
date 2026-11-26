// Real app.js and DOM, with synthetic push status; no Telegram/APNs sends.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const snapshot = {account: 'qa', stage: 'ready', language: 'es', rtl: false, locked: false,
  connection: 'online', accounts: [], appearance: {}, lock: {}, settings: {font_size: 12, notifications: true}};
let status = {state: 'registered', provider: 'APNs', token_received: true, sandbox: false,
  registered_accounts: 1, connected_accounts: 1, token: 'PRIVATE_MUST_NOT_RENDER'};
let finishDelayed = null, delayStatus = false;
const requests = [];
const server = http.createServer((req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    const name = route.slice(5); requests.push(name);
    const result = name === 'state' ? snapshot : name === 'strings' ? {} :
      name === 'notification_status' ? status : [];
    const deliver = () => {res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify({ok: true, result}));};
    if (name === 'notification_status' && delayStatus) finishDelayed = deliver; else deliver();
    return;
  }
  fs.readFile(path.join(web, route === '/' ? 'index.html' : route), (error, data) => {
    if (error) {res.writeHead(404); res.end(); return;}
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
    await page.evaluate(() => {source.close(); state.settingsTab = 'notifications'; go('settings');});
    await page.getByRole('button', {name: 'Comprobar notificaciones', exact: true}).click();
    const panel = page.getByRole('dialog');
    await panel.getByText('Telegram ha aceptado el registro de 1 cuenta(s).', {exact: true}).waitFor();
    assert.match(await panel.innerText(), /Entorno de Apple: distribución/);
    assert.doesNotMatch(await panel.innerText(), /PRIVATE|APNs|token|registered_accounts/);
    assert.equal(await panel.evaluate(node => node.scrollWidth <= node.clientWidth), true);
    if (process.env.QA_SCREENSHOT) await page.screenshot({path: process.env.QA_SCREENSHOT});
    checks.push('settings control reports accepted registration and distribution without private token or raw fields');
    async function next(value, text) {
      status = {...status, ...value};
      await panel.getByRole('button', {name: 'Actualizar', exact: true}).click();
      await panel.getByText(text, {exact: true}).waitFor();
    }
    await next({state: 'registered', registered_accounts: 0, connected_accounts: 0},
      'Conecta una cuenta para comprobar el registro de notificaciones.');
    assert.doesNotMatch(await panel.innerText(), /ha aceptado/);
    checks.push('zero registered accounts never report success');
    await next({state: 'retrying', error: 'TimeoutError', connected_accounts: 1},
      'El registro no se ha completado. La app volverá a intentarlo automáticamente.');
    assert.doesNotMatch(await panel.innerText(), /TimeoutError/);
    checks.push('temporary failure offers automatic retry without raw internal exception');
    await next({state: 'unavailable', error: 'permission_denied'},
      'Permiso denegado. Activa las notificaciones en Ajustes del sistema.');
    checks.push('denied permission explains system Settings action');
    await next({state: 'registered', error: null, permission: 'denied', registered_accounts: 1},
      'Telegram ha aceptado el registro de 1 cuenta(s).');
    await panel.getByText('Permiso denegado. Activa las notificaciones en Ajustes del sistema.', {exact: true}).waitFor();
    checks.push('accepted Telegram registration never conceals independently denied OS permission');
    await next({state: 'disabled', error: null}, 'Las notificaciones están desactivadas en esta app.');
    checks.push('app preference disabled is distinct from OS failure');
    await next({state: 'registering', sandbox: true, permission: 'granted'}, 'Esperando a que se complete el registro de notificaciones.');
    assert.match(await panel.innerText(), /Entorno de Apple: desarrollo/);
    checks.push('pending registration and sandbox environment are shown honestly');
    delayStatus = true;
    await panel.getByRole('button', {name: 'Actualizar', exact: true}).click();
    await panel.getByText('Cargando...', {exact: true}).waitFor();
    await panel.getByRole('button', {name: 'Close', exact: true}).click();
    while (!finishDelayed) await new Promise(resolve => setTimeout(resolve, 5));
    finishDelayed();
    await page.getByRole('dialog').waitFor({state: 'hidden'});
    assert.equal(await page.evaluate(() => currentSheetPanel), null);
    checks.push('late response cannot reopen a dismissed dialog');
    assert.deepEqual(errors, []);
    assert.equal(requests.filter(name => /send|register_device|notify_test/.test(name)).length, 0);
    checks.push('diagnostic only reads state; no push or Telegram message is sent');
    console.log(JSON.stringify({passed: checks.length, checks}, null, 2));
  } finally {await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
