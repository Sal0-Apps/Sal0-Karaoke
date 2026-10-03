const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = fs.readFileSync('app/templates/index.html', 'utf8');
const icon = fs.readFileSync('app/templates/app-icon-v8.png');
const srtDefaults = {text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,font_size:24,text_position:'bottom',
    video_subtitle_source:'translated',background_color:'#101827',background_file:''};

(async () => {
    const browser = await chromium.launch({headless:true});
    try {
        const page = await browser.newPage({viewport:{width:390,height:900}});
        let config = {...srtDefaults}, delayedDraft, delayedFetch, holdDraft = false, holdFetch = false;
        const errors = [], drafts = new Map(), submissions = [], deletes = [], backgroundPolls = [];
        const jobs = [{id:'active',title:'Processando A',status:'processing',owner_username:'owner'}];
        await page.addInitScript(() => localStorage.setItem('karaoke_token','session'));
        page.on('pageerror',error => errors.push(error.message));
        page.on('dialog',dialog => {errors.push(dialog.message());dialog.dismiss();});
        await page.route('**/*',async route => {
            const request=route.request(),url=new URL(request.url());
            if(url.hostname!=='karaoke.test')return route.abort();
            if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:HTML});
            if(url.pathname==='/favicon.png')return route.fulfill({contentType:'image/png',body:icon});
            const reply=data=>route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
            if(url.pathname==='/api/auth_status')return reply({status:'authenticated',username:'owner',role:'admin'});
            if(url.pathname==='/api/status')return reply({status:'processing',step:'Transcribing original audio',progress:50,can_cancel:true,
                process_summary:{title:'Processando A',mode:'Legendar vídeo'},result_available_to_current_user:true});
            if(url.pathname==='/api/queue')return reply({jobs});
            if(url.pathname==='/api/easy-mode')return reply({enabled:true,whisper_model:'large-v3-turbo',lyrics_mode:'auto',background_mode:'original'});
            if(url.pathname==='/api/subtitle-mode'){
                if(request.method()==='POST')config={...request.postDataJSON()};
                return reply(request.method()==='POST'?{status:'success',config}:config);
            }
            if(url.pathname==='/api/library')return reply({videos:['A.mp4','B.mp4','C.mp4','D.mp4'],photos:['bg.mp4'],history:[]});
            if(url.pathname==='/api/cache_info')return reply({has_cache:false});
            if(url.pathname==='/api/lyrics'){
                const body=request.method()==='POST'?request.postDataJSON():{},key=body.source_key||url.searchParams.get('source_key');
                assert(key,'Every guide operation must identify its media');
                if(request.method()==='POST'){drafts.set(key,body);return reply({status:'saved'});}
                if(request.method()==='DELETE'){deletes.push(key);drafts.set(key,{lyrics_text:'',lyrics_mode:'manual'});return reply({status:'deleted'});}
                if(holdDraft&&key==='library:C.mp4'){delayedDraft=()=>reply({lyrics_text:'Wrong late guide',lyrics_mode:'manual'});return;}
                return reply(drafts.get(key)||{lyrics_text:'',lyrics_mode:'auto'});
            }
            if(url.pathname==='/api/lyrics/search'){
                const query=request.postDataJSON().query;
                return reply({results:query==='explicit search'?[{provider:'LRCLIB',id:1,track_name:'A',artist_name:'Artist',has_lyrics:true}]:[]});
            }
            if(url.pathname==='/api/lyrics/fetch'){
                if(holdFetch){delayedFetch=()=>reply({lyrics_text:'Wrong late import',track_name:'A',artist_name:'Artist'});return;}
                return reply({lyrics_text:'Chosen online guide',track_name:'A',artist_name:'Artist'});
            }
            if(url.pathname==='/api/process'){
                const body=request.postData();submissions.push(body);
                const id='queued-'+submissions.length;jobs.push({id,title:'Novo vídeo',status:'queued'});
                return reply({status:'queued',job_id:id,position:jobs.length-1});
            }
            if(url.pathname==='/api/download-bg-youtube-preset')return reply({status:'started',download_id:'background-id'});
            if(url.pathname==='/api/youtube-preset-status/bg'){
                backgroundPolls.push(url.searchParams.get('download_id'));
                return reply({status:'done',progress:100,title:'New background',filename:'new-bg.mp4'});
            }
            return reply({});
        });
        await page.goto('http://karaoke.test');
        await page.waitForFunction(()=>currentUser?.username==='owner'&&Boolean(window.attachLyricDraft));
        await page.locator('#processCard').waitFor({state:'visible'});
        const field=(body,name)=>body.match(new RegExp('name="'+name+'"\\r?\\n\\r?\\n([^\\r\\n]*)'))?.[1]||'';
        const newItem=async mode=>{
            await page.locator('#btnToggleQueueCreation').click();
            await page.locator('#btnCreator'+({advanced:'Advanced',easy:'Easy',subtitle:'Subtitle'})[mode]).click();
        };
        const chooseLibrary=async filename=>{
            await page.locator('#btnAudioModeLibrary').click();
            await page.locator('#libraryAudioSelect').selectOption(filename);
            await page.evaluate(()=>window.onLyricSourceChange());
        };
        const edit=async text=>{
            if(await page.locator('#btnToggleLyrics').getAttribute('aria-expanded')!=='true')await page.locator('#btnToggleLyrics').click();
            await page.locator('#lyricsMode').selectOption('manual');
            await page.locator('#lyricsText').fill(text);
        };
        await newItem('advanced');await chooseLibrary('A.mp4');await edit('Guide A');
        await page.locator('#btnSaveLyrics').click();
        await page.waitForFunction(()=>document.getElementById('btnSaveLyrics').textContent.includes('Salvar'));
        assert.equal(drafts.get('library:A.mp4').lyrics_text,'Guide A');
        await page.locator('#btnSubmit').click();
        await page.locator('#processCard').waitFor({state:'visible'});
        assert.equal(field(submissions[0],'lyrics_text'),'Guide A');
        assert.equal(field(submissions[0],'lyrics_selected'),'true');

        await newItem('advanced');await chooseLibrary('B.mp4');await edit('Guide B');
        await page.locator('#btnSaveLyrics').click();
        await page.waitForFunction(()=>document.getElementById('btnSaveLyrics').textContent.includes('Salvar'));
        await page.locator('#btnClearLyrics').click();
        await page.waitForFunction(()=>document.getElementById('lyricsText').value==='');
        assert.deepEqual(deletes,['library:B.mp4']);
        assert.equal(drafts.get('library:A.mp4').lyrics_text,'Guide A');
        assert.equal(field(submissions[0],'lyrics_text'),'Guide A');
        await chooseLibrary('A.mp4');assert.equal(await page.locator('#lyricsText').inputValue(),'Guide A');
        await edit('Guide A edited after enqueue');
        assert.equal(field(submissions[0],'lyrics_text'),'Guide A');

        // Both karaoke modes use the same source-specific guide editor.
        await page.locator('#btnCreatorEasy').click();
        await page.locator('[data-quick-source="library"]').click();
        await page.locator('#easyLibraryAudio').selectOption('A.mp4');
        await page.evaluate(()=>window.onLyricSourceChange());
        assert(await page.locator('#easyModeForm #lyricsCard').isVisible());
        assert.equal(await page.locator('#lyricsText').inputValue(),'Guide A edited after enqueue');
        await page.locator('#easySubmitBtn').click();await page.locator('#processCard').waitFor({state:'visible'});
        assert.equal(field(submissions[1],'lyrics_text'),'Guide A edited after enqueue');

        // A batch must not copy the first file's guide to unrelated files.
        await newItem('easy');await page.locator('[data-quick-source="upload"]').click();
        await page.locator('#easyAudioFile').setInputFiles([{name:'First.wav',mimeType:'audio/wav',buffer:Buffer.from('one')},
            {name:'Second.wav',mimeType:'audio/wav',buffer:Buffer.from('two')}]);
        await page.evaluate(()=>window.onLyricSourceChange());await edit('Guide of first file');
        await page.locator('#easySubmitBtn').click();await page.locator('#processCard').waitFor({state:'visible'});
        assert.equal(field(submissions[2],'lyrics_text'),'Guide of first file');
        assert.equal(field(submissions[3],'lyrics_text'),'');
        assert.equal(field(submissions[3],'lyrics_mode'),'auto');

        // Late draft responses and late online imports cannot replace a new media's text.
        await newItem('advanced');holdDraft=true;
        await page.locator('#btnAudioModeLibrary').click();await page.locator('#libraryAudioSelect').selectOption('C.mp4');
        await page.waitForTimeout(50);assert(delayedDraft);
        drafts.set('library:D.mp4',{lyrics_text:'Guide D',lyrics_mode:'manual'});
        await page.locator('#libraryAudioSelect').selectOption('D.mp4');await page.evaluate(()=>window.onLyricSourceChange());
        await delayedDraft();await page.waitForTimeout(50);
        assert.equal(await page.locator('#lyricsText').inputValue(),'Guide D');
        await page.locator('#lyricsSearchQuery').fill('explicit search');await page.locator('#btnSearchLyrics').click();
        await page.getByRole('button',{name:'Usar esta letra'}).waitFor();holdFetch=true;
        await page.getByRole('button',{name:'Usar esta letra'}).click();await page.waitForTimeout(50);assert(delayedFetch);
        await chooseLibrary('B.mp4');await edit('New Guide B');await delayedFetch();await page.waitForTimeout(50);
        assert.equal(await page.locator('#lyricsText').inputValue(),'New Guide B');

        // Speech captioning has distinct labels, defaults and a video submission.
        await page.locator('#btnCreatorSubtitle').click();
        assert(await page.locator('#subtitleModeForm').isVisible());
        assert.equal(await page.locator('#subtitleSubmitBtn').textContent(),'▤ Legendar vídeo');
        assert.equal(await page.locator('#subtitleTranscriptionPreset').inputValue(),'difficult');
        await page.locator('#subtitleLibraryVideo').selectOption('A.mp4');await page.locator('#subtitleSubmitBtn').click();
        await page.locator('#processCard').waitFor({state:'visible'});
        assert.equal(field(submissions[4],'subtitle_only'),'true');
        assert.equal(field(submissions[4],'translation_language'),'pt-BR');
        assert.equal(field(submissions[4],'lyrics_text'),'');

        await page.locator('#tabBtnSettings').click();
        assert(await page.locator('#subtitleModeSettingsSection').isVisible());
        await page.locator('#srtVideoSubtitleSource').selectOption('original');
        await page.locator('#srtBackgroundFile').selectOption('bg.mp4');
        await page.locator('#srtTextColor').fill('#ffcc00');await page.locator('#btnSaveSubtitleMode').click();
        await page.waitForFunction(()=>document.getElementById('subtitleSettingsMessage').textContent.includes('Padrão salvo'));
        assert.equal(config.video_subtitle_source,'original');assert.equal(config.background_file,'bg.mp4');
        for(const width of [320,360,390,768,1440]){
            await page.setViewportSize({width,height:900});
            assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow at '+width);
        }
        await page.setViewportSize({width:390,height:900});
        await page.locator('#subtitleModeSettingsSection').screenshot({path:'subtitle-admin-mobile.png'});

        // A background download remains available while the active task is running.
        await page.locator('#tabBtnLibrary').click();await page.locator('#libraryImports > summary').click();await page.locator('#libBgYoutubeUrl').fill('https://youtu.be/abcdefghijk');
        await page.locator('#btnLibDownloadBgYoutube').click();
        await page.waitForFunction(()=>document.getElementById('bgYtSelectedText').textContent.includes('new-bg.mp4'));
        assert.deepEqual(backgroundPolls,['background-id']);
        assert.deepEqual(errors,[]);
        console.log('SRT defaults, source-specific guides, queue snapshots, batches, delayed responses and background downloads passed.');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
