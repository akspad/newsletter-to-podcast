"""Choose one article consistently for attribution and narration, without I/O."""
import re
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit
from bs4 import Comment


BODY_SELECTORS = (
    '[itemprop~="articleBody"], .entry-content, .post-content, .post__content, '
    '.available-content .body.markup, .body.markup, [data-gu-name="body"], .entry.entryPage, #story_text, '
    'topcomment > article.comment > pre'
)
STRONG_TOWNS_HOSTS = {'strongtowns.org', 'www.strongtowns.org'}
FOOTNOTE_NAV = (
    '[role~="doc-noteref"], [role~="doc-backlink"], a.footnote-ref, a.footnote-backref, '
    'a.reversefootnote, a.footnote-return, a[rel~="footnote"], a[rel~="footnote-backref"], '
    'sup a[href^="#fn"], a[aria-label^="Back to reference " i][href^="#"], '
    'a.ref[href^="#note-"]:has(sup)'
)
MONTH = (r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
         r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)')
DATE = re.compile(
    rf'(?:{MONTH}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}|'
    rf'\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})', re.I)


def readable_prose(text):
    """Recognize substantial prose in spaced and unspaced writing systems."""
    return len(text.split()) >= 20 or len(re.findall(
        r'[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text)) >= 100


def opening_writer_credits(root):
    """Read a publication's explicit opening writer label, never quoted prose."""
    for body in root.select('.single-content'):
        if not editorial(body) or body.find_parent(['blockquote', 'pre', 'code']):
            continue
        paragraph = body.find('p', recursive=False)
        if (paragraph is None or not editorial(paragraph) or
                paragraph.find_parent(['blockquote', 'pre', 'code'])):
            continue
        value = paragraph.get_text(' ', strip=True)
        match = re.fullmatch(r'This blog was written and prepared by PLOS editor ([^\d.!?:;\n]{2,100})\.?', value)
        if match:
            yield paragraph, match[1].strip()


def url_identity(value, base=''):
    """Ignore known tracking fields, retaining query parameters that select content."""
    if not isinstance(value, str) or not value or value.startswith('#'):
        return None
    try:
        parsed = urlsplit(urljoin(base, value))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        query = tuple((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                      if not key.casefold().startswith('utm_') and key.casefold() not in
                      {'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid'})
        return parsed.scheme, parsed.netloc.casefold(), parsed.path.rstrip('/'), query
    except ValueError:
        return None


def plover_story_title(soup, url):
    """Find the story heading selected by a Plover permalink or archive fragment."""
    identity = url_identity(url)
    if not identity or identity[1] != 'blog.plover.com':
        return None
    fragment = unquote(urlsplit(url).fragment)
    for link in soup.select('.mainsection > p > a.storytitle[href]'):
        matched = (link.get('name') == fragment if fragment else url_identity(link['href'], url) == identity)
        section = link.parent.parent
        if matched and editorial(link) and len(section.select(':scope > p > a.storytitle')) == 1:
            return link
    return None


def remove_resolved_footnote_backlinks(root, url=''):
    """Remove unmarked return controls only after verifying both footnote links."""
    identity = url_identity(url)
    # Keep context-free imports (including anonymous feed identity material)
    # unchanged. The supplied page URL also anchors relative/absolute links.
    if not identity:
        return
    def fragment(href):
        if not isinstance(href, str):
            return ''
        try:
            parsed = urlsplit(href)
        except ValueError:
            return ''
        if not href.startswith('#') and (not identity or url_identity(href, url) != identity):
            return ''
        return unquote(parsed.fragment)

    identities = {}
    for node in root.select('[id]'):
        if editorial(node):
            identities.setdefault(node['id'], []).append(node)
    for link in list(root.find_all('a', href=True)):
        if (link.get_text('', strip=True).rstrip('\ufe0e\ufe0f') != '↩' or not editorial(link) or
                link.find_parent(['blockquote', 'pre', 'code'])):
            continue
        note = next((node for node in link.parents if getattr(node, 'attrs', None) and node.get('id') and
                     ('doc-endnote' in node.get('role', '').split() or
                      node.name == 'li' and node.find_parent(class_='footnotes'))), None)
        destination = fragment(link['href'])
        targets = identities.get(destination, [])
        if (note is None or not destination or len(targets) != 1 or
                len(identities.get(note['id'], [])) != 1):
            continue
        reference = targets[0]
        if (not editorial(reference) or reference.find_parent(['blockquote', 'pre', 'code']) or
                reference.find_parent('article') is not note.find_parent('article') or
                not (reference.name == 'sup' and 'footnote-reference' in reference.get('class', []) or
                     'doc-noteref' in reference.get('role', '').split())):
            continue
        forwards = [reference] if reference.name == 'a' else reference.find_all('a', href=True)
        if any(fragment(forward.get('href')) == note['id'] for forward in forwards):
            link.decompose()


def explicitly_hidden(node):
    if node.has_attr('hidden') or node.get('aria-hidden', '').casefold() == 'true':
        return True
    # Evaluate literal inline display declarations, including precedence. Do not
    # infer visibility from class names or fetch stylesheets / execute scripts.
    style = node.get('style', '')
    if not style:
        return False
    style = re.sub(r'/\*.*?\*/', '', style, flags=re.S)
    display, important = '', False
    for declaration in re.finditer(r'(?:^|;)\s*display\s*:\s*([^;]+)', style, re.I):
        value = declaration[1].strip().casefold()
        priority = bool(re.search(r'!\s*important\s*$', value))
        if priority or not important:
            display = re.sub(r'!\s*important\s*$', '', value).strip()
            important = priority
    return display == 'none'


def editorial(node, *, allow_hidden=False):
    for parent in (node, *node.parents):
        if not hasattr(parent, 'attrs'):
            continue
        classes = set(parent.get('class', []))
        if (not allow_hidden and explicitly_hidden(parent) or
                parent.name in ('nav', 'aside', 'footer') or
                classes & {'related-posts', 'related-articles', 'recommendations', 'comments', 'Comment-body', 'author-bio'}):
            return False
    return True


def heading_text(node):
    """Read a headline without nested dates, bylines or print-only metadata."""
    ignored = {id(child) for child in node.select(
        'time, .byline, .post-meta, .post-metadata, .whenprint, .when, devsite-actions, '
        '[itemprop~="datePublished"], [itemprop~="dateModified"]')}
    return ' '.join(' '.join(str(text) for text in node.strings
                            if not any(id(parent) in ignored for parent in text.parents)).split())


def heading_matches(value, title):
    normalize = lambda text: ' '.join(re.sub(r'[*_`]', '', text).casefold().split())
    value, title = normalize(value), normalize(title)
    return bool(value and title) and (value == title or
           any(title.startswith(value + sep) for sep in (' | ', ' - ', ' — ', ' – ')) or
           title.endswith(': ' + value))


def article_labels(root, title):
    """Recognize a labeled article masthead, not ordinary definition lists."""
    for block in root.select('dl.macrodata'):
        if block.parent is None or not editorial(block) or block.find_parent(['blockquote', 'pre', 'code']):
            continue
        fields = {}
        for label in block.find_all('dt'):
            value = label.find_next_sibling('dd')
            if value is not None and editorial(label) and editorial(value):
                fields[label.get_text(' ', strip=True).casefold()] = value
        if (fields.keys() <= {'title', 'author', 'dated'} and 'title' in fields and
                heading_matches(heading_text(fields['title']), title)):
            yield block, fields


def masthead_body(soup, title):
    """Recognize a static blog's body only beside its matching article masthead."""
    if not title:
        return None
    candidates = []
    for body in soup.select('div.container.main'):
        if (not editorial(body) or body.find_parent(['article', 'blockquote', 'pre', 'code']) or
                not readable_prose(' '.join(p.get_text(' ', strip=True) for p in
                                           body.find_all('p', recursive=False) if editorial(p)))):
            continue
        # This layout has flat prose blocks. An unknown nested container may
        # be a sidebar or another story; leave that ambiguity to density pruning.
        if (any(editorial(node) for node in body.find_all(['div', 'section', 'main'], recursive=False)) or
                not any(editorial(h) for h in body.find_all(['h2', 'h3', 'h4', 'h5', 'h6'], recursive=False))):
            continue
        # Empty edit links / line breaks may separate the masthead and body.
        # A content-bearing sibling is a boundary; never reach across another
        # story, recommendation card or prose to borrow a matching headline.
        previous = body.previous_sibling
        while previous is not None:
            if getattr(previous, 'name', None):
                if (previous.name not in ('a', 'br') or previous.get_text(' ', strip=True) or
                        previous.find(['img', 'svg'])):
                    break
            elif str(previous).strip() and not isinstance(previous, Comment):
                break
            previous = previous.previous_sibling
        if (previous is None or not getattr(previous, 'attrs', None) or
                previous.name != 'div' or not {'container', 'blog-title'} <= set(previous.get('class', [])) or
                not editorial(previous)):
            continue
        headings = [h for h in previous.select('h1') if editorial(h) and
                    not h.find_parent(['blockquote', 'pre', 'code'])]
        labels = previous.select('.blog-meta-author, .blog-meta-date')
        if (len(headings) == 1 and heading_matches(heading_text(headings[0]), title) and
                any(editorial(label) and not label.find_parent(['blockquote', 'pre', 'code']) and
                    label.get_text(' ', strip=True) for label in labels)):
            candidates.append(body)
    return candidates[0] if len(candidates) == 1 else None


def article_scope(soup, title='', url=''):
    articles = [node for node in soup.select('article') if editorial(node)]
    mains = [node for node in soup.select('main, [role="main"]') if editorial(node)]
    requested = url_identity(url)

    def same_url(value):
        return requested is not None and url_identity(value, url) == requested

    # Some short-link blogs use div.post instead of article. Require a
    # permalink in the post's own metadata or controls, not an arbitrary link
    # in its prose or a neighbouring post, before treating it as the story.
    posts = [node for node in soup.select('div.post, section.post')
             if editorial(node) and not node.find_parent(['blockquote', 'pre', 'code'])
             and node.find(['p', 'blockquote']) is not None
             and any(same_url(link.get('href')) for link in node.select(
                 ':scope > .post-meta a[href], :scope > .post-actions a[href]'))]
    post_ids = {id(node) for node in posts}

    def score(node):
        headings = [h for h in node.select('h1, h2, .entry-title') if editorial(h)]
        linked = id(node) in post_ids or any(same_url(node.get(key)) for key in ('itemid', 'data-url')) or any(
            same_url(link.get('href')) for h in headings for link in h.select('a[href]'))
        matched = any(heading_matches(heading_text(h), title) for h in headings)
        in_main = node.name == 'main' or node.get('role') == 'main' or node.find_parent(['main']) is not None
        prose = sum(len(p.get_text(' ', strip=True)) for p in node.select('p') if editorial(p))
        return linked, matched, in_main, prose

    # Lamer News layouts (including Antirez) put the permalink headline in
    # one article and its body in a topcomment. Require their shared news ID
    # and a matching permalink, rather than treating ordinary comments as posts.
    top_comments = {node.get('data-comment-id'): node for node in articles
                    if node.parent.name == 'topcomment' and 'comment' in node.get('class', [])}
    for node in articles:
        news_id = node.get('data-news-id')
        body = top_comments.get(f'{news_id}-') if news_id else None
        if body is not None and score(node)[0]:
            return body

    if posts:
        post = max(posts, key=score)
        if not articles or score(post)[:2] >= max(score(node)[:2] for node in articles):
            return post

    # Main may contain recommendation <article>s beside an unmarked main story.
    # A heading outside those cards is evidence to keep the wider main scope.
    for main in mains:
        main_score = score(main)
        # Longform pages can place a short headline hero in main and the full
        # article beside it. Prefer the matching, more substantial article,
        # while retaining a main story with stronger permalink evidence.
        if any(any(score(node)[:2]) and score(node)[:2] >= main_score[:2]
               and score(node)[3] > main_score[3]
               and not any(parent is main for parent in node.parents)
               and not any(parent is node for parent in main.parents)
               for node in articles):
            continue
        own_prose = [p for p in main.select('p') if not p.find_parent('article') and editorial(p)]
        matched = any(heading_matches(heading_text(h), title) and not h.find_parent('article')
                      for h in main.select('h1') if editorial(h))
        own_body = any(not node.find_parent('article') and editorial(node)
                       for node in main.select(BODY_SELECTORS))
        # A short deck outside a semantic article isn't the main story body.
        inside_prose = max((score(node)[3] for node in articles
                            if any(parent is main for parent in node.parents)), default=0)
        if not own_body and sum(len(p.get_text(' ', strip=True)) for p in own_prose) < inside_prose:
            continue
        if (own_prose or own_body) and (matched or not main.select('article') and
                                      not any(any(score(node)[:2]) for node in articles)):
            return main
    if not any(any(score(node)[:2]) for node in articles):
        recovered = masthead_body(soup, title)
        if recovered is not None:
            return recovered
    if articles:
        return max(articles, key=score)
    return max(mains, key=score) if mains else soup


def belongs_to_scope(node, scope):
    """Allow external bylines, but never borrow from a different article/card."""
    if not editorial(node):
        return False
    owner = node.find_parent('article')
    if owner is None and scope.name in ('div', 'section') and 'post' in scope.get('class', []):
        owner = node.find_parent(['div', 'section'], class_='post')
    return owner is None or owner is scope
