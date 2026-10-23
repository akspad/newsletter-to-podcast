# Newsletter to Podcast

Turn newsletters and blogs into an RSS podcast **for free**, then listen in your usual podcast app.

Full article narration uses Edge TTS, with **no API key or paid TTS subscription required**. Optional spoken summaries can use [Gemini's free tier](https://ai.google.dev/gemini-api/docs/pricing), subject to eligible models and quotas.

Choose **spoken summaries** or **full article narration**. Set a maximum episode length; long full articles become multiple parts rather than losing the rest of the article.

**[Try the article-to-audio demo](https://akspad.github.io/newsletter-to-podcast/)** · [Run the interactive demo](#run-the-interactive-demo) · [Offline sample](#quick-start-hear-a-sample-in-under-a-minute)

The demo leads with your own reading: paste a public article URL or its text, choose a voice, and generate an opening excerpt of **up to three minutes** with Edge TTS. No Microsoft login, API key or Gemini account is needed. Live previews require the small backend below; a static page without a connected backend explains this and offers the original audio sample.

- Reads Substack publications, RSS and Atom feeds, and simple article listing pages.
- Generates summaries with Gemini and audio with Edge TTS.
- Produces MP3s with podcast loudness normalization and an RSS feed.
- Runs locally or on a configurable schedule in your own GitHub repository: four times a day by default.
- Keeps your source list, credentials, and processing state out of the shared code.

The personal podcast pipeline is a Python command-line project. The optional demo backend generates individual previews without reading your subscriptions or writing to your podcast feed. The project reads the text a source makes available to you; it does not bypass paywalls, and feed excerpts may be shorter than the original article.

Built by [@akspad](https://x.com/akspad)

## Run the interactive demo

Install Python 3.12+, ffmpeg (including ffprobe), and the dependencies using the [installation commands](#generate-full-articles-from-your-own-sources), then run:

```sh
python src/preview_server.py
```

Open **http://localhost:8000/**, paste a direct public article link or select **Paste text**, choose a narrator, and select **Generate audio preview**. The result has a player, MP3 download and original-article link. The preview narrates the opening excerpt, not a summary. It selects up to 390 words / 3,000 characters and measures the finished MP3 to enforce a strict 180-second limit. The final limit can cut the ending for a slow voice. All three bundled voices speak English.

Public URLs use the same bounded, DNS-pinned downloader as the podcast pipeline, with every redirect checked against private and reserved destinations. Extraction looks for an article or main-content element; blocked sites, paywalls and some page layouts need the paste-text fallback. Edge TTS is an unofficial online service and can change or become unavailable.

### Connect the GitHub Pages demo

GitHub Pages serves the interface but cannot run Python or generate speech. Host the backend on a Linux service with Python and ffmpeg, expose it over HTTPS, and run one instance with:

```sh
PREVIEW_HOST=0.0.0.0 PORT=8000 \
PREVIEW_ALLOWED_ORIGINS=https://akspad.github.io \
python src/preview_server.py
```

Use your own Pages **origin** in `PREVIEW_ALLOWED_ORIGINS` (no repository path or trailing slash). Multiple exact origins can be comma-separated. Set the GitHub repository **variable** `PREVIEW_API_URL` to `https://YOUR-BACKEND-HOST/api/preview`, then run the existing Newsletter podcast workflow to rebuild/publish the landing page. This variable is a public endpoint, not a secret. Local static builds can set the same environment variable when running `--demo`. Until it is configured, generation is disabled with a local-setup link; the original sample remains playable.

The API accepts `POST /api/preview` with JSON containing either `url` or `text`, plus an optional `voice`. It returns MP3 bytes directly; `/health` reports process health without calling providers. Configure a hosting request timeout above 120 seconds and HTTPS termination. Run the demo separately from your personal pipeline without subscription secrets or mounted private state.

The server allows two simultaneous jobs, five attempts per client address per ten minutes, and sixty attempts total per hour. Limits are in memory and reset on restart. Behind a reverse proxy, clients share its address and therefore its five-attempt limit; forwarded IP headers are deliberately not trusted. For multiple instances or a larger public demo, put shared rate limiting at the gateway. The worker and its subprocesses are terminated after two minutes. Temporary audio files are removed after every job; audio returns only to the requesting browser and is never added to RSS or a public gallery. Access logs are disabled in the app; configure your host's logs separately. Text goes to Microsoft for speech generation.

## Quick start: hear a sample in under a minute

Try an original article and a working podcast feed before configuring any sources. This demo uses bundled audio, so it needs **Python 3.12+ only**: no API keys, provider SDKs, ffmpeg, or live feed access.

```sh
git clone https://github.com/akspad/newsletter-to-podcast.git
cd newsletter-to-podcast
python3.12 src/main.py --demo
python3.12 -m http.server 8000 --bind 127.0.0.1 --directory site-demo
```

Open **http://localhost:8000/** and press play. The page has an audio player, a source link and an RSS link. The demo creates a separate `site-demo/` directory and leaves your subscriptions, generated episodes and processing state alone. It refuses to overwrite a nonempty directory that is not already a demo. Stop the server with Ctrl+C.

The sample, [A little room for curiosity](samples/transcript.txt), is original MIT-licensed content narrated with the project's normal Edge TTS voice. [Listen to the sample MP3](https://akspad.github.io/newsletter-to-podcast/demo/sample.mp3). This prerecorded demo verifies the listening and RSS experience; generating new audio uses the live providers described below.

## Generate full articles from your own sources

You need **Python 3.12+**, **ffmpeg** (including ffprobe), and a POSIX filesystem with owner-only permissions, such as on macOS or Linux. Native Windows generation is not supported; use Linux through WSL with the project and state on its Linux filesystem. The bundled `--demo` does not require these state protections. On macOS: `brew install python@3.12 ffmpeg`. On Ubuntu: install Python 3.12 and `sudo apt-get install ffmpeg python3-venv`.

```sh
git clone https://github.com/akspad/newsletter-to-podcast.git
cd newsletter-to-podcast
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
```

### Generate your first episode

Copy and paste this command to fetch an original, MIT-licensed article from the project's public RSS source and generate **new audio with Edge TTS**. No API key is needed. This exercises source fetching, text extraction, narration and podcast RSS generation; unlike `--demo`, it does not use prerecorded audio.

```sh
PUBLICATIONS="https://raw.githubusercontent.com/akspad/newsletter-to-podcast/main/samples/source.xml Original sample | rss | full" \
EPISODE_MODE=full \
LOOKBACK_HOURS=87600 \
MAX_EPISODE_MINUTES=10 \
SITE_DIR=site-first-episode \
STATE_DIR=.state-first-episode \
SITE_URL=http://localhost:8000 \
PUBLISH_TO_PAGES=false \
python src/main.py

python -m http.server 8000 --bind 127.0.0.1 --directory site-first-episode
```

Generation needs internet access and may take a minute. Open **http://localhost:8000/feed.xml** for your newly generated episode's MP3 link, or open the MP3 in `site-first-episode/episodes/`. The root page still plays the bundled demo. Stop the server with Ctrl+C.

The long lookback includes the sample's fixed publication date. Output and processing history use separate, ignored directories. Running the command again skips the completed sample; to regenerate it, remove only `site-first-episode/` and `.state-first-episode/`, then run it again.

### Use your own sources

```sh
cp publications.example.txt publications.txt
cp .env.example .env
```

Edit `publications.txt` with your own source URLs. The example file contains placeholder domains, so replace them before running. In `.env`, set:

```dotenv
EPISODE_MODE=full
MAX_EPISODE_MINUTES=10
```

The example source file includes a per-source `summary` example: remove that line or change it to `full` for a run without a Gemini key.

```sh
python src/main.py --env-file .env --check
python src/main.py --env-file .env
python -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open `http://localhost:8000/feed.xml` to inspect your personal feed. The root page shows the project demo, without your personal episode list. To listen on another device, host the contents of `site/` at a URL your podcast app can reach and set `SITE_URL` to that address before generating it. Choose authenticated hosting if the content should be private; the local HTTP preview has no access controls.

Full narration uses Edge TTS and needs internet access, but does not require Gemini. Summary mode needs a Gemini API key.

## Spoken summaries

Create a key at [Google AI Studio](https://aistudio.google.com/) and put it in your ignored `.env`:

```dotenv
GEMINI_API_KEY=your-key
EPISODE_MODE=summary
MAX_EPISODE_MINUTES=5
```

The script budgets roughly 130 spoken words per minute, up to `MAX_SCRIPT_WORDS`. The final audio is capped to the configured duration. If a voice is unusually slow, the hard cap can cut the ending; reduce `MAX_SCRIPT_WORDS` to leave more headroom.

Full narration does not use the summary model. Changing modes affects new articles; already completed articles are not regenerated.

## Choose your sources

One URL per line, followed by an optional display name and options:

```text
https://newsletter.example.com Example Newsletter
https://blog.example.com/feed Example Blog | rss | full
https://another.example.com/atom.xml Example Digest | summary | only: Weekly | any length
https://example.com Example Site | page: /stories/ | full
```

| Option | Behavior |
| --- | --- |
| `full` | Narrate all the available article text; override the global mode. |
| `summary` | Generate a spoken summary; override the global mode. |
| `only: Weekly` | Match titles containing this text, ignoring case. Explicit matches bypass length/audio filtering. |
| `any length` | Allow short articles in summary mode. |
| `rss` | Read RSS or Atom. Feed URLs ending in `/feed`, `/rss`, or `.xml` are also detected automatically. |
| `page: /stories/` | Read a simple HTML listing with article paths and dated article bodies. This is a heuristic, not a general crawler. |

By default, summary mode selects posts with at least 1,500 words and no playable attached audio. Full mode takes every recent post, including ones that already have audio.

The source list is explicit: the program never imports your account's subscriptions automatically. `PUBLICATIONS` can contain the same multiline text instead of a file; if set, it takes precedence over `PUBLICATIONS_FILE`.

For optional authenticated Substack access, put `SUBSTACK_SID` and a comma-separated `SUBSTACK_AUTH_HOSTS` list in `.env` or repository secrets. Use exact hostnames, without schemes or paths. The cookie is sent only to HTTPS URLs on those hosts, including after redirects. Authentication and Substack's unofficial endpoints may not work from every network.

## Configuration

Use `.env` with `--env-file`, exported environment variables, or the Actions variables listed below. Existing environment variables take precedence over the env file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EPISODE_MODE` | `summary` | `summary` or `full`; per-source options override it. |
| `MAX_EPISODE_MINUTES` | `10` | Maximum duration per MP3, in minutes. Full articles split into parts. `0` disables the per-MP3 duration cap; overall narration and other security ceilings still apply. |
| `MAX_SCRIPT_WORDS` | `700` | Additional summary word limit, including its introduction. |
| `MIN_WORDS` | `1500` | Minimum article length in default summary selection. |
| `LOOKBACK_HOURS` | automatic: at least `168` | Scan the past week and cover longer gaps with a 48-hour overlap before the last complete source scan. Set a value only to override this for a specific backfill. |
| `RUNS_PER_DAY` | `4` | Target scheduled podcast runs per UTC day, from `1` to `24`. Set an Actions repository variable to change cadence without editing cron. |
| `MAX_EPISODES_PER_RUN` | `20` | Maximum articles processed per run; a full article can produce several MP3s. |
| `KEEP_EPISODES` | `0` | Retain all articles by default. A positive value limits retained articles; all parts stay together. |
| `SITE_DIR` / `STATE_DIR` | `site` / `.state` | Feed/audio output and separate private processing state. |
| `SITE_URL` | `http://localhost:8000` | URL prefix used for RSS enclosure links. |
| `FEED_TITLE` | `Newsletter Podcast` | Name shown in your podcast app. |
| `SUMMARY_MODEL` | `gemini-flash-latest` | Gemini model, with a lighter fallback for transient failures. |
| `TTS_VOICE` / `TTS_RATE` | `en-US-AndrewNeural` / `+0%` | Edge voice and speaking rate; list voices with `edge-tts --list-voices`. |
| `VERBOSE` | `false` | Log created episode titles. Avoid enabling it in public workflows. |
| `STATE_ENCRYPTION_KEY` | unset | Random Fernet key used to encrypt processing state for public publishing. Store it as a secret. |
| `PUBLISH_TO_PAGES` | `false` | Explicitly publish the feed and audio, with encrypted processing state, to Pages. |

Leave `LOOKBACK_HOURS` blank for automatic catch-up. If upgrading from an older example `.env` that sets it to `36`, remove or clear that value. Retaining `.state/` preserves completed-post history and the retry queue. Do not serve that directory.

### Podcast descriptions

Full narrations include the available article text in their podcast descriptions, including every split part, within the per-article description budget. New summary episodes include the generated spoken summary in their descriptions. Existing summary descriptions are preserved because their original scripts were not saved. Existing full-narration placeholders are updated on the next successful run when the article is still returned by its configured source; audio, dates and episode identities are preserved. Unavailable articles retain their existing notes for a later retry.

This replaces the old generic full-narration placeholder and no longer requires `INCLUDE_FULL_TEXT`. The landing page continues to show the project demo without personal feed metadata. Article text is part of the podcast feed output; subscription lists, per-source settings, credentials and retry payloads stay in private configuration and encrypted processing state. Source titles and article text are omitted from default workflow logs.

Each full-narration episode opens with the newsletter name, article title, and author, followed by “Part X of Y” when split into multiple parts. The default per-file duration limit is 10 minutes; an explicit `MAX_EPISODE_MINUTES` value in your environment or repository variables overrides it. The renderer groups complete narrated passages at sentence or paragraph boundaries and measures their audio, including the spoken introduction, to stay within the per-file duration limit. If one sentence is too long, it falls back to a clause or word boundary; it does not cut the finished audio mid-word. An unusually short limit that cannot fit the introduction and part number fails generation for retry rather than clipping them. Failed TTS passages likewise fail the article and queue a retry rather than silently omitting words. This applies to newly generated articles; existing published audio is preserved.

Completed TTS passages are checkpointed atomically under `STATE_DIR` (outside the served site). If a passage fails or the process is interrupted, the next attempt reuses validated speech with matching text, voice, and rate, including completed children of a split passage. Only missing or invalid speech is requested again; local audio assembly is repeated. All parts of an article must still finish before any of them enter the feed. Checkpoints expire after seven days without use and are bounded to 512 MiB, so evicted speech may need to be generated again.

For public publishing, checkpoints are encrypted with `STATE_ENCRYPTION_KEY` and restored/saved in a separate GitHub Actions cache, including after generation failures. They are never included in the public site bundle. Private workflows retain them in their existing private state cache. A runner loss or cancellation that prevents the cache-save step from running can still lose that run's new checkpoints; local runs retain checkpoints already written to disk. Retry scheduling is unchanged: queued article failures normally wait for the next configured window, or a manual run. Source text must still be available to reconstruct the narration; summary mode can reuse only passages whose newly generated script matches. Retain the original encryption key to reuse public-workflow checkpoints.

Before narration, invisible word-breaking artifacts (zero-width spaces, word joiners, byte-order marks, soft hyphens, and joiners adjacent to ASCII) are removed from the spoken script and introduction. This keeps obfuscated English words intact while preserving joiners within scripts that need them. Cleanup happens before speech splitting and checkpoint lookup; source descriptions keep their original text. It applies to new generation and retries, without replacing existing published audio.

## Scheduled runs with GitHub Actions

Actions generates the feed; your hosting choice determines who can access it. For personal listening, use a private repository and [private hosting](#keep-your-personal-feed-private). A public source repository can keep configuration in secrets, but the supplied workflow requires public Pages publishing in that case. In Settings → Secrets and variables → Actions:

1. Add a `PUBLICATIONS` secret containing your source list.
2. Add `GEMINI_API_KEY` if any source uses summaries; optionally add `SUBSTACK_SID` and `SUBSTACK_AUTH_HOSTS`.
3. For Pages publishing, generate a state key and save it as a `STATE_ENCRYPTION_KEY` secret:

   ```sh
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Add repository variables for any non-sensitive configuration you want to override. Keep personal per-source modes and title filters in the `PUBLICATIONS` secret. `EPISODE_MODE` defaults to `summary`; this is the recommended mode for public feeds and requires `GEMINI_API_KEY`. A per-source `full` option overrides it, so review your source list too.
5. Set `ENABLE_AUTOMATION=true` for scheduled runs. Leave `PUBLISH_TO_PAGES` unset or `false` in a private repository for personal listening. Set it to `true` only after reviewing the [public publishing warning](#optional-public-github-pages-feed). Keep `KEEP_EPISODES=0` to retain every existing and new episode.
6. Optionally set the **repository variable** `RUNS_PER_DAY`. Its default is `4`; use `2` for two runs a day, `6` for six, or another integer from `1` through `24`.

**Existing installations also need `ENABLE_AUTOMATION=true` after upgrading.** Automation is disabled by default.

### Four runs a day and automatic catch-up

The workflow checks hourly at minute 17. Python divides each UTC day into `RUNS_PER_DAY` equal windows and uses the encrypted processing state to allow one completed source scan per window. With the default `4`, the windows begin at 00:00, 06:00, 12:00 and 18:00 UTC. Checks in an already completed window skip audio-tool installation, generation and publishing. GitHub can delay or drop scheduled events, so these are target windows rather than guaranteed start times; a later hourly check can retry a missed attempt. Complete or partial source outages leave the window available for retry.

Each due run adds eligible missing articles available from its configured sources, while completed IDs prevent duplicate episodes. Automatic catch-up scans at least the past seven days and reaches back further after longer gaps. Failed episodes and articles beyond `MAX_EPISODES_PER_RUN` remain queued for later runs, even after they leave the source's current feed. Existing episodes stay in place unless you deliberately set a retention limit.

To request a longer backfill immediately, open **Actions → Newsletter podcast → Run workflow** and enter `lookback_hours`, for example `720` for 30 days. Manual runs bypass the scheduling window and still deduplicate completed articles. After the backfill, leave this input blank for automatic catch-up. Recovery is limited to articles still exposed by the source or already saved in the private retry queue; an older article absent from both cannot be recovered by increasing lookback alone.

Changes to `.github/workflows/daily.yml` or `src/tts.py` on `main` also start a catch-up run when automation is enabled, so scheduling and speech-provider fixes apply to queued articles immediately. Manual and workflow-update runs bypass the cadence check; scheduled runs remain limited to one complete source scan per window.

### Keep your personal feed private

You can keep scheduled Actions generation without publishing to GitHub Pages:

1. Use a **private repository**, leave `PUBLISH_TO_PAGES` unset or `false`, and set `ENABLE_AUTOMATION=true`. These runs save audio and state in a private Actions cache and provide a seven-day `newsletter-podcast` artifact containing `feed.xml` and the MP3s. Caches can expire or be evicted; keep a backup for durable personal history.
2. Set the Actions repository variable `SITE_URL` to your private host's HTTPS base URL before generation, for example `https://podcast.example.com/listening`. RSS enclosure links use this address. Upload the artifact's feed and audio there, preserving the `feed.xml` and `episodes/` layout. The supplied workflow does not upload to a private host automatically. Never upload `.state/` or credentials.
3. Protect **both the RSS feed and MP3 URLs** with authentication your podcast app supports, or use a private network your listening device can reach. Test feed refresh and audio playback in the app; a browser login alone may not work. `SITE_URL` does not accept embedded credentials, so configure authentication in the host and app.

An unguessable path is an **unlisted URL, not access control**: anyone who obtains it can download and share the feed and audio. If you use one, apply it to both the feed and enclosure URLs and treat those URLs as secrets. On GitHub Pages, paths and files may also be discoverable through the published branch. A hidden landing-page link does not make the podcast private.

Private hosting limits distribution; it does not grant rights to access or convert someone else's writing. Use content you are authorized to access and convert.

### Optional public GitHub Pages feed

> **Public redistribution warning:** Full narrations of someone else's writing can prompt copyright complaints and takedown notices. Publish them only with permission or a license that permits redistribution as audio and article text. A secret source list, encrypted processing state, or a private source repository does not protect the published feed or MP3s. For personal listening, use [private hosting](#keep-your-personal-feed-private).

Keep the default `EPISODE_MODE=summary` for public feeds and remove per-source `full` overrides unless you have redistribution rights. Summaries should use original wording, avoid extensive quotations, and retain source links; review them before sharing. Summary mode reduces copying but does not guarantee that publication is permitted. Changing modes affects new episodes only: existing full audio and article-text descriptions remain published until you remove them from the host and feed. Copies already downloaded may persist.

Set `PUBLISH_TO_PAGES=true` only for content you deliberately want everyone to see. Then run the workflow and configure Settings → Pages to deploy the `gh-pages` branch, folder `/`. The default feed address is `https://<owner>.github.io/<repo>/feed.xml`. The root address opens the project demo page. It does not list your episodes, display your feed title or link to your personal RSS feed. Your existing RSS and MP3 URLs remain available directly through Pages.

A public repository can use a `PUBLICATIONS` **secret**, including personal per-source filters and modes. Generated RSS and audio are public. Processing state and the retry queue are encrypted into `podcast-state.enc` with your secret state key and restored on the next run. Plaintext runtime state is never published or cached by the public workflow. Keep that key stable and back it up privately: losing or changing it prevents the next run from decrypting the queue. Restrict repository write access to people you trust with your Actions secrets.

**GitHub Pages output is public, even when the source repository is private.** It reveals publications through titles, audio, links and full-narration article text. Secrets protect stored configuration, not generated content. Read [PRIVACY.md](PRIVACY.md) before migrating an existing installation.

Add your reachable RSS URL to a podcast app that supports custom RSS feeds, such as Apple Podcasts, Overcast or Pocket Casts.

### Upgrading an existing public podcast

Keep the existing `gh-pages` branch and Pages settings. Upload the cleaned source to `main` only. Set the secrets and variables above before enabling daily runs, then run the workflow manually once.

The first run moves legacy `state.json` out of the served directory, imports completed-post history and retries, and preserves existing GUIDs, enclosure URLs, dates and show notes. Existing MP3s stay in place. New articles are appended, and the new processing state is published only in encrypted form. The feed title is preserved unless you explicitly set `FEED_TITLE`.

See [docs/deploy-existing-feed.md](docs/deploy-existing-feed.md) for the upgrade sequence. Cleaning old `main` history is a separate step; do not delete `gh-pages` or disable Pages when keeping the existing public podcast.

## Failure reporting

If every configured source fails, the command exits with status **1** and leaves the existing feed, audio, retry queue and run timestamps unchanged. GitHub Actions stops before publishing. A scheduled failure is not counted as the day's successful run, so the next scheduled attempt can retry.

A source that responds successfully with no eligible recent posts is different: that run succeeds with **0** new episodes. Partial source failures are logged by source number and error type; available sources can still produce output, and the catch-up timestamp is not advanced. Episode-generation failures remain queued for retry. Private URLs and raw provider errors are omitted from logs.

### Pipeline failure alerts

Each due generation step writes numeric results to GitHub Actions outputs and a run summary: attempted/created articles, new audio files, unrecovered failures, expected deferrals, security skips and queued articles. These reports contain no source names, titles, URLs, article text or provider errors.

The final **health** job waits for generation and publication. Successful episodes and retry state are saved/published first; then an unrecovered episode-generation error marks the workflow failed, even when other articles succeeded. Build failures, missing reports and failed public publication also fail the health check. Empty runs, recovered provider retries, security-limit rejections and work deferred by article/run budgets do not trigger generation-failure alerts. A skipped scheduling window skips the health job.

Use [GitHub's notification settings](https://github.com/settings/notifications): under **System → Actions**, enable **Email** or **On GitHub** and **Only notify for failed workflows**. GitHub handles delivery when a run completes, without a polling service or additional notification secret. Scheduled-run recipients follow [GitHub's scheduled workflow notification rules](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs). Each failing run can generate a notification; recovery runs stay green. This checks runs that start; it does not independently detect a workflow that never starts or has been disabled.

### Edge TTS 403

Edge TTS 7.2.8 received HTTP 403 before audio arrived in our GitHub runner checks on 2026-10-12. We temporarily changed the synthesis endpoint to restore generation.

The hashed dependency lock now uses [`edge-tts==7.3.1`](https://github.com/rany2/edge-tts/releases/tag/7.3.1), released on 2026-10-13. Version 7.3.0 resolved [upstream issue #490](https://github.com/rany2/edge-tts/issues/490) with [v2 authentication tokens in PR #492](https://github.com/rany2/edge-tts/pull/492); 7.3.1 also fixes locale-dependent server date parsing. The official fix keeps the original synthesis endpoint. The proposed endpoint change in PR #491 was not merged.

`src/tts.py` now calls the official SDK directly without changing its endpoint or authentication. The dependency input requires at least 7.3.1; audio budgets, bounded streaming, timeouts and retries remain in place.

Live validation on GitHub runners covers short synthetic speech and a full original RSS article, including complete descriptions, bounded audio splits, valid RSS and a rerun with stable episode identities and unchanged MP3 bytes. Both summary and full narration use the same TTS path. The service remains unofficial and may change again; the prerecorded `--demo` works independently of it.

Episode-generation failures stay in the bounded retry queue, and the build can still save/publish its retained feed even when it creates no new audio. The final health job marks unrecovered generation failures red. Check the run summary and final `Feed ready` message for counts; a healthy run with no eligible articles can create no audio. Keep your processing state and, for public publishing, the original `STATE_ENCRYPTION_KEY` so queued work can resume when service access is restored.

## Limits and costs

Full narration can run locally without paid API calls. Optional summaries can use Gemini's free tier with an eligible model and available quota. Paid API plans and hosting usage can incur charges.

- Gemini usage depends on your account, model, quotas and data-use terms. Review them before sending private or paid article text.
- Edge TTS uses an unofficial endpoint without a reliability guarantee. It may be throttled or change.
- Substack's archive API is unofficial. Bot protection can block Substack and custom domains, especially from GitHub runners.
- RSS/Atom narration reads the text included in the feed; it does not automatically fetch the linked article to fill in missing content.
- Each Substack run requests up to 50 latest archive entries per source; RSS/Atom reads up to 500 entries provided by the feed, and HTML listing sources inspect up to 30 links. Older posts absent from those responses cannot be recovered by increasing lookback.
- Splitting bounds file length, not total processing cost or runtime. Very long articles can exceed the workflow timeout.
- GitHub Actions, hosting and API usage may have costs. This project does not promise a permanently free service.
- Use articles you are authorized to access and convert. Share generated audio only when you have permission to redistribute the source content.

## Security limits

Source requests allow only public IPv4/IPv6 destinations on standard HTTP/HTTPS ports.
Every redirect is rechecked and HTTPS cannot downgrade to HTTP. Connections use the
checked IP address so DNS rebinding cannot redirect them into a private network;
source fetching deliberately bypasses environment proxies. Localhost/private-network
feeds are not supported. `SITE_URL=http://localhost:8000` still works for output previews.

Hard ceilings apply independently of episode length and retention settings:

| Boundary | Limit |
| --- | --- |
| Decoded source response / total downloads per run | 4 MiB / 64 MiB |
| RSS/Atom entries per source / candidates per run | 500 / 1,000 |
| Retry queue | 500 articles and 16 MiB; bounded bodies are kept for catch-up |
| Article text | 100,000 UTF-8 bytes and 20,000 words |
| Entire Gemini prompt | 64,000 UTF-8 bytes (a conservative token ceiling) |
| Narration | 40 initial chunks, 240 TTS attempts, 64 MiB temporary audio, 3 hours, 200 parts |
| Full-text descriptions across all parts of one article | 2 MiB |
| Run provider work | 1 MiB article text, 200,000 conservative Gemini input/output tokens, 600 TTS attempts |
| Generated feed / plaintext state | 32 MiB / 64 MiB |

Gemini output allowances are derived from the requested summary word budget.
Over-budget articles are skipped without saving their payload for repeated narration.
Transient generation failures still retry within the bounded queue. Excess queue entries
can be rediscovered while they remain at their sources; these limits may constrain large
backfills. `MAX_EPISODE_MINUTES=0` disables only per-file splitting, not security ceilings.

Source text is normalized to XML 1.0 before feed rendering. The completed candidate is
parsed before atomic replacement, so invalid or oversized output cannot replace the
last valid feed. On POSIX, private state directories/files are enforced as `0700`/`0600`,
including existing files owned by the current user. State symlinks, hardlinks and unowned
files are rejected. Generation requires POSIX filesystem support for these protections;
the static demo remains usable independently.

### Dependency and workflow integrity

`requirements.txt` locks direct and transitive package versions and artifact hashes.
Install it with `--require-hashes --only-binary=:all:` so an install cannot silently
select a different release or execute a source-package build. `requirements.in` is
only the maintainer input used when deliberately reviewing dependency updates.
GitHub Actions are pinned to full commits, and checkouts never persist Git credentials.

Scheduled generation runs with repository read permission. Application secrets are
available only to validation, scheduling, or generation steps that need them, and are
absent during dependency installation. A separate job receives write permission only
for public publication. It downloads this run's immutable public artifact by ID,
checks its SHA-256 digest and file allowlist, and preserves the existing publication
lease before updating `gh-pages`. The artifact contains public RSS, audio, landing-page
assets and encrypted processing state; plaintext state and configuration are excluded.
Private installations continue to use their private cache and downloadable output.

When verbose local logging is enabled, publication names and titles are bounded,
ASCII-escaped JSON fields so embedded newlines or terminal controls remain inert.

## Development

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -v
```

To regenerate the bundled sample, install the dependencies and ffmpeg, then run `python src/render_sample.py`. The **Render original demo sample** workflow also produces a downloadable MP3 and metadata artifact; it never uses account credentials or personal sources. Commit the matching `samples/demo.mp3` and `samples/demo.json` together.

Tests use synthetic content and mocked provider calls; audio tests use real ffmpeg and ffprobe. CI installs the provider SDKs and runs the same suite. See [CONTRIBUTING.md](CONTRIBUTING.md). The code is [MIT licensed](LICENSE); that license does not grant rights to third-party articles or generated readings of them.

Built by [@akspad](https://x.com/akspad)
