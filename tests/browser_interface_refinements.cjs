const fs = require('fs');
const assert = require('assert/strict');
const {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();

(async () => {
    const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
        ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {})});
    const errors = [];
    try {
        const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
        page.on('pageerror', error => errors.push(error.message));
        await page.addInitScript(() => localStorage.setItem('karaoke_token', 'interface-test'));
        const library = {videos: ['Canção de teste.mp4'], photos: ['Palco.png'], history: ['Resultado.mp4']};
        await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            if (url.hostname !== 'karaoke.test') return route.abort();
            if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: HTML});
            if (!url.pathname.startsWith('/api/')) return route.fulfill({contentType: 'image/png', body: fs.readFileSync('app/templates/app-icon-v8.png')});
            const responses = {
                '/api/auth_status': {status: 'authenticated', username: 'owner', role: 'admin'},
                '/api/status': {status: 'idle', progress: 0}, '/api/queue': {jobs: []},
                '/api/library': library, '/api/users': [], '/api/models': {'large-v3-turbo': {status: 'done'}},
                '/api/profiles': {}, '/api/cache_info': {has_cache: false},
                '/api/easy-mode': {enabled: true, whisper_model: 'large-v3-turbo', font_size: 50, lyrics_mode: 'auto'},
                '/api/subtitle-mode': {}, '/api/youtube/publication-options': {enabled: false},
            };
            return route.fulfill({contentType: 'application/json', body: JSON.stringify(responses[url.pathname] || {})});
        });
        await page.goto('http://karaoke.test');
        await page.waitForFunction(() => currentUser && document.querySelector('#modelsListContainer button'));
        // Both static and dynamic icons must resolve locally, with no emoji text or internal tokens.
        const iconCheck = await page.evaluate(() => {
            const missing = [...document.querySelectorAll('svg.sal0-icon use')].filter(use => !document.querySelector(use.getAttribute('href')));
            return {missing: missing.length, count: document.querySelectorAll('svg.sal0-icon').length,
                text: document.body.innerText, options: [...document.querySelectorAll('option')].map(option => option.innerHTML)};
        });
        assert.equal(iconCheck.missing, 0);
        assert(iconCheck.count > 80);
        assert(!/\[\[sal0:|[\u{1F000}-\u{1FAFF}\u2600-\u27BF]/u.test(iconCheck.text));
        assert(iconCheck.options.every(option => !option.includes('<svg')));
        await page.evaluate(() => {
            renderEasyRandomBackgroundChoices([]);
            if (!document.getElementById('easyModeRandomBackgroundList').textContent.includes('Adicione'))
                throw new Error('Empty background collection must remain usable');
            renderEasyRandomBackgroundChoices(['Palco.png']);
        });
        await page.evaluate(async () => {
            // Stable responses retain select options and expanded file rows.
            const select = document.getElementById('libraryAudioSelect');
            select.value = 'Canção de teste.mp4';
            window.savedLibraryNode = document.querySelector('#libVideosList .library-item');
            window.savedModelNode = document.querySelector('#modelsListContainer button');
            await loadLibrary(); await fetchModelsStatus();
        });
        assert(await page.evaluate(() => savedLibraryNode === document.querySelector('#libVideosList .library-item')));
        assert(await page.evaluate(() => savedModelNode === document.querySelector('#modelsListContainer button')));
        assert.equal(await page.locator('#libraryAudioSelect').inputValue(), 'Canção de teste.mp4');
        const statusMutations = await page.evaluate(async () => {
            await renderServerStatus({status: 'processing', progress: 42, step: 'Transcribing vocals', can_cancel: true});
            let mutations = 0;
            const observer = new MutationObserver(records => { mutations += records.length; });
            observer.observe(document.getElementById('createTabContent'), {subtree: true, attributes: true, childList: true, characterData: true});
            await renderServerStatus({status: 'processing', progress: 42, step: 'Transcribing vocals', can_cancel: true});
            await new Promise(resolve => requestAnimationFrame(resolve)); observer.disconnect();
            return mutations;
        });
        assert.equal(statusMutations, 0);
        const serial = await page.evaluate(async () => {
            let active = 0, maximum = 0, count = 0;
            let done;
            const finished = new Promise(resolve => { done = resolve; });
            const poll = startSerialPoll(async () => {
                maximum = Math.max(maximum, ++active);
                await new Promise(resolve => setTimeout(resolve, 25)); active--; count++;
                if (count === 3) { stopSerialPoll(poll); done(); }
            }, 1);
            await finished; await new Promise(resolve => setTimeout(resolve, 50));
            return {maximum, count};
        });
        assert.deepEqual(serial, {maximum: 1, count: 3});
        await page.evaluate(async () => { lastStatusRenderSignature = ''; await renderServerStatus({status: 'idle'}); });
        fs.mkdirSync('review-artifacts', {recursive: true});
        await page.screenshot({path: 'review-artifacts/interface-desktop.png', fullPage: true});
        await page.setViewportSize({width: 390, height: 900});
        await page.screenshot({path: 'review-artifacts/interface-mobile.png', fullPage: true});
        await page.evaluate(() => {
            window.cacheEditorActive = true;
            currentSegments = Array.from({length: 80}, (_, i) => ({start: i * 3, end: i * 3 + 2, text: `Linha ${i + 1} da canção`}));
            renderSegments(); document.getElementById('correctionCard').style.display = 'block';
        });
        await page.locator('#correctionList textarea').first().fill('Letra revisada no celular');
        assert.equal(await page.locator('#previewSubtitleText').innerText(), 'Letra revisada no celular');
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.locator('#correctionCard').screenshot({path: 'review-artifacts/interface-editor-mobile.png'});
        assert.deepEqual(errors, []);
        console.log('PASS interface icons, unchanged DOM, select retention, serial polling, mobile editor; desktop/mobile screenshots saved.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
