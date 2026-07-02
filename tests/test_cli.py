import json
from unittest.mock import patch, MagicMock
from memhub import cli

def _resp(obj):
    m = MagicMock(); m.read.return_value = json.dumps(obj).encode()
    m.__enter__ = lambda s: m; m.__exit__ = lambda *a: False
    return m

def test_list_calls_memories_endpoint(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"memories": [
        {"id": 1, "content": "hi", "kind": "fact", "project": "p1", "agent": "x", "created_at": 0}]})):
        cli.main(["list", "--project", "p1"])
    assert "hi" in capsys.readouterr().out

def test_search_calls_search_endpoint(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"results": [
        {"id": 2, "content": "jwt auth", "kind": "decision", "project": "p1", "agent": "x", "created_at": 0}]})):
        cli.main(["search", "auth"])
    assert "jwt auth" in capsys.readouterr().out

def test_delete_calls_delete(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"deleted": True})):
        cli.main(["delete", "5", "--yes"])
    assert "deleted" in capsys.readouterr().out.lower()


def test_clear_pending_calls_capture_pending_endpoint(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"deleted": 3})):
        cli.main(["clear-pending", "--yes"])
    assert "3" in capsys.readouterr().out


def test_reindex_runs_directly_on_db(tmp_path, capsys):
    # reindex is an offline maintenance command: it touches the db file directly,
    # no running service required
    from memhub import db as db_mod, store
    p = tmp_path / "r.db"
    c = db_mod.connect(p)
    db_mod.init_schema(c)
    store.store_memory(c, "reindex me 重建索引内容", project="p", agent="x")
    c.close()
    rc = cli.main(["reindex", "--db", str(p), "--yes"])
    assert rc == 0
    assert "1" in capsys.readouterr().out
