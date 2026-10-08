"""Runtime configuration. No secrets or subscriptions are stored in source code."""
import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def load_env(path):
    """Read simple KEY=value files without executing shell code. Existing env wins."""
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().isidentifier():
            raise ValueError(f"Invalid environment entry on line {number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def number(name, default, minimum=0, integer=False):
    raw = os.environ.get(name) or str(default)
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a valid number") from None
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    site: Path
    state_dir: Path
    site_url: str
    mode: str
    max_seconds: float | None
    max_script_words: int
    min_words: int
    max_episodes: int
    keep_episodes: int
    lookback_hours: float
    explicit_lookback: bool
    verbose: bool
    runs_per_day: int

    @classmethod
    def from_env(cls):
        mode = os.environ.get("EPISODE_MODE") or "summary"
        if mode not in ("summary", "full"):
            raise ValueError("EPISODE_MODE must be summary or full")
        site_url = (os.environ.get("SITE_URL") or "http://localhost:8000").rstrip("/")
        parsed = urlparse(site_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("SITE_URL must be an HTTP(S) URL without credentials, query, or fragment")
        site = Path(os.environ.get("SITE_DIR") or "site")
        state_dir = Path(os.environ.get("STATE_DIR") or ".state")
        if state_dir.resolve().is_relative_to(site.resolve()):
            raise ValueError("STATE_DIR must be outside SITE_DIR; processing state is private")
        minutes = number("MAX_EPISODE_MINUTES", 5)
        if 0 < minutes < 1 / 60:
            raise ValueError("MAX_EPISODE_MINUTES must be 0 or at least one second")
        runs_per_day = number("RUNS_PER_DAY", 4, 1, True)
        if runs_per_day > 24:
            raise ValueError("RUNS_PER_DAY must be an integer from 1 to 24")
        return cls(site, state_dir, site_url, mode, minutes * 60 if minutes else None,
                   number("MAX_SCRIPT_WORDS", 700, 1, True), number("MIN_WORDS", 1500, 0, True),
                   number("MAX_EPISODES_PER_RUN", 20, 1, True), number("KEEP_EPISODES", 0, 0, True),
                   number("LOOKBACK_HOURS", 168, 0.01), bool(os.environ.get("LOOKBACK_HOURS")),
                   os.environ.get("VERBOSE", "false").lower() == "true", runs_per_day)

