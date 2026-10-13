"""生成 Cloudflare Worker 项目所需的产物（本地运行）。

产物：
    cloudflare/src/glyphs.js      字形数据（已裁剪行 + 整体 zlib 压缩 + base64）
    cloudflare/src/page.js        页面 HTML 模板（从 page.html 生成）
    cloudflare/public/*           静态资源副本（styles.css / app.js / assets/share-cover.png）

用法：python tools/build_cloudflare.py
"""

import base64
import json
import os
import shutil
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import ogcard

CLOUDFLARE = os.path.join(ROOT, "cloudflare")
STATIC_FILES = ("styles.css", "app.js")


def build_glyphs():
    """把字形蒙版裁剪成逐行的紧凑结构，整体压缩后交给 JS 端一次性解压。"""
    sizes = ogcard._load_glyphs()
    out = {"sizes": {}}
    for size, table in sizes.items():
        glyphs = {}
        for ch, glyph in table.items():
            glyphs[ch] = {
                "adv": glyph["adv"],
                "left": glyph["left"],
                "top": glyph["top"],
                "h": glyph["h"],
                "rows": [[dy, x0, base64.b64encode(row).decode("ascii")]
                         for dy, x0, row in glyph["rows"]],
            }
        out["sizes"][str(size)] = glyphs
    raw = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    return packed, len(raw), len(packed)


def build_glyphs_js():
    packed, raw_len, packed_len = build_glyphs()
    content = (
        "// 由 tools/build_cloudflare.py 生成，请勿手改\n"
        "// 字形蒙版：逐行裁剪后的 alpha 数据，整体 zlib 压缩再 base64\n\n"
        'export const GLYPHS_B64 =\n  "%s";\n' % packed
    )
    path = os.path.join(CLOUDFLARE, "src", "glyphs.js")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path, raw_len, packed_len


def build_page_js():
    with open(os.path.join(ROOT, "page.html"), encoding="utf-8") as fh:
        page = fh.read()
    content = (
        "// 由 tools/build_cloudflare.py 生成，请勿手改\n"
        "// 页面模板，来自 page.html\n\n"
        "export const PAGE_HTML = %s;\n" % json.dumps(page, ensure_ascii=False)
    )
    path = os.path.join(CLOUDFLARE, "src", "page.js")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path


def copy_static():
    public = os.path.join(CLOUDFLARE, "public")
    os.makedirs(os.path.join(public, "assets"), exist_ok=True)
    copied = []
    for name in STATIC_FILES:
        dst = os.path.join(public, name)
        shutil.copyfile(os.path.join(ROOT, name), dst)
        copied.append(dst)
    dst = os.path.join(public, "assets", "share-cover.png")
    shutil.copyfile(os.path.join(ROOT, "assets", "share-cover.png"), dst)
    copied.append(dst)
    return copied


def main():
    for sub in ("src", "public"):
        os.makedirs(os.path.join(CLOUDFLARE, sub), exist_ok=True)

    path, raw_len, packed_len = build_glyphs_js()
    print("written: %s  (原始 %.1f KB -> 打包 %.1f KB)"
          % (path, raw_len / 1024.0, packed_len / 1024.0))
    print("written: %s" % build_page_js())
    for path in copy_static():
        print("copied : %s" % path)


if __name__ == "__main__":
    main()
