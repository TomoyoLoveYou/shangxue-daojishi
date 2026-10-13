"""把项目源码打包成 EdgeOne Pages 的云函数（本地运行）。

产物（都是自包含单文件，不依赖外部模块或资源，便于平台打包）：
    cloud-functions/index.py   ->  GET /     返回注入 og:* 元信息后的页面
    cloud-functions/og.py      ->  GET /og   动态渲染分享卡片图（PNG）

EdgeOne Pages 的 Python 云函数（Handler 模式）约定：
  - 文件即路由：cloud-functions/<path>.py 对应 /<path>
  - 文件内必须有名为 handler 的类，继承 http.server.BaseHTTPRequestHandler
  - 运行时 Python 3.10，支持纯标准库

用法：python tools/build_edgeone.py
"""

import base64
import os
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


OG_HANDLER = '''

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    """EdgeOne 云函数入口：GET /og -> 动态渲染的分享卡片图。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def _serve(self, head_only):
        try:
            body = render_png()
        except Exception:  # noqa: BLE001
            # 渲染失败时退回静态封面，保证卡片至少有一张图
            self.send_response(302)
            self.send_header("Location", "/assets/share-cover.png")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
'''


INDEX_TEMPLATE = '''# 上学倒计时 —— EdgeOne Pages 云函数（自动生成，请勿手改）
# 重新生成：python tools/build_edgeone.py
# 路由：GET /  ->  按当前倒计时注入 og:* 元信息后返回页面
#
# 说明：微信只读服务端返回的 HTML，所以卡片信息必须在这里按请求现算。

import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

PAGE_HTML = @PAGE_HTML@

# 若卡片图地址不对（反向代理把 Host 改写成了内部域名），可在 EdgeOne 项目设置里
# 添加环境变量 EO_PUBLIC_ORIGIN=https://你的域名，即可强制指定对外地址。
PUBLIC_ORIGIN = os.environ.get("EO_PUBLIC_ORIGIN", "").strip().rstrip("/")

BEIJING = timezone(timedelta(hours=8))
TARGET_HOUR = 18
TARGET_MINUTE = 35
WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")
OG_BEGIN = "<!-- og:begin -->"
OG_END = "<!-- og:end -->"
INTERNAL_HINTS = ("internal", "localhost", "127.0.0.1", ".local", "sandbox", "cloudstudio", "e2b.")


def next_target(now):
    """与前端 app.js 一致：北京时间下个周日 18:35。"""
    bj = now.astimezone(BEIJING)
    today = bj.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    days = (6 - bj.weekday()) % 7
    if days == 0 and bj >= today:
        days = 7
    return today + timedelta(days=days)


def split_countdown(target, now):
    total = max(0, int((target - now).total_seconds()))
    return total // 86400, (total % 86400) // 3600, (total % 3600) // 60, total % 60


def target_label(target):
    bj = target.astimezone(BEIJING)
    return "%d月%d日 周%s %02d:%02d" % (
        bj.month, bj.day, WEEKDAY_CN[bj.weekday()], bj.hour, bj.minute)


def build_plan(days, hours, minutes, seconds):
    pairs = [(days, "天"), (hours, "时"), (minutes, "分"), (seconds, "秒")]
    idx = 0
    while idx < len(pairs) - 1 and pairs[idx][0] == 0:
        idx += 1
    return pairs[idx:idx + 3]


def plan_head(plan):
    long_unit = {"天": "天", "时": "小时", "分": "分", "秒": "秒"}
    parts = ["%d %s" % (value, long_unit[unit]) for value, unit in plan[:2]]
    return "还有 " + " ".join(parts)


def pick_origin(headers):
    """找出对外可访问的站点地址，供 og:image / og:url 使用。"""
    if PUBLIC_ORIGIN:
        return PUBLIC_ORIGIN
    proto = (headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    for key in ("X-Forwarded-Host", "Host"):
        raw = headers.get(key)
        if not raw:
            continue
        for host in raw.split(","):
            host = host.strip()
            if not host:
                continue
            if any(hint in host.lower() for hint in INTERNAL_HINTS):
                continue
            return "%s://%s" % (proto, host)
    raw = headers.get("Host") or headers.get("X-Forwarded-Host") or ""
    return "%s://%s" % (proto, raw.split(",")[0].strip()) if raw else ""


def render_html(origin, now):
    target = next_target(now)
    days, hours, minutes, seconds = split_countdown(target, now)
    plan = build_plan(days, hours, minutes, seconds)
    label = target_label(target)
    title = "上学倒计时 · " + plan_head(plan)
    desc = "目标 %s · 北京时间，点开查看秒级倒计时" % label
    image = "%s/og?v=%dd%02dh%02d" % (origin, days, hours, minutes)
    page_url = origin + "/"

    block = "\\n".join([
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

    html = PAGE_HTML
    start = html.find(OG_BEGIN)
    end = html.find(OG_END)
    if start >= 0 and end > start:
        html = html[:start] + block + html[end + len(OG_END):]
    return html


class handler(BaseHTTPRequestHandler):
    """EdgeOne 云函数入口：GET / -> 注入卡片信息后的页面。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def _serve(self, head_only):
        origin = pick_origin(self.headers)
        body = render_html(origin, datetime.now(timezone.utc)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
'''


def build_og(out_dir):
    source = open(os.path.join(ROOT, "ogcard.py"), encoding="utf-8").read()
    source = source.split('if __name__ == "__main__":')[0].rstrip() + "\n"
    raw = open(os.path.join(ROOT, "assets", "glyphs.json"), "rb").read()
    payload = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")

    content = (
        "# 上学倒计时 —— EdgeOne Pages 云函数（自动生成，请勿手改）\n"
        "# 源文件：ogcard.py（渲染器） + assets/glyphs.json（字形数据，已内嵌）\n"
        "# 重新生成：python tools/build_edgeone.py\n"
        "# 路由：GET /og -> 900x900 PNG（分享卡片图）\n\n"
        + source
        + '\n\nGLYPH_PAYLOAD = "%s"\n' % payload
        + OG_HANDLER
    )
    path = os.path.join(out_dir, "og.py")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path


def build_index(out_dir):
    page = open(os.path.join(ROOT, "page.html"), encoding="utf-8").read()
    content = INDEX_TEMPLATE.replace("@PAGE_HTML@", repr(page))
    path = os.path.join(out_dir, "index.py")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path


def main():
    out_dir = os.path.join(ROOT, "cloud-functions")
    os.makedirs(out_dir, exist_ok=True)
    for path in (build_og(out_dir), build_index(out_dir)):
        print("written: %s  (%.1f KB)" % (path, os.path.getsize(path) / 1024.0))


if __name__ == "__main__":
    main()
