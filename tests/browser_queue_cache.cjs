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
  const options = {whisper_model:'medium',font_size:41,text_color:'#123456',text_position:'top',subtitle_mode:'line',background_mode:'image',background_filename:'Fundo A.png',audio_filename:'Canção A.mp4',lyrics_mode:'manual',lyrics_text:'Guia A',lyrics_selected:true,enable_correction:true,keep_backing_vocals:false,backing_vocals_volume:37,youtube_publish:true,youtube_title:'Título anterior',transcription_preset:'continuous',youtube_extra_playlists:false,words_per_line:4,max_chars_line:22,show_instrumental:false,transcribe_source:'vocals',show_next_line_preview:true,keep_first_line_visible:true,save_to_library:false,only_remove_vocals:false,break_on_punctuation:false,lyrics_timing:'acoustic'};
  const jobs = [{id:'A',title:'Canção A',status:'done',can_reprocess:true,has_segments:true}, {id:'B',title:'Canção B',status:'error',can_reprocess:true,has_segments:true}, {id:'S',title:'Vídeo para legendar',status:'done',can_reprocess:true,has_segments:true,subtitle_only:true}, {id:'C',title:'Canção C',status:'processing',can_reprocess:false,has_segments:false}];
  let saved = structuredClone(seg);
  let serverStatus={status:'processing',step:'Transcribing vocals',progress:60,can_cancel:true,process_summary:{title:'Canção C',mode:'Modo Detalhado'}};
  const publicationOptions = {enabled:true,can_publish:true,default_publish:false,can_choose_playlist:true,playlist_id:'PL-profile',privacy:'unlisted',channel_title:'Canal',playlists:[{id:'PL-profile',title:'Do perfil'},{id:'PL-extra1',title:'Extras 1'},{id:'PL-extra2',title:'Extras 2'}],additional_playlists:[{id:'PL-profile',title:'Do perfil'},{id:'PL-extra1',title:'Extras 1'},{id:'PL-extra2',title:'Extras 2'}]};
  let releaseStatus, releaseConfig, releasePreview, releaseSegments;
  const statusGate=new Promise(resolve=>releaseStatus=resolve), configGate=new Promise(resolve=>releaseConfig=resolve), previewGate=new Promise(resolve=>releasePreview=resolve), segmentsGate=new Promise(resolve=>releaseSegments=resolve);
  await page.route('**/*', async route=>{
   const req=route.request(),u=new URL(req.url());
   if(u.hostname!=='karaoke.test') return route.abort();
   if(u.pathname==='/') return route.fulfill({contentType:'text/html',body:HTML});
   if(u.pathname==='/favicon.png') return route.fulfill({contentType:'image/png',body:fs.readFileSync('app/templates/app-icon-v8.png')});
   const fulfill=d=>route.fulfill({contentType:'application/json',body:JSON.stringify(d)});
   requests.push({path:u.pathname,method:req.method(),body:req.postData(),query:u.search});
   if(u.pathname==='/api/auth_status')return fulfill({status:'authenticated',username:'owner',role:'admin'});
   if(u.pathname==='/api/status'){await statusGate;return fulfill(serverStatus);}
   if(u.pathname==='/api/queue'){assert.equal(u.searchParams.get('include_completed'),'true');return fulfill({jobs,paused:false});}
   if(u.pathname==='/api/queue-cache')throw new Error('The separate queue panel should not be fetched.');
   if(u.pathname.match(/^\/api\/queue-cache\/[ABS]$/)){
    assert.equal(u.searchParams.get('include_segments'),'false');
    const id=u.pathname.split('/').at(-1),job=jobs.find(j=>j.id===id);
    return fulfill({...job,options:id==='S'?{...options,subtitle_only:true,translation_language:'original',subtitle_settings:{font_size:24,text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,text_position:'bottom',video_subtitle_source:'original',background_color:'#101827'}}:options,publication:id==='A'?{video_id:'oldVideo001',url:'https://youtu.be/oldVideo001'}:null});
   }
   if(u.pathname==='/api/queue-cache/A/segments'){
    if(req.method()==='GET'){await segmentsGate;return fulfill({title:'Canção A',can_reprocess:true,segments:saved});}
    saved=JSON.parse(req.postData()).segments;return fulfill({status:'saved',segments:saved});
   }
   if(u.pathname==='/api/queue-cache/A/reprocess')return fulfill({status:'queued',job_id:'revision-A',position:1});
   if(u.pathname==='/api/process'){submissions.push(req.postData());return fulfill({status:'queued',job_id:'new-'+submissions.length,position:1});}
   if(u.pathname==='/api/cache_info'){if(u.searchParams.get('job_id'))await previewGate;return fulfill({has_cache:!!u.searchParams.get('job_id'),bg_is_video:false});}
   if(u.pathname==='/api/youtube/publication-options'){await configGate;return fulfill(publicationOptions);}
   if(u.pathname==='/api/youtube/additional-playlists')return fulfill({playlists:publicationOptions.playlists});
   if(u.pathname==='/api/easy-mode'){await configGate;return fulfill({enabled:true,whisper_model:'tiny',font_size:50,background_mode:'random_library',lyrics_mode:'auto',keep_backing_vocals:true});}
   if(u.pathname==='/api/profiles'){await configGate;return fulfill({'Karaokê equilibrado':{whisper_model:'tiny',font_size:50,background_mode:'color',lyrics_mode:'auto'}});}
   if(u.pathname==='/api/subtitle-mode')return fulfill({font_size:24,text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,text_position:'bottom',video_subtitle_source:'translated',background_color:'#101827'});
   if(u.pathname==='/api/library')return fulfill({videos:[],photos:[],history:[],audio:[],backgrounds:[]});
   return fulfill({});
  });
  await page.goto('http://karaoke.test');
  await page.waitForFunction(()=>currentUser && document.querySelectorAll('#processingQueueList .queue-item').length===4);
  assert.equal(await page.locator('#queueCacheCard').count(),0);
  assert.equal(await page.evaluate(()=>queueStatusLabel({status:'cancelled',cancel_requested:true})),'Cancelado');
  assert(await page.locator('#queueCard').isVisible());
  // The queue must arrive while status/profile/configuration requests are still blocked.
  releaseStatus();
  assert.equal(await page.locator('#easyYoutubeExtras').isChecked(),false);
  assert.equal(await page.locator('[data-cache-id="C"] button').first().isDisabled(),true);
  await page.locator('[data-cache-id="A"]').locator('[data-queue-action=edit]').click();
  await page.getByText('Carregando as legendas desta execução…',{exact:true}).waitFor();
  assert(await page.locator('#btnContinueProcess').isDisabled());
  releaseSegments();
  await page.locator('#correctionCard textarea').first().fill('Letra corrigida A');
  assert.equal(requests.filter(r=>r.path==='/api/queue-cache/A/segments'&&r.method==='GET').length,1);
  assert.equal(requests.filter(r=>r.path==='/api/queue-cache/A').length,0);
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
  await page.locator('[data-cache-id="A"]').locator('[data-queue-action=quick]').click();
  await page.locator('#easyModeForm').waitFor({state:'visible'});
  assert.equal(await page.locator('#easyKeepBackingVocals').inputValue(),'false');
  assert.equal(await page.locator('#easyBackingVolume').inputValue(),'37');
  assert.equal(await page.locator('#lyricsText').inputValue(),'Guia A');
  assert.equal(await page.locator('#lyricsText').isDisabled(),false);
  assert.equal(await page.locator('#easyBackgroundType').inputValue(),'default');
  assert((await page.locator('#easyDefaultBackgroundOption').textContent()).includes('Fundo A.png'));
  assert((await page.locator('#easySelectedMusic').textContent()).includes('Canção A'));
  await page.locator('#btnToggleLyrics').click();
  await page.locator('#lyricsText').fill('Guia corrigida no rápido');
  releaseConfig();
  await page.waitForFunction(()=>easyModeConfig?.font_size===50&&allProfiles['Karaokê equilibrado']&&document.getElementById('easyYoutubePlaylist').value==='PL-profile');
  assert((await page.locator('#easySummaryFont').textContent()).includes('41'));
  assert.equal(await page.locator('#easyYoutubePublish').isChecked(),true);
  assert.equal(await page.locator('#lyricsText').inputValue(),'Guia corrigida no rápido');
  assert.equal(await page.locator('#easyYoutubeTitle').inputValue(),'Título anterior');
  assert((await page.locator('#easyDefaultBackgroundOption').textContent()).includes('Fundo A.png'));
  releasePreview();
  await page.waitForTimeout(50);
  assert.equal(await page.locator('#previewBgImage').getAttribute('src'),null);
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
  assert.equal(value(submissions[0],'font_size'),'41');assert.equal(value(submissions[0],'text_color'),'#123456');
  assert.equal(value(submissions[0],'background_mode'),'image');assert.equal(value(submissions[0],'save_to_library'),'false');
  assert.equal(value(submissions[0],'words_per_line'),'4');assert.equal(value(submissions[0],'lyrics_text'),'Guia corrigida no rápido');
  assert.deepEqual(JSON.parse(value(submissions[0],'youtube_additional_playlists')),['PL-extra1','PL-extra2']);
  assert.equal(await page.locator('#easyYoutubeExtras').isChecked(),false);
  await page.locator('[data-cache-id="A"]').locator('[data-queue-action=detail]').click();
  await page.locator('#karaokêForm').waitFor({state:'visible'});
  assert.equal(await page.locator('[name="font_size"]').inputValue(),'41');
  for(const [name,expected] of Object.entries({whisper_model:'medium',text_color:'#123456',text_position:'top',subtitle_mode:'line',background_mode:'image',transcription_preset:'continuous',words_per_line:'4',max_chars_line:'22',show_instrumental:'false',transcribe_source:'vocals',show_next_line_preview:'true',keep_first_line_visible:'true',save_to_library:'false',enable_correction:'true',keep_backing_vocals:'false',backing_vocals_volume:'37',break_on_punctuation:'false'}))assert.equal(await page.locator(`[name="${name}"]`).inputValue(),expected,name);
  assert.equal(await page.locator('#lyricsText').inputValue(),'Guia A');
  assert((await page.locator('#bgTextName').textContent()).includes('Fundo A.png'));
  await page.locator('#lyricsText').fill('Guia corrigida no detalhado');
  if(!await page.locator('#advancedContent').isVisible())await page.locator('#btnToggleAdvanced').click();
  await page.locator('[name="font_size"]').fill('48');
  await page.locator('#btnSubmit').click();
  await page.waitForFunction(()=>!window.cachedRevisionId);
  assert.equal(value(submissions[1],'cache_job_id'),'A');assert.equal(value(submissions[1],'font_size'),'48');
  assert.equal(value(submissions[1],'youtube_extra_playlists'),'false');
  assert.equal(value(submissions[1],'lyrics_text'),'Guia corrigida no detalhado');
  await page.locator('[data-cache-id="S"]').locator('[data-queue-action=detail]').click();
  await page.waitForFunction(()=>window.cachedRevisionId==='S'&&!document.getElementById('cachedSubtitleStyle').hidden);
  assert.equal(await page.locator('#subtitleSaveLibrary').inputValue(),'false');
  await page.locator('[data-subtitle-field="font_size"]').fill('44');
  await page.locator('#subtitleSubmitBtn').click();
  await page.waitForFunction(()=>!window.cachedRevisionId);
  assert.equal(value(submissions[2],'subtitle_only'),'true');assert.equal(JSON.parse(value(submissions[2],'subtitle_settings_json')).font_size,44);
  assert.equal(await page.locator('[data-cache-id="S"] [data-queue-action=quick]').count(),0);
  serverStatus={status:'done',progress:100,can_cancel:false};
  jobs.forEach(j=>{j.status='done';j.can_reprocess=true;j.has_segments=true;});
  await page.evaluate(async()=>{await fetchStatus();await fetchProcessingQueue();});
  assert(await page.locator('#queueCard').isVisible());
  assert.equal(await page.locator('#processingQueueList .queue-item').count(),4);
  assert.equal(await page.locator('#queueCountBadge').textContent(),'4 itens');
  const rowBefore=await page.locator('[data-cache-id="A"]').elementHandle();
  await page.evaluate(async()=>{await fetchProcessingQueue();});
  assert(await rowBefore.evaluate(e=>e.isConnected));
  await page.locator('[data-cache-id="A"] [data-queue-action=edit]').focus();
  await page.evaluate(async()=>{await fetchProcessingQueue();});
  assert.equal(await page.locator('[data-cache-id="A"] [data-queue-action=edit]').evaluate(e=>e===document.activeElement),true);
  for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:900});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Overflow at ${width}`);
   await page.screenshot({path:`queue-cache-${width}.png`,fullPage:true});
  }
  await page.evaluate(()=>setTheme('light'));
  await page.waitForTimeout(350);
  await page.locator('#queueCard').screenshot({path:'queue-cache-light.png'});
  jobs.splice(0,jobs.length,{id:'NEXT',title:'Próxima fila',status:'queued',can_reprocess:true,has_segments:false});
  serverStatus={status:'processing',progress:1,step:'Preparing queued job',can_cancel:true};
  await page.evaluate(async()=>{await fetchStatus();await fetchProcessingQueue();});
  assert.equal(await page.locator('#processingQueueList .queue-item').count(),1);
  assert.equal(await page.locator('[data-cache-id="A"]').count(),0);
  assert(await page.locator('[data-cache-id="NEXT"]').isVisible());
  assert.deepEqual(errors,[]);
  console.log('Single queue list, finished-item retention, compact actions, stable focus, batch rotation and all revision flows passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
