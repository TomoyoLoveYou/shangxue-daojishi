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


def build_static_js():
    """把静态资源内联进 Worker，这样不依赖平台的静态资源行为，部署更稳。"""
    entries = []
    mimes = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
    for name in STATIC_FILES:
        ext = os.path.splitext(name)[1].lower()
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            text = fh.read()
        entries.append("  %s: { type: %s, text: %s },"
                       % (json.dumps("/" + name), json.dumps(mimes[ext]), json.dumps(text)))
    with open(os.path.join(ROOT, "assets", "share-cover.png"), "rb") as fh:
        png = base64.b64encode(fh.read()).decode("ascii")
    entries.append('  "/assets/share-cover.png": { type: "image/png", base64: %s },'
                   % json.dumps(png))

    content = (
        "// 由 tools/build_cloudflare.py 生成，请勿手改\n"
        "// 内联的静态资源（styles.css / app.js / 兜底封面图）\n\n"
        "export const STATIC_ASSETS = {\n" + "\n".join(entries) + "\n};\n"
    )
    path = os.path.join(CLOUDFLARE, "src", "static.js")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path


PAGES_WORKER_JS = """// 由 tools/build_cloudflare.py 生成，请勿手改
//
// Cloudflare Pages 高级模式入口：目录里放 _worker.js 时，
// 所有请求都交给这个 Worker 处理（静态资源也要自己吐）。
// 这里直接复用 Workers 版的实现，两者请求/响应模型一致。

export { default } from './worker.js';
"""


def build_pages_dist():
    """生成可直接 `wrangler pages deploy` 的目录。

    注意：Pages 的 *.pages.dev 在大陆可访问，而 Workers 的 *.workers.dev 被 DNS 污染，
    所以对外发布走 Pages 这条路。
    """
    dist = os.path.join(CLOUDFLARE, "dist")
    if os.path.isdir(dist):
        shutil.rmtree(dist)
    os.makedirs(os.path.join(dist, "assets"), exist_ok=True)

    # 代码模块
    src_dir = os.path.join(CLOUDFLARE, "src")
    for name in ("worker.js", "card.js", "meta.js", "glyphs.js", "page.js", "static.js"):
        shutil.copyfile(os.path.join(src_dir, name), os.path.join(dist, name))

    # 静态资源（同内容也内联在 Worker 里，双保险）
    for name in STATIC_FILES:
        shutil.copyfile(os.path.join(ROOT, name), os.path.join(dist, name))
    shutil.copyfile(os.path.join(ROOT, "assets", "share-cover.png"),
                    os.path.join(dist, "assets", "share-cover.png"))

    # Pages 入口
    with open(os.path.join(dist, "_worker.js"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(PAGES_WORKER_JS)

    # 让本地 Node 能直接 import 这些 .js（Cloudflare 会忽略它）
    with open(os.path.join(dist, "package.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{\n  "private": true,\n  "type": "module"\n}\n')

    return dist


def main():
    for sub in ("src", "public"):
        os.makedirs(os.path.join(CLOUDFLARE, sub), exist_ok=True)

    path, raw_len, packed_len = build_glyphs_js()
    print("written: %s  (原始 %.1f KB -> 打包 %.1f KB)"
          % (path, raw_len / 1024.0, packed_len / 1024.0))
    print("written: %s" % build_page_js())
    print("written: %s" % build_static_js())
    for path in copy_static():
        print("copied : %s" % path)

    dist = build_pages_dist()
    total = 0
    for dirpath, _dirnames, filenames in os.walk(dist):
        for name in filenames:
            total += os.path.getsize(os.path.join(dirpath, name))
    print("written: %s  (Pages 部署目录，共 %.1f KB)" % (dist, total / 1024.0))


if __name__ == "__main__":
    main()
