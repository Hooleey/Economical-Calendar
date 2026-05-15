"""
Ingest economic calendar events from alfaforex.ru.

Primary path: public JSON API (same as the site SPA).
Fallback: headless browser scrape when API returns zero rows or errors.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from html import unescape
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from . import crud

logger = logging.getLogger(__name__)

ALFAFOREX_PAGE_URL = (os.getenv("ALFAFOREX_PAGE_URL") or "https://alfaforex.ru/economic-calendar/").rstrip("/")
ALFAFOREX_TTL_SECONDS = int(os.getenv("ALFAFOREX_SYNC_TTL_SECONDS") or "60")
ALFAFOREX_CULTURE = os.getenv("ALFAFOREX_CULTURE") or "ru-RU"
ALFAFOREX_TIMEZONE = os.getenv("ALFAFOREX_TIMEZONE") or "Arabic Standard Time"
ALFAFOREX_COUNTRYCODE = os.getenv("ALFAFOREX_COUNTRYCODE") or (
    "AU,UK,DE,EMU,ES,IT,CA,CN,MX,NZ,RU,US,TR,FR,CH,ZA,JP"
)
ALFAFOREX_IANA_TIMEZONE = os.getenv("ALFAFOREX_IANA_TIMEZONE") or "Asia/Riyadh"

HTTP_TIMEOUT = float(os.getenv("ALFAFOREX_HTTP_TIMEOUT") or "45")
HTTP_RETRIES = int(os.getenv("ALFAFOREX_HTTP_RETRIES") or "3")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{ALFAFOREX_PAGE_URL}/",
}

# Site accepts several Windows timezone ids; wrong value yields HTTP 200 + [].
_TIMEZONE_CANDIDATES = (
    ALFAFOREX_TIMEZONE,
    "Arabic Standard Time",
    "Russian Standard Time",
    "GMT Standard Time",
)

_last_sync_epoch: float = 0.0
_desc_cache: dict[str, tuple[float, dict[str, str]]] = {}

RUS_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


class AlfaForexFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedEvent:
    external_id: str
    title: str
    event_date: date
    country: str
    importance: str
    event_time: Optional[str] = None
    remaining_time: Optional[str] = None
    currency: Optional[str] = None
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    description: Optional[str] = None


def _site_root() -> str:
    parts = urlsplit(ALFAFOREX_PAGE_URL)
    return f"{parts.scheme}://{parts.netloc}"


def _importance_from_volatility(volatility: Any) -> str:
    try:
        v = int(volatility)
    except (TypeError, ValueError):
        return "low"
    if v >= 3:
        return "high"
    if v == 2:
        return "medium"
    return "low"


def _parse_ru_date_label(label: str) -> Optional[date]:
    text = (label or "").strip().lower()
    match = re.search(r"(\d{1,2})\s+([а-я]+)\s+(\d{4})", text)
    if not match:
        return None
    day = int(match.group(1))
    month = RUS_MONTHS.get(match.group(2))
    year = int(match.group(3))
    if not month:
        return None
    return date(year, month, day)


def _extract_country_and_title(name_text: str) -> tuple[str, str]:
    text = (name_text or "").strip()
    match = re.search(r"^(.*)\(([^)]+)\)\s*$", text)
    if match:
        return match.group(2).strip()[:100], match.group(1).strip()[:255]
    return "Не указано", text[:255]


def _clean_html_description(raw_html: str) -> Optional[str]:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _metric_text(item: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        raw = item.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def _compute_remaining_time(item: dict[str, Any]) -> Optional[str]:
    if bool(item.get("AllDay")):
        return None
    dt = item.get("DateTime") or {}
    date_s = str(dt.get("Date") or "").strip()
    if len(date_s) < 19:
        return None
    try:
        naive = datetime.fromisoformat(date_s[:19])
        tz = ZoneInfo(ALFAFOREX_IANA_TIMEZONE)
        ev = naive.replace(tzinfo=tz)
        sec = int((ev - datetime.now(tz)).total_seconds())
        if sec <= 0:
            return None
        d, r = divmod(sec, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        if d:
            return f"{d}d {h}h {m}m"
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s" if s else f"{m}m"
        return f"{s}s" if s else "<1m"
    except Exception:
        return None


def _events_api_url(
    *,
    timezone: str,
    include_countrycode: bool,
    culture: Optional[str] = None,
) -> str:
    culture_q = quote(culture or ALFAFOREX_CULTURE, safe="")
    tz_q = quote(timezone, safe="")
    url = (
        f"{_site_root()}/api/economic-calendar/"
        f"?action=events&culture={culture_q}&timeZone={tz_q}"
    )
    if include_countrycode:
        url += f"&countrycode={quote(ALFAFOREX_COUNTRYCODE, safe=',')}"
    return url


def _parse_api_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        err = payload.get("error")
        if err:
            raise AlfaForexFetchError(str(err))
        for key in ("events", "data", "items", "result"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
    return []


def _http_get_json(url: str) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with httpx.Client(
                headers=DEFAULT_HEADERS,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "AlfaForex API attempt %s/%s failed for %s: %s",
                attempt,
                HTTP_RETRIES,
                url[:120],
                exc,
            )
            if attempt < HTTP_RETRIES:
                time.sleep(min(attempt * 0.75, 2.0))
    raise AlfaForexFetchError(f"HTTP failed after {HTTP_RETRIES} tries: {last_exc}") from last_exc


def fetch_events_from_api(*, culture: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Download events JSON; merge country-filtered and full feeds across timezone candidates.
    """
    merged: dict[str, dict[str, Any]] = {}
    seen_urls: list[str] = []

    for timezone in dict.fromkeys(_TIMEZONE_CANDIDATES):
        for include_cc in (True, False):
            url = _events_api_url(
                timezone=timezone,
                include_countrycode=include_cc,
                culture=culture,
            )
            if url in seen_urls:
                continue
            seen_urls.append(url)
            try:
                payload = _http_get_json(url)
                rows = _parse_api_payload(payload)
            except Exception as exc:
                logger.warning("AlfaForex fetch skipped (%s): %s", url[:100], exc)
                continue
            if not rows:
                logger.info(
                    "AlfaForex API returned 0 rows (tz=%r, countrycode=%s)",
                    timezone,
                    include_cc,
                )
                continue
            for item in rows:
                event_id = str(item.get("IdEcoCalendar") or "").strip()
                if event_id:
                    merged[event_id] = item
            logger.info(
                "AlfaForex API chunk: tz=%r countrycode=%s rows=%s total_unique=%s",
                timezone,
                include_cc,
                len(rows),
                len(merged),
            )

    return list(merged.values())


