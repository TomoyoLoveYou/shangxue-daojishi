"""上学倒计时 —— 站点服务（纯标准库，无第三方依赖）。

在原有静态页面的基础上多做两件事：
1. 请求 index.html 时，按「当前倒计时」动态注入 og:* 元信息（微信只能抓服务端返回的 HTML）
2. /og.png 实时渲染当前倒计时的分享卡片图

启动：PORT=3000 python3 server.py
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ogcard

PORT = int(os.environ.get("PORT", "3000"))
BIND = "0.0.0.0"

OG_BEGIN = "<!-- og:begin -->"
OG_END = "<!-- og:end -->"

# 反向代理会把 Host 改写成沙箱内部域名，而 og:image / og:url 必须是外网可达地址。
# 因此优先取公开域名，取不到就退回应用固定的分享域名。
PUBLIC_HOST_SUFFIXES = (".workbuddy.host",)
PUBLIC_HOST_FALLBACK = "school-countdown.app.workbuddy.host"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}

_index_lock = threading.Lock()
_index_cache = {"stamp": None, "text": None}


def _read_page() -> str:
    path = os.path.join(HERE, "page.html")
    stamp = os.path.getmtime(path)
    with _index_lock:
        if _index_cache["stamp"] != stamp or _index_cache["text"] is None:
            with open(path, "rb") as fh:
                _index_cache["text"] = fh.read().decode("utf-8")
            _index_cache["stamp"] = stamp
        return _index_cache["text"]


def render_html(host: str) -> str:
    """把 index.html 里的 og:begin/og:end 区块替换成当前的动态卡片信息。"""
    meta = ogcard.render_meta()
    image = "https://%s/og.png?v=%s" % (host, meta["cache_key"])
    page_url = "https://%s/" % host
    title = "上学倒计时 · %s" % meta["head"]
    desc = "目标 %s · 北京时间，点开查看秒级倒计时" % meta["label"]

    block = "\n".join([
        OG_BEGIN,
        '    <meta name="description" content="%s" />' % desc,
        '    <meta property="og:type" content="website" />',
        '    <meta property="og:site_name" content="上学倒计时" />',
        '    <meta property="og:title" content="%s" />' % title,
        '    <meta property="og:description" content="%s" />' % desc,
        '    <meta property="og:image" content="%s" />' % image,
        '    <meta property="og:image:type" content="image/png" />',
        '    <meta property="og:image:width" content="900" />',
        '    <meta property="og:image:height" content="900" />',
        '    <meta property="og:url" content="%s" />' % page_url,
        '    <meta name="twitter:card" content="summary" />',
        OG_END,
    ])

    html = _read_page()
    start = html.find(OG_BEGIN)
    end = html.find(OG_END)
    if start >= 0 and end > start:
        html = html[:start] + block + html[end + len(OG_END):]
    return html


class Handler(BaseHTTPRequestHandler):
    server_version = "shangxue-daojishi/1.0"
    protocol_version = "HTTP/1.1"

    # -- 基础输出 ------------------------------------------------------------
    def _send(self, status, body, ctype, cache="no-store", head_only=False):
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host(self) -> str:
        candidates = []
        for key in ("X-Forwarded-Host", "Host"):
            raw = self.headers.get(key)
            if raw:
                candidates.extend(h.strip() for h in raw.split(",") if h.strip())
        if not candidates:
            return PUBLIC_HOST_FALLBACK
        for host in candidates:
            if host.endswith(PUBLIC_HOST_SUFFIXES):
                return host
        for host in candidates:
            if host.partition(":")[0] in ("localhost", "127.0.0.1", "[::1]", "::1"):
                return host
        return PUBLIC_HOST_FALLBACK

    # -- 路由 ----------------------------------------------------------------
    def do_GET(self):
        self._route(head_only=False)

    def do_HEAD(self):
        self._route(head_only=True)

    def _route(self, head_only: bool):
        path = unquote(urlparse(self.path).path)

        if path == "/":
            body = render_html(self._host()).encode("utf-8")
            self._send(200, body, "text/html; charset=utf-8", "no-store", head_only)
            return

        if path == "/og.png":
            body = ogcard.render_png()
            self._send(200, body, "image/png", "public, max-age=300", head_only)
            return

        self._static(path, head_only)

    def _static(self, path: str, head_only: bool):
        rel = path.lstrip("/")
        target = os.path.normpath(os.path.join(HERE, rel))
        if not target.startswith(HERE + os.sep) or not os.path.isfile(target):
            self._send(404, b"Not Found", "text/plain; charset=utf-8", "no-store", head_only)
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as fh:
            body = fh.read()
        self._send(200, body, MIME.get(ext, "application/octet-stream"),
                   "public, max-age=300", head_only)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    # 预热：把背景/字形/首张卡片算好，避免第一次抓取超时
    try:
        ogcard.render_png()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("warmup skipped: %r\n" % (exc,))
    httpd = Server((BIND, PORT), Handler)
    sys.stderr.write("listening on %s:%d\n" % (BIND, PORT))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
