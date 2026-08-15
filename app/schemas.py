from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SourceName = Literal["gmail", "chat", "drive", "calendar", "odoo"]
ContextType = Literal["project", "client", "opportunity", "activity", "topic"]
ContextStatus = Literal["active", "watching", "archived"]


class ResourceCreate(BaseModel):
    source: SourceName
    external_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    resource_type: str = Field(default="item", max_length=64)
    excerpt: str = Field(default="", max_length=2000)
    author_name: str = Field(default="", max_length=160)
    occurred_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    context_id: str
    source: SourceName
    external_id: str
    title: str
    url: str
    resource_type: str
    excerpt: str
    author_name: str
    occurred_at: datetime
    extra: dict[str, Any]
    created_at: datetime


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    detail: str
    actor: str
    created_at: datetime


class ContextCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    summary: str = Field(default="", max_length=5000)
    context_type: ContextType = "project"
    status: ContextStatus = "active"
    priority: Literal["low", "normal", "high"] = "normal"
    owner_name: str = Field(default="", max_length=120)
    owner_email: str = Field(default="", max_length=200)
    color: str = "#5b5ce2"
    tags: list[str] = Field(default_factory=list, max_length=20)
    due_at: datetime | None = None

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip()[:40] for tag in value if tag.strip()))


class ContextUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)
    context_type: ContextType | None = None
    status: ContextStatus | None = None
    priority: Literal["low", "normal", "high"] | None = None
    owner_name: str | None = Field(default=None, max_length=120)
    owner_email: str | None = Field(default=None, max_length=200)
    color: str | None = None
    tags: list[str] | None = None
    due_at: datetime | None = None


class ContextListItem(BaseModel):
    id: str
    title: str
    summary: str
    context_type: str
    status: str
    priority: str
    owner_name: str
    owner_email: str
    color: str
    tags: list[str]
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    resource_count: int
    sources: list[str]
    latest_resource_at: datetime | None


class ContextDetail(ContextListItem):
    resources: list[ResourceRead]
    activities: list[ActivityRead]


class DashboardStats(BaseModel):
    total_contexts: int
    active_contexts: int
    linked_resources: int
    due_soon: int
    by_source: dict[str, int]


class OdooReferenceCreate(ResourceCreate):
    source: Literal["odoo"] = "odoo"
