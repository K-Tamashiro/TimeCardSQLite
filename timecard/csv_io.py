"""CSV export using the active contract period."""

import csv
import io
from timecard.contracts import active_contract, reporting_period
from timecard.db import con


def csv_export(uid, year, month):
    c = active_contract(year, month)
    (start, end) = reporting_period(year, month, c.get("closing", "末") if c else "末")
    rows = con.execute(
        "SELECT * FROM work WHERE user_id=? AND day>=? AND day<=? ORDER BY day",
        (uid, start.isoformat(), end.isoformat()),
    ).fetchall()
    f = io.StringIO()
    w = csv.writer(f)
    w.writerow(["日付", "出勤打刻", "退勤打刻", "実績開始", "実績終了", "日報", "備考"])
    for r in rows:
        w.writerow(
            [
                r[k]
                for k in (
                    "day",
                    "clock_in",
                    "clock_out",
                    "actual_in",
                    "actual_out",
                    "report",
                    "note",
                )
            ]
        )
    return "\ufeff" + f.getvalue()
