import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Context(Base):
    __tablename__ = "contexts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context_type: Mapped[str] = mapped_column(String(32), default="topic", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    owner_email: Mapped[str] = mapped_column(String(200), default="")
    color: Mapped[str] = mapped_column(String(16), default="#5b5ce2")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    resources: Mapped[list["Resource"]] = relationship(
        back_populates="context", cascade="all, delete-orphan", order_by="Resource.occurred_at.desc()"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="context", cascade="all, delete-orphan", order_by="Activity.created_at.desc()"
    )


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("context_id", "source", "external_id", name="uq_context_source_external"),
        Index("ix_resources_source_external", "source", "external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    context_id: Mapped[str] = mapped_column(ForeignKey("contexts.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(24), index=True)
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), default="item")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(160), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    context: Mapped[Context] = relationship(back_populates="resources")


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    context_id: Mapped[str] = mapped_column(ForeignKey("contexts.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(String(300), default="")
    actor: Mapped[str] = mapped_column(String(160), default="Context Hub")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    context: Mapped[Context] = relationship(back_populates="activities")


class Connector(Base):
    __tablename__ = "connectors"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="disconnected", nullable=False)
    configuration_secret: Mapped[str] = mapped_column(Text, default="", nullable=False)
    credentials_secret: Mapped[str] = mapped_column(Text, default="", nullable=False)
    external_account: Mapped[str] = mapped_column(String(240), default="")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
