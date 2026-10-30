"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re
from html import unescape
from urllib.parse import unquote, urlsplit
from soupsieve import match
from article_scope import BODY_SELECTORS, DATE, FOOTNOTE_NAV, article_scope, editorial, explicitly_hidden, heading_matches, heading_text, readable_prose, url_identity
from tts import speech_text


EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
    f'{FOOTNOTE_NAV}, '
    '.post-header, .post-footer, .post-meta, .post-metadata, .post-actions, .share-buttons, '
    '.byline, [data-block="byline"], [data-testid="multi-byline"], '
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


def remove_table_of_contents(root, url):
    """Remove marked section indexes, keeping their destination prose intact."""
    contents = list(root.select('.toc, #toc, .table-of-contents, #table-of-contents'))
    if not contents:
        return
    targets = {}
    for node in root.select('[id], a[name]'):
        for label in (node.get('id'), node.get('name') if node.name == 'a' else None):
            if label:
                targets.setdefault(label, []).append(node)
    requested = url_identity(url)
    for toc in contents:
        if toc.parent is None or toc.find_parent(['blockquote', 'pre', 'code']):
            continue

        def section_link(link):
            href = link.get('href', '').strip()
            try:
                fragment = unquote(urlsplit(href).fragment)
            except ValueError:
                return False
            if not fragment or not (href.startswith('#') or
                                    requested and url_identity(href, url) == requested):
                return False
            # A class on a wrapper containing the article itself is not an
            # instruction to discard that wrapper and all its destination text.
            return any(node.parent is not None and node is not toc and
                       not any(parent is toc for parent in node.parents)
                       for node in targets.get(fragment, []))

        links = toc.select('a[href]')
        if not links or not all(section_link(link) for link in links):
            continue
        heading = toc.find_previous_sibling()
        if heading is not None and heading.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            label = heading.get_text(' ', strip=True).rstrip(':').casefold().replace('\u2019', "'")
            if ('toch1' in heading.get('class', []) or
                    label in ('contents', 'table of contents', 'on this page', "today's links")):
                heading.decompose()
        toc.decompose()


def clean_tree(root, title, author, url=''):
    remove_site_endmatter(root)
    remove_press_contacts(root)
    for node in root.select('[style], [hidden], [aria-hidden]'):
        if node.parent is not None and explicitly_hidden(node):
            node.decompose()
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
        credit = re.match(r'^Lead Image:', value, re.I) and paragraph.find('em') and len(value) < 300
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
    for credit in root.select('.c-article-author, .c-article__author'):
        if credit.parent is not None and not credit.find_parent(['blockquote', 'pre', 'code']):
            credit.decompose()
    for node in root.select(EXCLUDED):
        if node.parent is not None:
            node.decompose()
    remove_table_of_contents(root, url)
    # Attribute the article once, outside its narration body.
    for node in root.select('h1, h2, h3, dt, [rel~="author"], [itemprop~="author"]'):
        value = heading_text(node) if node.name in ('h1', 'h2', 'h3') else ' '.join(node.get_text(' ', strip=True).split())
        if ((title and heading_matches(value[:160].strip(), title)) or
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


def extract_text(soup, title='', author='', url=''):
    scope = article_scope(soup, title, url)
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
    if match(BODY_SELECTORS, scope):
        candidates = [scope]
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