def _parse_api_item(item: dict[str, Any], descriptions_map: dict[str, str]) -> Optional[ParsedEvent]:
    event_id = str(item.get("IdEcoCalendar") or "").strip()
    title = str(item.get("Name") or "").strip()[:255]
    if not event_id or not title:
        return None

    dt = item.get("DateTime") or {}
    dt_str = str(dt.get("Date") or "").strip()
    if len(dt_str) < 10:
        return None
    try:
        day = date.fromisoformat(dt_str[:10])
    except ValueError:
        return None

    all_day = bool(item.get("AllDay"))
    ev_time = None
    if not all_day:
        try:
            h = int(dt.get("Hour"))
            m = int(dt.get("Minute"))
            if 0 <= h <= 23 and 0 <= m <= 59:
                ev_time = f"{h:02d}:{m:02d}"
        except (TypeError, ValueError):
            ev_time = None

    ext = f"alfaforex:{event_id}"
    description = _clean_html_description(str(item.get("HTMLDescription") or "")) or descriptions_map.get(ext)

    return ParsedEvent(
        external_id=ext,
        title=title,
        event_date=day,
        country=str(item.get("Country") or "").strip()[:100] or "Не указано",
        importance=_importance_from_volatility(item.get("Volatility")),
        event_time=ev_time,
        remaining_time=_compute_remaining_time(item),
        currency=_metric_text(item, "Currency"),
        actual=_metric_text(item, "DisplayActual", "Actual", "PotActual"),
        forecast=_metric_text(item, "DisplayConsensus", "Consensus", "PotConsensus"),
        previous=_metric_text(item, "DisplayPrevious", "Previous", "PotPrevious"),
        description=description,
    )


