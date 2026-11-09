"""Substack discovery keeps its bounded window across cursor and legacy pages."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import main
import security
import storage
from substack import SourceDownloadError, Substack
from curl_cffi.requests.exceptions import Timeout

PUB = {'base': 'https://fictional.example', 'name': 'Science Notes', 'mode': 'full'}
URL = PUB['base'] + '/api/v1/archive'
NOW = datetime.now(timezone.utc)


def posts(start, count):
    return [{'id': i, 'slug': f'article-{i}', 'title': f'Article {i}',
             'post_date': (NOW - timedelta(days=1 + i / 10)).isoformat(),
             'audience': 'everyone', 'wordcount': 1000} for i in range(start, start + count)]


class ArchivePaginationTests(unittest.TestCase):
    def setUp(self):
        self.source = Substack('')

    def test_default_window_uses_three_cursor_pages_without_offset(self):
        pages = [{'posts': posts(0, 20), 'nextCursor': 'next-one'},
                 {'posts': posts(20, 20), 'nextCursor': 'next-two'},
                 {'posts': posts(40, 10), 'nextCursor': 'next-three'}]
        with patch.object(self.source, 'get', side_effect=pages) as get:
            result = self.source.recent_posts(PUB)
        self.assertEqual(result, posts(0, 50))
        self.assertTrue(result.complete)
        self.assertEqual(get.call_args_list, [call(URL, sort='new', limit=20),
                         call(URL, sort='new', limit=20, cursor='next-one'),
                         call(URL, sort='new', limit=10, cursor='next-two')])

    def test_legacy_list_pages_use_offsets_and_keep_the_same_window(self):
        with patch.object(self.source, 'get', side_effect=[posts(0, 20), posts(20, 20), posts(40, 10)]) as get:
            result = self.source.recent_posts(PUB)
        self.assertEqual(result, posts(0, 50))
        self.assertTrue(result.complete)
        self.assertEqual(get.call_args_list, [call(URL, sort='new', limit=20),
                         call(URL, sort='new', limit=20, offset=20),
                         call(URL, sort='new', limit=10, offset=40)])

    def test_short_legacy_or_terminal_cursor_page_stops_early(self):
        for page in [posts(0, 3), [], {'posts': posts(0, 20), 'nextCursor': None},
                     {'posts': posts(0, 3), 'nextCursor': None}, {'posts': [], 'nextCursor': None}]:
            with self.subTest(page=type(page)), patch.object(self.source, 'get', return_value=page) as get:
                result = self.source.recent_posts(PUB)
                self.assertTrue(result.complete)
                get.assert_called_once()

    def test_short_cursor_page_can_continue_but_requests_stay_bounded(self):
        pages = [{'posts': posts(i, 1), 'nextCursor': f'next-{i}'} for i in range(3)]
        with patch.object(self.source, 'get', side_effect=pages) as get:
            result = self.source.recent_posts(PUB)
        self.assertEqual(result, posts(0, 3))
        self.assertFalse(result.complete)
        self.assertEqual(get.call_count, 3)

    def test_small_limit_and_global_ceiling_are_applied_to_requests(self):
        for requested, ceiling, expected in [(3, 500, 3), (50, 7, 7)]:
            with self.subTest(requested=requested), patch('security.MAX_SOURCE_ENTRIES', ceiling), \
                    patch.object(self.source, 'get', return_value={'posts': posts(0, expected), 'nextCursor': 'later'}) as get:
                result = self.source.recent_posts(PUB, limit=requested)
            self.assertEqual(len(result), expected)
            self.assertTrue(result.complete)
            get.assert_called_once_with(URL, sort='new', limit=expected)
        with patch.object(self.source, 'get') as get:
            for limit in [0, -1]:
                self.assertEqual(self.source.recent_posts(PUB, limit=limit), [])
            get.assert_not_called()

    def test_bad_or_oversized_page_is_never_treated_as_an_empty_success(self):
        for page in [None, 'not a page', {}, {'posts': {}}, {'posts': [], 'nextCursor': []},
                     {'posts': [], 'nextCursor': ''}, {'posts': [], 'nextCursor': '  '},
                     {'posts': [], 'nextCursor': 'x' * 4097}]:
            with self.subTest(page=type(page)), patch.object(self.source, 'get', return_value=page):
                with self.assertRaises(ValueError):
                    self.source.recent_posts(PUB)
        with patch.object(self.source, 'get', return_value=posts(0, 100)) as get:
            result = self.source.recent_posts(PUB)
        self.assertEqual(result, posts(0, 20))
        self.assertFalse(result.complete)
        get.assert_called_once()

    def test_missing_cursor_in_new_envelope_fails_first_page_or_preserves_partial_scan(self):
        for page in [{'posts': []}, {'posts': posts(20, 2)}]:
            with self.subTest(entries=len(page['posts'])), patch.object(self.source, 'get', return_value=page):
                with self.assertRaises(ValueError):
                    self.source.recent_posts(PUB)
            with patch.object(self.source, 'get', side_effect=[{'posts': posts(0, 20), 'nextCursor': 'next'}, page]):
                result = self.source.recent_posts(PUB)
                self.assertEqual(result, posts(0, 20))
                self.assertFalse(result.complete)

    def test_repeated_cursor_or_page_stops_and_deduplicates_without_losing_catchup(self):
        cases = [
            [{'posts': posts(0, 20), 'nextCursor': 'same'}, {'posts': posts(20, 20), 'nextCursor': 'same'}],
            [posts(0, 20), posts(0, 20)],
            [{'posts': posts(0, 20), 'nextCursor': 'one'}, {'posts': [], 'nextCursor': 'two'}],
            [{'posts': posts(0, 20), 'nextCursor': 'one'}, {'posts': posts(0, 20), 'nextCursor': None}],
            [posts(0, 20), posts(0, 10)],
        ]
        for pages in cases:
            with self.subTest(kind=type(pages[0])), patch.object(self.source, 'get', side_effect=pages) as get:
                result = self.source.recent_posts(PUB)
                self.assertFalse(result.complete)
                self.assertEqual(len(result), len({post['id'] for post in result}))
                self.assertEqual(get.call_count, 2)

    def test_overlapping_pages_cannot_extend_the_entry_or_request_budget(self):
        pages = [{'posts': posts(0, 20), 'nextCursor': 'one'},
                 {'posts': posts(19, 20), 'nextCursor': 'two'},
                 {'posts': posts(38, 10), 'nextCursor': 'three'}]
        with patch.object(self.source, 'get', side_effect=pages) as get:
            result = self.source.recent_posts(PUB)
        self.assertEqual(result, posts(0, 48))
        self.assertFalse(result.complete)
        self.assertEqual(get.call_count, 3)

    def test_failed_first_page_raises_and_failed_later_page_keeps_discoveries(self):
        for error in [SourceDownloadError('PRIVATE response', 503), Timeout('PRIVATE timeout'),
                      ValueError('PRIVATE malformed JSON')]:
            with self.subTest(error=type(error)), patch.object(self.source, 'get', side_effect=error):
                with self.assertRaises(type(error)):
                    self.source.recent_posts(PUB)
            with patch.object(self.source, 'get', side_effect=[{'posts': posts(0, 20), 'nextCursor': 'next'}, error]):
                result = self.source.recent_posts(PUB)
                self.assertEqual(result, posts(0, 20))
                self.assertFalse(result.complete)

    def test_download_and_runtime_budgets_still_propagate_after_usable_pages(self):
        for error in [security.BudgetExceeded('budget'), security.RunBudgetExceeded('budget')]:
            with self.subTest(error=type(error)), patch.object(self.source, 'get', side_effect=[posts(0, 20), error]):
                with self.assertRaises(type(error)):
                    self.source.recent_posts(PUB)

    def test_partial_scan_preserves_checkpoints_until_older_page_recovers(self):
        for scheduled in [False, True]:
            with self.subTest(scheduled=scheduled), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {'SITE_DIR': tmp + '/site', 'STATE_DIR': tmp + '/state',
                               'EPISODE_MODE': 'full', **({'GITHUB_EVENT_NAME': 'schedule'} if scheduled else {})}, clear=True):
                settings = config.Settings.from_env()
                previous = (NOW - timedelta(days=30)).isoformat()
                initial = {'episodes': [], 'seen': [], 'retry': [], 'last_run': previous, 'last_scheduled_run': previous}
                storage.save(settings, initial)
                created = []
                def create(source, pub, post, now, state, settings):
                    created.append(post['id'])
                pages = [{'posts': posts(0, 20), 'nextCursor': 'next'}, Timeout('PRIVATE response'),
                         {'posts': posts(0, 20), 'nextCursor': 'next'}, {'posts': posts(20, 2), 'nextCursor': None}]
                with patch.object(self.source, 'get', side_effect=pages), patch('main.make_episode', side_effect=create), \
                        patch('main.refresh_descriptions'), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(main.run(settings, [PUB], self.source), 0)
                    partial = storage.load(settings)
                    self.assertEqual(partial['last_run'], previous)
                    self.assertEqual(partial['last_scheduled_run'], previous)
                    self.assertIn('catchup_since', partial)
                    self.assertEqual(created, list(range(20)))
                    self.assertEqual(main.run(settings, [PUB], self.source), 0)
                recovered = storage.load(settings)
                self.assertNotEqual(recovered['last_run'], previous)
                if scheduled:
                    self.assertNotEqual(recovered['last_scheduled_run'], previous)
                self.assertNotIn('catchup_since', recovered)
                self.assertEqual(created[-2:], [20, 21])
                self.assertEqual(len(created), 22)
                self.assertIn('scan incomplete', errors.getvalue())
                self.assertNotIn('PRIVATE', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
