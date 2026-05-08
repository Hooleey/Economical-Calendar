"""
Collect economic news by parsing website HTML pages (no RSS/API endpoints).
"""

from __future__ import annotations

import os
import re
import time
import json
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from . import crud

NEWS_SYNC_TTL_SECONDS = int(os.getenv("NEWS_SYNC_TTL_SECONDS") or "900")
LAST_NEWS_REFRESH: float = 0.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SiteSpec:
    key: str
    label: str
    url: str
    host_suffix: str
    include_path_keywords: tuple[str, ...]
    strict_economic: bool = False


SITES: tuple[SiteSpec, ...] = (
    SiteSpec(
        key="reuters_business",
        label="Reuters Business",
        url="https://www.reuters.com/business/",
        host_suffix="reuters.com",
        include_path_keywords=("/business/", "/markets/", "/world/economy"),
        strict_economic=False,
    ),
    SiteSpec(
        key="rbc_economics",
        label="РБК Экономика",
        url="https://www.rbc.ru/economics/",
        host_suffix="rbc.ru",
        include_path_keywords=("/economics/", "/finances/", "/business/"),
        strict_economic=True,
    ),
    SiteSpec(
        key="interfax_business",
        label="Интерфакс Бизнес",
        url="https://www.interfax.ru/business/",
        host_suffix="interfax.ru",
        include_path_keywords=("/business/", "/business/"),
        strict_economic=True,
    ),
    SiteSpec(
        key="kommersant_economics",
        label="Коммерсант Экономика",
        url="https://www.kommersant.ru/rubric/3",
        host_suffix="kommersant.ru",
        include_path_keywords=("/doc/", "/rubric/3"),
        strict_economic=True,
    ),
    SiteSpec(
        key="vedomosti_economics",
        label="Ведомости Экономика",
        url="https://www.vedomosti.ru/economics",
        host_suffix="vedomosti.ru",
        include_path_keywords=("/economics/",),
        strict_economic=True,
    ),
    SiteSpec(
        key="tass_economics",
        label="ТАСС Экономика",
        url="https://tass.ru/ekonomika",
        host_suffix="tass.ru",
        include_path_keywords=("/ekonomika/",),
        strict_economic=True,
    ),
    SiteSpec(
        key="ria_economy",
        label="РИА Новости Экономика",
        url="https://ria.ru/economy/",
        host_suffix="ria.ru",
        include_path_keywords=("/economy/", "/20"),
        strict_economic=True,
    ),
    SiteSpec(
        key="cbr_press",
        label="Банк России Пресс-релизы",
        url="https://cbr.ru/press/",
        host_suffix="cbr.ru",
        include_path_keywords=("/press/",),
        strict_economic=True,
    ),
    SiteSpec(
        key="forbes_finance",
        label="Forbes Россия Финансы",
        url="https://www.forbes.ru/finansy",
        host_suffix="forbes.ru",
        include_path_keywords=("/finansy/",),
        strict_economic=True,
    ),
)


ECON_KEYWORDS: tuple[str, ...] = (
    "econom",
    "macro",
    "gdp",
    "inflation",
    "deflation",
    "interest rate",
    "central bank",
    "federal reserve",
    "ecb",
    "fomc",
    "bond",
    "yield",
    "stock",
    "market",
    "currency",
    "forex",
    "treasury",
    "trade",
    "tariff",
    "budget",
    "deficit",
    "bank",
    "earnings",
    "ipo",
    "recession",
    "commodit",
    "oil",
    "gas",
    "эконом",
    "макро",
    "инфля",
    "ввп",
    "ставк",
    "цб",
    "фрс",
    "облигац",
    "акци",
    "бирж",
    "рынок",
    "валют",
    "кредит",
    "банк",
    "нефт",
    "газ",
    "бюджет",
    "санкц",
    "экспорт",
    "импорт",
)

BLOCK_KEYWORDS: tuple[str, ...] = (
    "sport",
    "football",
    "soccer",
    "basketball",
    "nba",
    "nfl",
    "nhl",
    "movie",
    "cinema",
    "music",
    "celebrity",
    "recipe",
    "travel",
    "футбол",
    "хоккей",
    "теннис",
    "кино",
    "сериал",
    "звезд",
    "рецепт",
    "погода",
)


