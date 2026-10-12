"""Regression policies for code provenance, secret scope and publication isolation."""
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config
import main
import publish_bundle
import security

ROOT = Path(__file__).resolve().parents[1]


def workflow(path):
    try:
        import yaml
    except ImportError:
        # The local Mac runtime has Ruby's standard YAML parser; CI uses the locked test dependency.
        return json.loads(subprocess.check_output(["ruby", "-r", "yaml", "-r", "json", "-e",
            "puts JSON.generate(YAML.load_file(ARGV[0]))", str(path)], text=True))
    return yaml.safe_load(path.read_text())


class LogSafetyTests(unittest.TestCase):
    def test_json_field_neutralizes_cr_lf_c0_c1_csi_osc_and_unicode_controls(self):
        text = 'Title\r\n::warning:: forged\x1b[2J\x1b]0;fake\x07\x9b\x9d\u202e'
        safe = security.log_field(text)
        self.assertEqual(json.loads(safe), text)
        self.assertTrue(all(32 <= ord(c) < 127 for c in safe))
        self.assertIn('\\n', safe)
        self.assertIn('\\u001b', safe)
        self.assertIn('\\u009b', safe)
        self.assertLess(len(security.log_field('x' * 10_000)), 600)

    def test_successful_verbose_generation_emits_one_inert_creation_record(self):
        poison = 'Title\r\nFAKE RECORD\x1b[2J\x9b'
        post = {"id": 1, "title": poison, "slug": "article"}
        pub = {"base": "https://fictional.example", "name": "Source\nFORGED", "mode": "full"}
        source = types.SimpleNamespace(post_text=lambda *args: ({}, "Fictional article."))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "SITE_DIR": str(Path(tmp) / "site"), "STATE_DIR": str(Path(tmp) / "state"), "VERBOSE": "true"}, clear=True):
            settings = config.Settings.from_env()
            (settings.site / "episodes").mkdir(parents=True)
            def synthesize(script, path, limit):
                path.write_bytes(b"audio")
            with patch("tts.synthesize", side_effect=synthesize), patch("tts.duration", return_value=1), \
                    patch("tts.split_episode", side_effect=lambda path, cap: [path]), contextlib.redirect_stdout(io.StringIO()) as output:
                main.make_episode(source, pub, post, datetime.now(timezone.utc), {"episodes": []}, settings)
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertTrue(all(32 <= ord(c) < 127 for c in lines[0]))
            self.assertIn('\\nFAKE RECORD', lines[0])


