const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const HTML=fs.readFileSync('app/templates/index.html','utf8');
for(const match of HTML.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new Function(match[1]);
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:900},isMobile:true,hasTouch:true});
  const errors=[],writes=[],tests=[],verifications=[];
  let token='123456***oken',chat='-100123',testKind='failure',heldTest=null,holdTest=false,badSave=false;
  let delivery={state:'network_error',detail:'O servidor não consegue conectar ao Telegram. Confira a internet e o DNS do servidor.',last_delivery:{ok:false,detail:'O servidor não consegue conectar ao Telegram.',at:1791560000},last_success_at:1791559000,pending:0};
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{localStorage.setItem('karaoke_token','session');window.alert=()=>{};});
  await page.clock.install({time:new Date('2026-10-09T18:00:00Z')});
  await page.clock.pauseAt(new Date('2026-10-09T18:00:01Z'));
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.hostname!=='external.karaoke.test')return route.abort();
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:HTML});
   const reply=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
   const path=url.pathname;
   if(path==='/api/auth_status')return reply({status:'authenticated',username:'owner',role:'admin'});
   if(path==='/api/status')return reply({status:'processing',progress:45,owned_by_current_user:true,owner_username:'owner',original_filename:'Current.mp3'});
   if(path==='/api/easy-mode')return reply({enabled:true,lyrics_mode:'auto',background_mode:'original'});
   if(path==='/api/queue')return reply({jobs:[]});
   if(path==='/api/library')return reply({videos:[],photos:[],history:[]});
   if(path==='/api/users')return reply([{username:'owner',role:'admin'}]);
   if(path==='/api/admin/results')return reply({results:[]});
   if(path==='/api/youtube/publication-options')return reply({enabled:false});
   if(path==='/api/admin/youtube/status')return reply({connected:false,settings:{},jobs:[]});
   if(path==='/api/youtube-tools/status')return reply({yt_dlp_version:'2026.10.09',source:'image',access:{session_state:'anonymous'}});
   if(path==='/api/telegram'){
    if(request.method()==='POST'){
     writes.push(request.postDataJSON());
     if(badSave)return reply({detail:'Confira o Chat ID numérico completo.'},400);
     ({telegram_token:token,telegram_chat_id:chat}=request.postDataJSON());
     token='123456***oken';delivery={state:'unverified',detail:'Configuração salva. Verifique a conexão ou envie uma mensagem de teste.',pending:0};
     return reply({status:'success',detail:delivery.detail});
    }
    return reply({telegram_token:token,telegram_chat_id:chat,configured:true,delivery});
   }
   if(path==='/api/telegram/status')return reply(delivery);
   if(path==='/api/telegram/verify'){
    verifications.push(request.method());delivery={...delivery,state:'verified',detail:'Bot e destino verificados. Use Enviar mensagem de teste para confirmar a entrega.'};
    return reply({ok:true,kind:'verified',detail:delivery.detail});
   }
   if(path==='/api/telegram/test'){
    tests.push(request.method());
    const respond=()=>{
     if(testKind==='proxy')return route.fulfill({status:503,contentType:'text/html',body:'<h1>private proxy body</h1>'});
     const ok=testKind==='success';
     delivery={state:ok?'verified':'permission_denied',detail:ok?'Mensagem confirmada pelo Telegram.':'O bot está bloqueado ou sem permissão neste destino. Permita mensagens e vídeos no grupo.',last_delivery:{ok,at:1791560030,detail:ok?'Mensagem confirmada pelo Telegram.':'O bot está sem permissão.'},pending:0};
     return reply({ok,kind:ok?'delivered':'permission_denied',detail:delivery.detail});
    };
    if(holdTest){heldTest=respond;return;}
    return respond();
   }
   if(path.includes('models')||path.includes('profiles'))return reply([]);
   return reply({});
  });
  await page.goto('https://external.karaoke.test');
  await page.waitForFunction(()=>currentUser?.username==='owner');
  await page.locator('#tabBtnSettings').click();
