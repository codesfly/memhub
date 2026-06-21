from memhub import embedding, config


def test_embed_returns_correct_dim():
    vec = embedding.embed("hello world")
    assert len(vec) == config.EMBED_DIM


def test_embed_is_deterministic():
    a = embedding.embed("same text")
    b = embedding.embed("same text")
    assert a == b
