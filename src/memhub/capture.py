"""Capturers: turn a transcript into a list of memory dicts.

Each item: {"content": str, "kind": str, "tags": list, "scope": str}
"""
import json
import os
import subprocess
import urllib.request
from typing import Protocol

from . import config


class Capturer(Protocol):
    def capture(self, transcript: str, meta: dict) -> list[dict]:
        ...


class RawCapturer:
    """Fallback: slice transcript into fixed-size chunks, capped to the transcript tail."""

    def __init__(self, max_chars: int = 1000, max_chunks: int = config.RAW_MAX_CHUNKS):
        self.max_chars = max_chars
        self.max_chunks = max_chunks

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        text = transcript.strip()
        if not text:
            return []
        # keep the tail: session endings hold the conclusions, and an uncapped
        # transcript floods the store (one observed session produced 159 chunks)
        text = text[-(self.max_chars * self.max_chunks):]
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

# Sentinel: the opening of _EXTRACT_PROMPT. A transcript containing it is either
# memhub capturing its own `claude -p` extraction call (a feedback loop) or a
# session that pasted the prompt — never a real memory. Kept deliberately narrow
# (not the whole skill blurb) so normal sessions that merely load memhub are not
# filtered out.
_SELF_MARKER = "You extract durable memories from an AI coding session transcript"


def is_self_referential(text: str) -> bool:
    """True if the transcript is memhub's own machinery, not a real session."""
    return _SELF_MARKER in text


def _extract_json_array(text: str) -> list[dict]:
    # tolerate ```json fences or surrounding prose: grab first [ ... last ]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise CaptureError(f"no JSON array in extractor output: {text[:120]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise CaptureError(f"failed to parse JSON: {e}") from e
    if not isinstance(data, list):
        raise CaptureError("parsed JSON is not a list")
    return data


def _normalize_items(items: list) -> list[dict]:
    """Coerce extractor output into well-formed memory dicts; drop invalid entries."""
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
    return out


# structured-output schema for extractors that accept one (Ollama `format`);
# mirrors _EXTRACT_PROMPT so the model cannot return prose or a bare object
_EXTRACT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "kind": {"type": "string", "enum": ["decision", "fact", "convention", "snippet"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "string", "enum": ["current", "global"]},
        },
        "required": ["content", "kind", "tags", "scope"],
    },
}


class OllamaCapturer:
    """Primary: structured extraction via a local Ollama model.

    No cloud auth (works under launchd where `claude -p` has none) and no claude
    session recording (the self-capture feedback loop cannot occur on this path).
    """

    def __init__(self, url: str = config.OLLAMA_URL, model: str = config.OLLAMA_MODEL,
                 timeout: int = 120, max_chars: int = config.EXTRACT_MAX_CHARS):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_chars = max_chars

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        text = transcript.strip()
        if not text:
            raise CaptureError("empty transcript")
        text = text[-self.max_chars:]  # tail fits the model context; endings hold the conclusions
        body = json.dumps({
            "model": self.model,
            "prompt": f"{_EXTRACT_PROMPT}\n\nTranscript:\n{text}",
            "stream": False,
            "format": _EXTRACT_SCHEMA,
            "options": {"num_ctx": 16384, "temperature": 0},
        }).encode()
        req = urllib.request.Request(self.url + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except (OSError, ValueError) as e:  # URLError/timeout are OSError; bad JSON is ValueError
            raise CaptureError(f"ollama request failed: {e}") from e
        out = _normalize_items(_extract_json_array(data.get("response", "")))
        if not out:
            raise CaptureError("no valid memory items extracted")
        return out


class LLMCapturer:
    """Primary: use `claude -p` to extract structured memories."""

    def __init__(self, timeout: int = 120, model_cmd: str = "claude"):
        self.timeout = timeout
        self.model_cmd = model_cmd

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        if not transcript.strip():
            raise CaptureError("empty transcript")
        proc = subprocess.run(
            [self.model_cmd, "-p", _EXTRACT_PROMPT],
            input=transcript, text=True, capture_output=True, timeout=self.timeout,
            # Mark this subprocess so the SessionEnd hook skips it — otherwise the
            # extraction call's own session gets captured: an infinite feedback loop.
            env={**os.environ, "MEMHUB_EXTRACTING": "1"},
        )
        if proc.returncode != 0:
            raise CaptureError(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
        out = _normalize_items(_extract_json_array(proc.stdout))
        if not out:
            raise CaptureError("no valid memory items extracted")
        return out
