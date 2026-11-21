"""HTTP response helpers and HTML escaping for the standalone server."""

from dataclasses import dataclass, field
import html
import json


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


@dataclass
class Response:
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    body: bytes = b""
    headers: list = field(default_factory=list)


def html_response(body, status=200, headers=None):
    data = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    return Response(
        status=status,
        content_type="text/html; charset=utf-8",
        body=data,
        headers=list(headers or []),
    )


def text_response(body, status=200, headers=None):
    data = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    return Response(
        status=status,
        content_type="text/plain; charset=utf-8",
        body=data,
        headers=list(headers or []),
    )


def json_response(data, status=200, headers=None):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(
        status=status,
        content_type="application/json; charset=utf-8",
        body=raw,
        headers=list(headers or []),
    )


def csv_response(body, filename):
    data = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    return Response(
        status=200,
        content_type="text/csv; charset=utf-8",
        body=data,
        headers=[("Content-Disposition", 'attachment; filename="' + filename + '"')],
    )


def redirect(location, headers=None):
    hdrs = [("Location", location)]
    if headers:
        hdrs.extend(headers)
    return Response(status=303, content_type="text/plain; charset=utf-8", body=b"", headers=hdrs)
