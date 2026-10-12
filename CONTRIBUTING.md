# Contributing

Use Python 3.12+, install ffmpeg, then run:

```sh
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Keep test fixtures fictional. Never commit publication lists, login cookies, API keys, real paid article text, generated personal audio or processing state. `publications.example.txt` and `.env.example` document the supported configuration.

For bug reports, include your Python version, mode, sanitized configuration and a reproducible example using content you can share. Avoid posting raw provider errors, private URLs or article bodies.

Changes to source adapters, retry behavior or duration limits should include focused regression tests. Provider calls should be mocked in tests. Preserve all available article text in full mode and keep runtime state outside the served site.


Dependency ranges live in `requirements.in`; test-only ranges live in `requirements-dev.in`.
In a clean environment without production secrets, use pip-tools to regenerate both
locks with `pip-compile --generate-hashes --strip-extras --no-emit-index-url
--no-emit-trusted-host --output-file requirements.txt requirements.in` (and the matching
`requirements-dev` filenames). Review the version/hash changes and run the full CI suite.
Do not resolve dependencies or rewrite locks during production generation. Review Action
commit updates before changing workflow pins; the workflow policy tests enforce immutable
references, read-only generation, step-scoped secrets and hash-enforced installation.
