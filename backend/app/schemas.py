from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EventBase(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    date: date
    country: str = Field(min_length=2, max_length=100)
    regulator: str = Field(min_length=2, max_length=150)
    importance: str = Field(pattern="^(low|medium|high)$")
    event_time: Optional[str] = Field(default=None, max_length=16)
    remaining_time: Optional[str] = Field(default=None, max_length=32)
    currency: Optional[str] = Field(default=None, max_length=16)
    actual: Optional[str] = Field(default=None, max_length=64)
    forecast: Optional[str] = Field(default=None, max_length=64)
    previous: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=8000)

    @field_validator("event_time", mode="before")
    @classmethod
    def empty_time_to_none(cls, v):
        if v == "":
            return None
        return v


class EventCreate(EventBase):
    pass


class EventRead(EventBase):
    id: int
    source: str = "manual"
    external_id: Optional[str] = None

    model_config = {"from_attributes": True}


class NewsRead(BaseModel):
    id: int
    title: str
    link: str
    summary: Optional[str] = None
    source_key: str
    source_label: str
    published_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


