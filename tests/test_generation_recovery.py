"""Keep healthy work moving and recover assembly/provider edge cases."""
import contextlib
from datetime import datetime, timezone
from enum import Enum
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import security
import storage
import summarize
import tts

PUB = {'base': 'https://fictional.example', 'name': 'Science Notes', 'mode': 'full'}
BODY = 'An original article describes useful experiments and careful observations of the natural world.'


class RetryFairnessTests(unittest.TestCase):
    def run_cases(self, failing, runs, initial_retry=False, cap=None, budget_once=False):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full',
                'MAX_EPISODES_PER_RUN': '1'}, clear=True):
            settings = config.Settings.from_env()
            now = datetime.now(timezone.utc).isoformat()
            posts = [dict(id=i, slug='story-'+str(i), title='Story '+str(i), post_date=now, audience='everyone',
                          canonical_url='https://fictional.example/story-'+str(i)) for i in range(1, 4 if initial_retry else 3)]
            if initial_retry:
                storage.save(settings, {'episodes': [], 'seen': [], 'retry': [{'pub': PUB, 'post': p} for p in posts[:2]], 'last_run': None})
            attempts = []
            def post_text(pub, post):
                attempts.append(post['id'])
                if budget_once and len(attempts) == 1:
                    raise security.RunBudgetExceeded('Fixture work budget')
                if post['id'] in failing:
                    raise RuntimeError('PRIVATE provider detail')
                return post, BODY
            source = types.SimpleNamespace(recent_posts=lambda p: posts, post_text=post_text)
            def narrate(text, path, limit, intro):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-provider-fixture')
                return [path]
            snapshots = []
            with patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10), \
                    patch('security.MAX_RETRY_COUNT', cap or security.MAX_RETRY_COUNT), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                for _ in range(runs):
                    self.assertEqual(main.run(settings, [PUB], source), 0)
                    state = storage.load(settings)
                    snapshots.append({'retry': [row['post']['id'] for row in state['retry']],
                                      'titles': [e['title'] for e in state['episodes']], 'seen': state['seen']})
                    if cap:
                        self.assertLessEqual(len(state['retry']), cap)
            self.assertNotIn('PRIVATE', errors.getvalue())
            return attempts, snapshots

    def test_failed_retry_yields_to_healthy_work_and_remains_available_for_retry(self):
        attempts, snapshots = self.run_cases({1}, 3)
        self.assertEqual(attempts, [1, 2, 1])
        self.assertEqual(snapshots[0]['retry'], [2, 1])
        self.assertEqual(snapshots[-1]['retry'], [1])
        self.assertEqual(len(snapshots[-1]['titles']), 1)
        self.assertIn('Story 2', snapshots[-1]['titles'][0])
        self.assertNotIn(main.post_key(PUB, {'id': 1}), snapshots[-1]['seen'])

    def test_bounded_queue_preserves_saved_failures_and_progresses_waiting_work(self):
        attempts, snapshots = self.run_cases({1}, 4, initial_retry=True, cap=2)
        self.assertEqual(attempts, [1, 2, 1, 3])
        self.assertEqual(snapshots[0]['retry'], [2, 1])
        self.assertEqual(snapshots[-1]['retry'], [1])
        self.assertEqual(len(snapshots[-1]['titles']), 2)
        self.assertTrue(all(1 in s['retry'] for s in snapshots))

    def test_run_budget_deferral_keeps_fifo_priority_without_being_a_failed_retry(self):
        attempts, snapshots = self.run_cases(set(), 3, budget_once=True)
        self.assertEqual(attempts, [1, 1, 2])
        self.assertEqual(snapshots[0]['retry'], [1, 2])
        self.assertEqual(snapshots[-1]['retry'], [])
        self.assertEqual(len(snapshots[-1]['titles']), 2)


class QuotedAudioPathTests(unittest.TestCase):
    def fixture(self, root):
        clip = root / 'source.mp3'
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=24000', '-t', '0.5', str(clip)], capture_output=True, check=True)
        return clip

    def test_real_concat_accepts_apostrophes_spaces_unicode_and_backslashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            directory = root / "O'Neil's café \\ audio"
            directory.mkdir()
            quoted = directory / "speaker's take.mp3"
            shutil.copyfile(source, quoted)
            output = directory / "finished podcast's audio.mp3"
            duration = tts.join_audio([quoted, source], output)
            self.assertGreater(duration, 0.9)
            self.assertLess(duration, 1.5)
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(output), '-f', 'null', '-'],
                           capture_output=True, check=True)

    def test_synthesis_works_when_internal_temporary_directories_contain_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            directory = root / "O'Neil temp"
            directory.mkdir()
            def speak(text, path):
                shutil.copyfile(source, path)
                return True
            with patch('tts.tempfile.tempdir', str(directory)), patch('tts.speak', side_effect=speak):
                seconds = tts.synthesize('An original passage.', directory/'episode.mp3', 10)
            self.assertGreater(seconds, 0)
            self.assertTrue((directory/'episode.mp3').is_file())


