# 上学倒计时

一个极简的上学倒计时小站：默认倒数到**北京时间下个周日 18:35**，支持自定义目标时间；
分享到微信时，聊天里会显示一张**带当前倒计时的分享卡片**。

**在线体验：<https://shangxue-daojishi.pages.dev/>**

## 功能

- 秒级倒计时，主视觉按剩余时间**自动切换单位**（天 → 时 → 分 → 秒），
  剩不到一天时也不会出现没意义的「00 天」
- 自定义目标时间，并可通过链接携带（`?t=毫秒时间戳`，对方打开会恢复同一个目标）
- 页面内「分享给好友」按钮：自动给链接加随机参数，并按环境给出分享方式
- 微信卡片三段全动态：`og:title`、`og:description`、`og:image` 都由服务端按当下倒计时现算
- 卡片图是**纯代码绘制**的 900×900 PNG（自实现抗锯齿绘制与 PNG 编码，零第三方依赖）

## 它是怎么工作的

微信分享链接时**只读服务端返回的 HTML**（不执行 JS），并且会按 URL 缓存卡片结果。
所以卡片信息必须在服务端按请求现算，同时分享时要换一个新 URL：

```
点击「分享给好友」
      │  链接变为  /?v=<随机数>&t=<可选的目标时间>
      ▼
微信抓取 ──▶ /              → 现算 og:title / og:description / og:image
            /og?v=…&t=…     → 现算并渲染 900×900 PNG
```

因为每分享一次 URL 都不同，微信会重新抓取，卡片上的倒计时就是**发送那一刻**的时间。

## 项目结构

```
page.html                     页面源码（注意：故意不叫 index.html，原因见下）
styles.css / app.js           样式与交互（倒计时、自定义目标、分享）
assets/glyphs.json            预生成的字形蒙版
tools/build_glyphs.py         用 Pillow 预渲染字形蒙版（仅开发机运行）
tools/build_cloudflare.py     生成 cloudflare/ 下的部署产物

cloudflare/                   ★ 线上版本：Cloudflare Pages（Worker + 静态资源）
  src/card.js                   卡片渲染器（纯 Web 标准 API，Workers 与 Node 18+ 通用）
  src/meta.js                   按请求生成 og:* 元信息
  src/worker.js                 入口：/ 与 /og
  src/glyphs.js | page.js | static.js    由构建脚本生成
  wrangler.toml

cloud-functions/              （备选）EdgeOne Pages 云函数版本（Python，需自备域名）
server.py                     （备选）任意 Python 环境下的自托管版本
ogcard.py                     （备选版本的）卡片渲染器，纯标准库
```

## 本地开发与部署

```bash
# 1) 预生成字形蒙版（需要 Pillow；仅在改动字号或字符集时需要重跑）
python tools/build_glyphs.py

# 2) 生成部署产物
python tools/build_cloudflare.py

# 3) 本地预览（真实 workerd 运行时）
cd cloudflare && npx wrangler pages dev dist

# 4) 部署
npx wrangler pages deploy dist --project-name shangxue-daojishi --branch main
```

也可以直接用 Python 起一份自托管版本（无任何第三方依赖）：

```bash
PORT=3000 python3 server.py      # 提供 / 与 /og
```

## 实现上的几个关键点

- **根目录不能放 `index.html`**
  Cloudflare Pages / EdgeOne 的静态资源都优先于函数路由。根目录一旦有 `index.html`，
  `/` 会被静态文件接管，动态的卡片信息就失效了 —— 所以页面文件叫 `page.html`，由 Worker 接管 `/`。
- **静态资源 URL 必须带内容指纹**
  页面 HTML 是 `no-store`，而 `app.js` / `styles.css` 是长缓存。资源 URL 不变的话，
  改版后用户会拿到「新页面 + 旧脚本」，表现为**按钮点了没反应、新样式不生效**。
  构建脚本会自动把 `app.js?v=<内容 sha1>` 写进页面。
- **字形是预生成的**
  为了运行时零依赖，卡片用到的 40 多个字符（数字、`天时分秒`、`目标月日周一二三四五六`）
  在开发机用系统字体预先栅格化成 alpha 蒙版，压缩后内嵌进部署产物；
  改字号或换文案后重跑 `tools/build_glyphs.py`。
- **文案与图片同源**
  `og:description` 与卡片图都由同一个目标时间现算，不会出现「文字说 3 天、图上写 5 天」。

## 说明

- 页面样式里引用了 Google Fonts（Noto Sans SC / DM Mono），仅作为字体回退，不随仓库分发。
- 仓库中的字形蒙版由本机系统字体（微软雅黑粗体）栅格化而来，若用于商业用途请自行替换为开源字体。
- 卡片图在 `?t=` 传入的目标上做了合理区间校验（1 天前 ~ 2 年后），越界会自动回退到默认目标。
