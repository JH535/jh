#!/usr/bin/env python3
"""Collect public AI trend and community signals for the daily magazine."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "ai-trend-jh-magazine/1.0 (daily public-source roundup)"
NOW = dt.datetime.now(dt.timezone.utc)
SINCE = int((NOW - dt.timedelta(hours=30)).timestamp())


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, application/atom+xml, application/rss+xml, text/xml"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def clean(value: str, limit: int = 500) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


items = []
errors = []


def add(item):
    title = clean(item.get("title", ""), 240)
    url = item.get("url", "")
    if title and url.startswith("http"):
        items.append({
            "source": item.get("source", ""),
            "kind": item.get("kind", "news"),
            "title": title,
            "url": url,
            "summary": clean(item.get("summary", ""), 700),
            "published": item.get("published", ""),
            "score": item.get("score"),
            "comments": item.get("comments"),
            "extra": clean(item.get("extra", ""), 240),
        })


# Hacker News: recent posts plus visible community reaction counts.
try:
    for query in ("AI", "LLM", "ChatGPT", "OpenAI"):
        endpoint = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode({
            "query": query, "tags": "story", "numericFilters": f"created_at_i>{SINCE}", "hitsPerPage": 12
        })
        data = json.loads(get(endpoint))
        for hit in data.get("hits", []):
            add({"source": "Hacker News", "kind": "community", "title": hit.get("title"),
                 "url": hit.get("url") or ("https://news.ycombinator.com/item?id=" + str(hit.get("objectID"))),
                 "summary": hit.get("story_text") or "", "published": hit.get("created_at"),
                 "score": hit.get("points"), "comments": hit.get("num_comments"),
                 "extra": "HN points/comments"})
except Exception as exc:
    errors.append("Hacker News: " + type(exc).__name__)

# Reddit public listing endpoints expose post scores and comment counts where accessible.
for subreddit in ("LocalLLaMA", "MachineLearning", "ChatGPT", "artificial"):
    try:
        endpoint = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit=20"
        data = json.loads(get(endpoint))
        for entry in data.get("data", {}).get("children", []):
            post = entry.get("data", {})
            created = int(post.get("created_utc", 0))
            if created < SINCE:
                continue
            add({"source": "Reddit r/" + subreddit, "kind": "community",
                 "title": post.get("title"), "url": "https://www.reddit.com" + post.get("permalink", ""),
                 "summary": post.get("selftext", ""), "published": dt.datetime.fromtimestamp(created, dt.timezone.utc).isoformat(),
                 "score": post.get("score"), "comments": post.get("num_comments"),
                 "extra": "Reddit score/comments"})
    except Exception as exc:
        errors.append(f"Reddit r/{subreddit}: " + type(exc).__name__)

# GitHub repositories: practical launch and developer-interest signals.
try:
    query = urllib.parse.quote("AI OR LLM pushed:>=" + (NOW - dt.timedelta(days=1)).date().isoformat())
    data = json.loads(get("https://api.github.com/search/repositories?q=" + query + "&sort=stars&order=desc&per_page=20"))
    for repo in data.get("items", []):
        add({"source": "GitHub", "kind": "developer community", "title": repo.get("full_name"),
             "url": repo.get("html_url"), "summary": repo.get("description", ""),
             "published": repo.get("pushed_at"), "score": repo.get("stargazers_count"),
             "comments": None, "extra": "total stars; recently pushed"})
except Exception as exc:
    errors.append("GitHub: " + type(exc).__name__)

# Public RSS search keeps Korean and international reporting in the candidate pool.
rss_queries = [
    ("Google News KR · AI", "AI 인공지능 생성형 AI"),
    ("Google News KR · 커뮤니티", "site:dcinside.com OR site:fmkorea.com AI ChatGPT"),
    ("Google News EN · AI", "artificial intelligence AI LLM"),
]
for source, query in rss_queries:
    try:
        lang, region, edition = ("en-US", "US", "US:en") if source.startswith("Google News EN") else ("ko", "KR", "KR:ko")
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": lang, "gl": region, "ceid": edition})
        root = ET.fromstring(get(url))
        for entry in root.findall(".//item")[:12]:
            add({"source": source, "kind": "news", "title": entry.findtext("title", ""),
                 "url": entry.findtext("link", ""), "summary": entry.findtext("description", ""),
                 "published": entry.findtext("pubDate", "")})
    except Exception as exc:
        errors.append(source + ": " + type(exc).__name__)

# Deduplicate by URL, prioritizing the richer candidate.
unique = {}
for item in items:
    key = item["url"].split("?")[0]
    if key not in unique or len(item["summary"]) > len(unique[key]["summary"]):
        unique[key] = item

print(json.dumps({
    "collected_at_utc": NOW.isoformat(),
    "window_hours": 30,
    "items": list(unique.values())[:100],
    "source_errors": errors,
}, ensure_ascii=False))
