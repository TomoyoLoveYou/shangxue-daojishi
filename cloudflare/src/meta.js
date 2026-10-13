/**
 * 页面 + 分享卡片元信息。
 *
 * 微信只读服务端返回的 HTML，所以 og:* 必须按请求现算——
 * 这要求 / 由 Worker 接管，public/ 里不能放 index.html。
 */

import { nextTarget, splitCountdown, targetLabel, buildPlan, planHead } from './card.js';

const OG_BEGIN = '<!-- og:begin -->';
const OG_END = '<!-- og:end -->';

const pad = (n) => String(n).padStart(2, '0');

export function renderHtml(template, origin, ms) {
  const target = nextTarget(ms);
  const countdown = splitCountdown(target, ms);
  const plan = buildPlan(...countdown);
  const label = targetLabel(target);

  const title = '上学倒计时 · ' + planHead(plan);
  const desc = `目标 ${label} · 北京时间，点开查看秒级倒计时`;
  // 带上倒计时状态做缓存键：微信按 URL 缓存图片，URL 变了才会重新抓
  const image = `${origin}/og?v=${countdown[0]}d${pad(countdown[1])}h${pad(countdown[2])}`;
  const pageUrl = `${origin}/`;

  const block = [
    OG_BEGIN,
    `    <meta name="description" content="${desc}" />`,
    '    <meta property="og:type" content="website" />',
    '    <meta property="og:site_name" content="上学倒计时" />',
    `    <meta property="og:title" content="${title}" />`,
    `    <meta property="og:description" content="${desc}" />`,
    `    <meta property="og:image" content="${image}" />`,
    '    <meta property="og:image:type" content="image/png" />',
    '    <meta property="og:image:width" content="900" />',
    '    <meta property="og:image:height" content="900" />',
    `    <meta property="og:url" content="${pageUrl}" />`,
    '    <meta name="twitter:card" content="summary" />',
    OG_END,
  ].join('\n');

  const start = template.indexOf(OG_BEGIN);
  const end = template.indexOf(OG_END);
  if (start < 0 || end <= start) return template;
  return template.slice(0, start) + block + template.slice(end + OG_END.length);
}
