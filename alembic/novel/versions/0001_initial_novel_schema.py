"""initial novel schema

This is the schema as it existed before the optimistic-concurrency `version`
columns were added (i.e. what sqlite_store._DDL originally created + what the
JSON->SQLite migration produced). The `version` columns land in 0002 -- split
this way so the ~5 legacy dbs that have the tables but never got the runtime
_ensure_version_columns() ALTER can be stamped at 0001 and then upgraded, rather
than mis-stamped at head with a column still missing.

Revision ID: 0001_initial_novel_schema
Revises:
Create Date: 2026-08-28 06:38:34.262597

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import repositories.db_types

# revision identifiers, used by Alembic.
revision: str = '0001_initial_novel_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('documents',
    sa.Column('doc_key', sa.String(), nullable=False),
    sa.Column('data_json', repositories.db_types.JSONText(), nullable=False),
    sa.PrimaryKeyConstraint('doc_key')
    )
    op.create_table('lore_characters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('data_json', repositories.db_types.JSONText(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('plot_chapters',
    sa.Column('chapter', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('data_json', repositories.db_types.JSONText(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('chapter')
    )
    op.create_table('sandbox_events',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('chapter', sa.Integer(), nullable=False),
    sa.Column('turn_index', sa.Integer(), nullable=False),
    sa.Column('entry_json', repositories.db_types.JSONText(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('session_messages',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('content', sa.String(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('ts', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('vector_chunks',
    sa.Column('collection', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('document', sa.String(), nullable=False),
    sa.Column('metadata_json', repositories.db_types.JSONText(), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=False),
    sa.PrimaryKeyConstraint('collection', 'id')
    )
    op.create_table('character_archives',
    sa.Column('character_id', sa.Integer(), nullable=False),
    sa.Column('chapter', sa.Integer(), nullable=False),
    sa.Column('data_json', repositories.db_types.JSONText(), nullable=False),
    sa.ForeignKeyConstraint(['chapter'], ['plot_chapters.chapter'], ),
    sa.ForeignKeyConstraint(['character_id'], ['lore_characters.id'], ),
    sa.PrimaryKeyConstraint('character_id', 'chapter')
    )
    op.create_table('relationship_edges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('from_character_id', sa.Integer(), nullable=False),
    sa.Column('to_character_id', sa.Integer(), nullable=False),
    sa.Column('nature', sa.String(), server_default='', nullable=False),
    sa.Column('relationship_anchor', sa.String(), server_default='', nullable=False),
    sa.Column('from_ref_terms_json', repositories.db_types.JSONText(), server_default='[]', nullable=False),
    sa.Column('to_ref_terms_json', repositories.db_types.JSONText(), server_default='[]', nullable=False),
    sa.Column('deleted', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['from_character_id'], ['lore_characters.id'], ),
    sa.ForeignKeyConstraint(['to_character_id'], ['lore_characters.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('timeline_snapshots',
    sa.Column('character_id', sa.Integer(), nullable=False),
    sa.Column('chapter', sa.Integer(), nullable=False),
    sa.Column('stage', sa.Integer(), nullable=False),
    sa.Column('delta_json', repositories.db_types.JSONText(), nullable=False),
    sa.ForeignKeyConstraint(['chapter'], ['plot_chapters.chapter'], ),
    sa.ForeignKeyConstraint(['character_id'], ['lore_characters.id'], ),
    sa.PrimaryKeyConstraint('character_id', 'chapter', 'stage')
    )


def downgrade() -> None:
    op.drop_table('timeline_snapshots')
    op.drop_table('relationship_edges')
    op.drop_table('character_archives')
    op.drop_table('vector_chunks')
    op.drop_table('session_messages')
    op.drop_table('sandbox_events')
    op.drop_table('plot_chapters')
    op.drop_table('lore_characters')
    op.drop_table('documents')
