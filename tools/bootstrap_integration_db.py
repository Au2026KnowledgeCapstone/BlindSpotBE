"""Bootstrap ONLY an explicitly supplied disposable local PostgreSQL database."""
import os
from urllib.parse import urlsplit
from sqlalchemy import create_engine, text
from app.core.db import Base
import app.models

url = os.environ["BLINDSPOT_TEST_DATABASE_URL"]
parsed = urlsplit(url)
if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.path.endswith("_integration"):
    raise SystemExit("Requires a local disposable database ending in _integration")
engine = create_engine(url)
with engine.begin() as connection:
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS blindspot"))
    Base.metadata.create_all(connection, tables=[t for t in Base.metadata.sorted_tables if t.schema == "public"])