def _fetch_descriptions_map(*, culture: Optional[str] = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in fetch_events_from_api(culture=culture):
        event_id = str(item.get("IdEcoCalendar") or "").strip()
        description = _clean_html_description(str(item.get("HTMLDescription") or ""))
        if event_id and description:
            result[f"alfaforex:{event_id}"] = description
    return result


def get_description_by_external_id(external_id: str, *, lang: str) -> Optional[str]:
    culture_by_lang = {
        "ru": "ru-RU",
        "en": "en-US",
        "zh": "zh-CN",
        "es": "es-ES",
    }
    culture = culture_by_lang.get((lang or "").lower(), ALFAFOREX_CULTURE)
    now = time.time()
    cached = _desc_cache.get(culture)
    if cached and now - cached[0] < 600:
        descriptions_map = cached[1]
    else:
        try:
            descriptions_map = _fetch_descriptions_map(culture=culture)
        except Exception:
            descriptions_map = {}
        _desc_cache[culture] = (now, descriptions_map)
    key = external_id if external_id.startswith("alfaforex:") else f"alfaforex:{external_id}"
    return descriptions_map.get(key)


def _fetch_rendered_rows() -> list[dict[str, Any]]:
    last_error: Optional[Exception] = None
    tz_for_req = ALFAFOREX_TIMEZONE.replace(" ", "+")
    with sync_playwright() as p:
        for attempt in range(1, 4):
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(ALFAFOREX_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".trading-table__body tr", timeout=60000)
                rows = page.evaluate(
                    """({ timeZone, countrycode, culture }) => {
              const tbody = document.querySelector(".trading-table__body");
              if (!tbody) return [];
              const result = [];
              const descriptionsById = {};
              let currentDate = "";
              try {
                const params = new URLSearchParams({
                  action: "events",
                  culture,
                  timeZone,
                  countrycode
                });
                const url = `/api/economic-calendar/?${params.toString()}`;
                const req = new XMLHttpRequest();
                req.open("GET", url, false);
                req.send(null);
                if (req.status >= 200 && req.status < 300) {
                  const payload = JSON.parse(req.responseText || "[]");
                  if (Array.isArray(payload)) {
                    for (const item of payload) {
                      const id = String(item?.IdEcoCalendar || "").trim();
                      if (id) descriptionsById[id] = String(item?.HTMLDescription || "");
                    }
                  }
                }
              } catch (_) {}
              const trs = Array.from(tbody.querySelectorAll("tr"));
              for (const tr of trs) {
                if (tr.classList.contains("trading-table__placeholder")) continue;
                const tds = Array.from(tr.querySelectorAll("td"));
                if (!tds.length) continue;
                if (tds[0].getAttribute("colspan")) {
                  currentDate = (tds[0].textContent || "").trim();
                  continue;
                }
                const cells = tds.map((td) => (td.textContent || "").replace(/\\s+/g, " ").trim());
                const volImg = tr.querySelector("td:nth-child(4) img");
                const rowId = tr.getAttribute("data-IdEcoCalendar") || "";
                result.push({
                  dateLabel: currentDate,
                  rowId,
                  timeText: cells[0] || "",
                  remainingText: cells[1] || "",
                  currency: cells[2] || "",
                  nameText: cells[4] || "",
                  actual: cells[5] || "",
                  forecast: cells[6] || "",
                  previous: cells[7] || "",
                  volImg: volImg ? volImg.getAttribute("src") || "" : "",
                  descriptionHtml: descriptionsById[rowId] || ""
                });
              }
              return result;
            }""",
                    {
                        "timeZone": tz_for_req,
                        "countrycode": ALFAFOREX_COUNTRYCODE,
                        "culture": ALFAFOREX_CULTURE,
                    },
                )
                browser.close()
                return rows
            except Exception as exc:
                last_error = exc
                browser.close()
                logger.warning("Playwright scrape attempt %s failed: %s", attempt, exc)
                time.sleep(1)
    if last_error:
        raise AlfaForexFetchError(f"Playwright scrape failed: {last_error}") from last_error
    return []


def _parse_scraped_row(row: dict[str, Any], descriptions_map: dict[str, str]) -> Optional[ParsedEvent]:
    event_id = str(row.get("rowId") or "").strip()
    name_text = str(row.get("nameText") or "").strip()
    if not event_id or not name_text:
        return None
    day = _parse_ru_date_label(str(row.get("dateLabel") or ""))
    if day is None:
        return None
    country, title = _extract_country_and_title(name_text)
    raw_time = str(row.get("timeText") or "").strip()
    ev_time = raw_time if re.match(r"^\d{2}:\d{2}$", raw_time) else None
    vol_img = str(row.get("volImg") or "")
    volatility = 1
    if "volat-new-3" in vol_img:
        volatility = 3
    elif "volat-new-2" in vol_img:
        volatility = 2
    ext = f"alfaforex:{event_id}"
    return ParsedEvent(
        external_id=ext,
        title=title,
        event_date=day,
        country=country,
        importance=_importance_from_volatility(volatility),
        event_time=ev_time,
        remaining_time=str(row.get("remainingText") or "").strip() or None,
        currency=str(row.get("currency") or "").strip() or None,
        actual=str(row.get("actual") or "").strip() or None,
        forecast=str(row.get("forecast") or "").strip() or None,
        previous=str(row.get("previous") or "").strip() or None,
        description=_clean_html_description(str(row.get("descriptionHtml") or ""))
        or descriptions_map.get(ext),
    )


def _load_raw_events() -> tuple[list[dict[str, Any]], str]:
    """Returns (raw API-shaped dicts, source label)."""
    try:
        api_rows = fetch_events_from_api()
        if api_rows:
            return api_rows, "api"
    except AlfaForexFetchError as exc:
        logger.warning("AlfaForex API unavailable: %s", exc)

    logger.info("AlfaForex API empty or failed — falling back to Playwright scrape")
    scraped = _fetch_rendered_rows()
    if not scraped:
        raise AlfaForexFetchError("No events from API or Playwright")
    return scraped, "playwright"


def _upsert_parsed(db: Session, event: ParsedEvent) -> str:
    return crud.upsert_external_event(
        db,
        external_id=event.external_id,
        title=event.title,
        event_date=event.event_date,
        event_time=event.event_time,
        remaining_time=event.remaining_time,
        currency=event.currency,
        actual=event.actual,
        forecast=event.forecast,
        previous=event.previous,
        description=event.description,
        country=event.country,
        regulator="Альфа-Форекс",
        importance=event.importance,
        source="alfaforex",
    )


def sync_alfaforex_events(db: Session) -> dict[str, int]:
    descriptions_map: dict[str, str] = {}
    try:
        descriptions_map = _fetch_descriptions_map()
    except Exception as exc:
        logger.warning("Description prefetch failed: %s", exc)

    raw_rows, ingest_source = _load_raw_events()
    inserted = updated = skipped = 0

    for raw in raw_rows:
        if ingest_source == "api":
            parsed = _parse_api_item(raw, descriptions_map)
        else:
            parsed = _parse_scraped_row(raw, descriptions_map)
        if parsed is None:
            skipped += 1
            continue
        status = _upsert_parsed(db, parsed)
        if status == "inserted":
            inserted += 1
        elif status == "updated":
            updated += 1
        else:
            skipped += 1

    if descriptions_map:
        updated += crud.backfill_external_descriptions(db, descriptions_map)

    stats = {
        "fetched": len(raw_rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "source": ingest_source,
    }
    logger.info("AlfaForex sync done: %s", stats)
    return stats


def refresh_if_stale(db: Session, force: bool = False) -> Optional[dict[str, int]]:
    global _last_sync_epoch
    now = time.time()
    if not force and _last_sync_epoch and now - _last_sync_epoch < ALFAFOREX_TTL_SECONDS:
        return None
    try:
        result = sync_alfaforex_events(db)
    except AlfaForexFetchError:
        raise
    except Exception as exc:
        raise AlfaForexFetchError(str(exc)) from exc
    # Do not advance TTL when ingest returned nothing — retry on the next request.
    if result.get("fetched", 0) > 0:
        _last_sync_epoch = now
    else:
        logger.error("AlfaForex sync returned 0 rows; TTL not advanced")
    return result
