const assert = require('assert');
const {chromium} = require('playwright');
const HTML = require('./load_html.cjs')();

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/') return route.fulfill({contentType: 'text/html', body: HTML});
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(path === '/api/auth_status'
        ? {status: 'authenticated', username: 'owner', role: 'admin'} : {})});
    });
    await page.goto('http://karaoke.test');
    await page.waitForFunction(() => Boolean(currentUser));
    for (const mode of ['pending-post', 'proxy-timeout']) {
      const result = await page.evaluate(async mode => {
        const original = timedAuthFetch;
        let posts = 0, polls = 0, postTimeout = 0;
        const ids = [];
        timedAuthFetch = async (url, options, timeout) => {
          if (url === '/api/process') {
            posts++;
            postTimeout = timeout;
            ids.push(options.headers['x-submission-id']);
            if (mode === 'pending-post') return new Promise(() => {});
            return new Response('<h1>Gateway timeout</h1>', {status: 504});
          }
          if (url.startsWith('/api/queue/submissions/')) {
            polls++;
            ids.push(url.split('/').pop());
            return new Response(JSON.stringify(polls < 3 ? {status: 'preparing'}
              : {status: 'queued', job_id: 'accepted-' + mode, position: 1}), {
              headers: {'content-type': 'application/json'}});
          }
          return original(url, options, timeout);
        };
        try {
          const form = new FormData();
          form.set('youtube_url', 'https://youtu.be/abcdefghijk');
          form.set('source_title', mode);
          const receipt = await submitProcessWithConfirmation(form);
          return {receipt, posts, polls, postTimeout, ids,
            message: document.getElementById('creationLoadingDetail').textContent};
        } finally { timedAuthFetch = original; }
      }, mode);
      assert.equal(result.receipt.status, 'queued');
      assert.equal(result.posts, 1, 'An active preparation must not cause a second POST');
      assert.equal(result.polls, 3, 'Preparation must be polled until it becomes durable');
      assert.equal(result.postTimeout, 120000, 'A link must not be aborted after 20 seconds');
      assert.equal(new Set(result.ids).size, 1, 'Every confirmation uses the same identifier');
      assert(result.message.includes('acompanhada automaticamente'));
    }
    const rejected = await page.evaluate(async () => {
      const original = timedAuthFetch;
      timedAuthFetch = async url => new Response(JSON.stringify(url === '/api/process'
        ? {status: 'preparing'}
        : {status: 'rejected', http_status: 400, detail: 'A origem escolhida não está disponível.'}));
      try {
        const form = new FormData(); form.set('youtube_url', 'https://youtu.be/rejected001');
        await submitProcessWithConfirmation(form);
        return null;
      } catch (error) { return {message: error.message, confirmed: error.confirmedFailure}; }
      finally { timedAuthFetch = original; }
    });
    assert.equal(rejected.message, 'A origem escolhida não está disponível.');
    assert.equal(rejected.confirmed, true);
    assert.deepEqual(errors, []);
    console.log('Slow preparation, pending HTTP request, proxy timeout and explicit failure: confirmation passed.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exit(1);});
