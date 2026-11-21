"""Shared contract persistence, working-day rules, office holidays, and scoped events."""

import calendar
import datetime
import secrets
from timecard.db import con
from timecard.settings_store import SHARED_SCOPE, setval, val

DEFAULT_WORKDAYS = [0, 1, 2, 3, 4]
DEFAULT_FISCAL_START_MONTH = 4
DEFAULT_FISCAL_START_DAY = 1
DEFAULT_REGULAR_START = "08:30"
DEFAULT_REGULAR_END = "17:30"
DEFAULT_ROUND_UNIT = 15
DEFAULT_BREAK1_START = "11:45"
DEFAULT_BREAK1_END = "12:45"
DEFAULT_BREAK2_START = "17:30"
DEFAULT_BREAK2_END = "17:40"
DEFAULT_PAY_MONTH_OFFSET = 2
DEFAULT_PAY_DAY = "15"
DEFAULT_PAY_HOLIDAY_RULE = "next"

CONTRACT_FIELD_MAP = (
    ("name", "name"),
    ("display_title", "title"),
    ("customer", "cust"),
    ("start_date", "sdate"),
    ("end_date", "edate"),
    ("fee", "fee"),
    ("lower", "lower"),
    ("upper", "upper"),
    ("deduct_rate", "drate"),
    ("extra_rate", "erate"),
    ("closing", "close"),
    ("tax", "tax"),
    ("workdays", "wdays"),
    ("work_on_holiday", "whol"),
    ("fiscal_start_month", "fym"),
    ("fiscal_start_day", "fyd"),
    ("regular_start", "rstart"),
    ("regular_end", "rend"),
    ("round_unit", "runit"),
    ("break1_start", "b1s"),
    ("break1_end", "b1e"),
    ("break2_start", "b2s"),
    ("break2_end", "b2e"),
    ("pay_month_offset", "pmo"),
    ("pay_day", "pday"),
    ("pay_holiday_rule", "phol"),
    ("is_sample", "sample"),
)


def _valid_iso_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_ym(value):
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return False
    try:
        ym_number(value)
        return True
    except (ValueError, TypeError):
        return False


def normalize_hhmm(value):
    s = str(value or "").strip().replace("：", ":")
    if not s:
        return ""
    if s.isdigit() and len(s) in (3, 4):
        s = s.zfill(4)
        s = s[:2] + ":" + s[2:]
    try:
        parsed = datetime.datetime.strptime(s, "%H:%M")
        return parsed.strftime("%H:%M")
    except ValueError:
        return ""


def hhmm_to_minutes(value):
    norm = normalize_hhmm(value)
    if not norm:
        return None
    h, m = map(int, norm.split(":"))
    return h * 60 + m


def ym_number(value):
    (y, m) = map(int, value.split("-"))
    if not (1 <= y <= 9999 and 1 <= m <= 12):
        raise ValueError("Invalid month")
    return y * 12 + m - 1


