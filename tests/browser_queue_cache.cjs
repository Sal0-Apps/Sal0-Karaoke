const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();
for (const match of HTML.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new Function(match[1]);
(async () => {
 const browser = await chromium.launch({headless:true});
 try {
  const page = await browser.newPage({viewport:{width:390,height:900},isMobile:true,hasTouch:true});
  const errors=[], requests=[], submissions=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>{errors.push(d.message());d.dismiss();});
  await page.addInitScript(()=>localStorage.setItem('karaoke_token','test-session'));
  const seg = [{start:10,end:13,text:'Letra A',words:[{word:'Letra ',start:10.2,end:10.5},{word:'A',start:11.7,end:12.5}]}];
  const options = {whisper_model:'medium',font_size:41,text_color:'#00FFFF',text_position:'bottom',subtitle_mode:'word',background_mode:'original',lyrics_mode:'manual',lyrics_text:'Guia A',lyrics_selected:true,enable_correction:false,keep_backing_vocals:true,backing_vocals_volume:100,youtube_publish:true,transcription_preset:'karaoke',youtube_extra_playlists:false};
  const jobs = [{id:'A',title:'Canção A',status:'done',can_reprocess:true,has_segments:true}, {id:'B',title:'Canção B',status:'error',can_reprocess:true,has_segments:true}, {id:'S',title:'Vídeo para legendar',status:'done',can_reprocess:true,has_segments:true,subtitle_only:true}, {id:'C',title:'Canção C',status:'processing',can_reprocess:false,has_segments:false}];
  let saved = structuredClone(seg);
  const publicationOptions = {enabled:true,can_publish:true,default_publish:true,can_choose_playlist:true,playlist_id:'PL-profile',privacy:'unlisted',channel_title:'Canal',playlists:[{id:'PL-profile',title:'Do perfil'},{id:'PL-extra1',title:'Extras 1'},{id:'PL-extra2',title:'Extras 2'}],additional_playlists:[{id:'PL-profile',title:'Do perfil'},{id:'PL-extra1',title:'Extras 1'},{id:'PL-extra2',title:'Extras 2'}]};
  await page.route('**/*', async route=>{
   const req=route.request(),u=new URL(req.url());
   if(u.hostname!=='karaoke.test') return route.abort();
   if(u.pathname==='/') return route.fulfill({contentType:'text/html',body:HTML});
   if(u.pathname==='/favicon.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync('app/templates/app-icon-v8.png')});
   const fulfill=d=>route.fulfill({contentType:'application/json',body:JSON.stringify(d)});
   requests.push({path:u.pathname,method:req.method(),body:req.postData(),query:u.search});
   if(u.pathname==='/api/auth_status')return fulfill({status:'authenticated',username:'owner',role:'admin'});
   if(u.pathname==='/api/status')return fulfill({status:'processing',step:'Transcribing vocals',progress:60,can_cancel:true,process_summary:{title:'Canção C',mode:'Modo Detalhado'}});
   if(u.pathname==='/api/queue')return fulfill({jobs:[{id:'C',status:'processing',title:'Canção C'}],paused:false});
   if(u.pathname==='/api/queue-cache')return fulfill({jobs});
   if(u.pathname.match(/^\/api\/queue-cache\/[ABS]$/)){
    const id=u.pathname.split('/').at(-1),job=jobs.find(j=>j.id===id);
    return fulfill({...job,options:id==='S'?{...options,subtitle_only:true,translation_language:'original',subtitle_settings:{font_size:24,text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,text_position:'bottom',video_subtitle_source:'original',background_color:'#101827'}}:options,segments:id==='A'?saved:seg,publication:id==='A'?{video_id:'oldVideo001',url:'https://youtu.be/oldVideo001'}:null});
   }
   if(u.pathname==='/api/queue-cache/A/segments'){saved=JSON.parse(req.postData()).segments;return fulfill({status:'saved',segments:saved});}
   if(u.pathname==='/api/queue-cache/A/reprocess')return fulfill({status:'queued',job_id:'revision-A',position:1});
   if(u.pathname==='/api/process'){submissions.push(req.postData());return fulfill({status:'queued',job_id:'new-'+submissions.length,position:1});}
   if(u.pathname==='/api/cache_info')return fulfill({has_cache:!!u.searchParams.get('job_id'),bg_is_video:false});
   if(u.pathname==='/api/youtube/publication-options')return fulfill(publicationOptions);
   if(u.pathname==='/api/youtube/additional-playlists')return fulfill({playlists:publicationOptions.playlists});
   if(u.pathname==='/api/easy-mode')return fulfill({enabled:true,whisper_model:'medium',font_size:41,background_mode:'original',lyrics_mode:'manual',keep_backing_vocals:true});
   if(u.pathname==='/api/subtitle-mode')return fulfill({font_size:24,text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,text_position:'bottom',video_subtitle_source:'translated',background_color:'#101827'});
   if(u.pathname==='/api/library')return fulfill({videos:[],photos:[],history:[],audio:[],backgrounds:[]});
   return fulfill({});
  });
  await page.goto('http://karaoke.test');
  await page.waitForFunction(()=>currentUser && document.querySelectorAll('.queue-cache-row').length===4);
  assert.equal(await page.locator('#queueCacheCard').evaluate(e=>e.open),false);
  assert.equal(await page.locator('#easyYoutubeExtras').isChecked(),false);
  await page.locator('#queueCacheCard summary').click();
  assert.equal(await page.locator('[data-cache-id="C"] button').first().isDisabled(),true);
  await page.locator('[data-cache-id="A"]').getByRole('button',{name:'Editar legendas',exact:true}).click();
  await page.locator('#correctionCard textarea').first().fill('Letra corrigida A');
  await page.evaluate(async()=>{await fetchStatus();await fetchProcessingQueue();});
  assert.equal(await page.locator('#correctionCard textarea').first().inputValue(),'Letra corrigida A');
  assert.equal(await page.locator('#processCard').isVisible(),false);
  await page.locator('#cachedEditorSave').click();
  await page.waitForFunction(()=>document.getElementById('correctionValidationMessage').textContent==='Alterações salvas nesta execução.');
  assert.equal(saved[0].text,'Letra corrigida A');
  assert(requests.some(r=>r.path==='/api/cache_info' && r.query.includes('job_id=A')));
  await page.locator('#btnContinueProcess').click();
  await page.waitForFunction(()=>!window.cacheEditorActive);
  assert(!requests.some(r=>r.method==='POST' && ['/api/continue_process','/api/skip_edit','/api/cancel'].includes(r.path)));
  await page.locator('[data-cache-id="A"]').getByRole('button',{name:'Refazer no Rápido',exact:true}).click();
  await page.locator('#easyModeForm').waitFor({state:'visible'});
  assert.equal(await page.locator('#cachedReplaceYoutube').isChecked(),true);
  assert.equal(await page.locator('#easyYoutubePlaylist').isDisabled(),true);
  assert.equal(await page.locator('#easyYoutubePlaylist').inputValue(),'PL-profile');
  assert.equal(await page.locator('#easyYoutubeExtras').isChecked(),false);
  await page.locator('#easyYoutubeExtras').check();
  await page.locator('#easyYoutubeExtraList').getByLabel('Extras 1').check();
  await page.locator('#easyYoutubeExtraList').getByLabel('Extras 2').check();
  await page.locator('#easySubmitBtn').click();
  await page.waitForFunction(()=>!window.cachedRevisionId);
  const value=(body,name)=>body.match(new RegExp('name="'+name+'"\\r?\\n\\r?\\n([^\\r\\n]*)'))?.[1];
  assert.equal(value(submissions[0],'cache_job_id'),'A');assert.equal(value(submissions[0],'easy_mode'),'true');
  assert.equal(value(submissions[0],'youtube_replace_previous'),'true');
  assert.deepEqual(JSON.parse(value(submissions[0],'youtube_additional_playlists')),['PL-extra1','PL-extra2']);
  assert.equal(await page.locator('#easyYoutubeExtras').isChecked(),false);
  await page.locator('[data-cache-id="A"]').getByRole('button',{name:'Refazer no Detalhado',exact:true}).click();
  await page.locator('#karaokêForm').waitFor({state:'visible'});
  assert.equal(await page.locator('[name="font_size"]').inputValue(),'41');
  if(!await page.locator('#advancedContent').isVisible())await page.locator('#btnToggleAdvanced').click();
  await page.locator('[name="font_size"]').fill('48');
  await page.locator('#btnSubmit').click();
  await page.waitForFunction(()=>!window.cachedRevisionId);
  assert.equal(value(submissions[1],'cache_job_id'),'A');assert.equal(value(submissions[1],'font_size'),'48');
  assert.equal(value(submissions[1],'youtube_extra_playlists'),'false');
  await page.locator('[data-cache-id="S"]').getByRole('button',{name:'Rever ajustes',exact:true}).click();
  await page.locator('[data-subtitle-field="font_size"]').fill('44');
  await page.locator('#subtitleSubmitBtn').click();
  await page.waitForFunction(()=>!window.cachedRevisionId);
  assert.equal(value(submissions[2],'subtitle_only'),'true');assert.equal(JSON.parse(value(submissions[2],'subtitle_settings_json')).font_size,44);
  await page.locator('[data-cache-id="B"]').getByRole('button',{name:'Refazer no Detalhado',exact:true}).click();
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:900});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Overflow at ${width}`);
   await page.screenshot({path:`queue-cache-${width}.png`,fullPage:true});
  }
  assert.deepEqual(errors,[]);
  console.log('Queue retention UI, independent review, Quick/Detailed/SRT replay, replacement and optional multiple playlists passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
