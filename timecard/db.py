"""SQLite3 database lifecycle, schema initialization, and resource path resolution."""

import os
from pathlib import Path
import sqlite3
import sys
import threading

APP_DIR_NAME = "PersonalTimeCard"

_LOCK = threading.RLock()
_DB_PATH = None
_MEMORY_CONN = None
_LOCAL = threading.local()

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    can_admin INTEGER NOT NULL DEFAULT 0,
    is_sample INTEGER NOT NULL DEFAULT 0,
    salt TEXT NOT NULL,
    pw TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    active_role TEXT NOT NULL,
    expires TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER NOT NULL,
    k TEXT NOT NULL,
    v TEXT NOT NULL,
    is_sample INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, k)
);

CREATE TABLE IF NOT EXISTS work (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    clock_in TEXT NOT NULL DEFAULT '',
    clock_out TEXT NOT NULL DEFAULT '',
    actual_in TEXT NOT NULL DEFAULT '',
    actual_out TEXT NOT NULL DEFAULT '',
    report TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    text TEXT NOT NULL,
    is_sample INTEGER NOT NULL DEFAULT 0,
    UNIQUE(scope, user_id, day)
);
"""


def resource_root():
    """Return the package directory containing assets/ and images/ (PyInstaller-safe)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "timecard"
    return Path(__file__).resolve().parent


def default_data_dir():
    """Return a writable per-user data directory for the SQLite database."""
    override = os.environ.get("TIMECARD_DATA_DIR", "").strip()
    if override:
        p = Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        p = Path(base) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _open_connection(db_path):
    conn = sqlite3.connect(str(db_path), timeout=15.0, check_same_thread=False)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    if str(db_path) != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def configure(db_path=None):
    """Configure the active SQLite database path (or ':memory:' for tests)."""
    global _DB_PATH, _MEMORY_CONN
    with _LOCK:
        close_all()
        if db_path is None:
            _DB_PATH = default_data_dir() / "timecard.db"
        elif str(db_path) == ":memory:":
            _DB_PATH = ":memory:"
            _MEMORY_CONN = _open_connection(":memory:")
        else:
            p = Path(db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            _DB_PATH = p


def current_db_path():
    with _LOCK:
        if _DB_PATH is None:
            configure(None)
        return _DB_PATH


def get_connection():
    """Return an initialized SQLite connection for the current thread."""
    with _LOCK:
        if _DB_PATH is None:
            configure(None)
        if str(_DB_PATH) == ":memory:":
            return _MEMORY_CONN
        conn = getattr(_LOCAL, "conn", None)
        conn_path = getattr(_LOCAL, "conn_path", None)
        if conn is None or conn_path != _DB_PATH:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            conn = _open_connection(_DB_PATH)
            _LOCAL.conn = conn
            _LOCAL.conn_path = _DB_PATH
        return conn


def close_all():
    global _MEMORY_CONN
    with _LOCK:
        if _MEMORY_CONN is not None:
            try:
                _MEMORY_CONN.close()
            except Exception:
                pass
            _MEMORY_CONN = None
        conn = getattr(_LOCAL, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            _LOCAL.conn = None
            _LOCAL.conn_path = None


class ConnectionProxy:
    """Thread-safe proxy exposing execute/commit/close on the active SQLite DB."""

    def execute(self, sql, params=()):
        with _LOCK:
            return get_connection().execute(sql, params)

    def executescript(self, sql):
        with _LOCK:
            return get_connection().executescript(sql)

    def commit(self):
        with _LOCK:
            get_connection().commit()

    def close(self):
        close_all()


con = ConnectionProxy()
