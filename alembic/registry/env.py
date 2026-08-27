"""Alembic env for registry _registry.sqlite3, targeted via `-x db=<path>`."""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from repositories.registry_models import REGISTRY_METADATA

target_metadata = REGISTRY_METADATA


def _db_url() -> str:
    xargs = context.get_x_argument(as_dictionary=True)
    db = xargs.get("db") or context.config.attributes.get("db")
    if not db:
        raise RuntimeError("pass -x db=<path to _registry.sqlite3> or set config.attributes['db']")
    return db if db.startswith("sqlite") else f"sqlite:///{db}"


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_db_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
