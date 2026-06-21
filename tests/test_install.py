import sys, json
sys.path.insert(0, "deploy")
from install import merge_hooks

def test_merge_adds_hooks_to_empty():
    out = merge_hooks({}, "/x/capture.sh", "/x/inject.sh")
    assert any("inject.sh" in h["hooks"][0]["command"] for h in out["hooks"]["SessionStart"])
    assert any("capture.sh" in h["hooks"][0]["command"] for h in out["hooks"]["SessionEnd"])

def test_merge_preserves_existing_hooks():
    settings = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "other.sh"}]}]}}
    out = merge_hooks(settings, "/x/capture.sh", "/x/inject.sh")
    cmds = [h["hooks"][0]["command"] for h in out["hooks"]["SessionStart"]]
    assert "other.sh" in cmds
    assert any("inject.sh" in c for c in cmds)

def test_merge_is_idempotent():
    once = merge_hooks({}, "/x/capture.sh", "/x/inject.sh")
    twice = merge_hooks(json.loads(json.dumps(once)), "/x/capture.sh", "/x/inject.sh")
    assert len(twice["hooks"]["SessionStart"]) == len(once["hooks"]["SessionStart"])
