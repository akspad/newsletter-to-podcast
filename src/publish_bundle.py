"""Package only deliberately public podcast assets for the isolated publisher."""
import hashlib
import os
from pathlib import Path
import re
import sys
import tarfile

ROOT_FILES = ("feed.xml", "index.html", "favicon.svg", "preview.js", "podcast-state.enc", "demo/sample.mp3")
AUDIO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,250}\.mp3")


def prepare(site, published_ref, output):
    head = published_ref.read_text().split()
    head = head[0] if head else ""
    if head and not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid previous publication revision")
    if site.is_symlink() or any((site / directory).is_symlink() for directory in ("demo", "episodes")):
        raise ValueError("Public output directories must not be symlinks")
    files = list(ROOT_FILES)
    for path in sorted((site / "episodes").iterdir()):
        if not AUDIO_NAME.fullmatch(path.name):
            raise ValueError("Unexpected audio output filename")
        files.append("episodes/" + path.name)
    for name in files:
        path = site / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Public assets must be regular files")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "podcast-public.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in files:
            bundle.add(site / name, arcname=name, recursive=False)
    (output / "published-head.txt").write_text(head)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return digest


def main():
    digest = prepare(*(Path(value) for value in sys.argv[1:]))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"bundle_sha256={digest}\n")
    print("Prepared verified public assets; private runtime state is excluded.")


if __name__ == "__main__":
    main()
