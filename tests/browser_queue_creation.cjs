const fs = require('fs'), assert = require('assert'), {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();
const icon = fs.readFileSync('app/templates/app-icon-v8.png');
const processing = () => ({status: 'processing', progress: 23, step: 'Separating vocals',
    stage_progress: 8, stage_detail: 'Análise 1 de 4', can_cancel: true,
    process_summary: {title: 'Música em andamento', lyrics: 'Letra sincronizada', model: 'Large V3 Turbo', background: 'Vídeo original'}});
const activeJob = () => ({id: 'active', status: 'processing', title: 'Música em andamento', owner_username: 'owner'});

(async () => {
    const browser = await chromium.launch({headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 900}});
        let serverStatus = processing(), jobs = [activeJob()], queuePaused = false, reviewResponse;
        const errors = [], submissions = [], pending = [], waiters = [];
        const receipts = new Map();
        let confirmationFailures = 0;
        let queueFailures = 0;
        const untilSubmitted = count => submissions.length >= count ? Promise.resolve()
            : new Promise(resolve => waiters.push({count, resolve}));
        await page.addInitScript(() => localStorage.setItem('karaoke_token', 'test-session'));
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => { errors.push('Unexpected dialog: ' + dialog.message()); dialog.dismiss(); });
        await page.route('**/*', async route => {
            const request = route.request(), url = new URL(request.url());
            if (url.hostname !== 'karaoke.test') return route.abort();
            if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: HTML});
            if (url.pathname === '/app-icon-v8.png') return route.fulfill({contentType: 'image/png', body: icon});
            const fulfill = data => route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
            if (url.pathname === '/api/process') {
                assert.equal(request.method(), 'POST');
                const entry = {filename: request.postData().match(/name="audio_file"; filename="([^"]+)"/)?.[1] || 'link', body: request.postData(),
                    submissionId: request.postData().match(/name="submission_id"\r\n\r\n([^\r\n]+)/)?.[1]};
                assert.match(entry.submissionId, /^[a-f0-9]{32}$/);
                assert.equal(request.headers()['x-session-token'], 'test-session');
                pending.push(async (status = 200, body, failure = '') => {
                    if (failure === 'before') return route.abort('failed');
                    if (status === 200 && body === undefined) {
                        body = receipts.get(entry.submissionId);
                        if (!body) {
                            const id = 'job-' + submissions.indexOf(entry);
                            jobs.push({id, status: 'queued', title: entry.filename, position: jobs.length});
                            body = {status: 'queued', job_id: id, position: jobs.length - 1};
                            receipts.set(entry.submissionId, body);
                        }
                    }
                    if (failure === 'after') return route.abort('failed');
                    await route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
                });
                submissions.push(entry);
                waiters.filter(waiter => submissions.length >= waiter.count).forEach(waiter => waiter.resolve());
                return;
            }
            if (url.pathname.startsWith('/api/queue/submissions/')) {
                if (confirmationFailures-- > 0) return route.abort('failed');
                const receipt = receipts.get(url.pathname.split('/').pop());
                return route.fulfill({status: receipt ? 200 : 404, contentType: 'application/json', body: JSON.stringify(receipt || {})});
            }
            if (url.pathname === '/api/status') return fulfill(serverStatus);
            if (url.pathname === '/api/hung-status') return;
            if (url.pathname === '/api/queue') {
                assert.equal(request.method(), 'GET');
                if (queueFailures-- > 0) return route.fulfill({status:503,contentType:'application/json',body:'{}'});
                return fulfill({jobs, paused: queuePaused});
            }
            if (url.pathname === '/api/auth_status') return fulfill({status: 'authenticated', username: 'owner', role: 'admin'});
            if (url.pathname === '/api/easy-mode') return fulfill({enabled: true, whisper_model: 'large-v3-turbo', font_size: 50, lyrics_mode: 'auto'});
            if (url.pathname === '/api/library') return fulfill({audio: [], backgrounds: [], history: [], videos: [], photos: []});
            if (url.pathname === '/api/profiles') return fulfill({});
            if (url.pathname === '/api/cache_info') return fulfill({has_cache: false});
            if (url.pathname === '/api/segments_to_edit') {
                reviewResponse = () => fulfill([{start: 10, end: 13, text: 'Letra preservada', words: []}]);
                return;
            }
            return fulfill({});
        });
        await page.goto('http://karaoke.test');
        await page.locator('#processCard').waitFor({state: 'visible'});
        await page.waitForFunction(() => Boolean(currentUser));
        await page.waitForFunction(() => latestServerStatus?.status === 'processing' && creationUiLocked
            && getComputedStyle(document.getElementById('createTabContent')).display === 'flex');
        const refresh = async () => {
            await page.evaluate(async () => {await fetchStatus(); await fetchProcessingQueue();});
            await page.waitForFunction(status => latestServerStatus?.status === status, serverStatus.status);
        };
        const editorVisible = async mode => {
            assert(await page.locator('#creatorModeSwitch').isVisible());
            assert(await page.locator('#' + {easy: 'easyModeForm', advanced: 'karaokêForm', subtitle: 'subtitleModeForm'}[mode]).isVisible());
            for (const id of ['processCard', 'correctionCard', 'queueCard', 'downloadBox', 'creationLoadingCard'])
                assert(!await page.locator('#' + id).isVisible(), id + ' must stay hidden while entering the next item');
        };
        const loadingVisible = async () => {
            assert(await page.locator('#creationLoadingCard').isVisible());
            assert.equal(await page.locator('#createTabContent').getAttribute('aria-busy'), 'true');
            for (const id of ['processCard', 'correctionCard', 'queueCard', 'downloadBox', 'creatorModeSwitch', 'easyModeForm', 'karaokêForm', 'subtitleModeForm'])
                assert(!await page.locator('#' + id).isVisible(), id + ' must stay hidden before confirmation');
            assert(await page.locator('#btnReturnToProcess').isDisabled());
        };
        const startNew = async mode => {
            await page.locator('#btnToggleQueueCreation').click();
            await page.locator('#btnCreator' + {easy: 'Easy', advanced: 'Advanced', subtitle: 'Subtitle'}[mode]).click();
            if (mode === 'easy') await page.locator('[data-quick-source="upload"]').click();
            await editorVisible(mode);
        };
        const file = name => ({name, mimeType: 'audio/wav', buffer: Buffer.from('test audio')});

        // An unavailable queue schedules a new consultation; a hanging read cannot reserve polling forever.
        queueFailures=1;
        await page.evaluate(() => fetchProcessingQueue());
        await page.waitForResponse(response => new URL(response.url()).pathname === '/api/queue' && response.status() === 200);
        const timeoutResult=await page.evaluate(async () => {
            const start=performance.now();
            try {await timedAuthFetch('/api/hung-status',{},80);return null;}
            catch(error) {return {name:error.name,elapsed:performance.now()-start};}
        });
        assert.equal(timeoutResult.name,'AbortError');assert(timeoutResult.elapsed<1000);

        // The two primary actions are visible together; queue count comes from GET /api/queue.
        assert(!await page.locator('#creationFeedback').isVisible());
        assert(await page.locator('#queueCard').isVisible());
        for (const width of [320, 360, 390, 768, 1440]) {
            await page.setViewportSize({width, height: 900});
            await page.evaluate(async () => {
                await document.fonts.ready;
                await new Promise(resolve => requestAnimationFrame(resolve));
                await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
                    .map(animation => animation.finished.catch(() => {})));
                await new Promise(resolve => requestAnimationFrame(resolve));
            });
            const add = await page.locator('#btnToggleQueueCreation').boundingBox();
            const cancel = await page.locator('#processCard .btn-cancel-task').boundingBox();
            assert(add && cancel && Math.abs(add.y - cancel.y) < 75, 'Actions must be adjacent at ' + width);
            assert(add.y + add.height < 900, 'Add action must be visible without scrolling at ' + width + ': ' + JSON.stringify(add));
            assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        }
        await page.setViewportSize({width: 390, height: 900});
        jobs = [activeJob(), ...Array.from({length: 9}, (_, i) => ({id: 'waiting-' + i, status: 'queued', title: 'Na fila ' + i, position: i + 1}))];
        await refresh();
        assert.equal(await page.locator('#queueCountBadge').textContent(), '9 aguardando');
        assert(!await page.locator('#creationFeedback').isVisible());
        await page.screenshot({path: 'queue-creation-progress-mobile.png'});

        // A fresh source selection replaces the old song, and live progress cannot close the editor.
        await page.evaluate(() => {document.getElementById('easyYoutubeUrl').value = 'https://youtube.com/watch?v=oldSong1234';});
        await startNew('easy');
        assert.equal(await page.locator('#easyYoutubeUrl').inputValue(), '');
        assert((await page.locator('#queueCreationNoticeText').textContent()).includes('em andamento'));
        await page.locator('#easyAudioFile').setInputFiles(file('draft.wav'));
        assert((await page.locator('#easySelectedMusic').textContent()).includes('draft.wav'));
        serverStatus.progress = 64;
        await refresh();
        await editorVisible('easy');
        assert.equal(await page.locator('#easyAudioFile').evaluate(input => input.files[0].name), 'draft.wav');
        jobs = []; serverStatus = {status: 'done', result_available_to_current_user: false};
        await refresh();
        await editorVisible('easy');
        assert((await page.locator('#queueCreationNoticeText').textContent()).includes('concluído'));
        assert.equal(await page.locator('#easyAudioFile').evaluate(input => input.files[0].name), 'draft.wav');
        serverStatus = processing(); jobs = [activeJob()];
        await refresh();
        await page.locator('#queueCreationNotice').scrollIntoViewIfNeeded();
        await page.screenshot({path: 'queue-creation-editor-mobile.png'});
        await page.locator('#btnReturnToProcess').click();
        await page.locator('#processCard').waitFor({state: 'visible'});
        assert.equal(submissions.length, 0, 'Returning must not submit or cancel work');

        // Exercise the real handlers for quick, detailed and SRT, with server replies deliberately held.
        for (const [mode, input, button] of [['easy', 'easyAudioFile', 'easySubmitBtn'], ['advanced', 'audioFile', 'btnSubmit'], ['subtitle', 'subtitleVideoFile', 'subtitleSubmitBtn']]) {
            await startNew(mode);
            const baseline = submissions.length;
            await page.locator('#' + input).setInputFiles([file(mode + '-one.wav'), file(mode + '-two.wav')]);
            await page.locator('#' + button).click();
            await untilSubmitted(baseline + 1);
            await loadingVisible();
            serverStatus.progress = 78;
            await refresh();
            await loadingVisible();
            if (mode === 'easy') {
                for (const status of ['done', 'waiting_for_user_correction', 'paused', 'busy', 'idle', 'error']) {
                    serverStatus = {status, can_cancel: false};
                    await refresh();
                    await loadingVisible();
                }
                serverStatus = processing();
                await refresh();
            }
            await pending.shift()();
            await untilSubmitted(baseline + 2);
            await loadingVisible();
            assert((await page.locator('#creationLoadingDetail').textContent()).includes('2 de 2'));
            if (mode === 'easy') await page.screenshot({path: 'queue-creation-loading-mobile.png'});
            await pending.shift()();
            await page.waitForFunction(() => !clientPreparationInProgress && !queueCreationExpanded);
            await page.locator('#processCard').waitFor({state: 'visible'});
            assert.equal(await page.locator('#' + input).evaluate(element => element.files.length), 0);
            assert(await page.locator('#queueCard').isVisible());
            assert.equal(await page.locator('#queueCountBadge').textContent(), (jobs.length - 1) + ' aguardando');
            assert(!await page.locator('#creationFeedback').isVisible());
            assert(!await page.locator('#queueCreationNotice').isVisible());
        }
        assert(submissions.find(item => item.filename === 'subtitle-one.wav').body.includes('name="subtitle_only"'));

        // Partial failure keeps only the unaccepted file and a polling update never destroys its retry.
        await startNew('easy');
        let baseline = submissions.length;
        await page.locator('#easyAudioFile').setInputFiles([file('accepted.wav'), file('retry.wav')]);
        await page.locator('#easySubmitBtn').click();
        await untilSubmitted(baseline + 1); await pending.shift()();
        await untilSubmitted(baseline + 2); await pending.shift()(400, {detail: 'Fila cheia: tente novamente.'});
        await page.waitForFunction(() => document.getElementById('creationFeedback').textContent.includes('Fila cheia'));
        await editorVisible('easy');
        await refresh(); await editorVisible('easy');
        assert.deepEqual(await page.locator('#easyAudioFile').evaluate(input => [...input.files].map(item => item.name)), ['retry.wav']);
        await page.locator('#easySubmitBtn').click();
        await untilSubmitted(baseline + 3); await loadingVisible(); await pending.shift()();
        await page.waitForFunction(() => !clientPreparationInProgress && !queueCreationExpanded);
        assert.equal(submissions.filter(item => item.filename === 'accepted.wav').length, 1);

        // HTTP 200 without a valid queue acknowledgement must not return to tracking or clear input.
        await startNew('easy'); baseline = submissions.length;
        await page.locator('#easyAudioFile').setInputFiles(file('unconfirmed.wav'));
        await page.locator('#easySubmitBtn').click();
        await untilSubmitted(baseline + 1); await pending.shift()(200, {});
        await untilSubmitted(baseline + 2); await pending.shift()(200, {});
        await page.waitForFunction(() => document.getElementById('creationFeedback').textContent.includes('não foi possível confirmar'));
        await editorVisible('easy');
        assert.equal(await page.locator('#easyAudioFile').evaluate(input => input.files[0].name), 'unconfirmed.wav');
        assert.equal(submissions[baseline].submissionId, submissions[baseline + 1].submissionId);
        await page.locator('#easySubmitBtn').click();
        await untilSubmitted(baseline + 3); await pending.shift()();
        assert.equal(submissions[baseline].submissionId, submissions[baseline + 2].submissionId, 'Manual retry must preserve the uncertain identifier');
        await page.waitForFunction(() => !clientPreparationInProgress && !queueCreationExpanded);

        // Lost acknowledgements and requests recover in all modes without duplicating YouTube jobs.
        for (const [mode, input, button, failure] of [['easy','easyYoutubeUrl','easySubmitBtn','after'],
            ['advanced','youtubeUrl','btnSubmit','before'], ['subtitle','subtitleYoutubeUrl','subtitleSubmitBtn','after']]) {
            await startNew(mode);
            if (mode === 'easy') await page.locator('[data-quick-source="youtube"]').click();
            if (mode === 'advanced') await page.locator('#btnAudioModeYoutube').click();
            await page.locator('#'+input).fill('https://youtu.be/abcdefghijk');
            await page.locator('#'+input).evaluate(input => {input.dataset.youtubeTitle='Artista - Música';});
            baseline=submissions.length;
            const jobCount=jobs.length;
            if (mode === 'subtitle') confirmationFailures=1;
            await page.locator('#'+button).click();
            await untilSubmitted(baseline + 1); await loadingVisible();
            assert(submissions[baseline].body.includes('name="youtube_url"'));
            assert(submissions[baseline].body.includes('name="source_title"'), mode+' source title must be submitted');
            await pending.shift()(200, undefined, failure);
            if (mode !== 'easy') {
                await untilSubmitted(baseline + 2);
                assert.equal(submissions[baseline].submissionId, submissions[baseline + 1].submissionId);
                await pending.shift()();
            }
            await page.waitForFunction(() => !clientPreparationInProgress && !queueCreationExpanded);
            assert.equal(jobs.length,jobCount+1, 'Recovery must accept only one '+mode+' YouTube job');
            assert(!await page.locator('#creationFeedback').isVisible());
            assert(!await page.locator('#'+input).isVisible(), 'Confirmed creation must return to tracking');
            serverStatus={...processing(),step:'Downloading YouTube',stage_progress:45,stage_detail:'Transferindo mídia'};
            await refresh();
            assert.equal(await page.locator('#statusMessage').textContent(),'Baixando mídia');
        }
        serverStatus=processing();await refresh();

        // A title arriving after an uncertain response is display metadata, not a different creation.
        baseline=submissions.length;
        const beforeMetadataRetry=jobs.length;
        confirmationFailures=2;
        await page.evaluate(() => {
            const form=new FormData();form.set('youtube_url','https://youtu.be/abcdefghijk');form.set('source_title','Video do YouTube');
            window.metadataRecoveryError='';
            submitProcessWithConfirmation(form).catch(error => {window.metadataRecoveryError=error.message;});
        });
        await untilSubmitted(baseline+1);await pending.shift()(200,undefined,'after');
        await untilSubmitted(baseline+2);await pending.shift()(200,undefined,'after');
        await page.waitForFunction(() => Boolean(window.metadataRecoveryError));
        await page.evaluate(() => {
            const form=new FormData();form.set('youtube_url','https://youtu.be/abcdefghijk');form.set('source_title','Artista - Titulo identificado');
            window.metadataRecoveryResult=null;
            submitProcessWithConfirmation(form).then(result => {window.metadataRecoveryResult=result;});
        });
        await untilSubmitted(baseline+3);await pending.shift()();
        await page.waitForFunction(() => Boolean(window.metadataRecoveryResult));
        assert.equal(submissions[baseline].submissionId,submissions[baseline+2].submissionId);
        assert.equal(jobs.length,beforeMetadataRetry+1);

        // When the previous job finishes, the accepted next item has its own waiting view.
        await startNew('easy'); baseline = submissions.length;
        jobs = []; serverStatus = {status: 'done', result_available_to_current_user: true, original_filename: 'old.mp4'};
        await refresh();
        await editorVisible('easy');
        await page.locator('#easyAudioFile').setInputFiles(file('after-finish.wav'));
        await page.locator('#easySubmitBtn').click();
        await untilSubmitted(baseline + 1); await pending.shift()();
        await page.waitForFunction(() => !clientPreparationInProgress && !queueCreationExpanded);
        await page.locator('#processCard').waitFor({state: 'visible'});
        assert.equal(await page.locator('#processStatusTitle').textContent(), '⏳ Aguardando');
        assert(!await page.locator('#easyModeForm').isVisible());
        assert(!await page.locator('#downloadBox').isVisible());
        assert.equal(await page.locator('#queueCountBadge').textContent(), '1 aguardando');
        queuePaused = true;
        await refresh();
        assert.equal(await page.locator('#processStatusTitle').textContent(), '⏸ Fila pausada');
        queuePaused = false; serverStatus = processing(); jobs[0].status = 'processing';
        await refresh();
        assert.equal(await page.locator('#processStatusTitle').textContent(), '⏳ Produzindo');
        assert(await page.locator('#queueCard').isVisible());

        // An asynchronous review load must not reopen its panel over a new-item draft.
        serverStatus = {status: 'waiting_for_user_correction', can_cancel: true};
        await refresh();
        await page.locator('#correctionCard .btn-add-queue').click();
        await page.locator('#btnCreatorEasy').click();
        await page.waitForFunction(() => queueCreationExpanded);
        assert(reviewResponse, 'Review request must have started');
        await reviewResponse();
        await page.waitForFunction(() => isShowingCorrection);
        await editorVisible('easy');
        await page.locator('#btnReturnToProcess').click();
        await page.locator('#correctionCard').waitFor({state: 'visible'});
        assert.equal(await page.locator('#correctionList textarea').first().inputValue(), 'Letra preservada');

        // Non-admin users can add while another profile is busy; the entry notice reveals no details.
        await page.evaluate(() => {currentUser = {username: 'another', role: 'user'};});
        serverStatus = {status: 'busy', can_cancel: false}; jobs = [];
        await refresh();
        await page.locator('#btnToggleQueueCreation').click();
        await editorVisible('easy');
        assert.equal(await page.locator('#queueCreationNoticeText').textContent(), 'Há um processamento em andamento.');
        await page.locator('#btnReturnToProcess').click();
        serverStatus = {status: 'paused', can_cancel: false}; queuePaused = true;
        await refresh();
        await page.locator('#btnToggleQueueCreation').click();
        await editorVisible('easy');
        assert((await page.locator('#queueCreationNoticeText').textContent()).includes('pausada'));
        await page.setViewportSize({width: 1440, height: 1000});
        await page.evaluate(() => setTheme('light'));
        await page.screenshot({path: 'queue-creation-editor-desktop.png'});
        assert.deepEqual(errors, []);
        console.log('Queue creation: three modes, lost YouTube acknowledgements, idempotent network/manual retries, download progress, uninterrupted drafts/loading, partial retry, review race, privacy, pause and five viewport sizes passed.');
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
