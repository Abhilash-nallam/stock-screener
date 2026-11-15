"""Multi-source India + global news and exchange-filings ingestion.

Sources are headline/summary feeds, not a claim of crawling the whole web:
NSE RSS, BSE notices RSS, SEBI/RBI/PIB RSS, GDELT multilingual global news,
and Google News company queries. Every item keeps its source and timestamp.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import time
import urllib.parse

import feedparser
import requests

USER_AGENT = "IndiaStockRadar/2.0 (+https://github.com/Abhilash-nallam/stock-screener)"
TIMEOUT = 12
MAX_AGE_HOURS = 120

OFFICIAL_FEEDS = [
    ("NSE Announcements", "https://archives.nseindia.com/content/RSS/Online_announcements.xml", "exchange"),
    ("NSE Daily Buyback", "https://nsearchives.nseindia.com/content/RSS/Daily_Buyback.xml", "exchange"),
    ("NSE Shareholding Pattern", "https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml", "exchange"),
    ("NSE BRSR Filings", "https://nsearchives.nseindia.com/content/RSS/brsr.xml", "exchange"),
    ("NSE Circulars", "https://nsearchives.nseindia.com/content/RSS/Circulars.xml", "exchange"),
    ("BSE Corporate Announcements", "https://www.bseindia.com/data/xml/announcements.xml", "exchange"),
    ("SEBI", "https://www.sebi.gov.in/sebirss.xml", "regulator"),
    ("RBI Press Releases", "https://rbi.org.in/pressreleases_rss.xml", "regulator"),
    ("RBI Notifications", "https://rbi.org.in/notifications_rss.xml", "regulator"),
    ("PIB Government Releases", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1", "government"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "global"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "global"),
    ("BBC Asia", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", "global"),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "global"),
    ("CNBC Asia", "https://www.cnbc.com/id/19832390/device/rss/rss.html", "global"),
    ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "global"),
    ("The Guardian Business", "https://www.theguardian.com/us/business/rss", "global"),
]

POSITIVE = [
    "profit rises", "profit rose", "profit jumps", "profit surged", "profit beats",
    "revenue rises", "revenue growth", "sales growth", "record revenue", "beats estimates",
    "order win", "wins order", "new order", "work order", "contract win", "bags contract",
    "capacity expansion", "plant expansion", "commercial production", "guidance raised",
    "outlook raised", "dividend", "buyback", "bonus issue", "debt reduced", "debt repaid",
    "credit rating upgraded", "rating upgrade", "regulatory approval", "receives approval",
    "promoter buying", "stake increase", "fund raising", "strong results",
]
NEGATIVE = [
    "profit falls", "profit fell", "profit declines", "loss widens", "net loss",
    "revenue falls", "sales decline", "misses estimates", "guidance cut", "outlook cut",
    "order cancelled", "contract terminated", "payment default", "loan default",
    "insolvency", "bankruptcy", "fraud", "accounting irregularity", "forensic audit",
    "sebi penalty", "regulatory penalty", "tax demand", "search operation", "raid",
    "investigation", "probe", "trading suspended", "license cancelled", "credit downgrade",
    "rating downgraded", "pledge rises", "promoter pledge", "plant shutdown",
    "production halted", "resignation", "resigns", "recall", "ban imposed",
]
TAGS = {
    "results": ("quarterly results", "financial results", "profit", "revenue", "earnings", "ebitda"),
    "orders": ("order", "contract", "work order", "letter of award"),
    "corporate_actions": ("dividend", "buyback", "bonus", "split", "record date"),
    "regulatory": ("sebi", "rbi", "penalty", "circular", "regulatory", "compliance"),
    "macro": ("inflation", "interest rate", "repo rate", "federal reserve", "tariff", "gdp"),
    "commodities": ("crude", "oil price", "gold", "copper", "aluminium", "gas"),
    "geopolitics": ("war", "sanction", "conflict", "trade restriction", "ceasefire"),
    "technology": ("semiconductor", "artificial intelligence", "ai chip", "cloud", "cyber"),
}

GLOBAL_MARKET_TERMS = (
    "stock market", "stock markets", "share market", "equity market", "equity markets",
    "stocks", "shares", "equities", "bond", "bonds", "treasury", "yield", "yields",
    "central bank", "federal reserve", "bank of england", "bank of japan", "bank of korea",
    "interest rate", "interest rates", "rate cut", "rate hike", "monetary policy",
    "inflation", "deflation", "gdp", "gross domestic product", "economic growth",
    "economy", "economic outlook", "recession", "fiscal deficit", "government debt",
    "currency", "currencies", "forex", "foreign exchange", "rupee", "dollar",
    "tariff", "tariffs", "trade war", "trade deal", "trade agreement", "sanctions",
    "crude oil", "oil prices", "brent", "opec", "natural gas", "gold prices",
    "commodities", "commodity", "copper", "semiconductor", "semiconductors", "chipmaker",
    "earnings", "corporate profit", "company profits", "revenue", "default", "credit rating",
    "banking sector", "lender", "lenders", "financial sector", "financial markets",
    "ipo", "merger", "acquisition", "bankruptcy", "capital expenditure", "supply chain",
    "export", "exports", "import", "imports", "investment", "investor", "investors",
    "market regulator", "securities regulator", "sebi", "rbi", "fii", "fpi", "dii",
)
COMPANY_NOISE_PATTERNS = (
    r"\bstock price\b", r"\bstock quote\b", r"\bshare price\b",
    r"\bquote and history\b", r"\bhistorical data\b", r"\bcompany profile\b",
    r"\bfinancials and stock price\b", r"\bstock forecast\b",
    r"\bmarket data and news\b", r"\bprice, news, quote\b",
    r"\bnews, quote and history\b", r"\byahoo finance\b.*\bstock\b",
)


def _is_market_relevant(title, summary=""):
    """Keep global-news feed entries with a clear economy/market connection."""
    text = _clean(str(title or "") + " " + str(summary or "")).lower()
    return any(term in text for term in GLOBAL_MARKET_TERMS)


def _is_company_noise(title):
    text = _clean(title).lower()
    return any(re.search(pattern, text) for pattern in COMPANY_NOISE_PATTERNS)


COMMON_COMPANY_WORDS = {
    "limited", "ltd", "india", "industries", "industry", "company", "corporation",
    "corporate", "private", "pvt", "the", "and", "of", "inc", "holdings", "holding",
    "enterprises", "enterprise", "services", "service", "group", "global",
}


def _clean(value):
    text = unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    text = str(value).strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _sentiment(text):
    lower = _clean(text).lower()
    pos = [term for term in POSITIVE if term in lower]
    neg = [term for term in NEGATIVE if term in lower]
    total = len(pos) + len(neg)
    score = (len(pos) - len(neg)) / total if total else 0.0
    confidence = min(1.0, total / 2.0)
    tags = [tag for tag, terms in TAGS.items() if any(term in lower for term in terms)]
    return round(score, 3), round(confidence, 2), tags, pos[:3], neg[:3]


def _normalise_item(title, link, published, source, source_type, summary="", publisher=""):
    title = _clean(title)
    summary = _clean(summary)
    if not title:
        return None
    dt = _parse_date(published)
    now = datetime.now(timezone.utc)
    age_hours = (now - dt).total_seconds() / 3600 if dt else None
    if age_hours is not None and (age_hours < -6 or age_hours > MAX_AGE_HOURS):
        return None
    sentiment, confidence, tags, positive_hits, negative_hits = _sentiment(title + " " + summary)
    weights = {"exchange": 1.0, "regulator": 1.0, "government": 0.9, "global": 0.7, "company_news": 0.65}
    return {
        "title": title[:500],
        "summary": summary[:800],
        "link": str(link or ""),
        "published": dt.isoformat(timespec="seconds") if dt else str(published or "Unknown"),
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "source": str(source or "Unknown"),
        "publisher": str(publisher or source or "Unknown"),
        "source_type": source_type,
        "source_weight": weights.get(source_type, 0.5),
        "sentiment": sentiment,
        "sentiment_confidence": confidence,
        "impact_tags": tags,
        "positive_terms": positive_hits,
        "negative_terms": negative_hits,
    }


def _fetch_feed(spec):
    name, url, source_type = spec
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml,*/*"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        items = []
        for entry in parsed.entries[:500]:
            published = entry.get("published") or entry.get("updated") or ""
            if entry.get("published_parsed"):
                try:
                    published = time.strftime("%a, %d %b %Y %H:%M:%S +0000", entry.published_parsed)
                except Exception:
                    pass
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if source_type == "global" and not _is_market_relevant(title, summary):
                continue
            item = _normalise_item(
                title,
                entry.get("link", url),
                published,
                name,
                source_type,
                summary,
                entry.get("author", name),
            )
            if item:
                items.append(item)
        return name, items, {"ok": True, "count": len(items), "status": response.status_code}
    except Exception as exc:
        return name, [], {"ok": False, "count": 0, "error": str(exc)[:180]}


def _fetch_gdelt():
    """Fetch a recent multilingual global macro/market news sample (no API key)."""
    query = (
        '("India economy" OR "Indian stock market" OR "global markets" OR '
        '"crude oil" OR "Federal Reserve" OR tariffs OR inflation OR sanctions OR '
        'semiconductor OR "US bond yields" OR "China economy" OR "central bank")'
    )
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    try:
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": 60,
            "timespan": "24h",
            "sort": "HybridRel",
        }
        response = None
        for attempt in range(2):
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=22,
            )
            if response.status_code in (429, 503) and attempt == 0:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(8, max(4, int(retry_after)))
                except (TypeError, ValueError):
                    delay = 6
                time.sleep(delay)
                continue
            response.raise_for_status()
            break
        response.raise_for_status()
        body = response.json()
        articles = body.get("articles", []) if isinstance(body, dict) else []
        items = []
        for article in articles:
            title = article.get("title", "")
            if not _is_market_relevant(title):
                continue
            item = _normalise_item(
                title,
                article.get("url", ""),
                article.get("seendate", ""),
                "GDELT Global News",
                "global",
                "",
                article.get("domain") or article.get("sourceCountry") or "GDELT",
            )
            if item:
                item["source_country"] = article.get("sourceCountry", "")
                item["language"] = article.get("language", "")
                items.append(item)
        return items, {"ok": True, "count": len(items), "status": response.status_code}
    except Exception as exc:
        return [], {"ok": False, "count": 0, "error": str(exc)[:180]}


def _dedupe(items):
    seen = set()
    result = []
    for item in sorted(items, key=lambda x: (x.get("age_hours") is None, x.get("age_hours") or 1e9)):
        key = item.get("link") or item.get("title", "").lower()
        key = str(key).split("?utm_", 1)[0].rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def fetch_market_news():
    """Fetch official Indian sources plus a multilingual global market-news sample."""
    items = []
    status = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_feed, spec) for spec in OFFICIAL_FEEDS]
        for future in as_completed(futures):
            name, feed_items, feed_status = future.result()
            status[name] = feed_status
            items.extend(feed_items)
        global_items, global_status = _fetch_gdelt()
        status["GDELT Global News"] = global_status
        items.extend(global_items)

    deduped = _dedupe(items)
    global_news = [x for x in deduped if x["source_type"] == "global"]
    official_news = [x for x in deduped if x["source_type"] in ("exchange", "regulator", "government")]
    return {
        "items": deduped,
        "global_news": global_news[:12],
        "official_news": official_news[:20],
        "source_status": status,
        "total_items": len(deduped),
        "working_sources": sum(1 for x in status.values() if x.get("ok")),
        "total_sources": len(status),
    }


def _company_tokens(company, symbol=""):
    tokens = [x for x in re.findall(r"[a-z0-9]+", str(company or "").lower())
              if len(x) >= 4 and x not in COMMON_COMPANY_WORDS]
    symbol = re.sub(r"[^A-Za-z0-9]", "", str(symbol or "")).lower()
    return list(dict.fromkeys(tokens)), symbol


def _matches_company(item, company, symbol=""):
    tokens, ticker = _company_tokens(company, symbol)
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    if ticker and re.search(r"(?<![a-z0-9])" + re.escape(ticker) + r"(?![a-z0-9])", text):
        return True
    if not tokens:
        return False
    hits = sum(1 for token in tokens if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text))
    return hits >= (2 if len(tokens) >= 2 else 1)


def _google_company_news(company, limit):
    query = urllib.parse.quote(f'"{company}" India company shares stock')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        items = []
        for entry in parsed.entries[:max(limit * 2, 10)]:
            published = entry.get("published") or entry.get("updated") or ""
            if entry.get("published_parsed"):
                try:
                    published = time.strftime("%a, %d %b %Y %H:%M:%S +0000", entry.published_parsed)
                except Exception:
                    pass
            publisher = entry.get("source", {}).get("title", "Google News")
            title = entry.get("title", "")
            if _is_company_noise(title):
                continue
            item = _normalise_item(
                title, entry.get("link", ""), published,
                "Google News", "company_news", entry.get("summary", ""), publisher
            )
            if item:
                items.append(item)
        return items
    except Exception:
        return []


def company_news(company, limit=6, official_items=None, symbol=""):
    """Merge company-matched official/global stories with recent Google News results."""
    matched = [
        item for item in (official_items or [])
        if _matches_company(item, company, symbol)
    ]
    google_items = [
        item for item in _google_company_news(company, limit)
        if not _is_company_noise(item.get("title", ""))
        and _matches_company(item, company, symbol)
    ]
    merged = _dedupe(matched + google_items)
    # Prefer primary exchange/regulator evidence over repeated aggregator copies.
    merged.sort(key=lambda x: (
        {"exchange": 0, "regulator": 1, "government": 2, "global": 3, "company_news": 4}.get(x["source_type"], 5),
        x.get("age_hours") is None,
        x.get("age_hours") or 1e9,
    ))
    return merged[:limit]
