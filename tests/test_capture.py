import json
from unittest.mock import patch, MagicMock

from memhub.capture import LLMCapturer, RawCapturer


def test_raw_capturer_returns_chunks():
    cap = RawCapturer(max_chars=20)
    text = "a" * 50
    items = cap.capture(text, {})
    assert len(items) == 3  # 50 chars / 20 -> 3 chunks
    assert all(it["kind"] == "raw" for it in items)
    assert all(it["scope"] == "current" for it in items)


def test_raw_capturer_empty_text():
    assert RawCapturer().capture("   ", {}) == []


def _fake_run(stdout):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = 0
    return m


def test_llm_capturer_parses_json():
    out = json.dumps([{"content": "use JWT", "kind": "decision", "tags": [], "scope": "global"}])
    with patch("memhub.capture.subprocess.run", return_value=_fake_run(out)):
        items = LLMCapturer().capture("transcript text", {})
    assert items[0]["content"] == "use JWT"
    assert items[0]["kind"] == "decision"


def test_llm_capturer_handles_fenced_json():
    out = "```json\n[{\"content\":\"x\",\"kind\":\"fact\",\"tags\":[],\"scope\":\"current\"}]\n```"
    with patch("memhub.capture.subprocess.run", return_value=_fake_run(out)):
        items = LLMCapturer().capture("t", {})
    assert items[0]["content"] == "x"


def test_llm_capturer_raises_on_bad_output():
    with patch("memhub.capture.subprocess.run", return_value=_fake_run("not json at all")):
        try:
            LLMCapturer().capture("t", {})
            assert False, "expected CaptureError"
        except Exception as e:
            assert "parse" in str(e).lower() or "json" in str(e).lower()


def test_llm_capturer_raises_on_timeout():
    import subprocess as sp
    with patch("memhub.capture.subprocess.run", side_effect=sp.TimeoutExpired("claude", 60)):
        try:
            LLMCapturer().capture("t", {})
            assert False, "expected error"
        except Exception:
            pass
