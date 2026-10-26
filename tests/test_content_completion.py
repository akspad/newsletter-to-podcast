"""Only the selected article and complete model responses reach publication."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from google.genai import types as gt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import storage
from substack import Substack

PUB = {'base': 'https://fictional.example', 'page': '/stories/', 'name': 'Science Notes', 'mode': 'full'}
TARGET = ('The target article explains how astronomers compare observations from distant galaxies, '
          'measure the distribution of matter, and plan a larger survey to test their conclusions.')
OTHER = ('An unrelated recommendation describes local weather, garden irrigation, and the different tools '
         'that householders can use when a dry summer reduces their water supply.')
PARTIAL = 'Science Notes. A discovery. The decisive result was'
COMPLETE = 'Science Notes. A discovery. The team found a reproducible seasonal pattern.'
NOW = datetime.now(timezone.utc)
DATE = (NOW-timedelta(days=1)).strftime('%B %d, %Y')
CARD = '<article><h2>Other story</h2><p>'+OTHER+'</p></article>'


class ListingBodyTests(unittest.TestCase):
    def publish(self, html):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state', 'EPISODE_MODE': 'full'}, clear=True):
            settings = config.Settings.from_env()
            source = Substack('')
            spoken = []
            def narrate(text, path, limit, intro):
                spoken.append(text)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-fixture')
                return [path]
            with patch.object(source, 'get', side_effect=['<a href="/stories/target">Target</a>', html]), \
                    patch('tts.synthesize_full', side_effect=narrate), patch('tts.duration', return_value=10), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                status = main.run(settings, [PUB], source)
            return status, storage.load(settings), spoken

    def test_sidebar_card_never_replaces_the_selected_article_body(self):
        story = ('<main><article><h1>Target article</h1><p>'+DATE+'</p>'
                 '<div class="w-richtext"><p>'+TARGET+'</p></div></article></main>')
        for layout in ('<aside>'+CARD+'</aside>'+story, story+'<aside>'+CARD+'</aside>'):
            with self.subTest(layout=layout[:60]):
                status, state, spoken = self.publish('<title>Target article</title>'+layout)
                self.assertEqual(status, 0)
                self.assertEqual(spoken, [TARGET])
                self.assertEqual(state['episodes'][0]['description'], TARGET)
                self.assertEqual(len(state['seen']), 1)
                self.assertEqual(state['retry'], [])

    def test_unwrapped_main_keeps_prose_and_removes_nested_recommendation_articles(self):
        html = ('<title>Target article</title><main>'+CARD+'<h1>Target article</h1><p>'+DATE+'</p>'
                '<p>'+TARGET+'</p><p>'+TARGET+'</p>'+CARD+'</main>')
        status, state, spoken = self.publish(html)
        self.assertEqual(status, 0)
        self.assertEqual(spoken[0].count(TARGET), 2)
        self.assertNotIn(OTHER, spoken[0])
        self.assertNotIn(OTHER, state['episodes'][0]['description'])

    def test_split_richtext_sections_keep_order_without_nested_duplicates_or_hidden_text(self):
        second = 'A second section describes the scientific instruments and explains how measurements are checked.'
        html = ('<title>Target article</title><main><h1>Target article</h1><p>'+DATE+'</p>'
                '<div class="w-richtext"><div class="w-richtext"><p>'+TARGET+'</p></div>'
                '<aside>'+OTHER+'</aside><p hidden>'+OTHER+'</p></div>'
                '<div class="w-richtext"><p>'+second+'</p></div></main>')
        status, _, spoken = self.publish(html)
        self.assertEqual(status, 0)
        self.assertEqual(spoken, [TARGET+'\n'+second])

    def test_unmarked_richtext_layout_still_publishes(self):
        html = ('<title>Target article</title><div><h1>Target article</h1><p>'+DATE+'</p>'
                '<div class="w-richtext"><p>'+TARGET+'</p></div></div>')
        self.assertEqual(self.publish(html)[2], [TARGET])


class SummaryCompletionTests(unittest.TestCase):
    def response(self, text, reason):
        return gt.GenerateContentResponse(candidates=[gt.Candidate(
            finish_reason=reason, content=gt.Content(parts=[gt.Part(text=text)]))])

    def publish(self, behavior, runs=1):
        calls, spoken, states = [], [], []
        def generate(**kwargs):
            calls.append(kwargs['model'])
            return behavior(calls)
        client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate))
        pub = {'base': PUB['base'], 'name': PUB['name'], 'mode': 'summary', 'any_length': True}
        post = {'id': 1, 'slug': 'target', 'title': 'A discovery', 'post_date': NOW.isoformat(),
                'wordcount': 2000, 'audience': 'everyone'}
        source = types.SimpleNamespace(recent_posts=lambda p: [post], post_text=lambda p, q: (post, TARGET))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'SITE_DIR': tmp+'/site', 'STATE_DIR': tmp+'/state'}, clear=True):
            settings = config.Settings.from_env()
            def narrate(text, path, limit):
                spoken.append(text)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ID3-fixture')
                return 10
            with patch('google.genai.Client', return_value=client), patch('summarize.time.sleep'), \
                    patch('tts.synthesize', side_effect=narrate), patch('tts.duration', return_value=10), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                for _ in range(runs):
                    self.assertEqual(main.run(settings, [pub], source), 0)
                    states.append(storage.load(settings))
        return calls, spoken, states

    def test_nonempty_truncated_response_retries_before_narration_and_publication(self):
        calls, spoken, states = self.publish(lambda calls: self.response(
            PARTIAL if len(calls) == 1 else COMPLETE, 'MAX_TOKENS' if len(calls) == 1 else 'STOP'))
        self.assertEqual(calls, ['gemini-flash-latest']*2)
        self.assertEqual(spoken, [COMPLETE])
        self.assertEqual(states[0]['episodes'][0]['description'], COMPLETE)
        self.assertEqual(len(states[0]['seen']), 1)
        self.assertEqual(states[0]['retry'], [])

    def test_persistent_primary_truncation_uses_the_healthy_fallback(self):
        calls, spoken, _ = self.publish(lambda calls: self.response(
            PARTIAL if calls[-1] == 'gemini-flash-latest' else COMPLETE,
            'MAX_TOKENS' if calls[-1] == 'gemini-flash-latest' else 'STOP'))
        self.assertEqual(calls, ['gemini-flash-latest']*3+['gemini-flash-lite-latest'])
        self.assertEqual(spoken, [COMPLETE])

    def test_all_truncated_responses_queue_article_without_publishing_partial_audio(self):
        calls, spoken, states = self.publish(lambda calls: self.response(PARTIAL, 'MAX_TOKENS'))
        self.assertEqual(calls, ['gemini-flash-latest']*3+['gemini-flash-lite-latest']*3)
        self.assertEqual(spoken, [])
        self.assertEqual(states[0]['episodes'], [])
        self.assertEqual(states[0]['seen'], [])
        self.assertEqual(len(states[0]['retry']), 1)

    def test_queued_truncated_summary_can_recover_on_a_later_run(self):
        calls, spoken, states = self.publish(lambda calls: self.response(
            PARTIAL if len(calls) <= 6 else COMPLETE, 'MAX_TOKENS' if len(calls) <= 6 else 'STOP'), runs=2)
        self.assertEqual(len(calls), 7)
        self.assertEqual(states[0]['episodes'], [])
        self.assertEqual(len(states[0]['retry']), 1)
        self.assertEqual(spoken, [COMPLETE])
        self.assertEqual(len(states[1]['episodes']), 1)
        self.assertEqual(states[1]['retry'], [])

    def test_block_signal_remains_terminal_even_when_finish_reason_is_max_tokens(self):
        def blocked(calls):
            response = self.response(PARTIAL, 'MAX_TOKENS')
            response.prompt_feedback = gt.GenerateContentResponsePromptFeedback(block_reason='SAFETY')
            return response
        calls, spoken, states = self.publish(blocked)
        self.assertEqual(len(calls), 1)
        self.assertEqual(spoken, [])
        self.assertEqual(states[0]['episodes'], [])
        self.assertEqual(len(states[0]['retry']), 1)


if __name__ == '__main__':
    unittest.main()
