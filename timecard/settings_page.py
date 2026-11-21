"""Role-aware settings screen: billing info, contracts, holiday/event calendar, user management, and sample reset."""

import calendar
import datetime
from decimal import Decimal, ROUND_DOWN
import json
from urllib.parse import quote
from timecard.attendance import dayok
from timecard.auth import (
    ROLE_LABELS,
    ROLE_SYSADMIN,
    can_edit_holidays,
    can_edit_public_events,
    is_sysadmin,
    list_users,
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
    contract_by_id,
    contract_work_rules,
    contracts,
    default_fiscal_year,
    fiscal_year_range,
    get_contract_holidays,
    get_private_events,
    get_public_events,
    same_workplace_contracts,
    save_contract_holidays,
    save_contracts,
    upsert_contract_holiday,
    upsert_event,
    ym_number,
)
from timecard.db import con, resource_root
from timecard.holidays import national_holidays
from timecard.http_utils import esc, html_response, json_response, redirect
from timecard.invoice import DEFAULT_INVOICE_NUMBER
from timecard.layout import layout
from timecard.sample_data import (
    SAMPLE_USER_DEFAULT_PW,
    SAMPLE_USER_LOGIN,
    sample_data_summary,
)
from timecard.settings_store import SHARED_SCOPE, set_shared_val, shared_val

_SETTINGS_SCRIPT_CACHE = None

WEEKDAY_PILLS = [
    (6, "日", "is-sun"),
    (0, "月", ""),
    (1, "火", ""),
    (2, "水", ""),
    (3, "木", ""),
    (4, "金", ""),
    (5, "土", "is-sat"),
]
WEEKDAY_SHORT = "月火水木金土日"


def _settings_script():
    global _SETTINGS_SCRIPT_CACHE
    if _SETTINGS_SCRIPT_CACHE is None:
        _SETTINGS_SCRIPT_CACHE = (
            resource_root() / "assets" / "settings.js"
        ).read_text(encoding="utf-8-sig")
    return _SETTINGS_SCRIPT_CACHE


def _json_for_script(data):
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _floor10(numerator, denominator):
    try:
        n = Decimal(str(numerator))
        d = Decimal(str(denominator))
        if n <= 0 or d <= 0:
            return None
        return int((n / d / Decimal(10)).to_integral_value(rounding=ROUND_DOWN) * 10)
    except (ValueError, ArithmeticError):
        return None


def _money(raw):
    try:
        return "{:,.0f}".format(int(Decimal(str(raw))))
    except (ValueError, ArithmeticError):
        return str(raw)


def _format_workdays(contract):
    wdays = contract.get("workdays", DEFAULT_WORKDAYS)
    order = [6, 0, 1, 2, 3, 4, 5]
    parts = [WEEKDAY_SHORT[d] for d in order if d in wdays]
    if contract.get("work_on_holiday"):
        parts.append("祝")
    return "・".join(parts) if parts else "なし"


def _format_payment_terms(contract):
    offset_labels = {1: "翌月", 2: "翌々月", 3: "3ヶ月後"}
    offset = contract.get("pay_month_offset", DEFAULT_PAY_MONTH_OFFSET)
    pay_day = str(contract.get("pay_day") or DEFAULT_PAY_DAY)
    hol_rule = str(contract.get("pay_holiday_rule") or DEFAULT_PAY_HOLIDAY_RULE)
    day_label = "末" if pay_day == "末" else pay_day + "日"
    hol_label = "前営" if hol_rule == "prev" else "翌営"
    return offset_labels.get(offset, "翌々月") + day_label + "(" + hol_label + ")"


def _format_schedule_summary(contract):
    rules = contract_work_rules(contract)
    b_parts = []
    if rules["break1_minutes"] > 0:
        b_parts.append("昼" + str(rules["break1_minutes"]) + "分")
    if rules["break2_minutes"] > 0:
        b_parts.append("残前" + str(rules["break2_minutes"]) + "分")
    break_text = "・".join(b_parts) if b_parts else "休憩なし"
    return (
        rules["regular_start"]
        + "～"
        + rules["regular_end"]
        + " / "
        + str(rules["round_unit"])
        + "分刻み / "
        + break_text
    )


def _invoice_month_options(contract_list, selected_month):
    rows = con.execute(
        "SELECT DISTINCT SUBSTR(day, 1, 7) AS month FROM work ORDER BY month DESC"
    ).fetchall()
    months = {row["month"] for row in rows if row.get("month")}
    for c in contract_list:
        if c.get("start"):
            months.add(c["start"])
    if selected_month:
        months.add(selected_month)
    months.add(datetime.date.today().strftime("%Y-%m"))
    return "".join(
        '<option value="'
        + esc(m)
        + '"'
        + (" selected" if m == selected_month else "")
        + ">"
        + esc(m.replace("-", "年") + "月")
        + "</option>"
        for m in sorted(months, reverse=True)
    )


