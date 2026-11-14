"""Flat static-blog article bodies must retain facts that exist only in headings."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_extract import extract_text
from article_metadata import article_metadata
from article_scope import article_scope, masthead_body
from substack import Substack
import preview

URL = 'https://fictional.example/blog/awards/'
TITLE = 'Conference plans and community awards'
AUTHOR = 'Conference Organizing Team'
OPENING = ('The organizers announced the next meeting and reviewed the research presented last year. '
           'The program will bring together researchers who compare observations, share tools and discuss future work.')
ENDING = 'Applications are open until the end of March. Reviewers can volunteer by completing the form.'
MASTHEAD = ('<div class="container blog-title"><div class="blog-title-heading"><h1>' + TITLE + '</h1></div>'
            '<p><span class="blog-meta-date">14 November 2026</span> | '
            '<span class="blog-meta-author">' + AUTHOR + '</span></p></div>')
BLOCKS = ('<h2 id="next"><a href="#next">Next conference announced</a></h2><p>' + OPENING + '</p>'
          '<h3>Key dates</h3><ul><li>Proposals open in January.</li><li>Tickets go on sale in February.</li></ul>'
          '<h3>Community awards</h3><p>The committee recognized the following contributors.</p>'
          '<h4 id="alex"><a class="header-anchor" href="#alex"><strong>Alex Researcher</strong></a></h4>'
          '<p>For maintaining the measurement tools.</p>'
          '<h4 id="team"><em>Sam Scientist and Jordan Engineer</em></h4><p>For their work on data analysis.</p>'
          '<h5>Proceedings</h5><p>' + ENDING + '</p><h6>Reviewers</h6><p>New reviewers are welcome.</p>')
EXPECTED = ('Next conference announced ' + OPENING + ' Key dates Proposals open in January. '
            'Tickets go on sale in February. Community awards The committee recognized the following contributors. '
            'Alex Researcher For maintaining the measurement tools. Sam Scientist and Jordan Engineer '
            'For their work on data analysis. Proceedings ' + ENDING + ' Reviewers New reviewers are welcome.')


def page(blocks=BLOCKS, masthead=MASTHEAD, between='<!-- body follows --><br><a class="edit-float" href="/edit"></a>'):
    return ('<html><head><title>' + TITLE + '</title><meta property="og:title" content="' + TITLE + '">'
            '<meta name="author" content="' + AUTHOR + '"></head><body>' + masthead + between +
            '<div class="container main">' + blocks + '</div></body></html>')


def read(html):
    return extract_text(BeautifulSoup(html, 'html.parser'), TITLE, AUTHOR, URL)


class UnmarkedHeadingTests(unittest.TestCase):
    def test_heading_only_winners_and_short_contributions_keep_order_once(self):
        self.assertEqual(read(page()), EXPECTED)
        with patch('substack.Substack.get', return_value=page()), contextlib.redirect_stderr(io.StringIO()):
            narration = preview.article_text(URL)
        self.assertEqual(narration.partition('\n')[2], EXPECTED)
        self.assertEqual(narration.count(TITLE), 1)
        self.assertEqual(narration.count(AUTHOR), 1)
        self.assertEqual(narration.count('Alex Researcher'), 1)
        self.assertEqual(article_metadata(BeautifulSoup(page(), 'html.parser'), URL)[1:], (TITLE, AUTHOR))

    def test_self_linked_and_emphasized_headings_do_not_require_anchor_classes(self):
        for markup in ('<h4><a href="#winner">Alex Researcher</a></h4>',
                       '<h4><strong><em>Alex Researcher</em></strong></h4>',
                       '<h4>Alex Researcher</h4>'):
            html = page('<h2>Findings</h2><p>' + OPENING + '</p>' + markup + '<p>A short contribution.</p>')
            self.assertEqual(read(html), 'Findings ' + OPENING + ' Alex Researcher A short contribution.')

    def test_inline_words_lists_and_intentional_repetition_are_preserved(self):
        blocks = ('<h2><span>Re</span>search results</h2><p>' + OPENING + '</p>'
                  '<h4>Repeated name</h4><p>A repeated contribution.</p>'
                  '<h4>Repeated name</h4><p>A repeated contribution.</p>')
        text = read(page(blocks))
        self.assertTrue(text.startswith('Research results '))
        self.assertEqual(text.count('Repeated name A repeated contribution.'), 2)

    def test_body_selection_excludes_navigation_footer_comments_and_unrelated_cards(self):
        boilerplate = ('<nav><h2>Navigation heading</h2><p>Navigation prose.</p></nav>'
                       '<article><h2>Other article</h2><p>Other article prose.</p></article>'
                       '<div class="comments"><h4>Comment author</h4><p>Comment prose.</p></div>'
                       '<div class="related-posts"><h3>Related heading</h3><p>Related prose.</p></div>'
                       '<footer><h3>Footer heading</h3><p>Footer prose.</p></footer>')
        html = page(BLOCKS + boilerplate) + '<h2>Outside body heading</h2><p>Outside body prose.</p>'
        self.assertEqual(read(html), EXPECTED)

    def test_hidden_headings_and_repeated_metadata_do_not_enter_body(self):
        for hidden in ('<h4 hidden>Hidden winner</h4>', '<h4 style="display:none">Hidden winner</h4>',
                       '<h4 aria-hidden="true">Hidden winner</h4>'):
            blocks = '<h1>' + TITLE + '</h1><p class="post-meta">Metadata label.</p>' + BLOCKS + hidden
            self.assertEqual(read(page(blocks)), EXPECTED)

    def test_generic_main_or_mismatched_masthead_is_not_trusted_as_a_body(self):
        for html in (page(masthead=''), page(masthead=MASTHEAD.replace(TITLE, 'Another story')),
                     page(masthead=MASTHEAD.replace('blog-title', 'site-title')),
                     page(masthead=MASTHEAD.replace('blog-meta-date', 'plain').replace('blog-meta-author', 'plain')),
                     page().replace('container main', 'main')):
            with self.subTest(html=html[:90]):
                self.assertIsNone(masthead_body(BeautifulSoup(html, 'html.parser'), TITLE))

    def test_body_cannot_borrow_masthead_across_content_or_another_story(self):
        for between in ('<p>An intervening story.</p>', 'Unwrapped intervening prose.',
                        '<a href="/other">Another article</a>', '<img src="/other.jpg">',
                        '<div><h2>Other story</h2></div>'):
            self.assertIsNone(masthead_body(BeautifulSoup(page(between=between), 'html.parser'), TITLE))

    def test_hidden_quoted_or_conflicting_mastheads_cannot_identify_body(self):
        for masthead in (MASTHEAD.replace('container blog-title', 'container blog-title" hidden data-unused="'),
                         MASTHEAD.replace('<h1>', '<blockquote><h1>').replace('</h1>', '</h1></blockquote>'),
                         MASTHEAD.replace('</h1>', '</h1><h1>Another headline</h1>')):
            self.assertIsNone(masthead_body(BeautifulSoup(page(masthead=masthead), 'html.parser'), TITLE))

    def test_unknown_sidebar_container_keeps_density_based_selection(self):
        html = page(BLOCKS + '<div class="sidebar"><h3>Unrelated sidebar heading</h3>'
                    '<a href="/one">Other article</a><a href="/two">Another story</a></div>')
        soup = BeautifulSoup(html, 'html.parser')
        self.assertIsNone(masthead_body(soup, TITLE))
        self.assertNotIn('Unrelated sidebar heading', read(html))

    def test_ambiguous_parallel_bodies_are_not_promoted(self):
        html = page() + page()
        self.assertIsNone(masthead_body(BeautifulSoup(html, 'html.parser'), TITLE))

    def test_matching_semantic_article_keeps_priority_over_layout_recovery(self):
        article = '<article><h1>' + TITLE + '</h1><div class="entry-content"><p>Requested semantic body.</p></div></article>'
        html = page() + article
        self.assertEqual(article_scope(BeautifulSoup(html, 'html.parser'), TITLE, URL).name, 'article')
        self.assertEqual(read(html), 'Requested semantic body.')

    def test_rss_blurb_remains_publisher_supplied_without_page_fetch(self):
        blurb = '<p>A brief publisher-supplied announcement blurb.</p>'
        xml = ('<rss><channel><item><guid>announcement</guid><title>' + TITLE + '</title><link>' + URL + '</link>'
               '<pubDate>Sat, 14 Nov 2026 12:00:00 GMT</pubDate><description>&lt;p&gt;A brief publisher-supplied '
               'announcement blurb.&lt;/p&gt;</description></item></channel></rss>')
        source = Substack('')
        with patch.object(source, 'get', return_value=xml) as fetch:
            post = source.recent_posts({'base': 'https://fictional.example/feed.xml', 'rss': True})[0]
            _, text = source.post_text({'rss': True}, post)
        fetch.assert_called_once()
        self.assertEqual(post['body_html'], blurb)
        self.assertEqual(text, 'A brief publisher-supplied announcement blurb.')
        self.assertEqual(post['publishedBylines'], [])


if __name__ == '__main__':
    unittest.main()
