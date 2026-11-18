"""Run real RSS/Atom discovery across retries, with fictional feeds and local audio doubles."""
import contextlib
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import security
import storage
from substack import Substack


class EmptyFeedRetryTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(contextlib.ExitStack())
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.outputs = tmp / 'outputs'
        stack.enter_context(patch.dict(os.environ, {
            'SITE_DIR': str(tmp / 'site'), 'STATE_DIR': str(tmp / 'state'),
            'GITHUB_OUTPUT': str(self.outputs), 'EPISODE_MODE': 'full'}, clear=True))
        self.settings = config.Settings.from_env()
        self.pub = {'name': 'Fixture', 'base': 'https://fictional.example/feed', 'rss': True}
        self.source = Substack('')
        self.download = stack.enter_context(patch.object(self.source, 'get'))
        self.now = datetime.now(timezone.utc).isoformat()
        def render(text, path, seconds, intro):
            path.write_bytes(b'fictional audio')
            return [path]
        self.speech = stack.enter_context(patch('tts.synthesize_full', side_effect=render))
        stack.enter_context(patch('tts.duration', return_value=7))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.log = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def publish_fixture(self, body, atom=False, date=None):
        date = date or self.now
        if atom:
            self.download.return_value = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>abc</id><updated>{date}</updated><title>A report</title><content>{body}</content></entry></feed>'
        else:
            self.download.return_value = f'<rss><channel><item><guid>abc</guid><pubDate>{date}</pubDate><title>A report</title><description>{body}</description></item></channel></rss>'

    def cycle(self):
        self.outputs.write_text('')
        self.assertEqual(main.run(self.settings, [self.pub], self.source), 0)
        self.counts = dict(line.split('=') for line in self.outputs.read_text().splitlines())
        return storage.load(self.settings)

    def test_atom_empty_exhaustion_and_late_recovery_once(self):
        self.publish_fixture('', atom=True)
        for failure in (1, 2):
            state = self.cycle()
            self.assertEqual(state['retry'][0]['empty_feed_attempts'], failure)
            self.assertEqual(self.counts['failed_articles'], '1')
        state = self.cycle()
        self.assertEqual(self.counts['skipped_articles'], '1')
        self.assertEqual(self.counts['failed_articles'], '0')
        self.assertEqual(state['retry'], [])
        self.assertEqual(state['seen'], [])
        self.assertIn('empty feed attempt limit reached', self.log.getvalue())
        self.cycle()
        self.assertEqual(self.counts['attempted_articles'], '0')
        self.speech.assert_not_called()
        self.publish_fixture('One short sentence.', atom=True, date='2000-01-01T00:00:00Z')
        state = self.cycle()
        self.assertEqual(len(state['episodes']), 1)
        self.assertEqual(state['empty_feed_keys'], [])
        self.cycle()
        self.assertEqual(self.speech.call_count, 1)
        self.assertEqual(self.speech.call_args.args[0], 'One short sentence.')

    def test_legacy_rss_retry_with_old_date_uses_fresh_text(self):
        self.publish_fixture('', date='2000-01-01T00:00:00Z')
        post, = self.source.recent_posts(self.pub)
        storage.save(self.settings, {'episodes': [], 'seen': [], 'retry': [{'pub': self.pub, 'post': post}]})
        self.publish_fixture('A newly supplied paragraph.', date='2000-01-01T00:00:00Z')
        state = self.cycle()
        self.assertEqual(len(state['episodes']), 1)
        self.assertEqual(state['retry'], [])
        self.assertEqual(self.speech.call_args.args[0], 'A newly supplied paragraph.')

    def test_budget_deferral_and_absent_entry_preserve_empty_attempts(self):
        self.publish_fixture('')
        self.cycle()
        self.download.return_value = '<rss><channel/></rss>'
        with patch.object(self.source, 'post_text', side_effect=security.RunBudgetExceeded()):
            state = self.cycle()
        self.assertEqual(self.counts['deferred_articles'], '1')
        self.assertEqual(state['retry'][0]['empty_feed_attempts'], 1)
        self.assertEqual(self.cycle()['retry'][0]['empty_feed_attempts'], 2)
        self.assertEqual(self.cycle()['retry'], [])

    def test_readable_saved_feed_copy_survives_empty_update_after_speech_failure(self):
        self.publish_fixture('')
        self.cycle()
        self.publish_fixture('The recovered text.')
        with patch('tts.synthesize_full', side_effect=RuntimeError('temporary')):
            state = self.cycle()
        self.assertNotIn('empty_feed_attempts', state['retry'][0])
        self.publish_fixture('')
        self.assertEqual(len(self.cycle()['episodes']), 1)
        self.assertEqual(self.speech.call_args.args[0], 'The recovered text.')
