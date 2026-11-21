"""Validated attendance, contract, user management, CSV, and sample reset handlers."""

import calendar
import csv
import datetime
from decimal import Decimal
import io
from urllib.parse import quote
from timecard.attendance import dayok, dt, normalize_time
from timecard.auth import (
    ROLE_USER,
    can_use_csv,
    create_user,
    delete_user,
    is_sysadmin,
    update_user,
)
from timecard.contracts import (
    DEFAULT_BREAK1_END,
    DEFAULT_BREAK1_START,
    DEFAULT_BREAK2_END,
    DEFAULT_BREAK2_START,
    DEFAULT_FISCAL_START_DAY,
    DEFAULT_FISCAL_START_MONTH,
    DEFAULT_PAY_DAY,
    DEFAULT_PAY_HOLIDAY_RULE,
    DEFAULT_PAY_MONTH_OFFSET,
    DEFAULT_REGULAR_END,
    DEFAULT_REGULAR_START,
    DEFAULT_ROUND_UNIT,
    DEFAULT_WORKDAYS,
    active_contract,
    contract_is_workday,
    contract_work_rules,
    contracts,
    delete_contract_storage,
    get_contract_holidays,
    hhmm_to_minutes,
    new_contract_id,
    normalize_hhmm,
    reporting_period,
    save_contract_holidays,
    save_contracts,
)
from timecard.csv_io import csv_export
from timecard.db import con
from timecard.holidays import national_holidays
from timecard.http_utils import (
    csv_response,
    esc,
    html_response,
    redirect,
    text_response,
)
from timecard.layout import layout
from timecard.sample_data import reset_sample_data
from timecard.settings_store import delval, setval
from timecard.work_store import getwork, savework


def _forbidden(sess, message="この操作を実行する権限がありません。"):
    return html_response(
        layout(
            "権限エラー",
            '<div class="card"><p class="notice">'
            + esc(message)
            + '</p><p><a href="/">勤務表に戻る</a></p></div>',
            sess=sess,
        ),
        status=403,
    )


def _error_page(sess, message, back_url="/?a=settings", back_label="設定画面に戻る"):
    return html_response(
        layout(
            "入力エラー",
            '<div class="card"><p class="notice">'
            + esc(message)
            + '</p><p><a href="'
            + esc(back_url)
            + '">'
            + esc(back_label)
            + "</a></p></div>",
            sess=sess,
        ),
        status=400,
    )


def handle_punch(sess, p, today):
    uid = sess["user_id"]
    day = today.isoformat()
    t = datetime.datetime.now().strftime("%H:%M")
    key = "clock_in" if p.get("kind") == "in" else "clock_out"
    savework(uid, day, {key: t}, is_sample=0)
    return redirect("/?day=" + day)


def handle_save(sess, p):
    uid = sess["user_id"]
    day = p.get("day", "")
    if not dayok(day):
        return text_response("Invalid date", status=400)
    fields = {
        k: p.get(k, "")[:2000] for k in ("clock_in", "clock_out", "report", "note")
    }
    for k in ("clock_in", "clock_out"):
        fields[k] = normalize_time(fields[k])
    if any((fields[k] and (not dt(fields[k])) for k in ("clock_in", "clock_out"))):
        return text_response("Invalid time", status=400)
    rest = p.get("break_minutes", "").strip()
    if rest and (not rest.isdigit() or int(rest) > 1440):
        return text_response("Invalid break", status=400)
    if rest:
        setval(uid, "break:" + day, rest, is_sample=0)
    else:
        delval(uid, "break:" + day)
    if p.get("early_work") == "1":
        setval(uid, "early:" + day, "1", is_sample=0)
    else:
        delval(uid, "early:" + day)
    savework(uid, day, fields, is_sample=0)
    return redirect("/?day=" + day)


