"""预生成分享卡片所需的字形蒙版。

只在开发机运行（需要 Pillow）。产物 assets/glyphs.json 随仓库提交，
线上运行时不需要 Pillow。

用法:
    python tools/build_glyphs.py
"""

import base64
import json
import os
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ogcard

FONT_CJK = "C:/Windows/Fonts/msyhbd.ttc"
FONT_MONO = "C:/Windows/Fonts/consola.ttf"


def render_glyph(font, ch):
    """返回 (Image, left, top)。

    Pillow 默认以「ascender 左上角」为原点布局，而卡片渲染需要以「基线」为参照，
    因此用 font.getmetrics() 的 ascent 把偏移换算到基线（top 为墨迹顶到基线的距离）。
    """
    ascent, _descent = font.getmetrics()
    x0, y0, x1, y1 = font.getbbox(ch)
    if x1 <= x0 or y1 <= y0:
        return None
    pad = 4
    img = Image.new("L", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), 0)
    ImageDraw.Draw(img).text((pad - x0, pad - y0), ch, font=font, fill=255)
    tight = img.getbbox()
    if tight is None:
        return None
    img = img.crop(tight)
    left = tight[0] - pad + x0
    top = ascent + pad - y0 - tight[1]
    return img, left, top


def main():
    out = {"sizes": {}}
    for size in sorted(ogcard.GLYPH_SPEC):
        chars = ogcard.GLYPH_SPEC[size]
        path = FONT_MONO if size in ogcard.MONO_SIZES else FONT_CJK
        font = ImageFont.truetype(path, size)
        glyphs = {}
        for ch in chars + " ":
            advance = round(font.getlength(ch), 2)
            result = render_glyph(font, ch)
            if result is None:
                glyphs[ch] = {"w": 0, "h": 0, "left": 0, "top": 0,
                              "adv": advance, "mask": ""}
                continue
            img, left, top = result
            raw = img.tobytes()
            glyphs[ch] = {
                "w": img.width,
                "h": img.height,
                "left": round(left, 2),
                "top": round(top, 2),
                "adv": advance,
                "mask": base64.b64encode(zlib.compress(raw, 9)).decode("ascii"),
            }
        out["sizes"][str(size)] = glyphs

    path = os.path.join(ROOT, "assets", "glyphs.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print("written: %s  (%.1f KB)" % (path, os.path.getsize(path) / 1024.0))


if __name__ == "__main__":
    main()
