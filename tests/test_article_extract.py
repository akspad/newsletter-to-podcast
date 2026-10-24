"""Narration body regressions using fictional markup and offline extraction."""
from pathlib import Path
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from article_extract import extract_text, extract_structured_text


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
    def test_repeated_headline_with_nested_print_metadata_is_omitted(self):
        heading = ('<h1>A discovery<div class="normal"><div class="whenprint">Alex Writer<br>'
                   'December 1, 2009<br><i>fictional.example/story</i></div><div class="when">'
                   'Posted on Tuesday, December 1, 2009.</div></div></h1>')
        html = '<div class="entry-content">' + heading + '<p>' + PARAGRAPHS[0] + '</p></div>'
        for title in ('A discovery', 'Science Notes: A discovery'):
            with self.subTest(title=title):
                self.assertEqual(extract(html, title, 'Alex Writer'), PARAGRAPHS[0])

    def test_marked_publication_dates_are_omitted_without_removing_prose_dates(self):
        body = ('<p class="mobile-date">17th June 2024</p><p class="date">29 May 2019</p>'
                '<p>May 2024 was an eventful month.</p><blockquote><p class="date">29 May 2019</p></blockquote>'
                '<ul><li><p class="date">17th June 2024</p></li></ul><p>29 May 2019</p>'
                '<p class="date">May 2024 brought a discovery.</p>')
        expected = ('May 2024 was an eventful month. 29 May 2019 17th June 2024 '
                    '29 May 2019 May 2024 brought a discovery.')
        self.assertEqual(extract('<div class="entry-content">' + body + '</div>'), expected)
        self.assertEqual(extract_structured_text(body), expected)

    def test_year_age_badges_are_omitted_but_years_and_subscripts_remain(self):
        body = ('<p>Presented in May <span title="2024 was 2 years ago">2024'
                '<sub class="styled-sub">2ya</sub></span>. H<sub>2</sub>O and x<sub>2ya</sub> remain.</p>'
                '<p><span title="A real annotation">2024<sub class="styled-sub">2ya</sub></span> remains.</p>')
        expected = 'Presented in May 2024. H2O and x2ya remain. 20242ya remains.'
        self.assertEqual(extract('<div class="entry-content">' + body + '</div>'), expected)
        self.assertEqual(extract_structured_text(body), expected)

    def test_opening_translation_byline_and_change_labels_are_not_narrated(self):
        labels = ('<p>By <a href="/">Alex Writer</a></p><p><em>February 6, 2009</em> '
                  '(<a href="#changes">Changes</a>)</p><p><em>Translations: '
                  '<a href="fr/">French</a>, and <a href="de/">German</a></em></p>')
        html = '<article><h1>A discovery</h1><div class="entry-content">' + labels + '<p>' + PARAGRAPHS[0] + '</p></div></article>'
        self.assertEqual(extract(html, 'A discovery', 'Alex Writer'), PARAGRAPHS[0])
        self.assertEqual(extract_structured_text(labels + '<p>' + PARAGRAPHS[0] + '</p>', 'A discovery', 'Alex Writer'), PARAGRAPHS[0])

    def test_metadata_cleanup_preserves_quoted_credits_dates_and_translation_prose(self):
        examples = (
            ('<blockquote><p>By Alex Writer</p><p>Translations: <a href="fr/">French</a></p></blockquote>',
             'By Alex Writer Translations: French'),
            ('<p>July 2013 began with an important discovery.</p>', 'July 2013 began with an important discovery.'),
            ('<p>Translations: <a href="fr/">French</a> examples explain the original argument.</p>',
             'Translations: French examples explain the original argument.'),
            ('<p>A real opening sentence.</p><p>By Alex Writer</p>', 'A real opening sentence. By Alex Writer'),
            ('<p>By Alex Writer</p>', 'By Alex Writer'))
        for html, expected in examples:
            with self.subTest(html=html):
                author = '' if html == '<p>By Alex Writer</p>' else 'Alex Writer'
                self.assertEqual(extract('<div class="entry-content">' + html + '</div>', author=author), expected)

    def test_lamer_news_body_is_selected_by_matching_permalink_and_news_id(self):
        html = ('<div id="content"><section id="newslist"><article data-news-id="42">'
                '<h2><a href="/news/42">A useful article</a></h2></article></section>'
                '<topcomment><article class="comment" data-comment-id="42-">'
                '<span class="info">Alex Writer 50 days ago 123 views</span><pre>' + PARAGRAPHS[0] +
                '</pre></article></topcomment><article class="comment" data-comment-id="42-1">'
                '<pre>Unrelated reader comment.</pre></article></div>')
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(extract_text(soup, 'A useful article', url='https://fictional.example/news/42?utm_source=email'),
                         PARAGRAPHS[0])

    def test_lamer_news_body_cannot_borrow_another_post_id(self):
        html = ('<article data-news-id="42"><h2><a href="/news/42">A useful article</a></h2></article>'
                '<topcomment><article class="comment" data-comment-id="99-"><pre>' +
                PARAGRAPHS[0] + '</pre></article></topcomment>')
        soup = BeautifulSoup(html, 'html.parser')
        self.assertNotIn(PARAGRAPHS[0], extract_text(soup, 'A useful article', url='https://fictional.example/news/42'))

    def test_streamed_post_body_follows_the_selected_article_even_when_hidden(self):
        card = '<article><h2>Another article</h2><div class="PostsPage-postContent"><p>Unrelated recommendation.</p></div></article>'
        for hidden in ('', ' hidden'):
            html = ('<main>' + card + '<article><h1>Requested article</h1><div' + hidden +
                    '><div class="PostsPage-postContent"><p>' + PARAGRAPHS[0] + '</p></div></div></article>' + card + '</main>')
            with self.subTest(hidden=hidden):
                self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])
        html = ('<article itemid="https://fictional.example/other"><h1>A discovery</h1>'
                '<div class="PostsPage-postContent"><p>Unrelated recommendation.</p></div></article>'
                '<article itemid="https://fictional.example/story"><h1>A discovery</h1>'
                '<div class="PostsPage-postContent"><p>' + PARAGRAPHS[0] + '</p></div></article>')
        self.assertEqual(extract_text(BeautifulSoup(html, 'html.parser'), 'A discovery',
                                     url='https://fictional.example/story'), PARAGRAPHS[0])
        html = ('<article class="PostsPage-postContent"><h2>Other story</h2><p>Unrelated recommendation.</p></article>'
                '<article class="PostsPage-postContent"><h1>Requested article</h1><p>' + PARAGRAPHS[0] + '</p></article>')
        self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_streamed_classes_in_navigation_and_recommendations_are_not_article_bodies(self):
        for wrapper in ('aside', 'nav', 'div class="recommendations"', 'div class="Comment-body"'):
            close = wrapper.split()[0]
            html = ('<' + wrapper + '><div class="PostsPage-postContent"><p>Unrelated recommendation.</p></div></' + close + '>'
                    '<main><h1>Requested article</h1><div hidden><div class="PostsPage-postContent"><p>' +
                    PARAGRAPHS[0] + '</p></div></div></main>')
            with self.subTest(wrapper=wrapper):
                self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_footnote_navigation_is_excluded_but_citations_and_exponents_are_preserved(self):
        body = ('<p>Careful observations<sup><a href="#fn1" role="doc-noteref">1</a></sup> help researchers.'
                ' The formula is x<sup>2</sup> and <a href="#methods">methods</a> explain it.</p>'
                '<section role="doc-endnotes"><ol><li id="fn1">A research citation.'
                '<a href="#ref1" role="doc-backlink">Back to text</a></li></ol></section>')
        expected = 'Careful observations help researchers. The formula is x2 and methods explain it. A research citation.'
        self.assertEqual(extract('<div class="entry-content">' + body + '</div>'), expected)
        self.assertEqual(extract_structured_text(body), expected)

    def test_common_markdown_footnote_controls_do_not_become_speech(self):
        for marker, backlink in (
                ('<a class="footnote-ref" href="#note-1">[1]</a>', '<a class="footnote-backref" href="#ref-1">↩</a>'),
                ('<a rel="footnote" href="#note-1">1</a>', '<a rel="footnote-backref" href="#ref-1">Return</a>'),
                ('<sup><a href="#fn:1">1</a></sup>', '<a class="reversefootnote" href="#fnref:1">Back to text</a>')):
            html = '<div class="entry-content"><p>Original' + marker + ' prose.</p><p>A citation.' + backlink + '</p></div>'
            with self.subTest(marker=marker):
                self.assertEqual(extract(html), 'Original prose. A citation.')

    def test_empty_streamed_placeholders_do_not_hide_a_later_lesswrong_body(self):
        for empty in ('', ' \n ', '&#8203;', '&#173;', '<p class="byline">Alex Writer</p>',
                      '<p hidden>Hidden words.</p>', '<script>Only a script.</script>',
                      '<div hidden><div class="PostsPage-postContent">Hidden nested body.</div></div>'):
            html = ('<main><h1>A useful article</h1><div hidden><div class="PostsPage-postContent">' + empty +
                    '</div></div><div hidden><div class="PostsPage-postContent"><p>' + PARAGRAPHS[0] +
                    '</p></div></div></main>')
            with self.subTest(empty=empty):
                self.assertEqual(extract(html, 'A useful article', 'Alex Writer'), PARAGRAPHS[0])

    def test_empty_streamed_bodies_allow_normal_fallback_and_still_reject_empty_pages(self):
        shell = ('<main><h1>A useful article</h1><div hidden><div class="PostsPage-postContent"></div></div>'
                 '<div class="PostsPage-postContent">&#8203;</div>{}</main>')
        self.assertEqual(extract(shell.format('<section><p>' + PARAGRAPHS[0] + '</p></section>'),
                                 'A useful article'), PARAGRAPHS[0])
        self.assertEqual(extract(shell.format(''), 'A useful article'), '')

    def test_streamed_duplicates_and_nested_bodies_are_read_only_once(self):
        body = '<div class="PostsPage-postContent"><p>' + PARAGRAPHS[0] + '</p></div>'
        for html in (body + body, '<div class="PostsPage-postContent">' + body + '</div>'):
            with self.subTest(html=html):
                self.assertEqual(extract(html), PARAGRAPHS[0])

    def test_table_cells_and_definition_entries_keep_word_boundaries(self):
        html = ('<div class="entry-content"><p><span>A</span>n <em>example</em>s paragraph.</p>'
                '<table><tr><th>Model</th><th>Memory</th></tr><tr><td><em>Atlas</em></td><td>16 GB</td></tr>'
                '<tr><td>Beta</td><td>32 GB</td></tr></table>'
                '<dl><dt>Processor</dt><dd>Four <strong>cores</strong></dd>'
                '<dt>Storage</dt><dd>1 TB</dd></dl></div>')
        self.assertEqual(extract(html),
                         'An examples paragraph. Model Memory Atlas 16 GB Beta 32 GB Processor Four cores Storage 1 TB')

    def test_empty_or_cleaned_body_placeholders_do_not_suppress_readable_prose(self):
        for placeholder in ('', ' \n ', '&#8203;', '&#173;', '<span hidden>Hidden text.</span>',
                            '<p class="byline">Alex Writer</p>', '<div style="display:none">Hidden text.</div>'):
            html = ('<article><h1>A useful article</h1><div class="entry-content">' + placeholder +
                    '</div><section><p>' + PARAGRAPHS[0] + '</p></section></article>')
            with self.subTest(placeholder=placeholder):
                self.assertEqual(extract(html, 'A useful article', 'Alex Writer'), PARAGRAPHS[0])

    def test_empty_placeholder_without_article_prose_still_returns_nothing(self):
        self.assertEqual(extract('<main><h1>A useful article</h1><div class="entry-content"></div>'
                                 '<nav>Subscribe and browse</nav></main>', 'A useful article'), '')

    def test_unwrapped_main_story_excludes_recommendation_articles_before_and_after_it(self):
        card = '<article><h2>Another story</h2><div class="entry-content"><p>Unrelated recommendation.</p></div></article>'
        for marked in (True, False):
            body = '<p>' + PARAGRAPHS[0] + '</p>'
            if marked:
                body = '<div class="entry-content">' + body + '</div>'
            for start, end in (('<main>', '</main>'), ('<div role="main">', '</div>')):
                html = start + '<h1>Requested article</h1>' + card + body + card + end
                with self.subTest(marked=marked, wrapper=start):
                    self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_main_deck_does_not_replace_a_longer_semantic_article(self):
        html = ('<main><h1>Requested article</h1><p>A brief introductory deck.</p><article>'
                '<div class="entry-content"><p>' + PARAGRAPHS[0] + '</p></div></article></main>')
        self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_unwrapped_explicit_body_without_paragraph_tags_is_preserved(self):
        html = ('<main><h1>Requested article</h1><article><div class="entry-content">'
                '<p>An unrelated recommendation.</p></div></article><div class="entry-content">' +
                PARAGRAPHS[0] + '</div></main>')
        self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_inline_display_none_and_hidden_ancestors_are_not_narrated(self):
        for style in ('display: none', 'DISPLAY : NONE ! IMPORTANT;', 'color:red; display:/* comment */none',
                      'display: block; display: none', 'display:none!important; display:block'):
            html = ('<article><div class="entry-content"><div style="' + style + '">'
                    '<p>Hidden mobile duplicate.</p></div><p>' + PARAGRAPHS[0] + '</p></div></article>')
            with self.subTest(style=style):
                self.assertEqual(extract(html), PARAGRAPHS[0])

    def test_visible_display_overrides_and_css_discussion_are_preserved(self):
        for style in ('display:none; display:block', 'display:none; display:block!important',
                      'display:none!important; display:block!important', '--example:display:none; color:red'):
            html = '<div class="entry-content"><p style="' + style + '">' + PARAGRAPHS[0] + '</p></div>'
            with self.subTest(style=style):
                self.assertEqual(extract(html), PARAGRAPHS[0])
        self.assertEqual(extract('<div class="entry-content"><p>We discuss display: none in CSS.</p></div>'),
                         'We discuss display: none in CSS.')

    def test_requested_article_wins_over_an_earlier_longer_recommendation(self):
        for marked in (False, True):
            recommendation = '<p>Unrelated recommendation. </p>' * 80
            actual = '<p>' + PARAGRAPHS[0] + '</p>'
            if marked:
                recommendation = '<div class="entry-content">' + recommendation + '</div>'
                actual = '<div class="entry-content">' + actual + '</div>'
            html = ('<main><article><h1>Another story</h1>' + recommendation + '</article>'
                    '<article><h1>Requested article</h1>' + actual + '</article></main>')
            with self.subTest(marked=marked):
                self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

    def test_main_content_wins_over_a_card_outside_main_without_a_title_match(self):
        for semantic_article in (True, False):
            body = '<div class="entry-content"><p>' + PARAGRAPHS[0] + '</p></div>'
            if semantic_article:
                body = '<article>' + body + '</article>'
            html = ('<section><article><div class="entry-content"><p>Unrelated recommendation.</p>'
                    '</div></article></section><main>' + body + '</main>')
            with self.subTest(semantic_article=semantic_article):
                self.assertEqual(extract(html), PARAGRAPHS[0])

    def test_requested_url_distinguishes_cards_with_the_same_title(self):
        html = ('<main><article><h2><a href="/other">A discovery</a></h2><div class="entry-content">'
                '<p>Unrelated recommendation.</p></div></article><article><h2>'
                '<a href="/story">A discovery</a></h2><div class="entry-content"><p>' +
                PARAGRAPHS[0] + '</p></div></article></main>')
        for query in ('', '?utm_source=newsletter'):
            soup = BeautifulSoup(html, 'html.parser')
            with self.subTest(query=query):
                self.assertEqual(extract_text(soup, 'A discovery', url='https://fictional.example/story' + query), PARAGRAPHS[0])

    def test_external_main_headline_does_not_hide_the_actual_article_body(self):
        html = ('<main><h1>Requested article</h1><article><div class="entry-content"><p>' +
                PARAGRAPHS[0] + '</p></div></article></main>')
        self.assertEqual(extract(html, 'Requested article'), PARAGRAPHS[0])

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

    def test_science_story_body_excludes_summary_metadata_and_reference_panels(self):
        html = ('<main><h1>A discovery</h1><dl><dt>Date:</dt><dd>October 2026</dd>'
                '<dt>Source:</dt><dd>Research Institute</dd><dt>Summary:</dt><dd>A teaser.</dd>'
                '<dt>Share:</dt><dd>Facebook</dd></dl><div id="story_text">'
                '<figure><img src="/photo"><figcaption>A media caption.</figcaption></figure>'
                '<p>' + PARAGRAPHS[0] + '</p><div><p>' + PARAGRAPHS[1] + '</p></div></div>'
                '<div id="story_source">Story Source: Research Institute</div>'
                '<div id="journal_references">Cite This Page:</div></main>')
        self.assertEqual(extract(html), ' '.join(PARAGRAPHS[:2]))

    def test_article_icon_and_sharing_translation_and_donation_widgets_are_removed(self):
        html = ('<div class="entry-content"><div class="j-icon">The icon indicates free access.</div>'
                '<p>' + PARAGRAPHS[0] + '</p><div class="sharedaddy">Share this:</div>'
                '<div class="translate-post">Can you translate this article?</div>'
                '<div id="jp-relatedposts">Related</div><div class="harvard-sharing">Print/PDF</div>'
                '<div class="collection-cta"><div class="article-cta-box">Support our work.</div></div>'
                '<div class="collection-dateline">Published October 2026</div></div>')
        self.assertEqual(extract(html), PARAGRAPHS[0])

    def test_inline_ads_teasers_and_caption_paragraphs_are_removed(self):
        html = ('<article><p>' + PARAGRAPHS[0] + '</p><div class="AscendiumAdUnit_wrapper__abc">'
                'Subscribe to skip ads Advertisement</div><p><strong>Read more: </strong>'
                '<a href="/other">Another story</a></p><p>' + PARAGRAPHS[1] + '</p>'
                '<p><em>Enjoying</em> Science Notes? <a href="/newsletter">Subscribe to our free newsletter</a>.</p>'
                '<p><em>Lead Image: Alex Photographer</em></p></article>')
        self.assertEqual(extract(html), ' '.join(PARAGRAPHS[:2]))

    def test_editorial_discussion_of_newsletters_and_quoted_promotions_is_preserved(self):
        html = ('<div class="entry-content"><p>We invite readers to read more about how newsletters work.</p>'
                '<p>Subscribe to our free newsletter was the slogan we chose to analyze.</p>'
                '<blockquote><p><em>Enjoying</em> Science Notes? '
                '<a href="/newsletter">Subscribe to our free newsletter</a>.</p></blockquote></div>')
        text = extract(html)
        self.assertIn('read more about how newsletters work', text)
        self.assertIn('was the slogan we chose to analyze', text)
        self.assertIn('Enjoying Science Notes?', text)


if __name__ == '__main__':
    unittest.main()
