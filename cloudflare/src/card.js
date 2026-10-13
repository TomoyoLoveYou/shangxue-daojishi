/**
 * 上学倒计时 —— 分享卡片图渲染器（纯 Web 标准 API）。
 *
 * 与 Python 版 ogcard.py 逐像素对齐：字形蒙版由 tools/build_glyphs.py 预生成，
 * 这里只做「蒙版合成 + PNG 编码」，不依赖任何第三方库，
 * 因此 Cloudflare Workers 与本地 Node 18+ 都能直接跑。
 */

export const CANVAS = 900;
const STRIDE = CANVAS * 3;

const INK = [24, 55, 45];
const INK_SOFT = [101, 128, 117];
const INK_FAINT = [148, 169, 159];
const PAPER = [255, 255, 255];
const LINE = [220, 232, 223];
const ACCENT = [237, 138, 85];
const BG_TOP = [245, 248, 246];
const BG_BOTTOM = [228, 239, 233];
const BLOB = [207, 226, 215];

const HERO_SIZE = 300;
const HERO_UNIT_SIZE = 56;
const ROW_SIZE = 76;
const ROW_UNIT_SIZE = 22;
const LINE_SIZE = 30;
const TITLE_SIZE = 44;
const EYEBROW_SIZE = 20;

const BEIJING_OFFSET = 8 * 3600 * 1000;
const TARGET_HOUR = 18;
const TARGET_MINUTE = 35;
const WEEKDAY_CN = ['一', '二', '三', '四', '五', '六', '日'];
const LONG_UNIT = { 天: '天', 时: '小时', 分: '分', 秒: '秒' };

// ---------------------------------------------------------------------------
// 倒计时（与前端 app.js 的默认目标一致：北京时间下个周日 18:35）
// ---------------------------------------------------------------------------

function beijingParts(ms) {
  const d = new Date(ms + BEIJING_OFFSET);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    second: d.getUTCSeconds(),
    weekday: (d.getUTCDay() + 6) % 7, // 0 = 周一
  };
}

export function nextTarget(ms) {
  const p = beijingParts(ms);
  const today = Date.UTC(p.year, p.month - 1, p.day, TARGET_HOUR - 8, TARGET_MINUTE, 0, 0);
  let days = (6 - p.weekday + 7) % 7;
  if (days === 0 && ms >= today) days = 7;
  return today + days * 86400000;
}

export function splitCountdown(target, ms) {
  const total = Math.max(0, Math.floor((target - ms) / 1000));
  return [
    Math.floor(total / 86400),
    Math.floor((total % 86400) / 3600),
    Math.floor((total % 3600) / 60),
    total % 60,
  ];
}

export function targetLabel(target) {
  const p = beijingParts(target);
  const pad = (n) => String(n).padStart(2, '0');
  return `${p.month}月${p.day}日 周${WEEKDAY_CN[p.weekday]} ${pad(p.hour)}:${pad(p.minute)}`;
}

export function buildPlan(days, hours, minutes, seconds) {
  const pairs = [[days, '天'], [hours, '时'], [minutes, '分'], [seconds, '秒']];
  let idx = 0;
  while (idx < pairs.length - 1 && pairs[idx][0] === 0) idx += 1;
  return pairs.slice(idx, idx + 3);
}

export function planHead(plan) {
  return '还有 ' + plan.slice(0, 2).map(([v, u]) => `${v} ${LONG_UNIT[u]}`).join(' ');
}

