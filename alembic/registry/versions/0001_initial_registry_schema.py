"""initial registry schema

Revision ID: 0001_initial_registry_schema
Revises: 
Create Date: 2026-08-28 06:38:34.914891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '0001_initial_registry_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('novels',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('created_at', sa.String(), nullable=False),
    sa.Column('is_active', sa.Integer(), server_default='0', nullable=False),
    sa.Column('deleted_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('pinned_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('novels')
