const assert = require('assert'), {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();
(async () => {
    const browser = await chromium.launch({headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
        const errors = []; page.on('pageerror', error => errors.push(error.message));
        let role = 'admin', ready = false, saved = null;
        let config = {animation_style: 'smooth', highlight_glow: true, instrumental_style: 'progress',
            instrumental_color: '#38bdf8', min_instrumental_gap: 2, countdown_seconds: 3};
        await page.route('**/*', async route => {
            const request = route.request(), url = new URL(request.url());
            if (url.hostname !== 'karaoke.test') return route.abort();
            if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: HTML});
            let data = {}, status = 200;
            if (url.pathname === '/api/auth_status') data = {status: 'authenticated', username: 'owner', role};
            if (url.pathname === '/api/status') data = {status: 'idle', progress: 0};
            if (url.pathname === '/api/queue') data = {jobs: []};
            if (url.pathname === '/api/admin/youtube/status') data = {connected: false, jobs: [], settings: {user_assignments: {}}};
            if (url.pathname === '/api/users') data = [];
            if (url.pathname === '/api/profiles') data = {};
            if (url.pathname === '/api/easy-mode') data = {enabled: true, random_backgrounds: [], whisper_model: 'medium'};
            if (url.pathname === '/api/library') data = {videos: [], photos: [], history: [], audio: [], backgrounds: []};
            if (url.pathname === '/api/youtube/publication-options') {
                if (!ready) status = 503;
                else data = {enabled: true, can_publish: true, default_publish: true, playlist_id: 'PL-profile',
                    playlists: [{id: 'PL-profile', title: 'Minha playlist'}], privacy: 'unlisted', channel_title: 'Canal'};
            }
            if (url.pathname === '/api/admin/karaoke-visuals') {
                if (request.method() === 'POST') { saved = request.postDataJSON(); config = saved; }
                data = config;
            }
            return route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)});
        });
        await page.goto('http://karaoke.test/');
        await page.waitForFunction(() => currentUser?.role === 'admin');
        // An unavailable options panel cannot silently submit false in either mode.
        for (const prefix of ['easy', 'full']) {
            const result = await page.evaluate(prefix => {
                const data = new FormData(); attachYoutubePublicationChoice(data, prefix);
                return [data.get('youtube_publish'), data.get('youtube_use_profile_default')];
            }, prefix);
            assert.deepEqual(result, [null, 'true']);
        }
        ready = true; await page.evaluate(() => loadYoutubePublicationOptions());
        for (const prefix of ['easy', 'full']) {
            assert(await page.locator('#' + prefix + 'YoutubePublish').isChecked());
            assert.equal(await page.evaluate(prefix => {
                const data = new FormData(); attachYoutubePublicationChoice(data, prefix); return data.get('youtube_publish');
            }, prefix), 'true');
            await page.evaluate(prefix => {
                const box = document.getElementById(prefix + 'YoutubePublish'); box.checked = false;
                box.dispatchEvent(new Event('change', {bubbles: true}));
            }, prefix);
        }
        await page.evaluate(() => loadYoutubePublicationOptions());
        for (const prefix of ['easy', 'full']) {
            assert.equal(await page.evaluate(prefix => {
                const data = new FormData(); attachYoutubePublicationChoice(data, prefix); return data.get('youtube_publish');
            }, prefix), 'false', 'Explicit opt-out must survive panel refresh');
        }
        await page.locator('#tabBtnSettings').click();
        await page.locator('#karaokeVisualSettingsSection > summary').click();
        await page.locator('#karaokeAnimationStyle').selectOption('classic');
        await page.locator('#karaokeHighlightGlow').selectOption('false');
        await page.locator('#karaokeCountdown').fill('5');
        await page.locator('#karaokeMinimumRest').fill('4.5');
        await page.locator('#btnSaveKaraokeVisuals').click();
        await page.waitForFunction(() => document.getElementById('karaokeVisualsMessage').textContent.startsWith('Salvo.'));
        assert.equal(saved.countdown_seconds, 5); assert.equal(saved.min_instrumental_gap, 4.5);
        assert.equal(saved.animation_style, 'classic'); assert.equal(saved.highlight_glow, false);
        assert.equal(await page.locator('#karaokeAnimationStyle option').count(), 5);
        assert.equal(await page.locator('#karaokeInstrumentalStyle option').count(), 4);
        await page.locator('#karaokeAnimationStyle').selectOption('pulse');
        await page.locator('#karaokeInstrumentalStyle').selectOption('dots');
        await page.locator('#karaokeInstrumentalText').fill('Solo & volta ao canto');
        await page.locator('#karaokeInstrumentalSize').fill('125');
        await page.locator('#karaokeCountdown').fill('0');
        await page.locator('#btnSaveKaraokeVisuals').click();
        await page.waitForFunction(() => document.getElementById('karaokeVisualsMessage').textContent.startsWith('Salvo.'));
        assert.equal(saved.animation_style, 'pulse'); assert.equal(saved.instrumental_style, 'dots');
        assert.equal(saved.instrumental_text, 'Solo & volta ao canto'); assert.equal(saved.instrumental_size, 125);
        assert.equal(saved.countdown_seconds, 0);
        await page.reload(); await page.waitForFunction(() => currentUser?.role === 'admin');
        await page.locator('#tabBtnSettings').click();
        await page.locator('#karaokeVisualSettingsSection > summary').click();
        assert.equal(await page.locator('#karaokeAnimationStyle').inputValue(), 'pulse');
        assert.equal(await page.locator('#karaokeInstrumentalStyle').inputValue(), 'dots');
        assert.equal(await page.locator('#karaokeInstrumentalText').inputValue(), 'Solo & volta ao canto');
        assert.equal(await page.locator('#karaokeInstrumentalSize').inputValue(), '125');
        assert.equal(await page.locator('#karaokeCountdown').inputValue(), '0');
        for (const width of [1280, 390]) {
            await page.setViewportSize({width, height: 1000});
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
            await page.screenshot({path: `review-artifacts/karaoke-visuals-${width}.png`, fullPage: true});
        }
        role = 'user'; await page.reload();
        await page.waitForFunction(() => currentUser?.role === 'user');
        assert(!await page.locator('#karaokeVisualSettingsSection').isVisible());
        assert.deepEqual(errors, []);
        console.log('Karaoke admin visuals and automatic publication choices passed.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