await page.locator('#telegramSection > summary').click();
  await page.locator('#telegramSection').scrollIntoViewIfNeeded();
  assert((await page.locator('#telegramConfiguredBadge').textContent()).includes('Configuração salva'));
  assert(!(await page.locator('#telegramConfiguredBadge').textContent()).includes('ativo'));
  assert((await page.locator('#telegramDeliveryStatus').textContent()).includes('DNS'));
  assert((await page.locator('#telegramDeliveryStatus').textContent()).includes('Última entrega confirmada'));
  assert.strictEqual(tests.length,0);
  await page.locator('#btnVerifyTelegram').click();
  await page.waitForFunction(()=>document.getElementById('telegramFeedback').textContent.includes('verificados'));
  assert.deepStrictEqual(verifications,['POST']);assert.strictEqual(tests.length,0);
  holdTest=true;
  await page.locator('#btnTestTelegram').click();
  await page.waitForFunction(()=>document.getElementById('btnTestTelegram').disabled);
  assert(await page.locator('#btnEditTelegram').isDisabled());
  assert(await page.locator('#btnVerifyTelegram').isDisabled());
  await page.evaluate(()=>document.getElementById('btnTestTelegram').click());
  while(!heldTest)await new Promise(resolve=>setTimeout(resolve,10));
  assert.strictEqual(tests.length,1);
  await heldTest();holdTest=false;
  await page.waitForFunction(()=>!document.getElementById('btnTestTelegram').disabled);
  assert((await page.locator('#telegramFeedback').textContent()).includes('permissão'));
  assert((await page.locator('#telegramDeliveryStatus').textContent()).includes('não confirmado'));
  await page.locator('#telegramSection').screenshot({path:'telegram-delivery-error.png'});
  await page.locator('#btnEditTelegram').click();
  await page.locator('#telegramChatIdInput').fill('-100999');
  await page.locator('#telegramTokenInput').focus();
  await page.locator('#telegramTokenInput').evaluate(element=>element.setSelectionRange(1,4));
  assert(await page.locator('#btnTestTelegram').isDisabled());
  assert(await page.locator('#btnVerifyTelegram').isDisabled());
  await page.clock.runFor(11000);
  assert.strictEqual(await page.locator('#telegramChatIdInput').inputValue(),'-100999');
  assert.strictEqual(await page.evaluate(()=>document.activeElement.id),'telegramTokenInput');
  assert.deepStrictEqual(await page.locator('#telegramTokenInput').evaluate(element=>[element.selectionStart,element.selectionEnd]),[1,4]);
  badSave=true;await page.locator('#btnSaveTelegram').click();
  await page.waitForFunction(()=>document.getElementById('telegramFeedback').textContent.includes('Confira'));
  assert.strictEqual(await page.locator('#telegramChatIdInput').inputValue(),'-100999');
  assert(await page.locator('#btnTestTelegram').isDisabled());
  badSave=false;await page.locator('#btnSaveTelegram').click();
  await page.waitForFunction(()=>document.getElementById('telegramInputsDiv').style.display==='none');
  assert.strictEqual(writes.at(-1).telegram_chat_id,'-100999');
  testKind='proxy';await page.locator('#btnTestTelegram').click();
  await page.waitForFunction(()=>document.getElementById('telegramFeedback').textContent.includes('503'));
  assert(!(await page.locator('#telegramFeedback').textContent()).includes('private proxy body'));
  testKind='success';await page.locator('#btnTestTelegram').click();
  await page.waitForFunction(()=>document.getElementById('telegramFeedback').textContent.includes('Mensagem de teste enviada'));
  await page.waitForFunction(()=>document.getElementById('telegramDeliveryStatus').textContent.includes('Último envio confirmado'));
  assert((await page.locator('#telegramDeliveryStatus').textContent()).includes('Último envio confirmado'));
  for(const width of [320,360,390,768,1440]){
   await page.setViewportSize({width,height:900});
   await page.locator('#telegramSection').scrollIntoViewIfNeeded();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'overflow at '+width);
   await page.locator('#telegramSection').screenshot({path:'telegram-delivery-'+width+'.png'});
  }
  assert.deepStrictEqual(errors,[]);console.log('Telegram status, safe test, retry, editing/focus and five layouts passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
