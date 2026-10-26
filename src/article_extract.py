"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re
from html import unescape
from soupsieve import match
from article_scope import BODY_SELECTORS, DATE, article_scope, editorial, explicitly_hidden, heading_matches, heading_text, readable_prose
from tts import speech_text


EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
    '[role~="doc-noteref"], [role~="doc-backlink"], a.footnote-ref, a.footnote-backref, '
    'a.reversefootnote, a[rel~="footnote"], a[rel~="footnote-backref"], sup a[href^="#fn"], '
    '.post-header, .post-footer, .post-meta, .post-metadata, .share-buttons, '
    '.byline, [data-block="byline"], [data-testid="multi-byline"], '
    '[itemprop="datePublished"], [itemprop="dateModified"], [data-testid="timestamp"], '
    '.subscription-widget, .entryFooter, .mobile-date-eyebrow, .edit-page-link, '
    '.posted, .publish-date-author, .basic-hero--blog-detail__description, '
    '.author-bio, .post-author, .post-categories, .related-posts, .related-articles, '
    '.comments, #comments, #Sidebar, #Footer, .linkedlist .smallprint, '
    '.gh-post-upgrade-cta, .gh-post-upgrade-cta-content, .post-access-cta, '
    '.j-icon, .sharedaddy, .translate-post, #jp-relatedposts, .harvard-sharing, '
    '.article-cta-box, .collection-cta, .collection-dateline, [class*="AscendiumAdUnit_wrapper__"], '
    '.wp-block-image, .wp-caption, .wp-block-video, .caption, '
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
        if not (translation or byline or history):
            break
        paragraph.decompose()


def clean_tree(root, title, author):
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
        if (heading.get_text(' ', strip=True).casefold() == 'written by' and
                heading.parent is not root and len(heading.parent.get_text(' ', strip=True)) < 600):
            heading.parent.decompose()
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
    for node in root.select(EXCLUDED):
        if node.parent is not None:
            node.decompose()
    # Attribute the article once, outside its narration body.
    for node in root.select('h1, h2, h3, dt, [rel~="author"], [itemprop~="author"]'):
        value = heading_text(node) if node.name in ('h1', 'h2', 'h3') else ' '.join(node.get_text(' ', strip=True).split())
        if ((title and heading_matches(value[:160].strip(), title)) or
                (author and re.sub(r'^by\s+', '', value, flags=re.I)[:100].strip() == author)):
            node.decompose()
    for tags in list(root.select('.post-tags')):
        parent = tags.parent
        heading = parent.find(['h2', 'h3']) if parent else None
        if heading and heading.get_text(' ', strip=True).rstrip(':').casefold() == 'tags':
            parent.decompose()
        else:
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


def extract_structured_text(body, title='', author=''):
    """Normalize an already-selected JSON-LD body; never execute or fetch it."""
    from bs4 import BeautifulSoup
    # Preserve plain-text comparisons and code such as C++'s <vector>.
    if not re.search(r'</?(?:p|div|section|article|h[1-6]|br|ul|ol|li|blockquote|pre|table|thead|tbody|tfoot|tr|th|td|caption|dl|dt|dd|a|em|strong|span|script|style)\b[^>]*>', body, re.I):
        return ' '.join(unescape(body).split())
    fragment = BeautifulSoup(body, 'html.parser')
    clean_tree(fragment, title, author)
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
    deferred = None
    for node in sections:
        node.extract()
        clean_tree(node, title, author)
        if speech_text(node.get_text('', strip=True)).strip():
            deferred = node
            break
    # Select before cleanup removes the headline used to identify the article.
    for node in list(soup.select('article, .recommendations, .related-posts, .related-articles')):
        if node.parent is not None and (not editorial(node) or
                (node is not scope and not any(parent is node for parent in scope.parents)
                 and node.name == 'article' and (scope.name in ('article', 'main') or scope.get('role') == 'main'))):
            node.decompose()
    clean_tree(soup, title, author)
    if deferred is not None:
        return plain_text(deferred)
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
            clean_tree(section, title, author)
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
