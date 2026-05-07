from typing import Optional, Tuple

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas


def get_events(
    db: Session,
    country: Optional[str] = None,
    regulator: Optional[str] = None,
    importance: Optional[str] = None,
):
    stmt = select(models.Event).order_by(models.Event.date.asc(), models.Event.id.asc())

    if country:
        stmt = stmt.where(models.Event.country == country)
    if regulator:
        stmt = stmt.where(models.Event.regulator == regulator)
    if importance:
        stmt = stmt.where(models.Event.importance == importance)

    return db.execute(stmt).scalars().all()


def create_event(db: Session, event_in: schemas.EventCreate):
    data = event_in.model_dump()
    event = models.Event(
        title=data["title"],
        date=data["date"],
        country=data["country"],
        regulator=data["regulator"],
        importance=data["importance"],
        event_time=data.get("event_time"),
        remaining_time=data.get("remaining_time"),
        currency=data.get("currency"),
        actual=data.get("actual"),
        forecast=data.get("forecast"),
        previous=data.get("previous"),
        description=data.get("description"),
        source="manual",
        external_id=None,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def try_insert_fred_event(
    db: Session,
    *,
    title: str,
    event_date,
    country: str,
    regulator: str,
    importance: str,
    external_id: str,
    event_time: Optional[str] = None,
) -> Tuple[str, Optional[models.Event]]:
    existing = db.scalar(select(models.Event).where(models.Event.external_id == external_id))
    if existing is not None:
        return "skipped", None

    event = models.Event(
        title=title,
        date=event_date,
        country=country,
        regulator=regulator,
        importance=importance,
        event_time=event_time,
        source="fred",
        external_id=external_id,
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
        return "inserted", event
    except IntegrityError:
        db.rollback()
        return "skipped", None


def upsert_external_event(
    db: Session,
    *,
    external_id: str,
    title: str,
    event_date,
    country: str,
    regulator: str,
    importance: str,
    source: str,
    event_time: Optional[str] = None,
    remaining_time: Optional[str] = None,
    currency: Optional[str] = None,
    actual: Optional[str] = None,
    forecast: Optional[str] = None,
    previous: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    existing = db.scalar(select(models.Event).where(models.Event.external_id == external_id))
    if existing is None:
        event = models.Event(
            title=title,
            date=event_date,
            country=country,
            regulator=regulator,
            importance=importance,
            event_time=event_time,
            remaining_time=remaining_time,
            currency=currency,
            actual=actual,
            forecast=forecast,
            previous=previous,
            description=description,
            source=source,
            external_id=external_id,
        )
        db.add(event)
        try:
            db.commit()
            return "inserted"
        except IntegrityError:
            db.rollback()
            return "skipped"

    changed = False
    for attr, value in (
        ("title", title),
        ("date", event_date),
        ("country", country),
        ("regulator", regulator),
        ("importance", importance),
        ("event_time", event_time),
        ("remaining_time", remaining_time),
        ("currency", currency),
        ("actual", actual),
        ("forecast", forecast),
        ("previous", previous),
        ("description", description),
        ("source", source),
    ):
        if getattr(existing, attr) != value:
            setattr(existing, attr, value)
            changed = True

    if not changed:
        return "skipped"

    db.add(existing)
    db.commit()
    return "updated"


def backfill_external_descriptions(db: Session, descriptions: dict[str, str]) -> int:
    if not descriptions:
        return 0
    rows = (
        db.execute(
            select(models.Event).where(
                models.Event.external_id.is_not(None),
                models.Event.external_id.in_(list(descriptions.keys())),
            )
        )
        .scalars()
        .all()
    )
    changed = 0
    for row in rows:
        new_value = descriptions.get(row.external_id or "")
        if new_value and row.description != new_value:
            row.description = new_value
            changed += 1
    if changed:
        db.commit()
    return changed


def get_news_articles(db: Session, source_key: Optional[str] = None, limit: int = 120):
    sort_ts = func.coalesce(models.NewsArticle.published_at, models.NewsArticle.fetched_at)
    stmt = select(models.NewsArticle).order_by(sort_ts.desc(), models.NewsArticle.id.desc())
    if source_key:
        stmt = stmt.where(models.NewsArticle.source_key == source_key)
    stmt = stmt.limit(limit)
    return db.execute(stmt).scalars().all()


def get_news_article_by_id(db: Session, article_id: int):
    return db.get(models.NewsArticle, article_id)


def upsert_news_article(
    db: Session,
    *,
    link: str,
    title: str,
    summary: Optional[str],
    source_key: str,
    source_label: str,
    published_at: Optional[datetime],
):
    existing = db.scalar(select(models.NewsArticle).where(models.NewsArticle.link == link))
    if existing is None:
        row = models.NewsArticle(
            link=link,
            title=title,
            summary=summary,
            source_key=source_key,
            source_label=source_label,
            published_at=published_at,
        )
        db.add(row)
        db.commit()
        return "inserted"
    changed = False
    for attr, value in (
        ("title", title),
        ("summary", summary),
        ("source_key", source_key),
        ("source_label", source_label),
        ("published_at", published_at),
    ):
        if getattr(existing, attr) != value:
            setattr(existing, attr, value)
            changed = True
    if changed:
        db.add(existing)
        db.commit()
        return "updated"
    return "skipped"


def prune_old_news(db: Session, keep: int = 250):
    sort_ts = func.coalesce(models.NewsArticle.published_at, models.NewsArticle.fetched_at)
    subq = (
        select(models.NewsArticle.id).order_by(sort_ts.desc(), models.NewsArticle.id.desc()).limit(keep)
    )
    # SQLite-friendly: delete rows whose id NOT IN (...)
    ids = db.execute(subq).scalars().all()
    if not ids:
        return 0
    res = db.execute(delete(models.NewsArticle).where(~models.NewsArticle.id.in_(ids)))
    db.commit()
    return int(res.rowcount or 0)
