"""Keep processing state private while serving an intentionally public podcast."""
import base64
import hashlib
import json
import os
import re

import feed

PUBLIC_STATE = "podcast-state.enc"


def legacy_key(identifier):
    return "legacy-" + hashlib.sha256(str(identifier).encode()).hexdigest()


def validate_key():
    key = os.environ.get("STATE_ENCRYPTION_KEY", "").strip()
    if not key:
        raise ValueError("Public publishing needs a STATE_ENCRYPTION_KEY secret to protect processing state")
    try:
        if len(base64.b64decode(key, altchars=b"-_", validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("STATE_ENCRYPTION_KEY must be a URL-safe base64-encoded 32-byte random key") from None
    return key


def cipher():
    from cryptography.fernet import Fernet

    return Fernet(validate_key().encode())


def migrate(state, feed_path):
    """Preserve old RSS identities and recognize legacy completed-post IDs."""
    state.setdefault("episodes", [])
    seen = []
    for identifier in state.get("seen", []):
        value = str(identifier)
        seen.append(legacy_key(value) if value.isdecimal() else value)
    existing = {e["guid"]: e for e in feed.read(feed_path)} if feed_path.exists() else {}
    for episode in state["episodes"]:
        episode.setdefault("source_key", episode["guid"].split("-part-")[0])
        match = re.fullmatch(r"substack-(\d+)", episode["guid"])
        if match:
            seen.append(legacy_key(match.group(1)))
        else:
            seen.append(episode["source_key"])
        public = existing.get(episode["guid"])
        if public:
            # The feed is authoritative for values podcast clients already cached.
            episode.update({k: public[k] for k in ("rss_guid", "enclosure_url", "published", "description_html")})
    state["seen"] = list(dict.fromkeys(seen))
    state.setdefault("retry", [])
    state.setdefault("last_run", None)
    if feed_path.exists():
        state.setdefault("feed_title", feed.title(feed_path))
    return state


def load(settings):
    local = settings.state_dir / "state.json"
    public = settings.site / PUBLIC_STATE
    legacy = settings.state_dir / "legacy-state.json"
    if local.exists():
        state = json.loads(local.read_text(encoding="utf-8"))
    elif public.exists():
        from cryptography.fernet import InvalidToken

        try:
            state = json.loads(cipher().decrypt(public.read_bytes()))
        except InvalidToken:
            raise ValueError("Cannot decrypt processing state; restore the original STATE_ENCRYPTION_KEY") from None
    elif legacy.exists():
        state = json.loads(legacy.read_text(encoding="utf-8"))
    else:
        path = settings.site / "feed.xml"
        episodes = feed.read(path) if path.exists() else []
        state = {"episodes": episodes, "seen": [], "retry": [], "last_run": None}
    return migrate(state, settings.site / "feed.xml")


def publish(settings, state):
    if os.environ.get("PUBLISH_TO_PAGES") != "true":
        return
    # Authentication and encryption are provided by Fernet, not custom cryptography.
    encrypted = cipher().encrypt(json.dumps(state).encode())
    temporary = settings.site / (PUBLIC_STATE + ".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(settings.site / PUBLIC_STATE)


def was_seen(pub, post, seen, current_key):
    return current_key in seen or legacy_key(post["id"]) in seen
