"""Password hashing, 3-tier role authentication, and session management."""

import datetime
import hashlib
import hmac
import http.cookies
import secrets
from timecard.db import con

ROLE_SYSADMIN = "sysadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

ROLE_LABELS = {
    ROLE_SYSADMIN: "システム管理者",
    ROLE_ADMIN: "管理者",
    ROLE_USER: "ユーザ",
}


def digest(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 180000
    ).hex()


def has_any_sysadmin():
    row = con.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role=?", (ROLE_SYSADMIN,)
    ).fetchone()
    return bool(row and row["n"] > 0)


def list_users():
    return con.execute(
        "SELECT id, login, display_name, role, can_admin, is_sample, created_at "
        "FROM users ORDER BY CASE WHEN role='sysadmin' THEN 0 ELSE 1 END, id ASC"
    ).fetchall()


def create_user(login, password, display_name="", role=ROLE_USER, can_admin=False, is_sample=False):
    login = (login or "").strip()
    display_name = (display_name or "").strip()[:60]
    if not login or len(login) > 60:
        raise ValueError("ログインIDは1～60文字で入力してください。")
    if len(password or "") < 6:
        raise ValueError("パスワードは6文字以上で入力してください。")
    if role not in (ROLE_SYSADMIN, ROLE_USER):
        raise ValueError("ロール指定が不正です。")
    exists = con.execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()
    if exists:
        raise ValueError("同じログインIDが既に登録されています。")
    salt = secrets.token_hex(16)
    pw_hash = digest(password, salt)
    now = datetime.datetime.utcnow().isoformat()
    can_admin_int = 1 if (role == ROLE_USER and can_admin) else 0
    cur = con.execute(
        "INSERT INTO users(login, display_name, role, can_admin, is_sample, salt, pw, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (login, display_name or login, role, can_admin_int, 1 if is_sample else 0, salt, pw_hash, now),
    )
    con.commit()
    return cur.lastrowid


def update_user(user_id, display_name=None, can_admin=None, new_password=None):
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise ValueError("対象のユーザーが見つかりません。")
    disp = row["display_name"] if display_name is None else (display_name.strip()[:60] or row["login"])
    if row["role"] == ROLE_SYSADMIN:
        can_adm = 0
    else:
        can_adm = row["can_admin"] if can_admin is None else (1 if can_admin else 0)
    if new_password:
        if len(new_password) < 6:
            raise ValueError("パスワードは6文字以上で入力してください。")
        salt = secrets.token_hex(16)
        pw_hash = digest(new_password, salt)
        con.execute(
            "UPDATE users SET display_name=?, can_admin=?, salt=?, pw=? WHERE id=?",
            (disp, can_adm, salt, pw_hash, user_id),
        )
    else:
        con.execute(
            "UPDATE users SET display_name=?, can_admin=? WHERE id=?",
            (disp, can_adm, user_id),
        )
    if row["role"] == ROLE_USER and can_adm == 0:
        # Downgrade any active admin sessions for this user immediately.
        con.execute(
            "DELETE FROM sessions WHERE user_id=? AND active_role=?",
            (user_id, ROLE_ADMIN),
        )
    con.commit()


def delete_user(user_id, actor_user_id):
    if int(user_id) == int(actor_user_id):
        raise ValueError("現在ログイン中の自分自身は削除できません。")
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise ValueError("対象のユーザーが見つかりません。")
    if row["role"] == ROLE_SYSADMIN:
        cnt = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role=?", (ROLE_SYSADMIN,)
        ).fetchone()["n"]
        if cnt <= 1:
            raise ValueError("最後のシステム管理者は削除できません。")
    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM work WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM settings WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM events WHERE scope='private' AND user_id=?", (user_id,))
    con.execute("DELETE FROM users WHERE id=?", (user_id,))
    con.commit()


def authenticate(login, password, as_admin=False):
    """Return (session_token, active_role, user_row) or raise ValueError."""
    r = con.execute("SELECT * FROM users WHERE login=?", ((login or "").strip(),)).fetchone()
    if not r or not hmac.compare_digest(r["pw"], digest(password or "", r["salt"])):
        raise ValueError("ログインIDまたはパスワードが正しくありません。")
    if r["role"] == ROLE_SYSADMIN:
        active_role = ROLE_SYSADMIN
    elif as_admin:
        if not r["can_admin"]:
            raise ValueError("このアカウントには管理者としてログインする権限がありません。")
        active_role = ROLE_ADMIN
    else:
        active_role = ROLE_USER
    token = secrets.token_urlsafe(36)
    expiry = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat()
    con.execute(
        "INSERT INTO sessions(token, user_id, active_role, expires) VALUES(?,?,?,?)",
        (token, r["id"], active_role, expiry),
    )
    con.commit()
    return (token, active_role, r)


def revoke_session(cookie_header):
    token = _extract_token(cookie_header)
    if token:
        con.execute("DELETE FROM sessions WHERE token=?", (token,))
        con.commit()


def revoke_all_sessions():
    """Invalidate all active sessions (used on standalone launcher startup/shutdown)."""
    con.execute("DELETE FROM sessions")
    con.commit()


def _extract_token(cookie_header):
    c = http.cookies.SimpleCookie()
    try:
        c.load(cookie_header or "")
    except http.cookies.CookieError:
        return None
    m = c.get("tc_session")
    return m.value if m and m.value else None


def current_session(cookie_header):
    """Return dict(user_id, login, display_name, account_role, active_role, can_admin) or None."""
    token = _extract_token(cookie_header)
    if not token:
        return None
    now = datetime.datetime.utcnow().isoformat()
    row = con.execute(
        "SELECT s.user_id, s.active_role, u.login, u.display_name, u.role AS account_role, u.can_admin "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token=? AND s.expires>?",
        (token, now),
    ).fetchone()
    return row


def is_sysadmin(sess):
    return bool(sess and sess["active_role"] == ROLE_SYSADMIN)


def can_edit_holidays(sess):
    return bool(sess and sess["active_role"] in (ROLE_SYSADMIN, ROLE_ADMIN))


def can_edit_public_events(sess):
    return is_sysadmin(sess)


def can_use_csv(sess):
    return is_sysadmin(sess)


def role_label(active_role):
    return ROLE_LABELS.get(active_role, active_role)
