# Hacker News launch draft

GitHub About description:

> Turn newsletters and blogs into podcasts for free. Full article narration needs no API key; optional spoken summaries use Gemini.

Suggested repository topics: `python`, `podcast`, `rss`, `newsletters`, `text-to-speech`, `substack`.

The repository homepage should point to the listening page at https://akspad.github.io/newsletter-to-podcast/.

Suggested title:

> Show HN: Turn newsletters and blogs into a personal podcast

Suggested introductory comment:

> I wanted to listen to newsletters and blogs in a regular podcast app, so I built a small Python tool that turns an explicit list of sources into MP3s and an RSS feed. It supports spoken summaries and full article narration. You can choose a maximum episode length; longer full reads are split into parts. You can use it for free: full narration uses Edge TTS with no API key or paid TTS subscription. Optional summaries can use Gemini's free tier, subject to eligible models and quotas. It runs locally or in your own GitHub repository. The source adapters and free TTS endpoint are unofficial, so reliability is a tradeoff. I'd welcome feedback on setup, source compatibility and voice quality.

Before posting:

- Verify the documented quick start with a working, deliberately public source.
- Run the complete installed-dependency test suite and an actual provider smoke test.
- Finish the existing installation's privacy migration: personal lists can remain in old commits, public feed/audio, logs and caches even after the latest source tree is cleaned.
- Confirm that any public example audio uses content you can redistribute.

The source archive contains generic examples only. It is not evidence that previously published personal content has been removed from GitHub.
