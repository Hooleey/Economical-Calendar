import os
import re
import time
import json
import urllib.request
from urllib.parse import urlsplit, quote
from html import unescape
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from . import crud

ALFAFOREX_PAGE_URL = (os.getenv("ALFAFOREX_PAGE_URL") or "https://alfaforex.ru/economic-calendar/").rstrip("/")
ALFAFOREX_TTL_SECONDS = int(os.getenv("ALFAFOREX_SYNC_TTL_SECONDS") or "60")
ALFAFOREX_CULTURE = os.getenv("ALFAFOREX_CULTURE") or "ru-RU"
ALFAFOREX_TIMEZONE = os.getenv("ALFAFOREX_TIMEZONE") or "Arabic Standard Time"
# Same default list as the AlfaForex calendar page (must include CN etc. or many rows never appear in JSON).
ALFAFOREX_COUNTRYCODE = os.getenv("ALFAFOREX_COUNTRYCODE") or (
    "AU,UK,DE,EMU,ES,IT,CA,CN,MX,NZ,RU,US,TR,FR,CH,ZA,JP"
)
# Wall-clock for DateTime from the API matches the requested calendar timeZone; map to IANA for countdown.
ALFAFOREX_IANA_TIMEZONE = os.getenv("ALFAFOREX_IANA_TIMEZONE") or "Asia/Riyadh"

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
    # example: "вторник, 22 апреля 2026"
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
    # event often has "... (США)"
    match = re.search(r"^(.*)\(([^)]+)\)\s*$", text)
    if match:
        return match.group(2).strip()[:100], match.group(1).strip()[:255]
    return "Не указано", text[:255]


def _clean_html_description(raw_html: str) -> Optional[str]:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _compute_remaining_time(item: dict[str, Any]) -> Optional[str]:
    """
    JSON feed has no countdown field; derive it from DateTime (wall clock in ALFAFOREX_TIMEZONE).
    """
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


def _alfaforex_api_endpoint(*, include_countrycode: bool = True, culture: Optional[str] = None) -> str:
    parts = urlsplit(ALFAFOREX_PAGE_URL)
    site_root = f"{parts.scheme}://{parts.netloc}"
    culture = quote(culture or ALFAFOREX_CULTURE, safe="")
    tz = quote(ALFAFOREX_TIMEZONE, safe="")
    endpoint = f"{site_root}/api/economic-calendar/?action=events&culture={culture}&timeZone={tz}"
    if include_countrycode:
        cc = quote(ALFAFOREX_COUNTRYCODE, safe=",")
        endpoint += f"&countrycode={cc}"
    return endpoint


