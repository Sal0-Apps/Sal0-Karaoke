const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = fs.readFileSync('app/templates/index.html', 'utf8');
const title = 'YOASOBI / Tracing A Dream (あの夢をなぞって English Ver.)';
const correct = {id:1, provider:'LRCLIB', track_name:'Tracing A Dream', artist_name:'YOASOBI', has_lyrics:true};

(async () => {
    const browser = await chromium.launch({headless:true});
    try {
        const page = await browser.newPage({viewport:{width:390,height:900},isMobile:true,hasTouch:true});
        const errors=[], searches=[], saves=[];
        let heldSearch, heldFetch, heldDraft, heldAutomatic, holdSearch=false, holdFetch=false, holdDraft=false, holdAutomatic=false;
        let automaticMatch=null, status='done', reloads=0;
        page.on('pageerror',error=>errors.push(error.message));
        page.on('framenavigated',frame=>{if(frame===page.mainFrame())reloads++;});
        await page.addInitScript(()=>{
            localStorage.setItem('karaoke_token','session');
            sessionStorage.setItem('sal0-lyric-drafts:owner',JSON.stringify([
                ['youtube:abcdefghijk',{lyrics_mode:'auto',lyrics_text:'NOKIA — Drake'}]
            ]));
        });
        await page.route('**/*',async route=>{
            const request=route.request(), url=new URL(request.url());
            if(url.hostname!=='karaoke.test')return route.abort();
            if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:HTML});
            const reply=data=>route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
            if(url.pathname==='/api/auth_status')return reply({status:'authenticated',username:'owner',role:'admin'});
            if(url.pathname==='/api/easy-mode')return reply({enabled:true,lyrics_mode:'auto',background_mode:'original'});
            if(url.pathname==='/api/status')return reply({status,progress:100,original_filename:'previous.mp4',result_available_to_current_user:true});
            if(url.pathname==='/api/queue')return reply({jobs:[]});
            if(url.pathname==='/api/library')return reply({videos:['Other - Song.mp4'],photos:[],history:[]});
            if(url.pathname==='/api/youtube/metadata')return reply({title,lyrics_query:title});
            if(url.pathname==='/api/lyrics'){
                if(request.method()==='POST'){saves.push(request.postDataJSON());return reply({status:'saved'});}
                if(holdDraft){heldDraft=()=>reply({lyrics_text:'Late saved draft',lyrics_mode:'auto'});return;}
                return reply({lyrics_text:'',lyrics_mode:'auto',has_draft:false});
            }
            if(url.pathname==='/api/lyrics/search'){
                const body=request.postDataJSON();searches.push(body);
                // An unrelated provider result must never become an automatic guide.
                const response=body.automatic
                    ? {results:[],automatic_match:automaticMatch}
                    : {results:[correct]};
                if(holdAutomatic&&body.automatic){heldAutomatic=()=>reply(response);return;}
                if(holdSearch){heldSearch=()=>reply(response);return;}
                return reply(response);
            }
            if(url.pathname==='/api/lyrics/fetch'){
                if(holdFetch){heldFetch=()=>reply({lyrics_text:'Chosen manual guide',...correct});return;}
                return reply({lyrics_text:'Chosen manual guide',...correct});
            }
            return reply({});
        });
        await page.goto('http://karaoke.test');
        await page.waitForFunction(()=>currentUser?.username==='owner'&&Boolean(window.attachLyricDraft));
        await page.locator('#easyYoutubeUrl').fill('https://www.youtube.com/watch?v=abcdefghijk');
        await page.locator('#btnToggleLyrics').click();
        assert.equal(await page.locator('#lyricsText').inputValue(),'','Old unverified automatic guide is reused');
        await page.locator('#lyricsSearchQuery').focus();
        await page.locator('#lyricsSearchQuery').fill('Tracing A Dream YOASOBI');
        const scrollBefore=await page.evaluate(()=>scrollY);
        // Polling the completed or active task must not detach the focused editor.
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert.equal(await page.evaluate(()=>document.activeElement.id),'lyricsSearchQuery','Status polling closes the keyboard');
        assert.equal(await page.locator('#lyricsSearchQuery').inputValue(),'Tracing A Dream YOASOBI');
        assert.equal(await page.evaluate(()=>scrollY),scrollBefore,'Status polling moves the viewport');

        // Manual search takes ownership immediately, including while responses are slow.
        holdSearch=true;
        await page.locator('#btnSearchLyrics').click();
        await page.waitForFunction(()=>document.getElementById('btnSearchLyrics').disabled);
        assert.equal(await page.locator('#lyricsMode').inputValue(),'manual');
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert(heldSearch);holdSearch=false;await heldSearch();
        await page.getByRole('button',{name:'Usar esta letra'}).waitFor();
        holdFetch=true;await page.getByRole('button',{name:'Usar esta letra'}).click();
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert(heldFetch);holdFetch=false;await heldFetch();
        await page.waitForFunction(()=>document.getElementById('lyricsText').value==='Chosen manual guide');
        assert.equal(saves.at(-1).source_key,'youtube:abcdefghijk');
        await page.locator('#lyricsText').focus();
        status='idle';for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert.equal(await page.evaluate(()=>document.activeElement.id),'lyricsText');

        // New media gets one automatic attempt; no match stays empty across every poll.
        await page.locator('#easyYoutubeUrl').fill('https://youtu.be/123456789ab');
        await page.waitForTimeout(800);
        await page.waitForFunction(()=>document.getElementById('lyricsSearchStatus').textContent.includes('Nenhuma letra'));
        const count=searches.length;
        for(let i=0;i<8;i++)await page.evaluate(()=>fetchStatus());
        await page.waitForTimeout(800);
        assert.equal(searches.length,count,'A missing lyric triggers repeated searches');
        assert.equal(await page.locator('#lyricsText').inputValue(),'');
        assert.equal(await page.locator('#lyricsSearchResults').textContent(),'');
        assert.equal(searches.filter(x=>x.automatic).length,1);
        await page.locator('#lyricsMode').focus();
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert.equal(await page.evaluate(()=>document.activeElement.id),'lyricsMode','Polling interrupts the native mode picker');

        // Explicit automatic retry can import the confirmed song, using the returned text.
        automaticMatch={...correct,lyrics_text:'Confirmed automatic guide'};
        await page.locator('#lyricsMode').selectOption('manual');
        await page.locator('#lyricsMode').selectOption('auto');
        await page.waitForFunction(()=>document.getElementById('lyricsText').value==='Confirmed automatic guide');
        assert.equal(saves.at(-1).lyrics_text,'Confirmed automatic guide');

        // A pending draft cannot overwrite typing; manual search need not wait for it.
        holdDraft=true;await page.locator('#easyYoutubeUrl').fill('https://youtu.be/987654321ab');
        await page.waitForTimeout(50);assert(heldDraft);
        await page.locator('#lyricsText').fill('User-written guide');
        await heldDraft().catch(()=>{});holdDraft=false;
        assert.equal(await page.locator('#lyricsText').inputValue(),'User-written guide');
        assert.equal(await page.locator('#lyricsMode').inputValue(),'manual');

        // Starting a manual query also defeats an already-running automatic request.
        holdAutomatic=true;await page.locator('#easyYoutubeUrl').fill('https://youtu.be/111111111ab');
        await page.waitForTimeout(800);assert(heldAutomatic);
        await page.locator('#lyricsSearchQuery').fill('YOASOBI');
        await heldAutomatic().catch(()=>{});holdAutomatic=false;
        await page.keyboard.press('Enter');
        await page.getByRole('button',{name:'Usar esta letra'}).waitFor();
        assert.equal(await page.locator('#lyricsText').inputValue(),'','Late automatic result overrides a manual search');
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert(await page.getByRole('button',{name:'Usar esta letra'}).isVisible());

        // Creation while another job runs keeps the same keyboard and text.
        status='processing';await page.evaluate(()=>fetchStatus());
        await page.locator('#btnToggleQueueCreation').click();
        await page.locator('#easyYoutubeUrl').fill('https://youtu.be/222222222ab');
        await page.locator('#lyricsSearchQuery').fill('Search while processing');
        for(let i=0;i<4;i++)await page.evaluate(()=>fetchStatus());
        assert.equal(await page.evaluate(()=>document.activeElement.id),'lyricsSearchQuery');
        assert.equal(await page.locator('#lyricsSearchQuery').inputValue(),'Search while processing');

        // A configured manual default must not be silently changed to automatic.
        await page.evaluate(()=>{easyModeConfig.lyrics_mode='manual';});
        const beforeManual=searches.length;
        await page.locator('#easyYoutubeUrl').fill('https://youtu.be/333333333ab');
        await page.waitForTimeout(800);
        assert.equal(await page.locator('#lyricsMode').inputValue(),'manual');
        assert.equal(searches.length,beforeManual);
        assert.equal(reloads,1,'Editing must not reload the document');
        assert.deepEqual(errors,[]);
        await page.locator('#lyricsCard').screenshot({path:'lyrics-search-mobile.png'});
        console.log('Lyrics editor focus, stable polling, manual ownership, empty automatic results, retries and late drafts passed.');
    } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
