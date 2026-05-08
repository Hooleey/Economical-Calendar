import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from . import crud

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

HIGH_KEYWORDS = (
    "cpi",
    "consumer price",
    "employment",
    "payroll",
    "gdp",
    "fomc",
    "federal reserve",
    "interest rate",
    "jobless",
    "nonfarm",
    "inflation",
    "retail sales",
    "treasury",
    "bea",
    "nfp",
)
MEDIUM_KEYWORDS = (
    "housing",
    "pmi",
    "confidence",
    "trade",
    "production",
    "industrial",
    "manufacturing",
    "durable",
    "claims",
    "productivity",
)


def _fred_api_key() -> str:
    return (os.getenv("FRED_API_KEY") or "").strip()


def fred_api_configured() -> bool:
    """Used by /health — do not log or return the key."""
    return bool(_fred_api_key())


def _guess_importance(title: str) -> str:
    t = title.lower()
    for w in HIGH_KEYWORDS:
        if w in t:
            return "high"
    for w in MEDIUM_KEYWORDS:
        if w in t:
            return "medium"
    return "low"


def _parse_date_time(value: str) -> tuple[date, Optional[str]]:
    value = (value or "").strip()
    if not value:
        raise ValueError("empty date")
    if "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.date(), parsed.strftime("%H:%M")
        except ValueError:
            pass
    day = date.fromisoformat(value[:10])
    return day, None


def _fetch_releases_index(client: httpx.Client, api_key: str) -> dict[int, str]:
    names: dict[int, str] = {}
    offset = 0
    limit = 1000
    while True:
        r = client.get(
            f"{FRED_BASE}/releases",
            params={
                "api_key": api_key,
                "file_type": "json",
                "limit": limit,
                "offset": offset,
            },
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("releases") or []
        if not batch:
            break
        for item in batch:
            rid = item.get("id")
            name = item.get("name")
            if rid is not None and name:
                names[int(rid)] = str(name)
        if len(batch) < limit:
            break
        offset += limit
    return names


def _fetch_release_dates(
    client: httpx.Client,
    api_key: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 1000
    while True:
        r = client.get(
            f"{FRED_BASE}/releases/dates",
            params={
                "api_key": api_key,
                "file_type": "json",
                "limit": limit,
                "offset": offset,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        r.raise_for_status()
        data = r.json()
        batch = (
            data.get("release_dates")
            or data.get("releases")
            or data.get("releaseDates")
            or []
        )
        if not isinstance(batch, list):
            batch = []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def _row_release_id(row: dict[str, Any]) -> Optional[int]:
    rid = row.get("release_id")
    if rid is None:
        rid = row.get("id")
    if rid is None:
        return None
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def _row_title(row: dict[str, Any], names: dict[int, str]) -> str:
    for key in ("release_name", "name", "title"):
        v = row.get(key)
        if v:
            return str(v)[:255]
    rid = _row_release_id(row)
    if rid is not None:
        return (names.get(rid) or f"Release {rid}")[:255]
    return "Economic release"


def sync_fred_calendar(db: Session, start_date: date, end_date: date) -> dict[str, Any]:
    api_key = _fred_api_key()
    if not api_key:
        raise ValueError("FRED_API_KEY is not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html")

    start_s = start_date.isoformat()
    end_s = end_date.isoformat()

    inserted = 0
    skipped = 0

    # One-day pulls use release_name rows from /releases/dates; skip huge /releases crawl (timeouts).
    narrow_window = start_date.toordinal() == end_date.toordinal()

    with httpx.Client(timeout=60.0) as client:
        names: dict[int, str] = {} if narrow_window else _fetch_releases_index(client, api_key)
        rows = _fetch_release_dates(client, api_key, start_s, end_s)

    for row in rows:
        rid = _row_release_id(row)
        raw_date = row.get("date")
        if rid is None or not raw_date:
            continue
        try:
            day, ev_time = _parse_date_time(str(raw_date))
        except ValueError:
            continue

        title = _row_title(row, names)
        importance = _guess_importance(title)
        external_id = f"fred:{rid}:{day.isoformat()}"

        status, _ = crud.try_insert_fred_event(
            db,
            title=title,
            event_date=day,
            country="United States",
            regulator="FRED (Federal Reserve Economic Data)",
            importance=importance,
            external_id=external_id,
            event_time=ev_time,
        )
        if status == "inserted":
            inserted += 1
        else:
            skipped += 1

    stats = {
        "fetched": len(rows),
        "inserted": inserted,
        "skipped": skipped,
        "start_date": start_s,
        "end_date": end_s,
        "narrow_window": narrow_window,
    }
    logger.info("fred sync %s", stats)
    return stats


def default_sync_window() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=7), today + timedelta(days=120)
