from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape


def build(site_url: str, episodes: list, title="Newsletter Summaries") -> str:
    items = []
    for e in sorted(episodes, key=lambda e: e["published"], reverse=True):
        pub = format_datetime(datetime.fromisoformat(e["published"]).astimezone(timezone.utc))
        secs = int(e["duration"])
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <description>{escape(e['description'])}</description>
      <link>{escape(e['link'])}</link>
      <guid isPermaLink="false">{escape(e['guid'])}</guid>
      <pubDate>{pub}</pubDate>
      <enclosure url="{escape(site_url)}/episodes/{escape(e['file'])}" length="{e['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{secs // 60}:{secs % 60:02d}</itunes:duration>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(site_url)}</link>
    <description>Daily spoken summaries of long newsletter posts that have no audio.</description>
    <language>en-us</language>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""
