"""Main HTTP request dispatcher, initial sysadmin setup, and 3-role login flow."""

import datetime
from timecard.actions import (
    handle_bulk_regular,
    handle_clear_day,
    handle_contract_delete,
    handle_contract_save,
    handle_export,
    handle_import,
    handle_punch,
    handle_sample_reset,
    handle_save,
    handle_user_create,
    handle_user_delete,
    handle_user_update,
)
from timecard.attendance import dayok
from timecard.auth import (
    ROLE_SYSADMIN,
    authenticate,
    create_user,
    current_session,
    has_any_sysadmin,
    revoke_session,
)
from timecard.contracts import active_contract, reporting_period
from timecard.http_utils import esc, html_response, redirect
from timecard.layout import layout
from timecard.report import handle_search, render_report
from timecard.sample_data import seed_sample_data
from timecard.settings_page import (
    handle_calendar_data,
    handle_contract_fiscal_save,
    handle_event_save,
    handle_holiday_clear,
    handle_holiday_copy,
    handle_holiday_save,
    handle_settings,
)
from timecard.version import APP_COPYRIGHT, APP_NAME


def _session_cookie(token, max_age=604800):
    return (
        "Set-Cookie",
        "tc_session=" + token + "; Path=/; Max-Age=" + str(max_age) + "; HttpOnly; SameSite=Lax",
    )


def _render_setup_page(error_msg=""):
    err_html = '<p class="notice">' + esc(error_msg) + "</p>" if error_msg else ""
    body = (
        '<div class="card auth-card">'
        "<h1>初期セットアップ：システム管理者の作成</h1>"
        '<p class="muted small">'
        + esc(APP_NAME)
        + " の初回起動です。まずシステム管理者アカウントを作成してください。<br>"
        "作成後、動作確認用の架空サンプル契約・サンプル実績が自動投入されます（設定画面のリセットボタンからいつでも削除できます）。</p>"
        + err_html
        + '<form method="post" action="/?a=setup" class="auth-form">'
        '<label class="field"><span>システム管理者 ログインID<em>*</em></span>'
        '<input type="text" name="login" required maxlength="60" placeholder="例：sysadmin" autocomplete="username"></label>'
        '<label class="field"><span>表示名</span>'
        '<input type="text" name="display_name" maxlength="60" placeholder="例：システム管理者"></label>'
        '<label class="field"><span>パスワード<em>*</em><small class="field-hint">6文字以上</small></span>'
        '<input type="password" name="password" required minlength="6" autocomplete="new-password"></label>'
        '<label class="field"><span>パスワード（確認）<em>*</em></span>'
        '<input type="password" name="password_confirm" required minlength="6" autocomplete="new-password"></label>'
        '<div class="form-actions"><button type="submit">システム管理者を作成して開始</button></div>'
        "</form>"
        '<p class="muted small" style="margin-top:14px">' + esc(APP_COPYRIGHT) + "</p>"
        "</div>"
    )
    return html_response(layout("初期セットアップ", body))


def _render_login_page(error_msg=""):
    err_html = '<p class="notice">' + esc(error_msg) + "</p>" if error_msg else ""
    body = (
        '<div class="card auth-card">'
        "<h1>ログイン</h1>"
        + err_html
        + '<form method="post" action="/?a=login" class="auth-form">'
        '<label class="field"><span>ログインID</span>'
        '<input type="text" name="login" required autocomplete="username"></label>'
        '<label class="field"><span>パスワード</span>'
        '<input type="password" name="password" required autocomplete="current-password"></label>'
        '<label class="login-admin-check">'
        '<input type="checkbox" name="as_admin" value="1">'
        '<span>管理者としてログイン<small class="muted">（管理者昇格可能なユーザーのみ）</small></span>'
        "</label>"
        '<div class="form-actions"><button type="submit">ログイン</button></div>'
        "</form>"
        '<p class="muted small" style="margin-top:12px">'
        "※ システム管理者IDでログインするとシステム管理者権限になります。<br>"
        "※ 通常はユーザ権限でログインし、管理者へ切り替える場合はログアウト後に「管理者としてログイン」にチェックを入れて入り直してください。</p>"
        "</div>"
    )
    return html_response(layout("ログイン", body))