def ym_string(number):
    return "%04d-%02d" % (number // 12, number % 12 + 1)


def new_contract_id():
    return "c_" + secrets.token_hex(4)


def normalize_contract(raw, storage_key=None):
    c = dict(raw)
    start_date = str(c.get("start_date") or "")
    start_ym = str(c.get("start") or "")
    if not _valid_iso_date(start_date):
        if _valid_ym(start_ym):
            start_date = start_ym + "-01"
        elif _valid_ym(str(storage_key or "")):
            start_date = str(storage_key) + "-01"
    if _valid_iso_date(start_date):
        start_ym = start_date[:7]

    end_date = str(c.get("end_date") or "")
    end_ym = end_date[:7] if _valid_iso_date(end_date) else ""
    if not _valid_iso_date(end_date):
        end_date = ""

    cid = str(c.get("id") or storage_key or new_contract_id())

    raw_workdays = c.get("workdays")
    if isinstance(raw_workdays, list):
        workdays = sorted(
            {int(d) for d in raw_workdays if isinstance(d, int) and 0 <= d <= 6}
        )
    elif isinstance(raw_workdays, str):
        if raw_workdays == "-":
            workdays = []
        elif raw_workdays:
            workdays = sorted(
                {
                    int(tok)
                    for tok in raw_workdays.split(",")
                    if tok.strip().isdigit() and 0 <= int(tok.strip()) <= 6
                }
            )
        else:
            workdays = list(DEFAULT_WORKDAYS)
    else:
        workdays = list(DEFAULT_WORKDAYS)

    raw_whol = c.get("work_on_holiday", False)
    work_on_holiday = (
        raw_whol.strip() in ("1", "true", "True")
        if isinstance(raw_whol, str)
        else bool(raw_whol)
    )

    try:
        fy_month = int(c.get("fiscal_start_month", DEFAULT_FISCAL_START_MONTH))
        if not 1 <= fy_month <= 12:
            fy_month = DEFAULT_FISCAL_START_MONTH
    except (ValueError, TypeError):
        fy_month = DEFAULT_FISCAL_START_MONTH

    try:
        fy_day = int(c.get("fiscal_start_day", DEFAULT_FISCAL_START_DAY))
        max_day = calendar.monthrange(2026, fy_month)[1]
        if not 1 <= fy_day <= max_day:
            fy_day = min(DEFAULT_FISCAL_START_DAY, max_day)
    except (ValueError, TypeError):
        fy_day = DEFAULT_FISCAL_START_DAY

    closing = str(c.get("closing") or "末")
    if closing not in ("5", "10", "15", "20", "25", "末"):
        closing = "末"

    tax_val = c.get("tax")
    tax_str = "" if tax_val is None else str(tax_val).strip()

    regular_start = normalize_hhmm(c.get("regular_start")) or DEFAULT_REGULAR_START
    regular_end = normalize_hhmm(c.get("regular_end")) or DEFAULT_REGULAR_END
    rs_min = hhmm_to_minutes(regular_start)
    re_min = hhmm_to_minutes(regular_end)
    if rs_min is None or re_min is None or re_min <= rs_min:
        regular_start, regular_end = DEFAULT_REGULAR_START, DEFAULT_REGULAR_END

    try:
        round_unit = int(c.get("round_unit", DEFAULT_ROUND_UNIT))
        if not 1 <= round_unit <= 30:
            round_unit = DEFAULT_ROUND_UNIT
    except (ValueError, TypeError):
        round_unit = DEFAULT_ROUND_UNIT

    if "break1_start" in c or "break1_end" in c:
        b1s = normalize_hhmm(c.get("break1_start"))
        b1e = normalize_hhmm(c.get("break1_end"))
        b1s_min = hhmm_to_minutes(b1s)
        b1e_min = hhmm_to_minutes(b1e)
        if b1s_min is None or b1e_min is None or b1e_min <= b1s_min:
            b1s, b1e = "", ""
    else:
        b1s, b1e = DEFAULT_BREAK1_START, DEFAULT_BREAK1_END

    if "break2_start" in c or "break2_end" in c:
        b2s = normalize_hhmm(c.get("break2_start"))
        b2e = normalize_hhmm(c.get("break2_end"))
        b2s_min = hhmm_to_minutes(b2s)
        b2e_min = hhmm_to_minutes(b2e)
        if b2s_min is None or b2e_min is None or b2e_min <= b2s_min:
            b2s, b2e = "", ""
    else:
        b2s, b2e = DEFAULT_BREAK2_START, DEFAULT_BREAK2_END

    try:
        pay_month_offset = int(c.get("pay_month_offset", DEFAULT_PAY_MONTH_OFFSET))
        if pay_month_offset not in (1, 2, 3):
            pay_month_offset = DEFAULT_PAY_MONTH_OFFSET
    except (ValueError, TypeError):
        pay_month_offset = DEFAULT_PAY_MONTH_OFFSET

    raw_pay_day = str(c.get("pay_day") or DEFAULT_PAY_DAY).strip()
    if raw_pay_day == "末":
        pay_day = "末"
    elif raw_pay_day.isdigit() and 1 <= int(raw_pay_day) <= 31:
        pay_day = str(int(raw_pay_day))
    else:
        pay_day = DEFAULT_PAY_DAY

    raw_pay_hol = str(c.get("pay_holiday_rule") or DEFAULT_PAY_HOLIDAY_RULE).strip()
    pay_holiday_rule = (
        raw_pay_hol if raw_pay_hol in ("next", "prev") else DEFAULT_PAY_HOLIDAY_RULE
    )

    raw_sample = c.get("is_sample", False)
    is_sample = (
        raw_sample.strip() in ("1", "true", "True")
        if isinstance(raw_sample, str)
        else bool(raw_sample)
    )

    return {
        "id": cid,
        "name": str(c.get("name") or ""),
        "display_title": str(c.get("display_title") or ""),
        "customer": str(c.get("customer") or ""),
        "start": start_ym,
        "end": end_ym,
        "start_date": start_date,
        "end_date": end_date,
        "work_start": start_date if start_date and not start_date.endswith("-01") else "",
        "lower": str(c.get("lower") if c.get("lower") is not None else ""),
        "upper": str(c.get("upper") if c.get("upper") is not None else ""),
        "fee": str(c.get("fee") or ""),
        "deduct_rate": str(c.get("deduct_rate") or ""),
        "extra_rate": str(c.get("extra_rate") or ""),
        "closing": closing,
        "tax": tax_str,
        "workdays": workdays,
        "work_on_holiday": work_on_holiday,
        "fiscal_start_month": fy_month,
        "fiscal_start_day": fy_day,
        "regular_start": regular_start,
        "regular_end": regular_end,
        "round_unit": round_unit,
        "break1_start": b1s,
        "break1_end": b1e,
        "break2_start": b2s,
        "break2_end": b2e,
        "pay_month_offset": pay_month_offset,
        "pay_day": pay_day,
        "pay_holiday_rule": pay_holiday_rule,
        "is_sample": is_sample,
    }


def contracts():
    rows = con.execute(
        "SELECT k, v FROM settings WHERE user_id=? AND k LIKE ?",
        (SHARED_SCOPE, "cf:%"),
    ).fetchall()
    grouped = {}
    short_to_long = {short: long_name for long_name, short in CONTRACT_FIELD_MAP}
    for row in rows:
        parts = row["k"].split(":", 2)
        if len(parts) != 3:
            continue
        cid, short_field = parts[1], parts[2]
        long_field = short_to_long.get(short_field)
        if long_field:
            grouped.setdefault(cid, {"id": cid})[long_field] = row["v"]
    result = []
    for cid, raw in grouped.items():
        if raw.get("name") and raw.get("start_date"):
            result.append(normalize_contract(raw, storage_key=cid))
    return sorted(result, key=lambda x: x.get("start_date") or "", reverse=True)


def save_contracts(items):
    normalized_items = []
    keep_ids = set()
    for item in items:
        c = normalize_contract(item)
        cid = c["id"] or new_contract_id()
        c["id"] = cid
        normalized_items.append(c)
        keep_ids.add(cid)

    existing_rows = con.execute(
        "SELECT k FROM settings WHERE user_id=? AND k LIKE ?",
        (SHARED_SCOPE, "cf:%"),
    ).fetchall()
    for row in existing_rows:
        parts = row["k"].split(":", 2)
        if len(parts) == 3 and parts[1] not in keep_ids:
            con.execute(
                "DELETE FROM settings WHERE user_id=? AND k=?",
                (SHARED_SCOPE, row["k"]),
            )

    for c in normalized_items:
        cid = c["id"]
        sample_flag = 1 if c.get("is_sample") else 0
        for long_field, short_field in CONTRACT_FIELD_MAP:
            value = c[long_field]
            if long_field == "workdays":
                encoded = ",".join(str(d) for d in value) if value else "-"
            elif long_field in ("work_on_holiday", "is_sample"):
                encoded = "1" if value else "0"
            else:
                encoded = str(value)[:100]
            setval(SHARED_SCOPE, "cf:" + cid + ":" + short_field, encoded, is_sample=sample_flag)

    con.commit()


def contract_by_id(cid):
    if not cid:
        return None
    for c in contracts():
        if c["id"] == cid:
            return c
    return None


def contract_display_title(contract):
    if not contract:
        return ""
    return (contract.get("display_title") or contract.get("name") or "").strip()


def active_contract(year, month):
    month_first = datetime.date(year, month, 1).isoformat()
    month_last = datetime.date(
        year, month, calendar.monthrange(year, month)[1]
    ).isoformat()
    for c in contracts():
        s = c.get("start_date") or ""
        e = c.get("end_date") or ""
        if s and s <= month_last and (not e or e >= month_first):
            return c
    return None


def contract_for_day(day_str):
    if not _valid_iso_date(day_str):
        return None
    for c in contracts():
        s = c.get("start_date") or ""
        e = c.get("end_date") or ""
        if s and s <= day_str and (not e or e >= day_str):
            return c
    y, m, _ = map(int, day_str.split("-"))
    return active_contract(y, m)


def contract_work_rules(contract):
    if contract:
        reg_start = normalize_hhmm(contract.get("regular_start")) or DEFAULT_REGULAR_START
        reg_end = normalize_hhmm(contract.get("regular_end")) or DEFAULT_REGULAR_END
        rs_min = hhmm_to_minutes(reg_start)
        re_min = hhmm_to_minutes(reg_end)
        if rs_min is None or re_min is None or re_min <= rs_min:
            reg_start, reg_end = DEFAULT_REGULAR_START, DEFAULT_REGULAR_END
            rs_min, re_min = hhmm_to_minutes(reg_start), hhmm_to_minutes(reg_end)
        try:
            unit = int(contract.get("round_unit", DEFAULT_ROUND_UNIT))
            if not 1 <= unit <= 30:
                unit = DEFAULT_ROUND_UNIT
        except (ValueError, TypeError):
            unit = DEFAULT_ROUND_UNIT
        if "break1_start" in contract or "break1_end" in contract:
            b1s = normalize_hhmm(contract.get("break1_start"))
            b1e = normalize_hhmm(contract.get("break1_end"))
        else:
            b1s, b1e = DEFAULT_BREAK1_START, DEFAULT_BREAK1_END
        if "break2_start" in contract or "break2_end" in contract:
            b2s = normalize_hhmm(contract.get("break2_start"))
            b2e = normalize_hhmm(contract.get("break2_end"))
        else:
            b2s, b2e = DEFAULT_BREAK2_START, DEFAULT_BREAK2_END
    else:
        reg_start, reg_end = DEFAULT_REGULAR_START, DEFAULT_REGULAR_END
        rs_min, re_min = hhmm_to_minutes(reg_start), hhmm_to_minutes(reg_end)
        unit = DEFAULT_ROUND_UNIT
        b1s, b1e = DEFAULT_BREAK1_START, DEFAULT_BREAK1_END
        b2s, b2e = DEFAULT_BREAK2_START, DEFAULT_BREAK2_END

    b1s_min = hhmm_to_minutes(b1s)
    b1e_min = hhmm_to_minutes(b1e)
    if b1s_min is None or b1e_min is None or b1e_min <= b1s_min:
        b1s, b1e, b1s_min, b1e_min, b1_dur = "", "", None, None, 0
    else:
        b1_dur = b1e_min - b1s_min

    b2s_min = hhmm_to_minutes(b2s)
    b2e_min = hhmm_to_minutes(b2e)
    if b2s_min is None or b2e_min is None or b2e_min <= b2s_min:
        b2s, b2e, b2s_min, b2e_min, b2_dur = "", "", None, None, 0
    else:
        b2_dur = b2e_min - b2s_min

    b1_in_reg = (
        max(0, min(re_min, b1e_min) - max(rs_min, b1s_min))
        if b1s_min is not None and b1e_min is not None
        else 0
    )
    scheduled_regular = max(0, (re_min - rs_min) - b1_in_reg)
    overtime_origin = b2e_min if b2e_min is not None and b2_dur > 0 else re_min
    return {
        "regular_start": reg_start,
        "regular_end": reg_end,
        "regular_start_min": rs_min,
        "regular_end_min": re_min,
        "round_unit": unit,
        "break1_start": b1s,
        "break1_end": b1e,
        "break1_start_min": b1s_min,
        "break1_end_min": b1e_min,
        "break1_minutes": b1_dur,
        "break2_start": b2s,
        "break2_end": b2e,
        "break2_start_min": b2s_min,
        "break2_end_min": b2e_min,
        "break2_minutes": b2_dur,
        "overtime_origin_min": overtime_origin,
        "scheduled_regular_minutes": scheduled_regular,
    }


def reporting_period(year, month, closing):
    closing = str(closing)
    if closing == "末":
        return (
            datetime.date(year, month, 1),
            datetime.date(year, month, calendar.monthrange(year, month)[1]),
        )
    d = int(closing)
    end = datetime.date(year, month, d)
    (py, pm) = (year - 1, 12) if month == 1 else (year, month - 1)
    start = datetime.date(py, pm, d + 1)
    return (start, end)


def fiscal_year_range(
    fiscal_year,
    start_month=DEFAULT_FISCAL_START_MONTH,
    start_day=DEFAULT_FISCAL_START_DAY,
):
    start_m = max(1, min(12, int(start_month)))
    s_day = max(1, min(int(start_day), calendar.monthrange(fiscal_year, start_m)[1]))
    fy_start = datetime.date(fiscal_year, start_m, s_day)
    next_s_day = max(
        1, min(int(start_day), calendar.monthrange(fiscal_year + 1, start_m)[1])
    )
    fy_end = datetime.date(fiscal_year + 1, start_m, next_s_day) - datetime.timedelta(
        days=1
    )
    return (fy_start, fy_end)


def default_fiscal_year(
    today,
    start_month=DEFAULT_FISCAL_START_MONTH,
    start_day=DEFAULT_FISCAL_START_DAY,
):
    start_m = max(1, min(12, int(start_month)))
    s_day = max(1, min(int(start_day), calendar.monthrange(today.year, start_m)[1]))
    if (today.month, today.day) >= (start_m, s_day):
        return today.year
    return today.year - 1


def same_workplace_contracts(contract):
    if not contract:
        return []
    title = (contract.get("display_title") or "").strip()
    if not title:
        return [contract]
    matches = [c for c in contracts() if (c.get("display_title") or "").strip() == title]
    return matches or [contract]


def _holiday_scope_id(contract):
    return contract["id"] if contract else "__common__"


def get_contract_holidays(contract):
    cid = _holiday_scope_id(contract)
    prefix = "h:" + cid + ":"
    rows = con.execute(
        "SELECT k, v FROM settings WHERE user_id=? AND k LIKE ?",
        (SHARED_SCOPE, prefix + "%"),
    ).fetchall()
    result = {}
    for row in rows:
        day_str = row["k"][len(prefix) :]
        if _valid_iso_date(day_str) and str(row["v"]).strip():
            result[day_str] = str(row["v"]).strip()
    return result


def save_contract_holidays(contract_id, holidays_map, is_sample=0):
    cid = str(contract_id or "__common__")
    prefix = "h:" + cid + ":"
    con.execute(
        "DELETE FROM settings WHERE user_id=? AND k LIKE ?",
        (SHARED_SCOPE, prefix + "%"),
    )
    cleaned = {}
    for k, v in holidays_map.items():
        day_str = str(k)
        label = str(v).strip()[:100]
        if _valid_iso_date(day_str) and label:
            setval(SHARED_SCOPE, prefix + day_str, label, is_sample=is_sample)
            cleaned[day_str] = label
    con.commit()
    return cleaned


def upsert_contract_holiday(contract, day_str, label, is_sample=0):
    cid = _holiday_scope_id(contract)
    key = "h:" + cid + ":" + str(day_str)
    label = (label or "").strip()[:100]
    if label:
        setval(SHARED_SCOPE, key, label, is_sample=is_sample)
    else:
        con.execute("DELETE FROM settings WHERE user_id=? AND k=?", (SHARED_SCOPE, key))
    con.commit()
    return get_contract_holidays(contract)


def delete_contract_storage(contract):
    cid = contract["id"]
    con.execute(
        "DELETE FROM settings WHERE user_id=? AND (k LIKE ? OR k LIKE ?)",
        (SHARED_SCOPE, "cf:" + cid + ":%", "h:" + cid + ":%"),
    )


def contract_is_workday(contract, day_obj, official_holidays, office_holidays):
    if day_obj.isoformat() in office_holidays:
        return False
    workdays = contract["workdays"] if contract else DEFAULT_WORKDAYS
    work_on_holiday = contract["work_on_holiday"] if contract else False
    if day_obj in official_holidays and not work_on_holiday:
        return False
    return day_obj.weekday() in workdays


# ---------------------------------------------------------
# Events (public: sysadmin only, visible to all; private: per-user)
# ---------------------------------------------------------
def get_public_events():
    rows = con.execute(
        "SELECT day, text FROM events WHERE scope='public' AND user_id=0 ORDER BY day"
    ).fetchall()
    return {r["day"]: r["text"] for r in rows if _valid_iso_date(r["day"]) and r["text"]}


def get_private_events(uid):
    rows = con.execute(
        "SELECT day, text FROM events WHERE scope='private' AND user_id=? ORDER BY day",
        (uid,),
    ).fetchall()
    return {r["day"]: r["text"] for r in rows if _valid_iso_date(r["day"]) and r["text"]}


def get_visible_events(uid):
    pub = get_public_events()
    priv = get_private_events(uid)
    days = sorted(set(pub.keys()) | set(priv.keys()))
    result = {}
    for d in days:
        p_txt = pub.get(d, "")
        u_txt = priv.get(d, "")
        parts = []
        if p_txt:
            parts.append("【全体】" + p_txt)
        if u_txt:
            parts.append(u_txt)
        result[d] = {
            "public": p_txt,
            "private": u_txt,
            "combined": "\n".join(parts),
        }
    return result


def upsert_event(scope, uid, day_str, text, is_sample=0):
    if scope not in ("public", "private"):
        raise ValueError("イベント公開範囲が不正です。")
    owner_id = 0 if scope == "public" else int(uid)
    text = (text or "").strip()[:200]
    if text:
        con.execute(
            "REPLACE INTO events(scope, user_id, day, text, is_sample) VALUES(?,?,?,?,?)",
            (scope, owner_id, day_str, text, 1 if is_sample else 0),
        )
    else:
        con.execute(
            "DELETE FROM events WHERE scope=? AND user_id=? AND day=?",
            (scope, owner_id, day_str),
        )
    con.commit()
