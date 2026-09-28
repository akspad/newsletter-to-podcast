# Substack audio summaries

Every day at 9am New York time, this finds long posts (1,500+ words) in your Substack subscriptions that have no audio,
has Claude write a spoken summary (at most 20 minutes), voices it with Microsoft Edge's free neural TTS (no key needed), and publishes it to a podcast feed
served by GitHub Pages at `https://<owner>.github.io/<repo>/feed.xml`.

## Setup
1. Repo secrets (Settings → Secrets and variables → Actions): `SUBSTACK_SID` (the `substack.sid` cookie from substack.com),
   `ANTHROPIC_API_KEY`.
2. Run the workflow once by hand (Actions → Daily audio summaries → Run workflow). It creates the `gh-pages` branch.
3. Settings → Pages: deploy from branch `gh-pages`, folder `/`.
4. Add the feed URL to your podcast app (Overcast, Pocket Casts, Apple Podcasts → "Follow a show by URL").

Tunables (env vars in the workflow): `MIN_WORDS`, `MAX_SCRIPT_WORDS`, `MAX_EPISODES_PER_RUN`, `TTS_VOICE`, `TTS_RATE`, `SUMMARY_MODEL`.

Substack has no official reader API; this uses the JSON endpoints its web app calls, so field names may drift.
Paywalled posts are summarized in full only if you're a paid subscriber; otherwise from the free preview.
Edge TTS is an unofficial free endpoint; if it ever stops working, swap `src/tts.py` for Piper or Kokoro (both run locally).
