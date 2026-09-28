# Newsletter to podcast

A private daily podcast of spoken summaries of long newsletter posts that don't come with audio you can play,
such as SemiAnalysis's paywalled previews.

Every day at 9am New York time a GitHub Action:

1. Checks each publication in `publications.txt` for posts from the past day that are 1,500+ words and have no playable audio.
2. Has Google Gemini (free tier) write a spoken summary of at most 20 minutes.
3. Voices it with Microsoft Edge's free neural text-to-speech.
4. Publishes the MP3 and an RSS feed to GitHub Pages at `https://<owner>.github.io/<repo>/feed.xml`.

It runs entirely on free services: GitHub Actions and Pages (public repo), Gemini's free API tier, and Edge TTS.

## Adding publications

Add one line per publication to `publications.txt`: the site URL, then optionally the name to use in episode titles.

```
https://newsletter.semianalysis.com SemiAnalysis
```

Posts are read from each site's public archive (the `/api/v1/archive` JSON that Substack-hosted sites serve).
Publications on their own domain work. Addresses on `substack.com` or `*.substack.com` are blocked for GitHub's
servers by Cloudflare and are skipped with a warning. Paywalled posts are summarized from the free preview.

## Setup

1. Repo secret (Settings → Secrets and variables → Actions → Repository secrets): `GEMINI_API_KEY`, free from
   aistudio.google.com. An optional `SUBSTACK_SID` login cookie is sent if present.
2. Run the workflow once by hand (Actions → Daily audio summaries → Run workflow). It creates the `gh-pages` branch.
   A manual run can take `lookback_hours` to summarize older posts.
3. Settings → Pages: deploy from branch `gh-pages`, folder `/`.
4. Add the feed URL to a podcast app that accepts RSS links (Castbox, Pocket Casts, Overcast, Apple Podcasts).
   Spotify can't follow private feeds.

## Tuning

Environment variables in the workflow: `MIN_WORDS`, `MAX_SCRIPT_WORDS`, `MAX_EPISODES_PER_RUN`, `KEEP_EPISODES`,
`TTS_VOICE` (list voices with `edge-tts --list-voices`), `TTS_RATE`, `SUMMARY_MODEL`.

## Caveats

- The archive JSON is an unofficial endpoint, so field names may change.
- Gemini's free tier sometimes reports high demand. The run falls back to a lighter model, and posts that still fail are retried the next day.
- Edge TTS is an unofficial free endpoint. If it stops working, swap `src/tts.py` for Piper or Kokoro, which run locally.
