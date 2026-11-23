"""Shared HTML shell with role badge, icon header, and copyright footer."""

from timecard.auth import role_label
from timecard.db import resource_root
from timecard.http_utils import esc
from timecard.version import APP_COPYRIGHT, APP_NAME, APP_SHORT_NAME, APP_VERSION

_STYLE_CACHE = None


def load_stylesheet():
    global _STYLE_CACHE
    if _STYLE_CACHE is None:
        _STYLE_CACHE = (resource_root() / "assets" / "style.css").read_text(
            encoding="utf-8"
        )
    return _STYLE_CACHE


HEADER_ICON_NAV = (
    '<nav class="header-nav" aria-label="メニュー">'
    '<a href="/" class="header-icon-link" aria-label="勤務表" title="勤務表">'
    '<img src="images/work-list.png" alt="勤務表"></a>'
    '<a href="/?a=settings" class="header-icon-link" aria-label="設定" title="設定">'
    '<img src="images/setting.png" alt="設定"></a>'
    '<a href="/?a=logout" class="header-icon-link" aria-label="ログアウト" title="ログアウト">'
    '<img src="images/logout.png" alt="ログアウト"></a>'
    "</nav>"
)


def layout(title, body, header_actions="", sess=None):
    full_title = (title + " | " if title else "") + APP_NAME
    if sess:
        role_cls = "role-badge is-" + esc(sess["active_role"])
        user_badge = (
            '<span class="header-user-info">'
            '<span class="' + role_cls + '">' + esc(role_label(sess["active_role"])) + "</span>"
            '<span class="header-user-name">' + esc(sess["display_name"] or sess["login"]) + "</span>"
            "</span>"
        )
        header_cls = "has-icon-nav" + (" has-header-actions" if header_actions else "")
        header_html = (
            '<header class="' + header_cls + '">'
            '<div class="header-brand">'
            '<b class="header-logo-wrap"><img src="images/app_title.png" alt="' + esc(APP_NAME) + '" class="header-title-logo">'
            '<small class="header-version">v' + esc(APP_VERSION) + "</small></b>"
            + user_badge
            + "</div>"
            '<div class="header-controls">' + header_actions + HEADER_ICON_NAV + "</div>"
            "</header>"
        )
    else:
        header_html = (
            "<header>"
            '<b class="header-logo-wrap"><img src="images/app_title.png" alt="' + esc(APP_NAME) + '" class="header-title-logo">'
            '<small class="header-version">v' + esc(APP_VERSION) + "</small></b>"
            "</header>"
        )

    footer_html = (
        '<footer class="app-footer">'
        '<span>' + esc(APP_NAME) + " v" + esc(APP_VERSION) + "</span>"
        '<span>' + esc(APP_COPYRIGHT) + "</span>"
        "</footer>"
    )
    watcher_js = (
        "<script>(function(){"
        "var wasLoggedIn=" + ("true" if sess else "false") + ";"
        "var stopped=false;"
        "function showStopped(){"
        "if(stopped)return;stopped=true;"
        "if(timer)clearInterval(timer);"
        "document.title='終了しました | " + esc(APP_NAME) + "';"
        "document.body.innerHTML="
        "'<div style=\"max-width:520px;margin:72px auto;padding:28px 26px;background:#fff;border-radius:14px;box-shadow:0 6px 24px rgba(18,57,71,.12);text-align:center;font-family:system-ui,Meiryo,sans-serif;color:#182c36\">'"
        "+'<h1 style=\"margin:0 0 12px;font-size:20px;color:#123947\">アプリを終了しました（ログアウト済み）</h1>'"
        "+'<p style=\"margin:0 0 10px;line-height:1.7;font-size:14px;color:#3d5563\">ローカルサーバーが停止し、安全にログアウトされました。<br>このブラウザタブは閉じていただいて構いません。</p>'"
        "+'<p style=\"margin:0;font-size:12px;color:#6c8290\">再度利用する場合は、アプリを起動し直してください。</p>'"
        "+'</div>';"
        "}"
        "function check(){"
        "if(stopped)return;"
        "fetch('/?a=status',{cache:'no-store',credentials:'same-origin'})"
        ".then(function(r){if(!r.ok)throw new Error('http');return r.json();})"
        ".then(function(d){"
        "if(!d||d.running===false){showStopped();return;}"
        "if(wasLoggedIn&&d.logged_in===false){location.href='/';}"
        "})"
        ".catch(function(){showStopped();});"
        "}"
        "var timer=setInterval(check,2000);"
        "window.addEventListener('focus',check);"
        "document.addEventListener('visibilitychange',function(){if(!document.hidden)check();});"
        "})();</script>"
    )
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + esc(full_title) + "</title>"
        '<link rel="icon" type="image/x-icon" href="favicon.ico">'
        "<style>" + load_stylesheet() + "</style>"
        "</head><body>"
        + header_html
        + "<main>"
        + body
        + "</main>"
        + footer_html
        + watcher_js
        + "</body></html>"
    )
