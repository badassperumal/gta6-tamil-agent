"""TREND SCOUT — watches Google News, Reddit and (daily) YouTube for GTA 6 stories.
Scores every story, removes ones already covered, and flags breaking news."""
import hashlib
import re
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import requests

from .core import State, config, get_logger, mock, now

log = get_logger("scout")
UA = {"User-Agent": "Mozilla/5.0 (gta6-tamil-agent; +https://github.com)"}
HOT_WORDS = {
    "trailer": 3, "official": 2, "rockstar": 2, "update": 2, "online": 2, "release": 2, "patch": 2,
    "secret": 2, "easter egg": 3, "map": 2, "record": 2, "sales": 2, "dlc": 2, "pc": 2, "glitch": 1,
    "money": 1, "car": 1, "jason": 1, "lucia": 1, "leonida": 1, "vice city": 2, "launch": 2, "price": 1,
}


def _key(title: str) -> str:
    words = sorted(set(re.findall(r"[a-z0-9]{4,}", title.lower())) - {"grand", "theft", "auto", "rockstar"})
    return hashlib.md5(" ".join(words[:8]).encode()).hexdigest()[:12]


def _ts(entry):
    for f in ("published", "updated"):
        if entry.get(f):
            try:
                return parsedate_to_datetime(entry[f])
            except Exception:  # noqa: BLE001
                pass
    return now()


def google_news(q: str):
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(requests.get(url, headers=UA, timeout=30).content)
    for e in feed.entries[:25]:
        yield {"title": e.title, "link": e.link, "source": "google_news",
               "summary": re.sub("<[^>]+>", " ", e.get("summary", ""))[:400], "published": _ts(e).isoformat(), "pop": 1}


def reddit(sub: str):
    url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day"
    feed = feedparser.parse(requests.get(url, headers=UA, timeout=30).content)
    for i, e in enumerate(feed.entries[:15]):
        yield {"title": e.title, "link": e.link, "source": f"r/{sub}",
               "summary": re.sub("<[^>]+>", " ", e.get("summary", ""))[:400], "published": _ts(e).isoformat(),
               "pop": max(1, 6 - i // 3)}  # rank in "top today" ≈ popularity


def youtube_competitors(query: str):
    """Top recent videos for the niche query (costs 100 quota units — call once a day)."""
    from .core import Quota
    from .core.youtube import yt
    if not Quota.can_spend("search"):
        return []
    r = yt().search().list(part="snippet", q=query, type="video", order="viewCount", maxResults=25,
                           publishedAfter=(now() - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
                           relevanceLanguage="ta").execute()
    Quota.spend("search")
    return [{"title": i["snippet"]["title"], "channel": i["snippet"]["channelTitle"], "id": i["id"]["videoId"]}
            for i in r.get("items", [])]


def score(item: dict) -> float:
    t = item["title"].lower()
    s = item.get("pop", 1) + sum(w for k, w in HOT_WORDS.items() if k in t)
    age_h = (now() - __import__("datetime").datetime.fromisoformat(item["published"])).total_seconds() / 3600
    return round(s * (1.0 if age_h < 6 else 0.7 if age_h < 24 else 0.4), 2)


def run() -> dict:
    cfg = config()["trends"]
    if mock():
        from tests.mock_llm import mock_trends
        items = mock_trends()
    else:
        items = []
        for q in cfg["google_news_queries"]:
            try:
                items += list(google_news(q))
            except Exception as e:  # noqa: BLE001
                log.warning("google news '%s' failed: %s", q, e)
        for sub in cfg["reddit_subs"]:
            try:
                items += list(reddit(sub))
            except Exception as e:  # noqa: BLE001
                log.warning("reddit %s failed: %s", sub, e)

    covered = set(State.load("history", {"topic_keys": []}).get("topic_keys", []))
    clusters: dict[str, dict] = {}
    for it in items:
        if "gta" not in it["title"].lower() and "grand theft" not in it["title"].lower() and it["source"] == "google_news":
            continue
        k = _key(it["title"])
        c = clusters.setdefault(k, {"key": k, "title": it["title"], "items": [], "score": 0, "covered": k in covered})
        c["items"].append(it)
        c["score"] += score(it)
    ranked = sorted(clusters.values(), key=lambda c: c["score"], reverse=True)

    recent = [c for c in ranked if any(
        (now() - __import__("datetime").datetime.fromisoformat(i["published"])).total_seconds() < 3 * 3600 for i in c["items"])]
    breaking = [c for c in recent if len(c["items"]) >= cfg["breaking_threshold"] and not c["covered"]]

    out = {"updated": now().isoformat(), "stories": ranked[:40], "breaking": breaking[:3]}
    State.save("trends", out)
    log.info("scouted %d items → %d stories, %d breaking", len(items), len(ranked), len(breaking))
    return out
