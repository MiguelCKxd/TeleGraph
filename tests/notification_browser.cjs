// Real app.js and DOM, with synthetic push status; no Telegram/APNs sends.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
// Check the real bridge contract, without importing Core or opening an account.
const safeCodes = JSON.parse(execFileSync(process.env.PYTHON || 'python3', ['-c', `
import ast, json, pathlib, sys
tree = ast.parse(pathlib.Path(sys.argv[1]).read_text())
method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'push_error_code')
sets = {target.id: ast.literal_eval(node.value) for node in ast.walk(method) if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name) and target.id in {'allowed', 'rpc_codes'}}
assert set(sets) == {'allowed', 'rpc_codes'}
print(json.dumps(sorted(sets['allowed'] | sets['rpc_codes'])))
`, path.join(__dirname, '../src/tg_ascii_mobile/core.py')], {encoding: 'utf8'}));
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
    await next({privacy_warning: 'TimeoutError', privacy_warning_accounts: 1},
      'Telegram ha aceptado el registro de 1 cuenta(s).');
    await panel.locator('.notification-warning').getByText('Código: TimeoutError.', {exact: true}).waitFor();
    assert.doesNotMatch(await panel.innerText(), /no se ha completado|concentración/);
    checks.push('accepted registration stays accepted with a secondary privacy retry warning');
    await next({privacy_warning: 'token=PRIVATE_WARNING'},
      'No hay un código de error disponible para esta comprobación.');
    assert.doesNotMatch(await panel.innerText(), /PRIVATE_WARNING|token=/);
    checks.push('privacy warnings use the same fixed safe code boundary');
    await next({privacy_warning: null, privacy_warning_accounts: 0},
      'Telegram ha aceptado el registro de 1 cuenta(s).');
    assert.equal(await panel.locator('.notification-warning').count(), 0);
    checks.push('resolved privacy warning disappears on refresh');
    await next({state: 'registered', registered_accounts: 0, connected_accounts: 0},
      'Conecta una cuenta para comprobar el registro de notificaciones.');
    assert.doesNotMatch(await panel.innerText(), /ha aceptado/);
    checks.push('zero registered accounts never report success');
    await next({state: 'retrying', phase: 'telegram', error: 'TimeoutError', connected_accounts: 1},
      'La activación de las notificaciones no se ha completado. La app volverá a intentarlo automáticamente.');
    await panel.getByText('Paso: registro con Telegram.', {exact: true}).waitFor();
    await panel.getByText('Código: TimeoutError.', {exact: true}).waitFor();
    assert.doesNotMatch(await panel.innerText(), /concentración/);
    checks.push('registration timeout identifies its phase and safe code without blaming Focus settings');
    for (const code of safeCodes) {
      await next({state: 'retrying', phase: 'telegram', error: code, permission: 'granted'}, `Código: ${code}.`);
      assert.doesNotMatch(await panel.innerText(), /No hay un código|PRIVATE|concentración/);
      const explanation = await panel.locator('p.error').innerText();
      assert.ok(explanation.length > 0, `missing explanation for ${code}`);
    }
    checks.push(`all ${safeCodes.length} fixed Core diagnostic codes retain their code and explanation in the dialog`);
    // Paired with the actual Telethon BadRequestError boundary in test_push_diagnostic.py.
    // This is a synthetic provider error, not an error observed on the user's device.
    await next({error: 'APP_PUSH_APIKEY_MISSING'},
      'Falta la configuración del proveedor de notificaciones de esta app en Telegram.');
    await panel.getByText('Código: APP_PUSH_APIKEY_MISSING.', {exact: true}).waitFor();
    checks.push('synthetic exact provider RPC code explains app configuration and is not mistaken for OS permission');
    await next({error: 'BadRequestError'}, 'Telegram devolvió un error al procesar la solicitud.');
    await panel.getByText('Código: BadRequestError.', {exact: true}).waitFor();
    checks.push('generic BadRequestError preserves its safe category without implying a specific provider error');
    for (const error of ['APP_PUSH_API_KEY_MISSING', 'APP_PUSH_APIKEY_MISSING PRIVATE_SUFFIX',
      'PRIVATE_PREFIX TOKEN_INVALID', 'TOKEN_INVALID\nPRIVATE_SUFFIX']) {
      await next({error}, 'No hay un código de error disponible para esta comprobación.');
      assert.doesNotMatch(await panel.innerText(), /PRIVATE|APP_PUSH|TOKEN_INVALID|Código:/);
    }
    checks.push('unrecognized spellings and decorated RPC codes never reveal raw bridge text');
    await next({state: 'retrying', phase: 'privacy', error: 'TypeError', registered_accounts: 1, permission: 'granted'},
      'Paso: privacidad de los avisos en Telegram.');
    await panel.getByText('Cuentas registradas en Telegram: 1. Cuentas conectadas: 1.', {exact: true}).waitFor();
    await panel.getByText('Código: TypeError.', {exact: true}).waitFor();
    assert.match(await panel.innerText(), /La activación de las notificaciones no se ha completado/);
    assert.doesNotMatch(await panel.innerText(), /El registro no se ha completado/);
    assert.doesNotMatch(await panel.innerText(), /concentración/);
    checks.push('privacy failure preserves accepted registration count and distinguishes its cause');
    await next({error: 'privacy_registration'}, 'Telegram no confirmó los ajustes de privacidad de los avisos.');
    checks.push('false privacy result remains distinct from a request exception');
    await next({phase: undefined}, 'Paso: privacidad de los avisos en Telegram.');
    checks.push('legacy privacy failure without an explicit phase still identifies the right step');
    await next({phase: 'PRIVATE_PHASE_MUST_NOT_RENDER', error: 'token=PRIVATE_TOKEN_MUST_NOT_RENDER'},
      'No hay un código de error disponible para esta comprobación.');
    assert.doesNotMatch(await panel.innerText(), /PRIVATE|token=|concentración/);
    checks.push('unknown phase and free-form error payload cannot reveal private values');
    await next({phase: 'native', error: 'APNs_3010', registered_accounts: 0},
      'Paso: registro del dispositivo con Apple.');
    await panel.getByText('Código: APNs_3010.', {exact: true}).waitFor();
    checks.push('native registration failure is distinct from Telegram registration');
    await next({state: 'unavailable', phase: 'permission', error: 'permission_query_failed', permission: 'unknown'},
      'No se pudo consultar el permiso de notificaciones del sistema.');
    checks.push('OS permission query failure has its own phase and cause');
    await next({state: 'unavailable', phase: 'permission', error: 'permission_denied', permission: 'denied'},
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
