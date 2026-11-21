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
            '<b>' + esc(APP_SHORT_NAME) + ' <small style="font-size:11px;opacity:.7">v' + esc(APP_VERSION) + "</small></b>"
            + user_badge
            + "</div>"
            '<div class="header-controls">' + header_actions + HEADER_ICON_NAV + "</div>"
            "</header>"
        )
    else:
        header_html = (
            "<header>"
            '<b>' + esc(APP_NAME) + ' <small style="font-size:11px;opacity:.75">v' + esc(APP_VERSION) + "</small></b>"
            "</header>"
        )

    footer_html = (
        '<footer class="app-footer">'
        '<span>' + esc(APP_NAME) + " v" + esc(APP_VERSION) + "</span>"
        '<span>' + esc(APP_COPYRIGHT) + "</span>"
        "</footer>"
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
        + "</body></html>"
    )
