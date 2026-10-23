(() => {
  const form = document.getElementById('preview-form');
  if (!form) return;
  const url = document.getElementById('article-url');
  const text = document.getElementById('article-text');
  const button = document.getElementById('generate-preview');
  const status = document.getElementById('preview-status');
  const result = document.getElementById('preview-result');
  const audio = document.getElementById('preview-audio');
  const source = document.getElementById('preview-source');
  let audioUrl;
  let pending = false;

  async function waitForService(signal) {
    const endpoint = new URL(form.dataset.endpoint, window.location.href);
    const health = new URL('../health', endpoint);
    while (!signal.aborted) {
      try {
        const response = await fetch(health, {
          headers: {'Accept': 'application/json'}, credentials: 'omit',
          referrerPolicy: 'no-referrer', signal,
        });
        if ([403, 404].includes(response.status)) {
          throw new Error('The preview service is not configured correctly. Please try again later.');
        }
        if (response.ok && (await response.json()).status === 'ok') return;
      } catch (error) {
        // Render may return a loading page while a free service spins up.
        // Retry only the health check; never submit generation twice.
        if (error.name === 'AbortError' || !(error instanceof TypeError || error instanceof SyntaxError)) throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new DOMException('Service wake-up timed out', 'AbortError');
  }

  form.addEventListener('change', () => {
    const paste = form.elements['input-mode'].value === 'text';
    document.getElementById('url-input').hidden = paste;
    document.getElementById('text-input').hidden = !paste;
    url.disabled = paste;
    url.required = !paste;
    text.disabled = !paste;
    text.required = paste;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!form.dataset.endpoint || pending || !form.reportValidity()) return;
    const paste = form.elements['input-mode'].value === 'text';
    const articleUrl = paste ? '' : url.value.trim();
    if (articleUrl && !['https:', 'http:'].includes(new URL(articleUrl).protocol)) {
      status.textContent = 'Use a public article link starting with https:// or http://.';
      status.dataset.error = 'true';
      return;
    }
    pending = true;
    button.disabled = true;
    button.textContent = 'Generating your preview…';
    form.setAttribute('aria-busy', 'true');
    status.dataset.error = 'false';
    status.textContent = 'Connecting to the preview service. If it is asleep, waking it can take about a minute…';
    audio.pause();
    result.hidden = true;
    const controller = new AbortController();
    let timeout = setTimeout(() => controller.abort(), 90000);
    try {
      await waitForService(controller.signal);
      clearTimeout(timeout);
      timeout = setTimeout(() => controller.abort(), 130000);
      status.textContent = paste ? 'Turning your text into speech. This can take up to two minutes…' : 'Reading your article and generating speech. This can take up to two minutes…';
      const response = await fetch(form.dataset.endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
        signal: controller.signal,
        body: JSON.stringify({url: articleUrl, text: paste ? text.value.trim() : '', voice: form.elements.voice.value}),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.error === 'string' ? error.error : 'The preview service is unavailable. Please try again shortly.');
      }
      if (!response.headers.get('Content-Type')?.startsWith('audio/mpeg')) throw new Error('The service did not return audio. Please try again.');
      const blob = await response.blob();
      if (!blob.size || blob.size > 2 * 1024 * 1024) throw new Error('The service returned an invalid audio preview.');
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      audioUrl = URL.createObjectURL(blob);
      audio.src = audioUrl;
      document.getElementById('preview-download').href = audioUrl;
      source.hidden = !articleUrl;
      if (articleUrl) source.href = articleUrl;
      else source.removeAttribute('href');
      result.hidden = false;
      status.textContent = 'Your preview is ready. Press play to listen.';
    } catch (error) {
      status.dataset.error = 'true';
      status.textContent = error.name === 'AbortError' ? 'The preview service took too long to respond. Try a shorter excerpt or try again shortly.' : error instanceof TypeError ? 'Couldn’t reach the preview service. Please try again shortly.' : error.message;
    } finally {
      clearTimeout(timeout);
      pending = false;
      button.disabled = false;
      button.textContent = 'Generate audio preview';
      form.removeAttribute('aria-busy');
    }
  });
  window.addEventListener('pagehide', (event) => { if (audioUrl && !event.persisted) URL.revokeObjectURL(audioUrl); });
})();
