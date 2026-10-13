# 上学倒计时 —— EdgeOne Pages 云函数（自动生成，请勿手改）
# 源文件：ogcard.py（渲染器） + assets/glyphs.json（字形数据，已内嵌）
# 重新生成：python tools/build_edgeone.py
# 路由：GET /og -> 900x900 PNG（分享卡片图）

"""上学倒计时 —— 分享卡片图渲染（纯标准库）。

渲染一张 900x900 的 PNG：薄荷渐变背景 + 超大「剩余天数」+ 时/分 + 目标时间。
运行时不依赖任何第三方库：字形蒙版由 tools/build_glyphs.py 预生成到
assets/glyphs.json，这里只做「蒙版合成 + PNG 编码」。

单独预览：
    python ogcard.py preview.png
"""

from __future__ import annotations

import base64
import json
import math
import os
import struct
import zlib
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
GLYPH_FILE = os.path.join(HERE, "assets", "glyphs.json")

# tools/build_edgeone.py 生成云函数时会在这里内嵌字形数据（zlib+base64），
# 使部署产物是单文件、不依赖外部资源；本地运行时保持 None，从 assets/ 读取。
GLYPH_PAYLOAD = None

CANVAS = 900
STRIDE = CANVAS * 3
BEIJING = timezone(timedelta(hours=8))

INK = (24, 55, 45)
INK_SOFT = (101, 128, 117)
INK_FAINT = (148, 169, 159)
PAPER = (255, 255, 255)
LINE = (220, 232, 223)
ACCENT = (237, 138, 85)
BG_TOP = (245, 248, 246)
BG_BOTTOM = (228, 239, 233)
BLOB = (207, 226, 215)

TARGET_HOUR = 18
TARGET_MINUTE = 35
WEEKDAY_CN = ("一", "二", "三", "四", "五", "六", "日")

# 版面字号
HERO_SIZE = 300        # 主视觉数字
HERO_UNIT_SIZE = 56    # 主视觉单位
ROW_SIZE = 76          # 次级数字
ROW_UNIT_SIZE = 22     # 次级单位
LINE_SIZE = 30         # 目标时间行
TITLE_SIZE = 44        # 标题 / 品牌字
EYEBROW_SIZE = 20      # 英文小标

# 需要预渲染的字形清单：字号 -> 字符集
GLYPH_SPEC = {
    HERO_SIZE: "0123456789",
    ROW_SIZE: "0123456789",
    HERO_UNIT_SIZE: "天时分秒",
    TITLE_SIZE: "上学倒计时",
    LINE_SIZE: "0123456789:目标月日周",
    ROW_UNIT_SIZE: "时分秒",
    EYEBROW_SIZE: "TIMEOG",
}

MONO_SIZES = {EYEBROW_SIZE}

_glyphs = None
_bg = None
_png_cache: dict = {}


# --------------------------------------------------------------------------
# 倒计时计算（与前端 app.js 的默认目标保持一致：北京时间下个周日 18:35）
# --------------------------------------------------------------------------

def next_target(now: datetime) -> datetime:
    bj = now.astimezone(BEIJING)
    today = bj.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    days = (6 - bj.weekday()) % 7
    if days == 0 and bj >= today:
        days = 7
    return today + timedelta(days=days)


def split_countdown(target: datetime, now: datetime):
    total = max(0, int((target - now).total_seconds()))
    return total // 86400, (total % 86400) // 3600, (total % 3600) // 60, total % 60


def target_label(target: datetime) -> str:
    bj = target.astimezone(BEIJING)
    return "%d月%d日 周%s %02d:%02d" % (
        bj.month,
        bj.day,
        WEEKDAY_CN[bj.weekday()],
        bj.hour,
        bj.minute,
    )


def build_plan(days: int, hours: int, minutes: int, seconds: int):
    """把剩余时间拆成「单位序列」，保证任何阶段都有可读的主视觉。

    规则：丢掉前面为零的单位（至少保留最后一个），最多取三项。
    剩 5 天  -> [(5, '天'), (9, '时'), (44, '分')]
    剩 9 小时 -> [(9, '时'), (44, '分'), (12, '秒')]
    剩 44 分钟 -> [(44, '分'), (12, '秒')]
    """
    pairs = [(days, "天"), (hours, "时"), (minutes, "分"), (seconds, "秒")]
    idx = 0
    while idx < len(pairs) - 1 and pairs[idx][0] == 0:
        idx += 1
    return pairs[idx:idx + 3]


