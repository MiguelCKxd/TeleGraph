// Changes go through the actual user controls and saveLook/API path.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const snapshot = {account:'qa', stage:'ready', language:'es', rtl:false, locked:false, connection:'online',
  accounts:[], appearance:{presentation:{}}, lock:{}, settings:{font_size:12, bubbles:true, reduce_animations:true}};
const writes = [];
const server = http.createServer(async (req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type':'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    let body = ''; for await (const chunk of req) body += chunk;
    const args = body ? JSON.parse(body) : {};
    if (route === '/api/appearance') {
      assert.equal(args.account, 'qa'); writes.push(args.values);
      snapshot.appearance = {...snapshot.appearance, ...args.values};
    }
    const result = route === '/api/state' ? snapshot : route === '/api/strings' ? {}
      : route === '/api/appearance' ? snapshot.appearance : [];
    res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify({ok:true, result})); return;
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
  const errors = [], checks = [], measured = {};
  page.on('pageerror', error => errors.push(error.message));
  async function settings() {
    await page.evaluate(() => {source.close(); state.settingsTab = 'appearance'; go('settings');});
  }
  async function field(key) {
    const holder = page.locator('[data-presentation-key="' + key + '"]');
    const group = holder.locator('xpath=ancestor::details');
    if (await group.getAttribute('open') === null) await group.locator('summary').click();
    return holder;
  }
  async function settle() {await page.evaluate(() => appearanceWrites);}
  async function number(key, value) {
    const input = (await field(key)).locator('input[type=number]');
    await input.fill(String(value)); await input.focus(); await input.dispatchEvent('change'); await settle();
  }
  async function choose(key, value) {
    await (await field(key)).locator('select').selectOption(value); await settle();
  }
  async function toggle(key) {
    await (await field(key)).getByRole('switch').click(); await settle();
  }
  async function color(key, value) {
    const input = (await field(key)).locator('input[type=color]');
    await input.fill(value); await input.dispatchEvent('change'); await settle();
  }
  async function metrics() {
    return page.evaluate(() => {
      const old = document.getElementById('presentation-fixture'); old?.remove();
      const messages = [{id:901, sender:'Alba', text:'A measured incoming message with several words.', time:'12:45', kind:'text'},
        {id:902, sender:'You', text:'A measured outgoing reply.', time:'12:46', kind:'text', out:true}];
      state.open = {peer:42, chat:{id:42, name:'Fixture', kind:'group'}, messages};
      const fixture = h('section', {id:'presentation-fixture', style:'position:fixed;left:-1000px;top:0;width:360px'},
        h('div', {class:'bar'}, button('<', () => {}), h('div', {class:'title'}, 'Measured title')),
        h('div', {id:'chatlist'}, chatRow({id:42, name:'Alba', unread:7,
          preview:'A deliberately long message preview fills more than one line so wrapping can be measured reliably.',
          date:1}, 'chats', false)),
        h('div', {class:'bubbles'}, h('div', {class:'messages'}, ...messages.map(messageNode))),
        button('Measured button', () => {}), h('div', {class:'sheet'}, h('button', {class:'item'}, 'Menu item')),
        h('button', {class:'tab'}, 'Tab'));
      document.body.append(fixture);
      const find = selector => fixture.querySelector(selector);
      const style = selector => getComputedStyle(find(selector));
      const box = selector => {const b = find(selector).getBoundingClientRect(); return {x:b.x, y:b.y, width:b.width, height:b.height};};
      return {
        message:style('.msg .text').fontSize, header:style('.bar .title').fontSize, name:style('.row .name').fontSize,
        preview:style('.row .preview').fontSize, metadata:style('.msg .meta').fontSize,
        lineHeight:style('.msg .text').lineHeight, gap:style('.messages').gap,
        paddingX:style('.msg').paddingInlineStart, paddingY:style('.msg').paddingBlockStart,
        previewHeight:box('.row .preview').height, previewLineHeight:parseFloat(style('.row .preview').lineHeight),
        previewWhiteSpace:style('.row .preview').whiteSpace, buttonHeight:box(':scope > .btn').height,
        headerButtonHeight:box('.bar .btn').height, menuItemHeight:box('.sheet .item').height, tabHeight:box(':scope > .tab').height,
        inAlign:style('.msg:not(.out)').alignSelf, outAlign:style('.msg.out').alignSelf,
        inBounds:box('.msg:not(.out)'), outBounds:box('.msg.out'),
        inColor:style('.msg:not(.out) .text').color, outColor:style('.msg.out .text').color,
        inMeta:style('.msg:not(.out) .meta').color, outMeta:style('.msg.out .meta').color,
        avatarDisplay:style('.chat-avatar-button').display, timeDisplay:style('.when').display, badgeDisplay:style('.badge').display,
        unreadText:find('.badge').textContent,
        livePreviewMessage:getComputedStyle(document.querySelector('.presentation-preview .msg .text')).fontSize,
      };
    });
  }
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=qa&platform=iOS`);
    await page.waitForFunction(() => state.started);
    await settings(); measured.before = await metrics();
    assert.ok(measured.before.menuItemHeight >= 48, 'the existing 48px menu target is preserved');
    for (const [key, value] of [['message_font_size',24], ['header_font_size',27], ['name_font_size',20],
      ['preview_font_size',18], ['metadata_font_size',12]]) await number(key, value);
    measured.sizes = await metrics();
    assert.deepEqual(['message','header','name','preview','metadata'].map(key => measured.sizes[key]),
      ['24px','27px','20px','18px','12px']);
    assert.equal(measured.sizes.livePreviewMessage, measured.sizes.message);
    checks.push('five independent size controls change computed typography in actual chat widgets and the live preview');
    await number('message_line_height', 175); await number('message_gap', 12);
    await number('message_padding_x', 17); await number('message_padding_y', 9);
    measured.spacing = await metrics();
    assert.equal(measured.spacing.lineHeight, '42px');
    assert.deepEqual([measured.spacing.gap, measured.spacing.paddingX, measured.spacing.paddingY], ['12px','17px','9px']);
    checks.push('line height, message gap and both padding axes have independent measured effects');
    await number('preview_lines', 3); measured.lines = await metrics();
    assert.equal(measured.lines.previewWhiteSpace, 'normal');
    assert.ok(measured.lines.previewHeight > measured.lines.previewLineHeight * 2.5);
    assert.ok(measured.lines.previewHeight < measured.lines.previewLineHeight * 3.1);
    checks.push('three preview lines wrap and clamp the actual chat row');
    for (const key of ['list_avatars','list_times','list_badges']) await toggle(key);
    const hidden = await metrics();
    assert.deepEqual([hidden.avatarDisplay,hidden.timeDisplay,hidden.badgeDisplay], ['none','none','none']);
    assert.equal(hidden.unreadText, '7');
    checks.push('list visibility options hide presentation while preserving unread data');
    for (const value of ['start','end','center']) {
      await choose('bubble_alignment', value); const result = await metrics();
      const position = box => box.x + (value === 'end' ? box.width : value === 'center' ? box.width / 2 : 0);
      assert.ok(Math.abs(position(result.inBounds) - position(result.outBounds)) < .1, value + ' aligns actual bubble edges');
    }
    checks.push('all three explicit alignments affect incoming and outgoing bubbles');
    for (const [key, value] of [['incoming_text_color','#e3f2fd'],['outgoing_text_color','#ffe0b2'],
      ['incoming_metadata_color','#90caf9'],['outgoing_metadata_color','#ffcc80']]) await color(key, value);
    measured.colors = await metrics();
    assert.deepEqual([measured.colors.inColor,measured.colors.outColor,measured.colors.inMeta,measured.colors.outMeta],
      ['rgb(227, 242, 253)','rgb(255, 224, 178)','rgb(144, 202, 249)','rgb(255, 204, 128)']);
    checks.push('incoming/outgoing text and metadata colors work independently without replacing bubble backgrounds');
    await number('button_height', 60); measured.buttons = await metrics();
    for (const key of ['buttonHeight','headerButtonHeight','menuItemHeight','tabHeight']) assert.ok(measured.buttons[key] >= 60, key);
    await choose('controls', 'icons'); await choose('navigation','tabs');
    assert.equal(await page.locator('.app-navigation [data-ui-icon]').count(), 4);
    checks.push('button target height is adjustable above 44px and navigation preserves native icon hooks');
    const keyboardSlider = (await field('message_font_size')).locator('input[type=range]');
    await keyboardSlider.focus(); await keyboardSlider.press('ArrowRight'); await settle();
    assert.equal(await page.evaluate(() => document.activeElement?.closest('[data-presentation-key]')?.dataset.presentationKey), 'message_font_size',
      JSON.stringify(await page.evaluate(() => ({active:document.activeElement?.tagName,
        open:document.querySelector('[data-presentation-key=message_font_size]').closest('details').open,
        count:document.querySelectorAll('[data-presentation-key=message_font_size] input[type=number]').length}))));
    assert.equal(await page.locator('[data-presentation-key=message_font_size]').locator('xpath=ancestor::details').getAttribute('open'), '');
    await page.keyboard.press('ArrowRight'); await settle();
    assert.equal(await page.locator('[data-presentation-key=message_font_size] input[type=number]').inputValue(), '26');
    checks.push('keyboard slider adjustments preserve section and focus across successive saves');
    const presentation = page.locator('.presentation-settings');
    assert.equal(await presentation.evaluate(node => node.scrollWidth <= node.clientWidth), true);
    await page.evaluate(() => {state.open = null;});
    for (const width of [320, 1024]) {
      await page.setViewportSize({width, height:844}); await settings();
      assert.equal(await presentation.evaluate(node => node.scrollWidth <= node.clientWidth), true, 'settings overflow at ' + width);
    }
    await page.setViewportSize({width:390, height:844}); await settings();
    checks.push('the grouped controls fit narrow phones and tablet side panes without horizontal overflow');
    if (process.env.QA_SCREENSHOT) {
      await page.locator('.presentation-preview .messages').scrollIntoViewIfNeeded();
      await page.screenshot({path:process.env.QA_SCREENSHOT});
    }
    await page.reload(); await page.waitForFunction(() => state.started); await settings();
    assert.equal(await page.locator('[data-presentation-key=message_font_size] input[type=number]').inputValue(), '26');
    checks.push('a new page reads saved presentation choices through the state API');
    await page.getByRole('button', {name:'Restablecer composición', exact:true}).click(); await settle();
    measured.reset = await metrics();
    for (const key of ['message','header','name','preview','metadata','lineHeight','gap','paddingX','paddingY','previewWhiteSpace',
      'buttonHeight','headerButtonHeight','menuItemHeight','tabHeight','inAlign','outAlign','inColor','outColor','inMeta','outMeta','avatarDisplay','timeDisplay','badgeDisplay']) {
      assert.equal(measured.reset[key], measured.before[key], 'reset restores ' + key);
    }
    checks.push('composition reset restores baseline computed styles and list visibility');
    assert.deepEqual(errors, []);
    assert.ok(writes.length >= 20);
    console.log(JSON.stringify({passed:checks.length, checks, measured, savedThroughUserControls:writes.length}, null, 2));
  } finally {await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1;});
