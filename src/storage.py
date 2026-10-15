"""Keep processing state private while serving an intentionally public podcast."""
from contextlib import contextmanager
import secrets
import stat
import security
import base64
import hashlib
import json
import os
import re

import feed

PUBLIC_STATE = "podcast-state.enc"


@contextmanager
def private_directory(path):
    if os.name != "posix":
        raise ValueError("Private state generation requires POSIX filesystem protections")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise ValueError("Private state directory must belong to the current user")
        os.fchmod(fd, 0o700)
        yield fd
    finally:
        os.close(fd)


def check_private_file(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("Private state must be an owned regular file")
    os.fchmod(fd, 0o600)
    if info.st_size > security.MAX_STATE_BYTES:
        raise security.BudgetExceeded("Processing state exceeds the size limit")


def read_private(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        check_private_file(source.fileno())
        data = source.read(security.MAX_STATE_BYTES + 1)
    if len(data.encode("utf-8")) > security.MAX_STATE_BYTES:
        raise security.BudgetExceeded("Processing state exceeds the size limit")
    return json.loads(data)


def save(settings, state):
    data = json.dumps(state, indent=2).encode("utf-8")
    if len(data) > security.MAX_STATE_BYTES:
        raise security.BudgetExceeded("Processing state exceeds the size limit")
    with private_directory(settings.state_dir) as directory:
        # Reject a pre-existing link or unowned target instead of silently replacing it.
        try:
            existing = os.open("state.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            pass
        else:
            try:
                check_private_file(existing)
            finally:
                os.close(existing)
        temporary = ".state-" + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        os.fchmod(fd, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, "state.json", src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    publish(settings, state)


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
            # Include repaired audio metadata so stale encrypted state cannot
            # restore an old duration or enclosure size on the next run.
            episode.update({k: public[k] for k in ("rss_guid", "enclosure_url", "published", "description_html",
                                                  "bytes", "duration")})
    state["seen"] = list(dict.fromkeys(seen))
    state.setdefault("retry", [])
    state.setdefault("last_run", None)
    if feed_path.exists():
        state.setdefault("feed_title", feed.title(feed_path))
    return state


def load(settings):
    public = settings.site / PUBLIC_STATE
    state = legacy = None
    if settings.state_dir.exists() or settings.state_dir.is_symlink():
        with private_directory(settings.state_dir) as directory:
            state = read_private(directory, "state.json")
            legacy = read_private(directory, "legacy-state.json") if state is None and not public.exists() else None
    if state is None and public.exists():
        from cryptography.fernet import InvalidToken

        with public.open("rb") as source:
            encrypted = source.read(2 * security.MAX_STATE_BYTES + 1)
        if len(encrypted) > 2 * security.MAX_STATE_BYTES:
            raise security.BudgetExceeded("Encrypted processing state exceeds the size limit")
        try:
            decoded = cipher().decrypt(encrypted)
            if len(decoded) > security.MAX_STATE_BYTES:
                raise security.BudgetExceeded("Processing state exceeds the size limit")
            state = json.loads(decoded)
        except InvalidToken:
            raise ValueError("Cannot decrypt processing state; restore the original STATE_ENCRYPTION_KEY") from None
    elif state is None:
        state = legacy
    if state is None:
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