def _customer_choices(contract_list, current_customer):
    seen = set()
    choices = []

    def add(name):
        cleaned = (name or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            choices.append(cleaned)

    add(current_customer)
    for c in contract_list:
        add(c.get("customer"))
    return choices


def _select_initial_contract(contract_list, requested_id):
    if requested_id:
        for c in contract_list:
            if c["id"] == requested_id:
                return c
    if not contract_list:
        return None
    today_iso = datetime.date.today().isoformat()
    for c in contract_list:
        s = c.get("start_date") or ""
        e = c.get("end_date") or ""
        if s <= today_iso and (not e or e >= today_iso):
            return c
    return contract_list[0]


def build_calendar_payload(sess, contract_id, fy_raw=None):
    uid = sess["user_id"]
    c = (
        contract_by_id(contract_id)
        if contract_id and contract_id != "__common__"
        else None
    )
    fy_month = (
        c.get("fiscal_start_month", DEFAULT_FISCAL_START_MONTH)
        if c
        else DEFAULT_FISCAL_START_MONTH
    )
    fy_day = (
        c.get("fiscal_start_day", DEFAULT_FISCAL_START_DAY)
        if c
        else DEFAULT_FISCAL_START_DAY
    )
    today = datetime.date.today()
    try:
        fy = int(fy_raw)
        if not 2020 <= fy <= 2098:
            raise ValueError()
    except (ValueError, TypeError):
        fy = default_fiscal_year(today, fy_month, fy_day)

    (fy_start, fy_end) = fiscal_year_range(fy, fy_month, fy_day)
    official = {}
    for y in range(fy_start.year, fy_end.year + 1):
        for d_obj, lbl in national_holidays(y).items():
            official[d_obj.isoformat()] = lbl

    office_holidays = get_contract_holidays(c)
    public_events = get_public_events()
    private_events = get_private_events(uid)

    workdays = c["workdays"] if c else list(DEFAULT_WORKDAYS)
    work_on_holiday = c["work_on_holiday"] if c else False
    same_group = same_workplace_contracts(c) if c else []
    return {
        "contract_id": c["id"] if c else "__common__",
        "contract_name": c["name"] if c else "共通カレンダー",
        "display_title": (c.get("display_title") or "").strip() if c else "",
        "same_workplace_count": len(same_group),
        "fiscal_year": fy,
        "fiscal_start_month": fy_month,
        "fiscal_start_day": fy_day,
        "fy_start": fy_start.isoformat(),
        "fy_end": fy_end.isoformat(),
        "workdays": workdays,
        "work_on_holiday": work_on_holiday,
        "official_holidays": official,
        "office_holidays": office_holidays,
        "public_events": public_events,
        "private_events": private_events,
        "can_edit_holidays": can_edit_holidays(sess),
        "can_edit_public_events": can_edit_public_events(sess),
    }


def handle_calendar_data(sess, q):
    payload = build_calendar_payload(sess, q.get("contract", ""), q.get("fy", ""))
    return json_response(payload)


def handle_holiday_save(sess, p):
    if not can_edit_holidays(sess):
        return json_response(
            {"ok": False, "error": "休日設定はシステム管理者または管理者のみ変更できます。"},
            status=403,
        )
    cid = p.get("contract_id", "").strip()
    day_str = p.get("holiday_day", "").strip()
    label = p.get("holiday_name", "").strip()[:100]
    fy = p.get("fy", "").strip()
    sync_same = p.get("sync_same_title") == "1"
    if not dayok(day_str):
        return json_response({"ok": False, "error": "日付の形式が不正です。"}, status=400)
    c = contract_by_id(cid) if cid and cid != "__common__" else None
    targets = same_workplace_contracts(c) if (c and sync_same) else [c]
    for target in targets:
        upsert_contract_holiday(target, day_str, label, is_sample=0)
    payload = build_calendar_payload(sess, cid, fy)
    return json_response({"ok": True, "calendar": payload, "updated_count": len(targets)})


def handle_event_save(sess, p):
    uid = sess["user_id"]
    cid = p.get("contract_id", "").strip()
    day_str = p.get("event_day", "").strip()
    text = p.get("event_text", "").strip()[:200]
    scope = p.get("event_scope", "private").strip()
    fy = p.get("fy", "").strip()
    if not dayok(day_str):
        return json_response({"ok": False, "error": "日付の形式が不正です。"}, status=400)
    if scope == "public" and not can_edit_public_events(sess):
        return json_response(
            {"ok": False, "error": "パブリック予定はシステム管理者のみ登録・変更できます。"},
            status=403,
        )
    if scope not in ("public", "private"):
        return json_response({"ok": False, "error": "公開範囲が不正です。"}, status=400)
    upsert_event(scope, uid, day_str, text, is_sample=0)
    payload = build_calendar_payload(sess, cid, fy)
    return json_response({"ok": True, "calendar": payload})


def handle_holiday_clear(sess, p):
    if not can_edit_holidays(sess):
        return json_response(
            {"ok": False, "error": "休日設定はシステム管理者または管理者のみ変更できます。"},
            status=403,
        )
    cid = p.get("contract_id", "").strip()
    fy = p.get("fy", "").strip()
    sync_same = p.get("sync_same_title") == "1"
    c = contract_by_id(cid) if cid and cid != "__common__" else None
    targets = same_workplace_contracts(c) if (c and sync_same) else [c]
    for target in targets:
        save_contract_holidays(target["id"] if target else "__common__", {}, is_sample=0)
    payload = build_calendar_payload(sess, cid, fy)
    return json_response({"ok": True, "calendar": payload})


def handle_holiday_copy(sess, p):
    if not can_edit_holidays(sess):
        return json_response(
            {"ok": False, "error": "休日コピーはシステム管理者または管理者のみ実行できます。"},
            status=403,
        )
    target_cid = p.get("target_contract_id", "").strip()
    source_cid = p.get("source_contract_id", "").strip()
    fy = p.get("fy", "").strip()
    target_c = contract_by_id(target_cid)
    source_c = contract_by_id(source_cid)
    if not target_c or not source_c:
        return json_response({"ok": False, "error": "コピー元またはコピー先の契約が見つかりません。"}, status=400)
    src_holidays = get_contract_holidays(source_c)
    save_contract_holidays(target_c["id"], src_holidays, is_sample=0)
    payload = build_calendar_payload(sess, target_c["id"], fy)
    return json_response({"ok": True, "copied": len(src_holidays), "calendar": payload})


def handle_contract_fiscal_save(sess, p):
    if not can_edit_holidays(sess):
        return json_response(
            {"ok": False, "error": "年度開始設定はシステム管理者または管理者のみ変更できます。"},
            status=403,
        )
    cid = p.get("contract_id", "").strip()
    fy = p.get("fy", "").strip()
    try:
        fy_month = int(p.get("fiscal_start_month", DEFAULT_FISCAL_START_MONTH))
        fy_day = int(p.get("fiscal_start_day", DEFAULT_FISCAL_START_DAY))
        if not 1 <= fy_month <= 12:
            raise ValueError("開始月が不正です。")
        max_day = calendar.monthrange(2026, fy_month)[1]
        if not 1 <= fy_day <= max_day:
            raise ValueError("開始日が不正です。")
    except (ValueError, TypeError) as e:
        return json_response({"ok": False, "error": str(e)}, status=400)

    items = contracts()
    updated = False
    for item in items:
        if item["id"] == cid:
            item["fiscal_start_month"] = fy_month
            item["fiscal_start_day"] = fy_day
            updated = True
            break
    if updated:
        save_contracts(items)
    payload = build_calendar_payload(sess, cid, fy)
    return json_response({"ok": True, "calendar": payload})


def handle_settings(sess, p, method, q):
    if method == "POST":
        if not is_sysadmin(sess):
            return html_response(
                layout(
                    "権限エラー",
                    '<div class="card"><p class="notice">基本設定の保存はシステム管理者のみ実行できます。</p>'
                    '<p><a href="/?a=settings">設定画面に戻る</a></p></div>',
                    sess=sess,
                ),
                status=403,
            )
        if "company" in p:
            set_shared_val("company", p.get("company", "").strip()[:100], is_sample=0)
        if "customer" in p:
            set_shared_val("customer", p.get("customer", "").strip()[:100], is_sample=0)
        if "sender_address" in p:
            set_shared_val(
                "sender_address", p.get("sender_address", "").strip()[:200], is_sample=0
            )
        if "bank_account" in p:
            set_shared_val(
                "bank_account", p.get("bank_account", "").strip()[:200], is_sample=0
            )
        if "invoice_note" in p:
            set_shared_val(
                "invoice_note", p.get("invoice_note", "").strip()[:200], is_sample=0
            )
        if "invoice_base_month" in p:
            bm = p.get("invoice_base_month", "").strip()
            try:
                ym_number(bm)
                set_shared_val("invoice_base_month", bm, is_sample=0)
            except (ValueError, TypeError):
                pass
        if "invoice_number" in p:
            inv_no = p.get("invoice_number", "").strip()
            if inv_no.isdigit() and int(inv_no) >= 1:
                set_shared_val("invoice_number", str(int(inv_no)), is_sample=0)
        con.commit()
        return redirect("/?a=settings&msg=" + quote("基本設定を保存しました。"))

    contract_list = contracts()
    selected_contract = _select_initial_contract(contract_list, q.get("contract", ""))
    initial_cal = build_calendar_payload(
        sess,
        selected_contract["id"] if selected_contract else "__common__",
        q.get("fy", ""),
    )

    b = '<div class="settings-page">'
    flash_msg = (q.get("msg") or "").strip()
    if flash_msg:
        b += '<div class="notice">' + esc(flash_msg) + "</div>"

    # ---------------------------------------------------------
    # Sysadmin-only Cards: Basic Settings & Contract History
    # ---------------------------------------------------------
    if is_sysadmin(sess):
        today_ym = datetime.date.today().strftime("%Y-%m")
        current_company = shared_val("company", "")
        current_customer = shared_val("customer", "")
        current_address = shared_val("sender_address", "")
        current_bank = shared_val("bank_account", "")
        current_note = shared_val("invoice_note", "")
        current_base_month = shared_val("invoice_base_month", today_ym) or today_ym
        current_invoice_no = shared_val("invoice_number", DEFAULT_INVOICE_NUMBER)

        customer_choices = _customer_choices(contract_list, current_customer)
        customer_options = ['<option value="">（未選択）</option>']
        for cust in customer_choices:
            customer_options.append(
                '<option value="'
                + esc(cust)
                + '"'
                + (" selected" if cust == current_customer else "")
                + ">"
                + esc(cust)
                + "</option>"
            )
        customer_datalist = "".join(
            '<option value="' + esc(cust) + '"></option>' for cust in customer_choices
        )

        # Card 1: Basic Settings
        b += (
            '<section class="card settings-card">'
            '<div class="settings-card-head"><div><h1>基本設定（自社・請求情報）</h1>'
            '<p class="muted small">請求書・勤務実績表に印字される自社情報、基本請求先、振込先、請求番号の起点を設定します。（システム管理者専用）</p></div></div>'
            '<form method="post" action="/?a=settings" class="settings-form">'
            '<div class="settings-grid-2">'
            '<label class="field"><span>個人名／自社名</span>'
            '<input type="text" name="company" value="'
            + esc(current_company)
            + '" placeholder="例：山田 太郎 ／ 株式会社○○"></label>'
            '<label class="field"><span>基本請求先<small class="field-hint">（下部の契約履歴に登録した請求先から選択）</small></span>'
            '<select name="customer">'
            + "".join(customer_options)
            + "</select></label>"
            "</div>"
            '<label class="field"><span>住所（請求書差出人）</span>'
            '<textarea name="sender_address" rows="3" maxlength="200" placeholder="郵便番号・住所">'
            + esc(current_address)
            + "</textarea></label>"
            '<label class="field"><span>振込先口座</span>'
            '<input type="text" name="bank_account" maxlength="200" value="'
            + esc(current_bank)
            + '" placeholder="銀行名・支店名・種別・口座番号・口座名義"></label>'
            '<label class="field"><span>請求書備考</span>'
            '<textarea name="invoice_note" rows="2" maxlength="200" placeholder="請求書の備考欄に印字する内容">'
            + esc(current_note)
            + "</textarea></label>"
            '<div class="invoice-seq-box">'
            '<div class="field-title">請求番号（生涯連番の起点）</div>'
            '<div class="invoice-seq-row">'
            '<label class="field inline-field"><span>起点月（実績月）</span>'
            '<select name="invoice_base_month" id="invoice-base-month">'
            + _invoice_month_options(contract_list, current_base_month)
            + "</select></label>"
            '<label class="field inline-field"><span>起点番号</span>'
            '<input type="number" name="invoice_number" id="invoice-base-number" min="1" step="1" value="'
            + esc(current_invoice_no)
            + '" placeholder="1"></label>'
            '<div class="invoice-seq-preview-wrap"><span id="invoice-seq-preview" class="small muted"></span></div>'
            "</div></div>"
            '<div class="form-actions"><button type="submit" class="btn-with-icon">'
            '<img src="images/save.png" alt="" aria-hidden="true"><span>基本設定を保存</span></button></div>'
            "</form></section>"
        )

        # Card 2: Contract History
        closing_options = "".join(
            '<option value="'
            + v
            + '">'
            + (v + "日締め" if v != "末" else "末締め")
            + "</option>"
            for v in ("末", "5", "10", "15", "20", "25")
        )
        pay_month_options = "".join(
            '<option value="'
            + str(val_num)
            + '"'
            + (" selected" if val_num == DEFAULT_PAY_MONTH_OFFSET else "")
            + ">"
            + lbl
            + "</option>"
            for val_num, lbl in ((1, "翌月"), (2, "翌々月"), (3, "3ヶ月後"))
        )
        pay_day_choices = [("末", "末日（月末）")] + [
            (str(d), str(d) + "日") for d in range(1, 32)
        ]
        pay_day_options = "".join(
            '<option value="'
            + v
            + '"'
            + (" selected" if v == DEFAULT_PAY_DAY else "")
            + ">"
            + lbl
            + "</option>"
            for v, lbl in pay_day_choices
        )
        pay_hol_options = (
            '<option value="next" selected>翌営業日（次回最速）</option>'
            '<option value="prev">前営業日（前倒し）</option>'
        )
        workday_pills_html = "".join(
            '<label class="workday-pill '
            + cls
            + '"><input type="checkbox" name="workday_'
            + str(day_idx)
            + '" value="1"'
            + (" checked" if day_idx in DEFAULT_WORKDAYS else "")
            + "><span>"
            + lbl
            + "</span></label>"
            for day_idx, lbl, cls in WEEKDAY_PILLS
        ) + '<label class="workday-pill is-hol"><input type="checkbox" name="workday_holiday" value="1"><span>祝</span></label>'

        b += (
            '<section class="card settings-card" id="contract-section">'
            '<div class="settings-card-head"><div><h2>契約履歴</h2>'
            '<p class="muted small">契約ごとに単価・上下限・締日・支払期限・定時・休憩・丸め単位・稼働日を設定します。下の一覧から行をクリックすると編集できます。</p></div>'
            '<div class="contract-head-actions">'
            '<span id="contract-form-mode" class="mode-badge">新規契約の登録</span>'
            '<button type="button" id="contract-reset-btn" class="secondary-btn btn-with-icon">'
            '<img src="images/cleam.png" alt="" aria-hidden="true"><span>入力クリア</span></button>'
            "</div></div>"
            '<form method="post" action="/?a=contract_save" id="contract-form" class="contract-form">'
            '<input type="hidden" name="contract_id" value="">'
            '<input type="hidden" name="workdays_submitted" value="1">'
            '<input type="hidden" name="schedule_submitted" value="1">'
            '<datalist id="customer-suggestions">'
            + customer_datalist
            + "</datalist>"
            '<div class="contract-grid-3">'
            '<label class="field"><span>契約名（ID）<em>*</em></span>'
            '<input type="text" name="contract_name" required placeholder="例：サンプル基本契約"></label>'
            '<label class="field"><span>リスト表示タイトル</span>'
            '<input type="text" name="contract_display_title" placeholder="例：サンプル事業所"></label>'
            '<label class="field"><span>請求先名</span>'
            '<input type="text" name="contract_customer" list="customer-suggestions" placeholder="例：株式会社サンプル"></label>'
            "</div>"
            '<div class="contract-grid-3">'
            '<label class="field"><span>開始日<em>*</em></span>'
            '<input type="date" name="contract_start_date" required></label>'
            '<label class="field"><span>終了日（継続中は空欄）</span>'
            '<input type="date" name="contract_end_date"></label>'
            '<label class="field"><span>消費税率（%）</span>'
            '<input type="number" name="contract_tax" min="0" step="0.1" value="10" placeholder="10"></label>'
            "</div>"
            '<div class="contract-grid-4">'
            '<label class="field"><span>締日</span>'
            '<select name="contract_closing">'
            + closing_options
            + "</select></label>"
            '<label class="field"><span>支払月</span>'
            '<select name="contract_pay_month_offset">'
            + pay_month_options
            + "</select></label>"
            '<label class="field"><span>支払日</span>'
            '<select name="contract_pay_day">'
            + pay_day_options
            + "</select></label>"
            '<label class="field"><span>銀行休業日の扱い</span>'
            '<select name="contract_pay_holiday_rule">'
            + pay_hol_options
            + "</select></label>"
            "</div>"
            '<div class="contract-grid-5">'
            '<label class="field"><span>月額基本金額（円）</span>'
            '<input type="number" name="contract_fee" min="0" step="1" placeholder="500000"></label>'
            '<label class="field"><span>下限時間（h）<em>*</em></span>'
            '<input type="number" name="contract_lower" min="0" step="0.01" required placeholder="140"></label>'
            '<label class="field"><span>上限時間（h）<em>*</em></span>'
            '<input type="number" name="contract_upper" min="0" step="0.01" required placeholder="180"></label>'
            '<label class="field"><span>控除単価（円/h）</span>'
            '<input type="number" name="contract_deduct_rate" min="0" step="1" placeholder="自動計算"></label>'
            '<label class="field"><span>超過単価（円/h）</span>'
            '<input type="number" name="contract_extra_rate" min="0" step="1" placeholder="自動計算"></label>'
            "</div>"
            '<div class="rate-helper-row">'
            '<button type="button" id="calc-rates-btn" class="secondary-btn small-btn">単価を自動計算</button>'
            '<span class="muted small">基本金額 ÷ 下限（控除）／ 基本金額 ÷ 上限（超過）の10円未満切り捨て。確定値の手動入力も可能です。</span>'
            "</div>"
            '<div class="schedule-box">'
            '<div class="field-title">定時時刻・休憩・時刻丸め設定 <span class="muted small">（事業所ごとの定時・休憩・刻み単位を設定します）</span></div>'
            '<div class="schedule-regular-row">'
            '<label class="field"><span>定時開始（入場）</span>'
            '<input type="time" name="contract_regular_start" id="contract-regular-start" value="'
            + DEFAULT_REGULAR_START
            + '" required></label>'
            '<label class="field"><span>定時終了（退場）</span>'
            '<input type="time" name="contract_regular_end" id="contract-regular-end" value="'
            + DEFAULT_REGULAR_END
            + '" required></label>'
            '<label class="field"><span>刻み単位（分）<small class="field-hint">1～30分（未満切捨）</small></span>'
            '<input type="number" name="contract_round_unit" id="contract-round-unit" min="1" max="30" step="1" value="'
            + str(DEFAULT_ROUND_UNIT)
            + '" required></label>'
            "</div>"
            '<div class="schedule-break-list">'
            '<div class="schedule-break-row">'
            '<span class="schedule-break-label">休憩①（昼休憩）</span>'
            '<div class="schedule-time-range">'
            '<input type="time" name="contract_break1_start" id="contract-break1-start" value="'
            + DEFAULT_BREAK1_START
            + '" aria-label="休憩①開始"><span class="muted">～</span>'
            '<input type="time" name="contract_break1_end" id="contract-break1-end" value="'
            + DEFAULT_BREAK1_END
            + '" aria-label="休憩①終了">'
            '<span id="break1-duration" class="duration-pill">60分</span>'
            '<button type="button" class="secondary-btn small-btn" data-clear-break="1">なしにする</button>'
            "</div></div>"
            '<div class="schedule-break-row">'
            '<span class="schedule-break-label">休憩②（時間外前）</span>'
            '<div class="schedule-time-range">'
            '<input type="time" name="contract_break2_start" id="contract-break2-start" value="'
            + DEFAULT_BREAK2_START
            + '" aria-label="休憩②開始"><span class="muted">～</span>'
            '<input type="time" name="contract_break2_end" id="contract-break2-end" value="'
            + DEFAULT_BREAK2_END
            + '" aria-label="休憩②終了">'
            '<span id="break2-duration" class="duration-pill">10分</span>'
            '<button type="button" class="secondary-btn small-btn" data-clear-break="2">なしにする</button>'
            "</div></div></div>"
            '<p class="muted small schedule-hint">定時後の時間外は休憩②の終了時刻から刻み単位でカウントします（休憩②が空欄の場合は定時終了時刻からそのままカウント）。</p>'
            "</div>"
            '<div class="workdays-box">'
            '<div class="field-title">稼働日設定 <span class="muted small">（チェックした曜日・祝日を稼働日として集計／未チェックは休日扱い）</span></div>'
            '<div class="workday-pills">'
            + workday_pills_html
            + "</div></div>"
            '<div class="form-actions">'
            '<button type="submit" id="contract-submit-btn" class="btn-with-icon">'
            '<img src="images/save.png" alt="" aria-hidden="true"><span>契約を登録</span></button>'
            '<button type="button" id="contract-cancel-btn" class="secondary-btn" hidden>新規作成に戻る</button>'
            "</div></form>"
        )

        b += '<div class="contract-list-wrap">'
        if contract_list:
            b += (
                '<div class="scroll"><table id="contract-table" class="contract-table"><thead><tr>'
                "<th>契約名（ID）／表示</th><th>請求先</th><th>契約期間</th>"
                "<th>月額／上下限</th><th>控除／超過単価</th><th>締日・支払・税</th><th>稼働日・定時</th><th>操作</th>"
                "</tr></thead><tbody>"
            )
            for c in contract_list:
                fee_disp = _money(c["fee"]) + "円" if c.get("fee") else "未設定"
                eff_fee = c.get("fee") or "0"
                if c.get("deduct_rate"):
                    deduct_disp = _money(c["deduct_rate"]) + "円"
                else:
                    calc_d = _floor10(eff_fee, c["lower"])
                    deduct_disp = (_money(calc_d) + "円(自)") if calc_d is not None else "—"
                if c.get("extra_rate"):
                    extra_disp = _money(c["extra_rate"]) + "円"
                else:
                    calc_e = _floor10(eff_fee, c["upper"])
                    extra_disp = (_money(calc_e) + "円(自)") if calc_e is not None else "—"
                tax_disp = (c["tax"] if c.get("tax") not in (None, "") else "10") + "%"
                closing_disp = c["closing"] + ("締め" if c["closing"] == "末" else "日締め")
                sample_tag = (
                    ' <span class="sample-pill">サンプル</span>' if c.get("is_sample") else ""
                )
                title_badge = (
                    '<div class="contract-sub-title">表示: ' + esc(c["display_title"]) + "</div>"
                    if c.get("display_title")
                    else ""
                )
                b += (
                    '<tr data-contract-id="'
                    + esc(c["id"])
                    + '" title="クリックして編集"><td><strong>'
                    + esc(c["name"])
                    + "</strong>"
                    + sample_tag
                    + title_badge
                    + "</td><td>"
                    + esc(c.get("customer") or "（基本請求先）")
                    + '</td><td class="nowrap">'
                    + esc(c["start_date"])
                    + " ～ "
                    + esc(c.get("end_date") or "継続中")
                    + '</td><td class="nowrap">'
                    + esc(fee_disp)
                    + '<div class="small muted">'
                    + esc(c["lower"])
                    + "～"
                    + esc(c["upper"])
                    + 'h</div></td><td class="nowrap">'
                    + esc(deduct_disp)
                    + '<div class="small muted">超過 '
                    + esc(extra_disp)
                    + '</div></td><td class="nowrap">'
                    + esc(closing_disp)
                    + " / 税 "
                    + esc(tax_disp)
                    + '<div class="small muted">支払 '
                    + esc(_format_payment_terms(c))
                    + "</div></td><td>"
                    + esc(_format_workdays(c))
                    + '<div class="small muted">'
                    + esc(_format_schedule_summary(c))
                    + '</div></td><td><form method="post" action="/?a=contract_delete" class="inline-delete-form" '
                    + 'onsubmit="return confirm(&quot;契約「'
                    + esc(c["name"])
                    + '」を削除しますか？&quot;)"><input type="hidden" name="contract_id" value="'
                    + esc(c["id"])
                    + '"><button type="submit" class="danger-btn small-btn">削除</button></form></td></tr>'
                )
            b += "</tbody></table></div>"
        else:
            b += '<p class="muted small">登録された契約はまだありません。上のフォームから契約を登録してください。</p>'
        b += "</div></section>"

    # ---------------------------------------------------------
    # Card 3: Annual Holiday & Event Calendar (All Roles, Role-Scoped Editing)
    # ---------------------------------------------------------
    edit_holidays = can_edit_holidays(sess)
    edit_public_ev = can_edit_public_events(sess)
    cal_title = (
        "事業所指定休日・イベントカレンダー"
        if edit_holidays
        else "イベントカレンダー（個人予定）"
    )
    if edit_public_ev:
        cal_desc = "事業所指定休日の管理、個人予定、および全ユーザーに表示されるパブリック予定を登録できます。"
    elif edit_holidays:
        cal_desc = "管理者権限で事業所指定休日とご自身の個人予定を登録できます（パブリック予定は閲覧のみ）。"
    else:
        cal_desc = "ご自身の個人予定を登録できます（事業所休日・全体予定はカレンダー上で確認できます）。"

    cal_contract_options = []
    if contract_list:
        for c in contract_list:
            period_label = c["start_date"] + "～" + (c.get("end_date") or "継続")
            title_part = (c["display_title"] + " / ") if c.get("display_title") else ""
            label = c["name"] + "（" + title_part + period_label + "）"
            cal_contract_options.append(
                '<option value="'
                + esc(c["id"])
                + '"'
                + (" selected" if initial_cal["contract_id"] == c["id"] else "")
                + ">"
                + esc(label)
                + "</option>"
            )
    else:
        cal_contract_options.append('<option value="__common__">共通カレンダー（契約未登録）</option>')

    fiscal_month_options = "".join(
        '<option value="'
        + str(m)
        + '"'
        + (" selected" if m == initial_cal["fiscal_start_month"] else "")
        + ">"
        + str(m)
        + "月</option>"
        for m in range(1, 13)
    )
    fiscal_day_options = "".join(
        '<option value="'
        + str(d)
        + '"'
        + (" selected" if d == initial_cal["fiscal_start_day"] else "")
        + ">"
        + str(d)
        + "日</option>"
        for d in range(1, 32)
    )

    copy_source_options = ['<option value="">別契約から休日をコピー…</option>']
    for c in contract_list:
        copy_source_options.append(
            '<option value="' + esc(c["id"]) + '">' + esc(c["name"]) + "</option>"
        )

    b += (
        '<section class="card settings-card" id="calendar-section">'
        '<div class="settings-card-head"><div><h2>'
        + esc(cal_title)
        + '</h2><p class="muted small">'
        + esc(cal_desc)
        + '</p></div><label class="cal-contract-picker"><span>対象契約</span>'
        '<select id="cal-contract-select">'
        + "".join(cal_contract_options)
        + "</select></label></div>"
        '<div class="cal-toolbar">'
    )
    if edit_holidays:
        b += (
            '<div class="cal-fiscal-config">'
            '<span class="small muted">年度開始</span>'
            '<select id="cal-fiscal-month" aria-label="年度開始月">'
            + fiscal_month_options
            + "</select>"
            '<select id="cal-fiscal-day" aria-label="年度開始日">'
            + fiscal_day_options
            + "</select>"
            '<button type="button" id="cal-fiscal-save" class="secondary-btn small-btn">開始日を保存</button>'
            "</div>"
        )
    b += (
        '<div class="cal-fy-nav">'
        '<button type="button" id="cal-prev-fy" class="secondary-btn cal-nav-btn" aria-label="前年度">'
        '<img src="images/Yesterday.png" alt="前年度"><span>前年度</span></button>'
        '<strong id="cal-fy-title" class="cal-fy-title"></strong>'
        '<button type="button" id="cal-next-fy" class="secondary-btn cal-nav-btn" aria-label="次年度">'
        '<span>次年度</span><img src="images/Tomorrow.png" alt="次年度"></button>'
        "</div>"
    )
    if edit_holidays:
        b += (
            '<div class="cal-copy-box">'
            '<select id="cal-copy-source" aria-label="コピー元契約">'
            + "".join(copy_source_options)
            + "</select>"
            '<button type="button" id="cal-copy-btn" class="secondary-btn small-btn">コピー</button>'
            '<button type="button" id="cal-clear-btn" class="danger-btn small-btn">休日を全クリア</button>'
            "</div>"
        )
    b += "</div>"

    if edit_holidays:
        b += (
            '<div id="cal-sync-bar" class="cal-sync-bar"'
            + ("" if initial_cal["same_workplace_count"] > 1 else " hidden")
            + '><label class="cal-sync-toggle">'
            '<input type="checkbox" id="cal-sync-same" checked>'
            '<span id="cal-sync-label">同じ表示タイトルの契約にも休日変更を同時反映する</span>'
            "</label></div>"
        )

    b += (
        '<div class="cal-meta-bar">'
        '<div class="cal-legend">'
        '<span><i class="legend-swatch is-workday"></i>稼働日</span>'
        '<span><i class="legend-swatch is-off-weekday"></i>所定休日</span>'
        '<span><i class="legend-swatch is-national-holiday"></i>国民の祝日</span>'
        '<span><i class="legend-swatch is-office-holiday"></i>事業所指定休日</span>'
        '<span><i class="legend-swatch is-event"></i>個人予定</span>'
        '<span><i class="legend-swatch is-public-event"></i>全体予定</span>'
        '<span><i class="legend-swatch is-selected"></i>選択中</span>'
        "</div>"
        '<div id="cal-stats" class="small muted"></div>'
        "</div>"
        '<div class="holiday-workspace">'
        '<div id="annual-calendar" class="annual-calendar-grid"></div>'
        '<aside class="holiday-side-panel">'
        '<div class="holiday-editor">'
    )

    if edit_holidays:
        b += (
            '<div class="editor-tabs" role="tablist">'
            '<button type="button" class="editor-tab is-active" id="tab-btn-holiday" data-editor-tab="holiday" role="tab" aria-selected="true">休日登録</button>'
            '<button type="button" class="editor-tab" id="tab-btn-event" data-editor-tab="event" role="tab" aria-selected="false">予定登録</button>'
            "</div>"
        )
    else:
        b += '<h3>個人予定の登録</h3>'

    b += '<p id="holiday-selected-meta" class="holiday-selected-meta small">カレンダーの日付をクリックして選択してください</p>'

    if edit_holidays:
        b += (
            '<form method="post" action="/?a=holiday_save" id="holiday-form" class="editor-pane">'
            '<input type="hidden" name="contract_id" value="'
            + esc(initial_cal["contract_id"])
            + '"><input type="hidden" name="fy" value="'
            + str(initial_cal["fiscal_year"])
            + '">'
            '<label class="field"><span>日付</span>'
            '<input type="date" id="holiday-day-input" name="holiday_day" required></label>'
            '<label class="field"><span>休日名</span>'
            '<input type="text" id="holiday-name-input" name="holiday_name" maxlength="100" placeholder="例：GW、夏期休暇、年末年始"></label>'
            '<div class="holiday-presets">'
            '<button type="button" class="preset-chip" data-holiday-preset="GW">GW</button>'
            '<button type="button" class="preset-chip" data-holiday-preset="夏期休暇">夏期休暇</button>'
            '<button type="button" class="preset-chip" data-holiday-preset="年末年始">年末年始</button>'
            '<button type="button" class="preset-chip" data-holiday-preset="フリー">フリー</button>'
            '<button type="button" class="preset-chip" data-holiday-preset="創立記念日">創立記念日</button>'
            "</div>"
            '<div class="holiday-editor-actions">'
            '<button type="submit" class="btn-with-icon"><img src="images/save.png" alt="" aria-hidden="true"><span>休日を登録</span></button>'
            '<button type="button" id="holiday-delete-btn" class="danger-btn" disabled>削除</button>'
            "</div></form>"
        )

    scope_selector_html = (
        '<label class="field"><span>公開範囲</span>'
        '<select id="event-scope-input" name="event_scope">'
        '<option value="private">個人予定（自分のみ表示）</option>'
        '<option value="public">パブリック予定（全ユーザーに表示）</option>'
        "</select></label>"
        if edit_public_ev
        else '<input type="hidden" id="event-scope-input" name="event_scope" value="private">'
    )
    b += (
        '<form method="post" action="/?a=event_save" id="event-form" class="editor-pane"'
        + (" hidden" if edit_holidays else "")
        + '><input type="hidden" name="contract_id" value="'
        + esc(initial_cal["contract_id"])
        + '"><input type="hidden" name="fy" value="'
        + str(initial_cal["fiscal_year"])
        + '">'
        + scope_selector_html
        + '<label class="field"><span>日付</span>'
        '<input type="date" id="event-day-input" name="event_day" required></label>'
        '<label class="field"><span>予定内容<small class="field-hint">（印刷には出力されません）</small></span>'
        '<textarea id="event-text-input" name="event_text" rows="2" maxlength="200" placeholder="例：定例会議 14:00"></textarea></label>'
        '<div class="holiday-editor-actions">'
        '<button type="submit" class="btn-with-icon event-save-btn"><img src="images/save.png" alt="" aria-hidden="true"><span>予定を登録</span></button>'
        '<button type="button" id="event-delete-btn" class="danger-btn" disabled>削除</button>'
        "</div></form>"
        '<p id="holiday-status" class="holiday-status small muted" role="status"></p>'
        "</div>"
    )

    if edit_holidays:
        b += (
            '<div class="holiday-list-box">'
            '<div class="holiday-list-head"><h3>登録済み休日</h3>'
            '<span id="holiday-list-count" class="count-badge">0件</span></div>'
            '<ul id="holiday-list" class="holiday-list"></ul>'
            '<p id="holiday-other-note" class="small muted"></p>'
            "</div>"
        )

    b += (
        '<div class="holiday-list-box event-list-box">'
        '<div class="holiday-list-head"><h3>登録済み予定</h3>'
        '<span id="event-list-count" class="count-badge is-event-badge">0件</span></div>'
        '<ul id="event-list" class="holiday-list"></ul>'
        '<p id="event-other-note" class="small muted"></p>'
        "</div></aside></div></section>"
    )

    # ---------------------------------------------------------
    # Sysadmin-only Cards: User Management & Sample Data Reset
    # ---------------------------------------------------------
    if is_sysadmin(sess):
        users = list_users()
        b += (
            '<section class="card settings-card" id="users-section">'
            '<div class="settings-card-head"><div><h2>ユーザー管理（システム管理者専用）</h2>'
            '<p class="muted small">一般ユーザーの登録・管理者昇格権限の設定・削除を行います。「管理者昇格可能」にチェックされたユーザーは、ログイン画面で「管理者としてログイン」にチェックを入れると管理者権限（休日・個人予定設定）でログインできます。</p></div></div>'
            '<form method="post" action="/?a=user_create" class="user-create-form">'
            '<div class="contract-grid-4">'
            '<label class="field"><span>ログインID<em>*</em></span>'
            '<input type="text" name="login" required maxlength="60" placeholder="例：tanaka"></label>'
            '<label class="field"><span>表示名</span>'
            '<input type="text" name="display_name" maxlength="60" placeholder="例：田中 花子"></label>'
            '<label class="field"><span>パスワード<em>*</em><small class="field-hint">6文字以上</small></span>'
            '<input type="password" name="password" required minlength="6" autocomplete="new-password"></label>'
            '<label class="field"><span>権限設定</span>'
            '<label class="workday-pill" style="margin-top:2px"><input type="checkbox" name="can_admin" value="1"><span>管理者昇格可能</span></label></label>'
            "</div>"
            '<div class="form-actions"><button type="submit" class="btn-with-icon">'
            '<img src="images/save.png" alt="" aria-hidden="true"><span>ユーザーを登録</span></button></div>'
            "</form>"
            '<div class="contract-list-wrap"><div class="scroll"><table class="contract-table" id="user-table"><thead><tr>'
            "<th>ログインID</th><th>表示名</th><th>アカウント種別</th><th>管理者昇格</th><th>パスワード変更／保存</th><th>削除</th>"
            "</tr></thead><tbody>"
        )
        for u in users:
            is_self = int(u["id"]) == int(sess["user_id"])
            is_sa = u["role"] == ROLE_SYSADMIN
            sample_badge = (
                ' <span class="sample-pill">サンプル</span>' if u["is_sample"] else ""
            )
            sample_hint = (
                '<div class="small muted">初期PW: ' + esc(SAMPLE_USER_DEFAULT_PW) + "</div>"
                if u["is_sample"] and u["login"] == SAMPLE_USER_LOGIN
                else ""
            )
            role_txt = ROLE_LABELS.get(u["role"], u["role"])
            form_id = "user-edit-" + str(u["id"])
            can_admin_cell = (
                '<span class="muted small">常時フル権限</span>'
                if is_sa
                else (
                    '<label class="inline-check"><input type="checkbox" form="'
                    + form_id
                    + '" name="can_admin" value="1"'
                    + (" checked" if u["can_admin"] else "")
                    + ">昇格可</label>"
                )
            )
            del_cell = (
                '<span class="muted small">ログイン中</span>'
                if is_self
                else (
                    '<form method="post" action="/?a=user_delete" class="inline-delete-form" '
                    'onsubmit="return confirm(&quot;ユーザー「'
                    + esc(u["login"])
                    + '」とこのユーザーの勤務データを削除します。よろしいですか？&quot;)">'
                    '<input type="hidden" name="target_user_id" value="'
                    + str(u["id"])
                    + '"><button type="submit" class="danger-btn small-btn">削除</button></form>'
                )
            )
            b += (
                "<tr><td><strong>"
                + esc(u["login"])
                + "</strong>"
                + sample_badge
                + sample_hint
                + '</td><td><input type="text" form="'
                + form_id
                + '" name="display_name" value="'
                + esc(u["display_name"])
                + '" class="table-inline-input"></td><td><span class="role-badge is-'
                + esc(u["role"])
                + '">'
                + esc(role_txt)
                + "</span></td><td>"
                + can_admin_cell
                + '</td><td><form method="post" action="/?a=user_update" id="'
                + form_id
                + '" class="inline-user-edit"><input type="hidden" name="target_user_id" value="'
                + str(u["id"])
                + '"><input type="password" name="new_password" placeholder="新PW(任意)" minlength="6" autocomplete="new-password" class="table-inline-pw">'
                '<button type="submit" class="secondary-btn small-btn">更新</button></form></td><td>'
                + del_cell
                + "</td></tr>"
            )
        b += "</tbody></table></div></div></section>"

        # Card 5: Sample Data Reset (Sysadmin Only)
        sample_stats = sample_data_summary()
        b += (
            '<section class="card settings-card" id="sample-reset-section">'
            '<div class="settings-card-head"><div><h2>サンプルデータの初期化・リセット（システム管理者専用）</h2>'
            '<p class="muted small">初回導入時に投入された架空のサンプルデータ（サンプル契約・サンプル基本設定・サンプル休日・サンプル予定・サンプル実績）のみを削除します。<strong>登録済みユーザーと権限設定、および手動で登録・編集したデータは保持されます。</strong></p></div></div>'
            '<div class="sample-reset-row">'
            '<div class="small">現在のサンプルデータ残件数：<strong>'
            + str(sample_stats["total"])
            + "件</strong>（実績 "
            + str(sample_stats["work"])
            + "件 / 予定 "
            + str(sample_stats["events"])
            + "件 / 設定・契約・休日 "
            + str(sample_stats["settings"])
            + "項目）</div>"
            '<form method="post" action="/?a=sample_reset" onsubmit="return confirm(&quot;サンプルデータ（架空の契約・休日・予定・サンプル実績）を削除します。ユーザーと権限、手動入力データは残ります。よろしいですか？&quot;)">'
            '<button type="submit" id="sample-reset-btn" class="danger-btn"'
            + (" disabled" if sample_stats["total"] == 0 else "")
            + ">サンプルデータを削除してリセット</button></form>"
            "</div></section>"
        )

    b += "</div>"

    settings_payload = {
        "contracts": contract_list,
        "initial_calendar": initial_cal,
        "today": datetime.date.today().isoformat(),
        "current_month": datetime.date.today().strftime("%Y-%m"),
        "active_role": sess["active_role"],
        "can_edit_holidays": edit_holidays,
        "can_edit_public_events": edit_public_ev,
    }
    b += (
        '<script type="application/json" id="settings-data">'
        + _json_for_script(settings_payload)
        + "</script>"
    )
    b += "<script>" + _settings_script() + "</script>"
    return html_response(layout("設定", b, sess=sess))
