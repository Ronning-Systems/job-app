from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Reuse the app's Base.metadata (single source of truth for the schema)
# and the app's DATABASE_URL resolution (DATABASE_URL env var -> Postgres,
# falling back to local SQLite). This keeps alembic and the runtime app
# pointed at the same database with the same model definitions — no
# duplicated config.
import models  # noqa: E402  (must come after config setup so logging is ready)

target_metadata = models.Base.metadata

# Pull the DB URL from the same place models.py does. Override via the
# sqlalchemy.url key in alembic.ini (or -x sqlalchemy.url=...) if needed.
config.set_main_option("sqlalchemy.url", str(models.engine.url))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to stdout without connecting to the DB. Useful for
    reviewing what a migration will do before applying it.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the DB and applies the migrations in a transaction.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()