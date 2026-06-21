from memhub import config


def test_config_defaults():
    assert config.EMBED_DIM == 384
    assert config.PORT == 37650
    assert config.RRF_K == 60
