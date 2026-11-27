"""Daily entry popup and monthly attendance report rendering."""

import datetime
import json
from timecard.attendance import calc_detail, dayok
from timecard.auth import can_use_csv
from timecard.contracts import (
    DEFAULT_WORKDAYS,
    closing_workday,
    contract_display_title,
    contract_work_rules,
    get_contract_holidays,
    get_visible_events,
    is_absence_label,
)
from timecard.db import con, resource_root
from timecard.formatting import dual, fmt
from timecard.holidays import national_holidays
from timecard.http_utils import esc, html_response, json_response
from timecard.invoice import DEFAULT_SENDER_NAME, render_invoice
from timecard.layout import layout
from timecard.settings_store import SHARED_SCOPE, month_limit, shared_val, val
from timecard.work_store import getwork

_REPORT_SCRIPT_CACHE = None


def _report_script():
    global _REPORT_SCRIPT_CACHE
    if _REPORT_SCRIPT_CACHE is None:
        _REPORT_SCRIPT_CACHE = (resource_root() / "assets" / "report.js").read_text(
            encoding="utf-8-sig"
        )
    return _REPORT_SCRIPT_CACHE


def _json_for_script(data):
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _compact_hhmm(hhmm):
    digits = str(hhmm or "").replace(":", "")
    if len(digits) == 4 and digits.startswith("0"):
        return digits[1:]
    return digits


def _overtime_cell(overtime_minutes, early_minutes):
    cell = dual(overtime_minutes)
    if early_minutes:
        cell += '<span class="early-tag">早出 %d:%02d</span>' % (
            early_minutes // 60,
            early_minutes % 60,
        )
    return cell


def _summary_text(start, end, total_min, early_min):
    text = (
        "計算用時刻："
        + (start or "—")
        + " ～ "
        + (end or "—")
        + "\u3000実績："
        + fmt(total_min)
    )
    if early_min:
        text += "（うち早出 " + fmt(early_min) + "）"
    return text


