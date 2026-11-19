"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re
from html import unescape
from soupsieve import match
from article_scope import BODY_SELECTORS, DATE, FOOTNOTE_NAV, STRONG_TOWNS_HOSTS, article_labels, article_scope, editorial, explicitly_hidden, heading_matches, heading_text, masthead_body, opening_writer_credits, plover_story_title, react_blog_credit, readable_prose, remove_nieman_footnote_controls, remove_resolved_footnote_backlinks, remove_substack_footnote_controls, remove_table_of_contents, url_identity
from imported_content import (
    COLOSSAL_HOSTS, GUARDIAN_HOSTS, HARVARD_HOSTS, OUTSIDE_HOSTS, QUILLETTE_HOSTS, WYOFILE_HOSTS, clean_jstor_pull_quotes,
    remove_bgs_related_news, remove_bgs_topic_links, remove_loc_subscription, remove_openculture_endmatter, remove_outside_newsletter, remove_pluralistic_footer,
    remove_quillette_bookmarks, remove_webb_download_intro, universal_hub_writer,
    wyofile_feature,
)
from tts import speech_text


EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
    f'{FOOTNOTE_NAV}, '
    '.post-header, .post-footer, .post-meta, .post-metadata, .post-actions, .share-buttons, '
    '[data-block="byline"], [data-testid="multi-byline"], '
    '[itemprop="datePublished"], [itemprop="dateModified"], [data-testid="timestamp"], '
    '.subscription-widget, .entryFooter, .mobile-date-eyebrow, .edit-page-link, '
    '.posted, .publish-date-author, .basic-hero--blog-detail__description, '
    '.author-bio, .post-author, .post-categories, .related-posts, .related-articles, '
    '.comments, #comments, #Sidebar, #Footer, .linkedlist .smallprint, '
    '.gh-post-upgrade-cta, .gh-post-upgrade-cta-content, .post-access-cta, '
    '.j-icon, .sharedaddy, .translate-post, #jp-relatedposts, .harvard-sharing, '
    '.article-cta-box, .collection-cta, .collection-dateline, [class*="AscendiumAdUnit_wrapper__"], '
    '.wp-block-image, .wp-caption, .wp-block-video, .caption, .featured-img__caption, '
    'figure:has(img), figure:has(video), figure:has(audio)'
)


def remove_opening_metadata(root, author):
    """Remove consecutive opening labels, preserving dates and credits in prose."""
    for paragraph in list(root.find_all('p')):
        value = ' '.join(speech_text(paragraph.get_text(' ', strip=True)).split())
        if not value:
            continue
        if paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure', 'figcaption']):
            break
        links = paragraph.find_all('a')
        outside = ' '.join(' '.join(str(node) for node in paragraph.find_all(string=True)
                                   if node.find_parent('a') is None).split())
        translation = (bool(links) and all(link.get('href') for link in links) and
                       re.fullmatch(r'Translations?\s*:[\s,;|/·•()\[\]]*',
                                    re.sub(r'\band\b', '', outside, flags=re.I), re.I))
        byline = author and re.fullmatch(r'by\s*:?\s*' + re.escape(author) + r'\.?', value, re.I)
        history = (len(links) == 1 and links[0].get('href', '').startswith('#') and
                   links[0].get_text(' ', strip=True).casefold() in ('changes', 'updates', 'changelog') and
                   DATE.fullmatch(outside.strip('()[] ')))
        # A standalone emphasized date is an opening publication label. Stop
        # at the first prose paragraph, leaving story dates and quotes intact.
        date = DATE.fullmatch(value) and paragraph.find('em') is not None
        if not (translation or byline or history or date):
            break
        paragraph.decompose()


