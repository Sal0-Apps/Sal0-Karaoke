const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = fs.readFileSync('app/templates/index.html', 'utf8');
const icon = fs.readFileSync('app/templates/app-icon-v8.png');
const audio = Buffer.alloc(44 + 20 * 8000 * 2);
audio.write('RIFF'); audio.writeUInt32LE(audio.length - 8, 4); audio.write('WAVEfmt ', 8);
audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
audio.writeUInt32LE(8000, 24); audio.writeUInt32LE(16000, 28); audio.writeUInt16LE(2, 32);
audio.writeUInt16LE(16, 34); audio.write('data', 36); audio.writeUInt32LE(audio.length - 44, 40);
for (const script of HTML.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new Function(script[1]);

(async () => {
    const browser = await chromium.launch({headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 900}});
        const errors = [], submitted = [], revisions = [];
        let failSecond = true, failReview = false, reviewCache = false, backgroundAuthenticated = false;
        await page.addInitScript(() => localStorage.setItem('karaoke_token', 'test-session'));
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => { errors.push('Unexpected blocking dialog: ' + dialog.message()); dialog.dismiss(); });
        await page.route('**/*', async route => {
            const request = route.request(), url = new URL(request.url());
            if (url.hostname !== 'karaoke.test') return route.abort();
            if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: HTML});
            if (url.pathname === '/favicon.png') return route.fulfill({contentType: 'image/png', body: icon});
            if (url.pathname === '/api/cache/background') {
                backgroundAuthenticated = url.searchParams.get('token') === 'test-session';
                return route.fulfill({contentType: 'image/png', body: icon});
            }
            if (url.pathname === '/api/cache/audio') {
                assert.equal(url.searchParams.get('token'), 'test-session');
                const range = request.headers().range?.match(/bytes=(\d+)-(\d*)/);
                if (range) {
                    const start = Number(range[1]), end = range[2] ? Math.min(Number(range[2]), audio.length - 1) : audio.length - 1;
                    return route.fulfill({status: 206, contentType: 'audio/wav', body: audio.subarray(start, end + 1),
                        headers: {'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${start}-${end}/${audio.length}`}});
                }
                return route.fulfill({contentType: 'audio/wav', body: audio, headers: {'Accept-Ranges': 'bytes'}});
            }
            let data = {}, status = 200;
            if (url.pathname === '/api/auth_status') data = {status: 'authenticated', username: 'owner', role: 'admin'};
            if (url.pathname === '/api/status') data = {status: 'idle', progress: 0};
            if (url.pathname === '/api/easy-mode') data = {enabled: true, font_size: 50, whisper_model: 'medium', background_mode: 'random_library', lyrics_mode: 'auto', enable_vad: true};
            if (url.pathname === '/api/library') data = {audio: [], backgrounds: [], history: [], videos: [], photos: []};
            if (url.pathname === '/api/queue') data = {jobs: []};
            if (url.pathname === '/api/cache_info') data = {has_cache: reviewCache, bg_is_video: false, audio_filename: 'review.wav'};
            if (url.pathname === '/api/segments_to_edit') data = [{start: 10, end: 13, text: '  Exact lyric  ', words: [], synced_line: true, acoustic_animation: true},
                {start: 14, end: 17, text: 'Next verse', words: [], synced_line: true, acoustic_animation: true}];
            if (url.pathname === '/api/profiles') data = {Legacy: {font_size: 50, whisper_model: 'medium', enable_vad: true, lyrics_timing: 'acoustic', background_mode: 'original', text_position: 'middle', subtitle_mode: 'syllable'}};
            if (url.pathname === '/api/process') {
                const file = request.postData().match(/name="audio_file"; filename="([^"]+)"/)?.[1] || 'link';
                submitted.push(file);
                if (failSecond && submitted.length === 2) {status = 400; data = {detail: 'Falha de teste no segundo arquivo.'};}
                else data = {status: 'queued', position: submitted.length, job_id: String(submitted.length)};
            }
            if (url.pathname === '/api/continue_process') {
                revisions.push(request.postDataJSON());
                if (failReview) {status = 400; data = {detail: 'Linha 1: tempo rejeitado pelo servidor.'};}
                else data = {status: 'success'};
            }
            return route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)});
        });
        await page.goto('http://karaoke.test');
        await page.locator('[data-quick-source="upload"]').waitFor();
        for (const width of [320, 360, 390, 768, 1440]) {
            await page.setViewportSize({width, height: 900});
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Horizontal overflow at ' + width);
            assert(await page.locator('#tabBtnLibrary').evaluate(button => getComputedStyle(button).whiteSpace === 'nowrap'));
            if (width <= 390) assert((await page.locator('header').boundingBox()).height < 205, 'Header too tall');
        }
        await page.setViewportSize({width: 390, height: 900});
        await page.locator('#tabBtnCreate').focus();
        await page.keyboard.press('ArrowRight');
        assert.equal(await page.locator('#tabBtnSettings').getAttribute('aria-selected'), 'true');
        await page.keyboard.press('Home');
        assert.equal(await page.locator('#tabBtnCreate').getAttribute('aria-selected'), 'true');
        await page.screenshot({path: 'creation-review-mobile.png', fullPage: false});
        await page.locator('[data-quick-source="upload"]').click();
        const files = ['one.wav', 'two.wav', 'three.wav'].map(name => ({name, mimeType: 'audio/wav', buffer: Buffer.from('test')}));
        await page.locator('#easyAudioFile').setInputFiles(files);
        await page.locator('#easySubmitBtn').click();
        await page.waitForFunction(() => document.getElementById('creationFeedback').textContent.includes('Falha de teste'));
        assert.equal(submitted.length, 2);
        assert.deepEqual(await page.locator('#easyAudioFile').evaluate(input => [...input.files].map(file => file.name)), ['two.wav', 'three.wav']);
        assert((await page.locator('#creationFeedback').textContent()).includes('1 arquivo(s) já adicionado(s)'));
        failSecond = false;
        await page.locator('#easySubmitBtn').click();
        await page.waitForFunction(() => !clientPreparationInProgress && document.getElementById('easyAudioFile').files.length === 0);
        assert.deepEqual(submitted, ['one.wav', 'two.wav', 'two.wav', 'three.wav']);
        assert.equal(await page.locator('#easyAudioFile').evaluate(input => input.files.length), 0);

        // Exercise each form's own input through the same actual submission handler.
        for (const [mode, input, button] of [['subtitle', 'subtitleVideoFile', 'subtitleSubmitBtn'], ['advanced', 'audioFile', 'btnSubmit']]) {
            await page.evaluate(mode => {setQueueCreationExpanded(true); setCreatorMode(mode);}, mode);
            await page.locator('#' + input).setInputFiles(files.slice(0, 1));
            await page.locator('#' + button).click();
            await page.waitForFunction(id => !clientPreparationInProgress && document.getElementById(id).files.length === 0, input);
            assert.equal(await page.locator('#' + input).evaluate(input => input.files.length), 0);
        }
        assert.equal(await page.locator('#enableVad').inputValue(), 'false');
        assert.equal(await page.locator('#lyricsTiming').inputValue(), 'auto');
        reviewCache = true;
        await page.evaluate(() => loadCorrectionPanel());
        await page.waitForFunction(() => document.getElementById('correctionAudio').readyState > 0);
        assert(backgroundAuthenticated, 'Review background must use the current login token');
        await page.locator('#btnNextSegment').click();
        await page.waitForFunction(() => document.getElementById('correctionAudio').currentTime === 14);
        assert.equal(await page.locator('#correctionAudio').evaluate(audio => audio.currentTime), 14);
        await page.locator('#btnPreviousSegment').click();
        await page.waitForFunction(() => document.getElementById('correctionAudio').currentTime === 10);
        assert.equal(await page.locator('#correctionAudio').evaluate(audio => audio.currentTime), 10);
        await page.locator('#correctionCard').scrollIntoViewIfNeeded();
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        await page.locator('#correctionCard').screenshot({path: 'creation-review-editor-mobile.png'});
        await page.setViewportSize({width: 1440, height: 1000});
        await page.evaluate(() => setTheme('light'));
        await page.locator('#correctionCard').screenshot({path: 'creation-review-editor-light.png'});
        await page.evaluate(() => setTheme('dark'));
        await page.setViewportSize({width: 390, height: 900});
        const textarea = page.locator('#correctionList textarea').first();
        await textarea.fill(' ');
        await page.locator('#btnContinueProcess').click();
        assert.equal(revisions.length, 0);
        assert((await page.locator('#correctionValidationMessage').textContent()).includes('Linha 1'));
        await textarea.fill('  Exact lyric  ');
        const start = page.locator('#correctionList input').first();
        await start.fill('not a time'); await start.blur();
        await page.locator('#btnContinueProcess').click();
        assert.equal(revisions.length, 0);
        await start.fill('00:10.00'); await start.blur();
        failReview = true;
        await page.locator('#btnContinueProcess').click();
        await page.waitForFunction(() => document.getElementById('correctionValidationMessage').textContent.includes('rejeitado pelo servidor'));
        assert(await page.locator('#correctionCard').isVisible());
        failReview = false;
        await page.locator('#btnContinueProcess').click();
        await page.waitForFunction(() => document.getElementById('correctionCard').style.display === 'none');
        assert.equal(revisions.at(-1).segments[0].text, '  Exact lyric  ');
        assert.equal(await page.evaluate(() => formatTimeMMSS(59.999)), '01:00.00');
        assert.equal(await page.evaluate(() => parseTimeMMSS('01:03,25')), 63.25);
        assert(await page.evaluate(() => Number.isNaN(parseTimeMMSS('00:90'))));
        await page.setViewportSize({width: 1440, height: 1000});
        await page.screenshot({path: 'creation-review-desktop.png', fullPage: false});
        assert.deepEqual(errors, []);
        console.log('All three creation forms, partial retries without duplicates, review validation, canonical text, keyboard and five viewport sizes passed.');
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
