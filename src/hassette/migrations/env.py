from alembic import context
from sqlalchemy import create_engine


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a database connection."""
    url = context.config.get_main_option("sqlalchemy.url")
    if url is None:
        msg = "sqlalchemy.url must be set in Alembic config"
        raise RuntimeError(msg)
    connectable = create_engine(url)

    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=None)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


run_migrations_online()
