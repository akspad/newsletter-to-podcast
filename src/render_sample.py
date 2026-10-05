"""Regenerate the original demonstration audio with the project's normal TTS path."""
import json
import os
from pathlib import Path

import tts

ROOT = Path(__file__).resolve().parents[1]


def main():
    samples = ROOT / "samples"
    path = samples / "demo.mp3"
    seconds = tts.synthesize((samples / "transcript.txt").read_text(encoding="utf-8"), path, None)
    (samples / "demo.json").write_text(json.dumps({
        "duration": seconds, "bytes": path.stat().st_size,
        "voice": os.environ.get("TTS_VOICE") or tts.VOICE,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Original sample rendered: {seconds:.1f} seconds.")


if __name__ == "__main__":
    main()
