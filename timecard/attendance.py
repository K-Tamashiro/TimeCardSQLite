"""Time normalization and contract-aware attendance rounding rules."""

import datetime
from timecard.contracts import contract_for_day, contract_work_rules
from timecard.settings_store import val


def normalize_time(s):
    s = s.strip().replace("：", ":")
    if s.isdigit() and len(s) in (3, 4):
        s = s.zfill(4)
        s = s[:2] + ":" + s[2:]
    return s


def dt(s):
    try:
        return datetime.datetime.strptime(normalize_time(s), "%H:%M")
    except Exception:
        return None


def rounded(t, up, unit=15):
    if not t:
        return ""
    unit = max(1, min(30, int(unit)))
    mins = t.hour * 60 + t.minute
    mins = (mins + unit - 1) // unit * unit if up else mins // unit * unit
    return "%02d:%02d" % (mins // 60, mins % 60)


def minutes(s):
    t = dt(s)
    return t.hour * 60 + t.minute if t else None


def _fmt_hhmm(total_minutes):
    return "%02d:%02d" % (total_minutes // 60, total_minutes % 60)


def dayok(s):
    try:
        return datetime.date.fromisoformat(s).isoformat() == s
    except Exception:
        return False


def calc_detail(r, uid, day=None, contract=None):
    """Calculate worked hours using per-contract schedule/break/rounding and per-day early flag."""
    resolved_contract = (
        contract
        if contract is not None
        else (contract_for_day(day) if day and dayok(day) else None)
    )
    rules = contract_work_rules(resolved_contract)
    reg_start = rules["regular_start_min"]
    reg_end = rules["regular_end_min"]
    unit = rules["round_unit"]
    b1_s = rules["break1_start_min"]
    b1_e = rules["break1_end_min"]
    b2_s = rules["break2_start_min"]
    b2_e = rules["break2_end_min"]
    ot_origin = rules["overtime_origin_min"]
    scheduled_regular = rules["scheduled_regular_minutes"]

    early_work = bool(day and val(uid, "early:" + day, "") == "1")

    if r["actual_in"]:
        start = normalize_time(r["actual_in"])
        a = minutes(start)
        if a is not None and (not early_work) and a < reg_start:
            start = rules["regular_start"]
            a = reg_start
    else:
        raw_in = minutes(r["clock_in"])
        if raw_in is None:
            start = ""
            a = None
        elif (not early_work) and raw_in <= reg_start:
            a = reg_start
            start = rules["regular_start"]
        elif not early_work:
            a = reg_start + ((raw_in - reg_start + unit - 1) // unit) * unit
            start = _fmt_hhmm(a)
        elif raw_in == reg_start:
            a = reg_start
            start = rules["regular_start"]
        else:
            a = ((raw_in + unit - 1) // unit) * unit
            start = _fmt_hhmm(a)

    raw_end = r["actual_out"] or r["clock_out"]
    raw = minutes(raw_end)
    if a is None or raw is None or raw < a:
        return dict(
            start=start,
            end=raw_end or "",
            gross=None,
            break_minutes=None,
            regular=None,
            overtime=None,
            early=None,
            early_work=early_work,
            after_overtime=None,
            late_early=None,
            total=None,
        )

    if raw >= ot_origin + unit:
        end_minutes = ot_origin + ((raw - ot_origin) // unit) * unit
    elif raw >= reg_end:
        end_minutes = reg_end
    else:
        end_minutes = (raw // unit) * unit

    if end_minutes < a:
        return dict(
            start=start,
            end="",
            gross=None,
            break_minutes=None,
            regular=None,
            overtime=None,
            early=None,
            early_work=early_work,
            after_overtime=None,
            late_early=None,
            total=None,
        )

    end = _fmt_hhmm(end_minutes)
    lunch = (
        max(0, min(end_minutes, b1_e) - max(a, b1_s))
        if b1_s is not None and b1_e is not None
        else 0
    )
    after_overtime = (
        max(0, end_minutes - ot_origin) if end_minutes >= ot_origin else 0
    )
    evening = (
        max(0, min(end_minutes, b2_e) - max(a, b2_s))
        if after_overtime > 0 and b2_s is not None and b2_e is not None
        else 0
    )
    if early_work and a < reg_start:
        early_end = min(end_minutes, reg_start)
        early_b1 = (
            max(0, min(early_end, b1_e) - max(a, b1_s))
            if b1_s is not None and b1_e is not None
            else 0
        )
        early_minutes = max(0, early_end - a - early_b1)
    else:
        early_minutes = 0

    gross = end_minutes - a
    override = val(uid, "break:" + day, "") if day else ""
    break_minutes = int(override) if override.isdigit() else lunch + evening
    total = max(0, gross - break_minutes)
    overtime = min(total, early_minutes + after_overtime)
    regular = max(0, total - overtime)
    late_early = max(0, scheduled_regular - regular)
    display_total = regular + overtime
    return dict(
        start=start,
        end=end,
        gross=gross,
        break_minutes=break_minutes,
        regular=regular,
        overtime=overtime,
        early=early_minutes,
        early_work=early_work,
        after_overtime=after_overtime,
        late_early=late_early,
        total=display_total,
    )