class SummaryRecoveryTests(unittest.TestCase):
    def provider(self, generate):
        google = types.ModuleType('google')
        genai = types.ModuleType('google.genai')
        class APIError(Exception):
            def __init__(self, code):
                self.code = code
        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        genai.Client = lambda: types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate))
        genai.errors = types.SimpleNamespace(APIError=APIError)
        genai.types = types.SimpleNamespace(GenerateContentConfig=GenerateContentConfig)
        google.genai = genai
        return {'google': google, 'google.genai': genai}, APIError

    def response(self, text='', finish='STOP', block=None):
        return types.SimpleNamespace(text=text, candidates=[types.SimpleNamespace(finish_reason=finish)],
                                     prompt_feedback=types.SimpleNamespace(block_reason=block))

    def call(self, generate, model=None, words=700):
        modules, _ = self.provider(generate)
        env = {'SUMMARY_MODEL': model} if model else {}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, env, clear=True), \
                patch('summarize.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            return summarize.write_script('Science Notes', 'Alice Writer', 'A discovery', BODY, max_words=words)

    def test_empty_primary_response_can_recover_on_its_next_attempt(self):
        calls = []
        def generate(**kwargs):
            calls.append(kwargs['model'])
            return self.response('A complete summary.' if len(calls) == 2 else '')
        self.assertEqual(self.call(generate), 'A complete summary.')
        self.assertEqual(calls, ['gemini-flash-latest']*2)

    def test_empty_primary_uses_fallback_and_still_obeys_word_budget(self):
        calls = []
        class Block(Enum):
            UNSPECIFIED = 'BLOCKED_REASON_UNSPECIFIED'
        def generate(**kwargs):
            calls.append(kwargs['model'])
            if kwargs['model'] == 'gemini-flash-latest':
                return self.response(block=Block.UNSPECIFIED)
            return self.response('A complete summary. More words that exceed the limit.')
        self.assertEqual(self.call(generate, words=3), 'A complete summary.')
        self.assertEqual(calls, ['gemini-flash-latest']*3+['gemini-flash-lite-latest'])

    def test_empty_responses_stop_at_existing_model_and_attempt_limits(self):
        for selected, expected in ((None, 6), ('gemini-flash-lite-latest', 3)):
            calls = []
            def generate(**kwargs):
                calls.append(kwargs['model'])
                return self.response(None)
            with self.subTest(selected=selected), self.assertRaisesRegex(RuntimeError, 'no script'):
                self.call(generate, model=selected)
            self.assertEqual(len(calls), expected)

    def test_blocked_prompt_or_candidate_is_terminal_even_with_partial_text(self):
        for finish, block in (('SAFETY', None), ('STOP', 'PROHIBITED_CONTENT'), ('RECITATION', None)):
            calls = []
            def generate(**kwargs):
                calls.append(kwargs['model'])
                return self.response('Partial text must not be narrated.', finish, block)
            with self.subTest(finish=finish, block=block), self.assertRaisesRegex(RuntimeError, 'declined'):
                self.call(generate)
            self.assertEqual(len(calls), 1)

    def test_non_transient_api_errors_do_not_retry_or_fall_back(self):
        calls = []
        modules, APIError = self.provider(lambda **kwargs: None)
        def generate(**kwargs):
            calls.append(kwargs['model'])
            raise APIError(400)
        modules['google.genai'].Client = lambda: types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate))
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=True), self.assertRaises(APIError):
            summarize.write_script('Science Notes', 'Alice', 'A discovery', BODY)
        self.assertEqual(len(calls), 1)

    def test_work_budget_exhaustion_stops_before_provider_retry(self):
        calls = []
        def generate(**kwargs):
            calls.append(kwargs['model'])
            return self.response('A complete summary.')
        with patch('security.charge', side_effect=security.RunBudgetExceeded('Fixture budget')):
            with self.assertRaises(security.RunBudgetExceeded):
                self.call(generate)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
