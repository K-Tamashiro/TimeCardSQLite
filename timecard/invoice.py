"""Invoice calculation and printable invoice rendering (public standalone edition)."""

import calendar
import datetime
from decimal import Decimal, ROUND_DOWN
from timecard.attendance import dayok
from timecard.contracts import (
    DEFAULT_PAY_DAY,
    DEFAULT_PAY_HOLIDAY_RULE,
    DEFAULT_PAY_MONTH_OFFSET,
    contract_is_workday,
    get_contract_holidays,
    ym_number,
)
from timecard.holidays import national_holidays
from timecard.http_utils import esc
from timecard.settings_store import shared_val

DEFAULT_SENDER_NAME = "（個人名／自社名 未設定）"
DEFAULT_CUSTOMER_NAME = "（請求先 未設定）"
DEFAULT_INVOICE_NUMBER = "1"


def _multiline_esc(text):
    return "<br>".join(esc(line) for line in str(text or "").splitlines())


def invoice_number_for_month(year, month):
    today_ym = datetime.date.today().strftime("%Y-%m")
    base_month = (shared_val("invoice_base_month", today_ym) or today_ym).strip()
    try:
        base_ym = ym_number(base_month)
    except (ValueError, TypeError):
        base_ym = ym_number(today_ym)
    try:
        base_number = int(
            str(shared_val("invoice_number", DEFAULT_INVOICE_NUMBER)).strip()
            or DEFAULT_INVOICE_NUMBER
        )
    except (ValueError, TypeError):
        base_number = 1
    current_ym = year * 12 + month - 1
    return max(1, base_number + (current_ym - base_ym))


def _is_bank_holiday(d, holiday_cache):
    if d.weekday() >= 5:
        return True
    if (d.month == 1 and d.day in (1, 2, 3)) or (d.month == 12 and d.day == 31):
        return True
    if d.year not in holiday_cache:
        holiday_cache[d.year] = national_holidays(d.year)
    return d in holiday_cache[d.year]


def calculate_due_date(period_end, contract):
    offset = DEFAULT_PAY_MONTH_OFFSET
    pay_day = DEFAULT_PAY_DAY
    holiday_rule = DEFAULT_PAY_HOLIDAY_RULE
    if contract:
        try:
            cand = int(contract.get("pay_month_offset", DEFAULT_PAY_MONTH_OFFSET))
            if cand in (1, 2, 3):
                offset = cand
        except (ValueError, TypeError):
            offset = DEFAULT_PAY_MONTH_OFFSET
        raw_day = str(contract.get("pay_day") or DEFAULT_PAY_DAY).strip()
        if raw_day == "末" or (raw_day.isdigit() and 1 <= int(raw_day) <= 31):
            pay_day = "末" if raw_day == "末" else str(int(raw_day))
        raw_rule = str(
            contract.get("pay_holiday_rule") or DEFAULT_PAY_HOLIDAY_RULE
        ).strip()
        if raw_rule in ("next", "prev"):
            holiday_rule = raw_rule

    total_months = period_end.year * 12 + (period_end.month - 1) + offset
    due_y = total_months // 12
    due_m = total_months % 12 + 1
    last_day = calendar.monthrange(due_y, due_m)[1]
    day_num = last_day if pay_day == "末" else min(int(pay_day), last_day)
    due_day = datetime.date(due_y, due_m, day_num)

    holiday_cache = {}
    step = -1 if holiday_rule == "prev" else 1
    while _is_bank_holiday(due_day, holiday_cache):
        due_day += datetime.timedelta(days=step)
    return due_day


def format_due_date(due_day):
    return "%04d年%02d月%02d日（%s）" % (
        due_day.year,
        due_day.month,
        due_day.day,
        "月火水木金土日"[due_day.weekday()],
    )


