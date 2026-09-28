"""Daily run: find long Substack posts without audio, summarize them, publish episodes to the feed."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feed
import summarize
import tts
from substack import Substack, has_audio

SITE = Path(os.environ.get("SITE_DIR", "site"))  # checkout of the gh-pages branch
STATE = SITE / "state.json"
MIN_WORDS = int(os.environ.get("MIN_WORDS", "1500"))
MAX_EPISODES_PER_RUN = int(os.environ.get("MAX_EPISODES_PER_RUN", "8"))
KEEP_EPISODES = int(os.environ.get("KEEP_EPISODES", "60"))
FIRST_RUN_LOOKBACK = timedelta(hours=float(os.environ.get("LOOKBACK_HOURS") or 36))
NY = ZoneInfo("America/New_York")


def main():
    missing = [k for k in ("SUBSTACK_SID", "GEMINI_API_KEY", "SITE_URL") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}: add them under Settings > Secrets and variables > Actions > Repository secrets")
    state = json.loads(STATE.read_text()) if STATE.exists() else {"episodes": [], "seen": [], "last_run": None}
    now = datetime.now(timezone.utc)
    local = now.astimezone(NY)

    # Cron fires at 13:00 and 14:00 UTC so one of them is 9am New York time in both EST and EDT.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        last = state.get("last_run")
        ran_today = last and datetime.fromisoformat(last).astimezone(NY).date() == local.date()
        if local.hour < 9 or ran_today:
            print(f"Skipping: {local:%H:%M} New York, already ran today={bool(ran_today)}")
            return

    since = datetime.fromisoformat(state["last_run"]) if state.get("last_run") else now - FIRST_RUN_LOOKBACK
    if os.environ.get("LOOKBACK_HOURS"):  # manual override from a hand-started run
        since = now - FIRST_RUN_LOOKBACK
    seen = set(state["seen"])
    sub = Substack(os.environ["SUBSTACK_SID"])

    candidates = []
    for pub in sub.publications():
        try:
            posts = sub.recent_posts(pub)
            if pub["name"] == pub["id"]:  # name unknown when read from publications.txt
                pub["name"] = (posts[0].get("publication") or {}).get("name") or pub["name"] if posts else pub["name"]
        except Exception as e:  # one broken publication shouldn't sink the run
            print(f"! {pub['name']}: {e}", file=sys.stderr)
            continue
        for p in posts:
            published = datetime.fromisoformat(p["post_date"].replace("Z", "+00:00"))
            if published < since or str(p["id"]) in seen or has_audio(p):
                continue
            if (p.get("wordcount") or 0) < MIN_WORDS:
                continue
            candidates.append((pub, p))
    print(f"{len(candidates)} long posts without audio since {since:%Y-%m-%d %H:%M} UTC")

    (SITE / "episodes").mkdir(parents=True, exist_ok=True)
    for pub, p in candidates[:MAX_EPISODES_PER_RUN]:
        post, text = sub.post_text(pub, p["slug"])
        author = ", ".join(b.get("name", "") for b in post.get("publishedBylines", [])) or pub["name"]
        script = summarize.write_script(pub["name"], author, p["title"], text)
        slug = re.sub(r"[^a-z0-9-]+", "-", p["slug"].lower())[:60]
        fname = f"{now:%Y%m%d}-{p['id']}-{slug}.mp3"
        path = SITE / "episodes" / fname
        secs = tts.synthesize(script, path)
        paywalled = p.get("audience") not in (None, "everyone")
        state["episodes"].append({
            "guid": f"substack-{p['id']}",
            "title": f"{pub['name']}: {p['title']}",
            "description": (p.get("subtitle") or "") + (" (summary of a paywalled post)" if paywalled else ""),
            "link": p.get("canonical_url") or f"{pub['base']}/p/{p['slug']}",
            "published": now.isoformat(),
            "file": fname,
            "bytes": path.stat().st_size,
            "duration": secs,
        })
        seen.add(str(p["id"]))
        print(f"+ {pub['name']}: {p['title']} ({secs / 60:.1f} min)")

    # Keep the site small: drop the oldest episodes and their audio.
    state["episodes"].sort(key=lambda e: e["published"])
    for old in state["episodes"][:-KEEP_EPISODES]:
        (SITE / "episodes" / old["file"]).unlink(missing_ok=True)
    state["episodes"] = state["episodes"][-KEEP_EPISODES:]
    state["seen"] = sorted(seen)[-2000:]
    state["last_run"] = now.isoformat()

    (SITE / "feed.xml").write_text(feed.build(os.environ["SITE_URL"].rstrip("/"), state["episodes"]))
    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