class WorkflowPolicyTests(unittest.TestCase):
    def test_actions_are_immutable_and_checkouts_never_persist_credentials(self):
        approved = {"actions/checkout", "actions/setup-python", "actions/cache/restore", "actions/cache/save",
                    "actions/upload-artifact", "actions/download-artifact"}
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            definition = workflow(path)
            self.assertEqual(definition["permissions"], {"contents": "read"})
            for job in definition["jobs"].values():
                for step in job["steps"]:
                    if "uses" not in step:
                        continue
                    action, sha = step["uses"].split("@")
                    self.assertIn(action, approved)
                    self.assertRegex(sha, r"^[0-9a-f]{40}$")
                    if action == "actions/checkout":
                        self.assertIs(step["with"]["persist-credentials"], False)

    def test_only_minimal_publisher_has_write_access_and_no_application_secrets(self):
        jobs = workflow(ROOT / ".github/workflows/daily.yml")["jobs"]
        self.assertEqual(jobs["build"]["permissions"], {"contents": "read"})
        publisher = jobs["publish"]
        self.assertEqual(publisher["permissions"], {"contents": "write"})
        self.assertEqual(publisher["needs"], "build")
        self.assertNotIn("secrets.", json.dumps(publisher))
        self.assertNotIn("pip install", json.dumps(publisher))
        self.assertEqual(len(publisher["steps"]), 3)
        download = publisher["steps"][0]
        self.assertIn("public_artifact_id", download["with"]["artifact-ids"])
        self.assertIs(download["with"]["merge-multiple"], True)
        self.assertIn("bundle_sha256", publisher["steps"][1]["env"]["EXPECTED_SHA256"])
        self.assertNotIn("GH_TOKEN", publisher["steps"][1].get("env", {}))
        self.assertIn("--force-with-lease", publisher["steps"][2]["run"])
        self.assertIn("due == 'true'", publisher["if"])

    def test_application_secrets_are_only_in_necessary_step_environments(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            definition = workflow(path)
            self.assertNotIn("secrets.", json.dumps(definition.get("env", {})))
            for job in definition["jobs"].values():
                self.assertNotIn("secrets.", json.dumps({k: v for k, v in job.items() if k != "steps"}))
                for step in job["steps"]:
                    self.assertNotIn("secrets.", json.dumps({k: v for k, v in step.items() if k != "env"}))
                    if "pip install" in step.get("run", ""):
                        self.assertNotIn("secrets.", json.dumps(step.get("env", {})))
                        self.assertIn("--require-hashes", step["run"])
                        self.assertIn("--only-binary=:all:", step["run"])
                    if "uses" in step:
                        self.assertNotIn("secrets.", json.dumps(step.get("env", {})))

    def test_runtime_and_test_locks_have_exact_versions_and_hashes(self):
        for name in ("requirements.txt", "requirements-dev.txt"):
            lock = (ROOT / name).read_text().replace("\\\n", " ")
            requirements = [line for line in lock.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            self.assertTrue(requirements)
            for line in requirements:
                self.assertRegex(line, r"^[a-zA-Z0-9_.-]+==[a-zA-Z0-9_.-]+\s")
                self.assertRegex(line, r"--hash=sha256:[0-9a-f]{64}")
                self.assertNotRegex(line, r"[<>~]")


class PublicBundleTests(unittest.TestCase):
    def site(self, root):
        site = root / "site"
        for name in publish_bundle.ROOT_FILES:
            path = site / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"public data")
        (site / "episodes").mkdir()
        (site / "episodes/substack-123.mp3").write_bytes(b"existing audio")
        (site / "episodes/post-new-part-001.mp3").write_bytes(b"new audio")
        (site / "state.json").write_text("PRIVATE STATE MUST NEVER BE PACKAGED")
        (site / ".env").write_text("PRIVATE CONFIG MUST NEVER BE PACKAGED")
        ref = root / "published-ref"
        ref.write_text("a" * 40 + "\trefs/heads/gh-pages\n")
        return site, ref

    def verify(self, root, digest):
        job = workflow(ROOT / ".github/workflows/daily.yml")["jobs"]["publish"]
        script = job["steps"][1]["run"].split("<<'PYVERIFY'\n", 1)[1].rsplit("\nPYVERIFY", 1)[0]
        return subprocess.run([sys.executable, "-I", "-c", script], cwd=root,
                              env={**os.environ, "EXPECTED_SHA256": digest}, capture_output=True, text=True)

    def test_valid_bundle_preserves_public_feed_audio_and_publication_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site, ref = self.site(root)
            digest = publish_bundle.prepare(site, ref, root / "incoming")
            self.assertEqual(self.verify(root, digest).returncode, 0)
            published = root / "publish"
            self.assertEqual((published / "episodes/substack-123.mp3").read_bytes(), b"existing audio")
            self.assertFalse((published / "state.json").exists())
            self.assertFalse((published / ".env").exists())
            self.assertEqual((root / "incoming/published-head.txt").read_text(), "a" * 40)

    def test_modified_bundle_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site, ref = self.site(root)
            digest = publish_bundle.prepare(site, ref, root / "incoming")
            with (root / "incoming/podcast-public.tar").open("ab") as archive:
                archive.write(b"tampered")
            self.assertNotEqual(self.verify(root, digest).returncode, 0)
            self.assertFalse((root / "publish").exists())

    def test_correctly_hashed_unsafe_members_are_rejected(self):
        for name, kind in [("../escaped", tarfile.REGTYPE), ("state.json", tarfile.REGTYPE),
                           ("episodes/evil.mp3", tarfile.SYMTYPE), ("execute.py", tarfile.REGTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                site, ref = self.site(root)
                publish_bundle.prepare(site, ref, root / "incoming")
                archive = root / "incoming/podcast-public.tar"
                with tarfile.open(archive, "a") as bundle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "../private"
                    bundle.addfile(member)
                with archive.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                self.assertNotEqual(self.verify(root, digest).returncode, 0)
                self.assertFalse((root / "publish/feed.xml").exists())

    def test_symlinked_source_assets_and_invalid_branch_heads_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site, ref = self.site(root)
            audio = site / "episodes/substack-123.mp3"
            audio.unlink()
            audio.symlink_to(site / "state.json")
            with self.assertRaises(ValueError):
                publish_bundle.prepare(site, ref, root / "incoming")
            ref.write_text("invalid-revision")
            with self.assertRaises(ValueError):
                publish_bundle.prepare(site, ref, root / "incoming")


if __name__ == "__main__":
    unittest.main()
