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
        # Some RSS publishers include a thumbnail. Keep it when present; the app
        # uses a category-themed image when a feed has no thumbnail.
        image_url = ""
        for image_node in item.findall(".//{http://search.yahoo.com/mrss/}thumbnail") + item.findall(".//{http://search.yahoo.com/mrss/}content") + item.findall("enclosure"):
            candidate_image = (image_node.attrib.get("url") or "").strip()
            if candidate_image.startswith(("https://", "http://")):
                image_url = candidate_image
                break
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
                "imageUrl": image_url,
                "source": source,
                "language": language,
                "category": category_for(title, summary, fallback),
                "publishedAt": published,
                "published": True,
            })
    return articles


def fetch_article_details(url, browser_page=None):
    """Resolve Google News redirects, then extract publisher metadata when accessible."""
    details = {"imageUrl": "", "content": ""}
    page = ""
    article_url = url

    # Google News RSS links often return a Google News shell to plain HTTP clients.
    # Use one shared Playwright page in Actions to resolve the link to the publisher.
    if browser_page is not None:
        try:
            browser_page.goto(url, wait_until="domcontentloaded", timeout=12000)
            browser_page.wait_for_timeout(800)
            article_url = browser_page.url
            page = browser_page.content()
        except Exception:
            page = ""
    if not page or "news.google.com" in urllib.parse.urlparse(article_url).netloc:
        request = urllib.request.Request(
            article_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; GN-Career-Path-Academy/1.0)", "Accept": "text/html"}
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                final_url = response.geturl()
                if final_url:
                    article_url = final_url
                if "text/html" not in response.headers.get("Content-Type", "").lower():
                    return details
                page = response.read(1_500_000).decode("utf-8", errors="replace")
        except Exception:
            return details

    # Never publish generic Google News branding/description as the article's photo or text.
    if "news.google.com" in urllib.parse.urlparse(article_url).netloc:
        return details

    # Prefer publisher's Open Graph/Twitter lead image.
    image_patterns = [
        r"""<meta[^>]+(?:property|name)=["']og:image["'][^>]+content=["']([^"']+)""",
        r"""<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']og:image["']""",
        r"""<meta[^>]+(?:property|name)=["']twitter:image(?::src)?["'][^>]+content=["']([^"']+)""",
    ]
    for pattern in image_patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            candidate = html.unescape(match.group(1).strip())
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            if candidate.startswith(("https://", "http://")):
                details["imageUrl"] = candidate
                break

    # Use articleBody only when the publisher exposes it in structured metadata.
    body_match = re.search(r"""["']articleBody["']\s*:\s*("(?:\\.|[^"\\])*")""", page, flags=re.I)
    if body_match:
        try:
            body = json.loads(body_match.group(1))
            body = clean(body)
            if len(body) >= 250:
                details["content"] = body[:12000]
        except Exception:
            pass

    if not details["content"]:
        description_patterns = [
            r"""<meta[^>]+(?:property|name)=["']og:description["'][^>]+content=["']([^"']+)""",
            r"""<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)""",
        ]
        for pattern in description_patterns:
            match = re.search(pattern, page, flags=re.I)
            if match:
                candidate = clean(match.group(1))
                generic_descriptions = (
                    "comprehensive up-to-date news coverage",
                    "google news",
                    "read more",
                    "latest news",
                )
                if len(candidate) >= 120 and not any(
                    marker in candidate.lower() for marker in generic_descriptions
                ):
                    details["content"] = candidate[:2000]
                    break
    # Avoid generic/reused Google-hosted thumbnails masquerading as article images.
    if details["imageUrl"] and "lh3.googleusercontent.com" in details["imageUrl"]:
        if re.search(r"(?:=s0-w\d+|=w\d+-h\d+|^)$", details["imageUrl"]):
            details["imageUrl"] = ""
    return details


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

    # Resolve Google News redirect links and enrich the newest 60 stories using
    # one browser instance. Publisher pages may block automated access; those
    # stories keep an empty image/content rather than incorrect Google branding.
    browser = None
    browser_page = None
    try:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        browser_page = browser.new_page(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36")
    except Exception as error:
        print(f"WARNING: Playwright unavailable; article enrichment will use direct HTTP only: {error}")

    try:
        for article in articles[:60]:
            details = fetch_article_details(article["url"], browser_page=browser_page)
            if details.get("imageUrl"):
                article["imageUrl"] = details["imageUrl"]
            if details.get("content"):
                article["content"] = details["content"]
            print(f"Enriched: image={bool(article.get('imageUrl'))}, content={bool(article.get('content'))}, title={article['title'][:70]}")
    finally:
        if browser is not None:
            browser.close()
            playwright.stop()

    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(articles)} articles to {OUTPUT}")


if __name__ == "__main__":
    main()
