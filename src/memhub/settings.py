"""Runtime service settings persisted in SQLite."""
import sqlite3
import time

from . import config

CAPTURE_MODE_KEY = "capture_mode"
INJECT_ENABLED_KEY = "inject_enabled"


def normalize_capture_mode(value: str | None, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise ValueError(f"capture_mode must be one of: {', '.join(config.VALID_CAPTURE_MODES)}")
        value = default
    mode = value.lower()
    if mode not in config.VALID_CAPTURE_MODES:
        raise ValueError(f"capture_mode must be one of: {', '.join(config.VALID_CAPTURE_MODES)}")
    return mode


def default_capture_mode() -> str:
    try:
        return normalize_capture_mode(config.CAPTURE_MODE, default="raw")
    except ValueError:
        return "raw"


def get_capture_mode(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT value FROM service_settings WHERE key=?",
        (CAPTURE_MODE_KEY,),
    ).fetchone()
    if not row:
        return default_capture_mode()
    try:
        return normalize_capture_mode(row[0])
    except ValueError:
        return default_capture_mode()


def set_capture_mode(conn: sqlite3.Connection, value: str) -> str:
    mode = normalize_capture_mode(value)
    conn.execute(
        """INSERT INTO service_settings(key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (CAPTURE_MODE_KEY, mode, int(time.time())),
    )
    conn.commit()
    return mode


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if isinstance(value, int):
        return value != 0
    raise ValueError("inject_enabled must be a boolean")


def get_inject_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT value FROM service_settings WHERE key=?",
        (INJECT_ENABLED_KEY,),
    ).fetchone()
    if not row:
        return config.INJECT_ENABLED
    return row[0] == "1"


def set_inject_enabled(conn: sqlite3.Connection, value) -> bool:
    enabled = _bool_value(value)
    conn.execute(
        """INSERT INTO service_settings(key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (INJECT_ENABLED_KEY, "1" if enabled else "0", int(time.time())),
    )
    conn.commit()
    return enabled


def snapshot(conn: sqlite3.Connection) -> dict:
    mode = get_capture_mode(conn)
    inject_enabled = get_inject_enabled(conn)
    return {
        "capture_mode": mode,
        "capture_enabled": mode != "off",
        "llm_enabled": mode == "llm",
        "inject_enabled": inject_enabled,
        "valid_capture_modes": list(config.VALID_CAPTURE_MODES),
    }
