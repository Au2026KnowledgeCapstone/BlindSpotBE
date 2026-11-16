from sqlalchemy import text

from app.core.db import get_db


def test_get_db_select_1():
    gen = get_db()
    db = next(gen)
    try:
        assert db.execute(text("SELECT 1")).scalar() == 1
    finally:
        gen.close()
