// Real interface with controlled VisualViewport events; no accounts or network service.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const requests = [];
const snapshot = {account:'qa', stage:'ready', language:'es', connection:'online', accounts:[],
  appearance:{}, settings:{font_size:12}, lock:{}, locked:false};
const server = http.createServer((req,res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  if (route === '/events') {res.writeHead(200, {'Content-Type':'text/event-stream'}); res.write(': ready\n\n'); return;}
  if (route.startsWith('/api/')) {
    const method = route.slice(5); requests.push(method);
    const result = method === 'state' ? snapshot : method === 'strings' ? {} : [];
    res.writeHead(200, {'Content-Type':'application/json'}); res.end(JSON.stringify({ok:true,result})); return;
  }
  fs.readFile(path.join(web, route === '/' ? 'index.html' : route), (error,data) => {
    if (error) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {'Content-Type':route.endsWith('.js')?'text/javascript':route.endsWith('.css')?'text/css':'text/html'});
    res.end(data);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME || undefined});
  const page = await browser.newPage({viewport:{width:390,height:844}});
  const checks = [], errors = [], measurements = {};
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(() => {
      const fake = new EventTarget(); Object.assign(fake,{height:844,width:390,offsetTop:0,offsetLeft:0,scale:1});
      Object.defineProperty(window,'visualViewport',{value:fake});
      window.qaViewport = (values) => {Object.assign(fake,values); fake.dispatchEvent(new Event('resize'));};
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=fixture&platform=iOS`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => {
      source.close(); state.view='chat';
      state.open={peer:1,chat:{id:1,name:'Conversación de prueba',kind:'user'},messages:
        Array.from({length:80},(_,i)=>({id:i+1,text:'Mensaje de prueba '+i+' · contenido para mantener una conversación larga.',
          sender:'QA',sender_id:1,date:1795680000+i,kind:'text',out:i%2===1})),done:true};
      render(); document.documentElement.style.setProperty('--bottom','34px');
      window.qaField=document.getElementById('field');
      qaField.focus({preventScroll:true}); document.getElementById('scroll').scrollTop=100000;
    });
    const geometry = () => page.evaluate(() => {
      const app=document.getElementById('app').getBoundingClientRect(), bar=document.querySelector('#app > .bar').getBoundingClientRect();
      const composer=document.querySelector('.composer').getBoundingClientRect(), scroll=document.getElementById('scroll');
      return {height:app.height,top:app.top,headerTop:bar.top,composerBottom:composer.bottom,
        scrollTop:scroll.scrollTop,distance:scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop,
        focused:document.activeElement===qaField,bottom:getComputedStyle(document.documentElement).getPropertyValue('--bottom').trim()};
    });
    measurements.before=await geometry();
    await page.evaluate(() => qaViewport({height:500}));
    await page.waitForFunction(() => document.documentElement.hasAttribute('data-keyboard'));
    measurements.keyboard=await geometry();
    assert.equal(measurements.keyboard.height,500); assert.equal(measurements.keyboard.headerTop,0);
    assert.ok(measurements.keyboard.composerBottom<=500); assert.ok(measurements.keyboard.distance<=4);
    assert.equal(measurements.keyboard.focused,true); assert.equal(measurements.keyboard.bottom,'0px');
    checks.push('keyboard resizes only available area, retaining composer identity/focus and bottom message');
    await page.evaluate(() => {qaField.blur(); qaViewport({height:844});});
    await page.waitForFunction(() => !document.documentElement.hasAttribute('data-keyboard'));
    assert.equal((await geometry()).bottom,'34px');
    checks.push('closing keyboard restores the native bottom safe area');
    await page.evaluate(() => {document.getElementById('scroll').scrollTop=350; qaField.focus({preventScroll:true}); qaViewport({height:500});});
    await page.waitForFunction(() => document.documentElement.hasAttribute('data-keyboard'));
    assert.equal((await geometry()).scrollTop,350);
    checks.push('opening keyboard while reading older messages preserves position');
    const refreshed = await page.evaluate(() => {
      const field=document.getElementById('field'), scroll=document.getElementById('scroll');
      field.value='Borrador sin enviar';field.setSelectionRange(4,8);
      render();
      return {same:field===document.getElementById('field'),focused:document.activeElement===field,
        text:field.value,selection:[field.selectionStart,field.selectionEnd],scroll:scroll.scrollTop};
    });
    assert.deepEqual(refreshed,{same:true,focused:true,text:'Borrador sin enviar',selection:[4,8],scroll:350});
    checks.push('same-chat refresh preserves composer DOM, unsent draft, selection, keyboard and reading position');
    const bubbles = await page.evaluate(() => {
      const scroll=document.getElementById('scroll');state.settings.bubbles=true;render();
      return {same:scroll===document.getElementById('scroll'),bubbles:scroll.classList.contains('bubbles'),
        focused:document.activeElement===qaField};
    });
    assert.deepEqual(bubbles,{same:true,bubbles:true,focused:true});
    checks.push('retained conversation still applies changed presentation classes');
    const refreshedStyle = await page.evaluate(() => {
      Object.assign(S,{'Escribe un mensaje':'Write a message','Adjuntar':'Attach'});
      qaField.value='Primera línea\nSegunda línea\nTercera línea';resizeComposer(qaField);
      const before=qaField.clientHeight;
      state.settings.font_size=20;applySettings();render();
      const after=qaField.clientHeight;
      const result={same:qaField===document.getElementById('field'),focused:document.activeElement===qaField,
        placeholder:qaField.placeholder,aria:qaField.getAttribute('aria-label'),before,after};
      state.settings.font_size=12;applySettings();render();return result;
    });
    assert.equal(refreshedStyle.same,true);assert.equal(refreshedStyle.focused,true);
    assert.equal(refreshedStyle.placeholder,'Write a message');assert.equal(refreshedStyle.aria,'Write a message');
    assert.ok(refreshedStyle.after>refreshedStyle.before);
    checks.push('retained composer updates accessibility/localized labels and multiline height after a font change');
    const connection = await page.evaluate(() => {
      const bar=document.querySelector('#app > .bar');
      const read=()=>{const title=bar.querySelector('.title').getBoundingClientRect();
        const controls=[...bar.querySelectorAll(':scope > button')].map(node=>node.getBoundingClientRect().right);
        return {title:[title.x,title.width],controls};};
      // The usable edge: padding/safe area only, never an invisible reserved control (3.4.1 regression).
      const style=getComputedStyle(bar), usable=bar.getBoundingClientRect().right-parseFloat(style.paddingRight);
      const last=[...bar.children].filter(node=>node.getClientRects().length).pop().getBoundingClientRect().right;
      const before=read();const reserved=document.querySelectorAll('.connection-cell, .connection-slot').length;
      state.connection='offline';updateStatus();const after=read();
      const alert=document.getElementById('connection-alert').getBoundingClientRect();
      return {before,after,reserved,gap:usable-last,visible:!document.getElementById('connection-alert').hidden,
        alertInHeader:bar.contains(document.getElementById('connection-alert')),alertSize:[alert.width,alert.height]};
    });
    assert.deepEqual(connection.before,connection.after);assert.equal(connection.visible,true);
    assert.equal(connection.reserved,0);assert.ok(Math.abs(connection.gap)<=0.5,'chat header ends at its usable edge online');
    assert.equal(connection.alertInHeader,true);assert.ok(connection.alertSize.every(value=>value>=44));
    checks.push('offline indicator keeps the chat header and its controls in place without reserving space online');
    if(process.env.QA_SCREENSHOT_CHAT) await page.screenshot({path:process.env.QA_SCREENSHOT_CHAT});
    await page.evaluate(() => qaViewport({offsetTop:60}));
    await page.waitForFunction(() => document.getElementById('app').getBoundingClientRect().top===60);
    assert.equal((await geometry()).composerBottom,560);
    checks.push('visual viewport panning keeps header and composer in the visible rectangle');
    await page.evaluate(() => {
      window.qaWrites=0; window.qaObserver=new MutationObserver(records=>{qaWrites+=records.length;});
      qaObserver.observe(document.documentElement,{attributes:true,attributeFilter:['style','data-keyboard']});
      for(let i=0;i<100;i++)qaViewport({height:510,offsetTop:0});
    });
    await page.waitForFunction(() => document.getElementById('app').getBoundingClientRect().height===510);
    measurements.burstWrites=await page.evaluate(() => {qaObserver.disconnect();return qaWrites;});
    assert.ok(measurements.burstWrites<=3);
    checks.push('100 geometry events coalesce to a single frame and at most three DOM writes');
    await page.evaluate(() => {qaViewport({height:250,scale:2});});
    await page.waitForFunction(() => document.getElementById('app').getBoundingClientRect().height===844);
    assert.equal(await page.evaluate(() => document.documentElement.hasAttribute('data-keyboard')),false);
    checks.push('browser zoom is not treated as a keyboard or a different layout');
    await page.evaluate(() => {qaViewport({height:500,scale:1,offsetTop:0}); promptThen('Campo de prueba',{},()=>true,false);});
    await page.locator('#sheet-layer input').focus();
    await page.waitForFunction(() => document.getElementById('sheet-layer').getBoundingClientRect().height===500);
    await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(()=>{}))));
    const sheet=await page.locator('.sheet').boundingBox();
    assert.ok(sheet.y>=0 && sheet.y+sheet.height<=501);
    checks.push('focused form stays inside the reduced visible area');
    if(process.env.QA_SCREENSHOT) await page.screenshot({path:process.env.QA_SCREENSHOT});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:checks.length,checks,measurements},null,2));
  } finally {await browser.close();server.closeAllConnections(); await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
