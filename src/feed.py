from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path


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
        episodes.append({"guid": guid, "rss_guid": rss_guid, "source_key": guid.split("-part-")[0],
                         "title": item.findtext("title") or "", "description": "",
                         "description_html": item.findtext("description") or "",
                         "link": item.findtext("link") or "",
                         "published": parsedate_to_datetime(item.findtext("pubDate")).isoformat(),
                         "file": Path(enclosure.get("url", "")).name, "enclosure_url": enclosure.get("url", ""),
                         "bytes": int(enclosure.get("length", "0")), "duration": seconds})
    return episodes


def html(text: str) -> str:
    """Plain text with one paragraph per line, as HTML show notes."""
    return "".join(f"<p>{escape(line)}</p>" for line in text.splitlines() if line.strip())


def build(site_url: str, episodes: list, title="Newsletter Podcast") -> str:
    items = []
    # GUIDs include the feed's address so apps that cache episodes by GUID (Castbox) pick up
    # fresh audio links if the feed ever moves, e.g. after a repo rename.
    for e in sorted(episodes, key=lambda e: e["published"], reverse=True):
        pub = format_datetime(datetime.fromisoformat(e["published"]).astimezone(timezone.utc))
        secs = int(e["duration"])
        rss_guid = e.get("rss_guid") or f"{site_url}/{e['guid']}"
        enclosure_url = e.get("enclosure_url") or f"{site_url}/episodes/{e['file']}"
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(e.get('description_html') or html(e['description']))}</description>
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