def render_report(
    sess,
    day,
    selected,
    year,
    month,
    contract,
    period_start,
    period_end,
    auto_open=False,
):
    uid = sess["user_id"]
    today_iso = datetime.date.today().isoformat()
    r = getwork(uid, day)
    prev = (selected - datetime.timedelta(days=1)).isoformat()
    nxt = (selected + datetime.timedelta(days=1)).isoformat()
    official = national_holidays(year)
    official.update(national_holidays(period_start.year))
    official.update(national_holidays(period_end.year))
    office_holidays = get_contract_holidays(contract)
    visible_events = get_visible_events(uid)
    selected_event_info = visible_events.get(day, {})
    selected_event = selected_event_info.get("combined", "")
    workdays = contract["workdays"] if contract else DEFAULT_WORKDAYS
    work_on_holiday = contract["work_on_holiday"] if contract else False
    selected_office_label = office_holidays.get(day, "")
    selected_office_absence = is_absence_label(selected_office_label)
    selected_label = selected_office_label or official.get(selected, "")
    selected_note = r["note"] or ""
    selected_absence = is_absence_label(selected_note) or selected_office_absence
    selected_is_holiday = (
        (bool(selected_office_label) and not selected_office_absence)
        or (selected in official and not work_on_holiday)
        or "【祝】" in selected_note
    )
    selected_class = (
        "absence"
        if selected_absence
        else (
            "holiday"
            if selected_is_holiday
            or (selected.weekday() not in workdays and selected.weekday() not in (5, 6))
            else (
                "sunday"
                if selected.weekday() == 6 and 6 not in workdays
                else "saturday" if selected.weekday() == 5 and 5 not in workdays else ""
            )
        )
    )
    weekday = "月火水木金土日"[selected.weekday()]
    rules = contract_work_rules(contract)
    reg_start_compact = _compact_hhmm(rules["regular_start"])
    reg_end_compact = _compact_hhmm(rules["regular_end"])
    reg_placeholder = reg_start_compact + " / " + reg_end_compact
    b1_min = rules["break1_minutes"]
    b2_min = rules["break2_minutes"]
    auto_break_note = (
        "休憩時間が空欄の場合は自動計算（通常%d分・時間外%d分）"
        % (b1_min, b1_min + b2_min)
    )
    detail = calc_detail(r, uid, day, contract=contract)
    (start, end, m) = (detail["start"], detail["end"], detail["total"])
    suggested_break = str(
        b1_min + b2_min
        if detail["after_overtime"] is not None and detail["after_overtime"] > 0
        else b1_min
    )
    selected_break = val(uid, "break:" + day, "")
    days = (period_end - period_start).days + 1
    work_start = None
    work_end = None
    if contract:
        c_start_str = contract.get("start_date") or contract.get("work_start") or ""
        if c_start_str and dayok(c_start_str):
            work_start = datetime.date.fromisoformat(c_start_str)
        c_end_str = contract.get("end_date") or ""
        if c_end_str and dayok(c_end_str):
            work_end = datetime.date.fromisoformat(c_end_str)
    period_rows = []
    extra_holiday_days = set()
    for d in range(1, days + 1):
        x = period_start + datetime.timedelta(days=d - 1)
        ds = x.isoformat()
        rr = getwork(uid, ds)
        if "【祝】" in (rr["note"] or ""):
            extra_holiday_days.add(ds)
        period_rows.append((d, x, ds, rr))
    closing_date = closing_workday(
        period_start,
        period_end,
        contract,
        official,
        office_holidays,
        work_start=work_start,
        work_end=work_end,
        extra_holiday_days=extra_holiday_days,
    )
    closing_day_iso = closing_date.isoformat() if closing_date else ""
    selected_is_closing = bool(closing_day_iso and day == closing_day_iso)
    days_data = {
        day: {
            "day": day,
            "weekday": weekday,
            "prev": prev,
            "nxt": nxt,
            "cls": selected_class,
            "holiday_label": selected_label,
            "event": selected_event,
            "is_closing": selected_is_closing,
            "clock_in": r["clock_in"].replace(":", ""),
            "clock_out": r["clock_out"].replace(":", ""),
            "early_work": bool(detail["early_work"]),
            "early_fmt": fmt(detail["early"]) if detail["early"] else "",
            "break_minutes": selected_break,
            "suggested_break": suggested_break,
            "start": start or "—",
            "end": end or "—",
            "total_fmt": fmt(m),
            "report": r["report"],
            "note": r["note"],
        }
    }
    entry_card_classes = "card selected-day"
    if selected_class:
        entry_card_classes += " " + selected_class
    if selected_is_closing:
        entry_card_classes += " is-closing"
    entry_html = (
        '<dialog id="entry-dialog" class="entry-dialog" data-auto-open="'
        + ("1" if auto_open else "0")
        + '" data-selected-day="'
        + esc(day)
        + '" data-today="'
        + esc(today_iso)
        + '" aria-labelledby="entry-day-label">'
        + '<div class="'
        + entry_card_classes
        + '" id="entry-card"><div class="entry-dialog-top"><div class="clock-with-icon">'
        '<img src="images/TimeCard.png" alt="" aria-hidden="true" class="clock-icon">'
        '<div class="clock" id="clock">--:--:--</div></div>'
        '<div id="entry-status-boxes" class="entry-status-boxes"'
        + ("" if (selected_event or selected_is_closing) else " hidden")
        + ">"
        '<div id="entry-event-box" class="entry-event-box"'
        + ("" if selected_event else " hidden")
        + '><span class="entry-event-badge">イベント</span><span id="entry-event-text" class="entry-event-text">'
        + esc(selected_event)
        + "</span></div>"
        '<div id="entry-closing-box" class="entry-closing-box"'
        + ("" if selected_is_closing else " hidden")
        + ' title="契約締日（最終稼働日）"><span class="entry-closing-badge">締日</span></div>'
        "</div>"
        '<div class="entry-regular-slot">'
        '<button type="button" class="regular-btn icon-btn" id="regular-time" tabindex="-1"'
        ' data-regular-start="'
        + esc(reg_start_compact)
        + '" data-regular-end="'
        + esc(reg_end_compact)
        + '" aria-label="定時刻印（'
        + esc(reg_placeholder)
        + '）" title="定時刻印（'
        + esc(reg_placeholder)
        + '）">'
        '<img src="images/fixed-time.png" alt="定時刻印"></button></div>'
        '<button type="button" id="entry-close" class="entry-close icon-btn" aria-label="閉じる" title="閉じる">'
        '<img src="images/close.png" alt="閉じる"></button></div>'
        '<div class="flex day-navigation"><a href="/?day='
        + prev
        + '&amp;open=1" id="entry-prev" class="day-nav-icon" aria-label="前日" title="前日"><img src="images/Yesterday.png" alt="前日"></a>'
        '<h2 class="day-label" id="entry-day-label">'
        + esc(day)
        + "（"
        + weekday
        + '）</h2><a href="/?day='
        + nxt
        + '&amp;open=1" id="entry-next" class="day-nav-icon" aria-label="翌日" title="翌日"><img src="images/Tomorrow.png" alt="翌日"></a>'
        '<a href="/?open=1" id="entry-today" class="icon-btn entry-today-btn" aria-label="今日" title="今日"><img src="images/today.png" alt="今日"></a></div>'
    )
    entry_html += (
        '<p class="small" id="entry-holiday-label"'
        + ("" if selected_label else " hidden")
        + ">"
        + esc(selected_label)
        + "</p>"
    )
    entry_html += (
        '<div class="punch-row"><form method="post" action="/?a=punch">'
        '<input type="hidden" name="kind" value="in"><button class="punch in" type="submit">出勤</button>'
        '</form><form method="post" action="/?a=punch"><input type="hidden" name="kind" value="out">'
        '<button class="punch out" type="submit">退勤</button></form></div>'
    )
    entry_html += (
        '<form method="post" action="/?a=save" id="entry-form"><input type="hidden" name="day" value="'
        + day
        + '"><div class="entry-fields">'
        '<div class="entry-field">'
        '<div class="entry-field-head">'
        '<label for="entry-clock-in">出勤時刻</label>'
        '<label class="early-check" title="チェック時は定時前の打刻時刻から勤務時間をカウントします">'
        '<input type="checkbox" id="entry-early" name="early_work" value="1"'
        + (" checked" if detail["early_work"] else "")
        + "><span>早出</span></label>"
        "</div>"
        '<span class="time-with-clear">'
        '<input type="text" id="entry-clock-in" inputmode="numeric" pattern="(?:[0-9]{3,4}|[0-9]{1,2}:[0-9]{2})" '
        'placeholder="'
        + esc(reg_placeholder)
        + '" maxlength="5" autocomplete="off" tabindex="1" class="time-entry" name="clock_in" value="'
        + esc(r["clock_in"].replace(":", ""))
        + '"><button type="button" class="clear-time icon-btn" tabindex="-1" data-clear="clock_in" aria-label="出勤時刻をクリア" title="クリア"><img src="images/cleam.png" alt="クリア"></button></span></div>'
        '<div class="entry-field">'
        '<div class="entry-field-head"><label for="entry-clock-out">退勤時刻</label></div>'
        '<span class="time-with-clear">'
        '<input type="text" id="entry-clock-out" inputmode="numeric" pattern="(?:[0-9]{3,4}|[0-9]{1,2}:[0-9]{2})" '
        'placeholder="'
        + esc(reg_placeholder)
        + '" maxlength="5" autocomplete="off" tabindex="2" class="time-entry" name="clock_out" value="'
        + esc(r["clock_out"].replace(":", ""))
        + '"><button type="button" class="clear-time icon-btn" tabindex="-1" data-clear="clock_out" aria-label="退勤時刻をクリア" title="クリア"><img src="images/cleam.png" alt="クリア"></button></span></div>'
        '<div class="entry-field entry-field-break">'
        '<div class="entry-field-head"><label for="entry-break">休憩(分)</label></div>'
        '<input type="number" min="0" max="1440" step="1" id="entry-break" name="break_minutes" tabindex="3" placeholder="自動 '
        + suggested_break
        + '" value="'
        + esc(selected_break)
        + '"></div>'
        '</div><p class="muted small">'
        + esc(auto_break_note)
        + '</p><p class="muted small" id="entry-summary">'
        + esc(_summary_text(start, end, m, detail["early"]))
        + '</p><label class="entry-report" for="entry-report">1行日報</label><textarea id="entry-report" name="report" tabindex="4" rows="2">'
        + esc(r["report"])
        + '</textarea><div class="note-search-row"><label class="entry-note" for="entry-note">備考<input id="entry-note" class="note-input" name="note" tabindex="5" value="'
        + esc(r["note"])
        + '"></label><div class="entry-search"><label for="work-search">全月検索（作業内容・備考）</label><div class="search-controls">'
        '<input type="search" id="work-search" placeholder="検索キーワード">'
        '<button type="button" id="work-search-button" class="search-icon-btn icon-btn" aria-label="検索" title="検索"><img src="images/Search.png" alt="検索"></button>'
        '</div></div></div><div class="save-row"><button type="submit" class="btn-with-icon" tabindex="6"><img src="images/save.png" alt="" aria-hidden="true"><span>保存</span></button>'
        '<span class="muted small">Tab：出勤 → 退勤 → 休憩 → 日報 → 備考 → 保存</span></div></form></div></dialog>'
    )

    b = ""
    sender_name = (shared_val("company", "") or "").strip() or DEFAULT_SENDER_NAME
    sender_file_suffix = sender_name.replace(" ", "").replace("\u3000", "")
    display_title = contract_display_title(contract)
    print_title_text = (
        "勤務実績表"
        + ("\u3000" + display_title if display_title else "")
        + "\u3000"
        + sender_name
    )
    b += (
        "<script>function printMonthlyReport(){const original=document.title;const "
        'enabled=document.getElementById("print-invoice").checked;document.body.classList.toggle("invoice-mod'
        'e",enabled);document.title="'
        + str(year)
        + "年"
        + "%02d" % month
        + '月"+(enabled?"請求書・作業実績":"作業実績")+"_"+'
        + _json_for_script(sender_file_suffix)
        + ';window.addEventListener("afterprint",function(){document.titl'
        'e=original;document.body.classList.remove("invoice-mode")},{once:true});window.print()}</script>'
    )
    b += (
        '<div class="card print-sheet"><div class="print-report-head"><div><div class="print-report-title">'
        + esc(print_title_text)
        + '</div><div class="print-report-month">'
        + esc(period_start.strftime("%Y/%m/%d"))
        + " ～ "
        + esc(period_end.strftime("%Y/%m/%d"))
        + '</div></div><div class="print-stamps"><div class="print-stamp">担当印</div>'
        '<div class="print-stamp">承認印</div></div></div>'
        + report_toolbar(uid, year, month, contract, period_start, period_end)
        + '<div class="scroll"><table><thead><tr><th>日付</th><th>出勤</th><th>退勤</th><th>休憩(分)</th><th>定時</th><th>時間外</th><th>遅刻早退</th><th>合計</th><th>作業内容</th><th>備考</th></tr></thead><tbody>'
    )

    sums = [
        {
            "regular": 0,
            "overtime": 0,
            "early": 0,
            "late_early": 0,
            "total": 0,
            "absence": 0,
            "days": 0,
            "otdays": 0,
            "scheduled": 0,
        }
        for _ in range(3)
    ]

    def subtotal(label, part):
        z = sums[part]
        return (
            '<tr class="summary'
            + (" monthly-total" if part == 2 else "")
            + '"><th colspan="4">'
            + label
            + "</th><td>"
            + dual(z["regular"])
            + "</td><td>"
            + _overtime_cell(z["overtime"], z["early"])
            + '</td><td class="late-early">'
            + dual(z["late_early"])
            + "</td><td>"
            + dual(z["total"])
            + '</td><td colspan="2">稼働 '
            + str(z["days"])
            + "/"
            + str(z["scheduled"])
            + "日（残業 "
            + str(z["otdays"])
            + "日）\u3000不就業 ▲%.2fh" % (z["absence"] / 60)
            + "</td></tr>"
        )

    show_half_subtotals = bool(contract and contract.get("show_half_subtotals"))
    subtotal_layout = (
        contract.get("subtotal_layout", "split") if contract else "split"
    )

    for d, x, ds, rr in period_rows:
        detail = calc_detail(rr, uid, ds, contract=contract)
        office_label = office_holidays.get(ds, "")
        office_absence = is_absence_label(office_label)
        label = office_label or official.get(x, "")
        note = rr["note"] or ""
        absence = is_absence_label(note) or office_absence
        is_holiday = (
            (bool(office_label) and not office_absence)
            or (x in official and not work_on_holiday)
            or "【祝】" in note
        )
        cls = (
            "absence"
            if absence
            else (
                "holiday"
                if is_holiday
                or (x.weekday() not in workdays and x.weekday() not in (5, 6))
                else (
                    "sunday"
                    if x.weekday() == 6 and 6 not in workdays
                    else "saturday" if x.weekday() == 5 and 5 not in workdays else ""
                )
            )
        )
        for part in (0 if d <= 15 else 1, 2):
            z = sums[part]
            for k in ("regular", "overtime", "early", "late_early", "total"):
                z[k] += detail[k] or 0
            if (
                x.weekday() in workdays
                and (not is_holiday)
                and (work_start is None or x >= work_start)
                and (work_end is None or x <= work_end)
            ):
                z["scheduled"] += 1
            if absence:
                z["absence"] += rules["scheduled_regular_minutes"]
            if detail["total"] is not None and detail["total"] > 0:
                z["days"] += 1
            if detail["overtime"] is not None and detail["overtime"] > 0:
                z["otdays"] += 1
        row_break = val(uid, "break:" + ds, "")
        ev_info = visible_events.get(ds, {})
        day_event = ev_info.get("combined", "")
        has_public_ev = bool(ev_info.get("public"))
        is_closing_day = bool(closing_day_iso and ds == closing_day_iso)
        days_data[ds] = {
            "day": ds,
            "weekday": "月火水木金土日"[x.weekday()],
            "prev": (x - datetime.timedelta(days=1)).isoformat(),
            "nxt": (x + datetime.timedelta(days=1)).isoformat(),
            "cls": cls,
            "holiday_label": label,
            "event": day_event,
            "is_closing": is_closing_day,
            "clock_in": rr["clock_in"].replace(":", ""),
            "clock_out": rr["clock_out"].replace(":", ""),
            "early_work": bool(detail["early_work"]),
            "early_fmt": fmt(detail["early"]) if detail["early"] else "",
            "break_minutes": row_break,
            "suggested_break": str(
                b1_min + b2_min
                if detail["after_overtime"] is not None and detail["after_overtime"] > 0
                else b1_min
            ),
            "start": detail["start"] or "—",
            "end": detail["end"] or "—",
            "total_fmt": fmt(detail["total"]),
            "report": rr["report"],
            "note": rr["note"],
        }
        row_classes = "day-row"
        if cls:
            row_classes += " " + cls
        if day_event:
            row_classes += " has-event"
        if ds == day:
            row_classes += " is-active"
        if ds == today_iso:
            row_classes += " today-row"
        badges = []
        if day_event:
            badges.append(
                '<span class="event-dot'
                + (" is-public" if has_public_ev else "")
                + '" title="イベント：'
                + esc(day_event)
                + '">'
                + ("全体" if has_public_ev else "予定")
                + "</span>"
            )
        if is_closing_day:
            badges.append(
                '<span class="closing-dot" title="契約締日（最終稼働日）">締日</span>'
            )
        day_badges_html = (
            '<span class="day-badges">' + "".join(badges) + "</span>"
            if badges
            else ""
        )
        b += (
            '<tr class="'
            + row_classes
            + '" data-day="'
            + ds
            + '"><td><div class="day-cell"><a href="/?day='
            + ds
            + '&amp;open=1"><span class="screen-date">'
            + ("%02d月" % x.month if d == 1 or x.day == 1 else "")
            + "%02d" % x.day
            + '</span><span class="print-date">'
            + ("%02d月" % x.month if d == 1 or x.day == 1 else "")
            + "%02d" % x.day
            + "</span> ("
            + "月火水木金土日"[x.weekday()]
            + ")</a>"
            + day_badges_html
            + '<form method="post" action="/?a=clear_day" style="margin:0" onsubmit="return confirm(&quot;'
            + ds
            + ' の勤務実績と日報をクリアします。備考は残します。よろしいですか？&quot;)"><input type="hidden" name="day" value="'
            + ds
            + '"><button type="submit" class="day-clear icon-btn" title="この日の実績をクリア（備考は保持）" aria-label="'
            + ds
            + ' の実績をクリア" tabindex="-1"><img src="images/cleam.png" alt="クリア"></button></form></div></td><td>'
            + esc(rr["clock_in"])
            + "</td><td>"
            + esc(rr["clock_out"])
            + "</td><td>"
            + ("—" if detail["break_minutes"] is None else str(detail["break_minutes"]))
            + "</td><td>"
            + dual(detail["regular"])
            + "</td><td>"
            + _overtime_cell(detail["overtime"], detail["early"])
            + '</td><td class="late-early">'
            + dual(detail["late_early"])
            + "</td><td>"
            + dual(detail["total"])
            + '</td><td class="col-report"><div class="cell-clamp">'
            + esc(rr["report"])
            + '</div></td><td class="col-note"><div class="cell-clamp">'
            + esc(note or label)
            + "</div></td></tr>"
        )
        if show_half_subtotals and subtotal_layout != "bottom" and d == 15:
            b += subtotal("前半小計（前半15日）", 0).replace(
                'class="summary', 'class="screen-subtotal summary', 1
            )
    if show_half_subtotals:
        if subtotal_layout == "bottom":
            b += subtotal("前半小計（前半15日）", 0).replace(
                'class="summary', 'class="screen-subtotal summary', 1
            )
        b += subtotal("後半小計（16日～最終日）", 1).replace(
            'class="summary', 'class="screen-subtotal summary', 1
        )
    b += subtotal("月間合計", 2)
    if show_half_subtotals:
        print_footer = (
            subtotal("前半小計（前半15日）", 0)
            + subtotal("後半小計（16日～最終日）", 1)
            + subtotal("月間合計", 2)
        )
    else:
        print_footer = subtotal("月間合計", 2)

    lower_raw = (
        contract["lower"]
        if contract
        else month_limit(SHARED_SCOPE, "lower", year, month, "140")
    )
    upper_raw = (
        contract["upper"]
        if contract
        else month_limit(SHARED_SCOPE, "upper", year, month, "180")
    )
    try:
        lower_minutes = round(float(lower_raw) * 60)
        upper_minutes = round(float(upper_raw) * 60)
        if lower_minutes < 0 or upper_minutes < lower_minutes:
            raise ValueError()
        worked = sums[2]["total"]
        if worked < lower_minutes:
            diff = lower_minutes - worked
            status = '<span class="over">下限まで不足 ' + dual(diff) + "</span>"
        elif worked > upper_minutes:
            diff = worked - upper_minutes
            status = '<span class="over">上限超過 ' + dual(diff) + "</span>"
        else:
            status = '<span class="within">契約範囲内</span>'
        contract_row = (
            '<tr class="contract-status"><th colspan="4">契約時間</th><td colspan="2">下限 '
            + dual(lower_minutes)
            + '</td><td colspan="2">上限 '
            + dual(upper_minutes)
            + '</td><td colspan="2">'
            + status
            + "</td></tr>"
        )
    except (ValueError, OverflowError):
        contract_row = '<tr class="contract-status"><th colspan="4">契約時間</th><td colspan="6">設定値を確認してください</td></tr>'
    b += contract_row
    print_footer += contract_row

    invoice_html = render_invoice(
        year, month, contract, period_end, lower_raw, upper_raw, sums
    )
    b += (
        '</tbody></table></div><div class="print-footer"><table><colgroup><col style="width:17%">'
        '<col span="2" style="width:6%"><col span="5" style="width:7%"><col style="width:28%">'
        '<col style="width:8%"></colgroup><tbody>'
        + print_footer
        + "</tbody></table></div></div>"
    )
    b = invoice_html + b

    # CSV import/export is restricted to sysadmin only
    if can_use_csv(sess):
        b += (
            '<details class="card csv-import"><summary>CSVインポート/エクスポート</summary>'
            '<p class="small">CSV出力と同じ列名・UTF-8形式。既存日付は上書きします。（システム管理者専用）</p>'
            '<form method="post" action="/?a=import"><textarea name="csv" placeholder="CSVの内容を貼り付け"></textarea>'
            '<div class="csv-actions">'
            '<button type="submit" class="icon-btn csv-action-btn" aria-label="CSVインポート" title="CSVインポート"><img src="images/csv-inp.png" alt="CSVインポート"></button>'
            '<a class="icon-btn csv-action-btn" href="/?a=export&amp;day='
            + esc(day)
            + '" aria-label="CSVエクスポート" title="CSVエクスポート"><img src="images/csv-exp.png" alt="CSVエクスポート"></a>'
            "</div></form></details>"
        )

    b += entry_html
    b += (
        '<dialog id="search-dialog" aria-labelledby="search-title">'
        '<div class="search-dialog-heading"><h2 id="search-title">全月検索</h2>'
        '<button type="button" id="search-close" class="entry-close icon-btn" aria-label="閉じる" title="閉じる"><img src="images/close.png" alt="閉じる"></button></div>'
        '<div class="search-controls dialog-search-controls">'
        '<input type="search" id="dialog-work-search" placeholder="検索キーワード">'
        '<button type="button" id="dialog-work-search-button" class="search-icon-btn icon-btn" aria-label="検索" title="検索"><img src="images/Search.png" alt="検索"></button></div>'
        '<p id="search-message" role="status"></p><ul id="search-results"></ul></dialog>'
    )
    b += (
        '<script type="application/json" id="work-days-data">'
        + _json_for_script(days_data)
        + "</script>"
    )
    b += "<script>" + _report_script() + "</script>"
    return html_response(
        layout(
            "勤務表",
            b,
            header_actions=report_header_actions(year, month, contract=contract),
            sess=sess,
        )
    )


