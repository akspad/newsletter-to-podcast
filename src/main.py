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
from substack import AUDIO_FIELDS, Substack, has_audio

SITE = Path(os.environ.get("SITE_DIR", "site"))  # checkout of the gh-pages branch
STATE = SITE / "state.json"
MIN_WORDS = int(os.environ.get("MIN_WORDS", "1500"))
MAX_EPISODES_PER_RUN = int(os.environ.get("MAX_EPISODES_PER_RUN", "20"))
KEEP_EPISODES = int(os.environ.get("KEEP_EPISODES", "60"))
FIRST_RUN_LOOKBACK = timedelta(hours=float(os.environ.get("LOOKBACK_HOURS") or 36))
OVERLAP = timedelta(hours=48)
NY = ZoneInfo("America/New_York")


def make_episode(sub, pub, p, now, state):
    post, text = sub.post_text(pub, p)
    author = ", ".join(b.get("name", "") for b in post.get("publishedBylines", [])) or pub["name"]
    if pub.get("full"):
        # Read the article as written; the length cap is for summaries only.
        script = f"{pub['name']}. {p['title']}, by {author}.\n{text}"
        max_seconds = None
    else:
        script = summarize.write_script(pub["name"], author, p["title"], text)
        max_seconds = tts.MAX_SECONDS
    slug = re.sub(r"[^a-z0-9-]+", "-", p["slug"].lower())[:60]
    fname = f"{now:%Y%m%d}-{p['id']}-{slug}.mp3"
    path = SITE / "episodes" / fname
    secs = tts.synthesize(script, path, max_seconds)
    paywalled = p.get("audience") not in (None, "everyone")
    state["episodes"].append({
        "guid": f"substack-{p['id']}",
        "title": f"{pub['name']}: {p['title']}",
        "description": (p.get("subtitle") or "") + ((" (paywalled post, free preview only)" if paywalled else "") if pub.get("full")
                        else (" (summary of a paywalled post)" if paywalled else "")),
        "link": p.get("canonical_url") or f"{pub['base']}/p/{p['slug']}",
        "published": now.isoformat(),
        "file": fname,
        "bytes": path.stat().st_size,
        "duration": secs,
    })
    print(f"+ {pub['name']}: {p['title']} ({secs / 60:.1f} min)")


def main():
    missing = [k for k in ("GEMINI_API_KEY", "SITE_URL") if not os.environ.get(k)]
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

    # Look back at least OVERLAP past the last run: a late or hand-started run can't leave a gap,
    # and "seen" keeps posts from being published twice.
    since = now - FIRST_RUN_LOOKBACK
    if state.get("last_run") and not os.environ.get("LOOKBACK_HOURS"):
        since = min(datetime.fromisoformat(state["last_run"]), now - OVERLAP)
    seen = set(state["seen"])
    sub = Substack(os.environ.get("SUBSTACK_SID", ""))  # optional login cookie

    candidates = []
    for pub in sub.publications():
        try:
            posts = sub.recent_posts(pub)
        except Exception as e:  # one broken publication shouldn't sink the run
            print(f"! {pub['name']}: {e}", file=sys.stderr)
            continue
        for p in posts:
            published = datetime.fromisoformat(p["post_date"].replace("Z", "+00:00"))
            only = pub.get("only")
            if only or pub.get("full"):
                # Explicitly chosen posts (a series, or a blog read in full): take every match,
                # regardless of length or attached audio.
                skip = ("old" if published < since else "done" if str(p["id"]) in seen
                        else "not selected" if only and only.lower() not in p["title"].lower() else None)
            else:
                skip = ("old" if published < since else "done" if str(p["id"]) in seen
                        else "has audio" if has_audio(p) else "short" if (p.get("wordcount") or 0) < MIN_WORDS else None)
            audio = {k: p.get(k) for k in AUDIO_FIELDS if p.get(k)}
            print(f"  {pub['name']} | {published:%m-%d} | {p.get('wordcount')}w | {p.get('audience')} | "
                  f"type={p.get('type')} {audio or ''} | {skip or 'QUEUED'} | {p['title'][:60]}")
            if skip:
                continue
            candidates.append((pub, p))
    print(f"{len(candidates)} long posts without audio since {since:%Y-%m-%d %H:%M} UTC")

    # Posts that failed last time (e.g. Gemini overloaded) get another try first.
    retry = [(r["pub"], r["post"]) for r in state.get("retry", []) if str(r["post"]["id"]) not in seen]
    queued = {str(p["id"]) for _, p in candidates}
    candidates = [c for c in retry if str(c[1]["id"]) not in queued] + candidates
    state["retry"] = []

    (SITE / "episodes").mkdir(parents=True, exist_ok=True)
    for pub, p in candidates[:MAX_EPISODES_PER_RUN]:
        try:
            make_episode(sub, pub, p, now, state)
            seen.add(str(p["id"]))
        except Exception as e:  # keep going; retry this post next run
            print(f"! {pub['name']}: {p['title']}: {e}", file=sys.stderr)
            state["retry"].append({"pub": pub, "post": p})
    state["retry"] += [{"pub": pub, "post": p} for pub, p in candidates[MAX_EPISODES_PER_RUN:]]

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
