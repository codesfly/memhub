"""Local embedding via fastembed (lazy singleton)."""
import math
from functools import lru_cache

from fastembed import TextEmbedding

from . import config


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=config.EMBED_MODEL)


def _normalize(vec: list[float]) -> list[float]:
    # some fastembed models (e.g. paraphrase-multilingual) return unnormalized vectors;
    # unit length makes sqlite-vec's L2 distance order identical to cosine order
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def embed(text: str) -> list[float]:
    return embed_batch([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [_normalize([float(x) for x in v]) for v in _model().embed(texts)]
