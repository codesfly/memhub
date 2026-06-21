"""Local embedding via fastembed (lazy singleton)."""
from functools import lru_cache

from fastembed import TextEmbedding

from . import config


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=config.EMBED_MODEL)


def embed(text: str) -> list[float]:
    vec = next(iter(_model().embed([text])))
    return [float(x) for x in vec]