def handle_request(method, query_params, form_params, cookie_header=""):
    """Handle one HTTP request and return a Response object."""
    q = query_params or {}
    p = form_params or {}
    a = q.get("a", "")

    # 1. Initial sysadmin setup
    if not has_any_sysadmin():
        if a == "setup" and method == "POST":
            pw = p.get("password", "")
            pw2 = p.get("password_confirm", "")
            if pw != pw2:
                return _render_setup_page("パスワードと確認用パスワードが一致しません。")
            try:
                uid = create_user(
                    login=p.get("login", ""),
                    password=pw,
                    display_name=p.get("display_name", "") or "システム管理者",
                    role=ROLE_SYSADMIN,
                    can_admin=False,
                    is_sample=False,
                )
                seed_sample_data(uid)
                token, _, _ = authenticate(p.get("login", ""), pw, as_admin=False)
                return redirect("/", headers=[_session_cookie(token)])
            except ValueError as e:
                return _render_setup_page(str(e))
        return _render_setup_page()

    # 2. Login / Logout
    if a == "logout":
        revoke_session(cookie_header)
        return redirect("/", headers=[_session_cookie("", max_age=0)])

    if a == "login" and method == "POST":
        try:
            token, _, _ = authenticate(
                login=p.get("login", ""),
                password=p.get("password", ""),
                as_admin=(p.get("as_admin") == "1"),
            )
            return redirect("/", headers=[_session_cookie(token)])
        except ValueError as e:
            return _render_login_page(str(e))

    # 3. Require valid session
    sess = current_session(cookie_header)
    if not sess:
        return _render_login_page()

    # 4. Authenticated routes
    if a == "search":
        return handle_search(sess, q.get("q", ""))

    today = datetime.date.today()
    day = q.get("day", today.isoformat())
    day = day if dayok(day) else today.isoformat()
    selected = datetime.date.fromisoformat(day)
    (year, month) = (selected.year, selected.month)

    if a == "punch" and method == "POST":
        return handle_punch(sess, p, today)
    if a == "save" and method == "POST":
        return handle_save(sess, p)
    if a == "contract_save" and method == "POST":
        return handle_contract_save(sess, p)
    if a == "contract_delete" and method == "POST":
        return handle_contract_delete(sess, p)
    if a == "user_create" and method == "POST":
        return handle_user_create(sess, p)
    if a == "user_update" and method == "POST":
        return handle_user_update(sess, p)
    if a == "user_delete" and method == "POST":
        return handle_user_delete(sess, p)
    if a == "sample_reset" and method == "POST":
        return handle_sample_reset(sess)
    if a == "settings":
        return handle_settings(sess, p, method, q)
    if a == "calendar_data":
        return handle_calendar_data(sess, q)
    if a == "holiday_save" and method == "POST":
        return handle_holiday_save(sess, p)
    if a == "event_save" and method == "POST":
        return handle_event_save(sess, p)
    if a == "holiday_clear" and method == "POST":
        return handle_holiday_clear(sess, p)
    if a == "holiday_copy" and method == "POST":
        return handle_holiday_copy(sess, p)
    if a == "contract_fiscal_save" and method == "POST":
        return handle_contract_fiscal_save(sess, p)

    contract = active_contract(year, month)
    closing = contract.get("closing", "末") if contract else "末"
    if closing not in ("5", "10", "15", "20", "25", "末"):
        closing = "末"
    (period_start, period_end) = reporting_period(year, month, closing)

    if a == "bulk_regular" and method == "POST":
        return handle_bulk_regular(sess, p)
    if a == "clear_day" and method == "POST":
        return handle_clear_day(sess, p)
    if a == "export":
        return handle_export(sess, year, month)
    if a == "import" and method == "POST":
        return handle_import(sess, p)

    auto_open = (not q) or (q.get("open") == "1")
    return render_report(
        sess,
        day,
        selected,
        year,
        month,
        contract,
        period_start,
        period_end,
        auto_open=auto_open,
    )
