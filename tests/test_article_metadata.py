"""Attribution regressions from public blog layouts, using fictional content."""
import json
from pathlib import Path
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_metadata import article_metadata


def metadata(html):
    return article_metadata(BeautifulSoup(html, 'html.parser'), 'https://fictional.example/story')


class ArticleMetadataTests(unittest.TestCase):
    def test_linked_schema_authors_and_publisher_resolve_without_a_request(self):
        data = {'@graph': [
            {'@type': 'Article', 'headline': 'A discovery', 'author': [{'@id': '#alex'}, {'@id': '#sam'}],
             'publisher': {'@id': '#publisher'}},
            {'@id': '#alex', '@type': 'Person', 'name': 'Alex Writer'},
            {'@id': '#sam', '@type': 'Person', 'name': 'Sam Author'},
            {'@id': '#publisher', '@type': 'Organization', 'name': 'Science Notes'},
        ]}
        self.assertEqual(metadata('<script type="application/ld+json">' + json.dumps(data) + '</script>'),
                         ('Science Notes', 'A discovery', 'Alex Writer, Sam Author'))

    def test_visible_headline_and_article_heading_win_over_seo_title_and_branding(self):
        html = ('<meta property="og:site_name" content="Science Notes">'
                '<meta property="og:title" content="A discovery - Science Notes">'
                '<main><h1>Science Notes</h1><h1>A discovery</h1></main>')
        self.assertEqual(metadata(html), ('Science Notes', 'A discovery', ''))
        html = ('<script type="application/ld+json">{"@type":"Article","headline":"An SEO title"}</script>'
                '<main><h1>A visible headline</h1></main>')
        self.assertEqual(metadata(html)[1], 'A visible headline')

    def test_home_identity_and_feed_title_clean_publication_suffixes(self):
        html = ('<nav><a href="/" title="Home">Home</a><a href="/">Science Notes logo</a></nav>'
                '<meta property="og:title" content="A discovery | Science Notes">')
        self.assertEqual(metadata(html), ('Science Notes', 'A discovery', ''))
        html = ('<link rel="alternate" type="application/atom+xml" title="The Research Blog">'
                '<main><h1>The Research Blog</h1><h1>A discovery</h1></main><title>A discovery - Research</title>')
        self.assertEqual(metadata(html), ('The Research Blog', 'A discovery', ''))

    def test_visible_author_links_and_affiliations(self):
        for byline in ('<header><a href="/authors/alex">Alex Writer</a><time>October 2026</time></header>',
                       '<p class="author">Alex Writer<br>2 September 2026</p>',
                       '<div class="news-article--authored-by">Alex Writer | Research Lab</div>',
                       '<p class="byline">Alex Writer, Chief Research Officer</p>'):
            with self.subTest(byline=byline):
                self.assertEqual(metadata('<main><h1>A discovery</h1>' + byline + '</main>')[2], 'Alex Writer')

    def test_specialized_bylines_and_institution_labels(self):
        html = ('<meta property="og:site_name" content="Science Notes | Research Institute">'
                '<main><h1>A discovery</h1><div class="basic-hero--blog-detail__description">'
                '<p>October 5, 2026</p><p>Alex Writer, Research Scientist, and Sam Author, Principal Scientist, '
                'Research Institute</p></div></main>')
        self.assertEqual(metadata(html), ('Science Notes', 'A discovery', 'Alex Writer, Sam Author'))
        html = '<div class="publish-date-author">Sept. 21, 2026 · Alex Writer on behalf of security-response</div>'
        self.assertEqual(metadata(html)[2], 'Alex Writer')

    def test_malformed_references_do_not_invent_authors_or_loop(self):
        data = {'@graph': [{'@type': 'Article', 'author': {'@id': '#a'}},
                           {'@id': '#a', 'name': None}, {'@id': '#b', '@type': 'Person'}]}
        html = '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        self.assertEqual(metadata(html)[2], '')
        self.assertEqual(metadata('<article><h1>A discovery</h1><p>As '
                                  '<a href="/authors/somebody">Another Writer</a> said.</p></article>')[2], '')


if __name__ == '__main__':
    unittest.main()
