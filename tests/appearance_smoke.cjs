/* Shipped styles/controller: native header, themes, scrolling and cycle boundaries. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
let js,css,base;
if(fs.existsSync(path.join(root,'app/static/appearance.js'))){
 js=fs.readFileSync(path.join(root,'app/static/appearance.js'),'utf8');css=fs.readFileSync(path.join(root,'app/static/appearance.css'),'utf8');base=fs.readFileSync(path.join(root,'app/static/style.css'),'utf8');
}else{
 const html=fs.readFileSync(path.join(root,'app/templates/index.html'),'utf8');
 js=html.slice(html.indexOf('/* Sal0 native themes:')).split('</script>')[0];css=html.slice(html.indexOf('/* Sal0 glass themes.')).split('</style>')[0];base=html.split('<style>')[1].split('/* Sal0 glass themes.')[0];
}
const config=JSON.parse(js.match(/const config = (\{[^\n]+\});/)[1]);
const native=`const c=${JSON.stringify(config)};function apply(m){document.documentElement.dataset.theme=m;if(c.source==='body')document.body.classList.toggle('light',m==='light');localStorage.setItem(c.key,m);}apply(localStorage.getItem(c.key)||'dark');document.getElementById(c.button).onclick=()=>apply(document.documentElement.dataset.theme==='light'?'dark':'light');`;
const queue=config.source==='body'?'<button id="queue-toggle">Fila</button>':'<span class="user-chip">VictorSal0</span>';
const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/base.css"><link rel="stylesheet" href="/appearance.css"><script defer src="/native.js"></script><script defer src="/appearance.js"></script></head><body><div class="container app-container"><header class="app-header"><div class="logo-area"><h1>Sal0 ${config.source==='body'?'Voz':'Karaokê'}</h1></div><div class="header-actions">${queue}<button class="header-btn" id="${config.button}" type="button">Claro/escuro</button><button class="header-btn" id="manual">Manual</button><button class="header-btn" id="logout">Sair</button></div></header><div class="card">Conteúdo estável durante a animação</div></div></body></html>`;
const files={'/':[html,'text/html'],'/appearance.js':[js,'text/javascript'],'/appearance.css':[css,'text/css'],'/native.js':[native,'text/javascript'],'/base.css':[base+'\n.card{margin:30px 0;min-height:2200px;background:rgb(22,33,44)}','text/css']};
(async()=>{
 const server=http.createServer((req,res)=>{const [data,mime]=files[req.url]||['','text/plain'];res.setHeader('Content-Type',mime);res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:");res.end(data);});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try{
  browser=await chromium.launch({headless:true,...(process.env.SAL0_BROWSER_EXECUTABLE?{executablePath:process.env.SAL0_BROWSER_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const screenshots=path.join(root,'test-artifacts/appearance');fs.mkdirSync(screenshots,{recursive:true});
  for(const width of [320,390,691,820,1440]){
   await page.setViewportSize({width,height:844});
   assert.equal(await page.locator('.sal0-theme-launcher').count(),1);
   assert.equal(await page.locator('.header-actions button').count(),config.source==='body'?4:3);
   const theme=await page.locator('#'+config.button).boundingBox(),manual=await page.locator('#manual').boundingBox();
   assert.equal(await page.locator('#'+config.button+' span').innerText(),'Temas');assert(theme.height>=44);assert(Math.abs(theme.height-manual.height)<=1);assert(Math.abs(theme.y-manual.y)<=1);
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));
  }
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(screenshots,'mobile-dark.png')});
  await page.getByRole('button',{name:'Escolher tema visual',exact:true}).click();
  assert.equal(await page.locator('html').getAttribute('data-sal0-mode'),'dark','Opening the menu must not toggle the native color mode');
  await page.getByRole('radio',{name:'Tema antigo',exact:false}).click();assert.equal(await page.locator('#sal0-scene').evaluate(e=>getComputedStyle(e).display),'none');assert.equal(await page.locator('.card').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(22, 33, 44)');
  for(const name of ['Cristal','Aurora','Wall']){await page.getByRole('radio',{name,exact:false}).click();assert(await page.locator('#sal0-scene').isVisible());}
  await page.getByRole('button',{name:'Claro',exact:true}).click();assert.equal(await page.locator('html').getAttribute('data-sal0-mode'),'light');assert.equal(await page.locator('meta[name="color-scheme"]').getAttribute('content'),'only light');
  assert.equal(await page.locator('#'+config.button+' span').innerText(),'Temas');
  await page.getByRole('switch',{name:'Animações suaves',exact:false}).uncheck();assert.equal(await page.locator('#sal0-scene').getAttribute('data-paused'),'true');await page.getByRole('switch',{name:'Animações suaves',exact:false}).check();await page.getByRole('button',{name:'Fechar temas',exact:true}).click();
  const cycle=await page.evaluate(()=>{
   const scene=document.querySelector('#sal0-scene'),card=document.querySelector('.card'),header=document.querySelector('header');
   const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]};const before=[rect(card),rect(header)];
   const results=scene.getAnimations({subtree:true}).map(animation=>{
    const effect=animation.effect,timing=effect.getTiming();animation.pause();animation.currentTime=timing.duration-1;const a=new DOMMatrix(getComputedStyle(effect.target).transform).toFloat64Array();animation.currentTime=timing.duration+1;const b=new DOMMatrix(getComputedStyle(effect.target).transform).toFloat64Array();animation.play();
    return {direction:timing.direction,jump:Math.max(...a.map((v,i)=>Math.abs(v-b[i]))),backgroundOnly:scene.contains(effect.target)};
   });
   return {morphs:scene.querySelectorAll('animate,animateTransform').length,results,before,after:[rect(card),rect(header)]};
  });
  assert.equal(cycle.morphs,0);assert(cycle.results.length>=2);assert.deepEqual(cycle.before,cycle.after);
  for(const item of cycle.results){assert.equal(item.direction,'alternate');assert(item.backgroundOnly);assert(item.jump<.01,'Cycle boundary must be continuous');}
  await page.evaluate(()=>window.appearanceScene=document.querySelector('#sal0-scene'));const before=await page.locator('#sal0-scene').boundingBox();await page.evaluate(()=>scrollTo(0,1000));await page.waitForFunction(()=>scrollY>0);const after=await page.locator('#sal0-scene').boundingBox();assert.equal(after.y,0);assert.equal(before.height,after.height);assert(await page.evaluate(()=>appearanceScene===document.querySelector('#sal0-scene')));
  await page.reload();await page.waitForSelector('#sal0-scene');assert.equal(await page.locator('html').getAttribute('data-sal0-look'),'wall');assert.equal(await page.locator('html').getAttribute('data-sal0-mode'),'light');await page.screenshot({path:path.join(screenshots,'mobile-light.png')});assert.deepEqual(errors,[]);
  console.log('Appearance OK: single labeled header control, native modes, legacy, persistence, motion boundaries, fixed content and stable scrolling under CSP.');
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
