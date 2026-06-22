"""Central config: paths, port, constants."""
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMHUB_DB", Path.home() / ".memhub" / "memhub.db"))
HOST = os.environ.get("MEMHUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMHUB_PORT", "37650"))
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
# write-time near-dup merge: skip a new memory if a SAME-PROJECT one is within this
# L2 distance (normalized embeddings -> cos > ~0.95). Tight on purpose: opposite-meaning
# text scores ~0.88 cos (L2 ~0.49), so this stays well clear of merging contradictions.
DEDUP_L2_MAX = float(os.environ.get("MEMHUB_DEDUP_L2_MAX", "0.30"))
RRF_K = 60  # reciprocal-rank-fusion constant
DEFAULT_LIMIT = 10
VALID_CAPTURE_MODES = ("off", "raw", "llm")
CAPTURE_MODE = os.environ.get("MEMHUB_CAPTURE_MODE", "raw").lower()
INJECT_ENABLED = os.environ.get("MEMHUB_INJECT_ENABLED", "0").lower() in ("1", "true", "yes", "on")
# Zero-LLM sync of Claude's curated memory/*.md files into memhub.
MEMORY_PROJECTS_ROOT = Path(os.environ.get("MEMHUB_MEMORY_ROOT", str(Path.home() / ".claude" / "projects")))
MEMORY_SYNC_INTERVAL = float(os.environ.get("MEMHUB_MEMORY_SYNC_INTERVAL", "300"))
MEMORY_SYNC_ENABLED = os.environ.get("MEMHUB_MEMORY_SYNC", "1").lower() in ("1", "true", "yes", "on")
