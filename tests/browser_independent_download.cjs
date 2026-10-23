const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();

(async () => {
 const browser = await chromium.launch({headless:true});
 try {
  for (const width of [390, 1440]) {
   const page = await browser.newPage({viewport:{width,height:900}});
   const errors = [], imports = [], polls = [];
   let complete = false, failStart = false, libraryLoads = 0;
   await page.addInitScript(() => localStorage.setItem('karaoke_token', 'test-session'));
   page.on('pageerror', error => errors.push(error.message));
   page.on('dialog', dialog => { errors.push(dialog.message()); dialog.dismiss(); });
   await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.hostname !== 'karaoke.test') return route.abort();
    if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:HTML});
    if (url.pathname === '/app-icon-v8.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync('app/templates/app-icon-v8.png')});
    const send = (data, status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    if (url.pathname === '/api/auth_status') return send({status:'authenticated',username:'owner',role:'admin'});
    if (url.pathname === '/api/status') return send({status:'processing',step:'Transcribing vocals',progress:61,can_cancel:true,process_summary:{title:'Música em andamento'}});
    if (url.pathname === '/api/queue') return send({jobs:[{id:'active',title:'Música em andamento',status:'processing'}]});
    if (url.pathname === '/api/library') {libraryLoads++; return send({videos:[],photos:[],history:[],audio:[],backgrounds:[]});}
    if (url.pathname === '/api/easy-mode') return send({enabled:true,whisper_model:'medium',lyrics_mode:'auto'});
    if (url.pathname === '/api/youtube-metadata') return send({title:'Vídeo para guardar'});
    if (url.pathname === '/api/download-youtube-preset') {
     imports.push(request.postDataJSON());
     return failStart ? send({detail:'Renove os cookies do YouTube.'},409) : send({status:'started',download_id:'own-import'});
    }
    if (url.pathname === '/api/youtube-preset-status/audio') {
     polls.push(url.searchParams.get('download_id'));
     // The global latest download belongs to another tab. Never show it here.
     if (url.searchParams.get('download_id') !== 'own-import') return send({status:'done',filename:'wrong-tab.mp4'});
     return send(complete ? {status:'done',progress:100,title:'Meu vídeo',filename:'meu-video.mp4'} :
       {status:'downloading',progress:null,title:'Unindo áudio e vídeo…'});
    }
    return send({});
   });
   await page.goto('http://karaoke.test');
   await page.waitForFunction(() => currentUser && document.querySelector('#processingQueueList').textContent.includes('Música em andamento'));
   await page.locator('#tabBtnLibrary').click();
   await page.locator('#libraryImports > summary').click();
   await page.locator('#libAudioYoutubeUrl').fill('https://youtu.be/abcdefghijk');
   await page.locator('#btnLibDownloadYoutube').click();
   await page.waitForFunction(() => document.getElementById('audioYtStatusPercent').textContent === 'Transferindo…');
   assert(await page.locator('#btnLibDownloadYoutube').isDisabled());
   assert((await page.locator('#processingQueueList').textContent()).includes('Música em andamento'));
   assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
   fs.mkdirSync('review-artifacts',{recursive:true});
   await page.screenshot({path:`review-artifacts/download-${width}.png`,fullPage:false});
   const before = libraryLoads; complete = true;
   await page.waitForFunction(() => !document.getElementById('btnLibDownloadYoutube').disabled);
   assert(libraryLoads > before);
   assert((await page.locator('#audioYtSelectedText').textContent()).includes('meu-video.mp4'));
   assert.equal(await page.locator('#tabBtnLibrary').getAttribute('aria-selected'),'true');
   assert(polls.length > 0 && polls.every(id => id === 'own-import'));
   assert.equal(imports.length,1);
   assert.deepEqual(errors,[]);
   // The shared import helper must also follow the returned request ID.
   const imported = await page.evaluate(() => importYoutubeToLibrary('https://youtu.be/abcdefghijk','audio'));
   assert.equal(imported.filename,'meu-video.mp4');
   failStart = true;
   const dialogPromise = page.waitForEvent('dialog');
   await page.locator('#btnLibDownloadYoutube').click();
   assert((await dialogPromise).message().includes('Renove os cookies'));
   await page.close();
  }
  console.log('Independent downloads passed during processing on mobile and desktop.');
 } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