// ---------------------------------------------------------------------------
// 数据解包
// ---------------------------------------------------------------------------

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function deflate(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

let glyphPromise = null;

export function ensureGlyphs(b64) {
  if (!glyphPromise) glyphPromise = decodeGlyphs(b64);
  return glyphPromise;
}

async function decodeGlyphs(b64) {
  const json = JSON.parse(new TextDecoder().decode(await inflate(b64ToBytes(b64))));
  const sizes = {};
  for (const key of Object.keys(json.sizes)) {
    const table = json.sizes[key];
    const out = {};
    for (const ch of Object.keys(table)) {
      const info = table[ch];
      out[ch] = {
        adv: info.adv,
        left: info.left,
        top: info.top,
        h: info.h,
        rows: info.rows.map((r) => [r[0], r[1], b64ToBytes(r[2])]),
      };
    }
    sizes[Number(key)] = out;
  }
  return sizes;
}

// ---------------------------------------------------------------------------
// 绘制
// ---------------------------------------------------------------------------

/** Python 的 round() 是「四舍六入五取偶」，这里保持一致以免像素错位。 */
function pyRound(v) {
  const f = Math.floor(v);
  const diff = v - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

function metrics(sizes, text, size) {
  const table = sizes[size];
  let top = 0;
  let bottom = 0;
  let width = 0;
  for (const ch of text) {
    const g = table[ch] || table[' '];
    if (!g) continue;
    width += g.adv;
    if (g.h) {
      top = Math.max(top, g.top);
      bottom = Math.min(bottom, g.top - g.h);
    }
  }
  return [width, top, bottom];
}

function blit(buf, x, y, glyph, color, touched) {
  const [cr, cg, cb] = color;
  for (const [dy, x0, row] of glyph.rows) {
    const py = y + dy;
    if (py < 0 || py >= CANVAS) continue;
    let gx = x + x0;
    let start = 0;
    let end = row.length;
    if (gx < 0) {
      start = -gx;
      gx = 0;
    }
    if (gx + (end - start) > CANVAS) end = start + (CANVAS - gx);
    if (end <= start) continue;
    let idx = (py * CANVAS + gx) * 3;
    for (let i = start; i < end; i += 1) {
      const a = row[i];
      if (a) {
        const inv = 255 - a;
        buf[idx] = (buf[idx] * inv + cr * a) / 255 | 0;
        buf[idx + 1] = (buf[idx + 1] * inv + cg * a) / 255 | 0;
        buf[idx + 2] = (buf[idx + 2] * inv + cb * a) / 255 | 0;
      }
      idx += 3;
    }
    if (touched) touched.add(py);
  }
}

function drawText(buf, sizes, text, size, x, baseline, color, opts = {}) {
  const { tracking = 0, centerX = null, centerY = null, touched = null } = opts;
  const [width, top, bottom] = metrics(sizes, text, size);
  let px = x;
  let by = baseline;
  if (centerX !== null) px = centerX - width / 2;
  if (centerY !== null) by = centerY + (top + bottom) / 2;
  const table = sizes[size];
  let pen = px;
  for (const ch of text) {
    const g = table[ch] || table[' '];
    if (g) {
      if (g.rows.length) {
        blit(buf, pyRound(pen + g.left), pyRound(by - g.top), g, color, touched);
      }
      pen += g.adv + tracking;
    }
  }
  return width;
}

function drawRuns(buf, sizes, runs, centerX, centerY, touched) {
  let total = 0;
  const widths = [];
  for (const [text, size, , gap] of runs) {
    const [w] = metrics(sizes, text, size);
    widths.push(w);
    total += w + gap;
  }
  let top = 0;
  let bottom = 0;
  for (const [text, size] of runs) {
    const [, t, b] = metrics(sizes, text, size);
    top = Math.max(top, t);
    bottom = Math.min(bottom, b);
  }
  const baseline = centerY + (top + bottom) / 2;
  let x = centerX - total / 2;
  for (let i = 0; i < runs.length; i += 1) {
    drawText(buf, sizes, runs[i][0], runs[i][1], x, baseline, runs[i][2], { touched });
    x += widths[i] + runs[i][3];
  }
  return total;
}

function fillRoundedRect(buf, x0, y0, x1, y1, radius, color, touched) {
  const [cr, cg, cb] = color;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const halfW = (x1 - x0) / 2;
  const halfH = (y1 - y0) / 2;
  const rad = Math.min(radius, halfW, halfH);
  const ix = halfW - rad;
  const iy = halfH - rad;
  const yStart = Math.max(0, Math.trunc(y0) - 1);
  const yEnd = Math.min(CANVAS, Math.trunc(y1) + 2);
  const xStart = Math.max(0, Math.trunc(x0) - 1);
  const xEnd = Math.min(CANVAS, Math.trunc(x1) + 2);
  for (let py = yStart; py < yEnd; py += 1) {
    const ay = Math.abs(py + 0.5 - cy) - iy;
    let rowDrawn = false;
    for (let px = xStart; px < xEnd; px += 1) {
      const ax = Math.abs(px + 0.5 - cx) - ix;
      let cov;
      if (ax <= 0 && ay <= 0) {
        cov = 1;
      } else {
        const ox = ax > 0 ? ax : 0;
        const oy = ay > 0 ? ay : 0;
        let inner = ax > ay ? ax : ay;
        if (inner > 0) inner = 0;
        cov = 0.5 - (Math.hypot(ox, oy) + inner - rad);
        if (cov <= 0) continue;
        if (cov > 1) cov = 1;
      }
      rowDrawn = true;
      const idx = (py * CANVAS + px) * 3;
      if (cov >= 1) {
        buf[idx] = cr;
        buf[idx + 1] = cg;
        buf[idx + 2] = cb;
      } else {
        const af = (cov * 255) | 0;
        const inv = 255 - af;
        buf[idx] = (buf[idx] * inv + cr * af) / 255 | 0;
        buf[idx + 1] = (buf[idx + 1] * inv + cg * af) / 255 | 0;
        buf[idx + 2] = (buf[idx + 2] * inv + cb * af) / 255 | 0;
      }
    }
    if (rowDrawn && touched) touched.add(py);
  }
}

function fillCircle(buf, cx, cy, radius, color, touched) {
  fillRoundedRect(buf, cx - radius, cy - radius, cx + radius, cy + radius, radius, color, touched);
}

// ---------------------------------------------------------------------------
// 背景（渐变 + 薄荷光斑，每个 isolate 只算一次）
// ---------------------------------------------------------------------------

let backgroundCache = null;

export function ensureBackground() {
  if (!backgroundCache) backgroundCache = buildBackground();
  return backgroundCache;
}

function buildBackground() {
  const buf = new Uint8Array(CANVAS * STRIDE);
  for (let y = 0; y < CANVAS; y += 1) {
    const t = y / (CANVAS - 1);
    const r = Math.trunc(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t);
    const g = Math.trunc(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t);
    const b = Math.trunc(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t);
    let idx = y * STRIDE;
    for (let x = 0; x < CANVAS; x += 1) {
      buf[idx] = r;
      buf[idx + 1] = g;
      buf[idx + 2] = b;
      idx += 3;
    }
  }

  const bcx = 450;
  const bcy = 430;
  const brad = 430;
  const xLo = Math.max(0, Math.trunc(bcx - brad));
  const xHi = Math.min(CANVAS, Math.trunc(bcx + brad) + 1);
  const yLo = Math.max(0, Math.trunc(bcy - brad));
  const yHi = Math.min(CANVAS, Math.trunc(bcy + brad) + 1);
  for (let y = yLo; y < yHi; y += 1) {
    const dy = y + 0.5 - bcy;
    const base = y * CANVAS * 3;
    for (let x = xLo; x < xHi; x += 1) {
      const dx = x + 0.5 - bcx;
      const d = Math.sqrt(dx * dx + dy * dy) / brad;
      if (d >= 1) continue;
      const af = (0.5 * Math.pow(1 - d, 1.7) * 255) | 0;
      if (af <= 0) continue;
      const inv = 255 - af;
      const idx = base + x * 3;
      buf[idx] = (buf[idx] * inv + BLOB[0] * af) / 255 | 0;
      buf[idx + 1] = (buf[idx + 1] * inv + BLOB[1] * af) / 255 | 0;
      buf[idx + 2] = (buf[idx + 2] * inv + BLOB[2] * af) / 255 | 0;
    }
  }

  const rows = new Array(CANVAS);
  const filt = new Array(CANVAS);
  let prev = new Uint8Array(STRIDE);
  for (let y = 0; y < CANVAS; y += 1) {
    const row = buf.slice(y * STRIDE, (y + 1) * STRIDE);
    const f = new Uint8Array(STRIDE);
    for (let i = 0; i < STRIDE; i += 1) f[i] = (row[i] - prev[i]) & 255;
    rows[y] = row;
    filt[y] = f;
    prev = row;
  }
  return { buf, rows, filt };
}

// ---------------------------------------------------------------------------
// PNG 编码
// ---------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const out = new Uint8Array(12 + data.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, data.length);
  for (let i = 0; i < 4; i += 1) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  view.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}

function concat(parts) {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

async function encodePng(buf, touched, bgFilt) {
  const recompute = new Set(touched || []);
  for (const y of touched || []) recompute.add(y + 1);
  const raw = new Uint8Array(CANVAS * (STRIDE + 1));
  let off = 0;
  for (let y = 0; y < CANVAS; y += 1) {
    const dirty = y === 0 || recompute.has(y);
    raw[off] = dirty ? 0 : 2;
    off += 1;
    if (dirty) {
      raw.set(buf.subarray(y * STRIDE, (y + 1) * STRIDE), off);
    } else {
      raw.set(bgFilt[y], off);
    }
    off += STRIDE;
  }
  const idat = await deflate(raw);
  const ihdr = new Uint8Array(13);
  const view = new DataView(ihdr.buffer);
  view.setUint32(0, CANVAS);
  view.setUint32(4, CANVAS);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return concat([
    new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', idat),
    chunk('IEND', new Uint8Array(0)),
  ]);
}

// ---------------------------------------------------------------------------
// 卡片排版
// ---------------------------------------------------------------------------

function compose(plan, label, sizes, bg) {
  const buf = bg.buf.slice();
  const touched = new Set();

  // 品牌区
  fillRoundedRect(buf, 72, 64, 160, 152, 28, INK, touched);
  drawText(buf, sizes, '计', TITLE_SIZE, 0, 0, PAPER, { centerX: 116, centerY: 108, touched });
  drawText(buf, sizes, 'TIME TO GO', EYEBROW_SIZE, 184, 0, INK_FAINT, { tracking: 5, centerY: 92, touched });
  drawText(buf, sizes, '上学倒计时', TITLE_SIZE, 184, 0, INK, { centerY: 128, touched });

  // 主视觉：最大非零单位
  const [heroValue, heroUnit] = plan[0];
  const hero = String(heroValue).padStart(2, '0');
  const [heroW] = metrics(sizes, hero, HERO_SIZE);
  const [unitW] = metrics(sizes, heroUnit, HERO_UNIT_SIZE);
  const gap = 12;
  const left = (CANVAS - (heroW + gap + unitW)) / 2;
  const baseline = 486;
  drawText(buf, sizes, hero, HERO_SIZE, left, baseline, INK, { touched });
  drawText(buf, sizes, heroUnit, HERO_UNIT_SIZE, left + heroW + gap, baseline, INK_SOFT, { touched });

  // 次级单位（最多两项）；没有次级单位时不画分隔线，避免线悬空
  const runs = [];
  for (const [value, unit] of plan.slice(1)) {
    runs.push([String(value).padStart(2, '0'), ROW_SIZE, INK, 10]);
    runs.push([unit, ROW_UNIT_SIZE, INK_FAINT, 34]);
  }
  if (runs.length) {
    fillRoundedRect(buf, 176, 574, 724, 576, 1, LINE, touched);
    runs[runs.length - 1][3] = 0;
    drawRuns(buf, sizes, runs, CANVAS / 2, 660, touched);
  }

  // 目标时间
  const dotR = 7;
  const target = '目标 ' + label;
  const [labelW] = metrics(sizes, target, LINE_SIZE);
  const totalW = dotR * 2 + 16 + labelW;
  const start = (CANVAS - totalW) / 2;
  fillCircle(buf, start + dotR, 812, dotR, ACCENT, touched);
  drawText(buf, sizes, target, LINE_SIZE, start + dotR * 2 + 16, 0, INK_SOFT, { centerY: 812, touched });

  return { buf, touched };
}

const pngCache = new Map();

export async function renderCardPng(ms, sizes, bg) {
  const target = nextTarget(ms);
  const countdown = splitCountdown(target, ms);
  const label = targetLabel(target);
  const key = countdown.join('-') + '|' + label;
  const cached = pngCache.get(key);
  if (cached) return cached;
  const plan = buildPlan(...countdown);
  const { buf, touched } = compose(plan, label, sizes, bg);
  const png = await encodePng(buf, touched, bg.filt);
  if (pngCache.size > 32) pngCache.clear();
  pngCache.set(key, png);
  return png;
}
