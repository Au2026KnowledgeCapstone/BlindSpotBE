from sqlalchemy.orm import configure_mappers

from app.core.db import Base
import app.models


def test_every_model_imports_and_maps_without_error():
    configure_mappers()
    tables = Base.metadata.tables
    assert "blindspot.requirements" in tables
    assert "blindspot.results" in tables
    assert "public.projects" in tables
