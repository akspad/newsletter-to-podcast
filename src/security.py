"""Hard resource ceilings at boundaries controlled by remote publications."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlparse

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_SOURCE_ENTRIES = 500
MAX_CANDIDATES = 1000
MAX_RETRY_COUNT = 500
MAX_RETRY_BYTES = 16 * 1024 * 1024
MAX_ARTICLE_BYTES = 100_000
MAX_ARTICLE_WORDS = 20_000
MAX_MODEL_INPUT_BYTES = 64_000  # bytes also conservatively bound token count
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_AUDIO_SECONDS = 3 * 60 * 60
MAX_AUDIO_PARTS = 200
MAX_TTS_CHUNKS = 40
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_FEED_BYTES = 32 * 1024 * 1024


class BudgetExceeded(ValueError):
    """Permanent input rejection; do not queue this payload for repeated work."""


class RunBudgetExceeded(RuntimeError):
    """Transient run limit; bounded remaining work may be queued for another run."""


def check_text(text, maximum=MAX_ARTICLE_BYTES):
    if not isinstance(text, str):
        raise ValueError("Source text must be a string")
    if len(text) > maximum or len(text.encode("utf-8")) > maximum:
        raise BudgetExceeded("Article exceeds the text byte limit")
    if len(text.split()) > MAX_ARTICLE_WORDS:
        raise BudgetExceeded("Article exceeds the word limit")
    return text


@dataclass
class WorkBudget:
    article_bytes: int = 0
    model_tokens: int = 0
    tts_calls: int = 0

    def charge(self, field, amount, maximum):
        total = getattr(self, field) + amount
        if total > maximum:
            raise RunBudgetExceeded("Run work budget exhausted")
        setattr(self, field, total)


_budget = ContextVar("podcast_work_budget", default=None)


@contextmanager
def run_budget():
    token = _budget.set(WorkBudget())
    try:
        yield
    finally:
        _budget.reset(token)


def charge(field, amount):
    budget = _budget.get()
    if budget is not None:
        budget.charge(field, amount, {"article_bytes": 1024 * 1024,
                                     "model_tokens": 200_000, "tts_calls": 600}[field])


def public_destination(url):
    """Authorize and resolve once; callers must pin this address in the transport."""
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError("Invalid source URL")
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or "%" in parsed.hostname
            or parsed.port not in (None, 80 if parsed.scheme == "http" else 443)):
        raise ValueError("Source URL must use a public HTTP(S) destination on its standard port")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = {answer[4][0] for answer in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    if not addresses:
        raise ValueError("Source hostname has no addresses")
    for value in addresses:
        address = ipaddress.ip_address(value)
        address = getattr(address, "ipv4_mapped", None) or address
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise ValueError("Private or reserved source destinations are forbidden")
    return parsed.hostname, port, min(addresses, key=lambda value: (ipaddress.ip_address(value).version, value))
