"""Central config: paths, port, constants."""
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMHUB_DB", Path.home() / ".memhub" / "memhub.db"))
HOST = os.environ.get("MEMHUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMHUB_PORT", "37650"))
# multilingual (50+ languages, incl. Chinese) at the same 384 dims as all-MiniLM-L6-v2,
# so the vec0 schema is unchanged. After switching models run `memhub reindex` —
# vectors from different models live in different spaces and must not be mixed.
EMBED_MODEL = os.environ.get("MEMHUB_EMBED_MODEL",
                             "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBED_DIM = 384
# write-time near-dup merge: skip a new memory if a SAME-PROJECT one is within this
# L2 distance (embeddings are L2-normalized -> L2 0.45 ~= cos 0.90). Calibrated on the
# multilingual model: zh paraphrase pair L2 0.375 (must merge) vs zh opposite-meaning
# pair L2 0.581 (must NOT merge) — 0.45 keeps margin on both sides.
DEDUP_L2_MAX = float(os.environ.get("MEMHUB_DEDUP_L2_MAX", "0.45"))
RRF_K = 60  # reciprocal-rank-fusion constant
DEFAULT_LIMIT = 10
# raw capture keeps at most this many chunks per session (the transcript TAIL — session
# endings hold the conclusions). One observed runaway session produced 159 chunks.
RAW_MAX_CHUNKS = 40
# recency injection returns at most this many memories from the same session, so one
# giant raw-captured session can't fill every slot.
INJECT_SESSION_CAP = 2
VALID_CAPTURE_MODES = ("off", "raw", "llm")
CAPTURE_MODE = os.environ.get("MEMHUB_CAPTURE_MODE", "raw").lower()
INJECT_ENABLED = os.environ.get("MEMHUB_INJECT_ENABLED", "0").lower() in ("1", "true", "yes", "on")
# Zero-LLM sync of Claude's curated memory/*.md files into memhub.
MEMORY_PROJECTS_ROOT = Path(os.environ.get("MEMHUB_MEMORY_ROOT", str(Path.home() / ".claude" / "projects")))
MEMORY_SYNC_INTERVAL = float(os.environ.get("MEMHUB_MEMORY_SYNC_INTERVAL", "300"))
MEMORY_SYNC_ENABLED = os.environ.get("MEMHUB_MEMORY_SYNC", "1").lower() in ("1", "true", "yes", "on")
