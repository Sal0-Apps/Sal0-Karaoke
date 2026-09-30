const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const HTML=fs.readFileSync('app/templates/index.html','utf8');
for(const match of HTML.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new Function(match[1]);
(async()=>{
const browser=await chromium.launch({headless:true});const page=await browser.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
let connected=false,failImport=true,failPlaylists=false,saved=null;
await page.route('**/*',async route=>{
 const request=route.request(),u=new URL(request.url());if(u.hostname!=='karaoke.test')return route.abort();
 if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:HTML});
 let data={},status=200;
 if(u.pathname==='/api/auth_status')data={status:'authenticated',username:'owner',role:'admin'};
 if(u.pathname==='/api/status')data={status:'idle',progress:0,result_available_to_current_user:false};
 if(u.pathname==='/api/easy-mode')data={enabled:true,whisper_model:'medium',background_mode:'random_library',random_backgrounds:[],lyrics_mode:'auto'};
 if(u.pathname==='/api/youtube/publication-options')data={enabled:false,playlists:[],default_publish:false};
 if(u.pathname==='/api/users')data=[{username:'owner',role:'admin'},{username:'alice',role:'user'},{username:'bob',role:'user'}];
 if(u.pathname==='/api/admin/results')data={results:[]};
 if(u.pathname==='/api/library')data={audio:[],backgrounds:[],history:[],videos:[],photos:[]};
 if(u.pathname==='/api/processing-queue')data={jobs:[]};
 if(u.pathname==='/api/admin/youtube/status')data={configured:true,web_configured:false,connected,channel_title:'Canal teste',jobs:[],settings:{privacy:'private',playlist_id:'',title_template:'{title} | Karaokê',users_can_publish:true,user_assignments:{alice:{enabled:true,playlist_id:'PL-one',default_publish:false}}}};
 if(u.pathname==='/api/admin/youtube/import-authorization'){
  await new Promise(r=>setTimeout(r,350));
  if(failImport){status=400;data={detail:'Ative a YouTube Data API v3 no mesmo projeto Google da credencial.'}}
  else{connected=true;data={channel_title:'Canal teste'}}
 }
 if(u.pathname==='/api/admin/youtube/playlists'){
  if(failPlaylists){status=400;data={detail:'YouTube: quotaExceeded (HTTP 403).'}}
  else data={playlists:[{id:'PL-one',title:'Playlist Alice'},{id:'PL-two',title:'Playlist Bob'}]};
 }
 if(u.pathname==='/api/admin/youtube/settings'){saved=request.postDataJSON();data={status:'saved'};}
 return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
});
await page.goto('http://karaoke.test');await page.locator('#tabBtnSettings').click();
await page.locator('.yt-user-row').first().waitFor();
assert.equal(await page.locator('.yt-user-row').count(),2);
assert(await page.locator('#yt-user-playlist-0').isDisabled());
await page.locator('#ytDesktopAuthorization').setInputFiles({name:'youtube-autorizacao.json',mimeType:'application/json',buffer:Buffer.from('{}')});
await page.locator('#ytDesktopImport').click();
assert(await page.locator('#ytDesktopImport').isDisabled());
await page.waitForFunction(()=>document.getElementById('ytConnectionMessage').dataset.kind==='error');
assert((await page.locator('#ytConnectionMessage').textContent()).includes('Ative a YouTube Data API'));
assert(await page.locator('#ytConnectionMessage').isVisible());
failImport=false;
await page.locator('#ytDesktopImport').click();
await page.waitForFunction(()=>document.getElementById('ytPublishChannel').textContent.includes('✓ Canal conectado'));
await page.waitForFunction(()=>document.querySelectorAll('#yt-user-playlist-0 option').length===3);
assert(await page.locator('#ytPublishChannel').isVisible());
assert.equal(await page.locator('#yt-user-playlist-0').inputValue(),'PL-one');
const bob=page.locator('.yt-user-row').filter({hasText:'bob'});
await bob.locator('[data-field="enabled"]').check();
await bob.locator('[data-field="playlist"]').selectOption('PL-two');
await bob.locator('[data-field="default"]').check();
await page.locator('.yt-defaults summary').click();
await page.locator('#ytDefaultPrivacy').selectOption('unlisted');
await page.locator('#ytPublishSave').click();
await page.waitForFunction(()=>document.getElementById('ytUsersMessage').dataset.kind==='success');
assert.equal(saved.privacy,'unlisted');assert.equal(saved.user_assignments.bob.playlist_id,'PL-two');
assert.equal(saved.user_assignments.bob.enabled,true);assert.equal(saved.user_assignments.bob.default_publish,true);
for(const width of [360,390,768,1440]){
 await page.setViewportSize({width,height:1000});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);
 const boxes=await page.evaluate(()=>({panel:document.getElementById('youtubePublisherSection').getBoundingClientRect().width,grid:document.querySelector('.settings-grid').getBoundingClientRect().width}));
 assert(Math.abs(boxes.panel-boxes.grid)<2);
 await page.screenshot({path:'youtube-admin-'+width+'.png',fullPage:false});
}
failPlaylists=true;await page.locator('#ytPublishRefresh').click();
await page.waitForFunction(()=>document.getElementById('ytPlaylistStatus').dataset.kind==='error');
assert.equal(await page.locator('.yt-user-row').count(),2);
assert((await page.locator('#ytPublishChannel').textContent()).includes('Canal conectado'));
assert(await page.locator('#ytPublishSave').isDisabled());
assert.equal(errors.length,0,JSON.stringify(errors));
console.log('Connection error and success visible; user playlists persist; playlist failure isolated; mobile/desktop passed.');
await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