def month_options(uid, selected_month):
    rows = con.execute(
        "SELECT DISTINCT SUBSTR(day, 1, 7) AS month FROM work WHERE user_id=? ORDER BY month DESC",
        (uid,),
    ).fetchall()
    months = {row["month"] for row in rows if row.get("month")}
    months.add(selected_month)
    return "".join(
        '<option value="'
        + esc(m)
        + '-01"'
        + (" selected" if m == selected_month else "")
        + ">"
        + esc(m.replace("-", "年") + "月")
        + "</option>"
        for m in sorted(months, reverse=True)
    )


def search_work(uid, query):
    query = query.strip().casefold()
    if not query:
        return []
    rows = con.execute(
        "SELECT day, report, note FROM work WHERE user_id=? ORDER BY day DESC",
        (uid,),
    ).fetchall()
    return [
        dict(day=row["day"], report=row["report"] or "", note=row["note"] or "")
        for row in rows
        if query in (row["report"] or "").casefold()
        or query in (row["note"] or "").casefold()
    ]


def handle_search(sess, query):
    return json_response(search_work(sess["user_id"], query))


def report_header_actions(year, month, contract=None):
    rules = contract_work_rules(contract)
    return (
        '<div class="header-actions">'
        '<button type="button" class="icon-btn header-icon-btn" id="open-today-entry" aria-label="今日を入力" title="今日を入力">'
        '<img src="images/today.png" alt="今日を入力"></button>'
        '<button type="button" class="icon-btn header-icon-btn" id="toolbar-search-button" aria-label="全月検索" title="全月検索">'
        '<img src="images/Compare.png" alt="全月検索"></button>'
        '<form method="post" action="/?a=bulk_regular" onsubmit="return confirm(&quot;この月の未入力の平日を '
        + esc(rules["regular_start"])
        + "～"
        + esc(rules["regular_end"])
        + ' に一括登録します。よろしいですか？&quot;)">'
        '<input type="hidden" name="month" value="%04d-%02d">' % (year, month)
        + '<button type="submit" class="icon-btn header-icon-btn" aria-label="平日一括定時" title="平日一括定時">'
        '<img src="images/fixed-time.png" alt="平日一括定時"></button></form>'
        "</div>"
    )


