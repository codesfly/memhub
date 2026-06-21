"""Capturers: turn a transcript into a list of memory dicts.

Each item: {"content": str, "kind": str, "tags": list, "scope": str}
"""
import json
import subprocess
from typing import Protocol


class Capturer(Protocol):
    def capture(self, transcript: str, meta: dict) -> list[dict]:
        ...


class RawCapturer:
    """Fallback: slice transcript into fixed-size chunks."""

    def __init__(self, max_chars: int = 1000):
        self.max_chars = max_chars

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        text = transcript.strip()
        if not text:
            return []
        chunks = [text[i:i + self.max_chars] for i in range(0, len(text), self.max_chars)]
        return [{"content": c, "kind": "raw", "tags": [], "scope": "current"} for c in chunks]


class CaptureError(Exception):
    pass


# 'raw' is intentionally NOT in the LLM kind whitelist — it marks RawCapturer fallback output only.
_EXTRACT_PROMPT = (
    "You extract durable memories from an AI coding session transcript. "
    "Output ONLY a JSON array. Each item: "
    '{"content": <one concise memory>, "kind": <"decision"|"fact"|"convention"|"snippet">, '
    '"tags": <string list>, "scope": <"current"|"global">}. '
    "scope=global means reusable across projects; current means project-specific. "
    "No prose, no markdown fences, only the JSON array."
)


def _extract_json_array(text: str) -> list[dict]:
    # tolerate ```json fences or surrounding prose: grab first [ ... last ]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise CaptureError(f"no JSON array in claude output: {text[:120]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise CaptureError(f"failed to parse JSON: {e}") from e
    if not isinstance(data, list):
        raise CaptureError("parsed JSON is not a list")
    return data


class LLMCapturer:
    """Primary: use `claude -p` to extract structured memories."""

    def __init__(self, timeout: int = 120, model_cmd: str = "claude"):
        self.timeout = timeout
        self.model_cmd = model_cmd

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        proc = subprocess.run(
            [self.model_cmd, "-p", _EXTRACT_PROMPT],
            input=transcript, text=True, capture_output=True, timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise CaptureError(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
        items = _extract_json_array(proc.stdout)
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("content"):
                out.append({
                    "content": str(it["content"]),
                    # default 'fact' (LLM items); RawCapturer/schema default is 'raw'.
                    "kind": it.get("kind", "fact"),
                    "tags": it.get("tags", []) if isinstance(it.get("tags"), list) else [],
                    "scope": "global" if it.get("scope") == "global" else "current",
                })
        if not out:
            raise CaptureError("no valid memory items extracted")
        return out
