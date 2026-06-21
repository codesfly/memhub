import pytest
from memhub import db as db_mod


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "test.db")
    db_mod.init_schema(c)
    yield c
    c.close()
