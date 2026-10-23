"""Choose one article consistently for attribution and narration, without I/O."""
import re
from urllib.parse import urljoin, urlsplit


def editorial(node):
    for parent in (node, *node.parents):
        if not hasattr(parent, 'attrs'):
            continue
        classes = set(parent.get('class', []))
        if (parent.has_attr('hidden') or parent.get('aria-hidden') == 'true' or
                parent.name in ('nav', 'aside', 'footer') or
                classes & {'related-posts', 'related-articles', 'recommendations', 'comments', 'author-bio'}):
            return False
    return True


def heading_matches(value, title):
    normalize = lambda text: ' '.join(re.sub(r'[*_`]', '', text).casefold().split())
    value, title = normalize(value), normalize(title)
    return bool(value and title) and (value == title or
           any(title.startswith(value + sep) for sep in (' | ', ' - ', ' — ', ' – ')))


def article_scope(soup, title='', url=''):
    articles = [node for node in soup.select('article') if editorial(node)]
    mains = [node for node in soup.select('main, [role="main"]') if editorial(node)]

    def same_url(value):
        if not url or not isinstance(value, str) or value.startswith('#'):
            return False
        try:
            target, requested = urlsplit(urljoin(url, value)), urlsplit(url)
            return ((target.scheme, target.netloc, target.path.rstrip('/'), target.query) ==
                    (requested.scheme, requested.netloc, requested.path.rstrip('/'), requested.query))
        except ValueError:
            return False

    def score(node):
        headings = [h for h in node.select('h1, h2, .entry-title') if editorial(h)]
        linked = any(same_url(node.get(key)) for key in ('itemid', 'data-url')) or any(
            same_url(link.get('href')) for h in headings for link in h.select('a[href]'))
        matched = any(heading_matches(h.get_text(' ', strip=True), title) for h in headings)
        in_main = node.name == 'main' or node.get('role') == 'main' or node.find_parent(['main']) is not None
        prose = sum(len(p.get_text(' ', strip=True)) for p in node.select('p') if editorial(p))
        return linked, matched, in_main, prose

    # Main may contain recommendation <article>s beside an unmarked main story.
    # A heading outside those cards is evidence to keep the wider main scope.
    for main in mains:
        own_prose = [p for p in main.select('p') if not p.find_parent('article') and editorial(p)]
        matched = any(heading_matches(h.get_text(' ', strip=True), title) and not h.find_parent('article')
                      for h in main.select('h1') if editorial(h))
        if own_prose and (matched or not main.select('article') and
                          not any(any(score(node)[:2]) for node in articles)):
            return main
    if articles:
        return max(articles, key=score)
    return max(mains, key=score) if mains else soup


def belongs_to_scope(node, scope):
    """Allow external bylines, but never borrow from a different article/card."""
    if not editorial(node):
        return False
    owner = node.find_parent('article')
    return owner is None or owner is scope
