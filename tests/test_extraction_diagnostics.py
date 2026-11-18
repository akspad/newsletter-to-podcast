"""Extraction failures identify the operation, never private source or response data."""
import contextlib
from datetime import datetime, timezone
import io
import json
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
from substack import SourceDownloadError, Substack

PRIVATE = 'PRIVATE https://private.example/signed?token=SECRET\n::error::injected'
BODY = '<p>A fictional report preserves its original observations and attribution.</p>'


class ExtractionDiagnosticsTests(unittest.TestCase):
    def assert_private(self, value):
        for secret in ('PRIVATE', 'private.example', 'SECRET', '::error::', 'ValueError', 'JSONDecodeError'):
            self.assertNotIn(secret, value)

    @contextlib.contextmanager
    def response(self, body, status=200, headers=None):
        def get(*args, **kwargs):
            kwargs['content_callback'](body)
            return types.SimpleNamespace(status_code=status, is_redirect=False,
                                         headers=headers or {}, encoding='utf-8')
        with patch('curl_cffi.requests.get', side_effect=get) as request, \
                patch('security.public_destination', return_value=('private.example', 443, '93.184.216.34')):
            yield request

    def run_failure(self, *, pub, post, source=None, empty_feed=False):
        """Exercise the pipeline's real catch/queue path; providers must stay untouched."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full',
                'GITHUB_OUTPUT': tmp+'/outputs', 'GITHUB_STEP_SUMMARY': tmp+'/summary'}, clear=True):
            settings = config.Settings.from_env()
            adapter = source or Substack('')
            with patch.object(adapter, 'recent_posts', return_value=[post]), \
                    patch('main.refresh_descriptions'), patch('summarize.write_script') as summarize, \
                    patch('tts.synthesize') as speech, patch('tts.synthesize_full') as full_speech, \
                    contextlib.redirect_stderr(io.StringIO()) as err, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main.run(settings, [pub], adapter), 0)
            summarize.assert_not_called()
            speech.assert_not_called()
            full_speech.assert_not_called()
            state = storage.load(settings)
            self.assertEqual(state['seen'], [])
            self.assertEqual(state['episodes'], [])
            retry = {'pub': pub, 'post': post}
            if empty_feed:
                retry['empty_feed_attempts'] = 1
            self.assertEqual(state['retry'], [retry])
            outputs = Path(tmp+'/outputs').read_text()
            self.assertIn('failed_articles=1\n', outputs)
            self.assertIn('queued_articles=1\n', outputs)
            self.assertFalse(list(settings.site.glob('episodes/*.mp3')))
            self.assert_private(err.getvalue() + out.getvalue() + outputs + Path(tmp+'/summary').read_text())
            return err.getvalue()

    def fixture(self, kind='substack'):
        pub = {'name': PRIVATE, 'base': 'https://private.example', 'mode': 'full'}
        if kind in ('feed', 'page'):
            pub['rss' if kind == 'feed' else 'page'] = True
        post = {'id': 1, 'title': PRIVATE, 'slug': 'private-story',
                'canonical_url': 'https://private.example/story', 'audience': 'everyone',
                'post_date': datetime.now(timezone.utc).isoformat(), 'body_html': BODY}
        return pub, post

    def test_empty_feed_and_page_bodies_get_specific_reason_and_keep_retry(self):
        for kind in ('feed', 'page'):
            for body in ('', ' \n ', '<script>'+PRIVATE+'</script>'):
                with self.subTest(kind=kind, body=body):
                    pub, post = self.fixture(kind)
                    post['body_html'] = body
                    log = self.run_failure(pub=pub, post=post, empty_feed=(kind == 'feed'))
                    self.assertEqual(log, 'Episode failed (stage=extract reason=empty_article_text '
                                     f'step=validate_text source_kind={kind}); queued for retry.\n')

    def test_missing_and_invalid_feed_bodies_are_distinct(self):
        for kind in ('feed', 'page'):
            for missing, body in ((True, None), (False, None), (False, []), (False, 1)):
                with self.subTest(kind=kind, missing=missing, body=body):
                    pub, post = self.fixture(kind)
                    if missing:
                        post.pop('body_html')
                    else:
                        post['body_html'] = body
                    code = 'missing_article_body' if missing else 'invalid_article_body'
                    self.assertIn(f'reason={code} step=validate_response source_kind={kind}',
                                  self.run_failure(pub=pub, post=post))

    def test_api_json_decode_failure_does_not_log_response_or_parser_position(self):
        pub, post = self.fixture()
        with self.response(('<html>'+PRIVATE+'</html>').encode()) as request:
            log = self.run_failure(pub=pub, post=post)
        self.assertEqual(request.call_count, 1)
        self.assertIn('reason=invalid_json_response step=decode_response source_kind=substack', log)

    def test_api_response_shape_and_body_validation(self):
        for payload, reason in (([], 'invalid_post_response'), (None, 'invalid_post_response'),
                ({'private': PRIVATE}, 'missing_article_body'),
                ({'body_html': [PRIVATE]}, 'invalid_article_body'),
                ({'body_html': 0}, 'invalid_article_body'),
                ({'body_html': False}, 'invalid_article_body')):
            with self.subTest(payload=payload):
                pub, post = self.fixture()
                with self.response(json.dumps(payload).encode()):
                    log = self.run_failure(pub=pub, post=post)
                self.assertIn(f'reason={reason} step=validate_response source_kind=substack', log)

    def test_empty_or_null_api_body_is_reported_after_conversion(self):
        for body in ('', None, '<script>'+PRIVATE+'</script>'):
            with self.subTest(body=body):
                pub, post = self.fixture()
                with self.response(json.dumps({'body_html': body}).encode()):
                    log = self.run_failure(pub=pub, post=post)
                self.assertIn('reason=empty_article_text step=validate_text source_kind=substack', log)

    def test_non_string_adapter_output_is_identified_before_text_processing(self):
        pub, post = self.fixture('feed')
        source = Substack('')
        with patch.object(source, 'post_text', return_value=(post, None)):
            log = self.run_failure(pub=pub, post=post, source=source)
        self.assertIn('reason=invalid_article_text step=validate_text source_kind=feed', log)

    def test_episode_download_failures_keep_validated_http_and_challenge_fields(self):
        pub, post = self.fixture()
        for status, headers, body, label in (
                (403, {'cf-mitigated': 'challenge', 'set-cookie': PRIVATE}, PRIVATE.encode(),
                 'protection=cloudflare_challenge'),
                (200, {'content-type': 'text/html'}, b'<title>Vercel Security Checkpoint</title>',
                 'protection=vercel_challenge'),
                (503, {'server': PRIVATE, 'retry-after': PRIVATE}, PRIVATE.encode(), 'retry_after=present')):
            with self.subTest(status=status), self.response(body, status, headers):
                log = self.run_failure(pub=pub, post=post)
            self.assertIn(f'reason=source_download_error http_status={status}', log)
            self.assertIn(label, log)
            self.assertIn('step=download_article source_kind=substack', log)

    def test_destination_download_and_conversion_failures_preserve_original_exceptions(self):
        for target, step in (('security.public_destination', 'validate_destination'),
                             ('curl_cffi.requests.get', 'download_article'),
                             ('substack.html_to_text', 'convert_html')):
            with self.subTest(target=target), self.response(json.dumps({'body_html': BODY}).encode()), \
                    patch(target, side_effect=ValueError(PRIVATE)):
                pub, post = self.fixture()
                log = self.run_failure(pub=pub, post=post)
            self.assertIn(f'reason=invalid_value step={step} source_kind=substack', log)

    def test_mutated_codes_steps_sources_and_causes_cannot_inject_details(self):
        with monitoring.episode_attempt() as diagnostic:
            monitoring.set_episode_stage('extract')
            error = monitoring.ExtractionError('empty_article_text')
            for bad in (PRIVATE, [], None, True):
                error.reason = diagnostic.extraction_step = diagnostic.extraction_source = bad
                error.__cause__ = RuntimeError(PRIVATE)
                self.assertEqual(diagnostic.fields(error), 'stage=extract reason=invalid_value '
                                 'step=load_article source_kind=unknown')
                monitoring.set_extraction_step(bad, source_kind=bad)
                self.assert_private(diagnostic.fields(error))
            self.assertEqual(monitoring.ExtractionError(PRIVATE).reason, 'invalid_value')

    def test_unknown_exception_never_uses_message_class_or_similar_attributes(self):
        def forbidden_string(_):
            self.fail('Private exception message was inspected')
        error = type('PRIVATE_CLASS', (ValueError,), {'__str__': forbidden_string})(PRIVATE)
        error.reason = error.status_code = error.diagnostics = PRIVATE
        error.__cause__ = json.JSONDecodeError(PRIVATE, PRIVATE, 0)
        with monitoring.episode_attempt() as diagnostic:
            monitoring.set_episode_stage('extract')
            monitoring.set_extraction_step('convert_html', source_kind='feed')
            self.assertEqual(diagnostic.fields(error), 'stage=extract reason=invalid_value '
                             'step=convert_html source_kind=feed')

    def test_download_metadata_is_revalidated_for_episode_failures(self):
        error = SourceDownloadError(PRIVATE, 403)
        error.status_code, error.diagnostics = PRIVATE, PRIVATE
        with monitoring.episode_attempt() as diagnostic:
            monitoring.set_episode_stage('extract')
            self.assertEqual(diagnostic.fields(error), 'stage=extract reason=source_download_error '
                             'step=load_article source_kind=unknown')

    def test_extraction_context_isolated_across_nested_attempts_and_later_stages(self):
        monitoring.set_extraction_step('download_article', source_kind='substack')
        with monitoring.episode_attempt() as outer:
            monitoring.set_episode_stage('extract')
            monitoring.set_extraction_step('convert_html', source_kind='feed')
            with monitoring.episode_attempt() as inner:
                monitoring.set_episode_stage('extract')
                self.assertIn('step=load_article source_kind=unknown', inner.fields(ValueError(PRIVATE)))
                monitoring.set_extraction_step('download_article', source_kind='substack')
            self.assertIn('step=convert_html source_kind=feed', outer.fields(ValueError(PRIVATE)))
            monitoring.set_episode_stage('speech')
            monitoring.set_extraction_step('decode_response', source_kind='substack')
            self.assertEqual(outer.extraction_step, 'convert_html')
            self.assertEqual(outer.fields(ValueError(PRIVATE)), 'stage=speech reason=invalid_value')

    def test_successful_extraction_keeps_content_and_has_no_new_logs(self):
        for kind in ('feed', 'page', 'substack'):
            with self.subTest(kind=kind), self.response(json.dumps({'body_html': BODY}).encode()), \
                    monitoring.episode_attempt(), contextlib.redirect_stderr(io.StringIO()) as logs:
                monitoring.set_episode_stage('extract')
                pub, post = self.fixture(kind)
                full, text = Substack('').post_text(pub, post)
                self.assertEqual(text, 'A fictional report preserves its original observations and attribution.')
                self.assertEqual(full['body_html'], BODY)
                self.assertEqual(logs.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
