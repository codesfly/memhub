"""Redact secret-like strings before persisting."""
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(password|passwd|secret|token)\s*[=:]\s*\S+"),
]
_REPL = "[REDACTED]"


def redact(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(_REPL, text)
    return text
