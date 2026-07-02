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


def test_raw_capturer_caps_chunks_keeping_tail():
    # a giant transcript must not flood the store; the END of a session holds
    # the conclusions, so the tail is what survives
    cap = RawCapturer(max_chars=10, max_chunks=3)
    text = "".join(f"{i:02d}abcdefgh" for i in range(10))  # 100 chars = 10 uncapped chunks
    items = cap.capture(text, {})
    assert len(items) == 3
    assert items[-1]["content"] == text[-10:]
    assert items[0]["content"] == text[-30:-20]


def test_raw_capturer_default_cap_bounds_giant_transcript():
    from memhub import config
    items = RawCapturer().capture("x" * (1000 * (config.RAW_MAX_CHUNKS + 25)), {})
    assert len(items) == config.RAW_MAX_CHUNKS


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


def test_llm_capturer_rejects_empty_without_shelling_out():
    with patch("memhub.capture.subprocess.run") as run:
        raised = False
        try:
            LLMCapturer().capture("   ", {})
        except Exception:
            raised = True
        assert raised
        run.assert_not_called()  # never invoke claude for empty input


def test_is_self_referential_detects_extract_prompt():
    from memhub.capture import is_self_referential, _EXTRACT_PROMPT
    assert is_self_referential(f"user: {_EXTRACT_PROMPT}\nassistant: [{{}}]") is True


def test_is_self_referential_false_for_normal_session():
    from memhub.capture import is_self_referential
    assert is_self_referential("user: 把 API 超时改成 30 秒\nassistant: 好的，已改") is False


def test_self_marker_stays_in_sync_with_prompt():
    # the sentinel must remain a substring of the real prompt, or the guard rots
    from memhub.capture import _SELF_MARKER, _EXTRACT_PROMPT
    assert _SELF_MARKER in _EXTRACT_PROMPT


def test_llm_capturer_marks_subprocess_to_break_self_capture_loop():
    out = json.dumps([{"content": "x", "kind": "fact", "tags": [], "scope": "current"}])
    with patch("memhub.capture.subprocess.run", return_value=_fake_run(out)) as run:
        LLMCapturer().capture("some real transcript", {})
    env = run.call_args.kwargs.get("env")
    assert env is not None, "extraction must pass an env so the hook can skip it"
    assert env.get("MEMHUB_EXTRACTING") == "1"
    assert "PATH" in env, "must inherit os.environ, not replace it"
