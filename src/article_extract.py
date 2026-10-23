"""Find narration text in already-downloaded HTML; never fetch extra resources."""
import re
from soupsieve import match
from article_scope import BODY_SELECTORS, article_scope, editorial, explicitly_hidden


EXCLUDED = (
    'script, style, noscript, template, nav, header, footer, aside, form, '
    'button, input, select, textarea, svg, video, audio, figcaption, '
    '[hidden], [aria-hidden="true"], [role="button"], [role="navigation"], '
    '[role="complementary"], [role="dialog"], .visually-hidden, .sr-only, '
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
MONTH = (r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
         r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)')
DATE = re.compile(
    rf'(?:{MONTH}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}|'
    rf'\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})', re.I)


def clean_tree(root, title, author):
    for node in root.select('[style], [hidden], [aria-hidden]'):
        if node.parent is not None and explicitly_hidden(node):
            node.decompose()
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
    for node in root.select('h1, h2, h3, dt, [rel~="author"], [itemprop="author"]'):
        value = ' '.join(node.get_text(' ', strip=True).split())
        if ((title and value[:160].strip() == title) or
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


def plain_text(root):
    # Add separators around blocks, without inserting spaces inside inline words
    # (for example, a drop cap's <span>A</span>s or an emphasized word ending).
    for node in root.find_all(['p', 'div', 'section', 'blockquote', 'li', 'h1', 'h2',
                               'h3', 'h4', 'h5', 'h6', 'pre', 'tr', 'br']):
        node.insert_before('\n')
        node.insert_after('\n')
    return ' '.join(root.get_text('', strip=False).split())


def extract_text(soup, title='', author='', url=''):
    # LessWrong streams its explicit post body inside an initially hidden React
    # container. Detach only that body before discarding hidden page sections.
    deferred = soup.select_one('.PostsPage-postContent')
    if deferred is not None:
        deferred.extract()
    scope = article_scope(soup, title, url)
    # Select before cleanup removes the headline used to identify the article.
    for node in list(soup.select('article, .recommendations, .related-posts, .related-articles')):
        if node.parent is not None and (not editorial(node) or
                (node is not scope and not any(parent is node for parent in scope.parents)
                 and node.name == 'article' and (scope.name in ('article', 'main') or scope.get('role') == 'main'))):
            node.decompose()
    clean_tree(soup, title, author)
    if deferred is not None:
        clean_tree(deferred, title, author)
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
            pieces.append(plain_text(section))
        return ' '.join(filter(None, pieces))

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
            if len(text.split()) >= 20:
                return text
    # Preserve short semantic articles when the density heuristic declines them.
    if body is not None and body.find(['p', 'blockquote']) is not None:
        return plain_text(body)
    return ''
