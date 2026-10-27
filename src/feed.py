import os
import tempfile
import security
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit


def escape(text, entities=None):
    if not isinstance(text, str):
        raise ValueError("Feed text must be a string")
    # XML 1.0 excludes controls, surrogates and U+FFFE/U+FFFF.
    text = "".join(c for c in text if ord(c) in (9, 10, 13) or 0x20 <= ord(c) <= 0xD7FF
                   or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
    return xml_escape(text, entities or {})


def title(path):
    return ET.parse(path).getroot().findtext("channel/title") or "Newsletter Podcast"


def read(path):
    """Recover public episode metadata when no private processing state is available."""
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    episodes = []
    for item in ET.parse(path).getroot().findall("channel/item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        rss_guid = item.findtext("guid") or ""
        guid = rss_guid.rsplit("/", 1)[-1]
        raw = item.findtext("itunes:duration", "0", ns)
        seconds = 0
        for field in raw.split(":"):
            seconds = seconds * 60 + int(field)
        link = item.findtext("link") or ""
        # Recover the original notes so placeholder repairs still recognize them.
        notes = (item.findtext("description") or "").removeprefix(article_link(link))
        episodes.append({"guid": guid, "rss_guid": rss_guid, "source_key": guid.split("-part-")[0],
                         "title": item.findtext("title") or "", "description": "",
                         "description_html": notes,
                         "link": link,
                         "published": parsedate_to_datetime(item.findtext("pubDate")).isoformat(),
                         "file": Path(enclosure.get("url", "")).name, "enclosure_url": enclosure.get("url", ""),
                         "bytes": int(enclosure.get("length", "0")), "duration": seconds})
    return episodes


def html(text: str) -> str:
    """Plain text with one paragraph per line, as HTML show notes."""
    return "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())


def article_link(link: str) -> str:
    """A visible source link at the beginning of podcast show notes."""
    try:
        parsed = urlsplit(link)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return ""
    except ValueError:
        return ""
    href = escape(link, {'"': '&quot;'})
    return f'<p>Original article: <a href="{href}">{escape(link)}</a></p>'


def published_time(episode):
    value = datetime.fromisoformat(episode['published'].replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build(site_url: str, episodes: list, title="Newsletter Podcast") -> str:
    items = []
    # GUIDs include the feed's address so apps that cache episodes by GUID (Castbox) pick up
    # fresh audio links if the feed ever moves, e.g. after a repo rename.
    for e in sorted(episodes, key=published_time, reverse=True):
        pub = format_datetime(published_time(e))
        secs = int(e["duration"])
        rss_guid = e.get("rss_guid") or f"{site_url}/{e['guid']}"
        enclosure_url = e.get("enclosure_url") or f"{site_url}/episodes/{e['file']}"
        source = article_link(e["link"])
        notes = source + (e.get("description_html") or html(e["description"])).removeprefix(source)
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(notes)}</description>
      <link>{escape(e['link'])}</link>
      <guid isPermaLink="false">{escape(rss_guid)}</guid>
      <pubDate>{pub}</pubDate>
      <enclosure url="{escape(enclosure_url, {'"': '&quot;'})}" length="{e['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(site_url)}</link>
    <description>Spoken newsletter summaries and full article narrations.</description>
    <language>en-us</language>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""



def write(path, document):
    """Validate a bounded candidate before atomically replacing the last valid feed."""
    data = document.encode("utf-8")
    if len(data) > security.MAX_FEED_BYTES:
        raise security.BudgetExceeded("Generated feed exceeds the size limit")
    ET.fromstring(data)
    fd, temporary = tempfile.mkstemp(prefix=".feed-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
