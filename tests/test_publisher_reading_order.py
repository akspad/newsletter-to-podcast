"""Publisher templates must keep article content separate from page controls."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import preview
from substack import html_to_text, Substack

FIRST = 'We measured how quickly the fictional seedlings grew in different conditions.'
LAST = 'The final observations recorded the effect of light on every individual plant.'


def narrate(url, html):
    with patch.object(Substack, 'get', return_value=html):
        return preview.article_text(url).split('\n', 1)


class PublisherReadingOrderTests(unittest.TestCase):
    def test_quanta_keeps_figure_caption_and_credit_between_body_modules(self):
        html = f"""<title>Seed trials</title><main><div class="post"><div class="has-tombstone">
        <div class="acf-content"><div class="post__content">{FIRST}</div></div>
        <figure><img src="/map"><figcaption><div class="caption"><p>A map of the plots.</p></div>
        <div class="attribution"><p>Map by Lee.</p><p hidden>Hidden credit.</p></div></figcaption></figure>
        <div class="acf-content"><div class="post__content">{LAST}</div></div>
        </div></div></main>"""
        self.assertEqual(narrate('https://www.quantamagazine.org/seed-trials/', html)[1],
                         f'{FIRST} A map of the plots. Map by Lee. {LAST}')

    def test_loc_keeps_the_cover_credit_and_drops_the_verified_subscription_footer(self):
        url = 'https://blogs.loc.gov/loc/2026/11/seed-trials/'
        footer = ('<p><a href="https://public.govdelivery.com/accounts/USLOC/subscriber/new?topic_id=example">'
                  '<em>Subscribe</em></a><em> to the blog— it’s free!</em></p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p>{footer}'
        html = f"""<article><header class="entry-header"><h1>Seed trials</h1>
        <figure class="hero-post"><img src="/map"><figcaption>Map by Lee.</figcaption></figure></header>
        <div class="entry-content">{markup}</div></article>"""
        self.assertEqual(narrate(url, html)[1], f'Map by Lee. {FIRST} {LAST}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Subscribe', html_to_text(markup.replace('public.govdelivery.com', 'fictional.example'), url=url))

    def test_earthsky_keeps_the_video_caption_with_the_rich_text(self):
        html = f"""<title>Seed trials</title><div class="post-body"><div class="post"><div class="post-rich-text">
        <p>{FIRST}</p><figure class="wp-block-embed-youtube"><div class="wp-block-embed__wrapper">
        <iframe src="/player"></iframe></div><figcaption class="wp-element-caption">A labeled recording.</figcaption>
        </figure><p>{LAST}</p></div></div></div>"""
        self.assertEqual(narrate('https://earthsky.org/seed-trials/', html)[1], f'{FIRST} A labeled recording. {LAST}')

    def test_dev_preview_keeps_internal_headings_and_ignores_neighboring_cards(self):
        html = f"""<article id="article-show-container" class="crayons-article"><h1>Seed trials</h1>
        <div class="crayons-article__main"><div id="article-body" class="crayons-article__body">
        <p>{FIRST}</p><h2><a href="#result" name="result"></a>Results after rain</h2><p>{LAST}</p></div>
        <aside><p>Suggested article.</p></aside></div></article>"""
        self.assertEqual(narrate('https://dev.to/writer/seed-trials', html)[1],
                         f'{FIRST} Results after rain {LAST}')

    def test_simon_release_keeps_the_short_summary_after_the_title_is_announced_once(self):
        html = f"""<title>Release: Seed trials</title><div class="entry entryPage">
        <div class="beat"><div class="beat-content"><div class="beat-row1">
        <a class="beat-label release" href="/elsewhere/release/">Release</a>
        <span class="beat-title"><a href="https://example.test/release">Seed trials</a></span>
        <span class="beat-commit">— Report from the garden.</span>
        </div></div></div><p>{FIRST}</p><p>{LAST}</p></div>"""
        intro, body = narrate('https://simonwillison.net/2026/Nov/11/seed-trials/', html)
        self.assertIn('Release: Seed trials.', intro)
        self.assertEqual(body, f'Report from the garden. {FIRST} {LAST}')

    def test_geography_realm_keeps_captions_and_paragraphs_after_removing_page_navigation(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div><strong>Browse by state:</strong><br><a href="#one">First</a> • <a href="#two">Second</a></div>
        <h2 id="one">First</h2><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="/plot.png">
        <figcaption class="wp-element-caption">A map of the trial plots.</figcaption></figure></div>
        <h2 id="two">Second</h2><p>{LAST}</p><h2 class="wp-block-heading">Related</h2>
        <ul class="wp-block-list"><li><a href="/another-story/">Another story</a></li></ul>
        </div></article>"""
        _, body = narrate('https://www.geographyrealm.com/seed-trials/', html)
        self.assertEqual(body, f'First {FIRST} A map of the trial plots. Second {LAST}')

    def test_construction_physics_keeps_substack_caption_and_removes_feed_permalink_button(self):
        url = 'https://www.construction-physics.com/p/seed-trials'
        html = f"""<article><h1>Seed trials</h1><div class="available-content"><div class="body markup">
        <p>{FIRST}</p><div class="captioned-image-container"><figure><img src="/image">
        <figcaption class="image-caption">A plot after rain.</figcaption></figure></div><p>{LAST}</p>
        </div></div></article>"""
        self.assertEqual(narrate(url, html)[1], f'{FIRST} A plot after rain. {LAST}')
        feed = f'<p>{FIRST}</p><p><a href="{url}">Read more</a></p>'
        self.assertEqual(html_to_text(feed, url=url), FIRST)
        self.assertIn('Read more', html_to_text(feed.replace('/seed-trials', '/other'), url=url))

    def test_astronomy_removes_a_terminal_staff_bio_but_keeps_quoted_text(self):
        bio = '<p class="wp-block-paragraph"><em><strong>Lee Writer</strong> is a staff writer at Astronomy, based here.</em></p>'
        html = f"""<meta name="author" content="Lee Writer"><article><h1>Seed trials</h1>
        <div class="entry-content"><p>{FIRST}</p><blockquote>{bio}</blockquote><p>{LAST}</p>
        <hr class="wp-block-separator">{bio}</div></article>"""
        _, body = narrate('https://www.astronomy.com/science/seed-trials/', html)
        self.assertEqual(body.count('staff writer'), 1)
        self.assertTrue(body.endswith(LAST))

    def test_openculture_strips_the_plain_link_related_list_in_both_paths(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        links = ('<p><strong>Related Content:</strong></p><p><a href="/2026/01/a.html">Another story</a></p>'
                 '<p><a href="/2026/02/b.html">A prior story</a></p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p>{links}'
        html = f'<title>Seed trials</title><div class="recent_post"><div class="colorcontrast"><div class="entry">{markup}</div></div></div>'
        self.assertEqual(narrate(url, html)[1], f'{FIRST} {LAST}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Related Content:', html_to_text(markup.rsplit('<p>',1)[0], url=url))

    def test_raspberry_pi_keeps_the_video_caption_without_the_embed(self):
        html = f"""<article><h1>Seed trials</h1><div class="c-post-content__wysiwyg"><p>{FIRST}</p>
        <figure class="wp-block-embed-youtube"><div class="wp-block-embed__wrapper"><iframe src="/player"></iframe></div>
        <figcaption class="wp-element-caption">A demonstration after rain.</figcaption></figure>
        <p>{LAST}</p></div></article>"""
        self.assertEqual(narrate('https://www.raspberrypi.com/news/seed-trials/', html)[1],
                         f'{FIRST} A demonstration after rain. {LAST}')

    def test_jim_nielsen_uses_the_page_title_publication_instead_of_the_feed_format(self):
        html = f"""<title>Seed trials - Fictional Garden Notes</title>
        <link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS: XML Feed">
        <meta name="author" content="Lee Writer">
        <a href="/">Garden Notes</a><article><h1>Seed trials</h1>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, body = narrate('https://blog.jim-nielsen.com/2026/seed-trials/', html)
        self.assertEqual(intro, 'Fictional Garden Notes. Seed trials. By Lee Writer.')
        self.assertEqual(body, f'{FIRST} {LAST}')

    def test_public_domain_review_keeps_collection_captions_and_source_links_in_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="collection-preamble">
        <div class="essay__content entry-content"><p>{FIRST}</p>
        <div class="essay__image"><div class="essay__center-content"><img src="/image">
        <div class="essay__image__caption"><p>A tray after <em>rain</em> — <a href="/source">Source</a>.</p>
        <p>Photograph by Ash.</p></div></div></div>
        <div hidden class="essay__image"><div class="essay__center-content"><img src="/hidden">
        <div class="essay__image__caption"><p>Hidden credit.</p></div></div></div>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://publicdomainreview.org/collection/seed-trials', html)
        self.assertEqual(body, f'{FIRST} A tray after rain — Source. Photograph by Ash. {LAST}')

    def test_smashing_caption_preserves_literal_code_and_omits_same_image_zoom_link(self):
        html = f"""<article><h1>Seed trials</h1><div class="c-garfield-the-cat"><p>{FIRST}</p>
        <figure><a href="/plot.png"><img src="/plot.png"></a><figcaption class="op-vertical-bottom">
        A plot for <code>&lt;seed&gt;</code>. (<a href="/plot.png">Large preview</a>)</figcaption></figure>
        <figure><a href="/samples.png"><img src="/samples.png"></a><figcaption class="op-vertical-bottom">
        Observations after rain. (<a href="/other">Large preview</a>)</figcaption></figure>
        <p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.smashingmagazine.com/2026/11/seed-trials/', html)
        self.assertIn('A plot for <seed>.', body.replace('> .', '>.'))
        self.assertEqual(body.count('Large preview'), 1)
        self.assertIn(LAST, body)

    def test_strong_towns_uses_authors_beside_matching_headline_and_ignores_bio_card(self):
        html = f"""<title>Seed trials</title><main><div class="thought-leadership_wrap">
        <section><div class="mast-col"><div class="heading-component"><h1>Seed trials</h1></div>
        <div class="w-dyn-list"><div class="w-dyn-items">
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Lee Writer</div></div></div>
        <div hidden class="w-dyn-item"><div class="mast-paragraph"><div>Hidden Author</div></div></div>
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Ash Gardener</div></div></div>
        </div></div></div></section>
        <section><div class="mast-article-rich-text w-richtext"><p>{FIRST}</p><h2>Results</h2><p>{LAST}</p>
        <p>More next week.</p></div><div class="mast-card"><p>Lee Writer publishes across the country.</p></div>
        </section></div></main>"""
        intro, body = narrate('https://www.strongtowns.org/journal/seed-trials', html)
        self.assertTrue(intro.endswith('By Lee Writer, Ash Gardener.'), intro)
        self.assertEqual(body, f'{FIRST} Results {LAST} More next week.')

    def test_zed_zoom_caption_survives_and_only_related_widget_prompt_is_removed(self):
        html = f"""<main><article class="entry-content"><h1>Seed trials</h1><p>{FIRST}</p>
        <a href="/chart.png"><button class="cursor-zoom-in"><figure><img src="/chart.png">
        <figcaption>Harvest by season</figcaption></figure></button></a>
        <h3>Related Posts</h3><p>A phrase that belongs in the article.</p><p>{LAST}</p>
        <div class="flex flex-col gap-5"><div><h3>Related Posts</h3><p>Check out similar blogs from the Zed team.</p>
        <div><a href="/blog/recommended">A recommended story</a></div></div></div></article></main>"""
        _, body = narrate('https://zed.dev/blog/seed-trials', html)
        self.assertEqual(body, f'{FIRST} Harvest by season Related Posts A phrase that belongs in the article. {LAST}')

    def test_lithub_keeps_the_source_credit_and_skips_the_sibling_author_card(self):
        html = f"""<meta name="author" content="Lee Writer"><main><h1 class="entry-title">Seed trials</h1>
        <div class="story-content"><div class="story-body entry-content"><p>{FIRST}</p><p>{LAST}</p>
        <p>From <a href="/book">The seed journal</a>, published by arrangement.</p></div>
        <div class="bio-container"><div class="bio"><p>Lee Writer teaches gardening.</p></div></div>
        </div></main>"""
        intro, body = narrate('https://lithub.com/seed-trials/', html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'{FIRST} {LAST} From The seed journal, published by arrangement.')

    def test_wyofile_uses_signed_byline_and_captions_without_player_or_related_cards(self):
        byline = 'Lee Writer, Ash Gardener, Jules Grower and Pat Seed'
        html = f"""<meta name="author" content="Posting Account"><main class="site-main">
        <div class="featured-image-above"><figure class="post-thumbnail"><img src="/lead.png">
        <figcaption>A lead credit.</figcaption></figure><header class="entry-header">
        <h1 class="entry-title">Seed trials</h1><div class="entry-meta"><span class="byline">by {byline}</span></div>
        </header></div><div class="main-content"><article><div class="entry-content">
        <div class="article-summary"><div class="instaread-player-slot"></div>
        <p class="instaread-disclaimer">Play automatically generated audio.</p><p>Reported jointly.</p></div>
        <p>{FIRST}</p><div class="wp-block-image"><figure><img src="/tray.png">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure></div>
        <p>{LAST}</p><div class="wp-block-newspack-blocks-homepage-articles wpnbha"><div>
        <h2 class="article-section-title">RELATED</h2><article class="type-post"><h3>Other story</h3></article>
        </div></div></div></article></div></main>"""
        intro, body = narrate('https://wyofile.com/seed-trials/', html)
        self.assertIn(f'By {byline}.', intro)
        self.assertEqual(body, f'A lead credit. Reported jointly. {FIRST} A tray after rain. {LAST}')

    def test_wyofile_feed_keeps_all_signed_writers_once_and_preserves_unrelated_creators(self):
        url = 'https://wyofile.com/seed-trials/'
        title = 'Seed trials'
        signed = 'Lee Writer, Ash Gardener and Pat Seed'
        authors = [f'by {signed}', 'Ash Gardener, Example Daily', 'Pat Seed']
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>{title}</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p><p>The post <a href="{url}">{title}</a> appeared first on
        <a href="https://wyofile.com">WyoFile </a>.</p>]]></description>
        {''.join(f'<dc:creator>{name}</dc:creator>' for name in authors)}
        </item></channel></rss>"""
        sub = Substack('')
        pub = {'base': 'https://wyofile.com/feed/', 'rss': True}
        with patch.object(sub, 'get', return_value=xml):
            post, = sub.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': signed}])
        cached = {**post, 'publishedBylines': [{'name': name} for name in authors]}
        full, body = sub.post_text(pub, cached)
        self.assertEqual(full['publishedBylines'], [{'name': signed}])
        self.assertEqual(body, FIRST)
        cached['publishedBylines'][-1] = {'name': 'Another Contributor'}
        self.assertEqual(sub.post_text(pub, cached)[0]['publishedBylines'], cached['publishedBylines'])

    def test_buttondown_keeps_the_subject_deck_and_inner_heading_but_skips_web_footer(self):
        html = f"""<article class="email-body"><h1 class="subject">Seed trials</h1>
        <h2 class="description">Field notes</h2><div class="email-body-content">
        <p>{FIRST}</p><hr><h1>Volunteer update</h1><p>{LAST}</p>
        <pre><code>model = &#60;Plant&#62;</code></pre></div>
        <div class="email-body-web-footer"><p>Subscribe to these updates.</p></div></article>"""
        _, body = narrate('https://buttondown.com/fictional/archive/trials/', html)
        self.assertEqual(body, f'Field notes {FIRST} Volunteer update {LAST} model = <Plant>')

    def test_colossal_preview_keeps_the_featured_credit_once_before_the_prose(self):
        url = 'https://www.thisiscolossal.com/2026/11/seed-trials/'
        html = f"""<article><h1>Seed trials</h1><p class="byline"><a rel="author">Lee Writer</a></p>
        <div class="entry-content"><div class="entry-header">
        <figure class="colo-post-featured-image"><img src="/tray.jpg">
        <figcaption class="wp-element-caption">All images courtesy of <strong>Ash</strong></figcaption></figure>
        </div><p>{FIRST}</p><p>{LAST}</p><aside><figure class="colo-post-featured-image">
        <img src="/ad.jpg"><figcaption class="wp-element-caption">Advertisement caption</figcaption>
        </figure></aside></div></article>"""
        intro, body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'All images courtesy of Ash {FIRST} {LAST}')

    def test_paris_review_uses_the_visible_headline_beside_the_article_body(self):
        url = 'https://www.theparisreview.org/blog/2026/11/19/seed-trials/'
        schema = {'@type': 'Article', 'url': url, 'headline': 'A gardener&#8217;s notebook',
                  'author': {'name': 'Lee Writer'}}
        html = f"""<meta property="og:site_name" content="Example Review">
        <meta property="og:title" content="A gardener's notebook by Lee Writer">
        <script type="application/ld+json">{json.dumps(schema)}</script>
        <h1 hidden>A gardener’s notebook</h1><h1>Sign In</h1>
        <section id="content"><header class="titles"><h1>A gardener&rsquo;s notebook</h1></header>
        <div class="article-body-wrap"><main class="blog-body"><div class="entry-content">
        <p>{FIRST}</p><p>{LAST}</p></div></main></div></section>"""
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'Example Review. A gardener’s notebook. By Lee Writer.')
        self.assertEqual(body, f'{FIRST} {LAST}')
        # Visible examples of character-reference syntax are intentional.
        literal = html.replace('gardener&rsquo;s', 'gardener&amp;#8217;s')
        self.assertIn('A gardener&#8217;s notebook.', narrate(url, literal)[0])

    def test_harvard_preview_keeps_the_inline_caption_and_linked_scores_in_order(self):
        html = f"""<article class="node--type-article"><h1>Seed trials</h1>
        <div class="block-field-blocknodearticlebody"><div class="field--name-body field--type-text-with-summary">
        <p>{FIRST}</p><figure class="caption caption-img"><img src="/tray.jpg">
        <figcaption><strong>Seed tray</strong> | Photograph by Ash</figcaption></figure>
        <p>Short result.</p><p>{LAST}</p><p><a href="/results">Earlier results</a></p></div></div>
        <aside><figure class="caption caption-img"><img src="/sidebar.jpg">
        <figcaption>Advertisement caption</figcaption></figure></aside></article>"""
        _, body = narrate('https://www.harvardmagazine.com/seed-trials', html)
        self.assertEqual(body, f'{FIRST} Seed tray | Photograph by Ash Short result. {LAST} Earlier results')

    def test_harvard_rss_uses_the_exported_writer_and_removes_only_template_fields(self):
        url = 'https://www.harvardmagazine.com/seed-trials'
        html = f"""<span class="field--name-title">Seed trials</span>
        <span class="field--name-uid">Uploader</span><span class="field--name-created">Posted Tuesday</span>
        <div class="field--name-body field--type-text-with-summary"><p>{FIRST}</p>
        <figure><figcaption>A tray after rain.</figcaption></figure>
        <p>Hero image is the term we used in the experiment.</p><p>{LAST}</p></div>
        by <a href="/writer/lee">Lee Writer</a>
        <div class="field--name-field-external-description"><div class="field__label">Subhead (Required)</div>
        <div class="field__item">What the seedlings showed.</div></div>
        <div class="field--name-field-full-header-section">Deprecated header setting</div>
        <div class="field--name-field-hero-image">tray.webp</div>
        <div class="field--name-field-slug">Page Slug (Required)</div><p>Corrections added Tuesday.</p>"""
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><guid>trial-1</guid>
        <pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <dc:creator>uploader@example.test</dc:creator>
        <description><![CDATA[{html}]]></description></item></channel></rss>"""
        sub = Substack('')
        pub = {'base': 'https://www.harvardmagazine.com/rss.xml', 'rss': True}
        with patch.object(sub, 'get', return_value=xml):
            post, = sub.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': 'Lee Writer'}])
        cached = {**post, 'publishedBylines': [{'name': 'uploader@example.test'}]}
        full, body = sub.post_text(pub, cached)
        self.assertEqual(full['publishedBylines'], post['publishedBylines'])
        self.assertEqual(cached['publishedBylines'], [{'name': 'uploader@example.test'}])
        self.assertEqual(body.splitlines(), [
            'What the seedlings showed.', FIRST, 'A tray after rain.',
            'Hero image is the term we used in the experiment.', LAST, 'Corrections added Tuesday.',
        ])
        for other_url, other_title in ((url, 'Other title'), ('https://example.test/seed-trials', 'Seed trials')):
            with self.subTest(url=other_url, title=other_title):
                self.assertIn('Page Slug (Required)', html_to_text(html, title=other_title, url=other_url))

    def test_outside_keeps_headings_short_prose_and_photo_credit_but_drops_promotions(self):
        url = 'https://www.outsideonline.com/health/wellness/seed-trials/'
        footer = """<p><b>Want more <i>Outside</i> health stories?</b>
        <a href="https://hub.outsideinc.com/bodywork_newsletter_sign_up-0">Sign up for the Bodywork newsletter</a>.
        <a href="/newsletters/sweat-science-101/?utm_source=article">Sign up for the Sweat Science 101 newsletter</a>.</p>"""
        body = f"""<p>{FIRST}</p><h2>How we counted</h2><h3>1. Start at dawn</h3><p>Short result.</p>
        <blockquote>{footer}</blockquote><p>{LAST}</p>"""
        html = f"""<head><meta name="author" content="Lee Writer"></head>
        <div class="article-template"><div class="js-body-content"><div class="article-header"><h1>Seed trials</h1>
        <div><img src="/tray.jpg"><p class="fp-leadCaption">Photograph by Ash.</p></div></div>
        <div class="content-wrap fp-contentTarget"><div class="article-body"><div class="pub-date">Published today</div></div>
        <div class="ad-placeholder-wrapper">ADVERTISEMENT</div>{body}{footer}<span></span></div>
        <div class="article-bottom"><h2>More coverage</h2></div></div></div>"""
        intro, preview_body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertTrue(preview_body.startswith(f'Photograph by Ash. {FIRST} How we counted 1. Start at dawn Short result.'))
        rss_body = html_to_text(
            body + footer + f'<p>The post <a href="{url}">Seed trials</a> appeared first on '
            '<a href="https://www.outsideonline.com">Outside Online</a>.</p>', title='Seed trials', url=url)
        for text in (preview_body, rss_body):
            self.assertEqual(text.count('Want more Outside health stories?'), 1)
            self.assertIn('1. Start at dawn', text)
            self.assertTrue(text.endswith(LAST))
            for excluded in ('ADVERTISEMENT', 'Published today', 'More coverage', 'appeared first'):
                self.assertNotIn(excluded, text)
        self.assertEqual(html_to_text(body + footer + '<p>Closing note.</p>', url=url).count('Want more'), 2)

    def test_outside_rss_treats_a_login_as_missing_byline_and_keeps_display_names(self):
        pub = {'base': 'https://www.outsideonline.com/feed/', 'rss': True}
        sub = Substack('')
        for creator, host, expected in (
                ('loadingeditor', 'www.outsideonline.com', []),
                ('Lee Writer', 'www.outsideonline.com', [{'name': 'Lee Writer'}]),
                ('loadingeditor', 'example.test', [{'name': 'loadingeditor'}])):
            with self.subTest(creator=creator, host=host):
                xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
                <title>Seed trials</title><link>https://{host}/seed-trials/</link>
                <pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate><dc:creator>{creator}</dc:creator>
                <description><![CDATA[<p>{FIRST}</p>]]></description></item></channel></rss>"""
                with patch.object(sub, 'get', return_value=xml):
                    post, = sub.recent_posts(pub)
                self.assertEqual(post['publishedBylines'], expected)
                cached = {**post, 'publishedBylines': [{'name': creator}]}
                self.assertEqual(sub.post_text(pub, cached)[0]['publishedBylines'], expected)

    def test_guardian_credits_the_visible_author_and_retains_only_inline_caption(self):
        html = f"""<head><meta name="author" content="Staff reporter"></head><article><h1>Seed trials</h1>
        <aside data-gu-name="meta"><address data-component="meta-byline" data-gu-name="byline">
        <div><span>Lee</span><span hidden>Other author</span></div></address></aside>
        <div data-gu-name="body"><div class="article-body-viewer-selector"><p>{FIRST}</p>
        <figure><img src="/photo"><figcaption data-spacefinder-role="inline">Photo by Lee.</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        intro, body = narrate('https://www.theguardian.com/science/seed-trials', html)
        self.assertTrue(intro.endswith('By Lee.'), intro)
        self.assertEqual(body.split(), f'{FIRST} Photo by Lee. {LAST}'.split())

    def test_hakai_keeps_visible_coauthors_and_captions_without_the_hidden_body_label(self):
        html = f"""<article><header><h1>Seed trials</h1><section class="singlebyline">
        <a id="author_link_top" href="/profiles/lee/">Lee</a> and
        <a id="author_link_top" href="/profiles/ash/">Ash</a></section></header>
        <section class="maincontent"><h3 class="invis">Article body copy</h3><p>{FIRST}</p>
        <div class="wp-caption"><img src="/photo"><p class="wp-caption-text">A tray after rain.</p></div>
        <p>{LAST}</p></section></article>"""
        intro, body = narrate('https://hakaimagazine.com/features/seed-trials/', html)
        self.assertTrue(intro.endswith('By Lee, Ash.'), intro)
        self.assertEqual(body.split(), f'{FIRST} A tray after rain. {LAST}'.split())

    def test_plover_fragment_reads_story_title_once_and_keeps_series_links(self):
        archive = 'https://blog.plover.com/2026/09/24/#seed-trials'
        permalink = 'https://blog.plover.com/science/seed-trials.html'
        html = f"""<head><meta property="og:site_name" content="Example weblog : Seed trials"></head>
        <h1 class="pagetitle">Example weblog</h1><div class="mainsection"><span class="dateheader">Thu, 24 Sep 2026</span>
        <p><a class="storytitle" name="seed-trials" href="{permalink}">Seed trials</a><br>
        <p>{FIRST}</p><ol><li><a href="/prior">Earlier experiments</a></li></ol><p>{LAST}</p></p>
        <p>[ <a href="/science/">Other articles in category /science</a> ] <i><a href="{permalink}">permanent link</a></i></p>
        </div>"""
        for url in (archive, permalink):
            with self.subTest(url=url):
                intro, body = narrate(url, html)
                self.assertEqual(intro, 'Example weblog. Seed trials.')
                self.assertEqual(body.split(), f'{FIRST} Earlier experiments {LAST}'.split())

    def test_webdev_uses_the_visible_title_and_author_card(self):
        html = f"""<article><h1 class="devsite-page-title">Seed trials<devsite-actions hidden>
        <span>Save this page</span></devsite-actions></h1><div class="devsite-article-body entry-content">
        <p><div class="wd-authors"><div class="wd-author"><div><span>Lee</span>
        <span class="wd-author__title">Technical Writer</span></div></div>
        <div class="wd-author" hidden><div><span>Other author</span></div></div>
        </div></p><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, _ = narrate('https://web.dev/blog/seed-trials', html)
        self.assertEqual(intro, 'web.dev. Seed trials. By Lee.')

    def test_mental_floss_keeps_lead_and_inline_photo_credits_in_order(self):
        html = f"""<article id="main-article"><h1>Seed trials</h1>
        <figure><div data-lead-image="true"><picture><img src="tray"></picture></div>
        <div><figcaption>Lead photo by Lee.</figcaption></div></figure>
        <div class="odesa-article-main"><div class="entry-content article-content"><p>{FIRST}</p>
        <figure><div><picture><img src="another"></picture></div>
        <div><figcaption>Another photo by Ash.</figcaption></div></figure>
        <figure hidden><div><img src="hidden"></div><div><figcaption>Hidden caption.</figcaption></div></figure>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://www.mentalfloss.com/history/seed-trials', html)
        self.assertEqual(body.split(), f'Lead photo by Lee. {FIRST} Another photo by Ash. {LAST}'.split())

    def test_nieman_keeps_prose_inside_paragraphs_that_start_with_a_related_story_card(self):
        card = ('<div class="embed-relatedstory"><a class="embed-relatedstory-imagelink" href="/other">Photo</a>'
                '<div class="embed-relatedstory-headline">A different story</div></div>')
        html = f"""<article><h1>Seed trials</h1><div class="entry-content roscoe-body"><p>{card}{FIRST}</p>
        <p>We <a href="/notes">checked the same plots</a> again.</p><p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.niemanlab.org/2026/11/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} We checked the same plots again. {LAST}'.split())

    def test_openstreetmap_diary_uses_the_permalink_title_and_profile(self):
        url = 'https://www.openstreetmap.org/user/lee/diary/42'
        html = f"""<head><title>Lee’s Diary | Paths near the greenhouse | OpenStreetMap</title>
        <meta property="og:site_name" content="OpenStreetMap"></head>
        <h1>Lee’s Diary</h1><article class="diary_post"><div class="mb-3">
        <h2><a href="/user/lee/diary/42">Paths near the greenhouse</a></h2>
        <small>Posted by <a href="/user/lee">Lee</a> in <a href="/diary/en">English</a>.</small></div>
        <div class="richtext"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'OpenStreetMap. Paths near the greenhouse. By Lee.')
        self.assertEqual(body.split(), f'{FIRST} {LAST}'.split())
        unrelated, _ = narrate(url, html.replace('/user/lee/diary/42', '/user/lee/diary/41'))
        self.assertNotIn('By Lee.', unrelated)

    def test_sapiens_keeps_image_footers_with_their_caption_and_credit(self):
        figure = """<figure class="c-image-video"><img src="/photo"><footer class="c-image-video__footer">
        <div class="c-media-caption"><p>A field study.</p></div>
        <div class="c-media-credits"><a href="/artist">Photo by Ash.</a></div>
        </footer></figure>"""
        html = f"""<article><h1>Seed trials</h1><div class="entry-content c-article-content">
        <div class="m-article-img-header">{figure}</div><p>{FIRST}</p>
        <div class="m-image-video">{figure.replace('A field study.', 'A second tray.')}</div>
        <div class="m-image-video" hidden>{figure}</div><p>{LAST}</p>
        <footer><p>Email the editors</p></footer></div></article>"""
        _, body = narrate('https://www.sapiens.org/culture/seed-trials/', html)
        self.assertEqual(body.split(), f'A field study. Photo by Ash. {FIRST} A second tray. Photo by Ash. {LAST}'.split())

    def test_longreads_omits_newspack_recommendations_and_keeps_the_editorial_heading(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <h2 class="article-section-title">More picks from the greenhouse</h2><p>{LAST}</p>
        <div class="wp-block-newspack-blocks-homepage-articles wpnbha"><div>
        <h2 class="article-section-title">More picks from the archives</h2>
        <article class="type-post"><h3>Another story</h3></article></div></div></div></article>"""
        url = 'https://longreads.com/2026/11/18/seed-trials/'
        _, body = narrate(url, html)
        self.assertEqual(body.split(), f'{FIRST} More picks from the greenhouse {LAST}'.split())

    def test_robin_sloan_keeps_short_linked_paragraph_and_removes_home_button(self):
        html = f"""<main><article><h1>Seed trials</h1><date-stamp>November 11, 2026</date-stamp>
        <p>{FIRST}</p><p>Examples <a href="/one">here</a>, <a href="/two">here</a>.</p>
        <p>{LAST}</p><a class="button" href="/lab/">To the blog home page</a></article></main>"""
        _, body = narrate('https://www.robinsloan.com/lab/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} Examples here, here. {LAST}'.split())

    def test_popsci_keeps_featured_image_caption_and_omits_marked_awards_promo(self):
        html = f"""<article><h1>Seed trials</h1><div class="article-content-featured-image">
        <figure><img src="tray"><figcaption class="article-featured-image-caption">
        <span>A tray at rest.</span><span class="article-featured-image-caption-credits">Credit: Lee</span></figcaption></figure></div>
        <section class="entry-content"><p>{FIRST}</p><section class="content-widget pw-incontent-excluded">
        <a href="/gear/home-of-the-future-awards-2026/">See it</a></section>
        <p>The <a href="/gear/home-of-the-future-awards-2026/">awards page</a> mentions our trials.</p>
        <p>{LAST}</p></section></article>"""
        _, body = narrate('https://www.popsci.com/science/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'A tray at rest. Credit: Lee {FIRST} The awards page mentions our trials. {LAST}'.split())

    def test_aeon_video_uses_the_description_instead_of_recommendations(self):
        html = f"""<main><h1>Seed trials</h1><div class="article-content"><p>{FIRST}</p><p>{LAST}</p></div>
        <div><p>Watch a different video about riding bicycles.</p></div></main>"""
        _, body = narrate('https://aeon.co/videos/seed-trials', html)
        self.assertEqual(body.split(), f'{FIRST} {LAST}'.split())

    def test_openculture_takes_author_from_its_footer_and_removes_template_endmatter(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        appeal = ('<p><i>If you would like to sup&shy;port the mission of Open Culture, consider '
                  '<a href="/donate">making a donation to our site</a>. Thank you!</i></p>')
        related = ('<p><strong>Relat&shy;ed Content</strong></p>'
                   '<p><a rel="bookmark" href="/2026/10/another.html">Recommended article</a></p>')
        story = f'<p>{FIRST}</p>{appeal}<p>via Ash</p>{related}<p>{LAST}</p>'
        html = f"""<div class="recent_post"><h1>Seed trials</h1>
        <p class="byline"><a href="#respond">Leave a Comment</a></p>
        <div class="colorcontrast"><div class="entry">{story}</div></div>
        <div class="alignleft"><p class="author">by <a rel="author" href="/author/lee">Lee</a>
        <a title="Permalink" href="{url}">Permalink</a></p></div></div>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee.'), intro)
        expected = f'{FIRST} via Ash {LAST}'.split()
        self.assertEqual(body.split(), expected)
        self.assertEqual(html_to_text(story, url=url).split(), expected)
        unmatched, _ = narrate(url, html.replace('title="Permalink"', 'title="Other post"'))
        self.assertNotIn('By ', unmatched)
        for editorial in ('<blockquote>' + appeal + '</blockquote>',
                          related.replace('rel="bookmark"', 'rel="citation"'),
                          related.replace('>Recommended article</a>', '>Recommended article</a> explains the result.')):
            with self.subTest(editorial=editorial):
                self.assertEqual(html_to_text(editorial, url=url), html_to_text(editorial))

    def test_digital_antiquarian_keeps_captions_in_the_article_body(self):
        html = f"""<div class="post hentry"><h2>Seed trials</h2><div class="entry">
        <p>{FIRST}</p><div class="wp-caption"><a href="/tray"><img src="tray"></a>
        <p class="wp-caption-text">A tray of seedlings photographed after rain.</p></div>
        <div class="wp-caption" hidden><img src="unpublished">
        <p class="wp-caption-text">Unpublished frame.</p></div><p>{LAST}</p>
        <h4>Footnotes</h4><ol><li>The study began in March.</li></ol></div>
        <p>Read another article.</p></div><aside><div class="wp-caption"><img src="ad">
        <p class="wp-caption-text">A sponsored image.</p></div></aside>"""
        _, body = narrate('https://www.filfre.net/2026/10/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'{FIRST} A tray of seedlings photographed after rain. {LAST} '
                         'Footnotes The study began in March.'.split())

    def test_inkscape_uses_brand_and_skips_placeholder_and_header_timestamp(self):
        html = f"""<head><title>Seed trials | Inkscape</title><meta name="author" content="None">
        <link rel="alternate" type="application/rss+xml" title="News Feed" href="/news/feed/"></head>
        <div id="logo"><a href="/en/"><img alt="Inkscape"></a></div>
        <div id="content"><div class="wrapper"><h1>Seed trials</h1>
        <p class="postdate">May 2, 2026, 7:10 p.m.</p><p>{FIRST}</p>
        <p>Measurements on May 2, 2026 were repeated at 7:10 p.m.</p><p>{LAST}</p></div></div>"""
        url = 'https://inkscape.org/news/2026/05/02/seed-trials/'
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'Inkscape. Seed trials.')
        self.assertEqual(body.split(), f'{FIRST} Measurements on May 2, 2026 were repeated at 7:10 p.m. {LAST}'.split())
        named, _ = narrate(url, html.replace('content="None"', 'content="Lee"'))
        self.assertTrue(named.endswith('By Lee.'), named)

    def test_kde_reads_article_author_once_and_skips_header_metadata(self):
        html = f"""<article class="post-content"><div class="jumbotron"><div class="content-width">
        <h1 class="page-header">Seed trials</h1><p class="meta">Friday, 6 November 2026 |
        <a href="/authors/ash">Ash Linden</a></p><div class="blog-tags">#research</div>
        </div></div><div class="content-width"><p>{FIRST}</p>
        <p>Read <a href="/authors/lee">Lee’s article</a> for the earlier protocol.</p>
        <p>{LAST}</p></div></article>"""
        intro, body = narrate('https://blogs.kde.org/2026/11/06/seed-trials/', html)
        self.assertTrue(intro.endswith('By Ash Linden.'), intro)
        self.assertEqual(body.split(), f'{FIRST} Read Lee’s article for the earlier protocol. {LAST}'.split())

    def test_gds_byline_keeps_both_names_without_job_titles(self):
        html = f"""<article><header><h1>Seed trials</h1><div class="govuk-body-s">
        <a rel="author" href="/author/ash">Ash Linden, Head of Policy, Partnerships, and Program Delivery</a>
        and <a rel="author" href="/author/lee">Lee Cooper-Quinn, Head of Product, and Program Delivery</a>
        <a rel="category" href="/topics">Research</a></div></header>
        <div class="entry-content"><p>{FIRST}</p><p>{LAST}</p></div></article>"""
        intro, _ = narrate('https://gds.blog.gov.uk/2026/10/19/seed-trials/', html)
        self.assertTrue(intro.endswith('By Ash Linden, Lee Cooper-Quinn.'), intro)

    def test_earthsky_reads_the_rich_text_and_captions_without_controls(self):
        html = f"""<h1>Seed trials</h1><div class="post-content"><div class="post-body">
        <div class="post-share">Share this page</div><div class="post">
        <div class="post-rich-text"><p>{FIRST}</p><figure class="wp-block-image"><img src="sample">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure>
        <p>{LAST}</p><div class="ns-buttons ns-inline-below"><div class="ns-buttons-wrapper">
        <a href="/share" aria-label="Share on Bluesky">Share on Bluesky</a></div></div></div></div></div>
        <div class="post-subscribe">Join our list</div><div class="post-more">Another story</div></div>"""
        _, body = narrate('https://earthsky.org/science/seed-trials/', html)
        self.assertEqual(body.split(), f'{FIRST} A tray after rain. {LAST}'.split())

    def test_r_project_preserves_short_command_before_its_output(self):
        html = f"""<main id="quarto-document-content" class="quarto-banner-title-block">
        <h1>Seed trials</h1><section class="level2"><h2>Results</h2>
        <p>{FIRST}</p><div class="cell"><div class="code-copy-outer-scaffold"><pre class="sourceCode">
        <code><span>(fit &lt;- count(x ~ g))</span></code></pre><button>Copy example</button></div>
        <div class="cell-output"><pre>Group 1: 20 samples</pre></div></div>
        <p>{LAST}</p></section></main>"""
        _, body = narrate('https://blog.r-project.org/posts/seed-trials/', html)
        self.assertEqual(body.split(), f'Results {FIRST} (fit <- count(x ~ g)) Group 1: 20 samples {LAST}'.split())

    def test_wordpress_editorial_photo_captions_stay_in_place(self):
        cases = [
            ('www.smithsonianmag.com', '<figure class="article-image"><img src="tray">'
             '<figcaption class="caption">The tray at sunrise. <span class="credit">Photo by Lee.</span>'
             '</figcaption></figure>', 'The tray at sunrise. Photo by Lee.'),
            ('www.astronomy.com', '<figure class="wp-block-image wp-lightbox-container"><img src="tray">'
             '<figcaption class="wp-element-caption">The robotic arm at rest.</figcaption></figure>',
             'The robotic arm at rest.'),
            ('blogs.loc.gov', '<figure class="wp-caption"><img src="tray">'
             '<figcaption class="wp-caption-text">Seeds in March.</figcaption></figure>', 'Seeds in March.'),
            ('www.futilitycloset.com', '<figure class="wp-caption"><img src="roots">'
             '<figcaption class="wp-caption-text">Image: <a href="/credits/one">Plant archive</a></figcaption></figure>'
             '<figure class="wp-caption"><img src="stems">'
             '<figcaption class="wp-caption-text">Image: <a href="/credits/two">Plant archive</a></figcaption></figure>',
             'Image: Plant archive Image: Plant archive'),
            ('blogs.egu.eu', '<figure class="wp-caption post-thumbnail"><img src="tray">'
             '<figcaption class="featured_caption">Early growth.</figcaption></figure>'
             '<div class="wp-caption"><a href="/photo"><img src="tray2"></a>'
             '<p class="wp-caption-text">Seeds in April.</p></div>', 'Early growth. Seeds in April.'),
        ]
        for host, photo, expected in cases:
            with self.subTest(host=host):
                html = (f'<article><h1>Seeds</h1><div class="entry-content"><p>{FIRST}</p>{photo}'
                        f'<div hidden>{photo}</div><aside>{photo}</aside><p>{LAST}</p></div></article>')
                if host == 'www.smithsonianmag.com':
                    html = html.replace('class="entry-content"', 'class="entry-content articleWrap"')
                _, body = narrate(f'https://{host}/seed-trials/', html)
                self.assertEqual(body.split(), f'{FIRST} {expected} {LAST}'.split())

    def test_experimental_history_preserves_linked_image_captions_in_source_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="available-content"><div class="body markup">
        <p>{FIRST}</p><div class="captioned-image-container"><figure><a href="/photo"><img src="tray"></a>
        <figcaption class="image-caption">Early growth (<a href="/source">source</a>).</figcaption>
        </figure></div><p>{LAST}</p><div hidden class="captioned-image-container"><figure><img src="hidden">
        <figcaption class="image-caption">Hidden draft.</figcaption></figure></div></div></div></article>"""
        _, body = narrate('https://www.experimental-history.com/p/seed-trials', html)
        self.assertEqual(body.split(), f'{FIRST} Early growth (source). {LAST}'.split())

    def test_webkit_author_line_caption_and_linked_code_examples(self):
        html = f"""<article><h1>Seeds</h1><div class="byline"><p class="date">May 18, 2026</p>
        <p class="author">by <span>Ash and Lee</span></p></div><div class="bodycopy"><p>{FIRST}</p>
        <figure><picture><img src="seeds"></picture><figcaption>A tray of seedlings.</figcaption></figure>
        <ul><li><a href="/sample"><code>&lt;seed&gt;</code></a></li>
        <li><a href="/size"><code>size()</code></a></li></ul><p>{LAST}</p></div></article>"""
        intro, body = narrate('https://webkit.org/blog/123/seeds', html)
        self.assertIn('By Ash and Lee.', intro)
        self.assertNotIn('2026', intro)
        self.assertEqual(body.split(), f'{FIRST} A tray of seedlings. <seed> size() {LAST}'.split())

    def test_freebsd_post_navigation_and_feed_footer_keep_editorial_links(self):
        url = 'https://freebsdfoundation.org/blog/seeds/'
        html = f"""<article><h1>Seeds</h1><div class="post-content"><p>{FIRST}</p>
        <p><a rel="prev" href="/prior">Previous</a> trials had a different result.</p><p>{LAST}</p>
        <span class="nav-previous"><a href="/old" rel="prev">Previous</a></span>
        <span class="nav-next"><a href="/new" rel="next">Next</a></span></div></article>"""
        _, body = narrate(url, html)
        self.assertEqual(body.split(), f'{FIRST} Previous trials had a different result. {LAST}'.split())
        credit = (f'<p>The post <a href="{url}">Seeds</a> first appeared on '
                  '<a href="https://freebsdfoundation.org/">The Journal</a>.</p>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>'+credit, title='Seeds', url=url), FIRST)
        for retained in ('<blockquote>'+credit+'</blockquote>', credit+f'<p>{LAST}</p>',
                         credit.replace('/blog/seeds/', '/blog/other/')):
            self.assertIn('first appeared on', html_to_text(retained, title='Seeds', url=url))

    def test_internet_society_uses_matching_article_header_and_keeps_linked_prose(self):
        html = f"""<meta name="author" content="Publishing Account"><main>
        <div class="content-wrapper"><header><h1>Seed trials</h1><div class="author-box"><div class="author-meta">
        <span class="author-name">By <a href="/author/ash/">Ash</a></span>
        <span class="author-name"><a href="/author/lee/">Lee</a><a hidden href="/author/old/">Old name</a></span>
        <a href="/author/ash/feed">RSS</a></div></div></header>
        <article><h2 class="entry-title">Seed trials</h2><div class="body-text"><p>{FIRST}</p>
        <p><a href="/map">See the individual trial results.</a></p><h4>Findings</h4><p>{LAST}</p></div>
        <div class="tags">Other topics</div></article></div></main>"""
        url = 'https://www.internetsociety.org/blog/seed-trials/'
        intro, body = narrate(url, html)
        self.assertIn('By Ash, Lee.', intro)
        self.assertEqual(body.split(), f'{FIRST} See the individual trial results. Findings {LAST}'.split())
        for alternative in (html.replace('<h1>Seed trials', '<h1>Other story'),
                            html.replace('class="content-wrapper"', 'class="other"')):
            self.assertIn('By Publishing Account.', narrate(url, alternative)[0])

    def test_creative_commons_preserves_opening_and_removes_only_the_posting_stamp(self):
        html = f"""<body class="blog-post"><main><header><h1>Seed trials</h1></header><div class="content">
        <aside class="opening"><p>How did the experiment begin? We asked the gardeners.</p></aside>
        <p>{FIRST}</p><aside class="opening"><p>More stories from the archive.</p></aside>
        <p>Our notebook reads <span class="pub-date">Posted 18 May 2026</span> on its cover.</p>
        <p>{LAST}</p><span class="pub-date">Posted 19 May 2026</span></div></main></body>"""
        url = 'https://creativecommons.org/2026/05/19/seed-trials/'
        _, body = narrate(url, html)
        self.assertEqual(body.split(), ('How did the experiment begin? We asked the gardeners. '
                         + FIRST + ' Our notebook reads Posted 18 May 2026 on its cover. ' + LAST).split())

    def test_pypi_post_identity_and_heading_links(self):
        html = f"""<header><a class="md-logo" data-md-component="logo" title="Seed Journal"></a></header>
        <aside class="md-sidebar--post"><nav><a href="/">Back to index</a><div class="md-post__authors">
        <div class="md-profile__description"><strong><a href="/author/ash">Ash<span hidden>Other</span></a></strong>
        Scientist</div></div></nav></aside>
        <main><div class="md-content--post"><article><h1>Seeds</h1><p>{FIRST}</p>
        <h2 id="data">Results<a class="headerlink" href="#data">¶</a></h2>
        <p>The symbol <a class="headerlink" href="#data">¶</a> marks a paragraph.</p>
        <p>{LAST}</p></article></div></main>"""
        intro, body = narrate('https://blog.pypi.org/posts/seeds/', html)
        self.assertEqual(intro, 'Seed Journal. Seeds. By Ash.')
        self.assertEqual(body.split(), f'{FIRST} Results The symbol ¶ marks a paragraph. {LAST}'.split())

    def test_nist_retains_visible_image_caption_and_credit_in_order(self):
        html = f"""<main><h1>Seeds</h1><div class="nist-page__region--content"><div class="text-with-summary">
        <p>{FIRST}</p><figure class="nist-image"><img src="sample"><figcaption class="nist-image__caption">
        <div><p>The seeds after rain.</p></div><div>Credit: Ash</div></figcaption></figure>
        <figure hidden class="nist-image"><img src="other"><figcaption class="nist-image__caption">
        Hidden caption</figcaption></figure><p>{LAST}</p></div></div></main>"""
        _, body = narrate('https://www.nist.gov/news-events/news/seeds', html)
        self.assertEqual(body.split(), f'{FIRST} The seeds after rain. Credit: Ash {LAST}'.split())

    def test_eff_drops_only_the_embedded_player_disclosure(self):
        url = 'https://www.eff.org/deeplinks/seeds'
        widget = ('<div class="mytube"><div class="mytubetrigger"></div><div class="mytubetext">'
                  '<a href="/deeplinks/2008/02/embedded-video-and-your-privacy">Privacy info.</a> '
                  'This embed will serve content from <a href="https://player.example">player.example</a></div></div>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{widget}<p>{LAST}</p>', url=url).split(),
                         f'{FIRST} {LAST}'.split())
        for retained in ('<blockquote>' + widget + '</blockquote>', widget.replace('mytubetrigger', 'other'),
                         widget.replace('This embed', 'We reported why this embed')):
            self.assertIn('Privacy info.', html_to_text(retained, url=url))

    def test_coauthors_and_visible_image_caption(self):
        html = f"""<article><div class="post-content"><header><h1>Seedlings</h1><p>
        <span><a href="/author/ash/"><bdi>Ash</bdi></a></span>
        <span hidden><a href="/author/fake/"><bdi>Hidden</bdi></a></span>
        <span><a href="/author/lee/"><bdi>Lee</bdi></a></span></p></header>
        <div class="article-content"><p>{FIRST}</p>
        <figure class="emdash-image"><img src="one"><figcaption>The shaded tray.</figcaption></figure>
        <figure class="emdash-image" hidden><img src="two"><figcaption>Hidden</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        intro, body = narrate('https://blog.cloudflare.com/seedlings/', html)
        self.assertIn('By Ash, Lee.', intro)
        self.assertEqual(body.split(), f'{FIRST} The shaded tray. {LAST}'.split())

    def test_guardian_excludes_card_and_topic_widgets_but_keeps_prose_links(self):
        html = f"""<article><h1>Notes</h1><div data-gu-name="body">
        <div class="article-body-viewer-selector"><p>{FIRST}</p>
        <figure data-spacefinder-role="richLink"><div data-component="rich-link">
        <a href="/other">Another story</a></div></figure>
        <p><a href="/source">Read more</a> about this result.</p><p>{LAST}</p></div>
        <div>Topic widgets</div></div></article>"""
        _, body = narrate('https://www.theguardian.com/science/notes', html)
        self.assertEqual(body.split(), f'{FIRST} Read more about this result. {LAST}'.split())

    def test_guardian_feed_removes_only_terminal_standalone_permalink(self):
        url = 'https://www.theguardian.com/science/notes'
        link = '<a href="/science/notes">Continue reading...</a>'
        body = f'<p>{FIRST}</p>'
        self.assertEqual(html_to_text(body + link, url=url), FIRST)
        for html in (body + '<blockquote>' + link + '</blockquote>', link + body,
                     body + link.replace('/notes', '/other')):
            self.assertIn('Continue reading...', html_to_text(html, url=url))

    def test_go_atom_uses_matching_wrapper_and_preserves_navigation_words_in_prose(self):
        html = f"""<div id="blog"><div class="Article" data-slug="/blog/notes">
        <h1 class="small"><a href="/blog/">Example blog</a></h1><h1>Notes</h1>
        <p class="author">Ash</p><div class="markdown"><p>{FIRST}</p>
        <p>Next article: a quotation.</p></div></div>
        <div class="Article prevnext"><a href="/blog/all">Blog Index</a></div></div>"""
        url = 'https://go.dev/blog/notes'
        self.assertEqual(html_to_text(html, title='Notes', url=url).split(),
                         f'{FIRST} Next article: a quotation.'.split())
        for other, title in ((url, 'Different'), (url + '-other', 'Notes'), ('https://example.org/blog/notes', 'Notes')):
            self.assertIn('Blog Index', html_to_text(html, title=title, url=other))

    def test_wordpress_footer_credit_and_language_menu(self):
        html = f"""<article><h1>Notes</h1><div class="entry-content"><p>{FIRST} {LAST}</p>
        <p>This post is also available in our library.</p>
        <p class="icl_post_in_other_langs wpml-ls-statics-post_translations">Translation menu
        <span role="navigation"><a class="wpml-ls-link" hreflang="es">Spanish</a></span></p></div>
        <footer class="entry-meta"><span class="by-author"><span class="vcard">
        <a rel="author">Ash<span hidden>Wrong</span></a><a hidden rel="author">Other</a>
        </span></span></footer></article>"""
        intro, body = narrate('https://blog.openstreetmap.org/notes/', html)
        self.assertIn('By Ash.', intro)
        self.assertNotIn('Wrong', intro)
        self.assertEqual(body.split(), f'{FIRST} {LAST} This post is also available in our library.'.split())

    def test_w3c_credit_stays_with_its_label(self):
        html = f"""<article><h1>Notes</h1><section class="meta"><dl>
        <dt>By:</dt><dd><ul><li hidden>Hidden</li><li>Lee</li><li>Ash</li></ul></dd>
        <dt>Published:</dt><dd>Some date</dd></dl></section><p>{FIRST} {LAST}</p></article>"""
        intro, _ = narrate('https://www.w3.org/blog/notes/', html)
        self.assertIn('By Lee, Ash.', intro)
        self.assertNotIn('Hidden', intro)
        self.assertNotIn('By ', narrate('https://www.w3.org/blog/notes/', html.replace('By:', 'Editors:'))[0])

    def test_django_body_keeps_link_only_items_in_source_order(self):
        items = ''.join(f'<li><a href="/idea/{i}/">Idea {i}</a></li>' for i in range(6))
        html = f"""<main><h1>Notes</h1><div class="blog-entry-body"><p>{FIRST}</p>
        <ol>{items}</ol><p>{LAST}</p></div><nav>Other news</nav></main>"""
        _, body = narrate('https://www.djangoproject.com/weblog/2026/notes/', html)
        self.assertEqual(body.split(), (FIRST + ' ' + ' '.join(f'Idea {i}' for i in range(6)) + ' ' + LAST).split())

    def test_raspberry_pi_only_editorial_image_captions_are_retained(self):
        html = f"""<article><h1>Notes</h1><div class="c-post-content__wysiwyg"><p>{FIRST}</p>
        <div class="wp-block-image"><figure><img src="/one"><figcaption class="wp-element-caption">A useful diagram.</figcaption></figure></div>
        <div class="wp-block-image" hidden><figure><img src="/two"><figcaption class="wp-element-caption">Hidden caption.</figcaption></figure></div>
        <p>{LAST}</p></div></article>"""
        _, body = narrate('https://www.raspberrypi.com/news/notes/', html)
        self.assertEqual(body.split(), f'{FIRST} A useful diagram. {LAST}'.split())