def _fetch_events_payload(*, culture: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Prefer the site's JSON API: it contains far more events than the rendered table.
    Merges filtered and unfiltered responses so country-scoped gaps are filled.
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _load(include_countrycode: bool) -> None:
        endpoint = _alfaforex_api_endpoint(
            include_countrycode=include_countrycode, culture=culture
        )
        with urllib.request.urlopen(endpoint, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
        if not isinstance(payload, list):
            return
        for item in payload:
            event_id = str(item.get("IdEcoCalendar") or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            merged.append(item)

    for with_cc in (True, False):
        try:
            _load(with_cc)
        except Exception:
            continue
    return merged


def _fetch_descriptions_map(*, culture: Optional[str] = None) -> dict[str, str]:
    payload = _fetch_events_payload(culture=culture)
    result: dict[str, str] = {}
    for item in payload:
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
        descriptions_map = _fetch_descriptions_map(culture=culture)
        _desc_cache[culture] = (now, descriptions_map)
    key = external_id if external_id.startswith("alfaforex:") else f"alfaforex:{external_id}"
    return descriptions_map.get(key)


def _fetch_rendered_rows() -> list[dict[str, Any]]:
    last_error: Optional[Exception] = None
    with sync_playwright() as p:
        for _ in range(3):
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                # networkidle is too strict for this page and often times out
                page.goto(ALFAFOREX_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".trading-table__body tr", timeout=60000)
                tz_for_req = ALFAFOREX_TIMEZONE.replace(" ", "+")
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
                // description exists only in the events payload (HTMLDescription)
                // and not in visible table cells.
                // We read it here and still bind it to rows from rendered HTML.
                // eslint-disable-next-line no-undef
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
              } catch (_) {
                // keep rows even if descriptions endpoint is unavailable
              }
              const trs = Array.from(tbody.querySelectorAll("tr"));
              for (const tr of trs) {
                const placeholder = tr.classList.contains("trading-table__placeholder");
                if (placeholder) continue;
                const tds = Array.from(tr.querySelectorAll("td"));
                if (!tds.length) continue;
                const colSpan = tds[0].getAttribute("colspan");
                if (colSpan) {
                  currentDate = (tds[0].textContent || "").trim();
                  continue;
                }
                const cells = tds.map((td) => (td.textContent || "").replace(/\\s+/g, " ").trim());
                const volImg = tr.querySelector("td:nth-child(4) img");
                const href = tr.querySelector("td:nth-child(5) a")?.getAttribute("href") || "";
                const rowId = tr.getAttribute("data-IdEcoCalendar") || "";
                result.push({
                  dateLabel: currentDate,
                  rowId,
                  href,
                  timeText: cells[0] || "",
                  remainingText: cells[1] || "",
                  currency: cells[2] || "",
                  volatilityText: cells[3] || "",
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
                time.sleep(1)
    if last_error:
        raise last_error
    return []


def sync_alfaforex_events(db: Session) -> dict[str, int]:
    descriptions_map: dict[str, str] = {}
    try:
        descriptions_map = _fetch_descriptions_map()
    except Exception:
        descriptions_map = {}
    inserted = 0
    updated = 0
    skipped = 0

    fetched = 0
    try:
        payload = _fetch_events_payload()
        fetched = len(payload)
        for item in payload:
            event_id = str(item.get("IdEcoCalendar") or "").strip()
            title = str(item.get("Name") or "").strip()[:255]
            if not event_id or not title:
                skipped += 1
                continue

            dt = item.get("DateTime") or {}
            dt_str = str(dt.get("Date") or "").strip()  # "YYYY-MM-DDTHH:MM:SS"
            if len(dt_str) < 10:
                skipped += 1
                continue
            try:
                day = date.fromisoformat(dt_str[:10])
            except Exception:
                skipped += 1
                continue

            all_day = bool(item.get("AllDay"))
            hour = dt.get("Hour")
            minute = dt.get("Minute")
            ev_time = None
            if not all_day:
                try:
                    h = int(hour)
                    m = int(minute)
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        ev_time = f"{h:02d}:{m:02d}"
                except Exception:
                    ev_time = None

            volatility = item.get("Volatility")
            country = str(item.get("Country") or "").strip()[:100] or "Не указано"
            currency = str(item.get("Currency") or "").strip() or None
            actual = str(item.get("DisplayActual") or "").strip() or None
            forecast = str(item.get("DisplayConsensus") or "").strip() or None
            previous = str(item.get("DisplayPrevious") or "").strip() or None

            status = crud.upsert_external_event(
                db,
                external_id=f"alfaforex:{event_id}",
                title=title,
                event_date=day,
                event_time=ev_time,
                remaining_time=_compute_remaining_time(item),
                currency=currency,
                actual=actual,
                forecast=forecast,
                previous=previous,
                description=_clean_html_description(str(item.get("HTMLDescription") or ""))
                or descriptions_map.get(f"alfaforex:{event_id}"),
                country=country,
                regulator="Альфа-Форекс",
                importance=_importance_from_volatility(volatility),
                source="alfaforex",
            )
            if status == "inserted":
                inserted += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1
    except Exception:
        # fallback to rendered table scraping (less complete, but keeps API working)
        rows = _fetch_rendered_rows()
        fetched = len(rows)
        for row in rows:
            event_id = str(row.get("rowId") or row.get("href") or "").strip()
            name_text = str(row.get("nameText") or "").strip()
            if not event_id or not name_text:
                skipped += 1
                continue
            day = _parse_ru_date_label(str(row.get("dateLabel") or ""))
            if day is None:
                skipped += 1
                continue
            country, title = _extract_country_and_title(name_text)
            raw_time = str(row.get("timeText") or "").strip()
            ev_time = raw_time if re.match(r"^\d{2}:\d{2}$", raw_time) else None
            vol_img = str(row.get("volImg") or "")
            volatility = 1
            if "volat-new-3" in vol_img:
                volatility = 3
            elif "volat-new-2" in vol_img:
                volatility = 2

            status = crud.upsert_external_event(
                db,
                external_id=f"alfaforex:{event_id}",
                title=title,
                event_date=day,
                event_time=ev_time,
                remaining_time=str(row.get("remainingText") or "").strip() or None,
                currency=str(row.get("currency") or "").strip() or None,
                actual=str(row.get("actual") or "").strip() or None,
                forecast=str(row.get("forecast") or "").strip() or None,
                previous=str(row.get("previous") or "").strip() or None,
                description=(
                    _clean_html_description(str(row.get("descriptionHtml") or ""))
                    or descriptions_map.get(f"alfaforex:{event_id}")
                ),
                country=country,
                regulator="Альфа-Форекс",
                importance=_importance_from_volatility(volatility),
                source="alfaforex",
            )
            if status == "inserted":
                inserted += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1

    if descriptions_map:
        updated += crud.backfill_external_descriptions(db, descriptions_map)

    return {"fetched": fetched, "inserted": inserted, "updated": updated, "skipped": skipped}


def refresh_if_stale(db: Session, force: bool = False) -> Optional[dict[str, int]]:
    global _last_sync_epoch
    now = time.time()
    if not force and _last_sync_epoch and now - _last_sync_epoch < ALFAFOREX_TTL_SECONDS:
        return None
    result = sync_alfaforex_events(db)
    _last_sync_epoch = now
    return result
