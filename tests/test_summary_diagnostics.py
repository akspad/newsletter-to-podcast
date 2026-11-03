"""Summary diagnostics identify failures without disclosing provider/source details."""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import monitoring
import summarize
import security

PRIVATE = 'PRIVATE ARTICLE https://private.example/signed?token=SECRET ::error::injected'


class APIError(Exception):
    def __init__(self, code):
        self.code = code
        self.message = self.response = self.__cause__ = RuntimeError(PRIVATE)
    def __str__(self):
        raise AssertionError('A provider message must never be inspected')


def response(text='A complete summary.', finish='STOP', block=None):
    return types.SimpleNamespace(text=text, candidates=[types.SimpleNamespace(finish_reason=finish)],
                                 prompt_feedback=types.SimpleNamespace(block_reason=block))


@contextlib.contextmanager
def provider(results):
    google = types.ModuleType('google')
    genai = types.ModuleType('google.genai')
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        result = results[min(len(calls) - 1, len(results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result
    genai.Client = lambda: types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate))
    genai.errors = types.SimpleNamespace(APIError=APIError)
    genai.types = types.SimpleNamespace(GenerateContentConfig=lambda **kw: types.SimpleNamespace(**kw))
    google.genai = genai
    with patch.dict(sys.modules, {'google': google, 'google.genai': genai}), \
            patch.dict(os.environ, {'SUMMARY_MODEL': PRIVATE}, clear=True), \
            patch('summarize.time.sleep') as pause:
        yield calls, pause


def call():
    return summarize.write_script(PRIVATE, PRIVATE, PRIVATE, PRIVATE)


class SummaryDiagnosticsTests(unittest.TestCase):
    def assert_private(self, logs):
        for private in ('PRIVATE', 'private.example', 'SECRET', '::error::', 'APIError', 'RuntimeError'):
            self.assertNotIn(private, logs)

    def test_http_failures_have_bounded_codes_and_preserve_retry_policy(self):
        cases = [(400, 'request_rejected', 1), (401, 'authentication_failed', 1),
                 (403, 'permission_denied', 1), (404, 'model_unavailable', 1),
                 (429, 'rate_limited', 6), (500, 'service_unavailable', 6),
                 (502, 'service_unavailable', 6), (503, 'service_unavailable', 6), (504, 'timeout', 6),
                 (418, 'provider_error', 1)]
        for status, reason, count in cases:
            error = APIError(status)
            with self.subTest(status=status), provider([error]) as (calls, pause), \
                    monitoring.episode_attempt() as episode, contextlib.redirect_stderr(io.StringIO()) as out:
                monitoring.set_episode_stage('summary')
                with self.assertRaises(RuntimeError if count == 6 else APIError) as caught:
                    call()
                if count == 1:
                    self.assertIs(caught.exception, error)
                final = episode.fields(caught.exception)
            self.assertEqual(len(calls), count)
            self.assertEqual(pause.call_count, 6 if count == 6 else 0)
            self.assertIn(f'reason={reason}', final)
            self.assertIn(f'http_status={status}', final)
            ids = set(re.findall(r'summary_id=([0-9a-f]{32})', out.getvalue() + final))
            self.assertEqual(len(ids), 1)
            self.assertEqual(out.getvalue().count('event=failed '), 1)
            self.assertEqual(out.getvalue().count('event=exhausted '), 1 if count == 6 else 0)
            self.assert_private(out.getvalue() + final)

    def test_recovery_clears_old_http_status_and_failure_reason(self):
        with provider([APIError(503), response()]) as (calls, _), \
                contextlib.redirect_stderr(io.StringIO()) as out:
            self.assertEqual(call(), 'A complete summary.')
        completed = out.getvalue().splitlines()[-1]
        self.assertIn('event=completed reason=none', completed)
        self.assertIn('model_slot=1 attempt=2', completed)
        self.assertNotIn('http_status', completed)
        self.assertEqual(len(calls), 2)
        self.assert_private(out.getvalue())

    def test_preparation_and_budget_failures_log_once_without_calling_provider(self):
        for target, error, reason in [('check_text', ValueError(PRIVATE), 'invalid_value'),
                ('charge', security.RunBudgetExceeded(PRIVATE), 'budget_exceeded')]:
            with self.subTest(target=target), provider([response()]) as (calls, pause), \
                    patch('security.' + target, side_effect=error), \
                    contextlib.redirect_stderr(io.StringIO()) as out:
                with self.assertRaises(type(error)) as caught:
                    call()
            self.assertIs(caught.exception, error)
            self.assertEqual(calls, [])
            pause.assert_not_called()
            self.assertEqual(out.getvalue().count('event=failed '), 1)
            self.assertIn('reason=' + reason, out.getvalue())
            self.assert_private(out.getvalue())

    def test_later_unknown_error_is_not_misreported_as_an_earlier_503(self):
        error = KeyError(PRIVATE)
        with provider([APIError(503), error]), monitoring.episode_attempt() as episode, \
                contextlib.redirect_stderr(io.StringIO()) as out:
            monitoring.set_episode_stage('summary')
            with self.assertRaises(KeyError):
                call()
            final = episode.fields(error)
        self.assertIn('reason=unexpected_error', final)
        self.assertIn('attempt=2', final)
        self.assertNotIn('http_status', final)
        self.assert_private(out.getvalue() + final)

    def test_empty_truncated_and_blocked_outputs_have_distinct_reasons(self):
        for result, reason, count in [(response(''), 'empty_response', 6),
                (response(PRIVATE, 'MAX_TOKENS'), 'truncated_response', 6),
                (response(PRIVATE, 'SAFETY'), 'response_blocked', 1)]:
            with self.subTest(reason=reason), provider([result]) as (calls, _), \
                    monitoring.episode_attempt() as episode, contextlib.redirect_stderr(io.StringIO()) as out:
                monitoring.set_episode_stage('summary')
                with self.assertRaises(RuntimeError) as caught:
                    call()
                final = episode.fields(caught.exception)
            self.assertEqual(len(calls), count)
            self.assertIn('reason=' + reason, final)
            self.assert_private(out.getvalue() + final)

    def test_transport_errors_are_classified_without_changing_retry_behavior(self):
        from httpx import ConnectError, ReadTimeout
        for error, reason in [(ConnectError(PRIVATE), 'connection_error'), (ReadTimeout(PRIVATE), 'timeout')]:
            with self.subTest(reason=reason), provider([error]) as (calls, pause), \
                    contextlib.redirect_stderr(io.StringIO()) as out:
                with self.assertRaises(type(error)) as caught:
                    call()
            self.assertIs(caught.exception, error)
            self.assertEqual(len(calls), 1)
            pause.assert_not_called()
            self.assertIn('reason=' + reason, out.getvalue())
            self.assert_private(out.getvalue())

    def test_invalid_status_codes_and_mutated_fields_never_become_log_text(self):
        for code in (PRIVATE, True, 99, 600, None):
            with self.subTest(code_type=type(code).__name__), provider([APIError(code)]), \
                    contextlib.redirect_stderr(io.StringIO()) as out:
                with self.assertRaises(APIError):
                    call()
            self.assertNotIn('http_status=', out.getvalue())
            self.assertIn('reason=provider_error', out.getvalue())
            self.assert_private(out.getvalue())
        diagnostic = monitoring.SummaryDiagnostic(identity=PRIVATE, reason=[], model_slot=PRIVATE,
                                                  attempt=True, http_status=PRIVATE)
        with contextlib.redirect_stderr(io.StringIO()) as out:
            diagnostic.log(PRIVATE)
        self.assertEqual(out.getvalue(), 'summary_request event=failed reason=unexpected_error '
                         'summary_id=unknown model_slot=0 attempt=0\n')

    def test_log_lines_are_flushed_and_ids_are_new_per_article(self):
        ids = []
        for _ in range(2):
            with provider([response()]), patch('monitoring.print') as emit:
                call()
            for args in emit.call_args_list:
                self.assertTrue(args.kwargs['flush'])
                self.assertIs(args.kwargs['file'], sys.stderr)
            ids.append(re.search(r'summary_id=([0-9a-f]{32})', emit.call_args.args[0])[1])
        self.assertNotEqual(*ids)

    def test_nested_attempts_and_non_summary_failures_do_not_reuse_summary_details(self):
        with monitoring.episode_attempt() as outer:
            monitoring.set_episode_stage('summary')
            first = monitoring.summary_diagnostic()
            with monitoring.episode_attempt() as inner:
                second = monitoring.summary_diagnostic()
                self.assertIs(inner.summary, second)
            self.assertIs(outer.summary, first)
            monitoring.set_episode_stage('speech')
            self.assertEqual(outer.fields(RuntimeError(PRIVATE)), 'stage=speech reason=runtime_error')
        with monitoring.episode_attempt() as following:
            self.assertIsNone(following.summary)

    def test_pipeline_final_failure_has_same_id_and_preserves_the_retry(self):
        with tempfile.TemporaryDirectory() as directory, provider([APIError(400)]), \
                patch.dict(os.environ, {'SITE_DIR': directory + '/site', 'STATE_DIR': directory + '/state'}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            now = datetime.now(timezone.utc).isoformat()
            pub = {'base': 'https://fictional.example', 'name': PRIVATE, 'mode': 'summary', 'any_length': True}
            post = {'id': 'fixture', 'title': PRIVATE, 'post_date': now, 'wordcount': 2000}
            source = types.SimpleNamespace(recent_posts=lambda _: [post], post_text=lambda *_: (post, PRIVATE))
            with patch('main.refresh_descriptions'), patch('tts.synthesize') as speech:
                self.assertEqual(main.run(config.Settings.from_env(), [pub], source), 0)
            state = json.loads((Path(directory) / 'state/state.json').read_text())
            self.assertEqual(len(state['retry']), 1)
            self.assertEqual(state['episodes'], [])
            speech.assert_not_called()
        logs = err.getvalue()
        self.assertIn('Episode failed (stage=summary reason=request_rejected', logs)
        self.assertEqual(len(set(re.findall(r'summary_id=([0-9a-f]{32})', logs))), 1)
        self.assert_private(out.getvalue() + logs)


if __name__ == '__main__':
    unittest.main()
