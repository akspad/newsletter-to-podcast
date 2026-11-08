"""Source diagnostics stay useful without exposing private provider content."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import monitoring
import storage
from substack import SourceDownloadError

PRIVATE = 'PRIVATE https://private.example/signed?token=SECRET\n::error::injected'


class SourceDiagnosticsTests(unittest.TestCase):
    def test_http_and_challenge_labels_are_preserved_without_response_content(self):
        for status, headers, body, expected in [
            (403, {'server': 'cloudflare', 'cf-mitigated': 'challenge',
                   'set-cookie': PRIVATE}, PRIVATE.encode(), 'protection=cloudflare_challenge'),
            (429, {'server': 'vercel', 'retry-after': '120',
                   'x-vercel-mitigated': 'challenge'}, PRIVATE.encode(), 'retry_after=120'),
            (503, {'server': PRIVATE, 'retry-after': PRIVATE}, PRIVATE.encode(), 'server=other'),
            (200, {'content-type': 'text/html'}, b'<title>Vercel Security Checkpoint</title>',
             'protection=vercel_challenge'),
        ]:
            with self.subTest(status=status):
                error = SourceDownloadError(PRIVATE, status, headers=headers, body=body)
                result = monitoring.source_failure_fields(error)
                self.assertIn(f'http_status={status}', result)
                self.assertIn(expected, result)
                for secret in ('PRIVATE', 'private.example', 'SECRET', '::error::', 'SourceDownloadError'):
                    self.assertNotIn(secret, result)

    def test_mutated_fields_cannot_inject_log_content(self):
        error = SourceDownloadError(PRIVATE, 403)
        for status in [PRIVATE, True, 99, 600, 403.0]:
            for diagnostic in [PRIVATE, None, 'server=unknown protection=none retry_after=9999999']:
                error.status_code, error.diagnostics = status, diagnostic
                self.assertEqual(monitoring.source_failure_fields(error), 'reason=source_download_error')

    def test_unknown_exception_never_logs_message_or_class_name(self):
        CustomPrivateException = type('PRIVATE_CLASS', (Exception,), {})
        self.assertEqual(monitoring.source_failure_fields(CustomPrivateException(PRIVATE)),
                         'reason=unexpected_error')
        self.assertEqual(monitoring.source_failure_fields(TimeoutError(PRIVATE)), 'reason=timeout')

    def test_partial_outage_logs_status_and_preserves_catchup_and_health_semantics(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'GITHUB_EVENT_NAME': 'schedule',
                'GITHUB_OUTPUT': tmp+'/outputs', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            previous = '2026-10-01T12:00:00+00:00'
            state = {'episodes': [], 'seen': [], 'retry': [], 'last_run': previous,
                     'last_scheduled_run': previous}
            storage.save(settings, state)
            pubs = [{'base': 'https://fictional.example', 'name': PRIVATE},
                    {'base': 'https://other.example', 'name': PRIVATE}]
            calls = []
            def recent(pub):
                calls.append(pub['base'])
                if pub is pubs[0]:
                    raise SourceDownloadError(PRIVATE, 403, headers={'cf-mitigated': 'challenge'})
                return []
            with contextlib.redirect_stderr(io.StringIO()) as errors, \
                    contextlib.redirect_stdout(io.StringIO()), patch('main.refresh_descriptions'):
                self.assertEqual(main.run(settings, pubs, types.SimpleNamespace(recent_posts=recent)), 0)
            self.assertEqual(len(calls), 2)
            self.assertIn('Source 1 unavailable (reason=source_download_error http_status=403', errors.getvalue())
            self.assertIn('protection=cloudflare_challenge', errors.getvalue())
            self.assertNotIn('PRIVATE', errors.getvalue())
            saved = storage.load(settings)
            self.assertEqual(saved['last_run'], previous)
            self.assertEqual(saved['last_scheduled_run'], previous)
            self.assertIn('catchup_since', saved)
            self.assertEqual(saved['retry'], [])
            self.assertIn('failed_articles=0', Path(tmp+'/outputs').read_text())

    def test_total_outage_preserves_state_and_does_not_create_feed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state'}, clear=True):
            settings = config.Settings.from_env()
            state = {'episodes': [], 'seen': [], 'retry': [], 'last_run': None}
            storage.save(settings, state)
            source = types.SimpleNamespace(recent_posts=lambda _: (_ for _ in ()).throw(
                SourceDownloadError(PRIVATE, 503)))
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main.run(settings, [{'base': 'https://fictional.example'}], source), 1)
            self.assertEqual(storage.load(settings), state)
            self.assertFalse((settings.site/'feed.xml').exists())
            self.assertIn('http_status=503', errors.getvalue())
            self.assertNotIn('PRIVATE', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
