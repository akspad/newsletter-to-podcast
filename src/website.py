"""Article-preview landing page, never populated with personal feed metadata."""
from html import escape
import os
from pathlib import Path
import shutil
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/akspad/newsletter-to-podcast"


def render(sample=False, demo_url=None, preview_api_url=None):
    if preview_api_url is not None and preview_api_url != "/api/preview":
        parsed_api = urlparse(preview_api_url)
        if (parsed_api.scheme != "https" or not parsed_api.hostname or parsed_api.username is not None
                or parsed_api.password is not None or parsed_api.fragment or parsed_api.query):
            raise ValueError("Preview API URL must be HTTPS without credentials, query or fragment")
    endpoint = escape(preview_api_url or "", quote=True)
    unavailable = "" if preview_api_url else f'<p class="notice">Live previews aren’t connected on this page yet. <a href="{REPO}#run-the-interactive-demo">Run the interactive demo locally</a>, or listen to the original sample below.</p>'
    disabled = "" if preview_api_url else " disabled"
    # Only the isolated --demo page may advertise its synthetic RSS feed.
    rss_metadata = ""
    demo_link = ""
    if demo_url is not None:
        parsed = urlparse(demo_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Demo URL must be an HTTP(S) URL without credentials, query or fragment")
        rss = escape(demo_url.rstrip("/") + "/feed.xml", quote=True)
        rss_metadata = f'<link rel="alternate" type="application/rss+xml" title="Original demo only" href="{rss}">'
        demo_link = f'<a class="button secondary" href="{rss}">Open original demo feed</a>'
    sample_player = f'''<section class="sample"><div><p class="eyebrow">HEAR AN ORIGINAL SAMPLE</p><h2>A little room for curiosity</h2><p>An original article narrated with Edge TTS. <a href="{REPO}/blob/main/samples/transcript.txt">Read the transcript</a>. MIT licensed and free to share.</p></div><audio controls preload="none" aria-label="Listen to the original demo sample" src="demo/sample.mp3"></audio></section>''' if sample else ""
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" sizes="any" href="favicon.svg">
<title>Newsletter to Podcast · Hear your next read</title>
<meta name="description" content="Paste a public newsletter or blog article and hear an audio preview of up to three minutes with Edge TTS. No login or API key needed.">
{rss_metadata}
<style>
:root {{ color-scheme: light; --ink: #172a25; --muted: #596962; --green: #18583c; --line: #dce3da; --paper: #f7f8f2; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; }}
a {{ color: var(--green); text-underline-offset: .22em; }}
a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible {{ outline: 3px solid #477e58; outline-offset: 4px; }}
.wrap {{ max-width: 1080px; margin: auto; padding: 0 28px; }}
header {{ display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 28px 0; border-bottom: 1px solid var(--line); }}
.brand {{ font-weight: 750; letter-spacing: -.03em; text-decoration: none; color: var(--ink); }}
.brand img {{ width: 28px; height: 28px; vertical-align: middle; margin-right: 7px; }}
.code {{ font-size: .86rem; }}
.hero {{ padding: 60px 0 28px; max-width: 800px; }}
.eyebrow {{ font-size: .72rem; letter-spacing: .16em; font-weight: 750; color: var(--green); margin: 0 0 12px; }}
h1 {{ font-size: clamp(2.4rem, 6vw, 4.5rem); line-height: 1.1; letter-spacing: -.055em; margin: 0 0 22px; overflow-wrap: anywhere; }}
.intro {{ font-size: 1.1rem; max-width: 620px; color: var(--muted); }}
.actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 26px; }}
.button {{ display: inline-block; padding: 11px 19px; border: 1px solid var(--green); border-radius: 8px; background: var(--green); color: white; font: inherit; font-weight: 650; text-decoration: none; cursor: pointer; }}
.secondary {{ background: transparent; color: var(--green); }}
.sample {{ display: grid; grid-template-columns: 1fr 1fr; align-items: center; gap: 28px; border: 1px solid var(--line); border-radius: 14px; padding: 28px; background: #eef2e7; margin-bottom: 48px; }}
.sample h2 {{ margin: 0; font-size: 1.4rem; letter-spacing: -.03em; }}
.sample p:last-child {{ color: var(--muted); font-size: .9rem; margin-bottom: 0; }}
.grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }}
audio {{ display: block; width: 100%; }}
footer {{ margin-top: 54px; border-top: 1px solid var(--line); padding: 28px 0 36px; color: var(--muted); font-size: .85rem; }}
footer p {{ margin: 6px 0; }}
[hidden] {{ display: none !important; }}
.preview {{ border: 1px solid var(--line); border-radius: 16px; background: white; padding: 30px; margin-bottom: 40px; box-shadow: 0 12px 32px #172a2506; }}
.preview h2 {{ margin: 0 0 8px; font-size: 1.4rem; letter-spacing: -.03em; }}
.preview label {{ display: block; font-weight: 650; margin-bottom: 8px; }}
.preview input, .preview textarea, .preview select {{ width: 100%; border: 1px solid #b7c4b9; border-radius: 8px; padding: 13px; background: var(--paper); color: var(--ink); font: inherit; min-width: 0; }}
.preview textarea {{ resize: vertical; min-height: 150px; }}
.preview input[type="radio"] {{ width: auto; accent-color: var(--green); }}
.input-modes {{ display: flex; flex-wrap: wrap; gap: 20px; border: 0; margin: 20px 0; padding: 0; }}
.input-modes legend {{ font-weight: 650; margin-bottom: 10px; }}
.input-modes label {{ font-weight: 400; margin: 0; cursor: pointer; }}
.preview-options {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 18px; margin-top: 20px; }}
.preview .button {{ min-height: 53px; }}
.button:disabled {{ opacity: .55; cursor: not-allowed; }}
.hint, .notice, #preview-status {{ font-size: .9rem; color: var(--muted); }}
.notice {{ padding: 12px 16px; background: #eef2e7; border-radius: 8px; }}
#preview-status[data-error="true"] {{ color: #a12a20; }}
.preview-result {{ margin-top: 24px; border-top: 1px solid var(--line); padding-top: 24px; }}
.preview-result h3 {{ margin-top: 0; }}
.preview-result .actions {{ margin-top: 16px; }}
@media(max-width: 640px) {{ .preview {{ padding: 22px; }} .preview-options {{ grid-template-columns: 1fr; }} header .code {{ white-space: nowrap; }} }}
@media(max-width: 640px) {{ .wrap {{ padding: 0 18px; }} header {{ padding: 20px 0; }} .hero {{ padding-top: 42px; }} .sample, .grid {{ grid-template-columns: 1fr; }} .sample {{ padding: 22px; gap: 20px; }} .section-head {{ align-items: stretch; }} input {{ width: 100%; }} }}
</style>
<style>.feature {{ background: white; border: 1px solid var(--line); border-radius: 12px; padding: 24px; }} .feature h2 {{ margin: 0 0 12px; font-size: 1.15rem; }} .feature p {{ color: var(--muted); margin: 0; font-size: .95rem; }} .quick-start {{ margin-top: 38px; }} code {{ display: inline-block; padding: 10px 14px; background: #eef2e7; border-radius: 8px; overflow-wrap: anywhere; }} @media(max-width:640px) {{ .grid {{ grid-template-columns:1fr; }} }}</style>
</head>
<body><div class="wrap">
<header><a class="brand" href="./"><img src="favicon.svg" alt="" width="28" height="28">Newsletter to Podcast</a><a class="code" href="{REPO}">Get the code ↗</a></header>
<main>
<section class="hero"><p class="eyebrow">YOUR READING, READY TO LISTEN</p><h1>Hear your next read.</h1><p class="intro">Bring an article from your favorite newsletter or blog. Turn it into an audio preview of up to three minutes, free with Edge TTS. No login. No API key.</p></section>
<section class="preview" aria-labelledby="preview-heading">
<h2 id="preview-heading">Try it with your own article</h2><p class="hint">Paste a public article link, choose a voice, and press play when your preview is ready.</p>
{unavailable}
<form id="preview-form" data-endpoint="{endpoint}">
<fieldset class="input-modes"><legend>Bring your article</legend><label><input type="radio" name="input-mode" value="url" checked> Article link</label><label><input type="radio" name="input-mode" value="text"> Paste text</label></fieldset>
<div id="url-input"><label for="article-url">Public article URL</label><input id="article-url" name="url" type="url" placeholder="https://your-favorite-blog.com/an-article" maxlength="8192" aria-describedby="article-help" required></div>
<div id="text-input" hidden><label for="article-text">Article text</label><textarea id="article-text" name="text" placeholder="Paste the article or an excerpt here…" maxlength="100000" disabled></textarea></div>
<p class="hint" id="article-help">Use a direct article link. If a site blocks access or needs a login, try pasting text you can access.</p>
<div class="preview-options"><div><label for="preview-voice">Narrator</label><select id="preview-voice" name="voice"><option value="en-US-AndrewNeural">Andrew · English (US)</option><option value="en-US-AriaNeural">Aria · English (US)</option><option value="en-GB-SoniaNeural">Sonia · English (UK)</option></select></div><button class="button" id="generate-preview" type="submit"{disabled}>Generate audio preview</button></div>
<p class="hint">Up to 3 minutes · Opening excerpt · Usually ready within two minutes</p>
<p class="hint">Your link or text goes to the preview service; narration text goes to Microsoft’s Edge TTS service. Previews aren’t added to a public feed.</p>
</form>
<p id="preview-status" role="status" aria-live="polite"></p>
<div id="preview-result" class="preview-result" hidden><h3>Your article, ready to listen</h3><audio id="preview-audio" controls preload="metadata" aria-label="Listen to your article preview"></audio><div class="actions"><a id="preview-download" download="article-preview.mp3">Download MP3</a><a id="preview-source" target="_blank" rel="noopener noreferrer" hidden>Read the original article ↗</a></div></div>
<noscript><p>Enable JavaScript to generate a preview. You can still play the original sample below.</p></noscript>
</section>
{sample_player}
<section class="grid" aria-label="What the tool does">
<article class="feature"><h2>Full reads or summaries</h2><p>Full article narration is free with Edge TTS. Spoken summaries can use Gemini's free tier, subject to eligible models and quotas.</p></article>
<article class="feature"><h2>Your preferred length</h2><p>Set a maximum episode duration. Longer full readings split into parts.</p></article>
<article class="feature"><h2>Your own installation</h2><p>Run locally or in your own GitHub repository. Choose your sources and where to host your audio.</p></article>
</section>
<section class="quick-start"><h2>Make it part of your listening routine</h2><p>Liked the preview? Turn your newsletters into a personal podcast feed. Narrate full articles or make spoken summaries, and listen in your usual podcast app.</p><div class="actions"><a class="button secondary" href="{REPO}#generate-full-articles-from-your-own-sources">Set up your own podcast ↗</a>{demo_link}</div></section>
</main>
<footer><p><a href="{REPO}">Newsletter to Podcast</a> is an open-source Python tool. The code and original demo are MIT licensed.</p><p>Built by <a href="https://x.com/akspad">@akspad</a></p><p>Use sources you are authorized to access and convert. Share generated audio only with permission.</p></footer>
</div><script src="preview.js" defer></script></body></html>
'''


def write(site, demo_url=None):
    # Deliberately accept no episode list, feed title, source URLs or personal feed address.
    shutil.copyfile(ROOT / "src" / "favicon.svg", site / "favicon.svg")
    shutil.copyfile(ROOT / "src" / "preview.js", site / "preview.js")
    sample = ROOT / "samples" / "demo.mp3"
    available = sample.exists()
    if available:
        (site / "demo").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample, site / "demo" / "sample.mp3")
    (site / "index.html").write_text(render(available, demo_url, os.environ.get("PREVIEW_API_URL") or None), encoding="utf-8")
