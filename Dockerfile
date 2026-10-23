# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PREVIEW_HOST=0.0.0.0 \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
# Optional CA mount supports builds behind a managed network proxy. No
# environment-specific certificate is copied into the deployment image.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --require-hashes --only-binary=:all: -r requirements.txt

RUN groupadd --system preview && useradd --system --gid preview preview
COPY src/ ./src/
COPY samples/demo.mp3 ./samples/demo.mp3
COPY LICENSE ./LICENSE
RUN chmod -R a=rX /app
USER preview

EXPOSE 8000
CMD ["python", "src/preview_server.py"]