def _clean_text(text: str) -> str:
    t = unescape(text or "")
    t = re.sub(r"(?is)<script.*?>.*?</script>", " ", t)
    t = re.sub(r"(?is)<style.*?>.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _is_valid_article_url(url: str, site: SiteSpec) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if site.host_suffix not in (parsed.netloc or ""):
        return False
    path = (parsed.path or "").lower()
    if not path or path in ("/", "/news"):
        return False
    return any(k in path for k in site.include_path_keywords)


def _extract_links(html: str, site: SiteSpec) -> list[dict[str, Optional[str]]]:
    # Generic anchor extraction for listing pages.
    matches = re.findall(
        r'(?is)<a\b[^>]*?\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html or "",
    )
    rows: list[dict[str, Optional[str]]] = []
    seen: set[str] = set()
    for href, inner in matches:
        full_url = urljoin(site.url, (href or "").strip())
        if not _is_valid_article_url(full_url, site):
            continue
        title = _clean_text(inner)
        if len(title) < 24:
            continue
        title = title[:500]
        if full_url in seen:
            continue
        seen.add(full_url)
        rows.append(
            {
                "link": full_url[:2000],
                "title": title,
                "summary": None,
                "published_at": None,
            }
        )
        if len(rows) >= 70:
            break
    return rows


def passes_economic_filter(title: str, summary: str, *, strict_source: bool) -> bool:
    if strict_source:
        return True
    blob = _normalize(f"{title} {summary}")
    if not blob:
        return False
    if any(x in blob for x in BLOCK_KEYWORDS):
        return False
    return any(k in blob for k in ECON_KEYWORDS)


def _fetch_site(client: httpx.Client, site: SiteSpec) -> list[dict[str, Optional[str]]]:
    resp = client.get(site.url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    return _extract_links(html, site)


def _looks_like_allowed_host(url: str) -> bool:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return False
    return any(site.host_suffix in host for site in SITES)


def _extract_full_article_text(html: str) -> str:
    body = html or ""
    # Prefer semantic content blocks first.
    candidates = re.findall(r"(?is)<article\b[^>]*>(.*?)</article>", body)
    if not candidates:
        candidates = re.findall(r"(?is)<main\b[^>]*>(.*?)</main>", body)
    if not candidates:
        candidates = re.findall(
            r'(?is)<(?:div|section)\b[^>]*(?:class|id)=["\'][^"\']*(?:article|content|story|text|body)[^"\']*["\'][^>]*>(.*?)</(?:div|section)>',
            body,
        )
    if not candidates:
        candidates = [body]

    def collect_paragraphs(chunk: str) -> list[str]:
        ps = re.findall(r"(?is)<(?:p|h2|h3|li)\b[^>]*>(.*?)</(?:p|h2|h3|li)>", chunk or "")
        out: list[str] = []
        for raw in ps:
            t = _clean_text(raw)
            if len(t) < 24:
                continue
            if t in out:
                continue
            out.append(t)
        return out

    best: list[str] = []
    for chunk in candidates:
        ps = collect_paragraphs(chunk)
        if len(" ".join(ps)) > len(" ".join(best)):
            best = ps

    text = "\n\n".join(best).strip()
    if not text:
        # Fallback to plain cleaned text if site markup is unusual.
        text = _clean_text(body)
    # Keep a very high cap to allow practically full article text.
    return text[:120000]


def _extract_meta_description(html: str) -> str:
    m = re.search(
        r'(?is)<meta\b[^>]*?(?:name|property)=["\'](?:description|og:description)["\'][^>]*?\bcontent=["\']([^"\']+)["\']',
        html or "",
    )
    return _clean_text(m.group(1))[:1200] if m else ""


def _extract_json_ld_text(html: str) -> str:
    blocks = re.findall(
        r'(?is)<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "",
    )
    for raw in blocks:
        txt = (raw or "").strip()
        if not txt:
            continue
        try:
            payload = json.loads(txt)
        except Exception:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        for item in queue:
            if not isinstance(item, dict):
                continue
            article_body = item.get("articleBody")
            description = item.get("description")
            candidate = ""
            if isinstance(article_body, str):
                candidate = _clean_text(article_body)
            elif isinstance(description, str):
                candidate = _clean_text(description)
            if len(candidate) > 120:
                return candidate[:120000]
    return ""


def fetch_article_content(url: str) -> dict[str, str]:
    if not _looks_like_allowed_host(url):
        raise ValueError("Source host is not allowed")
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    full_text = _extract_full_article_text(html)
    if len(full_text) < 300:
        json_ld = _extract_json_ld_text(html)
        if len(json_ld) > len(full_text):
            full_text = json_ld
    summary = _extract_meta_description(html)
    if not summary and full_text:
        summary = full_text.split("\n\n", 1)[0][:600]
    if len(full_text) < 120:
        raise ValueError("Failed to extract full article text")
    return {"content": full_text, "summary": summary}


def refresh_news(db: Session, *, force: bool = False) -> dict[str, object]:
    global LAST_NEWS_REFRESH
    now = time.time()
    if not force and LAST_NEWS_REFRESH and (now - LAST_NEWS_REFRESH) < NEWS_SYNC_TTL_SECONDS:
        return {"status": "skipped", "reason": "ttl"}

    sources_ok = 0
    items_seen = 0
    items_kept = 0
    errors: list[dict[str, str]] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for site in SITES:
            try:
                rows = _fetch_site(client, site)
                sources_ok += 1
                items_seen += len(rows)
                for row in rows:
                    title = (row.get("title") or "").strip()
                    summary = (row.get("summary") or "").strip()
                    link = (row.get("link") or "").strip()
                    if not title or not link:
                        continue
                    if not passes_economic_filter(
                        title,
                        summary,
                        strict_source=site.strict_economic,
                    ):
                        continue
                    # Try to collect a readable teaser from the article page.
                    # If blocked by source, we keep the item and fallback later.
                    if not summary:
                        try:
                            preview = fetch_article_content(link)
                            summary = (preview.get("summary") or "").strip()
                        except Exception:
                            summary = ""
                    crud.upsert_news_article(
                        db,
                        link=link,
                        title=title[:500],
                        summary=summary[:8000] if summary else None,
                        source_key=site.key,
                        source_label=site.label,
                        published_at=None,
                    )
                    items_kept += 1
            except Exception as e:
                errors.append({"source": site.key, "error": str(e)})

    crud.prune_old_news(db, keep=250)
    LAST_NEWS_REFRESH = now
    return {
        "status": "ok",
        "sources": sources_ok,
        "items_seen": items_seen,
        "items_kept": items_kept,
        "errors": errors,
        "mode": "html_scrape",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
