import logging
import os
from pathlib import Path
from datetime import date as date_cls
from typing import Generator, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .crud import (
    count_events_on_date_by_source,
    create_event,
    get_events,
    get_news_articles,
    get_news_article_by_id,
)
from .alfaforex_sync import get_description_by_external_id, refresh_if_stale
from .fred_sync import default_sync_window, fred_api_configured, sync_fred_calendar
from .news_scrape import fetch_article_content, refresh_news as refresh_news_feeds
from .database import Base, SessionLocal, engine, ensure_sqlite_columns
from .models import Event
from .schemas import EventCreate, EventRead, NewsRead
from .seed import seed_if_empty

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


def _heavy_startup_sync() -> bool:
    """Long-running Alfa/news sync on startup is skipped on Render to avoid timeouts on cold boot."""
    if (os.getenv("FORCE_STARTUP_SYNC") or "").strip().lower() in ("1", "true", "yes"):
        return True
    return (os.getenv("RENDER") or "").strip().lower() != "true"


app = FastAPI(title="Economic Events API", version="0.6.0")

default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
origins_env = (os.getenv("FRONTEND_ORIGINS") or "").strip()
allow_origins = (
    [x.strip() for x in origins_env.split(",") if x.strip()] if origins_env else default_origins
)
allow_origin_regex = (os.getenv("FRONTEND_ORIGIN_REGEX") or "").strip() or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
ensure_sqlite_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _try_fred_fallback(db: Session) -> Optional[dict]:
    """Fallback source for events when AlfaForex is unavailable/empty."""
    try:
        start_d, end_d = default_sync_window()
        return sync_fred_calendar(db, start_d, end_d)
    except Exception:
        return None


@app.on_event("startup")
def startup_seed():
    with SessionLocal() as db:
        seed_if_empty(db)
        if not _heavy_startup_sync():
            logger.info(
                "Skipping heavy AlfaForex/news startup (Render cold start); data loads on first GET /events or GET /news."
            )
            return
        try:
            refresh_if_stale(db, force=True)
        except Exception:
            # External source might be temporarily unavailable during startup.
            pass
        try:
            refresh_news_feeds(db, force=False)
        except Exception:
            pass


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "features": {"news": True},
        "fred_api_configured": fred_api_configured(),
    }


@app.get("/api/v1/openapi.json", include_in_schema=False)
def openapi_schema_v1():
    """Same JSON as /openapi.json, path aligned with trading-calendar docs style."""
    return JSONResponse(app.openapi())


@app.get("/events", response_model=list[EventRead])
def list_events(
    country: Optional[str] = Query(default=None),
    regulator: Optional[str] = Query(default=None),
    importance: Optional[str] = Query(default=None),
    on_date: Optional[date_cls] = Query(default=None),
    auto_refresh: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    alfaforex_ok = True
    if auto_refresh:
        try:
            refresh_if_stale(db)
        except Exception:
            # Keep API available even if external source is temporarily down.
            alfaforex_ok = False
    rows = get_events(db, country=country, regulator=regulator, importance=importance)
    if not rows and auto_refresh:
        try:
            refresh_if_stale(db, force=True)
            rows = get_events(db, country=country, regulator=regulator, importance=importance)
        except Exception:
            alfaforex_ok = False
    # If AlfaForex path failed or still empty, attempt to backfill from FRED.
    if auto_refresh and (not alfaforex_ok or not rows):
        _try_fred_fallback(db)
        rows = get_events(db, country=country, regulator=regulator, importance=importance)
    # Exact-date UX: DB may have AlfaForex events on other days but none on ``on_date`` —
    # backfill FRED releases for that single day (still kept separate by ``source``).
    if auto_refresh and on_date is not None:
        try:
            if count_events_on_date_by_source(db, on_date, "alfaforex") == 0:
                fred_stats = sync_fred_calendar(db, on_date, on_date)
                rows = get_events(db, country=country, regulator=regulator, importance=importance)
                if not fred_stats.get("fetched"):
                    logger.warning(
                        "FRED returned 0 release rows for %s (check API key / FRED calendar)",
                        on_date.isoformat(),
                    )
        except Exception as exc:
            logger.warning("FRED fill for exact date %s failed: %s", on_date.isoformat(), exc)
    return rows


@app.post("/events", response_model=EventRead, status_code=201)
def add_event(payload: EventCreate, db: Session = Depends(get_db)):
    return create_event(db, payload)


@app.post("/events/refresh")
def refresh_events(db: Session = Depends(get_db)):
    details: dict[str, object] = {}
    try:
        result = refresh_if_stale(db, force=True)
        details["alfaforex"] = result or {"status": "ok"}
    except Exception as e:
        details["alfaforex_error"] = str(e)
    fred_result = _try_fred_fallback(db)
    if fred_result:
        details["fred"] = fred_result
    # If both sources failed, return 502.
    if "alfaforex" not in details and "fred" not in details:
        raise HTTPException(status_code=502, detail=f"Failed to refresh from all sources: {details.get('alfaforex_error', 'unknown error')}")
    return details or {"status": "ok"}


@app.get("/news", response_model=list[NewsRead])
def list_news(
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=120, ge=1, le=250),
    auto_refresh: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    if auto_refresh:
        try:
            refresh_news_feeds(db, force=False)
        except Exception:
            pass
    return get_news_articles(db, source_key=source, limit=limit)


@app.post("/news/refresh")
def refresh_news_route(db: Session = Depends(get_db)):
    try:
        return refresh_news_feeds(db, force=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to refresh news feeds: {e}") from e


@app.get("/news/{article_id}/content")
def news_content(article_id: int, db: Session = Depends(get_db)):
    article = get_news_article_by_id(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")
    try:
        payload = fetch_article_content(article.link)
        payload["degraded"] = False
        return payload
    except ValueError as e:
        fallback = (article.summary or "").strip()
        if fallback:
            return {
                "content": fallback,
                "summary": fallback[:600],
                "degraded": True,
                "note": f"Using fallback summary: {e}",
            }
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        fallback = (article.summary or "").strip()
        if fallback:
            return {
                "content": fallback,
                "summary": fallback[:600],
                "degraded": True,
                "note": f"Source temporarily unavailable: {e}",
            }
        raise HTTPException(status_code=502, detail=f"Failed to fetch source article: {e}") from e


@app.get("/events/{event_id}/description")
def event_description(event_id: int, lang: str = Query(default="ru"), db: Session = Depends(get_db)):
    row = db.get(Event, event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    fallback = row.description or ""
    # For non-AlfaForex/manual events we only have stored description.
    if row.source != "alfaforex" or not row.external_id:
        return {"description": fallback}

    if (lang or "").lower() == "ru":
        return {"description": fallback}

    try:
        translated = get_description_by_external_id(row.external_id, lang=lang)
    except Exception:
        translated = None
    return {"description": translated or fallback}
