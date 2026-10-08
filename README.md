# Newsletter to Podcast

Turn newsletters and blogs into an RSS podcast **for free**, then listen in your usual podcast app.

Full article narration uses Edge TTS, with **no API key or paid TTS subscription required**. Optional spoken summaries can use [Gemini's free tier](https://ai.google.dev/gemini-api/docs/pricing), subject to eligible models and quotas.

Choose **spoken summaries** or **full article narration**. Set a maximum episode length; long full articles become multiple parts rather than losing the rest of the article.

**[Listen to the demo](https://akspad.github.io/newsletter-to-podcast/)** · [Quick start](#quick-start-hear-a-sample-in-under-a-minute)

- Reads Substack publications, RSS and Atom feeds, and simple article listing pages.
- Generates summaries with Gemini and audio with Edge TTS.
- Produces MP3s with podcast loudness normalization and an RSS feed.
- Runs locally or on a configurable schedule in your own GitHub repository: four times a day by default.
- Keeps your source list, credentials, and processing state out of the shared code.

This is a Python command-line project, not a hosted service. It reads the text a source makes available to you; it does not bypass paywalls, and feed excerpts may be shorter than the original article.

Built by [@akspad](https://x.com/akspad)

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

You need **Python 3.12+** and **ffmpeg** (including ffprobe). On macOS: `brew install python@3.12 ffmpeg`. On Ubuntu: install Python 3.12 and `sudo apt-get install ffmpeg python3-venv`.

```sh
git clone https://github.com/akspad/newsletter-to-podcast.git
cd newsletter-to-podcast
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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

Open `http://localhost:8000/feed.xml` to inspect your personal feed. The root page shows only the original project demo. To listen on another device, host the contents of `site/` at a URL your podcast app can reach and set `SITE_URL` to that address before generating it. Choose authenticated hosting if the content should be private; the local HTTP preview has no access controls.

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
| `MAX_EPISODE_MINUTES` | `5` | Maximum duration per MP3, in minutes. Full articles split into parts. `0` disables the audio limit. |
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

### Full-article podcast descriptions

Full narrations include the available article text in their podcast descriptions, including every split part. Summary descriptions remain brief. Existing full-narration placeholders are updated on the next successful run when the article is still returned by its configured source; audio, dates and episode identities are preserved. Unavailable articles retain their existing notes for a later retry.

This replaces the old generic full-narration placeholder and no longer requires `INCLUDE_FULL_TEXT`. The landing page continues to show only the original demo. Article text is part of the podcast feed output; subscription lists, per-source settings, credentials and retry payloads stay in private configuration and encrypted processing state. Source titles and article text are omitted from default workflow logs.

Splits occur at audio time boundaries, so a part can end mid-sentence. Failed TTS passages fail the article and queue a retry rather than silently omitting words.

## Scheduled runs with GitHub Actions

The source repository can be public while your subscription configuration stays in secrets. The podcast itself can deliberately be public. In Settings → Secrets and variables → Actions:

1. Add a `PUBLICATIONS` secret containing your source list.
2. Add `GEMINI_API_KEY` if any source uses summaries; optionally add `SUBSTACK_SID` and `SUBSTACK_AUTH_HOSTS`.
3. For Pages publishing, generate a state key and save it as a `STATE_ENCRYPTION_KEY` secret:

   ```sh
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Add repository variables for any non-sensitive configuration you want to override. Keep personal per-source modes and title filters in the `PUBLICATIONS` secret.
5. Set `PUBLISH_TO_PAGES=true` for your public podcast, and `ENABLE_AUTOMATION=true` for scheduled runs. Keep `KEEP_EPISODES=0` to retain every existing and new episode.
6. Optionally set the **repository variable** `RUNS_PER_DAY`. Its default is `4`; use `2` for two runs a day, `6` for six, or another integer from `1` through `24`.

**Existing installations also need `ENABLE_AUTOMATION=true` after upgrading.** Automation is disabled by default.

### Four runs a day and automatic catch-up

The workflow checks hourly at minute 17. Python divides each UTC day into `RUNS_PER_DAY` equal windows and uses the encrypted processing state to allow one completed source scan per window. With the default `4`, the windows begin at 00:00, 06:00, 12:00 and 18:00 UTC. Checks in an already completed window skip audio-tool installation, generation and publishing. GitHub can delay or drop scheduled events, so these are target windows rather than guaranteed start times; a later hourly check can retry a missed attempt. Complete or partial source outages leave the window available for retry.

Each due run adds eligible missing articles available from its configured sources, while completed IDs prevent duplicate episodes. Automatic catch-up scans at least the past seven days and reaches back further after longer gaps. Failed episodes and articles beyond `MAX_EPISODES_PER_RUN` remain queued for later runs, even after they leave the source's current feed. Existing episodes stay in place unless you deliberately set a retention limit.

To request a longer backfill immediately, open **Actions → Newsletter podcast → Run workflow** and enter `lookback_hours`, for example `720` for 30 days. Manual runs bypass the scheduling window and still deduplicate completed articles. After the backfill, leave this input blank for automatic catch-up. Recovery is limited to articles still exposed by the source or already saved in the private retry queue; an older article absent from both cannot be recovered by increasing lookback alone.

Changes to `.github/workflows/daily.yml` on `main` also start a catch-up run when automation is enabled, so updating this workflow applies the recovery behavior immediately. Manual and workflow-update runs bypass the cadence check; scheduled runs remain limited to one complete source scan per window.

For an entirely private installation, use a private repository and leave `PUBLISH_TO_PAGES` unset. These runs save audio and state in a private Actions cache and provide a seven-day downloadable artifact. Host the output yourself. Caches can expire or be evicted; keep a backup for durable personal history.

### Optional public GitHub Pages feed

Set `PUBLISH_TO_PAGES=true` only for content you deliberately want everyone to see. Then run the workflow and configure Settings → Pages to deploy the `gh-pages` branch, folder `/`. The default feed address is `https://<owner>.github.io/<repo>/feed.xml`. The root address opens a project landing page featuring only the original demo. It does not list your episodes, display your feed title or link to your personal RSS feed. Your existing RSS and MP3 URLs remain available directly through Pages.

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

## Limits and costs

Full narration can run locally without paid API calls. Optional summaries can use Gemini's free tier with an eligible model and available quota. Paid API plans and hosting usage can incur charges.

- Gemini usage depends on your account, model, quotas and data-use terms. Review them before sending private or paid article text.
- Edge TTS uses an unofficial endpoint without a reliability guarantee. It may be throttled or change.
- Substack's archive API is unofficial. Bot protection can block Substack and custom domains, especially from GitHub runners.
- RSS/Atom narration reads the text included in the feed; it does not automatically fetch the linked article to fill in missing content.
- Each Substack run requests up to 50 latest archive entries per source; RSS/Atom reads all entries provided by the feed, and HTML listing sources inspect up to 30 links. Older posts absent from those responses cannot be recovered by increasing lookback.
- Splitting bounds file length, not total processing cost or runtime. Very long articles can exceed the workflow timeout.
- GitHub Actions, hosting and API usage may have costs. This project does not promise a permanently free service.
- Use articles you are authorized to access and convert. Share generated audio only when you have permission to redistribute the source content.

## Development

```sh
python -m unittest discover -s tests -v
```

To regenerate the bundled sample, install the dependencies and ffmpeg, then run `python src/render_sample.py`. The **Render original demo sample** workflow also produces a downloadable MP3 and metadata artifact; it never uses account credentials or personal sources. Commit the matching `samples/demo.mp3` and `samples/demo.json` together.

Tests use synthetic content and mocked provider calls; audio tests use real ffmpeg and ffprobe. CI installs the provider SDKs and runs the same suite. See [CONTRIBUTING.md](CONTRIBUTING.md). The code is [MIT licensed](LICENSE); that license does not grant rights to third-party articles or generated readings of them.

Built by [@akspad](https://x.com/akspad)

