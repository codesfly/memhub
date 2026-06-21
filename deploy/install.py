"""Idempotently install memhub hooks into ~/.claude/settings.json and load launchd."""
import json
import shutil
import sys
import subprocess
from pathlib import Path

HOME = Path.home()
SETTINGS = HOME / ".claude" / "settings.json"
HOOKS_DIR = HOME / "Code" / "memhub" / "hooks"
CAPTURE = str(HOOKS_DIR / "memhub-capture.sh")
INJECT = str(HOOKS_DIR / "memhub-inject.sh")

def _has(entries, needle):
    return any(needle in h.get("command", "")
               for e in entries for h in e.get("hooks", []))

def merge_hooks(settings: dict, capture: str, inject: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    ss = hooks.setdefault("SessionStart", [])
    se = hooks.setdefault("SessionEnd", [])
    if not _has(ss, Path(inject).name):
        ss.append({"matcher": "startup|resume", "hooks": [{"type": "command", "command": inject}]})
    if not _has(se, Path(capture).name):
        se.append({"hooks": [{"type": "command", "command": capture}]})
    return settings

def install_settings() -> None:
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    bak = Path(str(SETTINGS) + ".memhub-bak")
    if SETTINGS.exists() and not bak.exists():   # don't clobber a good backup on re-run
        shutil.copy(SETTINGS, bak)
        bak.chmod(0o600)                          # backup holds a token; restrict perms
    merged = merge_hooks(settings, CAPTURE, INJECT)
    SETTINGS.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    print(f"hooks installed into {SETTINGS} (backup: {bak})")

def install_launchd() -> None:
    (HOME / ".memhub").mkdir(exist_ok=True)
    py = str(HOME / "Code" / "memhub" / ".venv" / "bin" / "python")
    tmpl = (Path(__file__).parent / "com.memhub.plist").read_text()
    plist = tmpl.replace("__PYTHON__", py).replace("__HOME__", str(HOME))
    dst = HOME / "Library" / "LaunchAgents" / "com.memhub.server.plist"
    dst.write_text(plist)
    subprocess.run(["launchctl", "unload", str(dst)], capture_output=True)
    subprocess.run(["launchctl", "load", str(dst)], check=True)
    print(f"launchd loaded: {dst}")

if __name__ == "__main__":
    install_settings()
    if "--with-launchd" in sys.argv:
        install_launchd()
        print("memhub service loaded. Verify: curl -s localhost:37650/health")
    else:
        print("Skipped launchd (pass --with-launchd to load the service).")