def handle_bulk_regular(sess, p):
    uid = sess["user_id"]
    target = p.get("month", "")
    try:
        (yy, mm) = map(int, target.split("-"))
        if not (1 <= yy <= 9999 and 1 <= mm <= 12):
            raise ValueError()
        datetime.date(yy, mm, 1)
    except (ValueError, TypeError):
        return text_response("Invalid month", status=400)
    bulk_c = active_contract(yy, mm)
    (bulk_start, bulk_end) = reporting_period(
        yy, mm, bulk_c.get("closing", "末") if bulk_c else "末"
    )
    official_days = national_holidays(yy)
    official_days.update(national_holidays(bulk_start.year))
    official_days.update(national_holidays(bulk_end.year))
    office_holidays = get_contract_holidays(bulk_c)
    c_start = (
        datetime.date.fromisoformat(bulk_c["start_date"])
        if bulk_c and bulk_c.get("start_date") and dayok(bulk_c["start_date"])
        else None
    )
    c_end = (
        datetime.date.fromisoformat(bulk_c["end_date"])
        if bulk_c and bulk_c.get("end_date") and dayok(bulk_c["end_date"])
        else None
    )
    bulk_rules = contract_work_rules(bulk_c)
    for dd in range((bulk_end - bulk_start).days + 1):
        current = bulk_start + datetime.timedelta(days=dd)
        if c_start and current < c_start:
            continue
        if c_end and current > c_end:
            continue
        if not contract_is_workday(bulk_c, current, official_days, office_holidays):
            continue
        ds = current.isoformat()
        existing = getwork(uid, ds)
        if any(
            existing[k]
            for k in ("clock_in", "clock_out", "actual_in", "actual_out", "report", "note")
        ):
            continue
        savework(
            uid,
            ds,
            {
                "clock_in": bulk_rules["regular_start"],
                "clock_out": bulk_rules["regular_end"],
            },
            is_sample=0,
        )
    return redirect("/?day=" + bulk_end.isoformat())


def handle_clear_day(sess, p):
    uid = sess["user_id"]
    target = p.get("day", "")
    if not dayok(target):
        return text_response("Invalid date", status=400)
    savework(
        uid,
        target,
        {
            "clock_in": "",
            "clock_out": "",
            "actual_in": "",
            "actual_out": "",
            "report": "",
        },
        is_sample=0,
    )
    delval(uid, "break:" + target)
    delval(uid, "early:" + target)
    con.commit()
    return redirect("/?day=" + target)


def handle_export(sess, year, month):
    if not can_use_csv(sess):
        return _forbidden(sess, "CSVエクスポートはシステム管理者のみ利用できます。")
    return csv_response(
        csv_export(sess["user_id"], year, month),
        "timecard-%04d%02d.csv" % (year, month),
    )


