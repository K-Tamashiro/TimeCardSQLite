"""Comprehensive tests for Personal TimeCard for Free Lance (SQLite3 standalone edition)."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timecard import application, attendance, contracts, db, invoice, sample_data
from timecard.server import create_server
from timecard.version import APP_COPYRIGHT, APP_NAME


class StandaloneTimeCardTests(unittest.TestCase):
    def setUp(self):
        db.configure(":memory:")

    def tearDown(self):
        db.close_all()

    def _req(self, method, query="", form=None, cookie=""):
        q = {
            k: v[-1]
            for k, v in urllib.parse.parse_qs(query, keep_blank_values=True).items()
        }
        return application.handle_request(method, q, form or {}, cookie)

    def _cookie_from(self, resp):
        for k, v in resp.headers:
            if k.lower() == "set-cookie":
                return v.split(";", 1)[0]
        return ""

    def _setup_sysadmin(self, login="sysadmin", pw="password123"):
        resp = self._req(
            "POST",
            "a=setup",
            {
                "login": login,
                "display_name": "システム管理者",
                "password": pw,
                "password_confirm": pw,
            },
        )
        self.assertEqual(303, resp.status)
        cookie = self._cookie_from(resp)
        self.assertTrue(cookie.startswith("tc_session="))
        return cookie

    def test_initial_setup_seeds_clean_fictional_sample_data_and_branding(self):
        # Before setup, GET shows sysadmin creation screen
        r0 = self._req("GET")
        self.assertEqual(200, r0.status)
        html0 = r0.body.decode("utf-8")
        self.assertIn("システム管理者の作成", html0)
        self.assertIn(APP_NAME, html0)
        self.assertIn(APP_COPYRIGHT, html0)

        cookie = self._setup_sysadmin()
        r_report = self._req("GET", "", cookie=cookie)
        html = r_report.body.decode("utf-8")
        self.assertIn("サンプル事業所 実績表", html)
        self.assertIn("@page{size:A4 portrait;margin:11mm 6mm 6mm}", html)
        self.assertIn("CSVインポート/エクスポート", html)
        self.assertIn("システム管理者", html)
        self.assertIn(APP_COPYRIGHT, html)
        # Ensure fictional sample data is seeded into shared settings
        from timecard.settings_store import shared_val

        self.assertEqual("山田 太郎", shared_val("company", ""))
        self.assertEqual("株式会社サンプルソリューションズ", shared_val("customer", ""))

        # Sample data counts are positive
        summary = sample_data.sample_data_summary()
        self.assertGreater(summary["work"], 0)
        self.assertGreater(summary["events"], 0)
        self.assertGreater(summary["settings"], 0)

    def test_three_role_auth_and_strict_permission_matrix(self):
        sa_cookie = self._setup_sysadmin()

        # Create normal user (no admin) and admin-capable user
        r1 = self._req(
            "POST",
            "a=user_create",
            {"login": "user_normal", "display_name": "一般 太郎", "password": "userpass1"},
            cookie=sa_cookie,
        )
        self.assertEqual(303, r1.status)
        r2 = self._req(
            "POST",
            "a=user_create",
            {
                "login": "user_adminable",
                "display_name": "昇格 花子",
                "password": "adminpass1",
                "can_admin": "1",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(303, r2.status)

        # Normal user trying to login with as_admin=1 must be rejected
        r_deny_login = self._req(
            "POST",
            "a=login",
            {"login": "user_normal", "password": "userpass1", "as_admin": "1"},
        )
        self.assertEqual(200, r_deny_login.status)
        self.assertIn("管理者としてログインする権限がありません", r_deny_login.body.decode("utf-8"))

        # Normal user logs in as 'user'
        r_user_login = self._req(
            "POST",
            "a=login",
            {"login": "user_normal", "password": "userpass1"},
        )
        self.assertEqual(303, r_user_login.status)
        user_cookie = self._cookie_from(r_user_login)

        # Admin-capable user logs in without checkbox -> 'user' role
        r_adm_as_user = self._req(
            "POST",
            "a=login",
            {"login": "user_adminable", "password": "adminpass1"},
        )
        adm_user_cookie = self._cookie_from(r_adm_as_user)
        self.assertIn("role-badge is-user", self._req("GET", "", cookie=adm_user_cookie).body.decode("utf-8"))

        # Logout and re-login with checkbox -> 'admin' role
        self._req("GET", "a=logout", cookie=adm_user_cookie)
        r_adm_login = self._req(
            "POST",
            "a=login",
            {"login": "user_adminable", "password": "adminpass1", "as_admin": "1"},
        )
        self.assertEqual(303, r_adm_login.status)
        admin_cookie = self._cookie_from(r_adm_login)
        admin_home = self._req("GET", "", cookie=admin_cookie).body.decode("utf-8")
        self.assertIn("role-badge is-admin", admin_home)

        # --- Check report/invoice/CSV visibility & endpoints ---
        user_home = self._req("GET", "", cookie=user_cookie).body.decode("utf-8")
        self.assertIn('id="print-invoice"', user_home)  # user CAN issue invoice
        self.assertNotIn("CSVインポート/エクスポート", user_home)
        self.assertNotIn("CSVインポート/エクスポート", admin_home)
        self.assertEqual(403, self._req("GET", "a=export", cookie=user_cookie).status)
        self.assertEqual(403, self._req("GET", "a=export", cookie=admin_cookie).status)
        self.assertEqual(403, self._req("POST", "a=import", {"csv": ""}, cookie=admin_cookie).status)
        self.assertEqual(200, self._req("GET", "a=export", cookie=sa_cookie).status)

        # --- Check settings screen visibility per role ---
        user_settings = self._req("GET", "a=settings", cookie=user_cookie).body.decode("utf-8")
        self.assertNotIn("基本設定（自社・請求情報）", user_settings)
        self.assertNotIn("契約履歴", user_settings)
        self.assertNotIn('id="holiday-form"', user_settings)
        self.assertIn('id="event-form"', user_settings)
        self.assertNotIn("ユーザー管理", user_settings)
        self.assertNotIn("sample-reset-btn", user_settings)

        admin_settings = self._req("GET", "a=settings", cookie=admin_cookie).body.decode("utf-8")
        self.assertNotIn("基本設定（自社・請求情報）", admin_settings)
        self.assertNotIn("契約履歴", admin_settings)
        self.assertIn('id="holiday-form"', admin_settings)
        self.assertIn('class="holiday-mode-hint', admin_settings)
        self.assertIn("syncHolidayChipHighlight", admin_settings)
        self.assertIn("handleCalendarDateClick", admin_settings)
        self.assertIn(".preset-chip.is-active", admin_settings)
        self.assertIn('id="event-form"', admin_settings)
        self.assertNotIn("パブリック予定（全ユーザーに表示）", admin_settings)
        self.assertNotIn("ユーザー管理", admin_settings)
        self.assertNotIn("sample-reset-btn", admin_settings)

        # --- Check server-side 403 enforcement ---
        self.assertEqual(403, self._req("POST", "a=settings", {"company": "Hack"}, cookie=admin_cookie).status)
        self.assertEqual(403, self._req("POST", "a=contract_save", {"contract_name": "X"}, cookie=admin_cookie).status)
        self.assertEqual(403, self._req("POST", "a=sample_reset", {}, cookie=admin_cookie).status)
        self.assertEqual(403, self._req("POST", "a=user_create", {"login": "x", "password": "password"}, cookie=admin_cookie).status)
        # Admin CAN save holiday; User CANNOT
        self.assertEqual(
            200,
            self._req(
                "POST",
                "a=holiday_save",
                {"contract_id": sample_data.SAMPLE_CONTRACT_ID, "holiday_day": "2026-09-22", "holiday_name": "特別休"},
                cookie=admin_cookie,
            ).status,
        )
        self.assertEqual(
            403,
            self._req(
                "POST",
                "a=holiday_save",
                {"contract_id": sample_data.SAMPLE_CONTRACT_ID, "holiday_day": "2026-09-22", "holiday_name": "不可"},
                cookie=user_cookie,
            ).status,
        )

    def test_event_scoping_public_sysadmin_only_and_private_per_user(self):
        sa_cookie = self._setup_sysadmin()
        self._req(
            "POST",
            "a=user_create",
            {"login": "u1", "password": "password1", "can_admin": "1"},
            cookie=sa_cookie,
        )
        self._req(
            "POST",
            "a=user_create",
            {"login": "u2", "password": "password2"},
            cookie=sa_cookie,
        )
        u1_admin = self._cookie_from(
            self._req("POST", "a=login", {"login": "u1", "password": "password1", "as_admin": "1"})
        )
        u2_user = self._cookie_from(
            self._req("POST", "a=login", {"login": "u2", "password": "password2"})
        )

        # Sysadmin registers public event
        res_pub = self._req(
            "POST",
            "a=event_save",
            {"event_day": "2026-11-10", "event_text": "全社ミーティング", "event_scope": "public"},
            cookie=sa_cookie,
        )
        self.assertEqual(200, res_pub.status)

        # Admin and User CANNOT register public event
        self.assertEqual(
            403,
            self._req(
                "POST",
                "a=event_save",
                {"event_day": "2026-11-11", "event_text": "不正公開", "event_scope": "public"},
                cookie=u1_admin,
            ).status,
        )
        self.assertEqual(
            403,
            self._req(
                "POST",
                "a=event_save",
                {"event_day": "2026-11-11", "event_text": "不正公開", "event_scope": "public"},
                cookie=u2_user,
            ).status,
        )

        # u1 registers private event -> visible to u1, NOT visible to u2
        res_priv = self._req(
            "POST",
            "a=event_save",
            {"event_day": "2026-11-12", "event_text": "u1の個人予定", "event_scope": "private"},
            cookie=u1_admin,
        )
        self.assertEqual(200, res_priv.status)

        u1_html = self._req("GET", "day=2026-11-10", cookie=u1_admin).body.decode("utf-8")
        u2_html = self._req("GET", "day=2026-11-10", cookie=u2_user).body.decode("utf-8")
        self.assertIn("全社ミーティング", u1_html)
        self.assertIn("全社ミーティング", u2_html)
        self.assertIn("u1の個人予定", u1_html)
        self.assertNotIn("u1の個人予定", u2_html)

    def test_sample_reset_deletes_only_sample_data_and_preserves_users_and_manual_data(self):
        sa_cookie = self._setup_sysadmin()
        # Add a manual user and a manual attendance entry
        self._req(
            "POST",
            "a=user_create",
            {"login": "real_user", "display_name": "実運用 ユーザー", "password": "realpassword", "can_admin": "1"},
            cookie=sa_cookie,
        )
        self._req(
            "POST",
            "a=save",
            {"day": "2026-11-25", "clock_in": "600", "clock_out": "1730", "early_work": "1", "report": "手動入力データ"},
            cookie=sa_cookie,
        )

        # Reset sample data
        res_reset = self._req("POST", "a=sample_reset", {}, cookie=sa_cookie)
        self.assertEqual(303, res_reset.status)

        # Sample counts must be 0
        self.assertEqual(0, sample_data.sample_data_summary()["total"])
        # Sample contract is removed
        self.assertEqual([], contracts.contracts())
        # All users (sysadmin, sample_user, real_user) and their roles are preserved
        logins = {u["login"]: (u["role"], u["can_admin"]) for u in db.con.execute("SELECT * FROM users").fetchall()}
        self.assertIn("sysadmin", logins)
        self.assertIn("sample_user", logins)
        self.assertEqual(("user", 1), logins["real_user"])
        # Manual work row is preserved
        manual = db.con.execute("SELECT report FROM work WHERE day='2026-11-25'").fetchone()
        self.assertEqual("手動入力データ", manual["report"])

        # Sysadmin can delete sample_user afterwards
        sample_uid = db.con.execute("SELECT id FROM users WHERE login='sample_user'").fetchone()["id"]
        res_del = self._req("POST", "a=user_delete", {"target_user_id": str(sample_uid)}, cookie=sa_cookie)
        self.assertEqual(303, res_del.status)
        self.assertIsNone(db.con.execute("SELECT id FROM users WHERE login='sample_user'").fetchone())

    def test_schedule_early_work_and_payment_due_date_in_standalone(self):
        sa_cookie = self._setup_sysadmin()
        # Reset sample first, then add custom contract
        self._req("POST", "a=sample_reset", {}, cookie=sa_cookie)
        self._req(
            "POST",
            "a=contract_save",
            {
                "contract_name": "カスタム契約",
                "contract_display_title": "カスタム現場",
                "contract_customer": "テスト商事株式会社",
                "contract_start_date": "2026-06-01",
                "contract_end_date": "",
                "contract_closing": "末",
                "contract_pay_month_offset": "1",
                "contract_pay_day": "末",
                "contract_pay_holiday_rule": "prev",
                "contract_tax": "10",
                "contract_fee": "600000",
                "contract_lower": "140",
                "contract_upper": "180",
                "schedule_submitted": "1",
                "contract_regular_start": "09:00",
                "contract_regular_end": "18:00",
                "contract_round_unit": "10",
                "contract_break1_start": "12:00",
                "contract_break1_end": "13:00",
                "contract_break2_start": "",
                "contract_break2_end": "",
                "workdays_submitted": "1",
                "workday_0": "1",
                "workday_1": "1",
                "workday_2": "1",
                "workday_3": "1",
                "workday_4": "1",
            },
            cookie=sa_cookie,
        )
        # Early work 07:00-18:20 (10-min unit, no break2) -> early 2:00 + after 0:20 = 2:20 OT, 8:00 reg, 10:20 total
        self._req(
            "POST",
            "a=save",
            {"day": "2026-11-20", "clock_in": "700", "clock_out": "1820", "early_work": "1"},
            cookie=sa_cookie,
        )
        html = self._req("GET", "day=2026-11-20", cookie=sa_cookie).body.decode("utf-8")
        self.assertIn("計算用時刻：07:00 ～ 18:20\u3000実績：10:20 / 10.33h（うち早出 2:00 / 2.00h）", html)
        self.assertIn('<span class="early-tag">早出 2:00</span>', html)
        # 2026-11 closing -> next month end 2026-12-31 (bank holiday) -> prev business day 2026-12-30 (Wed)
        self.assertIn('<div class="invoice-due">2026年12月30日（水）</div>', html)

    def test_half_subtotals_default_off_and_opt_in_on_screen_and_print(self):
        sa_cookie = self._setup_sysadmin()
        # Default (sample contract): half-month subtotals are OFF in both screen table and print footer
        html_off = self._req("GET", "", cookie=sa_cookie).body.decode("utf-8")
        self.assertNotIn("前半小計（前半15日）", html_off)
        self.assertNotIn("後半小計（16日～最終日）", html_off)
        self.assertIn("月間合計", html_off)

        # Enable show_half_subtotals on a contract
        c = contracts.contracts()[0]
        self._req(
            "POST",
            "a=contract_save",
            {
                "contract_id": c["id"],
                "contract_name": c["name"],
                "contract_display_title": c["display_title"],
                "contract_customer": c["customer"],
                "contract_start_date": c["start_date"],
                "contract_end_date": c["end_date"],
                "contract_closing": c["closing"],
                "contract_tax": c["tax"],
                "contract_fee": c["fee"],
                "contract_lower": c["lower"],
                "contract_upper": c["upper"],
                "workdays_submitted": "1",
                "schedule_submitted": "1",
                "workday_0": "1",
                "workday_1": "1",
                "workday_2": "1",
                "workday_3": "1",
                "workday_4": "1",
                "contract_show_half_subtotals": "1",
            },
            cookie=sa_cookie,
        )
        html_on = self._req("GET", "", cookie=sa_cookie).body.decode("utf-8")
        # Appears twice: once in screen table and once in print_footer
        self.assertEqual(2, html_on.count("前半小計（前半15日）"))
        self.assertEqual(2, html_on.count("後半小計（16日～最終日）"))

        # Turn back off
        self._req(
            "POST",
            "a=contract_save",
            {
                "contract_id": c["id"],
                "contract_name": c["name"],
                "contract_display_title": c["display_title"],
                "contract_customer": c["customer"],
                "contract_start_date": c["start_date"],
                "contract_end_date": c["end_date"],
                "contract_closing": c["closing"],
                "contract_tax": c["tax"],
                "contract_fee": c["fee"],
                "contract_lower": c["lower"],
                "contract_upper": c["upper"],
                "workdays_submitted": "1",
                "schedule_submitted": "1",
                "workday_0": "1",
                "workday_1": "1",
                "workday_2": "1",
                "workday_3": "1",
                "workday_4": "1",
            },
            cookie=sa_cookie,
        )
        html_off_again = self._req("GET", "", cookie=sa_cookie).body.decode("utf-8")
        self.assertNotIn("前半小計（前半15日）", html_off_again)
        self.assertNotIn("後半小計（16日～最終日）", html_off_again)

    def test_status_endpoint_and_revoke_all_sessions(self):
        from timecard.auth import revoke_all_sessions

        application.reset_shutting_down()
        cookie = self._setup_sysadmin()

        r1 = self._req("GET", "a=status", cookie=cookie)
        self.assertEqual(200, r1.status)
        self.assertEqual({"running": True, "logged_in": True}, json.loads(r1.body.decode("utf-8")))

        # Revoking all sessions (as performed on dialog close/startup) logs out active sessions
        revoke_all_sessions()
        r2 = self._req("GET", "a=status", cookie=cookie)
        self.assertEqual({"running": True, "logged_in": False}, json.loads(r2.body.decode("utf-8")))

        r_home = self._req("GET", "", cookie=cookie)
        login_html = r_home.body.decode("utf-8")
        self.assertIn("ログイン", login_html)
        self.assertIn('images/app_title.png', login_html)
        self.assertIn('class="header-title-logo"', login_html)
        self.assertIn('class="auth-card-head"', login_html)
        self.assertIn('class="auth-title-logo"', login_html)

        # Shutting down flag is reflected in status endpoint
        application.mark_shutting_down()
        try:
            r3 = self._req("GET", "a=status", cookie=cookie)
            self.assertEqual({"running": False, "logged_in": False}, json.loads(r3.body.decode("utf-8")))
        finally:
            application.reset_shutting_down()

    def test_fixed_default_port_and_fallback_when_busy(self):
        import run_app

        blocker = create_server("127.0.0.1", 0)
        busy_port = blocker.server_address[1]
        try:
            srv = run_app._bind_server("127.0.0.1", busy_port, allow_fallback=True)
            try:
                self.assertNotEqual(busy_port, srv.server_address[1])
                self.assertGreater(srv.server_address[1], 0)
            finally:
                srv.server_close()
        finally:
            blocker.server_close()

        srv2 = run_app._bind_server("127.0.0.1", busy_port, allow_fallback=True)
        try:
            self.assertEqual(busy_port, srv2.server_address[1])
        finally:
            srv2.server_close()

    def test_builtin_http_server_and_file_sqlite_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db.configure(Path(tmp) / "timecard.db")
            srv = create_server("127.0.0.1", 0)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                base = f"http://127.0.0.1:{port}"
                with urllib.request.urlopen(base + "/") as resp:
                    self.assertEqual(200, resp.status)
                    self.assertIn("初期セットアップ", resp.read().decode("utf-8"))
                with urllib.request.urlopen(base + "/favicon.ico") as resp:
                    self.assertEqual(200, resp.status)
                    self.assertGreater(len(resp.read()), 0)
            finally:
                srv.shutdown()
                srv.server_close()
                db.close_all()

    def test_entry_dialog_layout_and_two_line_clamp(self):
        sa_cookie = self._setup_sysadmin()
        html = self._req("GET", "", cookie=sa_cookie).body.decode("utf-8")
        entry_html = html.split('<dialog id="entry-dialog"', 1)[1].split("</dialog>", 1)[0]
        entry_top_html = entry_html.split('<div class="entry-dialog-top">', 1)[1].split(
            '<div class="flex day-navigation">', 1
        )[0]
        self.assertIn('class="entry-regular-slot"', entry_top_html)
        self.assertIn('images/fixed-time.png" alt="定時刻印"', entry_top_html)
        self.assertLess(
            entry_top_html.index('id="clock"'),
            entry_top_html.index('id="entry-status-boxes"'),
        )
        self.assertLess(
            entry_top_html.index('id="entry-status-boxes"'),
            entry_top_html.index('id="regular-time"'),
        )
        self.assertLess(
            entry_top_html.index('id="regular-time"'),
            entry_top_html.index('id="entry-close"'),
        )
        self.assertIn('class="entry-field entry-field-break"', entry_html)
        self.assertIn('class="col-report"><div class="cell-clamp">', html)
        self.assertIn('class="col-note"><div class="cell-clamp">', html)
        self.assertIn("-webkit-line-clamp:2", html)
        self.assertIn(".print-sheet .day-cell a {text-decoration:none}", html)
        self.assertIn(".print-sheet>.scroll>table tbody tr.day-row .day-cell a {color:#f1f5f9!important}", html)
        self.assertIn(".print-sheet>.scroll>table tbody tr.day-row.saturday .day-cell a {color:#a6d7ff!important}", html)
        self.assertIn(".print-sheet>.scroll>table tbody tr.day-row.sunday .day-cell a,.print-sheet>.scroll>table tbody tr.day-row.holiday .day-cell a {color:#ffb7c0!important}", html)
        self.assertIn(".print-sheet tr.day-row.saturday .day-cell a {color:#1759ad!important}", html)
        self.assertIn(".print-sheet tr.day-row.sunday .day-cell a,.print-sheet tr.day-row.holiday .day-cell a {color:#b4232e!important}", html)
        self.assertIn(".entry-fields #entry-break::placeholder {font-size:26px}", html)
        self.assertIn(".entry-fields #entry-break::placeholder {font-size:clamp(17px,5.2vw,22px)}", html)

    def test_closing_day_badges_and_rollbacks(self):
        import datetime
        from timecard.holidays import national_holidays

        # 1) Direct closing_workday rollback checks
        c_end = contracts.normalize_contract(
            {"name": "EndClose", "start_date": "2026-01-01", "closing": "末"}
        )
        p_start, p_end = contracts.reporting_period(2026, 10, "末")
        self.assertEqual(
            datetime.date(2026, 10, 30),
            contracts.closing_workday(p_start, p_end, c_end, national_holidays(2026), {}),
        )
        p_start, p_end = contracts.reporting_period(2026, 5, "末")
        self.assertEqual(
            datetime.date(2026, 5, 29),
            contracts.closing_workday(p_start, p_end, c_end, national_holidays(2026), {}),
        )
        c_15 = contracts.normalize_contract(
            {"name": "Close15", "start_date": "2026-01-01", "closing": "15"}
        )
        p_start, p_end = contracts.reporting_period(2026, 11, "15")
        self.assertEqual(
            datetime.date(2026, 11, 13),
            contracts.closing_workday(p_start, p_end, c_15, national_holidays(2026), {}),
        )
        c_20 = contracts.normalize_contract(
            {"name": "Close20", "start_date": "2026-01-01", "closing": "20"}
        )
        p_start, p_end = contracts.reporting_period(2026, 7, "20")
        self.assertEqual(
            datetime.date(2026, 7, 17),
            contracts.closing_workday(p_start, p_end, c_20, national_holidays(2026), {}),
        )
        p_start, p_end = contracts.reporting_period(2026, 11, "末")
        self.assertEqual(
            datetime.date(2026, 11, 27),
            contracts.closing_workday(
                p_start, p_end, c_end, national_holidays(2026), {"2026-11-30": "振替休日"}
            ),
        )

        # 2) Full HTML render check: 15th close with event on same rolled-back closing day (2026-11-13)
        sa_cookie = self._setup_sysadmin()
        self._req("POST", "a=sample_reset", {}, cookie=sa_cookie)
        contracts.save_contracts(
            [
                {
                    "name": "Close15",
                    "start_date": "2026-01-01",
                    "lower": "120",
                    "upper": "160",
                    "closing": "15",
                }
            ]
        )
        self._req(
            "POST",
            "a=event_save",
            {"event_day": "2026-11-13", "event_text": "月次報告会", "event_scope": "private"},
            cookie=sa_cookie,
        )

        html = self._req("GET", "day=2026-11-13", cookie=sa_cookie).body.decode("utf-8")
        row_13 = html.split('data-day="2026-11-13"', 1)[1].split("</tr>", 1)[0]
        row_15 = html.split('data-day="2026-11-15"', 1)[1].split("</tr>", 1)[0]
        self.assertIn('class="day-badges"', row_13)
        self.assertIn('class="event-dot"', row_13)
        self.assertIn('class="closing-dot"', row_13)
        self.assertLess(
            row_13.index('class="event-dot"'), row_13.index('class="closing-dot"')
        )
        self.assertNotIn('class="closing-dot"', row_15)
        self.assertIn('<div class="card selected-day is-closing" id="entry-card">', html)
        self.assertIn('<div id="entry-status-boxes" class="entry-status-boxes">', html)
        self.assertIn(
            '<div id="entry-closing-box" class="entry-closing-box" title="契約締日（最終稼働日）"><span class="entry-closing-badge">締日</span></div>',
            html,
        )
        self.assertIn(
            "#entry-dialog .selected-day.is-closing {border:3px solid #ef4444;",
            html,
        )
        html_12 = self._req("GET", "day=2026-11-12", cookie=sa_cookie).body.decode("utf-8")
        self.assertIn('<div class="card selected-day" id="entry-card">', html_12)
        self.assertIn(
            '<div id="entry-closing-box" class="entry-closing-box" hidden',
            html_12,
        )
        self.assertIn(
            ".closing-dot,.day-badges,#entry-closing-box,#entry-status-boxes {display:none!important}",
            html,
        )

    def test_contract_subtotal_layout_split_and_bottom_screen_only(self):
        sa_cookie = self._setup_sysadmin()
        self._req("POST", "a=sample_reset", {}, cookie=sa_cookie)

        # Validation rejects invalid subtotal_layout
        res_bad = self._req(
            "POST",
            "a=contract_save",
            {
                "contract_name": "BadLayout",
                "contract_start_date": "2026-01-01",
                "contract_lower": "120",
                "contract_upper": "160",
                "contract_show_half_subtotals": "1",
                "contract_subtotal_layout": "top",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(400, res_bad.status)

        # Contract 1 (June): half subtotals ON, split layout (inline under 15th)
        res_split = self._req(
            "POST",
            "a=contract_save",
            {
                "contract_name": "SplitSub",
                "contract_start_date": "2026-06-01",
                "contract_end_date": "2026-06-30",
                "contract_closing": "末",
                "contract_lower": "120",
                "contract_upper": "160",
                "schedule_submitted": "1",
                "contract_show_half_subtotals": "1",
                "contract_subtotal_layout": "split",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(303, res_split.status)

        # Contract 2 (July): half subtotals ON, bottom 3-row set layout
        res_bottom = self._req(
            "POST",
            "a=contract_save",
            {
                "contract_name": "BottomSub",
                "contract_start_date": "2026-07-01",
                "contract_end_date": "2026-07-31",
                "contract_closing": "末",
                "contract_lower": "120",
                "contract_upper": "160",
                "schedule_submitted": "1",
                "contract_show_half_subtotals": "1",
                "contract_subtotal_layout": "bottom",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(303, res_bottom.status)

        # Contract 3 (August): half subtotals OFF
        res_off = self._req(
            "POST",
            "a=contract_save",
            {
                "contract_name": "NoSub",
                "contract_start_date": "2026-08-01",
                "contract_end_date": "2026-08-31",
                "contract_closing": "末",
                "contract_lower": "120",
                "contract_upper": "160",
                "schedule_submitted": "1",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(303, res_off.status)

        def _split_screen_and_print(html):
            screen_part = html.split('<div class="scroll"><table>', 1)[1].split(
                '</tbody></table></div><div class="print-footer">', 1
            )[0]
            print_part = html.split('<div class="print-footer">', 1)[1].split(
                "</tbody></table></div>", 1
            )[0]
            return screen_part, print_part

        # June (split): 前半小計 appears between 06-15 and 06-16; print footer has 3-row set
        html_jun = self._req("GET", "day=2026-06-10", cookie=sa_cookie).body.decode("utf-8")
        jun_screen, jun_print = _split_screen_and_print(html_jun)
        self.assertLess(jun_screen.index('data-day="2026-06-15"'), jun_screen.index("前半小計（前半15日）"))
        self.assertLess(jun_screen.index("前半小計（前半15日）"), jun_screen.index('data-day="2026-06-16"'))
        self.assertLess(jun_screen.index('data-day="2026-06-30"'), jun_screen.index("後半小計（16日～最終日）"))
        self.assertLess(jun_screen.index("後半小計（16日～最終日）"), jun_screen.index("月間合計"))
        self.assertLess(jun_print.index("前半小計（前半15日）"), jun_print.index("後半小計（16日～最終日）"))
        self.assertLess(jun_print.index("後半小計（16日～最終日）"), jun_print.index("月間合計"))

        # July (bottom): 前半小計 is NOT between 07-15 and 07-16; all 3 summary rows appear at bottom
        html_jul = self._req("GET", "day=2026-07-10", cookie=sa_cookie).body.decode("utf-8")
        jul_screen, jul_print = _split_screen_and_print(html_jul)
        between_15_16 = jul_screen.split('data-day="2026-07-15"', 1)[1].split('data-day="2026-07-16"', 1)[0]
        self.assertNotIn("前半小計", between_15_16)
        after_31 = jul_screen.split('data-day="2026-07-31"', 1)[1]
        self.assertIn('class="screen-subtotal summary"><th colspan="4">前半小計（前半15日）</th>', after_31)
        self.assertIn('class="screen-subtotal summary"><th colspan="4">後半小計（16日～最終日）</th>', after_31)
        self.assertLess(after_31.index("前半小計（前半15日）"), after_31.index("後半小計（16日～最終日）"))
        self.assertLess(after_31.index("後半小計（16日～最終日）"), after_31.index("月間合計"))
        self.assertLess(jul_print.index("前半小計（前半15日）"), jul_print.index("後半小計（16日～最終日）"))
        self.assertLess(jul_print.index("後半小計（16日～最終日）"), jul_print.index("月間合計"))
        self.assertNotIn("screen-subtotal", jul_print)

        # August (half subtotals OFF): neither screen nor print has half subtotals
        html_aug = self._req("GET", "day=2026-08-10", cookie=sa_cookie).body.decode("utf-8")
        aug_screen, aug_print = _split_screen_and_print(html_aug)
        self.assertNotIn("前半小計", aug_screen)
        self.assertNotIn("後半小計", aug_screen)
        self.assertIn("月間合計", aug_screen)
        self.assertNotIn("前半小計", aug_print)
        self.assertNotIn("後半小計", aug_print)
        self.assertIn("月間合計", aug_print)

        # Settings screen displays radio controls and contract summary badges
        html_settings = self._req("GET", "a=settings", cookie=sa_cookie).body.decode("utf-8")
        self.assertIn('name="contract_subtotal_layout" value="split"', html_settings)
        self.assertIn('name="contract_subtotal_layout" value="bottom"', html_settings)
        self.assertIn("syncSubtotalLayoutState", html_settings)
        self.assertIn(" / 15日小計</div>", html_settings)
        self.assertIn(" / 15日小計(下部)</div>", html_settings)

        # Editing July contract with half subtotals unchecked preserves saved subtotal_layout='bottom'
        jul_c = next(c for c in contracts.contracts() if c["name"] == "BottomSub")
        self.assertEqual("bottom", jul_c["subtotal_layout"])
        res_edit_off = self._req(
            "POST",
            "a=contract_save",
            {
                "contract_id": jul_c["id"],
                "contract_name": "BottomSub",
                "contract_start_date": "2026-07-01",
                "contract_end_date": "2026-07-31",
                "contract_closing": "末",
                "contract_lower": "120",
                "contract_upper": "160",
                "schedule_submitted": "1",
            },
            cookie=sa_cookie,
        )
        self.assertEqual(303, res_edit_off.status)
        jul_c_after = contracts.contract_by_id(jul_c["id"])
        self.assertFalse(jul_c_after["show_half_subtotals"])
        self.assertEqual("bottom", jul_c_after["subtotal_layout"])

    def test_absence_keywords_unified_handling(self):
        import datetime
        from timecard.holidays import national_holidays

        # 1) Keyword detection & workday rule
        for kw in ("【欠勤】", "【休み】", "【病欠】", "【私用】"):
            self.assertTrue(contracts.is_absence_label(kw))
            self.assertTrue(contracts.is_absence_label("午前" + kw))
        self.assertFalse(contracts.is_absence_label("GW"))
        self.assertFalse(contracts.is_absence_label("夏期休暇"))

        c = contracts.normalize_contract(
            {"name": "AbsTest", "start_date": "2026-09-01", "end_date": "2026-09-30"}
        )
        office = {
            "2026-09-07": "【欠勤】",
            "2026-09-08": "【休み】",
            "2026-09-09": "【病欠】",
            "2026-09-10": "【私用】",
            "2026-09-11": "創立記念日",
        }
        official = national_holidays(2026)
        for day_s in ("2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"):
            self.assertTrue(
                contracts.contract_is_workday(c, datetime.date.fromisoformat(day_s), official, office)
            )
        self.assertFalse(
            contracts.contract_is_workday(c, datetime.date(2026, 9, 11), official, office)
        )

        # 2) Full integration: report gray styling, bulk regular exclusion, and settings UI chips
        sa_cookie = self._setup_sysadmin()
        self._req("POST", "a=sample_reset", {}, cookie=sa_cookie)
        contracts.save_contracts(
            [
                {
                    "name": "AbsTest",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-30",
                    "lower": "120",
                    "upper": "160",
                    "closing": "末",
                }
            ]
        )
        saved_c = contracts.contracts()[0]
        contracts.save_contract_holidays(saved_c["id"], office)
        # Also mark another day via note field
        self._req(
            "POST",
            "a=save",
            {"day": "2026-09-14", "note": "【私用】手続き"},
            cookie=sa_cookie,
        )

        # Bulk regular must NOT punch the 4 absence days registered in office holidays or the note day
        res_bulk = self._req("POST", "a=bulk_regular", {"month": "2026-09"}, cookie=sa_cookie)
        self.assertEqual(303, res_bulk.status)

        html = self._req("GET", "day=2026-09-07", cookie=sa_cookie).body.decode("utf-8")
        for day_s in ("2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-14"):
            row = html.split(f'data-day="{day_s}"', 1)[1].split("</tr>", 1)[0]
            self.assertIn("absence", html.split(f'data-day="{day_s}"', 1)[0].rsplit("<tr ", 1)[1])
            self.assertNotIn("08:30", row)
        # Normal workday (2026-09-01) was punched by bulk regular
        row_01 = html.split('data-day="2026-09-01"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("08:30", row_01)
        # Office holiday (2026-09-11) is holiday class and not punched
        self.assertIn("holiday", html.split('data-day="2026-09-11"', 1)[0].rsplit("<tr ", 1)[1])
        # 5 absence days * 8.00h = 40.00h in monthly total
        self.assertIn("不就業 ▲40.00h", html)

        # Settings screen shows absence legend and 4 preset chips
        html_settings = self._req("GET", "a=settings", cookie=sa_cookie).body.decode("utf-8")
        self.assertIn('class="legend-swatch is-absence-holiday"', html_settings)
        for kw in ("【欠勤】", "【休み】", "【病欠】", "【私用】"):
            self.assertIn(f'data-holiday-preset="{kw}"', html_settings)


if __name__ == "__main__":
    unittest.main()
