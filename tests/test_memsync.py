from memhub import memsync


def _write(root, project, name, frontmatter, body):
    d = root / project / "memory"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.md"
    f.write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return f


def test_sync_scopes_only_user_type_as_global(conn, tmp_path):
    root = tmp_path / "projects"
    _write(root, "-Users-jiumu-Desktop-douyin", "u", "name: u\nmetadata:\n  type: user", "用户身份：15 年全栈")
    _write(root, "-Users-jiumu-Desktop-douyin", "fb", "name: fb\nmetadata:\n  type: feedback", "douyin 项目的反馈指引细节")
    memsync.sync_memory_files(conn, root)
    scopes = dict(conn.execute(
        "SELECT json_extract(tags,'$[0]'), scope FROM memories WHERE agent='claude-memory'").fetchall())
    assert scopes["user"] == "global"      # user identity — cross-project
    assert scopes["feedback"] == "current"  # project-local guidance, NOT global


def test_sync_resolves_real_cwd_as_project(conn, tmp_path):
    import json
    root = tmp_path / "projects"
    pdir = root / "-Users-jiumu-Desktop-douyin"
    (pdir / "memory").mkdir(parents=True)
    (pdir / "sess.jsonl").write_text(
        json.dumps({"type": "user", "cwd": "/Users/jiumu/Desktop/douyin",
                    "message": {"content": "hi"}}) + "\n")
    (pdir / "memory" / "a.md").write_text("---\nname: a\n---\n一条 douyin 项目的记忆内容。\n")
    memsync.sync_memory_files(conn, root)
    proj = conn.execute("SELECT project FROM memories WHERE agent='claude-memory'").fetchone()[0]
    assert proj == "/Users/jiumu/Desktop/douyin"  # the cwd inject/capture send, not a short label


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


def test_sync_updates_memory_when_file_edited(conn, tmp_path):
    root = tmp_path / "projects"
    f = _write(root, "proj", "a", "name: a", "第一版：关于 pnpm 的团队约定细节。")
    memsync.sync_memory_files(conn, root)
    # edit the file's body, then re-sync
    f.write_text("---\nname: a\n---\n第二版：约定改成 yarn，补充了不少新的说明内容。\n")
    memsync.sync_memory_files(conn, root)
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1  # updated, not duplicated
    content = conn.execute("SELECT content FROM memories").fetchone()[0]
    assert "第二版" in content and "yarn" in content


def test_sync_removes_memory_when_file_deleted(conn, tmp_path):
    root = tmp_path / "projects"
    fa = _write(root, "proj", "a", "name: a", "记忆 A 的内容足够长可入库。")
    _write(root, "proj", "b", "name: b", "记忆 B 的内容足够长可入库。")
    memsync.sync_memory_files(conn, root)
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2
    fa.unlink()  # 删掉文件 a
    res = memsync.sync_memory_files(conn, root)
    assert res["deleted"] == 1
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert "记忆 B" in conn.execute("SELECT content FROM memories").fetchone()[0]


def test_sync_deletion_spares_non_file_memories(conn, tmp_path):
    from memhub import store
    root = tmp_path / "projects"
    store.store_memory(conn, content="手动笔记，不是文件来源的记忆", project="x", agent="manual", kind="note")
    _write(root, "proj", "a", "name: a", "文件来源的记忆 A。")
    memsync.sync_memory_files(conn, root)
    import shutil
    shutil.rmtree(root)  # 删掉所有 memory 文件
    memsync.sync_memory_files(conn, root)
    # 手动笔记必须留存，只移除文件来源的那条
    assert conn.execute("SELECT count(*) FROM memories WHERE agent='manual'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM memories WHERE agent='claude-memory'").fetchone()[0] == 0