def plan_head(plan) -> str:
    """给分享卡片的一句话文案（用自然的中文单位）。"""
    long_unit = {"天": "天", "时": "小时", "分": "分", "秒": "秒"}
    parts = ["%d %s" % (value, long_unit[unit]) for value, unit in plan[:2]]
    return "还有 " + " ".join(parts)


# --------------------------------------------------------------------------
# 字形蒙版
# --------------------------------------------------------------------------

def _glyph_data():
    if GLYPH_PAYLOAD:
        return json.loads(zlib.decompress(base64.b64decode(GLYPH_PAYLOAD)).decode("utf-8"))
    with open(GLYPH_FILE, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _load_glyphs():
    global _glyphs
    if _glyphs is None:
        data = _glyph_data()
        sizes = {}
        for size, table in data["sizes"].items():
            glyphs = {}
            for ch, info in table.items():
                raw = zlib.decompress(base64.b64decode(info["mask"])) if info["mask"] else b""
                w, h = info["w"], info["h"]
                rows = []
                for dy in range(h):
                    row = raw[dy * w:(dy + 1) * w]
                    first = -1
                    last = -1
                    for i, v in enumerate(row):
                        if v:
                            if first < 0:
                                first = i
                            last = i
                    if first >= 0:
                        rows.append((dy, first, row[first:last + 1]))
                glyphs[ch] = {
                    "adv": info["adv"],
                    "left": info["left"],
                    "top": info["top"],
                    "h": h,
                    "rows": rows,
                }
            sizes[int(size)] = glyphs
        _glyphs = sizes
    return _glyphs


def _metrics(text: str, size: int):
    table = _load_glyphs()[size]
    top = 0.0
    bottom = 0.0
    width = 0.0
    for ch in text:
        g = table.get(ch) or table.get(" ")
        if g is None:
            continue
        width += g["adv"]
        if g["h"]:
            top = max(top, g["top"])
            bottom = min(bottom, g["top"] - g["h"])
    return width, top, bottom


def _blit(buf, x, y, glyph, color, alpha, touched):
    r, g, b = color
    for dy, x0, row in glyph["rows"]:
        py = y + dy
        if py < 0 or py >= CANVAS:
            continue
        gx = x + x0
        start = 0
        end = len(row)
        if gx < 0:
            start = -gx
            gx = 0
        if gx + (end - start) > CANVAS:
            end = start + (CANVAS - gx)
        if end <= start:
            continue
        base = (py * CANVAS + gx) * 3
        for i in range(start, end):
            a = row[i]
            if not a:
                continue
            af = a if alpha >= 1.0 else int(a * alpha)
            if af <= 0:
                continue
            idx = base + (i - start) * 3
            inv = 255 - af
            buf[idx] = (buf[idx] * inv + r * af) // 255
            buf[idx + 1] = (buf[idx + 1] * inv + g * af) // 255
            buf[idx + 2] = (buf[idx + 2] * inv + b * af) // 255
        if touched is not None:
            touched.add(py)


def draw_text(buf, text, size, x, baseline, color, tracking=0.0,
              center_x=None, center_y=None, touched=None):
    width, top, bottom = _metrics(text, size)
    if center_x is not None:
        x = center_x - width / 2.0
    if center_y is not None:
        baseline = center_y + (top + bottom) / 2.0
    table = _load_glyphs()[size]
    pen = x
    for ch in text:
        g = table.get(ch) or table.get(" ")
        if g is not None:
            if g["rows"]:
                _blit(buf, int(round(pen + g["left"])), int(round(baseline - g["top"])),
                      g, color, 1.0, touched)
            pen += g["adv"] + tracking
    return width


def draw_runs(buf, runs, center_x=CANVAS / 2.0, center_y=None, baseline=None, touched=None):
    """runs: [(text, size, color, gap), ...] 以同一条基线居中对齐绘制。"""
    total = 0.0
    widths = []
    for text, size, _color, gap in runs:
        w, _t, _b = _metrics(text, size)
        widths.append(w)
        total += w + gap
    if baseline is None:
        top = 0.0
        bottom = 0.0
        for text, size, _color, _gap in runs:
            _w, t, b = _metrics(text, size)
            top = max(top, t)
            bottom = min(bottom, b)
        baseline = center_y + (top + bottom) / 2.0
    x = center_x - total / 2.0
    for (text, size, color, gap), w in zip(runs, widths):
        draw_text(buf, text, size, x, baseline, color, touched=touched)
        x += w + gap
    return total


# --------------------------------------------------------------------------
# 矢量绘制（AA）
# --------------------------------------------------------------------------

def fill_rounded_rect(buf, x0, y0, x1, y1, radius, color, touched=None):
    r, g, b = color
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    half_w = (x1 - x0) / 2.0
    half_h = (y1 - y0) / 2.0
    rad = min(radius, half_w, half_h)
    ix = half_w - rad
    iy = half_h - rad
    for py in range(max(0, int(y0) - 1), min(CANVAS, int(y1) + 2)):
        ay = abs(py + 0.5 - cy) - iy
        row_drawn = False
        for px in range(max(0, int(x0) - 1), min(CANVAS, int(x1) + 2)):
            ax = abs(px + 0.5 - cx) - ix
            if ax <= 0 and ay <= 0:
                cov = 1.0
            else:
                ox = ax if ax > 0 else 0.0
                oy = ay if ay > 0 else 0.0
                inner = ax if ax > ay else ay
                if inner > 0:
                    inner = 0.0
                # 标准圆角矩形 SDF
                cov = 0.5 - (math.hypot(ox, oy) + inner - rad)
                if cov <= 0:
                    continue
                if cov > 1:
                    cov = 1.0
            row_drawn = True
            idx = (py * CANVAS + px) * 3
            if cov >= 1.0:
                buf[idx] = r
                buf[idx + 1] = g
                buf[idx + 2] = b
            else:
                af = int(cov * 255)
                inv = 255 - af
                buf[idx] = (buf[idx] * inv + r * af) // 255
                buf[idx + 1] = (buf[idx + 1] * inv + g * af) // 255
                buf[idx + 2] = (buf[idx + 2] * inv + b * af) // 255
        if row_drawn and touched is not None:
            touched.add(py)


def fill_circle(buf, cx, cy, radius, color, touched=None):
    fill_rounded_rect(buf, cx - radius, cy - radius, cx + radius, cy + radius, radius, color, touched)


# --------------------------------------------------------------------------
# 背景（渐变 + 薄荷光斑，只算一次）
# --------------------------------------------------------------------------

def _background():
    global _bg
    if _bg is not None:
        return _bg
    buf = bytearray(CANVAS * CANVAS * 3)
    for y in range(CANVAS):
        t = y / (CANVAS - 1)
        row = bytes((
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
        )) * CANVAS
        buf[y * STRIDE:(y + 1) * STRIDE] = row

    bcx, bcy, brad = 450.0, 430.0, 430.0
    x_lo = max(0, int(bcx - brad))
    x_hi = min(CANVAS, int(bcx + brad) + 1)
    y_lo = max(0, int(bcy - brad))
    y_hi = min(CANVAS, int(bcy + brad) + 1)
    for y in range(y_lo, y_hi):
        dy = y + 0.5 - bcy
        base = y * CANVAS * 3
        for x in range(x_lo, x_hi):
            dx = x + 0.5 - bcx
            d = math.sqrt(dx * dx + dy * dy) / brad
            if d >= 1.0:
                continue
            a = 0.5 * (1.0 - d) ** 1.7
            af = int(a * 255)
            if af <= 0:
                continue
            inv = 255 - af
            idx = base + x * 3
            buf[idx] = (buf[idx] * inv + BLOB[0] * af) // 255
            buf[idx + 1] = (buf[idx + 1] * inv + BLOB[1] * af) // 255
            buf[idx + 2] = (buf[idx + 2] * inv + BLOB[2] * af) // 255

    rows = [bytes(buf[y * STRIDE:(y + 1) * STRIDE]) for y in range(CANVAS)]
    filt = []
    prev = bytes(STRIDE)
    for row in rows:
        filt.append(bytes([(a - b) & 255 for a, b in zip(row, prev)]))
        prev = row
    _bg = (bytes(buf), rows, filt)
    return _bg


# --------------------------------------------------------------------------
# PNG 编码（filter 0 / Up 混合，脏行才重算）
# --------------------------------------------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(buf, touched=None) -> bytes:
    _bg_bytes, bg_rows, bg_filt = _background()
    dirty = touched or set()
    if dirty:
        recompute = dirty | {y + 1 for y in dirty}
    else:
        recompute = set(range(CANVAS))
    raw = bytearray()
    for y in range(CANVAS):
        row = bytes(buf[y * STRIDE:(y + 1) * STRIDE])
        if y == 0 or y in recompute:
            raw.append(0)
            raw.extend(row)
        else:
            raw.append(2)
            raw.extend(bg_filt[y])
    ihdr = struct.pack(">IIBBBBB", CANVAS, CANVAS, 8, 2, 0, 0, 0)
    body = zlib.compress(bytes(raw), 9)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", body) + _chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# 卡片排版
# --------------------------------------------------------------------------

def compose(plan, label: str) -> tuple:
    """plan: [(value, unit), ...]，第一项作主视觉，其余作次级行。"""
    buf = bytearray(_background()[0])
    touched = set()

    # 品牌区
    fill_rounded_rect(buf, 72, 64, 160, 152, 28, INK, touched)
    draw_text(buf, "计", TITLE_SIZE, 0, 0, PAPER, center_x=116, center_y=108, touched=touched)
    draw_text(buf, "TIME TO GO", EYEBROW_SIZE, 184, 0, INK_FAINT, tracking=5.0,
              center_y=92, touched=touched)
    draw_text(buf, "上学倒计时", TITLE_SIZE, 184, 0, INK, center_y=128, touched=touched)

    # 主视觉：最大非零单位
    hero_value, hero_unit = plan[0]
    hero = "%02d" % hero_value
    hero_w, _ht, _hb = _metrics(hero, HERO_SIZE)
    unit_w, _ut, _ub = _metrics(hero_unit, HERO_UNIT_SIZE)
    gap = 12.0
    left = (CANVAS - (hero_w + gap + unit_w)) / 2.0
    baseline = 486.0
    draw_text(buf, hero, HERO_SIZE, left, baseline, INK, touched=touched)
    draw_text(buf, hero_unit, HERO_UNIT_SIZE, left + hero_w + gap, baseline, INK_SOFT,
              touched=touched)

    # 次级单位（最多两项）；没有次级单位时不画分隔线，避免线悬空
    runs = []
    for value, unit in plan[1:]:
        runs.append(("%02d" % value, ROW_SIZE, INK, 10))
        runs.append((unit, ROW_UNIT_SIZE, INK_FAINT, 34))
    if runs:
        fill_rounded_rect(buf, 176, 574, 724, 576, 1, LINE, touched)
        text, size, color, _gap = runs[-1]
        runs[-1] = (text, size, color, 0)
        draw_runs(buf, runs, center_y=660, touched=touched)

    # 目标时间
    dot_r = 7.0
    label_w, _lt, _lb = _metrics("目标 " + label, 30)
    total_w = dot_r * 2 + 16 + label_w
    start = (CANVAS - total_w) / 2.0
    fill_circle(buf, start + dot_r, 812, dot_r, ACCENT, touched)
    draw_text(buf, "目标 " + label, 30, start + dot_r * 2 + 16, 0, INK_SOFT,
              center_y=812, touched=touched)

    return buf, touched


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------

def render_png(now: datetime | None = None) -> bytes:
    now = now or datetime.now(timezone.utc)
    target = next_target(now)
    countdown = split_countdown(target, now)
    label = target_label(target)
    key = countdown + (label,)
    cached = _png_cache.get(key)
    if cached is None:
        plan = build_plan(*countdown)
        buf, touched = compose(plan, label)
        cached = encode_png(buf, touched)
        if len(_png_cache) > 32:
            _png_cache.clear()
        _png_cache[key] = cached
    return cached


def render_meta(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    target = next_target(now)
    days, hours, minutes, seconds = split_countdown(target, now)
    plan = build_plan(days, hours, minutes, seconds)
    return {
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "plan": plan,
        "label": target_label(target),
        "head": plan_head(plan),
        "cache_key": "%dd%02dh%02d" % (days, hours, minutes),
    }


GLYPH_PAYLOAD = "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"


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
