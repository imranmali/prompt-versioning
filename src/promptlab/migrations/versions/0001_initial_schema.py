"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-20 11:54:32.197848
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "runtime", "editor", "admin", name="api_key_role", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", JSON_TYPE, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompts")),
        sa.UniqueConstraint("name", name=op.f("uq_prompts_name")),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "running",
                "paused",
                "completed",
                name="experiment_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("traffic_percent", sa.Integer(), nullable=False),
        sa.Column("primary_metric", sa.String(length=64), nullable=False),
        sa.Column("fallback_label", sa.String(length=64), nullable=False),
        sa.Column("winner_variant_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_experiments_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
        sa.UniqueConstraint("prompt_id", "name", name="uq_experiments_prompt_id_name"),
    )
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_experiments_prompt_id_status", ["prompt_id", "status"], unique=False
        )

    op.create_table(
        "label_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=True),
        sa.Column("to_version", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_label_events_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_label_events")),
    )
    with op.batch_alter_table("label_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_label_events_prompt_id_label", ["prompt_id", "label", "created_at"], unique=False
        )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("variables", JSON_TYPE, nullable=False),
        sa.Column("model_settings", JSON_TYPE, nullable=False),
        sa.Column("metadata", JSON_TYPE, nullable=False),
        sa.Column("commit_message", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_prompt_versions_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_id_version"),
    )
    with op.batch_alter_table("prompt_versions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_prompt_versions_prompt_id_content_hash", ["prompt_id", "content_hash"], unique=False
        )

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("is_control", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_experiment_variants_experiment_id_experiments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_experiment_variants_version_id_prompt_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_variants")),
        sa.UniqueConstraint(
            "experiment_id", "key", name="uq_experiment_variants_experiment_id_key"
        ),
    )
    # experiments <-> experiment_variants is a cycle: add the winner FK once both tables exist.
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.create_foreign_key(
            "fk_experiments_winner_variant_id_experiment_variants",
            "experiment_variants",
            ["winner_variant_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "prompt_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_prompt_labels_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_labels_version_id_prompt_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_labels")),
        sa.UniqueConstraint("prompt_id", "name", name="uq_prompt_labels_prompt_id_name"),
    )
    op.create_table(
        "events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_events_experiment_id_experiments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["experiment_variants.id"],
            name=op.f("fk_events_variant_id_experiment_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("experiment_id", "event_id", name="uq_events_experiment_id_event_id"),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_events_experiment_id_name_variant_id",
            ["experiment_id", "name", "variant_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_events_experiment_id_subject_id", ["experiment_id", "subject_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index("ix_events_experiment_id_subject_id")
        batch_op.drop_index("ix_events_experiment_id_name_variant_id")

    op.drop_table("events")
    op.drop_table("prompt_labels")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_experiments_winner_variant_id_experiment_variants", type_="foreignkey"
        )
    op.drop_table("experiment_variants")
    with op.batch_alter_table("prompt_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_prompt_versions_prompt_id_content_hash")

    op.drop_table("prompt_versions")
    with op.batch_alter_table("label_events", schema=None) as batch_op:
        batch_op.drop_index("ix_label_events_prompt_id_label")

    op.drop_table("label_events")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_index("ix_experiments_prompt_id_status")

    op.drop_table("experiments")
    op.drop_table("prompts")
    op.drop_table("api_keys")
