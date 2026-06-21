import json
from memhub.transcript import parse_transcript

def _write(tmp_path, rows):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return str(p)

def test_extracts_user_str_and_assistant_text(tmp_path):
    path = _write(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "how do I add auth"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": "use JWT tokens"},
            {"type": "tool_use", "name": "Bash"},
        ]}},
        {"type": "queue-operation", "content": "ignored"},
        {"type": "system", "content": "ignored"},
    ])
    out = parse_transcript(path)
    assert "how do I add auth" in out
    assert "use JWT tokens" in out
    assert "ignored" not in out

def test_tolerates_bad_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('not json\n{"type":"user","message":{"content":"ok"}}\n{bad}\n')
    out = parse_transcript(str(p))
    assert "ok" in out

def test_empty_returns_empty(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("")
    assert parse_transcript(str(p)) == ""
