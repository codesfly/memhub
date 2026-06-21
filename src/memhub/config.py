"""Central config: paths, port, constants."""
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMHUB_DB", Path.home() / ".memhub" / "memhub.db"))
HOST = os.environ.get("MEMHUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMHUB_PORT", "37650"))
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
RRF_K = 60  # reciprocal-rank-fusion constant
DEFAULT_LIMIT = 10
