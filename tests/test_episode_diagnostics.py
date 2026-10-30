"""Failure locations must be useful without logging private provider data."""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import monitoring

PRIVATE = 'PRIVATE ARTICLE https://private.example/signed?token=SECRET ::error::injected'
BODY = 'A fictional research report compares careful observations from several independent experiments.'


class EpisodeDiagnosticsTests(unittest.TestCase):
    def test_failure_stages_keep_retry_state_and_redact_all_provider_details(self):
        for stage, reason, error in (
                ('extract', 'timeout', TimeoutError(PRIVATE)),
                ('summary', 'runtime_error', RuntimeError(PRIVATE)),
                ('speech', 'runtime_error', RuntimeError(PRIVATE)),
                ('audio_metadata', 'subprocess_error', subprocess.CalledProcessError(1, PRIVATE, stderr=PRIVATE))):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                env = {'SITE_DIR': str(root / 'site'), 'STATE_DIR': str(root / 'state'),
                       'GITHUB_OUTPUT': str(root / 'outputs'), 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
                pub = {'name': PRIVATE, 'base': 'https://private.example', 'mode': 'summary'}
                post = {'id': PRIVATE, 'title': PRIVATE, 'post_date': datetime.now(timezone.utc).isoformat(),
                        'wordcount': 2000, 'audience': 'everyone', 'canonical_url': 'https://private.example/article'}
                def source_text(*_):
                    if stage == 'extract':
                        raise error
                    return post, BODY
                source = types.SimpleNamespace(recent_posts=lambda _: [post], post_text=source_text)
                def render(_, path, limit):
                    if stage == 'speech':
                        path.write_bytes(b'partial')
                        raise error
                    path.write_bytes(b'fictional audio')
                with patch.dict(os.environ, env, clear=True), patch('main.refresh_descriptions'), \
                        patch('summarize.write_script', side_effect=error if stage == 'summary' else None,
                              return_value=BODY), patch('tts.synthesize', side_effect=render), \
                        patch('tts.duration', side_effect=error if stage == 'audio_metadata' else None,
                              return_value=10), contextlib.redirect_stdout(io.StringIO()) as out, \
                        contextlib.redirect_stderr(io.StringIO()) as err:
                    settings = config.Settings.from_env()
                    self.assertEqual(main.run(settings, [pub], source), 0)
                self.assertEqual(err.getvalue(), f'Episode failed (stage={stage} reason={reason}); queued for retry.\n')
                logs = out.getvalue() + err.getvalue() + (root / 'summary').read_text() + (root / 'outputs').read_text()
                for secret in ('PRIVATE', 'private.example', 'SECRET', '::error::injected'):
                    self.assertNotIn(secret, logs)
                state = json.loads((root / 'state/state.json').read_text())
                self.assertEqual(state['seen'], [])
                self.assertEqual(state['episodes'], [])
                self.assertEqual(len(state['retry']), 1)
                self.assertFalse(list((root / 'site/episodes').glob('*.mp3')))
                self.assertIn('failed_articles=1', (root / 'outputs').read_text())

    def test_context_resets_after_failure_and_nested_attempts(self):
        with monitoring.episode_attempt() as outer:
            monitoring.set_episode_stage('summary')
            with self.assertRaises(RuntimeError):
                with monitoring.episode_attempt() as inner:
                    monitoring.set_episode_stage('speech')
                    raise RuntimeError(PRIVATE)
            self.assertEqual(inner.stage, 'speech')
            self.assertEqual(outer.stage, 'summary')
        monitoring.set_episode_stage('extract')  # no attempt must remain active
        self.assertEqual(outer.stage, 'summary')
        with monitoring.episode_attempt() as following:
            self.assertEqual(following.stage, 'unknown')

    def test_allowlist_never_uses_exception_names_messages_or_attributes(self):
        def forbidden_string(_):
            self.fail('Provider exception string was inspected')
        provider_error = type(PRIVATE, (Exception,), {'__str__': forbidden_string})(PRIVATE)
        provider_error.reason = provider_error.stage = PRIVATE
        with monitoring.episode_attempt() as diagnostic:
            monitoring.set_episode_stage(PRIVATE)
            self.assertEqual(diagnostic.fields(provider_error), 'stage=unknown reason=unexpected_error')
            diagnostic.stage = PRIVATE  # validate again at the output boundary
            self.assertEqual(diagnostic.fields(provider_error), 'stage=unknown reason=unexpected_error')
            diagnostic.stage = []
            self.assertEqual(diagnostic.fields(provider_error), 'stage=unknown reason=unexpected_error')

    def test_failure_reason_categories_are_bounded_and_do_not_follow_causes(self):
        for error, expected in ((TimeoutError(PRIVATE), 'timeout'), (ConnectionError(PRIVATE), 'connection_error'),
                (FileNotFoundError(PRIVATE), 'missing_file'), (PermissionError(PRIVATE), 'permission_denied'),
                (OSError(PRIVATE), 'io_error'), (subprocess.SubprocessError(PRIVATE), 'subprocess_error'),
                (subprocess.TimeoutExpired(PRIVATE, 1), 'timeout'), (ValueError(PRIVATE), 'invalid_value'),
                (RuntimeError(PRIVATE), 'runtime_error'), (KeyError(PRIVATE), 'unexpected_error')):
            error.__cause__ = RuntimeError(PRIVATE)
            self.assertEqual(monitoring.failure_reason(error), expected)


if __name__ == '__main__':
    unittest.main()
