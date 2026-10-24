"""Listing discovery must support ordinary HTML links and isolate failures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from substack import Substack
from curl_cffi.requests.exceptions import Timeout
import security

PUB = {'base': 'https://fictional.example', 'page': '/stories/', 'name': 'Science Notes'}
ARTICLE = ('<title>A discovery</title><main><h1>A discovery</h1><p>October 23, 2026</p>'
           '<div class="w-richtext"><p>An original article body.</p></div></main>')


class PageAdapterTests(unittest.TestCase):
    def test_equivalent_links_import_once_with_the_existing_identity(self):
        listing = ("<a href='/stories/one'>One</a>" '<a href="https://fictional.example/stories/one">One</a>'
                   '<a href="/stories/one?utm_source=home#intro">One</a>')
        source = Substack('')
        with patch.object(source, 'get', side_effect=[listing, ARTICLE]) as get:
            posts = source.recent_posts(PUB)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]['canonical_url'], 'https://fictional.example/stories/one')
        self.assertEqual(posts[0]['id'], 406963629313)  # ID produced before link discovery changed.
        self.assertEqual(get.call_count, 2)

    def test_discovery_rejects_other_origins_and_keeps_functional_queries(self):
        listing = ''.join('<a href="' + href + '">Link</a>' for href in (
            'https://other.example/stories/one', 'https://fictional.example:444/stories/one',
            'https://fictional.example:0/stories/one', 'https://user@fictional.example/stories/one',
            'http://fictional.example/stories/one', 'javascript:alert(1)', 'https://[bad',
            '/unrelated/one', '/stories/', '#section',
            '/stories/one?id=1&amp;utm_medium=email#intro'))
        source = Substack('')
        with patch.object(source, 'get', side_effect=[listing, ARTICLE]) as get:
            posts = source.recent_posts(PUB)
        self.assertEqual(posts[0]['canonical_url'], 'https://fictional.example/stories/one?id=1')
        self.assertEqual(get.call_args_list[1].args[0], 'https://fictional.example/stories/one?id=1')
        self.assertEqual(get.call_count, 2)

    def test_final_listing_url_resolves_relative_links_without_changing_legacy_ids(self):
        source = Substack('')
        def fetch(url, **kwargs):
            if url == PUB['base']:
                source.last_url = 'https://publication.example/catalog/'
                return '<a href="../stories/one">One</a>'
            self.assertEqual(url, 'https://publication.example/stories/one')
            return ARTICLE
        with patch.object(source, 'get', side_effect=fetch):
            post = source.recent_posts(PUB)[0]
        self.assertEqual(post['id'], 406963629313)
        self.assertEqual(post['canonical_url'], 'https://publication.example/stories/one')

    def test_timed_out_articles_do_not_abort_later_articles(self):
        source = Substack('')
        listing = '<a href="/stories/bad">Bad</a><a href="/stories/good">Good</a>'
        for error in (Timeout('Simulated timeout'), ConnectionError('Simulated failure')):
            with self.subTest(error=type(error).__name__), patch.object(source, 'get', side_effect=[listing, error, ARTICLE]) as get:
                posts = source.recent_posts(PUB)
                self.assertEqual(len(posts), 1)
                self.assertEqual(posts[0]['canonical_url'], 'https://fictional.example/stories/good')
                self.assertEqual(get.call_count, 3)

    def test_resource_budgets_still_stop_listing_work(self):
        source = Substack('')
        listing = '<a href="/stories/one">One</a><a href="/stories/two">Two</a>'
        for error in (security.BudgetExceeded('Budget exceeded'), security.RunBudgetExceeded('Run budget exceeded')):
            with self.subTest(error=type(error).__name__), patch.object(source, 'get', side_effect=[listing, error, ARTICLE]) as get:
                with self.assertRaises(type(error)):
                    source.recent_posts(PUB)
                self.assertEqual(get.call_count, 2)
        with patch.object(source, 'get', side_effect=[listing, ARTICLE]) as get:
            self.assertEqual(len(source.page_posts(PUB, 1)), 1)
            self.assertEqual(get.call_count, 2)

    def test_invalid_article_dates_do_not_discard_valid_pages(self):
        source = Substack('')
        listing = '<a href="/stories/bad">Bad</a><a href="/stories/good">Good</a>'
        with patch.object(source, 'get', side_effect=[listing, ARTICLE.replace('October 23', 'February 30'), ARTICLE]):
            posts = source.recent_posts(PUB)
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0]['canonical_url'].endswith('/stories/good'))


if __name__ == '__main__':
    unittest.main()
