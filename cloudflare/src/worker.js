/**
 * Cloudflare Worker 入口。
 *
 *   GET /        -> 按当前倒计时注入 og:* 元信息后的页面
 *   GET /og      -> 实时渲染的分享卡片图（900x900 PNG）
 *   其他路径      -> public/ 里的静态资源（styles.css / app.js / assets/*）
 *
 * 注意：public/ 里不要放 index.html —— 静态资源优先于 Worker，
 * 否则 / 会被静态文件接管，动态的卡片信息就失效了。
 */

import { GLYPHS_B64 } from './glyphs.js';
import { PAGE_HTML } from './page.js';
import { ensureGlyphs, ensureBackground, renderCardPng } from './card.js';
import { renderHtml } from './meta.js';

let ready = null;

function prepare() {
  if (!ready) {
    ready = (async () => ({
      sizes: await ensureGlyphs(GLYPHS_B64),
      bg: ensureBackground(),
    }))();
  }
  return ready;
}

function withoutBody(response) {
  return new Response(null, { status: response.status, headers: response.headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headOnly = request.method === 'HEAD';

    if (url.pathname === '/og') {
      let response;
      try {
        const { sizes, bg } = await prepare();
        const png = await renderCardPng(Date.now(), sizes, bg);
        response = new Response(png, {
          headers: {
            'Content-Type': 'image/png',
            'Cache-Control': 'public, max-age=300',
            'Referrer-Policy': 'no-referrer',
          },
        });
      } catch (err) {
        // 渲染失败时退回静态封面，保证卡片至少有一张图
        response = Response.redirect(new URL('/assets/share-cover.png', url.origin).toString(), 302);
      }
      return headOnly ? withoutBody(response) : response;
    }

    if (url.pathname === '/') {
      const html = renderHtml(PAGE_HTML, url.origin, Date.now());
      const response = new Response(html, {
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        },
      });
      return headOnly ? withoutBody(response) : response;
    }

    if (env && env.ASSETS) return env.ASSETS.fetch(request);
    return new Response('Not Found', { status: 404 });
  },
};
