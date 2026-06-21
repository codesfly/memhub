"""Parse a Claude Code transcript JSONL into plain user/assistant text."""
import json
from pathlib import Path

def parse_transcript(path: str) -> str:
    out = []
    try:
        raw = Path(path).read_text(errors="replace")
    except OSError:
        return ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t not in ("user", "assistant"):
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        text = text.strip()
        if text:
            out.append(f"{t}: {text}")
    return "\n".join(out)
