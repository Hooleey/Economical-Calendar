from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Date, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    regulator: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    importance: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    event_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    remaining_time: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    actual: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    forecast: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    previous: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'manual'"),
        index=True,
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    link: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(160), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
