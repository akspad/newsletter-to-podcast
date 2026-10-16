"""Bounded, private speech checkpoints; public workflow caches contain ciphertext only."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import security
import storage

_current = ContextVar("speech_checkpoints", default=None)
MAX_CACHE_BYTES = 512 * 1024 * 1024
MAX_AGE = 7 * 24 * 60 * 60


class Checkpoints:
    def __init__(self, root, encrypted):
        self.root = root
        self.cipher = storage.cipher() if encrypted else None
        with storage.private_directory(root):
            pass
        self.prune()

    def prune(self):
        files = []
        for path in self.root.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            if time.time() - stat.st_mtime > MAX_AGE or path.suffix == ".tmp":
                path.unlink()
            else:
                files.append((stat.st_mtime, stat.st_size, path))
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files):
            if total <= MAX_CACHE_BYTES:
                break
            path.unlink()
            total -= size

    def key(self, text, voice, rate):
        # Version the format/renderer so incompatible changes can invalidate old speech.
        identity = json.dumps([1, "edge-tts", text, voice, rate], ensure_ascii=False)
        return hashlib.sha256(identity.encode()).hexdigest()

    def get(self, key):
        path = self.root / (key + (".enc" if self.cipher else ".clip"))
        try:
            if path.is_symlink() or path.stat().st_size > security.MAX_AUDIO_BYTES * 2:
                return None
            data = path.read_bytes()
            if self.cipher:
                data = self.cipher.decrypt(data)
            # Bind the payload to its identity, and detect incomplete/corrupt private files.
            if data[:64] != key.encode() or data[64:96] != hashlib.sha256(data[96:]).digest():
                return None
            os.utime(path, None)
            return data[96:]
        except (OSError, ValueError):
            return None
        except Exception as error:
            from cryptography.fernet import InvalidToken
            if isinstance(error, InvalidToken):
                return None
            raise

    def put(self, key, payload):
        data = key.encode() + hashlib.sha256(payload).digest() + payload
        if self.cipher:
            data = self.cipher.encrypt(data)
        destination = self.root / (key + (".enc" if self.cipher else ".clip"))
        fd, name = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)
        self.prune()


@contextmanager
def use(state_dir):
    encrypted = os.environ.get("PUBLISH_TO_PAGES") == "true"
    cache = Checkpoints(state_dir / ("speech-encrypted" if encrypted else "speech-private"), encrypted)
    token = _current.set(cache)
    try:
        yield
    finally:
        _current.reset(token)


def current():
    return _current.get()
