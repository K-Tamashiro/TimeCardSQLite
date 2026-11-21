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


if __name__ == "__main__":
    unittest.main()