def remove_site_endmatter(root):
    """Recognize a divided site footer, rather than matching prose about ads."""
    for paragraph in list(root.find_all('p')):
        if (not editorial(paragraph) or
                paragraph.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure', 'figcaption'])):
            continue
        value = ' '.join(paragraph.get_text(' ', strip=True).split())
        separator = paragraph.find_previous_sibling()
        recommendations = paragraph.find(['ul', 'ol'])
        if recommendations is None:
            following = paragraph.find_next_sibling()
            if following is not None and following.name in ('ul', 'ol'):
                recommendations = following
        # This combination marks the start of site endmatter: a divider, a
        # self-description linked to the homepage, then recommended articles.
        # Remove only the remainder of that same container, never its ancestors.
        if (separator is None or separator.name != 'hr' or
                not re.match(r"^You['’]re reading\s+", value, re.I) or
                not re.search(r'If you liked this you might also enjoy:\s*', value, re.I) or
                paragraph.select_one('a[href="/"]') is None or
                recommendations is None or not recommendations.select('li a[href]')):
            continue
        preceding = ' '.join(node.get_text(' ', strip=True) for node in separator.find_previous_siblings()
                             if editorial(node))
        if not readable_prose(preceding):
            continue
        for node in [separator, *separator.next_siblings]:
            node.extract()


def remove_press_contacts(root):
    """Recognize contact-only tails after a press release's explicit end marker."""
    for marker in list(root.find_all('p')):
        if (marker.get_text(' ', strip=True).casefold() != '-end-' or
                marker.find_parent(['blockquote', 'pre', 'code', 'li', 'table'])):
            continue
        following = [node for node in marker.next_siblings if str(node).strip()]
        if not following or len(following) > 8:
            continue
        if not all(getattr(node, 'name', '') == 'p' and node.find('br') and
                   node.select_one('a[href^="mailto:"]') and
                   len(node.get_text(' ', strip=True)) < 600 and
                   not readable_prose(node.get_text(' ', strip=True)) for node in following):
            continue
        preceding = ' '.join(node.get_text(' ', strip=True) for node in marker.find_previous_siblings())
        if not readable_prose(preceding):
            continue
        for node in [marker, *following]:
            node.decompose()


def remove_article_footer(root, author):
    """Remove a marked footer and its adjacent author-bio/feedback labels."""
    for footer in root.select('#single-article-footer'):
        if footer.parent is None or footer.find_parent(['blockquote', 'pre', 'code']):
            continue
        feedback = footer.find_previous_sibling()
        if (feedback is not None and feedback.name == 'p' and feedback.find('a') and
                feedback.find(['b', 'strong']) and len(feedback.get_text(' ', strip=True)) < 350 and
                re.match(r'^FEEDBACK:\s*Use this form\b', feedback.get_text(' ', strip=True), re.I)):
            biography = feedback.find_previous_sibling()
            feedback.decompose()
            if (author and biography is not None and biography.name == 'p' and
                    biography.find(['i', 'em']) and biography.find('a') and
                    len(biography.get_text(' ', strip=True)) < 500 and
                    re.match(re.escape(author)+r' is (?:a|an) .{0,100}\b(?:writer|reporter|journalist|editor)\b',
                             biography.get_text(' ', strip=True)) and
                    re.search(r'\bFind (?:him|her|them)\s+on\b', biography.get_text(' ', strip=True), re.I)):
                biography.decompose()
        footer.decompose()


def remove_publication_notices(root):
    """Omit marked publishing widgets while retaining article references/prose."""
    for node in root.select('.cc-attribution'):
        if node.parent is None or node.find_parent(['blockquote', 'pre', 'code']):
            continue
        paragraphs = node.find_all('p')
        if (len(paragraphs) == 1 and len(node.get_text(' ', strip=True)) < 1500 and
                paragraphs[0].get_text(' ', strip=True).startswith('The text in this work is licensed under a Creative Commons') and
                node.select_one('a[href*="creativecommons.org/licenses/"]')):
            node.decompose()
    labels = {'article-citation': 'cite this work', 'article-past-versions': 'past versions',
              'article-licence': 'reuse this work freely'}
    for node in root.select('section#article-citation, section#article-past-versions, section#article-licence'):
        if (node.parent is None or node.find_parent(['blockquote', 'pre', 'code']) or
                not node.find_parent('article', class_='centered-article-container')):
            continue
        heading = node.find(['h2', 'h3'])
        if heading and heading.get_text(' ', strip=True).casefold() == labels[node['id']]:
            node.decompose()


def remove_repeated_cover_deck(root, title):
    """Avoid reading a title-cover teaser again at the start of the body."""
    for cover in root.select('.wp-block-cover__inner-container'):
        if not editorial(cover) or cover.find_parent(['blockquote', 'pre', 'code']):
            continue
        heading = cover.find('h1')
        paragraphs = cover.find_all('p')
        owner = next((node for node in cover.parents if match(BODY_SELECTORS, node)), None)
        if (owner is None or heading is None or len(paragraphs) != 1 or
                not heading_matches(heading_text(heading), title)):
            continue
        deck = paragraphs[0]
        following = deck.find_next('p')
        if (following is None or not editorial(following) or
                following.find_parent(['blockquote', 'pre', 'code']) or
                not any(node is owner for node in following.parents)):
            continue
        value = ' '.join(deck.get_text(' ', strip=True).split()).rstrip('.!?')
        body = ' '.join(following.get_text(' ', strip=True).split())
        if len(value) > 40 and re.match(re.escape(value) + r'[.!?](?:\s|$)', body):
            deck.decompose()


def clean_tree(root, title, author, url=''):
    remove_resolved_footnote_backlinks(root, url)
    remove_substack_footnote_controls(root)
    for block, _ in article_labels(root, title):
        block.decompose()
    # RebelMouse recommendation widgets can sit inside the article body.
    # Require their complete component structure; retain quotations and prose.
    for widget in root.select('.around-the-web'):
        children = [node for node in widget.children if str(node).strip()]
        headings = widget.select(':scope > .from-your-site__headline, :scope > .around-the-web__headline')
        if (not widget.find_parent(['blockquote', 'pre', 'code']) and
                headings and all(node.get_text(' ', strip=True).casefold() in
                                 {'from your site articles', 'related articles around the web'} for node in headings) and
                widget.select_one('ul.around-the-web__list li a[href]') and
                all(getattr(node, 'name', None) and match(
                    '.from-your-site__headline, .around-the-web__headline, .around-the-web__list', node)
                    for node in children)):
            widget.decompose()
    remove_site_endmatter(root)
    remove_press_contacts(root)
    remove_article_footer(root, author)
    remove_publication_notices(root)
    remove_repeated_cover_deck(root, title)
    for paragraph, writer in opening_writer_credits(root):
        if writer == author:
            paragraph.decompose()
    for node in root.select('[style], [hidden], [aria-hidden]'):
        if node.parent is not None and explicitly_hidden(node):
            node.decompose()
    identity = url_identity(url)
    if identity and identity[1] in {'universalhub.com', 'www.universalhub.com'}:
        opening, writer = universal_hub_writer(root, url)
        if opening and writer == author:
            opening.decompose()
        for story in root.select('article.node-story.view-mode-full > .content'):
            photo = story.select_one(':scope > .field-name-field-top-photo:has(img)')
            caption = photo.find_next_sibling() if photo else None
            body = story.select_one(':scope > .field-name-body > .field-items > .field-item')
            if caption and body and match('.field-name-field-caption', caption) and editorial(caption):
                body.insert(0, caption.extract())
    if identity and identity[1] in STRONG_TOWNS_HOSTS and identity[2].startswith('/journal/'):
        for wrapper in root.select('.action-content_wrap'):
            body = wrapper.select_one(':scope > section .mast-article-rich-text.w-richtext')
            caption = wrapper.select_one(':scope > .mast-section .img-component:has(img) + div '
                                         '> .rich-text-component.mast-mt-xs > .mast-rich-text.w-richtext')
            if body and caption and editorial(body) and editorial(caption):
                body.insert(0, caption.extract())
    if identity and identity[1] == 'daily.jstor.org':
        for body in root.select('article > .entry-content'):
            clean_jstor_pull_quotes(body)
    if identity and identity[1] in {'postgresql.org', 'www.postgresql.org'} and identity[2].startswith('/about/news/'):
        for node in root.select('#pgContentWrap > .newsdate'):
            node.decompose()
    if identity and identity[1] in {'tbray.org', 'www.tbray.org'} and identity[2].startswith('/ongoing/When/'):
        for caption in root.select('#centercontent > .main-image:has(img) + div.caption'):
            if editorial(caption):
                caption['class'].remove('caption')
        footer = root.select_one('#centercontent > #footer')
        if footer and footer.select_one(':scope > p.footer > [data-pagefind-meta^="date:"]'):
            footer.decompose()
    if identity and identity[1] in {'eff.org', 'www.eff.org'} and identity[2].startswith('/deeplinks/'):
        for figure in root.select('article.node--blog--full .field--name-body .caption:has(img)'):
            caption = figure.select_one('.caption-inner > p.caption-text')
            if caption and editorial(caption):
                figure.insert_before(caption.extract())
    if identity and identity[1] == 'www.bgs.ac.uk':
        for main in root.select('main'):
            remove_bgs_related_news(main)
            remove_bgs_topic_links(main, url)
            bodies = main.select(':scope > section.wp-block-bgs-blocks-content-container.content-section')
            for hero in main.select(':scope > section.hero-section-article > .hero-info-wrap .hero-info'):
                heading = hero.find('h1', recursive=False)
                deck = heading.find_next_sibling() if heading else None
                if (len(bodies) == 1 and deck and deck.name == 'p' and editorial(deck)
                        and heading_matches(heading_text(heading), title)):
                    bodies[0].insert(0, deck.extract())
    if identity and identity[1] == 'www.w3.org' and identity[2].startswith('/blog/'):
        layout = 'body.post main#main > .content > article'
        for section in root.select(layout + ' > section.meta:has(time[datetime])'):
            labels = [item.get_text(strip=True) for item in section.select(':scope > dl > dt')]
            if labels and all(label in {'By:', 'Published:', 'Updated:'} for label in labels):
                section.decompose()
        for category in root.select(layout + ' > .sub-head:has(a[href^="/blog/category/"])'):
            if category.get_text(' ', strip=True).startswith('Part of '):
                category.decompose()
    if identity and identity[1] == 'daringfireball.net':
        for node in root.select('#Main > .article > #PreviousNext:has(table), #Main > .article > h6.dateline'):
            label = node.get_text(strip=True).split(', ', 1)[-1]
            if node.get('id') == 'PreviousNext' or DATE.fullmatch(label):
                node.decompose()
    if identity and identity[1] in {'atlasobscura.com', 'www.atlasobscura.com'} and identity[2].startswith('/articles/'):
        for link in root.select('section#article-body.ArticleBody > h3.article-second-subheading-pre-rd > a[href]'):
            if editorial(link):
                link.unwrap()
    if identity and identity[1] in {'theconversation.com', 'www.theconversation.com'}:
        for article in root.select('article#article'):
            bodies = article.select('.entry-content.content-body')
            captions = article.select(':scope > figure.magazine:has(img) > .caption-wrapper > figcaption:has(> .attribution)')
            if len(bodies) == len(captions) == 1 and editorial(bodies[0]) and editorial(captions[0]):
                caption = captions[0]
                caption.name = 'p'
                caption.string = ' '.join(caption.stripped_strings)
                bodies[0].insert(0, caption.extract())
        for caption in root.select('article#article .entry-content > figure.zoomable:has(img) > figcaption:has(> .caption)'):
            if editorial(caption):
                figure = caption.parent
                caption.name = 'p'
                caption.string = ' '.join(caption.stripped_strings)
                figure.insert_before(caption.extract())
    if identity and identity[1] == 'diff.wikimedia.org':
        # Keep captions from the inner image blocks when the enclosing photo
        # gallery would otherwise be pruned as an image.
        for gallery in root.select('article .entry-content.wrapper-small > figure.wp-block-gallery.has-nested-images'):
            gallery.name = 'div'
    if identity and identity[1] in {'reason.com', 'www.reason.com'} and identity[2].startswith('/volokh/'):
        for article in root.select('article.volokh-post'):
            permalink = article.select_one(':scope > header > h2.entry-title > a[href]')
            body = article.select_one(':scope > .entry-content')
            if permalink and body and url_identity(permalink['href'], url) == identity:
                deck = permalink.parent.select_one(':scope > p.entry-subtitle')
                if deck and editorial(deck):
                    opening = body.find('p', recursive=False)
                    if not opening or ' '.join(opening.get_text().split()) != ' '.join(deck.get_text().split()):
                        body.insert(0, deck.extract())
    if identity and identity[1] in {'reason.com', 'www.reason.com'}:
        for widget in root.select('article.rcom-standard-article .entry-content .gform_wrapper.incontent-email-signup_wrapper'):
            if (widget.select_one(':scope > form input[type="email"]')
                    and not widget.find_parent(['blockquote', 'pre', 'code'])):
                widget.decompose()
    if identity and identity[1] == 'blogs.kde.org':
        for form in root.select('article.post-content form.listmonk-form[action="https://newsletter.kde.org/subscription/form"]'):
            prompt = form.find_previous_sibling()
            heading = prompt.find_previous_sibling() if prompt and prompt.name == 'p' else None
            if (heading and heading.name == 'h2' and heading.get('id') == 'newsletter'
                    and heading.get_text(strip=True) == 'Newsletter'
                    and prompt.get_text(strip=True) == 'Enter your email address to follow this blog and receive notifications of new posts by email.'):
                prompt.decompose()
                heading.decompose()
    if identity and identity[1] == 'react.dev' and identity[2].startswith('/blog/'):
        byline, writer = react_blog_credit(root, title)
        if byline and writer == author:
            byline.decompose()
    if identity and identity[1] == 'projects.propublica.org':
        for opener in root.select('article > header.opener'):
            headline = opener.select_one('.opener__text > h1.opener__hed')
            deck = opener.select_one('.opener__text > p.opener__dek')
            if headline and deck and heading_matches(heading_text(headline), title) and editorial(deck):
                opener.insert_before(deck.extract())
        for stat in root.select('article > .p-grid-container > section.stat-row[aria-label="Totals"] > div.stat'):
            value = stat.select_one(':scope > .stat__value')
            label = stat.select_one(':scope > .stat__label')
            if value and label and editorial(value) and editorial(label):
                stat.name = 'p'
                stat.string = f'{label.get_text(" ", strip=True)}: {value.get_text(" ", strip=True)}.'
        for box in root.select('article > .p-grid-container > .wide-block > .callout-box'):
            if (not box.find_parent(['blockquote', 'pre', 'code']) and box.select_one(':scope > h3.callout-box__hed')
                    and box.select_one(':scope > .callout-box__text a[href="https://www.propublica.org/tips/"]')):
                box.decompose()
    if identity and identity[1] == 'news.mit.edu':
        for body in root.select('article .news-article--content--body--inner'):
            prose = [' '.join(node.get_text().split()) for node in
                     body.select('.paragraph--type--content-block-text p') if editorial(node)]
            for caption in body.select('.news-article--inline-image--descr > .news-article--inline-image--caption'):
                value = ' '.join(caption.get_text().split())
                # The image template can repeat a complete quotation and change only its speaker label.
                quote = re.fullmatch(r'(“[^”]+”)\s*(?:[A-Z][\w’.-]*(?: [A-Z][\w’.-]*)* (?:says|said|adds)\.)?', value)
                if quote and any(text.startswith(quote[1]) for text in prose):
                    caption.decompose()
    if identity and identity[1] == 'creativecommons.org':
        body = 'body.blog-post main > .content'
        for opening in root.select(body + ' > aside.opening:first-child'):
            if opening.find('p', recursive=False):
                opening.name = 'div'
        for stamp in root.select(body + ' > span.pub-date'):
            label = stamp.get_text(' ', strip=True)
            if label.startswith('Posted ') and DATE.fullmatch(label.removeprefix('Posted ')):
                stamp.decompose()
    if identity and identity[1] == 'blog.openstreetmap.org':
        for menu in root.select('p.icl_post_in_other_langs.wpml-ls-statics-post_translations'):
            if (menu.select_one('[role="navigation"] a.wpml-ls-link[hreflang]')
                    and not menu.find_parent(['blockquote', 'pre', 'code'])):
                menu.decompose()
    if identity and identity[1] == 'blog.mozilla.org':
        for menu in root.select('.ft-c-single-post__body > p.wpml-ls-statics-post_translations.wpml-ls'):
            links = menu.find_all('a', href=True)
            if (next(menu.stripped_strings, '') == 'This post is also available in:' and links
                    and all(link.select_one('.wpml-ls-native[lang]') and
                            (target := url_identity(link['href'], url)) and target[:2] == identity[:2]
                            for link in links)):
                menu.decompose()
    if identity and identity[1] == 'blog.pypi.org':
        for anchor in root.select('.md-content--post :is(h1,h2,h3,h4,h5,h6) > a.headerlink'):
            heading_id = anchor.parent.get('id')
            if heading_id and anchor.get('href') == '#' + heading_id and anchor.get_text(strip=True) == '¶':
                anchor.decompose()
    if identity and identity[1] == 'freebsdfoundation.org' and identity[2].startswith('/blog/'):
        for rel, label in (('prev', 'Previous'), ('next', 'Next')):
            for link in root.select(f'.post-content > span.nav-{label.lower()} > a[rel~="{rel}"][href]'):
                if link.get_text(' ', strip=True) == label:
                    link.decompose()
    if identity and identity[1] in {'openculture.com', 'www.openculture.com'}:
        for body in root.select('.recent_post > .colorcontrast > .entry'):
            if editorial(body):
                remove_openculture_endmatter(body, url)
    if identity and identity[1] == 'inkscape.org' and identity[2].startswith('/news/'):
        for stamp in root.select('#content .wrapper > h1 + p.postdate'):
            label = ' '.join(stamp.stripped_strings)
            date = re.sub(r',\s+\d{1,2}:\d{2}(?:\s+[ap]\.m\.)?$', '', label, flags=re.I)
            if DATE.fullmatch(date):
                stamp.decompose()
        for breadcrumbs in root.select('body.news #content > .wrapper > .breadcrumbs:has(a[href])'):
            breadcrumbs.decompose()
    if identity and identity[1] == 'earthsky.org':
        for widget in root.select('.post-rich-text > .ns-buttons.ns-inline-below'):
            if widget.select_one('.ns-buttons-wrapper a[aria-label^="Share on "]'):
                widget.decompose()
        for caption in root.select('.post-rich-text > figure.wp-block-video > figcaption.wp-element-caption'):
            if editorial(caption) and caption.parent.select_one(':scope > video[src], :scope > video > source[src]'):
                caption.name = 'p'
                caption.parent.insert_before(caption.extract())
    if identity and identity[1] in {'robinsloan.com', 'www.robinsloan.com'}:
        for stamp in root.select('main > article > h1 + date-stamp'):
            if DATE.fullmatch(' '.join(stamp.stripped_strings)):
                stamp.decompose()
        for link in root.select('main > article > a.button[href="/lab/"]'):
            if link.get_text(' ', strip=True) == 'To the blog home page':
                link.decompose()
    if identity and identity[1] in {'popsci.com', 'www.popsci.com'}:
        for body in root.select('article > .article-content-featured-image + .entry-content, '
                                'article.featured-template-post > section.featured-template-content > .entry-content'):
            if body.parent.name == 'section':
                caption = body.parent.parent.select_one(
                    ':scope > figure.featured-image:has(img) > figcaption.article-featured-image-caption')
            else:
                featured = body.find_previous_sibling()
                caption = featured.select_one('figure:has(img) > figcaption.article-featured-image-caption')
            if caption and editorial(caption) and editorial(body):
                caption.name = 'div' if caption.find('p') else 'p'
                credit = caption.select_one(':scope > .article-featured-image-caption-credits')
                if credit:
                    credit.insert_before(' ')
                body.insert(0, caption.extract())
        for widget in root.select('.entry-content section.content-widget.pw-incontent-excluded'):
            if widget.select_one('a[href*="/home-of-the-future-awards-"]'):
                widget.decompose()
    if identity and identity[1] in {'sapiens.org', 'www.sapiens.org'}:
        for body in root.select('.c-article-content[data-article-content] > .c-modules'):
            header = body.parent.select_one(':scope > .p-header-article')
            headline = header.select_one(':scope > h1.p-header-article__title') if header else None
            deck = header.select_one(':scope > .p-header-article__standfirst') if header else None
            if headline and deck and heading_matches(heading_text(headline), title) and editorial(deck):
                body.insert(0, deck.extract())
            for divider in body.select('.m-wysiwyg > .wysiwyg > .paragraph-break'):
                if divider.get_text(strip=True) == '✽':
                    divider.decompose()
            for card in body.select(':scope > .m-pull-quote'):
                link = card.select_one('blockquote > p > a[href]')
                target = url_identity(link['href'], url) if link else None
                if (target and target[:2] == identity[:2] and target != identity and
                        card.get_text(' ', strip=True).startswith('To learn more, read on from the SAPIENS archive:')):
                    card.decompose()
        # SAPIENS puts its editorial caption and photo credit in a figure footer.
        for footer in root.select('.c-article-content :is(.m-article-img-header, .m-image-video, '
                                  '.m-two-images__media, .m-text-insert-image__media) '
                                  '> figure.c-image-video > footer.c-image-video__footer:has(> .c-media-caption)'):
            figure = footer.parent
            if editorial(figure) and figure.find('img'):
                footer.name = 'p'
                footer.attrs = {}
                labels = footer.select(':scope > .c-media-caption, :scope > .c-media-credits')
                footer.string = ' '.join(label.get_text().strip() for label in labels)
                component = figure.parent
                modules = (component.parent.select_one(':scope > .c-modules')
                           if match('.c-article-content[data-article-content] > .m-article-img-header', component)
                           else None)
                if modules:
                    deck = modules.select_one(':scope > .p-header-article__standfirst')
                    if deck:
                        deck.insert_after(footer.extract())
                    else:
                        modules.insert(0, footer.extract())
                else:
                    component.insert_before(footer.extract())
    if identity and identity[1] in {'niemanlab.org', 'www.niemanlab.org'}:
        for card in root.select('.roscoe-body > p > div.embed-relatedstory'):
            if card.select_one(':scope > a.embed-relatedstory-imagelink[href]') and not card.find_parent(
                    ['blockquote', 'pre', 'code']):
                card.decompose()
        for body in root.select('.roscoe-body'):
            remove_nieman_footnote_controls(body, url)
    if identity and identity[1] in {'lithub.com', 'www.lithub.com'}:
        for bio in root.select('.story-content > .bio-container:has(> .bio)'):
            if not bio.find_parent(['blockquote', 'pre', 'code']):
                bio.decompose()
        for ad in root.select('.story-content > .story-body .insert-post-ads:has(> script)'):
            if (ad.get_text(strip=True) == 'Article continues after advertisement'
                    and not ad.find_parent(['blockquote', 'pre', 'code'])):
                ad.decompose()
        if identity[2].startswith('/lit-hub-daily-'):
            for lead in root.select('.story-content > .story-body > p:first-of-type > span.caption:first-child'):
                if lead.get_text(strip=True).startswith('TODAY:'):
                    lead['class'].remove('caption')
    if identity and identity[1] in {'universetoday.com', 'www.universetoday.com'}:
        for body in root.select('main.container > article > figure:has(img) + .article-content > .text'):
            figure = body.parent.find_previous_sibling()
            caption = figure.find('figcaption', recursive=False)
            if caption and editorial(caption) and editorial(body):
                caption.name = 'div' if caption.find('p') else 'p'
                body.insert(0, caption.extract())
    if identity and identity[1] in QUILLETTE_HOSTS:
        for body in root.select('article.post > section > .gh-content-fade'):
            remove_quillette_bookmarks(body, url)
            cover = body.parent.parent.select_one(':scope > header > figure.gh-feature-image:has(img) > figcaption')
            if cover and editorial(cover) and editorial(body):
                cover.name = 'div' if cover.find('p') else 'p'
                body.insert(0, cover.extract())
    if identity and identity[1] == 'www.raspberrypi.com' and identity[2].startswith('/news/'):
        for caption in root.select('.c-post-content__wysiwyg > figure.wp-block-gallery > figcaption.blocks-gallery-caption'):
            if editorial(caption) and caption.parent.find('img'):
                caption.name = 'p'
                caption.parent.insert_before(caption.extract())
    if identity and identity[1] in {'astronomy.com', 'www.astronomy.com'} and author:
        for bio in root.select('article > .entry-content > hr.wp-block-separator + p.wp-block-paragraph:last-child'):
            credit = bio.select_one(':scope > em > strong:first-child')
            if (credit and editorial(bio) and not bio.find_parent(['blockquote', 'pre', 'code'])
                    and credit.get_text(strip=True) == author
                    and bio.get_text(' ', strip=True).startswith(f'{author} is a staff writer at Astronomy,')
                    and bio.get_text(strip=True) == credit.parent.get_text(strip=True)):
                bio.decompose()
    if identity and identity[1] in {'geographyrealm.com', 'www.geographyrealm.com'}:
        for body in root.select('article .entry-content'):
            targets = {'#' + h['id'] for h in body.select(':scope > h2[id]')}
            for index in body.select(':scope > div:has(> strong)'):
                label = index.strong
                links = index.select(':scope > a[href]')
                other_text = ''.join(str(node) for node in index.find_all(string=True)
                                     if node.find_parent(['a', 'strong']) is None)
                if (editorial(index) and label.get_text(strip=True) == 'Browse by state:' and len(links) >= 2
                        and all(link['href'] in targets for link in links)
                        and not other_text.strip(' •\t\r\n')):
                    index.decompose()
            for listing in body.select(':scope > h2.wp-block-heading + ul.wp-block-list:last-child'):
                label = listing.find_previous_sibling()
                items = listing.find_all(recursive=False)
                more_articles = (label.get('id') == 'h-more-geography-articles-of-interest' and
                                 label.get_text(strip=True) == 'More Geography Articles of Interest')
                link_section = (label.get_text(strip=True) == 'Related' or
                                label.get('id') == 'h-see-also' and label.get_text(strip=True) == 'See Also' or
                                more_articles)
                links = [child.select_one(':scope > a[href]') if child.name == 'li' else None for child in items]
                if not link_section or not editorial(listing) or not links or not all(
                        link and item.get_text(strip=True) == link.get_text(strip=True) for item, link in zip(items, links)):
                    continue
                targets = [url_identity(link['href'], url) for link in links]
                local = [bool(target and target[:2] == identity[:2] and target != identity) for target in targets]
                label_only = more_articles and any(local) and all(
                    same_site or (target is None and link['href'].replace("'", '’') == link.get_text(strip=True))
                    for link, target, same_site in zip(links, targets, local))
                if all(local) or label_only:
                    label.decompose()
                    listing.decompose()
    if identity and identity[1] in {'publicdomainreview.org', 'www.publicdomainreview.org'} and identity[2].startswith('/collection/'):
        for notice in root.select('.collection-preamble .essay__image__wrapper > .undownloaded-image'):
            if (notice.get_text(' ', strip=True) == 'Scroll through the whole page to download all images before printing.'
                    and not notice.find_parent(['blockquote', 'pre', 'code'])):
                notice.decompose()
        for image in root.select('.collection-preamble > .essay__content > .essay__image:has(img)'):
            caption = image.select_one(':scope > .essay__center-content > .essay__image__caption')
            if caption and editorial(caption) and not caption.find_parent(['blockquote', 'pre', 'code']):
                # The layout marks both the picture and its credit as image
                # content. Move the caption text before image pruning.
                image.insert_before(caption.extract())
                caption.unwrap()
    if identity and identity[1] == 'creativecommons.org':
        for body in root.select('body.blog-post main > .content'):
            cover = body.parent.select_one(':scope > header > figure:has(img) > figcaption')
            if cover and editorial(cover) and editorial(body):
                cover.name = 'div' if cover.find('p') else 'p'
                body.insert(0, cover.extract())
    if identity and identity[1] in {'bbc.com', 'www.bbc.com', 'bbc.co.uk', 'www.bbc.co.uk'} and identity[2].startswith('/news/'):
        for image in root.select('main article [data-testid="image"] > figure:has(img)'):
            caption = image.find('figcaption', recursive=False)
            if caption and editorial(caption):
                for line in caption.find_all('p'):
                    if editorial(line):
                        image.parent.insert_before(line.extract())
    if identity and identity[1] in {'quantamagazine.org', 'www.quantamagazine.org'}:
        for figure in root.select('main .post > .has-tombstone > figure:has(img)'):
            caption = figure.find('figcaption', recursive=False)
            following = figure.find_next_sibling()
            body = following.select_one('.post__content') if following and match('div.acf-content', following) else None
            if caption and body and editorial(caption) and editorial(body):
                lines = [line for line in caption.select('.caption > p, .attribution > p') if editorial(line)]
                for index, line in enumerate(lines):
                    body.insert(index, line.extract())
    if identity and identity[1] == 'blogs.loc.gov':
        for body in root.select('article > .entry-content'):
            remove_loc_subscription(body)
            cover = body.parent.select_one(':scope > header.entry-header > figure.hero-post:has(img) > figcaption')
            if cover and editorial(cover) and editorial(body):
                cover.name = 'div' if cover.find('p') else 'p'
                body.insert(0, cover.extract())
    if identity and identity[1] in HARVARD_HOSTS:
        for article in root.select('article.node--type-article'):
            covers = article.select('.article_header_section .field--name-field-hero-image '
                                    'figure.media--view-mode-article-hero:has(img) > figcaption')
            bodies = article.select('.block-field-blocknodearticlebody > .field--name-body.field--type-text-with-summary')
            if len(covers) == len(bodies) == 1 and editorial(covers[0]) and editorial(bodies[0]):
                cover = covers[0]
                cover.name = 'div' if cover.find('p') else 'p'
                bodies[0].insert(0, cover.extract())
    if identity and identity[1] == 'pluralistic.net':
        for body in root.select('article > .entry-content'):
            remove_pluralistic_footer(body)
    if identity and identity[1] in {'www.nasa.gov', 'nasa.gov', 'science.nasa.gov'}:
        for image in root.select('.entry-content > .hds-media.wp-block-image, '
                                 '.entry-content > p.wp-block-paragraph > .hds-media.wp-block-image'):
            wrapper = image.select_one('.hds-media-wrapper:has(img)')
            caption = wrapper.find('figcaption', recursive=False) if wrapper else None
            if caption and editorial(caption):
                caption.name = 'div' if caption.find('p') else 'p'
                image.insert_before(caption.extract())
        if identity[1] == 'science.nasa.gov' and identity[2].startswith('/missions/webb/'):
            for body in root.select('article .usa-article-content > .entry-content'):
                remove_webb_download_intro(body)
                for caption in body.select(':scope > .stma-image-wrapper + figcaption.hds-caption'):
                    if editorial(caption) and caption.find_previous_sibling().find('img'):
                        caption.name = 'div'
    if identity and identity[1] in GUARDIAN_HOSTS:
        for media in root.select('article > [data-gu-name="media"]'):
            bodies = media.parent.select('[data-gu-name="body"] .article-body-viewer-selector')
            if len(bodies) != 1 or not editorial(bodies[0]):
                continue
            captions = {}
            for caption in media.select('figure figcaption[data-spacefinder-role="inline"]'):
                if editorial(caption) and caption.find_parent('figure').find('img'):
                    text = ' '.join(caption.get_text(' ', strip=True).split())
                    if text:
                        captions.setdefault(text, caption)
            for index, caption in enumerate(captions.values()):
                caption.name = 'p'
                bodies[0].insert(index, caption.extract())
    if identity and identity[1] in {'propublica.org', 'www.propublica.org'}:
        for body in root.select('article > .article-body > .entry-content'):
            cover = body.parent.parent.select_one(
                ':scope > .entry-header .p-opener__art-wrapper > figure:has(img) > figcaption.p-attribution')
            if cover and editorial(cover) and editorial(body):
                cover.name = 'p'
                body.insert(0, cover.extract())
    if identity and identity[1] == 'buttondown.com' and '/archive/' in identity[2]:
        for deck in root.select('article.email-body > h1.subject + h2.description'):
            body = deck.find_next_sibling()
            if (body and match('.email-body-content', body) and editorial(body) and editorial(deck)
                    and heading_matches(heading_text(deck.find_previous_sibling()), title)):
                body.insert(0, deck.extract())
    if identity and identity[1] in WYOFILE_HOSTS:
        feature = wyofile_feature(root, title)
        if feature:
            bodies = feature.parent.select(':scope > .main-content > article > .entry-content')
            caption = feature.select_one(':scope > figure.post-thumbnail:has(img) > figcaption')
            if len(bodies) == 1 and caption and editorial(caption) and editorial(bodies[0]):
                caption.name = 'p'
                bodies[0].insert(0, caption.extract())
        for player in root.select('article > .entry-content > .article-summary:has(> .instaread-player-slot)'):
            for label in player.select(':scope > p.instaread-disclaimer'):
                label.decompose()
            for prompt in player.select(':scope > p:has(> a[href^="mailto:"])'):
                link = prompt.select_one(':scope > a[href^="mailto:"]')
                address = link.get_text(strip=True)
                if (address.endswith('@wyofile.com') and link.get('href') == f'mailto:{address}'
                        and re.fullmatch(r'Do you have questions about this story\? Or information to share\? '
                                         r'Reach out to .+ at ' + re.escape(address) + r'\.',
                                         ' '.join(prompt.get_text().split()))):
                    prompt.decompose()
    if identity and identity[1] in {'mentalfloss.com', 'www.mentalfloss.com'}:
        for article in root.select('article#main-article'):
            bodies = article.select('.odesa-article-main .article-content')
            if len(bodies) != 1 or not editorial(bodies[0]):
                continue
            body = bodies[0]
            for caption in body.select(':scope > figure > div > figcaption'):
                figure = caption.parent.parent
                if editorial(caption) and figure.find('img'):
                    caption.name = 'p'
                    figure.insert_before(caption.extract())
            lead = article.select_one('figure:has(> [data-lead-image]) > div > figcaption')
            if lead and editorial(lead) and lead.parent.parent.find('img'):
                lead.name = 'p'
                body.insert(0, lead.extract())
    if identity and identity[1] in {'hakaimagazine.com', 'www.hakaimagazine.com'}:
        for heading in root.select('article > section.maincontent > h3.invis'):
            if heading.get_text(strip=True) == 'Article body copy':
                heading.decompose()
    if identity and identity[1] in OUTSIDE_HOSTS:
        for body in root.select('.article-template .js-body-content > .content-wrap.fp-contentTarget'):
            if not editorial(body):
                continue
            remove_outside_newsletter(body, url)
            for ad in body.select(':scope > .ad-placeholder-wrapper'):
                if ad.get_text(' ', strip=True).casefold() == 'advertisement':
                    ad.decompose()
            for stamp in body.select(':scope > .article-body > .pub-date'):
                if stamp.get_text(strip=True).startswith('Published '):
                    stamp.decompose()
            credit = body.parent.select_one(
                ':scope > .article-header > div:has(> img) > p.fp-leadCaption')
            if credit and editorial(credit):
                body.insert(0, credit.extract())
    if identity and identity[1] in {'smashingmagazine.com', 'www.smashingmagazine.com'}:
        for summary in root.select('.article__content .c-garfield-the-cat > .c-garfield-summary '
                                   '> section.article__summary[aria-label="Quick summary"]'):
            if editorial(summary):
                summary.name = 'p'
        for caption in root.select('.c-garfield-the-cat > figure > figcaption'):
            if not editorial(caption):
                continue
            # A positioning class makes density pruning treat the detached
            # caption as overlay text even after its figure is gone.
            if 'op-vertical-bottom' in caption.get('class', []):
                caption['class'].remove('op-vertical-bottom')
            image_link = caption.parent.select_one(':scope > a[href]:has(> img)')
            if not image_link:
                continue
            image = url_identity(image_link['href'], url)
            for link in caption.select(':scope > a[href]'):
                before, after = link.previous_sibling, link.next_sibling
                if (image and url_identity(link['href'], url) == image and link.get_text(strip=True) == 'Large preview'
                        and isinstance(before, str) and before.rstrip().endswith('(')
                        and isinstance(after, str) and after.strip() == ')' and after.next_sibling is None):
                    before.replace_with(before.rstrip()[:-1].rstrip())
                    after.extract()
                    link.decompose()
    if identity and identity[1] == 'zed.dev' and identity[2].startswith('/blog/'):
        for caption in root.select('main article > a[href] > button.cursor-zoom-in > figure:has(> img) > figcaption'):
            if editorial(caption):
                zoom_link = caption.parent.parent.parent
                caption.name = 'p'
                zoom_link.insert_before(caption.extract())
        for widget in root.select('main article > div.flex.flex-col.gap-5:last-of-type > div:has(> h3)'):
            heading = widget.find('h3', recursive=False)
            prompt = heading.find_next_sibling()
            if (heading.get_text(strip=True) == 'Related Posts' and prompt and prompt.name == 'p'
                    and prompt.get_text(strip=True) == 'Check out similar blogs from the Zed team.'
                    and widget.select_one('a[href^="/blog/"]')):
                widget.decompose()
    if identity and identity[1] == 'simonwillison.net':
        for card in root.select('.entry.entryPage > .beat > .beat-content > .beat-row1'):
            label = card.select_one(':scope > a.beat-label.release[href="/elsewhere/release/"]')
            release = card.select_one(':scope > .beat-title > a[href]')
            summary = card.select_one(':scope > .beat-commit')
            if label and release and summary and editorial(card) and not card.find_parent(['blockquote', 'pre', 'code']):
                repeated = f'{label.get_text(strip=True)}: {release.get_text(strip=True)}'
                if repeated == title and summary.get_text(strip=True):
                    label.decompose()
                    release.parent.decompose()
                    if isinstance(summary.contents[0], str):
                        value = summary.contents[0]
                        value.replace_with(re.sub(r'^\s*—\s*', '', value))
    if identity and identity[1] in {'hcn.org', 'www.hcn.org'}:
        for feature in root.select('main.site-main > .featured-image-beside:has(img)'):
            caption = feature.find('figcaption', recursive=False)
            bodies = feature.parent.select(':scope > .main-content article > .entry-content')
            if caption and editorial(caption) and len(bodies) == 1 and editorial(bodies[0]):
                caption.name = 'div' if caption.find('p') else 'p'
                bodies[0].insert(0, caption.extract())
        for widget in root.select('article section.below-content.widget'):
            if not widget.find_parent(['blockquote', 'pre', 'code']):
                label = widget.get_text(' ', strip=True)
                if (label == 'Republish' or
                        label.startswith(('Spread the word.', 'Republish This Story'))):
                    widget.decompose()
        for paragraph in root.select('article .entry-content p.wp-block-paragraph:has(> a[href="mailto:editor@hcn.org"])'):
            opening = paragraph.find('em', recursive=False)
            links = paragraph.find_all('a', recursive=False)
            if (opening and opening.get_text(strip=True) == 'We welcome reader letters. Email'
                    and not paragraph.find_parent(['blockquote', 'pre', 'code'])
                    and [url_identity(link.get('href'), url) for link in links] ==
                    [None, url_identity('/feedback/contact-us', url), url_identity('/policies/lte', url)]
                    and all(node.name in {'p', 'a', 'em'} for node in paragraph.find_all(recursive=False))):
                # WordPress sometimes omits the closing tag before the print-edition note.
                for following in paragraph.find_all('p', recursive=False):
                    paragraph.insert_before(following.extract())
                paragraph.decompose()
        for prompt in root.select('article .entry-content p.wp-block-paragraph > em:has(> a[href="mailto:editor@hcn.org"])'):
            label = prompt.find_previous_sibling()
            brand = prompt.previous_sibling
            if (label and label.name == 'em' and label.get_text(strip=True) == 'We welcome reader letters. Email'
                    and isinstance(brand, str) and brand.strip() == 'High Country News'
                    and not prompt.find_parent(['blockquote', 'pre', 'code'])
                    and [url_identity(link.get('href'), url) for link in prompt.find_all('a', recursive=False)] ==
                    [None, url_identity('/feedback/contact-us', url), url_identity('/policies/lte', url)]):
                label.decompose()
                brand.extract()
                prompt.decompose()
    if identity and identity[1] in {'damninteresting.com', 'www.damninteresting.com'}:
        for article in root.select('article'):
            seen = set()
            # Prefer the closing printed credit when the template repeats it at the top.
            for notice in reversed(article.select(':scope > p.print-only')):
                label = ' '.join(notice.get_text().split())
                if (label.startswith('Since you enjoyed our work enough to print it out,')
                        and (notice.select_one('a[href$="/donate"]')
                             or 'https://www.damninteresting.com/donate' in label)):
                    notice.decompose()
                elif 'print-copyright' in notice.get('class', []):
                    if label in seen:
                        notice.decompose()
                    seen.add(label)
    caption_selectors = {
        **dict.fromkeys(QUILLETTE_HOSTS, 'article.post > section.prose.prose-brand > figure.kg-image-card > figcaption'),
        'blog.archive.org': 'article > .entry-content > figure.wp-block-image > figcaption.wp-element-caption',
        'www.w3.org': 'article > figure.component.component--image > figcaption',
        'inkscape.org': 'body.news #content > .wrapper figure.plugin_picture > figcaption',
        'www.bgs.ac.uk': 'main section.wp-block-bgs-blocks-content-container figure.img-wrap > figcaption.caption',
        'diff.wikimedia.org': ('article .entry-content.wrapper-small .wp-block-image figcaption.wp-element-caption, '
                               'article .entry-content.wrapper-small .wp-block-jetpack-slideshow_slide > figure > figcaption'),
        **dict.fromkeys(STRONG_TOWNS_HOSTS, '.thought-leadership_wrap .mast-article-rich-text '
                        '> figure.w-richtext-figure-type-image > figcaption'),
        **dict.fromkeys({'hyperallergic.com', 'www.hyperallergic.com'}, 'article.gh-article > section.gh-content.is-body '
                        '> figure.kg-image-card > figcaption'),
        **dict.fromkeys(OUTSIDE_HOSTS, '.article-template .js-body-content > .content-wrap.fp-contentTarget '
                        '> figure.pom-image-wrap > figcaption.pom-caption'),
        **dict.fromkeys({'niemanlab.org', 'www.niemanlab.org'}, '.roscoe-body .rsc-quiz '
                        'figure.rsc-quiz-fig > figcaption.rsc-quiz-credit'),
        **dict.fromkeys({'theparisreview.org', 'www.theparisreview.org'}, 'section#content > .article-body-wrap '
                        '> main.article-body.blog-body > div.wp-caption > p.wp-caption-text'),
        'nautil.us': '.entry-content > [class^="PostContent_content__"] > figure.wp-block-image > figcaption.wp-element-caption',
        **dict.fromkeys({'hcn.org', 'www.hcn.org'},
                        'article .entry-content figure.wp-block-image > figcaption.wp-element-caption, '
                        'article .entry-content .wp-block-image > figure > figcaption.wp-element-caption, '
                        'article .entry-content > figure.wp-block-image > figcaption:has(> .image-credit)'),
        **dict.fromkeys({'damninteresting.com', 'www.damninteresting.com'},
                        'article > figure.entry-image > figcaption'),
        **dict.fromkeys({'sciencedaily.com', 'www.sciencedaily.com'},
                        '#story_text > #featured > figure.mainimg > figcaption'),
        **dict.fromkeys({'propublica.org', 'www.propublica.org'},
                        'article > .article-body > .entry-content > figure.wp-block-image > figcaption.attribution'),
        **dict.fromkeys({'popsci.com', 'www.popsci.com'},
                        'article.featured-template-post .entry-content > .content-wrapper '
                        '> figure.wp-block-image > figcaption.wp-element-caption'),
        **dict.fromkeys({'geographyrealm.com', 'www.geographyrealm.com'},
                        'article .entry-content > .wp-block-image > figure > figcaption.wp-element-caption'),
        **dict.fromkeys({'construction-physics.com', 'www.construction-physics.com'},
                        '.available-content .body.markup .captioned-image-container > figure > figcaption.image-caption'),
        **dict.fromkeys({'smashingmagazine.com', 'www.smashingmagazine.com'},
                        '.c-garfield-the-cat > figure:has(img) > figcaption'),
        **dict.fromkeys(WYOFILE_HOSTS, 'article > .entry-content > figure.wp-block-image > figcaption.wp-element-caption, '
                        'article > .entry-content > .wp-block-image > figure > figcaption.wp-element-caption, '
                        'article > .entry-content > .wp-block-columns > .wp-block-column '
                        '> figure.wp-block-image > figcaption.wp-element-caption'),
        **dict.fromkeys(COLOSSAL_HOSTS, 'article .entry-content > .entry-header '
                        '> figure.colo-post-featured-image > figcaption.wp-element-caption, '
                        'article > .entry-content > figure.wp-block-image > figcaption.wp-element-caption'),
        **dict.fromkeys(HARVARD_HOSTS,
                        '.block-field-blocknodearticlebody > .field--name-body figure.caption.caption-img > figcaption'),
        'theguardian.com': '.article-body-viewer-selector figure > figcaption[data-spacefinder-role="inline"]',
        'www.theguardian.com': '.article-body-viewer-selector figure > figcaption[data-spacefinder-role="inline"]',
        'hakaimagazine.com': '.maincontent > div.wp-caption > p.wp-caption-text',
        'www.hakaimagazine.com': '.maincontent > div.wp-caption > p.wp-caption-text',
        **dict.fromkeys({'filfre.net', 'www.filfre.net'},
                        '.post.hentry > .entry > div.wp-caption > p.wp-caption-text, '
                        '.post.hentry > .entry > div:not([class], [id]) > div.wp-caption > p.wp-caption-text'),
        'astronomy.com': '.entry-content > figure.wp-block-image > figcaption.wp-element-caption',
        'www.astronomy.com': '.entry-content > figure.wp-block-image > figcaption.wp-element-caption',
        'www.experimental-history.com': '.available-content .body.markup .captioned-image-container > figure > figcaption.image-caption',
        'experimental-history.com': '.available-content .body.markup .captioned-image-container > figure > figcaption.image-caption',
        'earthsky.org': ('.post-rich-text > figure.wp-block-image > figcaption.wp-element-caption, '
                         '.post-rich-text > div.wp-block-image > figure > figcaption.wp-element-caption'),
        'www.futilitycloset.com': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'futilitycloset.com': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'blogs.loc.gov': '.entry-content > figure.wp-caption > figcaption.wp-caption-text',
        'blogs.egu.eu': ('.entry-content > figure.post-thumbnail.wp-caption > figcaption.featured_caption, '
                         '.entry-content > div.wp-caption > p.wp-caption-text'),
        'webkit.org': 'article .bodycopy > figure > figcaption',
        'smithsonianmag.com': '.articleWrap > figure.article-image > figcaption.caption',
        'www.smithsonianmag.com': '.articleWrap > figure.article-image > figcaption.caption',
        'www.nist.gov': '.text-with-summary figure.nist-image > figcaption.nist-image__caption',
        'blog.cloudflare.com': '.article-content figure.emdash-image > figcaption',
        'www.raspberrypi.com': '.c-post-content__wysiwyg .wp-block-image > figure > figcaption.wp-element-caption',
    }
    if identity and identity[1] in caption_selectors:
        for caption in root.select(caption_selectors[identity[1]]):
            if editorial(caption) and caption.parent.find('img'):
                figure = caption.parent
                caption.name = 'div' if caption.find('p') else 'p'
                if 'caption' in caption.get('class', []):
                    caption['class'].remove('caption')
                container = figure.parent if 'wp-block-image' in figure.parent.get('class', []) else figure
                container.insert_before(caption.extract())
    video_bodies = {'www.raspberrypi.com': '.c-post-content__wysiwyg', 'earthsky.org': '.post-rich-text'}
    if (identity and identity[1] in video_bodies
            and (identity[1] != 'www.raspberrypi.com' or identity[2].startswith('/news/'))):
        for caption in root.select(video_bodies[identity[1]] + ' > figure.wp-block-embed-youtube > figcaption.wp-element-caption'):
            if editorial(caption) and caption.parent.select_one(':scope > .wp-block-embed__wrapper iframe[src]'):
                caption.parent.insert_before(caption.extract())
                caption.name = 'p'
    if identity and identity[1] in {'theguardian.com', 'www.theguardian.com'}:
        for card in root.select('.article-body-viewer-selector figure[data-spacefinder-role="richLink"]'):
            if card.select_one('[data-component="rich-link"] a[href]') and not card.find_parent('blockquote'):
                card.decompose()
    for node in root.select('p.date, p.mobile-date'):
        if (DATE.fullmatch(node.get_text(' ', strip=True)) and
                not node.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figure'])):
            node.decompose()
    # Relative-age badges decorate a year; they are not mathematical subscripts.
    for badge in root.select('sub.styled-sub'):
        label = re.fullmatch(r'(\d{4}) was \d+ years? ago', badge.parent.get('title', ''))
        if (label and re.fullmatch(r'\d+ya', badge.get_text(strip=True)) and
                badge.parent.get_text('', strip=True) == label[1] + badge.get_text(strip=True)):
            badge.decompose()
    for paragraph in list(root.find_all('p')):
        if paragraph.find_parent(['blockquote', 'pre', 'code']):
            continue
        value = paragraph.get_text(' ', strip=True)
        # Short, standalone promotional/caption paragraphs inside the prose.
        # Do not match ordinary sentences mentioning reading or newsletters.
        related = (re.match(r'^Read more:', value, re.I) and paragraph.find('a') and
                   paragraph.find('strong') and len(value) < 250)
        newsletter = (re.match(r'^Enjoying .{1,100}\?\s*Subscribe to our free newsletter', value, re.I)
                      and paragraph.find('a') and len(value) < 250)
        credit = (re.match(r'^(?:Lead|Banner) Image:', value, re.I) and
                  paragraph.find(['em', 'i']) and len(value) < 300 and
                  not any(str(text).strip() for text in paragraph.find_all(string=True)
                          if text.find_parent(['em', 'i']) is None))
        if related or newsletter or credit:
            paragraph.decompose()
    for heading in list(root.find_all(['h2', 'h3'])):
        if heading.parent is None or heading.find_parent(['blockquote', 'pre', 'code']):
            continue
        if heading.get_text(' ', strip=True).casefold() == 'written by':
            parent = heading.parent
            # Anonymous short author cards may contain a name and job title.
            # A readable body or semantic article container must survive cleanup.
            value = parent.get_text(' ', strip=True)
            if (parent is not root and parent.name in ('div', 'section') and
                    not match(BODY_SELECTORS, parent) and not parent.find(['h1', 'article', 'main']) and
                    len(value) < 600 and not readable_prose(value)):
                parent.decompose()
            else:
                heading.decompose()
    # Remove an audio player's label and duration together. Removing only its
    # button leaves labels such as "Listen to this essay / 27 minute listen".
    for label in list(root.find_all(string=re.compile(r'^Listen to this\s*$', re.I))):
        parent = label.parent
        for _ in range(3):
            if parent is None or parent is root:
                break
            value = parent.get_text(' ', strip=True)
            if parent.find('button') and len(value) < 150:
                parent.decompose()
                break
            parent = parent.parent
    # Remove a standalone byline's outer label with its author span. Keep
    # paragraphs that use the same link as part of a sentence or quotation.
    for byline in root.select('.byline, [rel~="author"], [itemprop~="author"]'):
        parent = byline.parent
        if parent is None or parent.name != 'p' or parent.find_parent(['blockquote', 'pre', 'code']):
            continue
        outside = ' '.join(str(text) for text in parent.strings
                           if not any(ancestor is byline for ancestor in text.parents))
        if re.fullmatch(r'\s*By\s*:?\s*', outside, re.I):
            parent.decompose()
    for credit in root.select('.byline, .c-article-author, .c-article__author'):
        if credit.parent is not None and not credit.find_parent(['blockquote', 'pre', 'code']):
            credit.decompose()
    for node in root.select(EXCLUDED):
        if node.parent is not None:
            node.decompose()
    remove_table_of_contents(root, url)
    # Attribute the article once, outside its narration body.
    for node in root.select('h1, h2, h3, dt, [rel~="author"], [itemprop~="author"]'):
        if node.find_parent(['blockquote', 'pre', 'code']):
            continue
        value = heading_text(node) if node.name in ('h1', 'h2', 'h3') else ' '.join(node.get_text(' ', strip=True).split())
        editorial_subheading = (identity and identity[1] == 'creativecommons.org' and node.name in ('h2', 'h3')
                                and match('body.blog-post main > .content > *', node) and value != title)
        if ((title and not editorial_subheading and heading_matches(value[:160].strip(), title)) or
                (author and re.sub(r'^by\s+', '', value, flags=re.I)[:100].strip() == author)):
            node.decompose()
    for tags in list(root.select('.post-tags')):
        if tags.parent is None:
            continue
        heading = tags.find_previous_sibling()
        if (heading and heading.name in ('h2', 'h3') and
                heading.get_text(' ', strip=True).rstrip(':').casefold() == 'tags'):
            heading.decompose()
        tags.decompose()
    for node in root.select('time'):
        if not node.find_parent(['p', 'li', 'blockquote', 'pre', 'code']):
            node.decompose()
    # Older pages often put a standalone date before a <br>. Preserve dates
    # embedded in prose and quotations, including stories that open on a date.
    for node in list(root.find_all(string=True)):
        before_break = (node.previous_sibling is None and
                        getattr(node.next_sibling, 'name', '') == 'br')
        prose = node.find_parent(['p', 'li', 'blockquote', 'pre', 'code'])
        quoted = node.find_parent(['blockquote', 'pre', 'code'])
        if DATE.fullmatch(str(node).strip()) and not quoted and (not prose or before_break):
            node.extract()
    remove_opening_metadata(root, author)


def plain_text(root):
    # Add separators around blocks, without inserting spaces inside inline words
    # (for example, a drop cap's <span>A</span>s or an emphasized word ending).
    for node in root.find_all(['p', 'div', 'section', 'blockquote', 'li', 'h1', 'h2',
                               'h3', 'h4', 'h5', 'h6', 'pre', 'table', 'thead', 'tbody',
                               'tfoot', 'tr', 'th', 'td', 'caption', 'dl', 'dt', 'dd', 'br']):
        node.insert_before('\n')
        node.insert_after('\n')
    return ' '.join(root.get_text('', strip=False).split())


def extract_structured_text(body, title='', author='', url=''):
    """Normalize an already-selected JSON-LD body; never execute or fetch it."""
    from bs4 import BeautifulSoup
    # Preserve plain-text comparisons and code such as C++'s <vector>.
    if not re.search(r'</?(?:p|div|section|article|h[1-6]|br|ul|ol|li|blockquote|pre|table|thead|tbody|tfoot|tr|th|td|caption|dl|dt|dd|a|em|strong|span|script|style)\b[^>]*>', body, re.I):
        return ' '.join(unescape(body).split())
    fragment = BeautifulSoup(body, 'html.parser')
    clean_tree(fragment, title, author, url)
    return plain_text(fragment)


def preserve_reference_lists(scope, url):
    """Keep editorial reference labels from being pruned solely for link density."""
    if scope.name == '[document]':
        return
    for heading in scope.find_all(['h2', 'h3', 'h4', 'h5', 'h6']):
        if (not editorial(heading) or heading.find_parent(['blockquote', 'pre', 'code', 'li', 'table', 'figcaption']) or
                ' '.join(heading.get_text('', strip=False).split()).casefold().rstrip(':') not in
                {'references', 'some references'}):
            continue
        following = heading.find_next_sibling()
        if following is not None and following.name == 'p' and len(following.get_text()) <= 300:
            following = following.find_next_sibling()
        if following is None or following.name not in ('ul', 'ol') or not editorial(following):
            continue
        items = following.find_all('li', recursive=False)
        links = following.find_all('a', href=True)
        if (not items or not links or following.find(['img', 'picture', 'figure', 'button', 'article', 'div', 'section', 'ul', 'ol']) or
                any(not item.find('a', href=True) for item in items) or
                any(not url_identity(link['href'], url) or url_identity(link['href'], url) == url_identity(url)
                    for link in links)):
            continue
        # Labels and inline formatting stay in place; only the link markup is
        # normalized. No references are fetched and no prose is reconstructed.
        for link in links:
            link.unwrap()


def extract_text(soup, title='', author='', url=''):
    scope = article_scope(soup, title, url)
    plover_title = plover_story_title(soup, url)
    plover_body = None
    if plover_title:
        plover_body = plover_title.parent.parent
        permalink = url_identity(plover_title['href'], url)
        plover_title.decompose()
        for date in plover_body.select(':scope > span.dateheader'):
            date.decompose()
        footer = plover_body.find_all('p', recursive=False)[-1]
        for link in footer.select(':scope > i > a[href]'):
            if (link.get_text(strip=True) == 'permanent link' and url_identity(link['href'], url) == permalink
                    and footer.get_text(' ', strip=True).startswith('[ Other articles in category ')):
                footer.decompose()
                break
    # Capture the layout evidence before cleanup removes its masthead. This
    # body uses the same structure-preserving path as explicit article bodies.
    recovered_body = masthead_body(soup, title)
    # LessWrong streams its explicit post body inside an initially hidden React
    # container. Detach only that body before discarding hidden page sections.
    candidates = []
    for node in soup.select('.PostsPage-postContent'):
        if not editorial(node, allow_hidden=True):
            continue
        owner = node if node.name == 'article' else node.find_parent('article')
        if owner is not None and owner is not scope:
            if scope.name == 'article':
                continue
            headings = owner.select('h1, h2, .entry-title')
            if title and headings and not any(heading_matches(heading_text(h), title) for h in headings):
                continue
        candidates.append(node)
    identities = {id(node) for node in candidates}
    sections = [node for node in candidates if not any(id(parent) in identities for parent in node.parents)]
    deferred = []
    for node in sections:
        node.extract()
        clean_tree(node, title, author, url)
        if speech_text(node.get_text('', strip=True)).strip():
            text = plain_text(node)
            # Streaming can repeat the same body for another layout. Keep
            # distinct sections and intentional repetition later in the story.
            if not deferred or text != deferred[-1]:
                deferred.append(text)
    identity = url_identity(url)
    trusted_short_body = False
    if identity and identity[1] in {'filfre.net', 'www.filfre.net'}:
        canonical = soup.select_one('link[rel~="canonical"][href]')
        headlines = scope.select('div.post.hentry > h1.post-title')
        trusted_short_body = (canonical is not None and url_identity(canonical['href'], url) == identity
                              and len(headlines) == 1 and editorial(headlines[0])
                              and heading_matches(heading_text(headlines[0]), title))
    if identity and identity[1] in {'longreads.com', 'www.longreads.com'} | WYOFILE_HOSTS:
        # Strip the Newspack list while its cards still identify the heading.
        for listing in scope.select('.entry-content .wp-block-newspack-blocks-homepage-articles.wpnbha '
                                    '> div:has(> h2.article-section-title):has(> article.type-post)'):
            if identity[1] in WYOFILE_HOSTS:
                heading = listing.select_one(':scope > h2.article-section-title')
                if heading.get_text(' ', strip=True).casefold() != 'related':
                    continue
            if (not listing.find_parent(['blockquote', 'pre', 'code'])
                    and all(match('h2.article-section-title, article.type-post', child)
                            for child in listing.find_all(recursive=False))):
                listing.decompose()
    # Select before cleanup removes the headline used to identify the article.
    for node in list(soup.select('article, .recommendations, .related-posts, .related-articles')):
        if node.parent is not None and (not editorial(node) or
                (node is not scope and not any(parent is node for parent in scope.parents)
                 and node.name == 'article' and scope is not soup)):
            node.decompose()
    clean_tree(soup, title, author, url)
    if deferred:
        return ' '.join(deferred)
    candidates = scope.select(BODY_SELECTORS)
    if plover_body:
        candidates = [plover_body]
    elif match(BODY_SELECTORS, scope) or scope is recovered_body:
        candidates = [scope]
    body_selector = None
    if identity:
        if identity[1] in {'theguardian.com', 'www.theguardian.com'}:
            body_selector = '[data-gu-name="body"] .article-body-viewer-selector'
        elif identity[1] in {'hakaimagazine.com', 'www.hakaimagazine.com'} and scope.name == 'article':
            body_selector = ':scope > section.maincontent'
        elif identity[1] in HARVARD_HOSTS and match('article.node--type-article', scope):
            body_selector = '.block-field-blocknodearticlebody > .field--name-body.field--type-text-with-summary'
        elif identity[1] in OUTSIDE_HOSTS:
            body_selector = '.article-template .js-body-content > .content-wrap.fp-contentTarget'
        elif identity[1] in STRONG_TOWNS_HOSTS and identity[2].startswith('/journal/'):
            body_selector = ':is(.thought-leadership_wrap, .action-content_wrap) .mast-article-rich-text.w-richtext'
        elif (identity[1] in {'universalhub.com', 'www.universalhub.com'}
              and match('article.node-story.view-mode-full', scope)):
            body_selector = ':scope > .content > .field-name-body > .field-items > .field-item'
        elif identity[1] == 'creativecommons.org' and scope.name == 'main' and match('body.blog-post main', scope):
            body_selector = ':scope > .content'
        elif (identity[1] == 'buttondown.com' and '/archive/' in identity[2]
              and match('article.email-body', scope)):
            body_selector = ':scope > .email-body-content'
        elif identity[1] == 'dev.to' and match('article#article-show-container.crayons-article', scope):
            body_selector = ':scope > .crayons-article__main > #article-body.crayons-article__body'
        elif identity[1] == 'www.internetsociety.org' and identity[2].startswith('/blog/') and scope.name == 'article':
            body_selector = ':scope > .body-text'
        elif identity[1] == 'webkit.org' and identity[2].startswith('/blog/') and scope.name == 'article':
            body_selector = ':scope > .bodycopy'
        elif identity[1] in {'filfre.net', 'www.filfre.net'}:
            body_selector = 'div.post.hentry > div.entry'
        elif identity[1] == 'blogs.kde.org' and match('article.post-content', scope):
            body_selector = ':scope > .jumbotron ~ .content-width'
        elif identity[1] == 'blog.rust-lang.org':
            body_selector = 'section.white[id] > div > div.post'
        elif identity[1] == 'inkscape.org' and identity[2].startswith('/news/'):
            body_selector = 'body.news #content > .wrapper'
        elif identity[1] == 'www.bgs.ac.uk' and scope.name == 'main':
            body_selector = ':scope > section.wp-block-bgs-blocks-content-container.content-section'
        elif identity[1] in {'jvns.ca', 'www.jvns.ca'} and identity[2].startswith('/blog/') and match('article.hentry', scope):
            body_selector = ':scope > main'
        elif identity[1] == 'www.w3.org' and identity[2].startswith('/blog/') and match('body.post main#main > .content > article', scope):
            candidates = [scope]
        elif identity[1] in {'eff.org', 'www.eff.org'} and identity[2].startswith('/deeplinks/') and match('article.node--blog--full', scope):
            body_selector = ':scope > .node__content > .field--name-body > .field__items > .field__item'
        elif identity[1] in {'openculture.com', 'www.openculture.com'}:
            body_selector = '.recent_post > .colorcontrast > .entry'
        elif (identity[1] in {'robinsloan.com', 'www.robinsloan.com'} and identity[2].startswith('/lab/')
              and match('main > article', scope)):
            candidates = [scope]
        elif identity[1] in {'aeon.co', 'www.aeon.co'} and identity[2].startswith('/videos/'):
            body_selector = '.article-content'
        elif identity[1] == 'earthsky.org':
            body_selector = '.post-body > .post > .post-rich-text'
        elif identity[1] in {'postgresql.org', 'www.postgresql.org'} and identity[2].startswith('/about/news/'):
            body_selector = '#pgContentWrap'
        elif identity[1] in {'tbray.org', 'www.tbray.org'} and identity[2].startswith('/ongoing/When/'):
            body_selector = '#center-and-right > #centercontent'
        elif identity[1] == 'daringfireball.net' and re.fullmatch(r'/\d{4}/\d{2}/[^/]+', identity[2]):
            body_selector = '#Main > div.article'
        elif (identity[1] == 'blog.r-project.org' and identity[2].startswith('/posts/')
              and match('main#quarto-document-content.quarto-banner-title-block:has(> section.level2)', scope)):
            candidates = [scope]
        elif identity[1] == 'www.nist.gov' and identity[2].startswith('/news-events/news/'):
            body_selector = '.nist-page__region--content .text-with-summary'
        elif identity[1] == 'www.djangoproject.com' and identity[2].startswith('/weblog/'):
            body_selector = '.blog-entry-body'
        elif identity[1] == 'www.raspberrypi.com' and identity[2].startswith('/news/'):
            body_selector = '.c-post-content__wysiwyg'
        elif identity[1] in {'niemanlab.org', 'www.niemanlab.org'}:
            body_selector = '.roscoe-article-body > .roscoe-body'
        elif identity[1] in {'publicdomainreview.org', 'www.publicdomainreview.org'} and identity[2].startswith('/collection/'):
            body_selector = '.collection-view > .collection-preamble > .essay__content'
        elif identity[1] in {'sapiens.org', 'www.sapiens.org'}:
            body_selector = '.c-article-content[data-article-content] > .c-modules'
        elif identity[1] in {'hyperallergic.com', 'www.hyperallergic.com'} and match('article.gh-article', scope):
            body_selector = ':scope > section.gh-content.is-body'
        elif identity[1] in {'universetoday.com', 'www.universetoday.com'} and match('main.container > article', scope):
            body_selector = ':scope > .article-content > .text'
        elif identity[1] in {'lithub.com', 'www.lithub.com'}:
            body_selector = '.story-content > .story-body'
        elif identity[1] in QUILLETTE_HOSTS and match('article.post', scope):
            body_selector = ':scope > section > .gh-content-fade, :scope > section.prose.prose-brand:not(:has(> .gh-content-fade))'
        elif identity[1] in {'theparisreview.org', 'www.theparisreview.org'} and identity[2].startswith('/blog/'):
            body_selector = 'section#content > .article-body-wrap > main.article-body.blog-body'
            if match(body_selector, scope):
                candidates = [scope]
                body_selector = None
    if body_selector:
        bodies = scope.select(body_selector)
        if len(bodies) == 1 and editorial(bodies[0]) and (trusted_short_body or readable_prose(plain_text(bodies[0]))):
            candidates = bodies
    if candidates:
        # Some publications split the article among sibling body containers.
        # Read each outermost section once, inside the same semantic article.
        identities = {id(node) for node in candidates}
        sections = [node for node in candidates if not any(id(parent) in identities for parent in node.parents)]
        pieces = []
        for section in sections:
            clean_tree(section, title, author, url)
            # Empty placeholders must not suppress the density-based fallback.
            if speech_text(section.get_text('', strip=True)).strip():
                pieces.append(plain_text(section))
            elif section is not scope:
                section.decompose()
        selected = ' '.join(filter(None, pieces))
        if selected:
            return selected

    # Density-based extraction handles unmarked layouts and separates article
    # prose from metadata, related stories, controls and comments.
    # Links and attribution classes inside an editorial quotation describe its
    # source, not navigation. Normalize the cleaned quotation to narration text
    # before density pruning, retaining its position and the surrounding layout.
    preserve_reference_lists(scope, url)
    quotes = [node for node in scope.select('blockquote') if not node.find_parent('blockquote')]
    for quote in quotes:
        quote.string = plain_text(quote)
    # Empty inline diagram markers can make the density extractor discard
    # their following text. Unwrap them first, including nested empty spans.
    for span in reversed(scope.select('span')):
        if not span.contents:
            span.unwrap()
    # With images disabled, the extractor drops entire figures. Code figures
    # are text: keep their pre blocks in place without enabling image content.
    for figure in scope.select('figure:has(pre)'):
        figure.unwrap()
    from trafilatura import bare_extraction
    body = scope if scope is not soup else None
    source = str(body if body is not None else soup)
    if body is not None or soup.find('html') is None:
        source = '<html><body>' + source + '</body></html>'
    for precision in (True, False):
        document = bare_extraction(source, include_comments=False, include_tables=True,
                                   include_images=False, favor_precision=precision)
        # Read the extracted tree directly so layout tables don't turn into
        # spoken Markdown pipes and separators.
        if document is not None and document.body is not None:
            text = ' '.join(' '.join(document.body.itertext()).split())
            if readable_prose(text):
                return text
    # Preserve short semantic articles when the density heuristic declines them.
    if body is not None and body.find(['p', 'blockquote']) is not None:
        return plain_text(body)
    return ''
