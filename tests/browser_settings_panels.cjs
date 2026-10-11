const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = fs.readFileSync('app/templates/index.html', 'utf8');
(async () => {
    const browser = await chromium.launch({headless:true});
    try {
        const page = await browser.newPage({viewport:{width:1440,height:1000}});
        const errors = [], writes = [];
        let role = 'admin', detail = 'Configure o bot para receber mensagens.';
        await page.addInitScript(() => localStorage.setItem('karaoke_token', 'session'));
        await page.clock.install();
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', async route => {
            const request = route.request(), url = new URL(request.url());
            if (url.hostname !== 'karaoke.test') return route.abort();
            if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:HTML});
            const reply = data => route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
            if (request.method() !== 'GET') writes.push(url.pathname);
            if (url.pathname === '/api/auth_status') return reply({status:'authenticated',username:'owner',role});
            if (url.pathname === '/api/status') return reply({status:'idle',progress:0});
            if (url.pathname === '/api/queue') return reply({jobs:[]});
            if (url.pathname === '/api/easy-mode') return reply({enabled:true,whisper_model:'medium',background_mode:'original',lyrics_mode:'manual'});
            if (url.pathname === '/api/library') return reply({videos:[],photos:[],history:[]});
            if (url.pathname === '/api/users') return reply([{username:'owner',role:'admin'}]);
            if (url.pathname === '/api/admin/results') return reply({results:[]});
            if (url.pathname === '/api/youtube/publication-options') return reply({enabled:false});
            if (url.pathname === '/api/admin/youtube/status') return reply({connected:false,device_configured:false,settings:{},jobs:[]});
            if (url.pathname === '/api/telegram') return reply({telegram_token:'123456***oken',telegram_chat_id:'-1001',configured:true,delivery:{state:'unverified',detail,pending:0}});
            if (url.pathname === '/api/telegram/status') return reply({state:'unverified',detail,pending:0});
            if (url.pathname === '/api/youtube-tools/status') return reply({yt_dlp_version:'2026.10.11',access:{session_state:'anonymous'}});
            if (url.pathname === '/api/subtitle-mode') return reply({text_color:'#FFFFFF',box_color:'#000000',box_opacity:65,font_size:24,text_position:'bottom',video_subtitle_source:'translated',background_color:'#101827',background_file:''});
            return reply({});
        });
        await page.goto('http://karaoke.test');
        await page.waitForFunction(() => currentUser?.role === 'admin');
        await page.locator('#tabBtnSettings').click();
        const panels = page.locator('.settings-grid > .settings-panel');
        assert.equal(await panels.count(),10);
        assert.equal(await page.locator('.settings-grid details[open]').count(),0);
        for (const panel of await panels.all()) {
            assert(await panel.isVisible());
            const summary = panel.locator(':scope > summary');
            assert.equal(await summary.getAttribute('aria-expanded'),'false');
            await summary.focus(); await page.keyboard.press('Enter');
            await page.waitForFunction(id => {
                const panel = document.getElementById(id);
                return panel.open && panel.querySelector(':scope > summary').getAttribute('aria-expanded') === 'true';
            }, await panel.getAttribute('id'));
            assert.equal(await summary.getAttribute('aria-expanded'),'true');
            await summary.click();
        }
        assert.equal(await page.locator('.settings-grid details[open]').count(),0);
        await page.locator('#telegramSection > summary').click();
        await page.locator('#btnEditTelegram').click();
        await page.locator('#telegramChatIdInput').fill('-100999');
        await page.locator('#telegramTokenInput').focus();
        await page.locator('#telegramTokenInput').evaluate(input => input.setSelectionRange(1,4));
        detail = 'Não foi possível confirmar o envio. Confira a conexão do servidor.';
        await page.evaluate(() => fetchTelegramDeliveryStatus());
        assert.equal(await page.evaluate(() => document.activeElement.id),'telegramTokenInput');
        assert.deepEqual(await page.locator('#telegramTokenInput').evaluate(input => [input.selectionStart,input.selectionEnd]),[1,4]);
        await page.waitForFunction(() => document.getElementById('telegramSectionOverview').textContent.includes('confirmar'));
        await page.locator('#telegramSection > summary').click();
        await page.locator('#telegramSection > summary').click();
        assert.equal(await page.locator('#telegramChatIdInput').inputValue(),'-100999');
        await page.locator('#easyModeSettingsSection > summary').click();
        await page.locator('#easyModeSettingsSection .easy-config-group').first().locator('summary').click();
        await page.locator('#easyModeModel').selectOption('small');
        await page.locator('#btnCollapseSettings').click();
        assert.equal(await page.locator('.settings-grid details[open]').count(),0);
        await page.locator('#easyModeSettingsSection > summary').click();
        await page.locator('#easyModeSettingsSection .easy-config-group').first().locator('summary').click();
        assert.equal(await page.locator('#easyModeModel').inputValue(),'small');
        assert.deepEqual(writes,[],'Opening, closing and status updates cannot save or send messages');
        await page.locator('#btnCollapseSettings').click();
        for (const width of [320,390,768,1440]) {
            await page.setViewportSize({width,height:1000});
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),'Overflow at '+width);
            assert(await page.locator('#youtubePublisherSection').evaluate(panel => {
                const heading = panel.querySelector('.settings-panel-heading').getBoundingClientRect();
                const overview = panel.querySelector('.settings-panel-overview').getBoundingClientRect();
                return overview.top >= heading.bottom;
            }),'YouTube overview must sit below its heading');
            await page.locator('#settingsTabContent').screenshot({path:'settings-panels-'+width+'-collapsed.png'});
        }
        await page.setViewportSize({width:1440,height:1000});
        await page.locator('#telegramSection > summary').click();
        await page.locator('#btnToggleSubtitleSettings').click();
        await page.locator('#btnToggleTheme').click();
        await page.clock.runFor(500);
        await page.waitForFunction(() => getComputedStyle(document.getElementById('telegramSection')).backgroundColor === 'rgb(255, 255, 255)');
        const gridWidth = await page.locator('.settings-grid').evaluate(grid => grid.getBoundingClientRect().width);
        assert.equal(await page.locator('#telegramSection').evaluate(panel => panel.getBoundingClientRect().width),gridWidth);
        await page.screenshot({path:'settings-panels-expanded-light.png',fullPage:true,animations:'disabled'});
        await page.reload(); await page.locator('#tabBtnSettings').click();
        assert.equal(await page.locator('.settings-grid details[open]').count(),0,'Reload starts closed');
        role = 'user';
        await page.reload(); await page.locator('#tabBtnSettings').click();
        await page.waitForFunction(() => currentUser?.role === 'user');
        assert.equal((await panels.all()).length,10);
        const visible = [];
        for (const panel of await panels.all()) if (await panel.isVisible()) visible.push(await panel.getAttribute('id'));
        assert.deepEqual(visible,['telegramSection']);
        assert.equal(await page.locator('.settings-grid details[open]').count(),0);
        assert.deepEqual(errors,[]);
        console.log('All settings start closed; keyboard, edits, live summaries, collapse-all, roles and responsive layouts passed.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
