/**
 * Worker 入口（Workers 与 Pages 通用）。
 *
 *   GET /        -> 按当前倒计时注入 og:* 元信息后的页面
 *   GET /og      -> 实时渲染的分享卡片图（900x900 PNG）
 *   其他路径      -> 内联的静态资源（styles.css / app.js / 兜底封面图）
 *
 * 静态资源是内联在 Worker 里的，不依赖平台的静态资源行为，
 * 所以不用担心"静态文件优先于 Worker"把 / 抢走的问题。
 */

import { GLYPHS_B64 } from './glyphs.js';
import { PAGE_HTML } from './page.js';
import { STATIC_ASSETS } from './static.js';
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

/**
 * 解析分享链接里的自定义目标（?t=毫秒时间戳）。
 * 限定在「1 天前 ~ 2 年后」这个合理区间，避免被乱填导致生成奇怪卡片。
 */
function parseCustomTarget(raw) {
  if (!raw) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  const now = Date.now();
  if (value < now - 86400000 || value > now + 730 * 86400000) return null;
  return Math.floor(value);
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

const assetCache = new Map();

function localAsset(pathname) {
  const entry = STATIC_ASSETS[pathname];
  if (!entry) return null;
  let body = assetCache.get(pathname);
  if (body === undefined) {
    body = entry.text !== undefined ? entry.text : b64ToBytes(entry.base64);
    assetCache.set(pathname, body);
  }
  return new Response(body, {
    headers: {
      'Content-Type': entry.type,
      'Cache-Control': 'public, max-age=3600',
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const headOnly = request.method === 'HEAD';
    const customTarget = parseCustomTarget(url.searchParams.get('t'));

    if (url.pathname === '/og') {
      let response;
      try {
        const { sizes, bg } = await prepare();
        const png = await renderCardPng(Date.now(), sizes, bg, customTarget);
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
      const html = renderHtml(PAGE_HTML, url.origin, Date.now(), customTarget);
      const response = new Response(html, {
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        },
      });
      return headOnly ? withoutBody(response) : response;
    }

    const local = localAsset(url.pathname);
    if (local) return headOnly ? withoutBody(local) : local;

    if (env && env.ASSETS) return env.ASSETS.fetch(request);
    return new Response('Not Found', { status: 404 });
  },
};
