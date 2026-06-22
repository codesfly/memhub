from memhub import memsync


def _write(root, project, name, frontmatter, body):
    d = root / project / "memory"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.md"
    f.write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return f


def test_sync_ingests_memory_file(conn, tmp_path):
    root = tmp_path / "projects"
    _write(root, "-Users-jiumu-Desktop-douyin", "pnpm-rule",
           "name: pnpm-rule\ndescription: 用 pnpm\nmetadata:\n  type: convention",
           "团队约定：统一用 pnpm，禁止 npm。")
    res = memsync.sync_memory_files(conn, root)
    assert res["stored"] == 1
    row = conn.execute("SELECT content, kind, agent, project FROM memories").fetchone()
    assert "pnpm" in row[0]
    assert row[1] == "note"
    assert row[2] == "claude-memory"
    assert "douyin" in row[3]


def test_sync_skips_memory_index_file(conn, tmp_path):
    root = tmp_path / "projects"
    d = root / "proj" / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text("- [x](x.md) — 索引行\n")
    res = memsync.sync_memory_files(conn, root)
    assert res["stored"] == 0
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0


def test_sync_is_idempotent_on_rerun(conn, tmp_path):
    root = tmp_path / "projects"
    _write(root, "proj", "a", "name: a", "一条耐久的记忆事实，足够长可入库。")
    memsync.sync_memory_files(conn, root)
    memsync.sync_memory_files(conn, root)  # 再跑一次，content_hash 去重，不应新增
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_sync_respects_since_ts(conn, tmp_path):
    root = tmp_path / "projects"
    f = _write(root, "proj", "a", "name: a", "旧记忆内容。")
    res = memsync.sync_memory_files(conn, root, since_ts=f.stat().st_mtime + 100)
    assert res["stored"] == 0
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0


def test_sync_returns_high_water_mtime(conn, tmp_path):
    root = tmp_path / "projects"
    f = _write(root, "proj", "a", "name: a", "记忆内容足够长以便入库。")
    res = memsync.sync_memory_files(conn, root)
    assert res["max_mtime"] >= f.stat().st_mtime
