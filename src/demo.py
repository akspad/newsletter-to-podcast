"""Build an offline sample feed without touching subscription configuration or state."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import feed
import website

ROOT = Path(__file__).resolve().parents[1]


def build(output, site_url="http://localhost:8000"):
    marker = output / ".newsletter-demo"
    if output.exists() and any(output.iterdir()) and not marker.is_file():
        raise ValueError("Demo output directory is not empty. Choose a new --demo-dir to preserve existing files")
    samples = ROOT / "samples"
    metadata = json.loads((samples / "demo.json").read_text(encoding="utf-8"))
    audio = samples / "demo.mp3"
    if audio.stat().st_size != metadata["bytes"]:
        raise ValueError("Bundled demo audio does not match its metadata")
    (output / "episodes").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(audio, output / "episodes" / "demo.mp3")
    episode = {"guid": "original-demo", "source_key": "original-demo",
               "title": "A little room for curiosity", "description": "Original demonstration article. MIT licensed.",
               "link": website.REPO + "/blob/main/samples/transcript.txt",
               "published": datetime.now(timezone.utc).isoformat(), "file": "demo.mp3",
               "bytes": metadata["bytes"], "duration": metadata["duration"]}
    (output / "feed.xml").write_text(feed.build(site_url, [episode], "Newsletter to Podcast · Demo"), encoding="utf-8")
    website.write(output, demo_url=site_url)
    marker.touch()
    print(f"Demo ready in {output}. No API keys, live source requests or processing state were used.")
    print(f"Serve that directory, then open {site_url}/ to listen.")
