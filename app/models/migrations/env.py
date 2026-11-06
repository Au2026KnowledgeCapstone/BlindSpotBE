from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.core.config import get_settings
from app.core.db import Base
from app import models  # noqa: F401 — registers tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# BE's Alembic owns the `blindspot` schema only. Everything else — public,
# auth, storage, realtime — belongs to Supabase's own migration history.
# Without this filter, autogenerate would cheerfully propose dropping every
# table it does not recognise.
TARGET_SCHEMA = "blindspot"


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == TARGET_SCHEMA
    return True


def include_object(object, name, type_, reflected, compare_to):
    schema = getattr(object, "schema", None)
    if schema is None and hasattr(object, "table"):
        schema = object.table.schema
    return schema == TARGET_SCHEMA


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
        _configure(connection=connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
