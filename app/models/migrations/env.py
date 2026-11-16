from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.core.config import get_settings
from app.core.db import Base
from app import models  # noqa: F401 — registers tables on Base.metadata
from app.models.migration_filters import TARGET_SCHEMA, include_name, include_object

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=TARGET_SCHEMA,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(
        url=get_settings().database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # A role named "blindspot" otherwise makes that schema PostgreSQL's
        # implicit default ($user). Alembic then reflects it as schema=None and
        # the ownership filter misses every existing application table.
        # Public must also stay out of search_path: otherwise PostgreSQL
        # omits its schema on reflected foreign keys and creates false drift.
        connection.exec_driver_sql("SET SESSION search_path TO pg_catalog")
        connection.commit()
        connection.dialect.default_schema_name = "pg_catalog"
        _configure(connection=connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
