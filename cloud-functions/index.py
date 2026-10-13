# 上学倒计时 —— EdgeOne Pages 云函数（自动生成，请勿手改）
# 重新生成：python tools/build_edgeone.py
# 路由：GET /  ->  按当前倒计时注入 og:* 元信息后返回页面
#
# 说明：微信只读服务端返回的 HTML，所以卡片信息必须在这里按请求现算。

import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

PAGE_HTML = '<!doctype html>\n<html lang="zh-CN">\n  <head>\n    <meta charset="UTF-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />\n    <meta name="theme-color" content="#f5f8f6" />\n    <title>上学倒计时</title>\n    <!-- og:begin -->\n    <meta name="description" content="简洁的上学倒计时，显示距离北京时间周日 18:35 的剩余时间。" />\n    <meta property="og:type" content="website" />\n    <meta property="og:site_name" content="上学倒计时" />\n    <meta property="og:title" content="上学倒计时" />\n    <meta property="og:description" content="目标 10月18日 周日 18:35 · 北京时间，点开查看秒级倒计时" />\n    <meta property="og:image" content="https://school-countdown.app.workbuddy.host/assets/share-cover.png" />\n    <meta property="og:image:type" content="image/png" />\n    <meta property="og:image:width" content="900" />\n    <meta property="og:image:height" content="900" />\n    <meta property="og:url" content="https://school-countdown.app.workbuddy.host/" />\n    <meta name="twitter:card" content="summary" />\n    <!-- og:end -->\n    <link rel="stylesheet" href="styles.css" />\n  </head>\n  <body>\n    <main class="app-shell">\n      <section class="timer-page" aria-labelledby="page-title">\n        <header class="topbar">\n          <div class="brand-mark" aria-hidden="true">计</div>\n          <div class="brand-copy">\n            <p class="eyebrow">TIME TO GO</p>\n            <h1 id="page-title">上学倒计时</h1>\n          </div>\n          <button class="icon-button" id="reset-button" type="button" aria-label="恢复默认目标" title="恢复默认目标">\n            <span aria-hidden="true">↺</span>\n          </button>\n        </header>\n\n        <section class="hero-panel" aria-live="polite">\n          <div class="status-row">\n            <span class="status-dot" aria-hidden="true"></span>\n            <span id="status-label">距离下个周日</span>\n          </div>\n          <div class="countdown" id="countdown" aria-label="剩余时间">\n            <span id="days" class="countdown-value">00</span>\n            <span class="countdown-unit">天</span>\n            <span class="countdown-value" id="hours">00</span>\n            <span class="countdown-unit">时</span>\n            <span class="countdown-value" id="minutes">00</span>\n            <span class="countdown-unit">分</span>\n            <span class="countdown-value" id="seconds">00</span>\n            <span class="countdown-unit">秒</span>\n          </div>\n          <p class="target-caption" id="target-caption">目标：周日下午 6:35</p>\n        </section>\n\n        <section class="info-grid" aria-label="目标信息">\n          <article class="info-item">\n            <span class="info-label">目标日期</span>\n            <strong id="target-date">--月--日 周日</strong>\n          </article>\n          <article class="info-item">\n            <span class="info-label">目标时间</span>\n            <strong id="target-time">18:35</strong>\n          </article>\n        </section>\n\n        <button class="customize-button" id="customize-button" type="button">\n          <span class="button-icon" aria-hidden="true">＋</span>\n          <span>自定义目标时间</span>\n          <span class="button-arrow" aria-hidden="true">→</span>\n        </button>\n\n        <footer class="footer-note">\n          <span class="footer-line" aria-hidden="true"></span>\n          <span>北京时间 · 精确到秒</span>\n          <span class="footer-line" aria-hidden="true"></span>\n        </footer>\n      </section>\n    </main>\n\n    <dialog class="custom-dialog" id="custom-dialog" aria-labelledby="dialog-title">\n      <form class="dialog-card" id="custom-form" method="dialog">\n        <div class="dialog-handle" aria-hidden="true"></div>\n        <div class="dialog-heading">\n          <div>\n            <p class="eyebrow">SET YOUR MOMENT</p>\n            <h2 id="dialog-title">自定义目标时间</h2>\n          </div>\n          <button class="close-button" id="close-dialog" type="button" aria-label="关闭">×</button>\n        </div>\n        <p class="dialog-description">选择一个具体日期和时间，倒计时会立即更新。</p>\n        <div class="form-fields">\n          <label class="field-label" for="custom-date">日期</label>\n          <input class="field-input" id="custom-date" name="custom-date" type="date" required />\n          <label class="field-label" for="custom-time">时间</label>\n          <input class="field-input" id="custom-time" name="custom-time" type="time" required />\n        </div>\n        <button class="save-button" type="submit">开始倒计时</button>\n      </form>\n    </dialog>\n\n    <script src="app.js"></script>\n  </body>\n</html>\n'

# 卡片图（og:image）必须是外网可达的绝对地址，而云函数看到的 Host 往往是内部域名
# （实测平台会给出 pages-xx.pages-scf-gz-pro.qcloudteo.com 这类地址）。因此：
#   1) 优先用下面的 PUBLIC_ORIGIN_DEFAULT / 环境变量 EO_PUBLIC_ORIGIN（最可靠）
#   2) 否则在请求头里挑平台公开域名（*.edgeone.app|.cool|.run）或非内部域名
#   3) 都拿不准时退化为相对地址 /og，交给抓取方按页面地址解析
PUBLIC_ORIGIN_DEFAULT = ""  # 绑定自定义域名后填这里，例如 "https://xxx.example.com"

PUBLIC_ORIGIN = (os.environ.get("EO_PUBLIC_ORIGIN") or PUBLIC_ORIGIN_DEFAULT).strip().rstrip("/")

BEIJING = timezone(timedelta(hours=8))
TARGET_HOUR = 18
TARGET_MINUTE = 35
WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")
OG_BEGIN = "<!-- og:begin -->"
OG_END = "<!-- og:end -->"
PUBLIC_HOST_SUFFIXES = (".edgeone.app", ".edgeone.cool", ".edgeone.run")
INTERNAL_HINTS = ("internal", "localhost", "127.0.0.1", ".local", "sandbox",
                  "cloudstudio", "e2b.", "qcloudteo", "tencentcloudapi",
                  "myqcloud", "qcloud.com")


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
    candidates = []
    for key in ("X-Forwarded-Host", "Host", "X-Original-Host", "X-Forwarded-Server"):
        raw = headers.get(key)
        if not raw:
            continue
        for host in raw.split(","):
            host = host.strip()
            if host and host not in candidates:
                candidates.append(host)
    for host in candidates:  # 平台公开域名优先
        if host.lower().endswith(PUBLIC_HOST_SUFFIXES):
            return "%s://%s" % (proto, host)
    for host in candidates:  # 其次是非内部的（多半是自定义域名）
        if not any(hint in host.lower() for hint in INTERNAL_HINTS):
            return "%s://%s" % (proto, host)
    return ""  # 拿不准就退化为相对地址


def render_html(origin, now):
    target = next_target(now)
    days, hours, minutes, seconds = split_countdown(target, now)
    plan = build_plan(days, hours, minutes, seconds)
    label = target_label(target)
    title = "上学倒计时 · " + plan_head(plan)
    desc = "目标 %s · 北京时间，点开查看秒级倒计时" % label
    image = "%s/og?v=%dd%02dh%02d" % (origin, days, hours, minutes)
    page_url = origin + "/"

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
