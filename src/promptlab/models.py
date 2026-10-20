"""ORM models. This module is the single source of truth for the relational schema."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptlab.db import Base, UTCDateTime, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")
EventId = BigInteger().with_variant(Integer(), "sqlite")


class Role(enum.StrEnum):
    """API key roles, ordered from least to most privileged."""

    RUNTIME = "runtime"
    EDITOR = "editor"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return list(Role).index(self)

    def allows(self, required: Role) -> bool:
        return self.rank >= required.rank


class ExperimentStatus(enum.StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(_enum(Role, "api_key_role"), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Prompt(TimestampMixin, Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", passive_deletes=True
    )
    labels: Mapped[list[PromptLabel]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", passive_deletes=True
    )


class PromptVersion(TimestampMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_id_version"),
        Index("ix_prompt_versions_prompt_id_content_hash", "prompt_id", "content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    model_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType, nullable=False, default=dict
    )
    commit_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    prompt: Mapped[Prompt] = relationship(back_populates="versions")


class PromptLabel(Base):
    __tablename__ = "prompt_labels"
    __table_args__ = (
        UniqueConstraint("prompt_id", "name", name="uq_prompt_labels_prompt_id_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    prompt: Mapped[Prompt] = relationship(back_populates="labels")
    version: Mapped[PromptVersion] = relationship(lazy="joined")


class LabelEvent(TimestampMixin, Base):
    """Append-only audit trail of label moves (``None`` means created/deleted)."""

    __tablename__ = "label_events"
    __table_args__ = (Index("ix_label_events_prompt_id_label", "prompt_id", "label", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    from_version: Mapped[int | None] = mapped_column(Integer)
    to_version: Mapped[int | None] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class Experiment(TimestampMixin, Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("prompt_id", "name", name="uq_experiments_prompt_id_name"),
        Index("ix_experiments_prompt_id_status", "prompt_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ExperimentStatus] = mapped_column(
        _enum(ExperimentStatus, "experiment_status"),
        nullable=False,
        default=ExperimentStatus.DRAFT,
    )
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    traffic_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    primary_metric: Mapped[str] = mapped_column(String(64), nullable=False, default="conversion")
    fallback_label: Mapped[str] = mapped_column(String(64), nullable=False, default="production")
    winner_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("experiment_variants.id", ondelete="SET NULL", use_alter=True)
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    prompt: Mapped[Prompt] = relationship()
    variants: Mapped[list[ExperimentVariant]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExperimentVariant.position",
        foreign_keys="ExperimentVariant.experiment_id",
    )


class ExperimentVariant(Base):
    __tablename__ = "experiment_variants"
    __table_args__ = (
        UniqueConstraint("experiment_id", "key", name="uq_experiment_variants_experiment_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    experiment: Mapped[Experiment] = relationship(
        back_populates="variants", foreign_keys=[experiment_id]
    )
    version: Mapped[PromptVersion] = relationship(lazy="joined")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_experiment_id_name_variant_id", "experiment_id", "name", "variant_id"),
        Index("ix_events_experiment_id_subject_id", "experiment_id", "subject_id"),
        UniqueConstraint("experiment_id", "event_id", name="uq_events_experiment_id_event_id"),
    )

    id: Mapped[int] = mapped_column(EventId, primary_key=True, autoincrement=True)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiment_variants.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    event_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


EXPOSURE_EVENT = "exposure"
