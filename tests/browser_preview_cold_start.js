(async () => {
  const nativeFetch = window.fetch.bind(window);
  const sample = await (await nativeFetch('demo/sample.mp3')).arrayBuffer();
  const form = document.querySelector('#preview-form');
  const button = document.querySelector('#generate-preview');
  const result = document.querySelector('#preview-result');
  const status = document.querySelector('#preview-status');
  const timing = document.querySelector('#preview-timing');
  const eta = document.querySelector('#preview-eta');
  const elapsed = document.querySelector('#preview-elapsed');
  const nativeNow = Date.now;
  let healthChecks = 0;
  let posts = 0;
  let generated = 0;
  let submitted;
  const waitFor = async (condition) => {
    const deadline = Date.now() + 10000;
    while (!condition()) {
      if (Date.now() > deadline) throw new Error('Preview browser check timed out');
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  };
  try {
    window.fetch = async (input, init = {}) => {
      const url = new URL(input, window.location.href);
      if (url.pathname === '/health') {
        healthChecks++;
        return healthChecks === 1
          ? new Response('<html>Service is starting</html>', {status: 503})
          : Response.json({status: 'ok'});
      }
      if (url.pathname === '/api/preview') {
        posts++;
        submitted = JSON.parse(init.body);
        if (posts === 1) return Response.json({code: 'preview_busy', error: 'Another preview is running'}, {status: 503, headers: {'Retry-After': '1'}});
        generated++;
        return new Response(sample, {headers: {'Content-Type': 'audio/mpeg'}});
      }
      return nativeFetch(input, init);
    };
    form.dataset.endpoint = '/api/preview';
    button.disabled = false;
    document.querySelector('input[name="input-mode"][value="text"]').click();
    document.querySelector('#article-text').value = 'An original passage to test the preview.';
    document.querySelector('#preview-voice').value = 'en-GB-SoniaNeural';
    form.requestSubmit();
    if (!button.disabled || posts !== 0) throw new Error('Generation started before the service woke');
    if (timing.hidden || timing.dataset.phase !== 'waking' || !eta.textContent.includes('Estimated wake-up') || elapsed.textContent !== 'Elapsed: 0s') throw new Error('Wake-up estimate did not start');
    await waitFor(() => status.textContent.includes('Another preview is finishing'));
    if (timing.dataset.phase !== 'waiting' || !eta.textContent.includes('wait + audio')) throw new Error('Queue estimate did not include generation');
    document.querySelector('#article-text').value = 'Edited while waiting; do not substitute this for the submitted text.';
    await waitFor(() => !result.hidden);
    if (healthChecks !== 2 || posts !== 2 || generated !== 1) throw new Error('Cold start or capacity retry duplicated generation');
    if (submitted.text !== 'An original passage to test the preview.' || submitted.voice !== 'en-GB-SoniaNeural') throw new Error('Form values changed during wake-up');
    if (button.disabled || form.hasAttribute('aria-busy')) throw new Error('Form stayed busy after success');
    if (!timing.hidden || eta.textContent || elapsed.textContent) throw new Error('Timer stayed active after success');

    let finishAudio;
    const heldAudio = new Promise((resolve) => { finishAudio = resolve; });
    window.fetch = async (input) => {
      if (new URL(input, window.location.href).pathname === '/health') return Response.json({status: 'ok'});
      await heldAudio;
      return new Response(sample, {headers: {'Content-Type': 'audio/mpeg'}});
    };
    document.querySelector('input[name="input-mode"][value="url"]').click();
    document.querySelector('#article-url').value = 'https://example.com/article';
    form.requestSubmit();
    if (elapsed.textContent !== 'Elapsed: 0s') throw new Error('New request retained previous elapsed time');
    await waitFor(() => timing.dataset.phase === 'generating');
    const initialEta = eta.textContent;
    if (!initialEta.includes('30s–2m')) throw new Error('Article URL did not use the conservative estimate');
    Date.now = () => nativeNow() + 10000;
    await new Promise((resolve) => setTimeout(resolve, 1100));
    if (eta.textContent === initialEta || !/Elapsed: 1\ds/.test(elapsed.textContent)) throw new Error('ETA and elapsed time did not advance');
    Date.now = () => nativeNow() + 130000;
    await new Promise((resolve) => setTimeout(resolve, 1100));
    if (!eta.textContent.includes('Taking longer than estimated') || !elapsed.textContent.includes('2m')) throw new Error('Overdue estimate showed a misleading zero countdown');
    Date.now = nativeNow;
    finishAudio();
    await waitFor(() => !result.hidden);
    if (!timing.hidden) throw new Error('Timer stayed visible after delayed audio');

    let compatiblePosts = 0;
    window.fetch = async (input) => {
      if (new URL(input, window.location.href).pathname === '/health') return Response.json({status: 'ok'});
      compatiblePosts++;
      if (compatiblePosts === 1) return Response.json({error: 'The preview service is busy. Please try again shortly.'}, {status: 503, headers: {'Retry-After': '1'}});
      return new Response(sample, {headers: {'Content-Type': 'audio/mpeg'}});
    };
    form.requestSubmit();
    await waitFor(() => !result.hidden);
    if (compatiblePosts !== 2) throw new Error('Previous backend busy response did not recover');

    let failedPosts = 0;
    window.fetch = async (input) => {
      if (new URL(input, window.location.href).pathname === '/health') return Response.json({status: 'ok'});
      failedPosts++;
      return Response.json({error: 'Speech provider is unavailable'}, {status: 503});
    };
    form.requestSubmit();
    await waitFor(() => status.dataset.error === 'true');
    if (failedPosts !== 1) throw new Error('A provider failure replayed generation');
    if (!timing.hidden || eta.textContent || elapsed.textContent) throw new Error('Timer stayed active after failure');

    window.fetch = async () => new Response('', {status: 404});
    form.requestSubmit();
    await waitFor(() => status.dataset.error === 'true');
    if (posts !== 2 || !result.hidden || button.disabled) throw new Error('Unhealthy service generated audio or prevented retry');

    window.fetch = async () => { throw new DOMException('Timed out', 'AbortError'); };
    form.requestSubmit();
    await waitFor(() => status.dataset.error === 'true');
    if (!status.textContent.includes('took too long') || button.disabled) throw new Error('Wake-up timeout was not actionable');
    return 'Verified ETA countdown, elapsed time, overdue/reset states, cold-start and busy recovery, and error handling';
  } finally {
    window.fetch = nativeFetch;
    Date.now = nativeNow;
  }
})()