def report_toolbar(uid, year, month, contract, period_start, period_end):
    display_title = contract_display_title(contract)
    title = (display_title + " " if display_title else "") + "実績表"
    previous = (period_start - datetime.timedelta(days=1)).isoformat()
    following = (period_end + datetime.timedelta(days=1)).isoformat()
    return (
        '<div class="report-heading"><h2>' + esc(title) + "</h2>"
        '<div class="report-print-actions"><label class="invoice-toggle">'
        '<input type="checkbox" id="print-invoice">請求書</label>'
        '<button type="button" class="print-btn icon-btn" onclick="printMonthlyReport()" aria-label="印刷" title="印刷">'
        '<img src="images/Print.png" alt="印刷"></button></div></div>'
        '<div class="report-navigation"><form method="get" action="/" class="month-picker">'
        '<select name="day" aria-label="登録月" onchange="this.form.submit()">'
        + month_options(uid, "%04d-%02d" % (year, month))
        + "</select>"
        "<noscript><button>表示</button></noscript></form>"
        '<div class="report-period-nav">'
        '<a href="/?day=' + previous + '" class="day-nav-icon" aria-label="前月" title="前月"><img src="images/Yesterday.png" alt="前月"></a>'
        '<span class="report-period">'
        + esc(period_start.strftime("%Y/%m/%d"))
        + " ～ "
        + esc(period_end.strftime("%Y/%m/%d"))
        + "</span>"
        '<a href="/?day=' + following + '" class="day-nav-icon" aria-label="翌月" title="翌月"><img src="images/Tomorrow.png" alt="翌月"></a>'
        "</div></div>"
    )
