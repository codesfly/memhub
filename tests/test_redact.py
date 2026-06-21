from memhub.redact import redact


def test_redacts_openai_key():
    assert "sk-" not in redact("token is sk-abc123DEF456ghi789jkl012mno345")


def test_redacts_github_token():
    assert "ghp_" not in redact("ghp_1234567890abcdefABCDEF1234567890abcd")


def test_redacts_password_assignment():
    assert "hunter2" not in redact("password=hunter2")


def test_keeps_normal_text():
    assert redact("we chose JWT for auth") == "we chose JWT for auth"
