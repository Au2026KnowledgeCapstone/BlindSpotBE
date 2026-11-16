"""The autogenerate filter, shared by env.py and its regression test so the
test exercises the real thing rather than a reimplementation of it.

BE's Alembic owns the `blindspot` schema only. Everything else — public,
auth, storage, realtime — belongs to Supabase's own migration history.
Without this filter, autogenerate would cheerfully propose dropping every
table it does not recognise."""

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
