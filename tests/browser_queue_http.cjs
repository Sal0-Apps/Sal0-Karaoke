const assert = require('assert');
const {spawn} = require('child_process');
const readline = require('readline');
const {chromium} = require('playwright');

(async () => {
  for (const mode of ['empty', 'cleared', 'locked']) {
    const server = spawn(process.env.PYTHON || 'python', ['tests/queue_http_fixture.py', mode], {stdio: ['ignore', 'pipe', 'pipe']});
    let logs = '';
    server.stderr.on('data', data => { logs += data; });
    let browser;
    try {
        const line = await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('HTTP fixture did not start: '+logs)), 15000);
            readline.createInterface({input: server.stdout}).once('line', value => {clearTimeout(timer); resolve(value);});
            server.once('exit', code => {clearTimeout(timer); reject(new Error('HTTP fixture exited '+code+': '+logs));});
        });
        const origin = `http://127.0.0.1:${JSON.parse(line).port}`;
        browser = await chromium.launch({headless: true});
        const page = await browser.newPage({viewport: {width: 390, height: 900}});
        await page.goto(origin);
        await page.waitForFunction(() => Boolean(currentUser));
        const guide = 'Guia preservada\nMesmo refrão\nMesmo refrão';
        const result = await page.evaluate(async guide => {
            const data = new FormData();
            data.set('youtube_url', 'https://youtu.be/XHsT0RPE6nk');
            data.set('source_title', 'High Enough to Carry You Over');
            data.set('easy_mode', 'true');
            data.set('easy_background_choice', 'original');
            data.set('lyrics_text', guide); data.set('lyrics_selected', 'true');
            data.set('audio_file', new File([], '')); // Browser's unselected file field.
            const started = performance.now();
            const receipt = await submitProcessWithConfirmation(data);
            const retry = await authFetch('/api/process', processRequestOptions(data));
            return {receipt, retry: await retry.json(), elapsed: performance.now()-started};
        }, guide);
        assert.equal(result.receipt.status, 'queued');
        assert.equal(result.receipt.job_id, result.retry.job_id);
        assert(result.elapsed < 5000, mode+' cache must not delay a link submission: '+result.elapsed);
        const state = await (await page.request.get(origin+'/__test__/jobs')).json();
        assert.equal(state.jobs.length, mode === 'locked' ? 2 : 1, 'Exactly one new job must be accepted');
        const job = state.jobs.at(-1);
        assert.equal(job.lyrics, guide);
        assert.equal(job.owner, 'alice');
        assert.equal(job.source, 'https://youtu.be/XHsT0RPE6nk');
        assert(state.encodings.every(value => value.startsWith('application/x-www-form-urlencoded')));
        const confirmation = await page.request.get(origin+'/api/queue/submissions/'+job.submission_id);
        assert.equal(confirmation.status(), 200);
        console.log('Real browser -> HTTP -> FastAPI: '+mode+' queue, complete guide, durable receipt and duplicate retry passed.');
    } finally {
        if (browser) await browser.close();
        server.kill('SIGTERM');
        await new Promise(resolve => {
            if(server.exitCode !== null || server.signalCode !== null) return resolve();
            const timer = setTimeout(() => server.kill('SIGKILL'), 3000);
            server.once('exit', () => {clearTimeout(timer); resolve();});
        });
    }
  }
})().catch(error => {console.error(error); process.exit(1);});