def render_invoice(year, month, contract, period_end, lower_raw, upper_raw, sums):
    try:
        fee_raw = (
            contract.get("fee")
            if contract and contract.get("fee")
            else shared_val("monthly_fee", "0")
        )
        fee = int(Decimal(str(fee_raw or "0")))
        fee_provisional = False
        work_start_str = ""
        if contract:
            work_start_str = contract.get("work_start") or contract.get("start_date") or ""
        if (
            contract
            and (not contract.get("fee"))
            and work_start_str
            and dayok(work_start_str)
        ):
            first_day = datetime.date.fromisoformat(work_start_str)
            if first_day.year == year and first_day.month == month and (
                contract.get("work_start") or first_day.day > 1
            ):
                all_days = [
                    datetime.date(year, month, i)
                    for i in range(1, calendar.monthrange(year, month)[1] + 1)
                ]
                official = national_holidays(year)
                office_holidays = get_contract_holidays(contract)
                business = [
                    d
                    for d in all_days
                    if contract_is_workday(contract, d, official, office_holidays)
                ]
                if business:
                    fee = int(
                        (
                            Decimal(fee)
                            * Decimal(sum((d >= first_day for d in business)))
                            / Decimal(len(business))
                        ).to_integral_value(rounding=ROUND_DOWN)
                    )
                    fee_provisional = True

        low = Decimal(str(lower_raw))
        high = Decimal(str(upper_raw))
        if contract:
            if contract.get("deduct_rate") not in (None, ""):
                deduct = Decimal(str(contract["deduct_rate"]))
            else:
                deduct = (
                    (Decimal(fee) / low / Decimal(10)).to_integral_value(
                        rounding=ROUND_DOWN
                    )
                    * 10
                    if low > 0
                    else Decimal("0")
                )
            if contract.get("extra_rate") not in (None, ""):
                extra = Decimal(str(contract["extra_rate"]))
            else:
                extra = (
                    (Decimal(fee) / high / Decimal(10)).to_integral_value(
                        rounding=ROUND_DOWN
                    )
                    * 10
                    if high > 0
                    else Decimal("0")
                )
            tax_raw = (
                contract["tax"]
                if contract.get("tax") not in (None, "")
                else shared_val("tax", "10")
            )
            tax_rate = Decimal(str(tax_raw))
        else:
            deduct = Decimal("0")
            extra = Decimal("0")
            tax_rate = Decimal(str(shared_val("tax", "10")))

        hours = Decimal(sums[2]["total"]) / Decimal(60)
        difference = (
            hours - high
            if hours > high
            else low - hours if hours < low else Decimal("0")
        )
        adjustment = (
            int(
                (
                    difference * (extra if hours > high else deduct) / Decimal(10)
                ).to_integral_value(rounding=ROUND_DOWN)
            )
            * 10
        )
        net = (
            fee + adjustment
            if hours > high
            else fee - adjustment if hours < low else fee
        )
        vat = int(
            (Decimal(net) * tax_rate / Decimal(100)).to_integral_value(
                rounding=ROUND_DOWN
            )
        )
        total_invoice = net + vat
        invoice_valid = (
            net >= 0
            and fee >= 0
            and low >= 0
            and high >= low
            and tax_rate >= 0
            and deduct >= 0
            and extra >= 0
        )
    except (ValueError, ArithmeticError, OverflowError):
        invoice_valid = False

    if not invoice_valid:
        return '<section class="invoice-sheet"><h1>請求書の設定値を確認してください</h1></section>'

    due_day = calculate_due_date(period_end, contract)
    due = format_due_date(due_day)
    money = lambda n: "{:,.0f}".format(n)
    customer_name = (
        (contract.get("customer") if contract and contract.get("customer") else "")
        or shared_val("customer", "")
        or DEFAULT_CUSTOMER_NAME
    )
    sender_name = (shared_val("company", "") or "").strip() or DEFAULT_SENDER_NAME
    sender_address = (shared_val("sender_address", "") or "").strip()
    sender_block = (
        (_multiline_esc(sender_address) + "<br>" if sender_address else "")
        + esc(sender_name)
    )
    invoice_note = (shared_val("invoice_note", "") or "").strip()
    bank_account = (shared_val("bank_account", "") or "").strip()
    if bank_account:
        bank_html = (
            esc(bank_account)
            if bank_account.startswith("お振込先")
            else "お振込先：" + esc(bank_account)
        )
    else:
        bank_html = ""
    issue = "%04d年%02d月%02d日" % (period_end.year, period_end.month, period_end.day)
    number = esc(str(invoice_number_for_month(year, month)))
    item = "超過" if hours > high else "控除" if hours < low else ""
    item_rate = extra if hours > high else deduct
    line = (
        "<tr><td>"
        + item
        + '</td><td>時間</td><td class="num">'
        + ("%.2f" % difference if item else "")
        + '</td><td class="num">'
        + (money(item_rate) if item else "")
        + '</td><td class="num">'
        + (("-" if hours < low else "") + money(adjustment) if item else "")
        + "</td></tr>"
    )
    tax_rate_str = (
        str(tax_rate.normalize())
        if tax_rate == tax_rate.to_integral_value()
        else str(tax_rate)
    )
    if tax_rate == 0:
        tax_rate_str = "0"
    return (
        '<section class="invoice-sheet"><div class="invoice-meta">請求番号 '
        + number
        + "\u3000請求日 "
        + issue
        + '</div><h1>御 請 求 書</h1><div class="invoice-top"><div style="flex:1"><div class="invoice-recipient">'
        + esc(customer_name)
        + '\u3000御中</div><p>下記の通りご請求申し上げます。</p><p>ご請求金額</p><div class="invoice-amount">￥'
        + money(total_invoice)
        + '－</div><p>お支払期限</p><div class="invoice-due">'
        + due
        + '</div></div><div class="invoice-sender">'
        + sender_block
        + '<div class="invoice-stamps"><span></span><span></span><span></span></div></div></div><table>'
        "<thead><tr><th>内容</th><th>単位</th><th>数量</th><th>単価</th><th>金額</th></tr></thead><tbody><tr><td>"
        + str(year)
        + "年"
        + str(month)
        + '月分</td><td>人月</td><td class="num">1.00</td><td class="num">'
        + money(fee)
        + '</td><td class="num">'
        + money(fee)
        + "</td></tr>"
        + line
        + '</tbody></table><div class="invoice-item-note">※'
        + str(year)
        + "年"
        + str(month)
        + "月 実績 "
        + "%.2f" % hours
        + 'h（詳細は別紙勤務表参照）</div><div class="invoice-rate">'
        + (
            "※月額は稼働日割による暫定額。確定額を契約設定に登録してください。<br>"
            if fee_provisional
            else ""
        )
        + "■控除単価："
        + money(deduct)
        + "円\u3000■超過単価："
        + money(extra)
        + '円</div><div class="invoice-totals"><div><span>'
        + esc(tax_rate_str)
        + "%対象計・小計（税抜き）</span><b>"
        + money(net)
        + "</b></div><div><span>消費税（"
        + esc(tax_rate_str)
        + "%）</span><b>"
        + money(vat)
        + '</b></div><div class="grand"><span>合計金額</span><b>￥'
        + money(total_invoice)
        + '</b></div></div><div class="invoice-note">備考'
        + ("<br>" + _multiline_esc(invoice_note) if invoice_note else "")
        + '</div><div class="invoice-bank">'
        + bank_html
        + "</div></section>"
    )
