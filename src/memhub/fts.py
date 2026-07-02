"""CJK-aware FTS5 text/query helpers.

FTS5's unicode61 tokenizer has no CJK word segmentation — a run of Chinese
characters becomes ONE token, so a substring query like 部署 can never match.
We space-separate CJK characters at index time and turn each CJK run into a
phrase query at match time; non-CJK text is left intact so porter stemming
still applies to English.
"""
import re

_CJK_CHAR = re.compile(r"([一-鿿])")
_RUN = re.compile(r"[一-鿿]+|[^一-鿿\s]+")


def index_text(text: str) -> str:
    """Text as stored in the FTS index (search-only copy; display content is untouched)."""
    return _CJK_CHAR.sub(r" \1 ", text)


def match_query(query: str) -> str:
    """FTS5 MATCH expression: every run quoted (neutralizes FTS syntax chars),
    CJK runs as per-character phrases so they match index_text output."""
    parts = []
    for run in _RUN.findall(query):
        if _CJK_CHAR.search(run):
            parts.append('"' + " ".join(run) + '"')
        else:
            parts.append('"' + run.replace('"', '""') + '"')
    return " ".join(parts)
