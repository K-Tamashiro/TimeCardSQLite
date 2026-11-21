"""Attendance work-row persistence."""

from timecard.db import con


def getwork(uid, day):
    row = con.execute(
        "SELECT * FROM work WHERE user_id=? AND day=?", (uid, day)
    ).fetchone()
    return row or dict(
        clock_in="",
        clock_out="",
        actual_in="",
        actual_out="",
        report="",
        note="",
        is_sample=0,
    )


def savework(uid, day, fields, is_sample=0):
    existing = getwork(uid, day)
    existing.update(fields)
    con.execute(
        "REPLACE INTO work(user_id, day, clock_in, clock_out, actual_in, actual_out, report, note, is_sample) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            uid,
            day,
            existing["clock_in"],
            existing["clock_out"],
            existing["actual_in"],
            existing["actual_out"],
            existing["report"],
            existing["note"],
            1 if is_sample else 0,
        ),
    )
    con.commit()
