"""Narration body regressions using fictional markup and offline extraction."""
from pathlib import Path
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_extract import extract_text


PARAGRAPHS = (
    'A sweeping spiral galaxy marks the spot where a distant source of light bends around a closer galaxy. '
    'Researchers use the shape of that light to understand how matter is distributed across the universe.',
    'The new observation adds another piece to a growing collection of images from an orbiting telescope. '
    'Comparing these images helps the team decide which parts of the sky deserve a closer look.',
    'Future observations will test whether the same pattern appears in other galaxies at different distances. '
    'The measurements also help scientists improve their instruments before a longer survey begins.',
)


def extract(html, title='', author=''):
    return extract_text(BeautifulSoup(html, 'html.parser'), title, author)


class ArticleExtractionTests(unittest.TestCase):
    def test_unmarked_table_layout_falls_back_to_article_prose(self):
        html = ('<nav>Subscribe and browse</nav><table><tr><td><font face="verdana">'
                '<p>July 2013<br><br>' + '<br><br>'.join(PARAGRAPHS) + '</p>'
                '</font></td></tr></table><footer>Related articles and comments</footer>')
        text = extract(html)
        self.assertTrue(text.startswith(PARAGRAPHS[0]))
        self.assertIn(PARAGRAPHS[-1], text)
        self.assertNotIn('July 2013', text)
        self.assertNotIn('Subscribe', text)
        self.assertNotIn('comments', text)

    def test_quote_entry_preserves_the_quote_and_its_citation(self):
        quote = 'A useful short quotation can still be a complete post with enough readable words to form a meaningful audio preview.'
        html = ('<div class="entry entryPage"><p class="mobile-date-eyebrow">22nd October 2026</p>'
                '<div class="quote"><blockquote><p>' + quote + '</p></blockquote>'
                '<p class="cite">— Alex Writer</p></div>'
                '<div class="entryFooter">Posted October 2026</div></div>'
                '<div>Recent articles and other unrelated stories</div>')
        self.assertEqual(extract(html), quote + ' — Alex Writer')

    def test_newsletter_body_excludes_share_counts_and_repeated_attribution(self):
        html = ('<article><div class="post-header"><h1>A useful article</h1>'
                'Alex Writer October 2026 937 110 101 Share</div>'
                '<div class="available-content"><div class="body markup">'
                '<p>' + PARAGRAPHS[0] + '</p></div></div>'
                '<div class="subscription-widget">Subscribe to keep reading</div></article>')
        self.assertEqual(extract(html, 'A useful article', 'Alex Writer'), PARAGRAPHS[0])

    def test_news_body_excludes_byline_timestamps_and_media_labels(self):
        html = ('<article><h1>A useful article</h1><div data-block="byline">'
                'By Alex Writer Technology reporter</div><ul><li>'
                '<span class="visually-hidden">Published</span>'
                '<time data-testid="timestamp">22 October 2026</time></li></ul>'
                '<figure><img src="https://fictional.example/photo.jpg">'
                '<figcaption>View image in fullscreen. Photo credit.</figcaption></figure>'
                '<button>Share</button>' + ''.join('<p>' + p + '</p>' for p in PARAGRAPHS) +
                '<aside>Comments and related stories</aside></article>')
        text = extract(html, 'A useful article', 'Alex Writer')
        self.assertTrue(text.startswith(PARAGRAPHS[0]))
        for unwanted in ['Alex Writer', 'Published', 'October', 'fullscreen', 'Photo credit', 'Share', 'Comments']:
            self.assertNotIn(unwanted, text)

    def test_dates_and_quotation_figures_in_prose_are_preserved(self):
        html = ('<div class="entry-content"><p>July 2013 began with a discovery on '
                '<time>22 October 2013</time>.</p><figure><blockquote><p>October 2013</p>'
                '<p>A quotation belongs to the article.</p></blockquote></figure></div>')
        self.assertEqual(extract(html), 'July 2013 began with a discovery on 22 October 2013. '
                         'October 2013 A quotation belongs to the article.')

    def test_inline_drop_caps_and_paragraph_boundaries_keep_words_intact(self):
        html = ('<div class="entry-content"><p><span>A</span>s the story begins, '
                'a <em>careful</em> reader listens.</p><p>Another paragraph follows.</p></div>')
        self.assertEqual(extract(html), 'As the story begins, a careful reader listens. Another paragraph follows.')

    def test_hidden_sections_and_page_controls_do_not_become_a_fallback_article(self):
        html = ('<div hidden><p>' + PARAGRAPHS[0] + '</p></div>'
                '<nav>' + ''.join('<a href="/link">An unrelated navigation item</a>' for _ in range(20)) +
                '</nav><form>Sign in to continue</form>')
        self.assertEqual(extract(html), '')

    def test_split_article_sections_are_read_once_in_order_without_related_articles(self):
        html = ('<main><article><div class="post__content"><div class="post__content"><p>' +
                PARAGRAPHS[0] + '</p></div></div><figure><img src="/photo"></figure>'
                '<div class="post__content"><p>' + PARAGRAPHS[1] + '</p></div>'
                '<div class="post__content"><p>' + PARAGRAPHS[2] + '</p></div></article>'
                '<article><div class="post__content">An unrelated recommendation.</div></article></main>')
        self.assertEqual(extract(html), ' '.join(PARAGRAPHS))

    def test_audio_player_metadata_and_paywall_prompts_are_excluded(self):
        html = ('<main><div><button title="Play"></button><div><p>Listen to this <!-- -->essay</p>'
                '<p>27 minute listen</p></div></div><div class="entry-content"><p>' + PARAGRAPHS[0] +
                '</p><div class="post-access-cta"><h2>Sign up for free access</h2>'
                '<p>This post is for paid members only.</p></div></div></main>')
        self.assertEqual(extract(html), PARAGRAPHS[0])

    def test_short_post_omits_repeated_heading_date_and_comment_count(self):
        html = ('<article><h2>A useful article</h2><p>' + PARAGRAPHS[0] + '</p>'
                '<p class="posted">Posted on October 21, 2026 at 7:02 AM • 3 Comments</p></article>')
        self.assertEqual(extract(html, 'A useful article'), PARAGRAPHS[0])

    def test_author_bio_and_tag_footer_do_not_leak_after_explicit_body(self):
        html = ('<section class="post__content"><p>' + PARAGRAPHS[0] + '</p><div><h2>Written by</h2>'
                '<a class="author">Alex Writer</a><p>Senior Technical Advocate</p></div>'
                '<div><h2>Tags:</h2><ul class="post-tags"><li>Testing</li></ul></div></section>')
        self.assertEqual(extract(html), PARAGRAPHS[0])


if __name__ == '__main__':
    unittest.main()
