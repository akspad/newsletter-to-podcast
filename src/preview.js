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

  function pause(milliseconds, signal) {
    return new Promise((resolve, reject) => {
      const abort = () => {
        clearTimeout(timer);
        reject(new DOMException('Preview request timed out', 'AbortError'));
      };
      const timer = setTimeout(() => {
        signal.removeEventListener('abort', abort);
        resolve();
      }, milliseconds);
      if (signal.aborted) abort();
      else signal.addEventListener('abort', abort, {once: true});
    });
  }

  async function requestPreview(payload, signal) {
    const capacityDeadline = Date.now() + 120000;
    while (true) {
      const response = await fetch(form.dataset.endpoint, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        credentials: 'omit', referrerPolicy: 'no-referrer', signal, body: payload,
      });
      if (response.ok) return response;
      const error = await response.json().catch(() => ({}));
      // Retry only a confirmed rejection before generation started. Support
      // the previous backend's exact busy response while a deploy rolls out.
      const busy = response.status === 503 && (error.code === 'preview_busy' ||
        error.error === 'The preview service is busy. Please try again shortly.');
      if (!busy) throw new Error(typeof error.error === 'string' ? error.error : 'The preview service is unavailable. Please try again shortly.');
      const delay = Math.min(15, Math.max(1, Number(response.headers.get('Retry-After')) || 5)) * 1000;
      if (Date.now() + delay >= capacityDeadline) {
        throw new Error('The demo is still handling other previews. Please try again in a couple of minutes.');
      }
      button.textContent = 'Waiting for your preview…';
      status.textContent = 'Another preview is finishing. Yours will start automatically when a slot opens. Waiting and generation can take up to four minutes.';
      await pause(delay, signal);
    }
  }

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
        // Wake-up retries only check health; they never start generation.
        if (error.name === 'AbortError' || !(error instanceof TypeError || error instanceof SyntaxError)) throw error;
      }
      await pause(2000, signal);
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
    const payload = JSON.stringify({url: articleUrl, text: paste ? text.value.trim() : '', voice: form.elements.voice.value});
    let timeout = setTimeout(() => controller.abort(), 90000);
    try {
      await waitForService(controller.signal);
      clearTimeout(timeout);
      // Allow up to two minutes waiting for capacity, plus a two-minute job.
      timeout = setTimeout(() => controller.abort(), 250000);
      status.textContent = paste ? 'Turning your text into speech. This can take up to two minutes…' : 'Reading your article and generating speech. This can take up to two minutes…';
      const response = await requestPreview(payload, controller.signal);
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
