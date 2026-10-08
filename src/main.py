"""Build a personal RSS podcast from explicitly configured newsletter sources."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feed
import summarize
import storage
import tts
import website
from schedule import scheduled_run_due
from config import Settings, load_env
from substack import Substack, has_audio, html_to_text

FULL_PLACEHOLDER = "Full narration of the text available from the source."
RESTRICTED_NOTICE = "The source has restricted access; the returned text may be a preview."


def episode_description(mode, text, preview):
    if mode == "full":
        return (RESTRICTED_NOTICE + "\n" if preview else "") + text
    description = "Spoken summary of the text available from the source."
    return description + (" " + RESTRICTED_NOTICE if preview else "")


def refresh_descriptions(sub, pub, posts, state):
    """Repair legacy full-narration notes using configured sources, without regenerating audio."""
    pending = []
    for episode in state["episodes"]:
        description = (html_to_text(episode["description_html"]) if episode.get("description_html")
                       else episode.get("description", ""))
        if description in (FULL_PLACEHOLDER, FULL_PLACEHOLDER + " " + RESTRICTED_NOTICE,
                           FULL_PLACEHOLDER + "\n" + RESTRICTED_NOTICE):
            pending.append(episode)
    updated = 0
    for post in posts:
        key = post_key(pub, post)
        link = post.get("canonical_url")
        matches = [e for e in pending if e.get("source_key", e["guid"].split("-part-")[0]) == key
                   or (link and e.get("link") == link)]
        if not matches:
            continue
        try:
            full, text = sub.post_text(pub, post)
            if not text.strip():
                raise ValueError("Source returned no article text")
            description = episode_description("full", text, full.get("audience") not in (None, "everyone"))
        except Exception as error:
            # Provider messages and URLs may reveal private source configuration.
            print(f"Description refresh failed ({type(error).__name__}); will retry.", file=sys.stderr)
            continue
        for episode in matches:
            episode["description"] = description
            episode.pop("description_html", None)
            pending.remove(episode)
            updated += 1
    if updated:
        print(f"Updated {updated} full-narration description(s).")


def post_key(pub, post):
    identity = f"{pub['base']}\n{post['id']}"
    return "post-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def episode_mode(pub, settings):
    return pub.get("mode") or ("full" if pub.get("full") else settings.mode)


def eligible(pub, post, since, seen, settings):
    if storage.was_seen(pub, post, seen, post_key(pub, post)):
        return False
    published = datetime.fromisoformat(post["post_date"].replace("Z", "+00:00"))
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    if published < since:
        return False
    only = pub.get("only")
    if only and only.lower() not in post["title"].lower():
        return False
    if only or episode_mode(pub, settings) == "full":
        return True
    return not has_audio(post) and (pub.get("any_length") or (post.get("wordcount") or 0) >= settings.min_words)


def make_episode(sub, pub, post, now, state, settings):
    full, text = sub.post_text(pub, post)
    if not text.strip():
        raise ValueError("Source returned no article text")
    author = ", ".join(b.get("name", "") for b in full.get("publishedBylines", [])) or pub["name"]
    mode = episode_mode(pub, settings)
    # We cannot reliably infer entitlement from an unofficial endpoint's response.
    preview = full.get("audience") not in (None, "everyone")
    if mode == "full":
        intro = f"{pub['name']}. {post['title']}, by {author}."
        if preview:
            intro += " This source has restricted access; reading the text available from the source."
        script = f"{intro}\n{text}"
    else:
        script = summarize.write_script(pub["name"], author, post["title"], text,
                                        settings.max_seconds, settings.max_script_words, preview)
    key = post_key(pub, post)
    path = settings.site / "episodes" / f"{key}.mp3"
    try:
        tts.synthesize(script, path, None if mode == "full" else settings.max_seconds)
        paths = tts.split_episode(path, settings.max_seconds) if mode == "full" else [path]
        episodes = []
        for index, part in enumerate(paths, 1):
            suffix = f" (part {index} of {len(paths)})" if len(paths) > 1 else ""
            description = episode_description(mode, text, preview)
            episodes.append({
                "guid": key + (f"-part-{index:03d}" if len(paths) > 1 else ""),
                "source_key": key,
                "title": f"{pub['name']}: {post['title']}{suffix}",
                "description": description,
                "link": post.get("canonical_url") or f"{pub['base']}/p/{post['slug']}",
                # Keep split parts ordered in podcast apps that sort by date.
                "published": (now + timedelta(seconds=index - 1)).isoformat(),
                "file": part.name,
                "bytes": part.stat().st_size,
                "duration": tts.duration(part),
            })
        state["episodes"].extend(episodes)  # commit only after every part is ready
        print(f"Created {len(episodes)} audio file(s)." + (f" {pub['name']}: {post['title']}" if settings.verbose else ""))
    except Exception:
        for incomplete in path.parent.glob(f"{key}*.mp3"):
            incomplete.unlink(missing_ok=True)
        raise


def load_state(settings):
    return storage.load(settings)


def save_state(settings, state):
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    path = settings.state_dir / "state.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)
    storage.publish(settings, state)


def run(settings, publications, sub):
    state = load_state(settings)
    now = datetime.now(timezone.utc)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        if not scheduled_run_due(state, now, settings.runs_per_day):
            print("Scheduled run skipped: this scheduling window already completed.")
            # Persist migrated state even when generation is skipped on its first run.
            if settings.site.exists():
                website.write(settings.site)
                save_state(settings, state)
            return 0

    since = now - timedelta(hours=settings.lookback_hours)
    if state.get("last_run") and not settings.explicit_lookback:
        since = min(datetime.fromisoformat(state["last_run"]) - timedelta(hours=48), since)
    seen = set(state.get("seen", []))
    configured = {pub["base"]: pub for pub in publications}
    # Drop queued posts from removed sources and use current mode/filter settings on retries.
    candidates = []
    queued = set()
    for retry in state.get("retry", []):
        pub = configured.get(retry["pub"]["base"])
        post = retry["post"]
        if pub and not storage.was_seen(pub, post, seen, post_key(pub, post)) and post_key(pub, post) not in queued:
            only = pub.get("only")
            if only and only.lower() not in post["title"].lower():
                continue
            candidates.append((pub, post))
            queued.add(post_key(pub, post))
    source_failed = False
    sources_available = 0
    for index, pub in enumerate(publications, 1):
        try:
            posts = list(sub.recent_posts(pub))
            refresh_descriptions(sub, pub, posts, state)
            for post in posts:
                if eligible(pub, post, since, seen, settings) and post_key(pub, post) not in queued:
                    candidates.append((pub, post))
                    queued.add(post_key(pub, post))
            sources_available += 1
        except Exception as error:
            source_failed = True
            print(f"Source {index} unavailable ({type(error).__name__}); will retry.", file=sys.stderr)
    if source_failed and not sources_available:
        print("All sources unavailable. Existing feed, audio and processing state were left unchanged; "
              "retry when source access is restored.", file=sys.stderr)
        return 1
    print(f"Found {len(candidates)} article(s) to process from {len(publications)} source(s).")
    state["retry"] = []
    (settings.site / "episodes").mkdir(parents=True, exist_ok=True)
    completed = []
    for pub, post in candidates[:settings.max_episodes]:
        try:
            make_episode(sub, pub, post, now, state, settings)
            key = post_key(pub, post)
            seen.add(key)
            completed.append(key)
        except Exception as error:
            # Exception messages may contain source text, URLs or credentials: don't print them.
            print(f"Episode failed ({type(error).__name__}); queued for retry.", file=sys.stderr)
            state["retry"].append({"pub": pub, "post": post})
    state["retry"].extend({"pub": pub, "post": post} for pub, post in candidates[settings.max_episodes:])

    # Retain whole articles together, including every part of a long narration.
    state["episodes"].sort(key=lambda e: e["published"])
    groups = list(dict.fromkeys(e.get("source_key", e["guid"]) for e in state["episodes"]))
    keep = set(groups[-settings.keep_episodes:] if settings.keep_episodes else groups)
    retained = []
    for episode in state["episodes"]:
        if episode.get("source_key", episode["guid"]) in keep:
            retained.append(episode)
        else:
            (settings.site / "episodes" / Path(episode["file"]).name).unlink(missing_ok=True)
    state["episodes"] = retained
    state["seen"] = list(dict.fromkeys(state.get("seen", []) + completed))
    if not source_failed:
        state["last_run"] = now.isoformat()
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not source_failed:
        state["last_scheduled_run"] = now.isoformat()
    title = os.environ.get("FEED_TITLE") or state.get("feed_title") or "Newsletter Podcast"
    (settings.site / "feed.xml").write_text(feed.build(settings.site_url, retained, title), encoding="utf-8")
    website.write(settings.site)
    # Public output contains audio and RSS only; runtime metadata stays outside SITE_DIR.
    save_state(settings, state)
    print(f"Feed ready: {len(retained)} audio file(s), {len(state['retry'])} article(s) waiting for retry.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Read a local KEY=value file (existing environment takes precedence)")
    parser.add_argument("--check", action="store_true", help="Validate configuration without network calls or generation")
    parser.add_argument("--demo", action="store_true", help="Create a separate offline podcast with bundled sample audio")
    parser.add_argument("--demo-dir", default="site-demo", help="Output directory for --demo (default: site-demo)")
    args = parser.parse_args()
    try:
        if args.demo:
            from demo import build
            build(Path(args.demo_dir))
            return 0
        if args.env_file:
            load_env(args.env_file)
        settings = Settings.from_env()
        if os.environ.get("PUBLISH_TO_PAGES") == "true":
            storage.validate_key()
        if (settings.site / "state.json").exists():
            raise ValueError("Legacy state.json is inside SITE_DIR. Move it outside the served directory before running")
        sub = Substack(os.environ.get("SUBSTACK_SID", ""))
        publications = sub.publications()
        if any(episode_mode(pub, settings) == "summary" for pub in publications) and not os.environ.get("GEMINI_API_KEY"):
            raise ValueError("Summary mode needs GEMINI_API_KEY; full mode does not")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise ValueError("Install ffmpeg (including ffprobe) first")
        if args.check:
            print(f"Configuration valid: {len(publications)} source(s), default mode {settings.mode}.")
            return 0
        required = ["curl_cffi", "bs4", "edge_tts"]
        if os.environ.get("PUBLISH_TO_PAGES") == "true" or (settings.site / storage.PUBLIC_STATE).exists():
            required.append("cryptography")
        if any(episode_mode(pub, settings) == "summary" for pub in publications):
            required.append("google.genai")
        for module in required:
            try:
                installed = importlib.util.find_spec(module)
            except ModuleNotFoundError:
                installed = None
            if installed is None:
                raise ValueError("Missing dependencies: run python -m pip install -r requirements.txt")
        return run(settings, publications, sub)
    except (ValueError, FileNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Run failed ({type(error).__name__}); check local setup and state.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

