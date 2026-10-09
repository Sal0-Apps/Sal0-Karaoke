const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const HTML=fs.readFileSync('app/templates/index.html','utf8');
for(const match of HTML.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new Function(match[1]);
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:390,height:900},isMobile:true,hasTouch:true});
  const errors=[],starts=[],cookies=[],updates=[],polls=[];
  let connected=false,configured=false,session=null,nonce=0,pollKind='pending',heldPoll=null,holdPoll=false,sessionState='anonymous',failCookies=false,failLink=true,updating=false,processing=false;
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{localStorage.setItem('karaoke_token','session');Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>window.copiedYoutubeCode=text}});});
  await page.clock.install({time:new Date('2026-10-09T13:00:00Z')});
  await page.clock.pauseAt(new Date('2026-10-09T13:00:01Z'));
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.hostname!=='external.karaoke.test')return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:HTML});
   const reply=(data,status=200,headers={})=>route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(data)});
   const path=url.pathname;
   if(path==='/api/auth_status')return reply({status:'authenticated',username:'owner',role:'admin'});
   if(path==='/api/status')return reply(processing?{status:'processing',progress:30,owned_by_current_user:true,owner_username:'owner',original_filename:'previous.mp3'}:{status:'idle',progress:0});
   if(path==='/api/easy-mode')return reply({enabled:true,lyrics_mode:'auto',background_mode:'original'});
   if(path==='/api/queue')return reply({jobs:[]});
   if(path==='/api/library')return reply({videos:[],photos:[],history:[]});
   if(path==='/api/users')return reply([{username:'owner',role:'admin'}]);
   if(path==='/api/admin/results')return reply({results:[]});
   if(path==='/api/youtube/publication-options')return reply({enabled:false});
   if(path==='/api/admin/youtube/status')return reply({connected,device_configured:configured,device_session:session,web_configured:false,channel_title:'Meu canal',connection_state:connected?'connected':'auth_required',recovery:connected?null:'auth_required',message:'A autorização expirou. Reconecte seu canal.',settings:{privacy:'unlisted',playlist_id:'PL-saved',title_template:'{title} | Karaokê',user_assignments:{}},jobs:connected?[]:[{id:'upload',title:'Vídeo em espera',status:'auth_required',progress:92,privacy:'unlisted'}]});
   if(path==='/api/admin/youtube/playlists')return reply({playlists:[{id:'PL-saved',title:'Destino salvo'}]});
   if(path==='/api/admin/youtube/verify-connection')return reply({connected,message:'Reconecte seu canal.'});
   if(path==='/api/admin/youtube/device/start'){
    const body=request.postDataJSON();starts.push(body);configured=true;
    session={session_id:'nonce-'+(++nonce),status:'pending',user_code:'ABCD-EFGH',verification_url:'https://www.google.com/device',expires_at:Date.now()/1000+1800,interval:5,message:'Aprove o código no Google.'};
    return reply(session);
   }
   if(path==='/api/admin/youtube/device/poll'){
    polls.push(request.postDataJSON());
    const result=pollKind==='connected'?{...session,status:'connected',channel_title:'Meu canal',message:'Canal conectado: Meu canal'}:pollKind==='slow'?{...session,status:'pending',interval:10,message:'Aguardando o Google.'}:pollKind==='denied'?{...session,status:'error',recovery:'auth_required',message:'O acesso foi negado. Gere outro código.'}:{...session,status:'pending',message:'Aguardando sua confirmação.'};
    if(pollKind==='connected')connected=true;
    if(holdPoll){heldPoll=()=>reply(result);return;}
    session=result;return reply(result);
   }
   if(path==='/api/admin/youtube/device/cancel'){session=null;return reply({status:'cancelled'});}
   if(path==='/api/youtube-tools/status')return reply({yt_dlp_version:'2026.10.09',source:'image',deno_version:'deno 2.6',update:{status:updating?'updating':'done',message:updating?'Atualização preparada. Aguardando downloads ativos.':'Pronto para uso.'},access:{session_state:sessionState}});
   if(path==='/api/youtube-tools/cookies'){
    if(request.method()==='DELETE'){sessionState='anonymous';return reply({session_state:sessionState});}
    cookies.push(request.postData());
    if(failCookies)return reply({detail:'Use cookies.txt no formato Netscape.'},400);
    sessionState='saved';return reply({session_state:sessionState});
   }
   if(path==='/api/youtube-tools/test')return failLink?reply({detail:'O YouTube pediu uma sessão válida. Renove a sessão.'},400):reply({title:'Vídeo teste',message:'O link foi consultado. Você pode tentar o download novamente.',access:{session_state:sessionState}});
   if(path==='/api/youtube-tools/update'){updates.push(request.method());updating=true;return reply({status:'started'});}
   return reply({});
  });
  async function advancePoll(milliseconds=5200){
   const response=page.waitForResponse(r=>r.url().endsWith('/api/admin/youtube/device/poll'));
   await page.clock.runFor(milliseconds);await response;
   await page.waitForFunction(()=>!youtubeDevicePolling);
   await page.clock.runFor(100);
  }
  await page.goto('https://external.karaoke.test');
  await page.waitForFunction(()=>currentUser?.role==='admin');
  await page.locator('#easyYoutubeUrl').fill('https://youtu.be/abcdefghijk');
  await page.locator('#tabBtnSettings').click();
  await page.waitForFunction(()=>document.getElementById('ytPublishChannel').dataset.kind==='error');
  assert((await page.locator('#ytPublishChannel').textContent()).includes('expirou'));
  assert((await page.locator('#ytPublishJobs').textContent()).includes('Aguardando reconexão'));
  assert(await page.locator('#ytDeviceSetup').evaluate(el=>el.open));
  await page.locator('#ytDeviceClientId').evaluate(el=>el.closest('details').open=true);
  await page.locator('#ytDeviceClientId').fill('tv-client');await page.locator('#ytDeviceClientSecret').fill('private-secret');
  await page.clock.runFor(5200);
  assert.equal(await page.locator('#ytDeviceClientSecret').inputValue(),'private-secret');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'ytDeviceClientSecret');
  await page.locator('#ytDeviceConfigure').click();
  await page.waitForFunction(()=>!document.getElementById('ytDevicePanel').hidden);
  assert.equal(starts[0].credentials.client_id,'tv-client');
  assert.equal(await page.locator('#ytDeviceCode').inputValue(),'ABCD-EFGH');
  assert.equal(await page.locator('#ytDeviceGoogle').getAttribute('href'),'https://www.google.com/device');
  assert.equal(await page.locator('#ytDeviceGoogle').getAttribute('target'),'_blank');
  await page.locator('#ytDevicePanel').screenshot({path:'youtube-recovery-code.png'});
  await page.locator('#ytDeviceCopy').click();assert.equal(await page.evaluate(()=>window.copiedYoutubeCode),'ABCD-EFGH');
  assert(await page.locator('#ytDeviceReconnect').isDisabled());
  await page.locator('#youtubeTestUrl').fill('https://youtu.be/abcdefghijk');await advancePoll();
  assert.equal(polls.length,1);assert.equal(await page.locator('#youtubeTestUrl').inputValue(),'https://youtu.be/abcdefghijk');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'youtubeTestUrl');
  pollKind='slow';await advancePoll();const slowedPolls=polls.length;
  await page.clock.runFor(5200);assert.equal(polls.length,slowedPolls);
  pollKind='connected';await advancePoll();
  await page.waitForFunction(()=>document.getElementById('ytPublishChannel').dataset.kind==='success');
  await page.waitForFunction(()=>!document.getElementById('ytDefaultPlaylist').disabled);
  assert.equal(await page.locator('#ytDefaultPlaylist').inputValue(),'PL-saved');
  assert(await page.locator('#ytDeviceCodeArea').evaluate(el=>el.hidden));
  assert(!(await page.locator('#ytDeviceReconnect').isDisabled()));
  pollKind='pending';await page.locator('#ytDeviceReconnect').click();await page.waitForFunction(()=>!document.getElementById('ytDeviceCodeArea').hidden);
  holdPoll=true;await page.clock.runFor(5200);await page.evaluate(()=>({polling:youtubeDevicePolling}));assert(heldPoll);
  await page.locator('#ytDeviceCancel').click();await page.waitForFunction(()=>document.getElementById('ytDevicePanel').hidden);
  holdPoll=false;await heldPoll();await page.clock.runFor(100);
  assert(await page.locator('#ytDevicePanel').evaluate(el=>el.hidden),'Canceled late response reopened code');
  pollKind='denied';await page.locator('#ytDeviceReconnect').click();await page.waitForFunction(()=>!document.getElementById('ytDeviceCodeArea').hidden);await advancePoll();
  await page.waitForFunction(()=>document.getElementById('ytDeviceMessage').dataset.kind==='error');
  assert(!(await page.locator('#ytDeviceReconnect').isDisabled()));
  await page.evaluate(()=>renderYoutubeDevice({...youtubeDeviceSession,status:'pending',message:'Old response'}));
  assert.equal(await page.locator('#ytDeviceMessage').getAttribute('data-kind'),'error');
  await page.locator('#youtubeCookiesGuide').evaluate(el=>el.open=true);
  await page.locator('#youtubeCookiesFile').setInputFiles({name:'cookies.txt',mimeType:'text/plain',buffer:Buffer.from('# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tprivate-cookie\n')});
  failCookies=true;await page.locator('#btnSaveYoutubeCookies').click();
  await page.waitForFunction(()=>document.getElementById('youtubeAccessMessage').dataset.kind==='error');
  assert.equal(await page.locator('#youtubeCookiesFile').evaluate(el=>el.files.length),1);
  failCookies=false;await page.locator('#btnSaveYoutubeCookies').click();
  await page.waitForFunction(()=>document.getElementById('youtubeAccessMessage').dataset.kind==='success');
  assert(cookies[1].includes('# Netscape HTTP Cookie File'));
  assert.equal(await page.locator('#youtubeCookiesFile').evaluate(el=>el.files.length),0);
  assert((await page.locator('#youtubeSessionStatus').textContent()).includes('Sessão salva'));
  await page.locator('#btnTestYoutubeAccess').click();await page.waitForFunction(()=>document.getElementById('youtubeAccessMessage').dataset.kind==='error');
  failLink=false;await page.locator('#btnTestYoutubeAccess').click();await page.waitForFunction(()=>document.getElementById('youtubeAccessMessage').dataset.kind==='success');
  assert((await page.locator('#youtubeAccessMessage').textContent()).includes('Vídeo teste'));
  processing=true;await page.locator('#btnUpdateYoutubeTools').click();
  await page.waitForFunction(()=>document.getElementById('btnUpdateYoutubeTools').disabled);
  assert.equal(updates.length,1);assert.equal(await page.locator('#easyYoutubeUrl').inputValue(),'https://youtu.be/abcdefghijk');
  await page.locator('#btnClearYoutubeCookies').click();await page.waitForFunction(()=>document.getElementById('youtubeAccessMessage').textContent.includes('conexão do canal foi mantida'));
  assert(connected);assert.equal(sessionState,'anonymous');
  for(const width of [320,360,390,768,1440]){
   await page.setViewportSize({width,height:1000});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);
   await page.locator('#youtubePublisherSection').scrollIntoViewIfNeeded();await page.screenshot({path:'youtube-recovery-'+width+'.png',fullPage:false});
  }
  assert.deepEqual(errors,[]);
  console.log('External mobile consent, private session controls, preserved inputs, retries, cancellation, resumed publication and responsive layout passed.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
