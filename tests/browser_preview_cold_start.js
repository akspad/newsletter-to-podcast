(async () => {
  const nativeFetch = window.fetch.bind(window);
  const sample = await (await nativeFetch('demo/sample.mp3')).arrayBuffer();
  const form = document.querySelector('#preview-form');
  const button = document.querySelector('#generate-preview');
  const result = document.querySelector('#preview-result');
  const status = document.querySelector('#preview-status');
  let healthChecks = 0;
  let posts = 0;
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
    await waitFor(() => !result.hidden);
    if (healthChecks !== 2 || posts !== 1) throw new Error('Cold start duplicated generation or failed to retry health');
    if (submitted.text !== 'An original passage to test the preview.' || submitted.voice !== 'en-GB-SoniaNeural') throw new Error('Form values changed during wake-up');
    if (button.disabled || form.hasAttribute('aria-busy')) throw new Error('Form stayed busy after success');

    window.fetch = async () => new Response('', {status: 404});
    form.requestSubmit();
    await waitFor(() => status.dataset.error === 'true');
    if (posts !== 1 || !result.hidden || button.disabled) throw new Error('Unhealthy service generated audio or prevented retry');

    window.fetch = async () => { throw new DOMException('Timed out', 'AbortError'); };
    form.requestSubmit();
    await waitFor(() => status.dataset.error === 'true');
    if (!status.textContent.includes('took too long') || button.disabled) throw new Error('Wake-up timeout was not actionable');
    return 'Verified cold-start recovery, one generation request, service errors and timeout recovery';
  } finally {
    window.fetch = nativeFetch;
  }
})()
