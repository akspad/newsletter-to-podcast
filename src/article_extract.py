"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re


BODY_SELECTORS = (
    '[itemprop~="articleBody"], .entry-content, .post-content, .post__content, '
    '.available-content .body.markup, .body.markup, [data-gu-name="body"], .entry.entryPage'
)
EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
    '.post-header, .post-footer, .post-meta, .post-metadata, .share-buttons, '
    '.byline, [data-block="byline"], [data-testid="multi-byline"], '
    '[itemprop="datePublished"], [itemprop="dateModified"], [data-testid="timestamp"], '
    '.subscription-widget, .entryFooter, .mobile-date-eyebrow, .edit-page-link, '
    '.wp-block-image, .wp-caption, .wp-block-video, .caption, '
    'figure:has(img), figure:has(video), figure:has(audio)'
)
MONTH = (r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
         r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)')
DATE = re.compile(
    rf'(?:{MONTH}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}|'
    rf'\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})', re.I)


def clean_tree(root, title, author):
    for node in root.select(EXCLUDED):
        if node.parent is not None:
            node.decompose()
    # Attribute the article once, outside its narration body.
    for node in root.select('h1, [rel~="author"], [itemprop="author"]'):
        value = ' '.join(node.get_text(' ', strip=True).split())
        if ((title and value[:160].strip() == title) or
                (author and re.sub(r'^by\s+', '', value, flags=re.I)[:100].strip() == author)):
            node.decompose()
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


def plain_text(root):
    # Add separators around blocks, without inserting spaces inside inline words
    # (for example, a drop cap's <span>A</span>s or an emphasized word ending).
    for node in root.find_all(['p', 'div', 'section', 'blockquote', 'li', 'h1', 'h2',
                               'h3', 'h4', 'h5', 'h6', 'pre', 'tr', 'br']):
        node.insert_before('\n')
        node.insert_after('\n')
    return ' '.join(root.get_text('', strip=False).split())


def extract_text(soup, title='', author=''):
    # LessWrong streams its explicit post body inside an initially hidden React
    # container. Detach only that body before discarding hidden page sections.
    deferred = soup.select_one('.PostsPage-postContent')
    if deferred is not None:
        deferred.extract()
    clean_tree(soup, title, author)
    explicit = deferred or soup.select_one(BODY_SELECTORS)
    if explicit is not None:
        clean_tree(explicit, title, author)
        return plain_text(explicit)

    # Density-based extraction handles unmarked layouts and separates article
    # prose from metadata, related stories, controls and comments.
    from trafilatura import bare_extraction
    body = soup.select_one('article') or soup.select_one('main')
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
            if len(text.split()) >= 20:
                return text
    # Preserve short semantic articles when the density heuristic declines them.
    if body is not None and body.find(['p', 'blockquote']) is not None:
        return plain_text(body)
    return ''
