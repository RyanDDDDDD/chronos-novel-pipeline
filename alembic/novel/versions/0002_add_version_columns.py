"""add optimistic-concurrency version columns

Adds `version` to lore_characters / plot_chapters / documents -- the column the
retired sqlite_store._ensure_version_columns() used to add at runtime. Legacy
dbs that already have it (via that runtime hook) are stamped straight at head and
never run this; only the never-hooked scaffolds and fresh dbs apply it.

Revision ID: 0002_add_version_columns
Revises: 0001_initial_novel_schema
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_version_columns"
down_revision: Union[str, None] = "0001_initial_novel_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("lore_characters", "plot_chapters", "documents")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "version")
