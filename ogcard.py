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
    LINE_SIZE: "0123456789:目标月日周一二三四五六",
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


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "preview.png"
    data = render_png()
    with open(out, "wb") as fh:
        fh.write(data)
    meta = render_meta()
    print("%s  %.1f KB  %s" % (out, len(data) / 1024.0, meta))