def handle_import(sess, p):
    if not can_use_csv(sess):
        return _forbidden(sess, "CSVインポートはシステム管理者のみ利用できます。")
    uid = sess["user_id"]
    raw = p.get("csv", "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(raw))
    count = 0
    for r in reader:
        d = r.get("日付", "")
        if not dayok(d):
            continue
        values = dict(
            zip(
                ("clock_in", "clock_out", "actual_in", "actual_out", "report", "note"),
                [
                    r.get(k, "")
                    for k in ("出勤打刻", "退勤打刻", "実績開始", "実績終了", "日報", "備考")
                ],
            )
        )
        if any(
            values[k] and (not dt(values[k]))
            for k in ("clock_in", "clock_out", "actual_in", "actual_out")
        ):
            continue
        savework(uid, d, values, is_sample=0)
        count += 1
    return html_response(
        layout(
            "インポート完了",
            '<div class="card"><p>'
            + str(count)
            + '件取り込みました。</p><p><a href="/">勤務表に戻る</a></p></div>',
            sess=sess,
        )
    )


def handle_contract_save(sess, p):
    if not is_sysadmin(sess):
        return _forbidden(sess, "契約設定の変更はシステム管理者のみ実行できます。")
    try:
        editing_id = p.get("contract_id", "").strip()
        name = p.get("contract_name", "").strip()[:100]
        display_title = p.get("contract_display_title", "").strip()[:100]
        customer = p.get("contract_customer", "").strip()[:100]

        start_date = p.get("contract_start_date", "").strip()
        end_date = p.get("contract_end_date", "").strip()
        if not start_date or not dayok(start_date):
            raise ValueError("開始日の形式が不正です。")
        start_ym = start_date[:7]
        if end_date:
            if not dayok(end_date):
                raise ValueError("終了日の形式が不正です。")
            if end_date < start_date:
                raise ValueError("終了日は開始日以降の日付を指定してください。")
            end_ym = end_date[:7]
        else:
            end_ym = ""

        lo = p.get("contract_lower", "").strip()
        hi = p.get("contract_upper", "").strip()
        closing = p.get("contract_closing", "末").strip() or "末"
        if not name or closing not in ("5", "10", "15", "20", "25", "末"):
            raise ValueError("契約名または締日が不正です。")
        if Decimal(lo) < 0 or Decimal(hi) < Decimal(lo):
            raise ValueError("下限・上限時間の設定が不正です。")

        fee = p.get("contract_fee", "").strip()
        if fee and (Decimal(fee) < 0 or Decimal(fee) != Decimal(fee).to_integral_value()):
            raise ValueError("月額基本金額は0以上の整数で入力してください。")
        deduct_rate = p.get("contract_deduct_rate", "").strip()
        if deduct_rate and (
            Decimal(deduct_rate) < 0
            or Decimal(deduct_rate) != Decimal(deduct_rate).to_integral_value()
        ):
            raise ValueError("控除単価は0以上の整数で入力してください。")
        extra_rate = p.get("contract_extra_rate", "").strip()
        if extra_rate and (
            Decimal(extra_rate) < 0
            or Decimal(extra_rate) != Decimal(extra_rate).to_integral_value()
        ):
            raise ValueError("超過単価は0以上の整数で入力してください。")
        tax = p.get("contract_tax", "").strip()
        if tax and Decimal(tax) < 0:
            raise ValueError("消費税率は0以上で入力してください。")

        existing = contracts()
        target_index = None
        existing_record = None
        if editing_id:
            for idx, c in enumerate(existing):
                if c["id"] == editing_id:
                    target_index = idx
                    existing_record = c
                    break
            if existing_record is None:
                raise ValueError("編集対象の契約が見つかりません。")

        for c in existing:
            if existing_record and c["id"] == existing_record["id"]:
                continue
            if c["name"] == name:
                raise ValueError("同じ契約名（ID）が既に登録されています。")
            other_start = c.get("start_date") or ""
            other_end = c.get("end_date") or "9999-12-31"
            this_end = end_date or "9999-12-31"
            if start_date <= other_end and other_start <= this_end:
                raise ValueError("契約期間が他の契約と重複しています。")

        if p.get("workdays_submitted") == "1":
            workdays = [d for d in range(7) if p.get("workday_" + str(d)) == "1"]
            work_on_holiday = p.get("workday_holiday") == "1"
        elif existing_record:
            workdays = list(existing_record.get("workdays", DEFAULT_WORKDAYS))
            work_on_holiday = bool(existing_record.get("work_on_holiday", False))
        else:
            workdays = list(DEFAULT_WORKDAYS)
            work_on_holiday = False

        fy_month = (
            existing_record.get("fiscal_start_month", DEFAULT_FISCAL_START_MONTH)
            if existing_record
            else DEFAULT_FISCAL_START_MONTH
        )
        fy_day = (
            existing_record.get("fiscal_start_day", DEFAULT_FISCAL_START_DAY)
            if existing_record
            else DEFAULT_FISCAL_START_DAY
        )

        schedule_submitted = p.get("schedule_submitted") == "1"
        raw_rs = p.get("contract_regular_start", "").strip()
        raw_re = p.get("contract_regular_end", "").strip()
        regular_start = (
            normalize_hhmm(raw_rs)
            if raw_rs
            else (
                existing_record.get("regular_start", DEFAULT_REGULAR_START)
                if existing_record
                else DEFAULT_REGULAR_START
            )
        )
        regular_end = (
            normalize_hhmm(raw_re)
            if raw_re
            else (
                existing_record.get("regular_end", DEFAULT_REGULAR_END)
                if existing_record
                else DEFAULT_REGULAR_END
            )
        )
        rs_min = hhmm_to_minutes(regular_start)
        re_min = hhmm_to_minutes(regular_end)
        if rs_min is None or re_min is None or re_min <= rs_min:
            raise ValueError("定時終了時刻は定時開始時刻より後にしてください。")

        raw_unit = p.get("contract_round_unit", "").strip()
        if raw_unit:
            if not raw_unit.isdigit() or not (1 <= int(raw_unit) <= 30):
                raise ValueError("刻み単位は1～30分の整数で入力してください。")
            round_unit = int(raw_unit)
        elif existing_record:
            round_unit = int(existing_record.get("round_unit", DEFAULT_ROUND_UNIT))
        else:
            round_unit = DEFAULT_ROUND_UNIT

        def _parse_break(sk, ek, label, ds, de, rsk, rek):
            s_val = p.get(sk, "").strip()
            e_val = p.get(ek, "").strip()
            if not schedule_submitted and (not s_val) and (not e_val):
                if existing_record:
                    return (existing_record.get(rsk, ds), existing_record.get(rek, de))
                return (ds, de)
            if not s_val and not e_val:
                return ("", "")
            if bool(s_val) != bool(e_val):
                raise ValueError(label + "は開始・終了の両方を入力してください（なしの場合は両方空欄）。")
            ns = normalize_hhmm(s_val)
            ne = normalize_hhmm(e_val)
            if not ns or not ne or hhmm_to_minutes(ne) <= hhmm_to_minutes(ns):
                raise ValueError(label + "の終了時刻は開始時刻より後にしてください。")
            return (ns, ne)

        break1_start, break1_end = _parse_break(
            "contract_break1_start",
            "contract_break1_end",
            "休憩①（昼休憩）",
            DEFAULT_BREAK1_START,
            DEFAULT_BREAK1_END,
            "break1_start",
            "break1_end",
        )
        break2_start, break2_end = _parse_break(
            "contract_break2_start",
            "contract_break2_end",
            "休憩②（時間外前休憩）",
            DEFAULT_BREAK2_START,
            DEFAULT_BREAK2_END,
            "break2_start",
            "break2_end",
        )
        if break2_start and hhmm_to_minutes(break2_start) < re_min:
            raise ValueError("休憩②（時間外前休憩）の開始時刻は定時終了時刻以降にしてください。")

        raw_pmo = p.get("contract_pay_month_offset", "").strip()
        if raw_pmo:
            if not raw_pmo.isdigit() or int(raw_pmo) not in (1, 2, 3):
                raise ValueError("支払月の設定が不正です。")
            pay_month_offset = int(raw_pmo)
        elif existing_record:
            pay_month_offset = int(
                existing_record.get("pay_month_offset", DEFAULT_PAY_MONTH_OFFSET)
            )
        else:
            pay_month_offset = DEFAULT_PAY_MONTH_OFFSET

        raw_pday = p.get("contract_pay_day", "").strip()
        if raw_pday:
            if raw_pday == "末":
                pay_day = "末"
            elif raw_pday.isdigit() and 1 <= int(raw_pday) <= 31:
                pay_day = str(int(raw_pday))
            else:
                raise ValueError("支払日の設定が不正です。")
        elif existing_record:
            pay_day = str(existing_record.get("pay_day", DEFAULT_PAY_DAY))
        else:
            pay_day = DEFAULT_PAY_DAY

        raw_phol = p.get("contract_pay_holiday_rule", "").strip()
        if raw_phol:
            if raw_phol not in ("next", "prev"):
                raise ValueError("銀行休業日の扱いが不正です。")
            pay_holiday_rule = raw_phol
        elif existing_record:
            pay_holiday_rule = str(
                existing_record.get("pay_holiday_rule", DEFAULT_PAY_HOLIDAY_RULE)
            )
        else:
            pay_holiday_rule = DEFAULT_PAY_HOLIDAY_RULE

        cid = existing_record["id"] if existing_record else new_contract_id()
        record = dict(
            id=cid,
            name=name,
            display_title=display_title,
            customer=customer,
            start=start_ym,
            end=end_ym,
            start_date=start_date,
            end_date=end_date,
            work_start=start_date if not start_date.endswith("-01") else "",
            lower=lo,
            upper=hi,
            closing=closing,
            fee=fee,
            deduct_rate=deduct_rate,
            extra_rate=extra_rate,
            tax=tax,
            workdays=workdays,
            work_on_holiday=work_on_holiday,
            fiscal_start_month=fy_month,
            fiscal_start_day=fy_day,
            regular_start=regular_start,
            regular_end=regular_end,
            round_unit=round_unit,
            break1_start=break1_start,
            break1_end=break1_end,
            break2_start=break2_start,
            break2_end=break2_end,
            pay_month_offset=pay_month_offset,
            pay_day=pay_day,
            pay_holiday_rule=pay_holiday_rule,
            is_sample=False,
        )
        if target_index is not None:
            existing[target_index] = record
        else:
            existing.append(record)
        save_contracts(existing)
        if existing_record is None and display_title:
            for other in existing:
                if (
                    other["id"] != cid
                    and (other.get("display_title") or "").strip() == display_title
                ):
                    save_contract_holidays(cid, get_contract_holidays(other), is_sample=0)
                    break
    except (ValueError, ArithmeticError, TypeError, KeyError) as e:
        return _error_page(sess, str(e) or "契約設定が不正です。")
    return redirect("/?a=settings&contract=" + quote(cid))


def handle_contract_delete(sess, p):
    if not is_sysadmin(sess):
        return _forbidden(sess, "契約の削除はシステム管理者のみ実行できます。")
    cid = p.get("contract_id", "").strip()
    existing = contracts()
    removed = [c for c in existing if c["id"] == cid]
    kept = [c for c in existing if c["id"] != cid]
    save_contracts(kept)
    for c in removed:
        delete_contract_storage(c)
    con.commit()
    return redirect("/?a=settings")


def handle_user_create(sess, p):
    if not is_sysadmin(sess):
        return _forbidden(sess, "ユーザー登録はシステム管理者のみ実行できます。")
    try:
        create_user(
            login=p.get("login", ""),
            password=p.get("password", ""),
            display_name=p.get("display_name", ""),
            role=ROLE_USER,
            can_admin=p.get("can_admin") == "1",
            is_sample=False,
        )
    except ValueError as e:
        return _error_page(sess, str(e))
    return redirect("/?a=settings&msg=" + quote("ユーザーを登録しました。"))


def handle_user_update(sess, p):
    if not is_sysadmin(sess):
        return _forbidden(sess, "ユーザー情報の変更はシステム管理者のみ実行できます。")
    try:
        uid = int(p.get("target_user_id", "0"))
        update_user(
            user_id=uid,
            display_name=p.get("display_name", ""),
            can_admin=p.get("can_admin") == "1",
            new_password=p.get("new_password", "").strip() or None,
        )
    except (ValueError, TypeError) as e:
        return _error_page(sess, str(e))
    return redirect("/?a=settings&msg=" + quote("ユーザー情報を更新しました。"))


def handle_user_delete(sess, p):
    if not is_sysadmin(sess):
        return _forbidden(sess, "ユーザーの削除はシステム管理者のみ実行できます。")
    try:
        uid = int(p.get("target_user_id", "0"))
        delete_user(uid, sess["user_id"])
    except (ValueError, TypeError) as e:
        return _error_page(sess, str(e))
    return redirect("/?a=settings&msg=" + quote("ユーザーを削除しました。"))


def handle_sample_reset(sess):
    if not is_sysadmin(sess):
        return _forbidden(sess, "サンプルデータのリセットはシステム管理者のみ実行できます。")
    counts = reset_sample_data()
    msg = (
        "サンプルデータを削除しました（実績:%d件 / 予定:%d件 / 設定項目:%d件）。ユーザーと権限は保持されています。"
        % (counts["work"], counts["events"], counts["settings"])
    )
    return redirect("/?a=settings&msg=" + quote(msg))
