#!/usr/bin/env python3
"""Fetch current-affairs RSS items and write a public JSON feed for GN Career Path Academy."""
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FEEDS = [
    ("India current affairs government", "en", "National"),
    ("Maharashtra government news", "en", "Maharashtra"),
    ("महाराष्ट्र शासन बातम्या योजना", "mr", "Maharashtra"),
    ("India economy RBI budget", "en", "Economy"),
    ("India science technology ISRO", "en", "Science & Technology"),
    ("India sports", "en", "Sports"),
    ("India education recruitment examination", "en", "Education & Exams"),
]
OUTPUT = Path("data/current_affairs.json")
MAX_PER_FEED = 25
MAX_TOTAL = 150


def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", value, flags=re.S)
    value = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def category_for(title, summary, fallback):
    text = (title + " " + summary).lower()
    rules = [
        (r"maharashtra|महाराष्ट्र|मुंबई|पुणे|नागपूर|नाशिक|मंत्रिमंडळ|राज्य शासन", "Maharashtra"),
        (r"cricket|football|hockey|olympic|sports|क्रीडा|विश्वचषक|ipl\b", "Sports"),
        (r"rbi|reserve bank|inflation|gdp|economy|economic|budget|repo rate|अर्थव्यवस्था|महागाई|अर्थसंकल्प", "Economy"),
        (r"isro|science|technology|space mission|artificial intelligence|चांद्रयान|विज्ञान|तंत्रज्ञान", "Science & Technology"),
        (r"scheme|yojana|government launches|cabinet approves|सरकारी योजना|योजना|शासन निर्णय", "Government & Schemes"),
        (r"school|university|education|exam|recruitment|vacancy|भरती|शिक्षण|परीक्षा|नियुक्ती", "Education & Exams"),
        (r"world|international|united nations|un security council|global summit|जागतिक|आंतरराष्ट्रीय", "International"),
    ]
    for pattern, category in rules:
        if re.search(pattern, text):
            return category
    return fallback or "National"


def fetch_feed(query, language, fallback):
    params = {
        "q": query,
        "hl": "mr-IN" if language == "mr" else "en-IN",
        "gl": "IN",
        "ceid": "IN:mr" if language == "mr" else "IN:en",
    }
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": "GN-Career-Path-Academy/1.0 (RSS reader)"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        xml_data = response.read()
    root = ET.fromstring(xml_data)
    articles = []
    for item in root.findall(".//item")[:MAX_PER_FEED]:
        title = clean(item.findtext("title"))
        summary = clean(item.findtext("description"))[:600]
        link = clean(item.findtext("link"))
        source_node = item.find("source")
        source = clean(source_node.text if source_node is not None else "") or "Google News"
        date_text = clean(item.findtext("pubDate"))
        try:
            from email.utils import parsedate_to_datetime
            published = parsedate_to_datetime(date_text).astimezone(timezone.utc).isoformat()
        except Exception:
            published = datetime.now(timezone.utc).isoformat()
        if title and link.startswith(("https://", "http://")):
            articles.append({
                "title": title,
                "summary": summary,
                "url": link,
                "source": source,
                "language": language,
                "category": category_for(title, summary, fallback),
                "publishedAt": published,
                "published": True,
            })
    return articles


def main():
    by_url = {}
    failures = []
    for query, language, fallback in FEEDS:
        try:
            for article in fetch_feed(query, language, fallback):
                by_url.setdefault(article["url"], article)
        except Exception as error:
            failures.append(f"{query}: {error}")
            print(f"WARNING: RSS feed failed ({query}): {error}")
    if not by_url:
        raise RuntimeError("All RSS feeds failed or returned no usable articles. " + "; ".join(failures))

    articles = sorted(
        by_url.values(),
        key=lambda item: item["publishedAt"],
        reverse=True,
    )[:MAX_TOTAL]
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(articles)} articles to {OUTPUT}")


if __name__ == "__main__":
    main()
