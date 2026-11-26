// Real WebView script; transport errors, account races and SSE packets are controlled.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const web = path.join(__dirname, '../src/tg_ascii_mobile/web');
const snapshot = {account: 'a', stage: 'ready', language: 'en', rtl: false, locked: false,
  connection: 'online', accounts: [], appearance: {}, lock: {}, settings: {font_size: 12}};
const requests = [];
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/events') {
    res.writeHead(200, {'Content-Type': 'text/event-stream'}); res.write(': ready\n\n'); return;
  }
  if (pathname.startsWith('/api/')) {
    const name = pathname.slice(5);
    requests.push(name);
    const result = name === 'state' ? snapshot : name === 'strings' ? {} :
      name === 'premium_settings' ? {premium: false, name_colors: [], profile_colors: []} :
      ['chats', 'folders', 'windows', 'outbox', 'calls', 'languages', 'recent_searches'].includes(name) ? [] : null;
    res.writeHead(200, {'Content-Type': 'application/json'});
    res.end(JSON.stringify({ok: true, result})); return;
  }
  const file = path.join(web, pathname === '/' ? 'index.html' : pathname);
  fs.readFile(file, (error, data) => {
    if (error) {res.writeHead(404); res.end(); return;}
    res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
    res.end(data);
  });
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME || undefined});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const checks = [];
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?t=fixture`);
    await page.waitForFunction(() => state.started);
    await page.evaluate(() => source.close());
    const late = await page.evaluate(async () => {
      const original = fetch, language = chooseLanguage, profile = openProfile, copied = copy, output = {};
      chooseLanguage = (title, done) => done('en');
      const tick = () => new Promise(resolve => setTimeout(resolve, 0));
      for (const method of ['translate', 'summarize', 'transcribe', 'compose_ai', 'bot_button']) {
        let finish, opened = 0;
        window.fetch = url => url === '/api/' + method ? new Promise(resolve => {finish = resolve;}) : original(url);
        openProfile = () => {opened++;}; copy = () => {opened++;};
        state.locked = false; state.account = 'a'; state.open = {peer: 1, chat: {id: 1}, messages: []};
        closeSheet(true);
        const message = {id: 2};
        if (method === 'translate') translateMessage(message);
        if (method === 'summarize') summarizeMessage(message);
        if (method === 'transcribe') transcribeMessage(message);
        if (method === 'compose_ai') {
          document.getElementById('field')?.remove();
          const field = document.createElement('textarea'); field.id = 'field'; field.value = 'Private draft'; document.body.append(field);
          composeAI(); document.querySelector('#sheet-layer .item').click();
        }
        if (method === 'bot_button') pressButton(message, {row:0,column:0});
        state.account = 'b'; state.accountRevision++; state.open = {peer: 99}; closeSheet(true);
        const value = method === 'translate' ? {'2': {text: 'Private result'}} : method === 'bot_button'
          ? {profile: 123, copy: 'Private'} : {text: 'Private result', emojis: []};
        finish({ok:true,json:async()=>({ok:true,result:value})}); await tick();
        output[method] = {shown: !document.getElementById('sheet-layer').hidden, opened};
      }
      fetch = original; chooseLanguage = language; openProfile = profile; copy = copied; closeSheet(true);
      return output;
    });
    checks.push(['late account responses', late]);
    const forms = await page.evaluate(async () => {
      let finish;
      formSheet('Old form', [], 'Submit', () => new Promise(resolve => {finish = resolve;}));
      document.querySelector('#sheet-layer .primary').click();
      formSheet('New form', [], 'Submit', () => false);
      finish(true); await new Promise(resolve => setTimeout(resolve,0));
      return !document.getElementById('sheet-layer').hidden;
    });
    checks.push(['new form survives old submit', forms]);
    const frames = await page.evaluate(async () => {
      const original = fetch, timer = setTimeout, finished = []; let rearmed = 0;
      fetch = url => url === '/api/call_frames' ? new Promise(resolve => finished.push(resolve)) : original(url);
      setTimeout = (action, delay, ...args) => {if (delay===160) rearmed++; return timer(action, delay, ...args);};
      state.stage='ready'; state.locked=false; state.nativeCall={token:'fixture',state:'active',peer:1,video:true};
      drawNativeCall(); drawNativeCall();
      finished[0]({ok:true,json:async()=>({ok:true,result:{local:'fixture'}})});
      await new Promise(resolve => timer(resolve,0));
      const staleTimers = rearmed;
      state.nativeCall=null; drawNativeCall();
      finished[1]({ok:true,json:async()=>({ok:true,result:{}})});
      await new Promise(resolve => timer(resolve,0));
      fetch=original; setTimeout=timer;
      return staleTimers;
    });
    checks.push(['detached call frame loops', frames]);
    const videos = await page.evaluate(async () => {
      const pause = HTMLMediaElement.prototype.pause, load = HTMLMediaElement.prototype.load;
      HTMLMediaElement.prototype.pause = function(){}; HTMLMediaElement.prototype.load = function(){};
      try {
        storyViewer([{peer:1,id:1,name:'a',video:true},{peer:1,id:2,name:'b',video:true}],0);
        const dialog=document.querySelector('.media-viewer'), first=dialog.querySelector('video');
        [...dialog.querySelectorAll('button')].find(item=>item.textContent==='Next').click();
        const second=dialog.querySelector('video');
        const closed = new Promise(resolve => dialog.addEventListener('close', resolve, {once:true}));
        dialog.close(); await closed;
        return [first.hasAttribute('src'),second.hasAttribute('src')];
      } finally {HTMLMediaElement.prototype.pause=pause; HTMLMediaElement.prototype.load=load;}
    });
    checks.push(['story players released', videos]);
    const abandoned = await page.evaluate(async () => {
      const original=fetch, output={}, tick=()=>new Promise(resolve=>setTimeout(resolve,0));
      let finish, extra=0;
      fetch=url=>url==='/api/sticker_packs' ? new Promise(resolve=>{finish=resolve;}) : url==='/api/sticker_documents'
        ? (extra++,Promise.resolve({ok:true,json:async()=>({ok:true,result:[]})})) : original(url);
      state.open={peer:1}; stickerPicker(true); closeSheet(true); state.accountRevision++;
      finish({ok:true,json:async()=>({ok:true,result:[]})}); await tick();
      output.stickerRequests=extra;
      fetch=original;
      const chosen=pickOnePhoto();
      const picker=document.querySelector('input[type=file]'); picker.dispatchEvent(new Event('cancel'));
      output.cancel=await Promise.race([chosen.then(()=>true),new Promise(resolve=>setTimeout(()=>resolve(false),30))]);
      output.pickerRemoved=!picker.isConnected; picker.remove();
      let uploads=0;
      fetch=url=>String(url).startsWith('/upload?') ? (uploads++,new Promise(resolve=>{finish=resolve;})) : original(url);
      state.account='a'; state.open={peer:1}; state.attachments=[];
      await chooseFiles('gallery');
      const input=document.querySelector('input[type=file]');
      Object.defineProperty(input,'files',{value:[new File(['a'],'a.jpg'),new File(['b'],'b.jpg')]});
      input.dispatchEvent(new Event('change'));
      await tick(); state.account='b'; state.accountRevision++; state.open={peer:2};
      finish({ok:true,json:async()=>({ok:true,result:{key:'old',name:'a.jpg'}})}); await tick();
      output.uploads=uploads;
      // Resolve the unwanted second transfer on the pre-fix version, for test cleanup.
      if(uploads>1) {finish({ok:true,json:async()=>({ok:true,result:{key:'old2',name:'b.jpg'}})}); await tick();}
      fetch=original;
      return output;
    });
    checks.push(['abandoned pickers and sticker work', abandoned]);
    const contacts = await page.evaluate(async () => {
      const original=fetch, originalOpen=openChat, originalPick=pickOnePhoto, output={}, tick=()=>new Promise(resolve=>setTimeout(resolve,0));
      let opened=0; openChat=()=>{opened++;};
      for (const method of ['create_group','add_contact','contact_photo','reactions']) {
        let finish; opened=0;
        state.account='a'; state.open={peer:1}; state.view='chats'; closeSheet(true);
        fetch=url=>url==='/api/'+method ? new Promise(resolve=>{finish=resolve;}) : original(url);
        if(method==='create_group') {newGroup([1]); document.querySelector('#sheet-layer input').value='Group'; document.querySelector('#sheet-layer .primary').click();}
        if(method==='add_contact') {contactForm(null); document.querySelector('#sheet-layer input').value='Name'; document.querySelector('#sheet-layer .primary').click();}
        if(method==='contact_photo') {pickOnePhoto=()=>new Promise(resolve=>{finish=resolve;}); contactPhoto({id:1,name:'Private contact'},true);}
        if(method==='reactions') reactionPicker({id:9});
        await tick();
        state.open={peer:2};
        if(method!=='reactions') {state.account='b'; state.accountRevision++;}
        closeSheet(true);
        if(method==='contact_photo') finish({key:'old'});
        else finish({ok:true,json:async()=>({ok:true,result:method==='reactions'?{standard:['👍'],custom:[]}:{id:44,name:'Private contact'}})});
        await tick();
        output[method]={opened,shown:!document.getElementById('sheet-layer').hidden};
      }
      fetch=original; openChat=originalOpen; pickOnePhoto=originalPick; closeSheet(true);
      return output;
    });
    checks.push(['late contacts and reaction context', contacts]);
    const voicePolls = await page.evaluate(async () => {
      const original=fetch; let polls=0, finish;
      fetch=url=>url==='/api/voice_level' ? (polls++,new Promise(resolve=>{finish=resolve;})) :
        ['/api/voice_start','/api/voice_cancel'].includes(url) ? Promise.resolve({ok:true,json:async()=>({ok:true,result:true})}) : original(url);
      state.voice=null; state.open={peer:1};
      await voiceRecorder(); await new Promise(resolve=>setTimeout(resolve,600));
      const count=polls;
      closeSheet(true);
      finish({ok:true,json:async()=>({ok:true,result:{recording:true,seconds:1,level:.1}})});
      await new Promise(resolve=>setTimeout(resolve,300));
      fetch=original;
      return [count,polls];
    });
    checks.push(['voice level backpressure and stop',voicePolls]);
    console.log(JSON.stringify({checks},null,2));
    assert.deepEqual(voicePolls,[1,1]);
    assert.ok(Object.values(contacts).every(item=>!item.shown&&!item.opened));
    assert.ok(Object.values(late).every(item=>!item.shown && !item.opened));
    assert.deepEqual(abandoned,{stickerRequests:0,cancel:true,pickerRemoved:true,uploads:1});
    assert.equal(forms,true); assert.equal(frames,0); assert.deepEqual(videos,[false,false]);
  } finally {await browser.close(); server.closeAllConnections(); server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
