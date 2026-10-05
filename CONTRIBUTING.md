# Contributing

Use Python 3.12+, install `requirements.txt` and ffmpeg, then run:

```sh
python -m unittest discover -s tests -v
```

Keep test fixtures fictional. Never commit publication lists, login cookies, API keys, real paid article text, generated personal audio or processing state. `publications.example.txt` and `.env.example` document the supported configuration.

For bug reports, include your Python version, mode, sanitized configuration and a reproducible example using content you can share. Avoid posting raw provider errors, private URLs or article bodies.

Changes to source adapters, retry behavior or duration limits should include focused regression tests. Provider calls should be mocked in tests. Preserve all available article text in full mode and keep runtime state outside the served site.
