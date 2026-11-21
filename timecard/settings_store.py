"""Shared organization settings (user_id=0) and per-user settings persistence."""

from timecard.db import con

SHARED_SCOPE = 0


def val(scope_id, k, default):
    row = con.execute(
        "SELECT v FROM settings WHERE user_id=? AND k=?", (scope_id, k)
    ).fetchone()
    return row["v"] if row else default


def setval(scope_id, k, v, is_sample=0):
    con.execute(
        "REPLACE INTO settings(user_id, k, v, is_sample) VALUES(?,?,?,?)",
        (scope_id, k, str(v), 1 if is_sample else 0),
    )


def delval(scope_id, k):
    con.execute("DELETE FROM settings WHERE user_id=? AND k=?", (scope_id, k))


def shared_val(k, default):
    return val(SHARED_SCOPE, k, default)


def set_shared_val(k, v, is_sample=0):
    setval(SHARED_SCOPE, k, v, is_sample=is_sample)


def month_limit(scope_id, key, year, month, default):
    override = val(scope_id, key + ":%04d-%02d" % (year, month), "")
    return override if override != "" else val(scope_id, key, default)
