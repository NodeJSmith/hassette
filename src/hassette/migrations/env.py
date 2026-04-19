from alembic import context
from sqlalchemy import create_engine, event


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a database connection."""
    url = context.config.get_main_option("sqlalchemy.url")
    if url is None:
        msg = "sqlalchemy.url must be set in Alembic config"
        raise RuntimeError(msg)
    connectable = create_engine(url)

    @event.listens_for(connectable, "connect")
    def _set_sqlite_fk_pragma(dbapi_conn: object, _connection_record: object) -> None:  # pyright: ignore[reportUnusedFunction]
        cursor = dbapi_conn.execute("PRAGMA foreign_keys = ON")  # pyright: ignore[reportAttributeAccessIssue]
        cursor.close()  # pyright: ignore[reportAttributeAccessIssue]

    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=None)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


run_migrations_online()
