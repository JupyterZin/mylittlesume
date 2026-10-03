from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import talos.db.models  # noqa: F401  (registra as tabelas)

config = context.config
target_metadata = SQLModel.metadata


def run_migrations() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
