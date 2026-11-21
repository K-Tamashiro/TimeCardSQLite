"""Fictional sample dataset seeding and sysadmin-only sample data reset."""

import calendar
import datetime
from timecard.auth import ROLE_USER, create_user
from timecard.contracts import (
    DEFAULT_BREAK1_END,
    DEFAULT_BREAK1_START,
    DEFAULT_BREAK2_END,
    DEFAULT_BREAK2_START,
    DEFAULT_PAY_DAY,
    DEFAULT_PAY_HOLIDAY_RULE,
    DEFAULT_PAY_MONTH_OFFSET,
    DEFAULT_REGULAR_END,
    DEFAULT_REGULAR_START,
    DEFAULT_ROUND_UNIT,
    DEFAULT_WORKDAYS,
    save_contract_holidays,
    save_contracts,
    upsert_event,
)
from timecard.db import con
from timecard.holidays import national_holidays
from timecard.settings_store import SHARED_SCOPE, set_shared_val, setval
from timecard.work_store import savework

SAMPLE_CONTRACT_ID = "c_sample01"
SAMPLE_USER_LOGIN = "sample_user"
SAMPLE_USER_DEFAULT_PW = "sample1234"


def seed_sample_data(sysadmin_uid, today=None):
    """Populate fictional sample contract, billing info, holidays, events, user, and entries."""
    today = today or datetime.date.today()
    ym = today.strftime("%Y-%m")
    year = today.year

    # 1. Sample basic billing settings (marked is_sample=1)
    set_shared_val("company", "山田 太郎", is_sample=1)
    set_shared_val("customer", "株式会社サンプルソリューションズ", is_sample=1)
    set_shared_val(
        "sender_address",
        "〒100-0001\n東京都千代田区サンプル1-2-3\nサンプルビル 4F",
        is_sample=1,
    )
    set_shared_val(
        "bank_account",
        "サンプル銀行 本店営業部（支店番号：001） 普通：1234567 名義：ヤマダ タロウ",
        is_sample=1,
    )
    set_shared_val(
        "invoice_note",
        "お振込手数料は貴社にてご負担くださいますようお願い申し上げます。",
        is_sample=1,
    )
    set_shared_val("invoice_base_month", ym, is_sample=1)
    set_shared_val("invoice_number", "1", is_sample=1)

    # 2. Sample contract (marked is_sample=1)
    sample_contract = {
        "id": SAMPLE_CONTRACT_ID,
        "name": "サンプル基本契約",
        "display_title": "サンプル事業所",
        "customer": "株式会社サンプルソリューションズ",
        "start_date": "%04d-01-01" % year,
        "end_date": "",
        "fee": "500000",
        "lower": "140",
        "upper": "180",
        "deduct_rate": "",
        "extra_rate": "",
        "closing": "末",
        "tax": "10",
        "workdays": list(DEFAULT_WORKDAYS),
        "work_on_holiday": False,
        "fiscal_start_month": 4,
        "fiscal_start_day": 1,
        "regular_start": DEFAULT_REGULAR_START,
        "regular_end": DEFAULT_REGULAR_END,
        "round_unit": DEFAULT_ROUND_UNIT,
        "break1_start": DEFAULT_BREAK1_START,
        "break1_end": DEFAULT_BREAK1_END,
        "break2_start": DEFAULT_BREAK2_START,
        "break2_end": DEFAULT_BREAK2_END,
        "pay_month_offset": DEFAULT_PAY_MONTH_OFFSET,
        "pay_day": DEFAULT_PAY_DAY,
        "pay_holiday_rule": DEFAULT_PAY_HOLIDAY_RULE,
        "show_half_subtotals": False,
        "is_sample": True,
    }
    save_contracts([sample_contract])

    # 3. Sample office holidays
    save_contract_holidays(
        SAMPLE_CONTRACT_ID,
        {
            "%04d-08-13" % year: "夏期休暇（サンプル）",
            "%04d-08-14" % year: "夏期休暇（サンプル）",
            "%04d-12-29" % year: "年末年始（サンプル）",
            "%04d-12-30" % year: "年末年始（サンプル）",
        },
        is_sample=1,
    )

    # 4. Sample public event (visible to all users) and private event
    last_day = calendar.monthrange(today.year, today.month)[1]
    upsert_event(
        "public",
        0,
        "%04d-%02d-%02d" % (today.year, today.month, last_day),
        "月末締め・請求書提出日（サンプル共有予定）",
        is_sample=1,
    )
    upsert_event(
        "private",
        sysadmin_uid,
        today.isoformat(),
        "定例ミーティング 14:00（サンプル個人予定）",
        is_sample=1,
    )

    # 5. Sample user (can elevate to admin; users are preserved by sample reset)
    sample_uid = None
    existing_sample = con.execute(
        "SELECT id FROM users WHERE login=?", (SAMPLE_USER_LOGIN,)
    ).fetchone()
    if not existing_sample:
        sample_uid = create_user(
            SAMPLE_USER_LOGIN,
            SAMPLE_USER_DEFAULT_PW,
            display_name="サンプル 太郎",
            role=ROLE_USER,
            can_admin=True,
            is_sample=True,
        )
    else:
        sample_uid = existing_sample["id"]

    # 6. Sample attendance entries for the current month (first 3 weekdays)
    official = national_holidays(today.year)
    weekdays = []
    for d in range(1, last_day + 1):
        cand = datetime.date(today.year, today.month, d)
        if cand.weekday() < 5 and cand not in official:
            weekdays.append(cand)
        if len(weekdays) >= 3:
            break

    sample_rows = [
        ("08:25", "17:32", False, "要件定義・画面設計（サンプル）", ""),
        ("08:30", "18:45", False, "機能実装・単体テスト（サンプル残業）", ""),
        ("07:00", "17:30", True, "リリース事前確認（サンプル早出）", "早出テスト"),
    ]
    target_uids = [sysadmin_uid]
    if sample_uid and sample_uid != sysadmin_uid:
        target_uids.append(sample_uid)

    for uid in target_uids:
        for idx, day_obj in enumerate(weekdays):
            if idx >= len(sample_rows):
                break
            ci, co, early, rep, note = sample_rows[idx]
            ds = day_obj.isoformat()
            savework(
                uid,
                ds,
                {"clock_in": ci, "clock_out": co, "report": rep, "note": note},
                is_sample=1,
            )
            if early:
                setval(uid, "early:" + ds, "1", is_sample=1)
    con.commit()


def sample_data_summary():
    """Return counts of remaining sample records (excluding users)."""
    settings_cnt = con.execute(
        "SELECT COUNT(*) AS n FROM settings WHERE is_sample=1"
    ).fetchone()["n"]
    work_cnt = con.execute(
        "SELECT COUNT(*) AS n FROM work WHERE is_sample=1"
    ).fetchone()["n"]
    event_cnt = con.execute(
        "SELECT COUNT(*) AS n FROM events WHERE is_sample=1"
    ).fetchone()["n"]
    return {
        "settings": settings_cnt,
        "work": work_cnt,
        "events": event_cnt,
        "total": settings_cnt + work_cnt + event_cnt,
    }


def reset_sample_data():
    """Delete ONLY sample data (contracts/settings/holidays/events/work). Users and roles stay intact."""
    w_del = con.execute("DELETE FROM work WHERE is_sample=1").rowcount
    e_del = con.execute("DELETE FROM events WHERE is_sample=1").rowcount
    s_del = con.execute("DELETE FROM settings WHERE is_sample=1").rowcount
    con.commit()
    return {"work": w_del, "events": e_del, "settings": s_del}
