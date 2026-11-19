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
    def test_high_country_news_keeps_a_credit_and_nested_print_note_without_letter_prompt(self):
        html = f'''<article><h1>Seed trials</h1><div class="entry-content">
        <figure class="wp-block-image"><img src="tray"><figcaption><span class="image-credit">Credit: Lee</span></figcaption></figure>
        <p>{FIRST}</p><p class="wp-block-paragraph"><em>We welcome reader letters. Email </em>High Country News
        <a href="mailto:editor@hcn.org">our editors</a> or submit a <a href="/feedback/contact-us">letter</a>.
        See our <a href="/policies/lte">policy</a>.<p class="wp-block-paragraph">{LAST}</p></div></article>'''
        _, body = narrate('https://www.hcn.org/articles/seed-trials/', html)
        self.assertEqual(body, f'Credit: Lee {FIRST} {LAST}')

    def test_aeon_feed_omits_the_duplicate_credit_and_matching_read_on_link(self):
        url = 'https://aeon.co/essays/seed-trials'
        ending = f'<p><em>- by Lee Writer</em></p><p><a href="{url}">Read on Aeon</a></p>'
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{ending}', url=url), FIRST)
        self.assertIn('Read on Aeon', html_to_text(f'<p>{FIRST}</p>{ending}<p>{LAST}</p>', url=url))
        self.assertIn('Read on Aeon', html_to_text(ending.replace('seed-trials', 'other-story'), url=url))

    def test_hyperallergic_preserves_ghost_image_captions_in_article_order(self):
        html = f'''<article class="gh-article"><h1>Seed trials</h1><section class="gh-content is-body">
        <figure class="kg-image-card"><img src="one"><figcaption>Tray one.</figcaption></figure><p>{FIRST}</p>
        <figure class="kg-image-card"><img src="two"><figcaption>Tray <em>two</em>.</figcaption></figure>
        <p>{LAST}</p></section><aside><figure class="kg-image-card"><img src="ad">
        <figcaption>Ad caption.</figcaption></figure></aside></article>'''
        _, body = narrate('https://hyperallergic.com/seed-trials/', html)
        self.assertEqual(body, f'Tray one. {FIRST} Tray two. {LAST}')

    def test_universe_today_preserves_the_lead_caption_and_stops_at_article_text(self):
        html = f'''<main class="container"><article><header class="article-header"><h1>Seed trials</h1></header>
        <figure><img src="tray"><figcaption>A tray. Credit: Lee.</figcaption></figure>
        <div class="article-content"><div class="text"><p>{FIRST}</p><p>{LAST}</p></div></div>
        <a class="plus-video-cta" href="/interview">Watch a trailer</a>
        <div class="author-footer"><p>Bio of Lee.</p></div></article></main>'''
        _, body = narrate('https://www.universetoday.com/articles/seed-trials', html)
        self.assertEqual(body, f'A tray. Credit: Lee. {FIRST} {LAST}')

    def test_freebsd_signed_travel_report_uses_the_named_guest_in_both_paths(self):
        url = 'https://freebsdfoundation.org/blog/event-report/'
        title = 'BSDCan 2026 Travel Report – Lee Writer'
        body = f'<p>{FIRST}</p><p>{LAST}<br>Be well,<br>Lee Writer bsdtv / bsdcan 2026 con chair</p>'
        html = f'<meta name="author" content="Site Editor"><article><h1>{title}</h1><div class="post-content">{body}</div></article>'
        intro, text = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertIn('Be well, Lee Writer', text)
        self.assertIn('By Site Editor.', narrate(url, html.replace('Lee Writer bsdtv', 'Ash Reporter bsdtv'))[0])
        post = {'title': title, 'canonical_url': url, 'body_html': body, 'publishedBylines': [{'name': 'Site Editor'}]}
        full, _ = Substack('').post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer'}])
        feed = (f'<section class="block-tadv-classic-paragraph">{body}</section>'
                f'<p>The post <a href="{url}">{title}</a> first appeared on '
                '<a href="/">FreeBSD Foundation</a>.</p>')
        full, _ = Substack('').post_text({'rss': True}, {**post, 'body_html': feed})
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer'}])
        full, _ = Substack('').post_text({'rss': True}, {**post, 'body_html': f'<blockquote>{body}</blockquote>'})
        self.assertEqual(full['publishedBylines'], [{'name': 'Site Editor'}])

    def test_creative_commons_feed_spaces_exported_author_separators(self):
        source = Substack('')
        post = {'canonical_url': 'https://creativecommons.org/2026/10/02/seed-trials/', 'title': 'Seed trials',
                'body_html': f'<p>{FIRST}</p>', 'publishedBylines': [{'name': 'Lee Writer,Ash Reporter'}]}
        full, body = source.post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Lee Writer, Ash Reporter'}])
        self.assertEqual(body, FIRST)

    def test_propublica_project_preserves_visible_static_deck_and_linked_contributors(self):
        html = f'''<meta property="og:site_name" content="ProPublica"><main><article><header class="opener">
        <div class="opener__text"><h1 class="opener__hed">Seed trials</h1><p class="opener__dek">{FIRST}</p>
        <div class="opener__meta"><p class="opener__byline">by
        <a href="https://www.propublica.org/people/lee">Lee Writer</a> and
        <a href="https://www.propublica.org/people/ash">Ash Reporter</a></p></div></div></header>
        <div class="p-grid-container"><section class="stat-row" aria-label="Totals">
        <div class="stat"><span class="stat__value">5</span> <span class="stat__label">Trials completed</span></div>
        </section><div class="wide-block"><div class="callout-box">
        <h3 class="callout-box__hed">Send news tips</h3><div class="callout-box__text">
        <a href="https://www.propublica.org/tips/">Contact our reporters</a></div></div></div>
        <p>{LAST}</p></div></article></main>'''
        url = 'https://projects.propublica.org/seed-trials/'
        intro, body = narrate(url, html)
        self.assertEqual(intro, 'ProPublica. Seed trials. By Lee Writer, Ash Reporter.')
        self.assertEqual(body, f'{FIRST} Trials completed: 5. {LAST}')

    def test_internet_archive_uses_linked_masthead_and_keeps_inline_image_caption(self):
        html = f'''<meta property="og:site_name" content="Fictional Archive - Latest updates">
        <header><h1 class="site-title"><a href="/" rel="home">Fictional Archive</a></h1></header>
        <article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <figure class="wp-block-image"><img src="/trays"><figcaption class="wp-element-caption">
        Trays on the windowsill.</figcaption></figure><p>{LAST}</p></div></article>'''
        url = 'https://blog.archive.org/2026/11/17/seed-trials/'
        self.assertEqual(narrate(url, html),
                         ['Fictional Archive. Seed trials.', f'{FIRST} Trays on the windowsill. {LAST}'])
        external = html.replace('href="/"', 'href="https://example.com/"')
        self.assertTrue(narrate(url, external)[0].startswith('Fictional Archive - Latest updates.'))

    def test_react_uses_the_blog_brand_and_moves_dated_author_into_intro(self):
        html = f"""<title>Seed trials – React</title><a href="/">logo by Lee</a><main><article>
        <div><h1 class="mdx-heading">Seed trials</h1></div>
        <p>November 19, 2026 by <a href="/about">Lee Writer</a></p><hr>
        <p>{FIRST}</p><p>{LAST}</p></article></main>"""
        self.assertEqual(narrate('https://react.dev/blog/2026/11/19/seed-trials', html),
                         ['React. Seed trials. By Lee Writer.', f'{FIRST} {LAST}'])

    def test_nautilus_preserves_caption_and_credit_in_article_order(self):
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div class="PostContent_content__fictional"><p>{FIRST}</p><figure class="wp-block-image"><img src="/plot">
        <figcaption class="wp-element-caption">Seeds after rain. <em>Photo by Lee.</em></figcaption>
        </figure><p>{LAST}</p></div></div></article>"""
        self.assertEqual(narrate('https://nautil.us/seed-trials-123/', html)[1],
                         f'{FIRST} Seeds after rain. Photo by Lee. {LAST}')

    def test_hcn_keeps_cover_and_inline_captions_without_republishing_widget(self):
        html = f"""<main class="site-main"><div class="featured-image-beside"><img src="/cover">
        <figcaption>Cover by Lee.</figcaption></div><div class="main-content"><article>
        <h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p><div class="wp-block-image">
        <figure><img src="/plot"><figcaption class="wp-element-caption">After rain.</figcaption></figure></div>
        <p>{LAST}</p><section class="below-content widget republication_tracker_tool">Republish This Story
        <p>Reuse details for newsrooms.</p></section></div></article></div></main>"""
        self.assertEqual(narrate('https://www.hcn.org/articles/seed-trials/', html)[1],
                         f'Cover by Lee. {FIRST} After rain. {LAST}')

    def test_damn_interesting_keeps_caption_and_one_rights_notice_without_donation_prompt(self):
        rights = '<p class="print-only print-copyright">Copyright belongs to the author.</p>'
        html = f"""<article><h1>Seed trials</h1>{rights}<div class="entry-content"><p>{FIRST}</p></div>
        <figure class="entry-image"><img src="/plot"><figcaption>After rain.</figcaption></figure>
        <div class="entry-content"><p>{LAST}</p></div>{rights}{rights}<p class="print-only">
        Since you enjoyed our work enough to print it out, <a href="/donate">give a little</a>.</p></article>"""
        # The publisher's full-width body uses the density fallback.
        html = html.replace(' class="entry-content"', '')
        _, body = narrate('https://www.damninteresting.com/seed-trials/', html)
        self.assertIn('After rain.', body)
        self.assertLessEqual(body.count('Copyright belongs to the author.'), 1)
        self.assertTrue(body.startswith(FIRST), body)
        self.assertNotIn('give a little', body)

    def test_outside_keeps_the_marked_inline_photo_caption_without_reading_sidebar_images(self):
        html = f'''<main><h1>Seed trials</h1><div class="article-template"><div class="js-body-content">
        <div class="content-wrap fp-contentTarget"><p>{FIRST}</p>
        <figure class="pom-image-wrap"><img src="tray"><figcaption class="pom-caption">
        <span class="article__caption">A tray in a greenhouse.</span> (Photo: Lee)</figcaption></figure><p>{LAST}</p></div>
        <aside><figure class="pom-image-wrap"><img src="ad"><figcaption class="pom-caption">
        Sponsored image.</figcaption></figure></aside></div></div></main>'''
        _, body = narrate('https://www.outsideonline.com/adventure-travel/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} A tray in a greenhouse. (Photo: Lee) {LAST}')

    def test_kottke_untitled_post_does_not_read_clipped_opening_as_a_title(self):
        url = 'https://kottke.org/26/11/0054321-seed-trials'
        quote = f'“{FIRST} {LAST}”'
        schema = {'@type': 'BlogPosting', 'headline': quote[:64], 'url': url,
                  'author': {'name': 'Lee Writer'}, 'publisher': {'name': 'Garden Notes'}}
        html = f"""<title>{quote[:34]}...</title><link rel="canonical" href="{url}">
        <script type="application/ld+json">{json.dumps(schema)}</script>
        <div class="post"><div class="post-meta"><a href="{url}">Published today</a></div>
        <p>{quote}</p></div>"""
        self.assertEqual(narrate(url, html), ['Garden Notes. By Lee Writer.', quote])
        titled = html.replace(f'<p>{quote}', f'<h2 class="post-title">Seed trials</h2><p>{quote}')
        self.assertIn('Seed trials.', narrate(url, titled)[0])

    def test_mit_news_feed_byline_omits_branding_and_keeps_specific_affiliations(self):
        url = 'https://news.mit.edu/2026/seed-trials-1119'
        names = ['Lee Writer | MIT News', 'Ash Gardener | School of Science']
        expected = [{'name': 'Lee Writer'}, {'name': names[1]}]
        rss = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p>]]></description>
        {''.join(f'<dc:creator>{name}</dc:creator>' for name in names)}
        </item></channel></rss>"""
        atom = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Seed trials</title>
        <link href="{url}"/><updated>2026-11-18T13:57:06Z</updated><content>{FIRST}</content>
        {''.join(f'<author><name>{name}</name></author>' for name in names)}
        </entry></feed>"""
        source = Substack('')
        pub = {'base': 'https://news.mit.edu/rss/feed', 'rss': True}
        for feed in (rss, atom):
            with patch.object(source, 'get', return_value=feed):
                post, = source.recent_posts(pub)
            self.assertEqual(post['publishedBylines'], expected)
            legacy = {**post, 'publishedBylines': [{'name': name} for name in names]}
            full, body = source.post_text(pub, legacy)
            self.assertEqual(full['publishedBylines'], expected)
            self.assertEqual(body, FIRST)
            self.assertEqual(legacy['publishedBylines'][0]['name'], names[0])

    def test_pluralistic_keeps_the_article_license_but_skips_the_verified_site_footer(self):
        url = 'https://pluralistic.net/2026/11/19/seed-trials/'
        license_note = 'This article uses a Creative Commons Attribution 4.0 license.'
        footer = ('<hr><h1>How to get Pluralistic:</h1>'
                  '<p><a href="https://pluralistic.net/plura-list">Newsletter</a></p>'
                  '<p>READ CAREFULLY: By reading this, you agree to the fictional site terms.</p>'
                  '<p>ISSN: 1234-567X</p>')
        markup = f'<p>{FIRST}</p><p>{LAST}</p><p>{license_note}</p>{footer}'
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">{markup}</div>
        <footer class="entry-footer"><span class="byline"><span class="author vcard">
        <a href="/author/lee/">Lee Writer</a></span></span></footer></article>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee Writer.'), intro)
        self.assertEqual(body, f'{FIRST} {LAST} {license_note}')
        self.assertEqual(html_to_text(markup, url=url), f'{FIRST}\n{LAST}\n{license_note}')
        self.assertIn('Newsletter', html_to_text(markup + '<p>A substantive closing note.</p>', url=url))

    def test_sciencedaily_keeps_the_illustration_caption_and_credit(self):
        html = f"""<main><h1>Seed trials</h1><div id="story_text"><div id="featured">
        <figure class="mainimg"><img src="/plots">
        <figcaption>Testing the plots. Credit: Lee Writer.</figcaption></figure></div>
        <p>{FIRST}</p><p>{LAST}</p></div></main>"""
        self.assertEqual(narrate('https://www.sciencedaily.com/releases/2026/11/seed-trials.htm', html)[1],
                         f'Testing the plots. Credit: Lee Writer. {FIRST} {LAST}')

    def test_cc_keeps_the_image_attribution_separately_from_page_license_boilerplate(self):
        html = f"""<body class="blog-post"><title>Seed trials</title><main><header><h1>Seed trials</h1>
        <figure><img src="/cover"><figcaption><p>Trial photos by Lee — <a href="/licenses/by/4.0/">CC BY 4.0</a>.</p>
        </figcaption></figure></header><div class="content"><p>{FIRST}</p><p>{LAST}</p>
        <div class="cc-attribution"><p>The text in this work is licensed under a Creative Commons
        <a href="https://creativecommons.org/licenses/by/4.0/">license</a>.</p></div>
        </div><article class="posts related"><p>Another story.</p></article></main></body>"""
        self.assertEqual(narrate('https://creativecommons.org/2026/11/seed-trials/', html)[1],
                         f'Trial photos by Lee — CC BY 4.0. {FIRST} {LAST}')

    def test_bbc_keeps_editorial_caption_without_the_screen_reader_prefix(self):
        html = f"""<main><article><h1>Seed trials</h1><div class="entry-content"><p>{FIRST}</p>
        <div data-testid="image"><figure><img src="/cover"><figcaption>
        <span class="visually-hidden">Image caption, </span><div><p>Putting the plots in order.</p></div>
        </figcaption></figure></div><p>{LAST}</p></div></article></main>"""
        self.assertEqual(narrate('https://www.bbc.com/news/articles/seed-trials', html)[1],
                         f'{FIRST} Putting the plots in order. {LAST}')

    def test_filfre_rejects_a_link_only_post_without_filling_it_with_sidebar_text(self):
        url = 'https://www.filfre.net/2026/11/seed-trials/'
        html = f"""<title>Seed trials</title><link rel="canonical" href="{url}">
        <div class="post hentry"><h1 class="post-title">Seed trials</h1><div class="entry">
        <p><a href="/external">This week's results</a></p></div></div>
        <div class="sidebar"><p>{FIRST} {LAST}</p></div>"""
        with self.assertRaisesRegex(ValueError, 'too little readable text'):
            narrate(url, html)

    def test_nasa_removes_rss_metadata_modules_but_preserves_a_details_section_with_prose(self):
        url = 'https://www.nasa.gov/testing/'
        opening = ('<div class="wp-block-nasa-blocks-article-intro"><div class="article-header">'
                   '<p class="label">2 min read</p><h1>Other story</h1></div></div>')
        end = ('<div class="wp-block-nasa-blocks-credits-and-details"><h2>Share</h2>'
               '<h2>Details</h2><div>Last Updated Tuesday</div><h2>Related Terms</h2></div>')
        self.assertEqual(html_to_text(opening + f'<p>{FIRST}</p>' + end, url=url), FIRST)
        self.assertIn(LAST, html_to_text(end.replace('</div>', f'<p>{LAST}</p></div>', 1), url=url))
        html = f"""<article><h1>Seed trials</h1><div class="entry-content">
        <div class="hds-media wp-block-image"><div class="hds-media-wrapper">
        <img src="/image"><figcaption>Observations after rain.</figcaption></div></div>
        <p>{FIRST}</p><p>{LAST}</p></div></article>"""
        self.assertEqual(narrate(url, html)[1], f'Observations after rain. {FIRST} {LAST}')

    def test_experimental_history_preserves_prose_beside_the_editor_subscribe_widget(self):
        url = 'https://www.experimental-history.com/p/seed-trials'
        widget = ('<div class="subscription-widget-wrap-editor"><div class="subscription-widget show-subscribe">'
                  '<p class="cta-caption">Follow the next trial</p></div></div>')
        self.assertEqual(html_to_text(f'<p>{FIRST}</p>{widget}<p>{LAST}</p>', url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Follow the next trial', html_to_text('<blockquote>' + widget + '</blockquote>', url=url))

    def test_guardian_keeps_one_lead_caption_and_does_not_announce_the_staff_role(self):
        url = 'https://www.theguardian.com/society/seed-trials'
        caption = '<figure><img src="/tray"><figcaption data-spacefinder-role="inline">A tray after rain.</figcaption></figure>'
        html = f"""<article><h1>Seed trials</h1><aside><address data-component="meta-byline" data-gu-name="byline">
        <a rel="author" href="/profile/lee">Lee Writer</a><span> Health policy editor</span></address></aside>
        <div data-gu-name="media">{caption}{caption}</div>
        <div data-gu-name="body"><div class="article-body-viewer-selector"><p>{FIRST}</p><p>{LAST}</p></div></div>
        </article>"""
        intro, body = narrate(url, html)
        self.assertTrue(intro.endswith('By Lee Writer.'), intro)
        self.assertEqual(body, f'A tray after rain. {FIRST} {LAST}')
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
        <title>Seed trials</title><link>{url}</link><pubDate>Wed, 18 Nov 2026 13:57:06 GMT</pubDate>
        <description><![CDATA[<p>{FIRST}</p>]]></description>
        <dc:creator>Lee Writer Health policy editor</dc:creator></item></channel></rss>"""
        source = Substack('')
        pub = {'base': 'https://www.theguardian.com/society/rss', 'rss': True}
        with patch.object(source, 'get', return_value=xml):
            post, = source.recent_posts(pub)
        self.assertEqual(post['publishedBylines'], [{'name': 'Lee Writer'}])

    def test_propublica_keeps_editorial_captions_without_the_duplicate_cover_copy(self):
        credit = '<span class="p-attribution__caption">Trial plots.</span> <span class="p-attribution__credit">Image by Lee.</span>'
        html = f"""<article><h1>Seed trials</h1><div class="entry-header"><div class="p-opener">
        <div class="p-opener__art-wrapper"><figure><img src="/cover">
        <figcaption class="p-attribution screen-reader-text">{credit}</figcaption></figure></div>
        <figcaption aria-hidden="true" class="p-attribution">{credit}</figcaption></div></div>
        <div class="article-body"><div class="entry-content"><p>{FIRST}</p>
        <figure class="wp-block-image"><img src="/plots"><figcaption class="attribution">After rain.</figcaption></figure>
        <p>{LAST}</p></div></div></article>"""
        _, body = narrate('https://www.propublica.org/article/seed-trials', html)
        self.assertEqual(body, f'Trial plots. Image by Lee. {FIRST} After rain. {LAST}')

    def test_popular_science_featured_template_keeps_cover_and_inline_captions(self):
        html = f"""<article class="featured-template-post"><h1>Seed trials</h1>
        <figure class="featured-image"><img src="/lead"><figcaption class="article-featured-image-caption">
        <span class="article-featured-image-caption-credits">Image by Lee.</span></figcaption></figure>
        <section class="featured-template-content"><div class="entry-content"><div class="content-wrapper">
        <p>{FIRST}</p><figure class="wp-block-image"><img src="/tray">
        <figcaption class="wp-element-caption">A tray after rain.</figcaption></figure><p>{LAST}</p>
        </div></div></section></article>"""
        self.assertEqual(narrate('https://www.popsci.com/science/seed-trials/', html)[1],
                         f'Image by Lee. {FIRST} A tray after rain. {LAST}')

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
        see_also = html.replace('>Related</h2>', ' id="h-see-also">See Also</h2>')
        url = 'https://www.geographyrealm.com/seed-trials/'
        self.assertEqual(narrate(url, see_also)[1], body)
        self.assertIn('See Also', narrate(url, see_also.replace('id="h-see-also"', 'id="editorial"'))[1])

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

    def test_substack_footnotes_keep_prose_without_paired_reference_numbers(self):
        ref = ('<a class="footnote-anchor" data-component-name="FootnoteAnchorToDOM" '
               'id="footnote-anchor-1" href="#footnote-1">1</a>')
        note = ('<div class="footnote" data-component-name="FootnoteToDOM"><a class="footnote-number" '
                'contenteditable="false" id="footnote-1" href="#footnote-anchor-1">1</a>'
                f'<div class="footnote-content"><p>{LAST}</p></div></div>')
        body = f'<p>{FIRST}{ref}</p>{note}'
        url = 'https://www.construction-physics.com/p/seed-trials'
        page = f'<article><h1>Seed trials</h1><div class="body markup">{body}</div></article>'
        self.assertEqual(narrate(url, page)[1], f'{FIRST} {LAST}')
        self.assertEqual(html_to_text(body), f'{FIRST}\n{LAST}')
        for control in (body.replace('href="#footnote-1"', 'href="#different-note"'), f'<blockquote>{body}</blockquote>'):
            self.assertIn(FIRST + '1', html_to_text(control))

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

    def test_open_culture_announces_the_signed_writer_and_prunes_both_own_host_variants(self):
        url = 'https://www.openculture.com/2026/11/seed-trials.html'
        bio = '<p><em>Ted Mills is a free&shy;lance writer on the arts.</em></p>'
        related = ('<p><strong>Related Content:</strong></p><p><a rel="bookmark" '
                   'href="https://openculture.com/2026/01/old.html">An unrelated story</a></p>')
        story = f'<p>{FIRST}</p><p>{LAST}</p>{related}{bio}'
        html = (f'<title>Seed trials</title><meta name="author" content="OC"><div class="recent_post">'
                f'<div class="colorcontrast"><div class="entry">{story}</div></div></div>')
        intro, body = narrate(url, html)
        self.assertIn('By Ted Mills.', intro)
        self.assertNotIn('An unrelated story', body)
        source = Substack('')
        post = {'title': 'Seed trials', 'canonical_url': url, 'body_html': story,
                'publishedBylines': [{'name': 'OC'}]}
        full, text = source.post_text({'rss': True}, post)
        self.assertEqual(full['publishedBylines'], [{'name': 'Ted Mills'}])
        self.assertNotIn('An unrelated story', text)
        for markup in (f'<blockquote>{bio}</blockquote>', bio + f'<p>{LAST}</p>'):
            control, _ = source.post_text({'rss': True}, {**post, 'body_html': markup})
            self.assertEqual(control['publishedBylines'], [{'name': 'OC'}])

    def test_astronomy_photo_feed_removes_only_its_own_read_more_control(self):
        title = 'Seed trials'
        url = 'https://www.astronomy.com/picture-of-the-day/photo/seed-trials/'
        link = (f'<a class="more-link" href="{url}">Continue reading '
                '<span class="screen-reader-text">"Seed trials"</span></a>')
        self.assertEqual(html_to_text(f'<p>{FIRST}{link}</p>', title=title, url=url), FIRST)
        for keep in (link.replace('seed-trials/', 'another/'), link + ' ' + LAST, link.replace('>"Seed trials"<', '>"Another story"<')):
            self.assertIn('Continue reading', html_to_text(f'<p>{FIRST}{keep}</p>', title=title, url=url))

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

    def test_public_domain_review_reads_the_collection_writer_and_image_grid_captions(self):
        html = f'''<div class="collection-view" role="main"><h1>Seed trials</h1>
        <div class="collection-byline"><div class="attribution">Text by <a href="/contributor/lee/">Lee Writer</a></div></div>
        <div class="collection-preamble"><div class="essay__content"><p>{FIRST}</p>
        <div class="essay__multi-image"><div class="essay__image__wrapper"><img src="tray">
        <span class="undownloaded-image">Scroll through the whole page to download all images before printing.</span></div>
        <div class="essay__multi-image__caption"><p>Three trays after the storm.</p></div></div>
        <p>For details, see <a href="/source">the notebook</a>.</p><p>{LAST}</p></div></div>
        <p>Browse another collection.</p></div>'''
        url = 'https://publicdomainreview.org/collection/seed-trials'
        intro, body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'{FIRST} Three trays after the storm. For details, see the notebook. {LAST}')
        self.assertNotIn('By Lee Writer.', narrate(url, html.replace('/contributor/lee/', '/collections/lee/'))[0])

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
        html = f"""<title>Seed trials | Strong Towns</title><main><div class="thought-leadership_wrap">
        <section><div class="mast-col"><div class="heading-component"><h1>Seed trials</h1></div>
        <div class="w-dyn-list"><div class="w-dyn-items">
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Lee Writer</div></div></div>
        <div hidden class="w-dyn-item"><div class="mast-paragraph"><div>Hidden Author</div></div></div>
        <div class="w-dyn-item"><div class="mast-paragraph"><div>Ash Gardener</div></div></div>
        </div></div></div></section>
        <section><div class="mast-article-rich-text w-richtext"><p>{FIRST}</p><h2>Results</h2>
        <figure class="w-richtext-figure-type-image"><img src="tray"><figcaption>Two trays outside.</figcaption></figure>
        <figure hidden class="w-richtext-figure-type-image"><img src="archived"><figcaption>Hidden caption.</figcaption></figure>
        <p>{LAST}</p>
        <p>More next week.</p></div><div class="mast-card"><p>Lee Writer publishes across the country.</p></div>
        </section></div></main>"""
        intro, body = narrate('https://www.strongtowns.org/journal/seed-trials', html)
        self.assertEqual(intro, 'Strong Towns. Seed trials. By Lee Writer, Ash Gardener.')
        self.assertEqual(body, f'{FIRST} Results Two trays outside. {LAST} More next week.')

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

    def test_lithub_keeps_prose_wrapped_in_the_layouts_ad_container(self):
        html = f'''<h1 class="entry-title">Seed trials</h1><div class="story-content"><div class="story-body">
        <p>{FIRST}</p><div class="pw-ad-scroll-container pw-clearfix"><div class="pw-ad-container-logo">
        <script>ad()</script><p>The roots stayed close to the surface of the tray.</p></div></div>
        <p>{LAST}</p></div><aside><p>Browse more reviews.</p></aside></div>'''
        self.assertEqual(narrate('https://lithub.com/seed-trials/', html)[1],
                         f'{FIRST} The roots stayed close to the surface of the tray. {LAST}')

    def test_quillette_uses_the_visible_writer_and_keeps_only_the_public_teaser(self):
        bookmark = '''<figure class="kg-card kg-bookmark-card"><a class="kg-bookmark-container" href="/extra/">
        <div class="kg-bookmark-content"><div class="kg-bookmark-title">Another article</div></div></a></figure>'''
        body = f'<p>{FIRST}</p>{bookmark}<p>{LAST}</p>'
        html = f'''<article class="post"><header><h1>Seed trials</h1>
        <a href="/author/lee/"><figure><figcaption class="sr-only">headshot</figcaption></figure></a>
        <div><a href="/author/lee/">Lee Writer</a><a href="/author/other/">Other author</a></div>
        <figure class="gh-feature-image"><img src="/tray"><figcaption>Seed tray.</figcaption></figure></header>
        <section><div class="gh-content-fade">{body}</div><div><p>The rest is for paying subscribers.</p></div>
        </section></article>'''
        url = 'https://quillette.com/2026/11/17/seed-trials/'
        intro, text = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(text, f'Seed tray. {FIRST} {LAST}')
        self.assertEqual(html_to_text(body, url=url), f'{FIRST}\n{LAST}')
        self.assertIn('Another article', html_to_text(f'<blockquote>{bookmark}</blockquote>', url=url))

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
        </div><p>{FIRST}</p><figure class="wp-block-image"><img src="/tray-two.jpg">
        <figcaption class="wp-element-caption">The second trial. Photo by Lee.</figcaption></figure>
        <p>{LAST}</p><aside><figure class="colo-post-featured-image">
        <img src="/ad.jpg"><figcaption class="wp-element-caption">Advertisement caption</figcaption>
        </figure></aside></div></article>"""
        intro, body = narrate(url, html)
        self.assertIn('By Lee Writer.', intro)
        self.assertEqual(body, f'All images courtesy of Ash {FIRST} The second trial. Photo by Lee. {LAST}')

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

    def test_paris_review_keeps_editorial_div_between_prose_and_quotation(self):
        html = f'''<h1>Seed trials</h1><section id="content" role="main"><div class="article-body-wrap">
        <main class="article-body blog-body"><p>{FIRST}</p>
        <div class="wp-caption"><img src="tray"><p class="wp-caption-text">Tray photograph by Lee.</p></div>
        <div id="message-list_test"><div aria-roledescription="message"><div><div draggable="false">
        <div>One source is <a href="/diary"><em>A gardener’s diary</em></a>.</div>
        </div></div></div></div><blockquote>The plants bent toward the light.</blockquote>
        <p>{LAST}</p></main><aside><p>Unrelated subscription</p></aside></div></section>'''
        _, body = narrate('https://www.theparisreview.org/blog/2026/11/19/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} Tray photograph by Lee. One source is A gardener’s diary. '
                         f'The plants bent toward the light. {LAST}')

    def test_harvard_preview_keeps_the_inline_caption_and_linked_scores_in_order(self):
        html = f"""<article class="node--type-article"><h1>Seed trials</h1>
        <div class="article_header_section"><div class="field--name-field-hero-image">
        <figure class="media--view-mode-article-hero"><img src="/hero.jpg"><figcaption>
        <p>The first three seedlings. Photographs by Lee.</p></figcaption></figure></div></div>
        <div class="block-field-blocknodearticlebody"><div class="field--name-body field--type-text-with-summary">
        <p>{FIRST}</p><figure class="caption caption-img"><img src="/tray.jpg">
        <figcaption><strong>Seed tray</strong> | Photograph by Ash</figcaption></figure>
        <p>Short result.</p><p>{LAST}</p><p><a href="/results">Earlier results</a></p></div></div>
        <aside><figure class="caption caption-img"><img src="/sidebar.jpg">
        <figcaption>Advertisement caption</figcaption></figure></aside></article>"""
        _, body = narrate('https://www.harvardmagazine.com/seed-trials', html)
        self.assertEqual(body, f'The first three seedlings. Photographs by Lee. {FIRST} '
                         f'Seed tray | Photograph by Ash Short result. {LAST} Earlier results')

    def test_harvard_export_drops_an_account_and_topics_without_guessing_attribution(self):
        url = 'https://www.harvardmagazine.com/seed-trials'
        account = 'fictional-user@harvard.edu'
        body = f'''<span class="field--name-title">Seed trials</span>
        <div class="field--name-body field--type-text-with-summary"><p>{FIRST}</p><p>{LAST}</p></div>
        by <a href="/writer/lee-writer">{account}</a>
        <div class="field--name-field-sub-topics"><div class="field__label">Related topics</div>Test tag</div>
        <div class="field--name-field-featured-topic"><div class="field__label">Primary Topic</div>News</div>'''
        entry = {'title': 'Seed trials', 'canonical_url': url, 'body_html': body,
                 'publishedBylines': [{'name': account}]}
        post, text = Substack('').post_text({'rss': True}, entry)
        self.assertEqual(post['publishedBylines'], [])
        self.assertEqual(text, f'{FIRST}\n{LAST}')
        self.assertIn(account, html_to_text(body, title='Different title', url=url))

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

    def test_nieman_preserves_chart_labels_and_footnotes_without_reading_controls(self):
        html = f'''<h1>Seed trials</h1><div class="roscoe-article-body"><div class="roscoe-body">
        <p>{FIRST}</p><div class="ljc"><div class="ljc-title">Tray measurements</div>
        <p>Measured at noon.</p><script>const data = []</script></div>
        <p>Seeds sprouted<sup><a class="footnote-identifier-link" id="reference" href="#note">1</a></sup>.</p>
        <p>{LAST}<ol class="footnotes"><li class="footnote" id="note">The trays were <a href="/trays">shallow</a>.
        [<a class="footnote-back-link" href="#reference">↩</a>]</li></ol></p>
        <blockquote>Use [<a class="footnote-back-link" href="#reference">↩</a>] to return.</blockquote>
        </div></div><p>Newsletter signup</p>'''
        _, body = narrate('https://www.niemanlab.org/2026/11/seed-trials/', html)
        self.assertEqual(body, f'{FIRST} Tray measurements Measured at noon. Seeds sprouted. {LAST} '
                         'The trays were shallow. Use [↩] to return.')

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

    def test_sapiens_keeps_each_grid_caption_and_the_standfirst_but_not_archive_promo(self):
        photos = ''.join(f'<div class="m-two-images__media"><figure class="c-image-video"><img src="{label}">'
                         '<footer class="c-image-video__footer"><div class="c-media-caption">'
                         f'<p>A {label} tray.</p></div><div class="c-media-credits">Photo by Lee.</div>'
                         '</footer></figure></div>' for label in ('first', 'second'))
        html = f'''<title>Seed trials</title><div class="c-article-content" data-article-content><div class="p-header-article">
        <h1 class="p-header-article__title">Seed trials</h1><div class="p-header-article__standfirst">Opening context.</div>
        </div><div class="m-article-img-header"><figure class="c-image-video"><img src="cover">
        <footer class="c-image-video__footer"><div class="c-media-caption">The cover tray.</div></footer></figure></div>
        <div class="c-modules"><div class="m-wysiwyg"><div class="wysiwyg">
        <div class="paragraph-break">✽</div><p>{FIRST}</p></div></div><div class="m-two-images">{photos}</div>
        <div class="m-pull-quote"><blockquote><p>To learn more, read on from the SAPIENS archive:
        <a href="/culture/another/">A different story.</a></p></blockquote></div>
        <blockquote>Short original quotation.</blockquote><p>{LAST}</p></div><div class="m-authors">Bio.</div></div>'''
        _, body = narrate('https://www.sapiens.org/culture/seed-trials/', html)
        self.assertEqual(body, f'Opening context. The cover tray. {FIRST} A first tray. Photo by Lee. A second tray. Photo by Lee. '
                         f'Short original quotation. {LAST}')

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
        <div><div class="wp-caption"><img src="wrapped-tray">
        <p class="wp-caption-text">A second tray on the windowsill.</p></div></div>
        <div class="wp-caption" hidden><img src="unpublished">
        <p class="wp-caption-text">Unpublished frame.</p></div><p>{LAST}</p>
        <h4>Footnotes</h4><ol><li>The study began in March.</li></ol></div>
        <p>Read another article.</p></div><aside><div class="wp-caption"><img src="ad">
        <p class="wp-caption-text">A sponsored image.</p></div></aside>"""
        _, body = narrate('https://www.filfre.net/2026/10/seed-trials/', html)
        self.assertEqual(body.split(),
                         f'{FIRST} A tray of seedlings photographed after rain. '
                         f'A second tray on the windowsill. {LAST} '
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
