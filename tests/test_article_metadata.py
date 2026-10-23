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
    def test_tracking_parameters_do_not_select_an_unrelated_schema_author(self):
        data = [{'@type': 'Article', 'url': 'https://fictional.example/other', 'headline': 'Other story',
                 'author': {'name': 'Other Writer'}},
                {'@type': 'Article', 'url': 'https://fictional.example/story', 'headline': 'Requested article',
                 'author': {'name': 'Correct Writer'}}]
        html = ('<script type="application/ld+json">' + json.dumps(data) + '</script>'
                '<meta property="og:title" content="Requested article">'
                '<main><article><h1>Requested article</h1><p class="byline">Correct Writer</p></article></main>')
        for query in ('', '?utm_source=newsletter', '?fbclid=tracking&utm_medium=email#section'):
            with self.subTest(query=query):
                self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'),
                                 'https://fictional.example/story' + query)[1:], ('Requested article', 'Correct Writer'))

    def test_content_selecting_query_parameters_remain_distinct(self):
        data = [{'@type': 'Article', 'url': 'https://fictional.example/story?id=1',
                 'headline': 'First story', 'author': {'name': 'First Writer'}},
                {'@type': 'Article', 'url': 'https://fictional.example/story?id=2',
                 'headline': 'Second story', 'author': {'name': 'Second Writer'}}]
        html = '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'),
                         'https://fictional.example/story?id=2&utm_source=email')[1:], ('Second story', 'Second Writer'))

    def test_canonical_and_main_entity_metadata_identify_the_article_after_a_redirect(self):
        for identity in ({'mainEntityOfPage': {'@id': 'https://fictional.example/story'}},
                         {'url': 'https://fictional.example/story'}):
            data = [{'@type': 'Article', 'url': 'https://fictional.example/other', 'author': {'name': 'Other Writer'}},
                    {'@type': 'Article', **identity, 'headline': 'Requested article', 'author': {'name': 'Correct Writer'}}]
            html = ('<link rel="canonical" href="/story"><script type="application/ld+json">' + json.dumps(data) + '</script>')
            with self.subTest(identity=identity):
                self.assertEqual(article_metadata(BeautifulSoup(html, 'html.parser'),
                                 'https://fictional.example/old-link')[2], 'Correct Writer')

    def test_inline_hidden_headlines_and_author_lists_cannot_override_visible_attribution(self):
        html = ('<meta property="og:title" content="Requested article"><main>'
                '<div style="display:none"><h1>Requested article</h1><div class="article-authors">Other Writer</div></div>'
                '<article><h1>Requested article</h1><div class="article-authors">Correct Writer</div></article></main>')
        self.assertEqual(metadata(html)[1:], ('Requested article', 'Correct Writer'))

    def test_byline_and_title_follow_the_requested_article_instead_of_an_earlier_card(self):
        for byline in ('<div class="article-authors"><a>{}</a></div>', '<p class="byline">{}</p>'):
            html = ('<meta property="og:title" content="Requested article">'
                    '<main><article><h1>Other article</h1>' + byline.format('Other Writer') + '</article>'
                    '<article><h1>Requested article</h1>' + byline.format('Correct Writer') + '</article></main>')
            with self.subTest(byline=byline):
                self.assertEqual(metadata(html)[1:], ('Requested article', 'Correct Writer'))

    def test_unmarked_author_card_cannot_override_the_selected_article_author(self):
        html = ('<meta property="og:title" content="Requested article">'
                '<section><article><div class="article-authors"><a>Other Writer</a></div></article></section>'
                '<main><article><h1>Requested article</h1>'
                '<div class="article-authors"><a>Correct Writer</a></div></article></main>')
        self.assertEqual(metadata(html)[2], 'Correct Writer')
        # With no visible byline on the requested article, omit the author.
        self.assertEqual(metadata(html.replace('<a>Correct Writer</a>', ''))[2], '')

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
        self.assertEqual(metadata('<a href="http://[broken">Broken menu link</a>' + html),
                         ('Science Notes', 'A discovery', ''))
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

    def test_visible_author_group_overrides_generic_schema_without_losing_coauthors(self):
        html = ('<script type="application/ld+json">'
                '{"@type":"Article","author":{"name":"The Editors"}}</script>'
                '<div class="article-authors"><span>By: </span><a href="/daily-author/alex">Alex Writer</a>'
                '<a href="/daily-author/sam">Sam Author</a></div><article><h1>A discovery</h1></article>')
        self.assertEqual(metadata(html)[2], 'Alex Writer, Sam Author')
        self.assertEqual(metadata(html.replace('<a href="/daily-author/alex">Alex Writer</a>'
                                             '<a href="/daily-author/sam">Sam Author</a>', 'Alex Writer'))[2], 'Alex Writer')

    def test_hidden_and_related_author_groups_do_not_override_attribution(self):
        html = ('<script type="application/ld+json">'
                '{"@type":"Article","author":{"name":"Alex Writer"}}</script>'
                '<div hidden><div class="article-authors"><a>Hidden Name</a></div></div>'
                '<aside><div class="article-authors"><a>Related Name</a></div></aside>')
        self.assertEqual(metadata(html)[2], 'Alex Writer')

    def test_matching_nonsemantic_headline_uses_visible_text_without_markdown(self):
        html = ('<meta property="og:site_name" content="Science Notes">'
                '<title>The *Quiet Book* (1677) — Science Notes</title>'
                '<div class="collection-header"><h1>The <em>Quiet Book</em> (1677)</h1></div>')
        self.assertEqual(metadata(html), ('Science Notes', 'The Quiet Book (1677)', ''))
        html = '<meta property="og:title" content="Actual article"><div><h1>Unrelated branding</h1></div>'
        self.assertEqual(metadata(html)[1], 'Actual article')


if __name__ == '__main__':
    unittest.main()
