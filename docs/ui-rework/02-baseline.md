# 02 · 改造前基线测量（Baseline）

> 测量人：QA 严过关 ｜ 测量时间：2026-11-17 ｜ 被测版本：改造前存量代码（`src/` 未改动，`git`/文件 mtime 均为改造前）
> 只读测量：未修改任何源码、配置或数据文件；截图与临时脚本均落在项目 `docs/ui-rework/baseline/` 与本机临时目录。

---

## 0. 测量环境与可复现方法

| 项 | 值 |
| --- | --- |
| 服务 | Express `http://localhost:3000/`（HTTP 200）+ 后端 FastAPI `http://localhost:8009`（HTTP 200），全程未重启 |
| 浏览器 | Chrome（`/c/Program Files/Google/Chrome/Application/chrome.exe`），`--headless=new` + CDP 远程调试口 9444 |
| Node | v22.22.2（内置 WebSocket 直连 CDP，无 puppeteer 依赖） |
| 视口设定 | `Emulation.setDeviceMetricsOverride{deviceScaleFactor:1}`；截图用 `Page.captureScreenshot{clip:{x:0,y:0,width,height},scale:1}` 保证像素尺寸=视口尺寸 |
| 屏数算法 | `document.body.scrollHeight / window.innerHeight`（保留 2 位小数） |
| 可见性判定 | `rect.top>=0 && rect.bottom<=innerHeight`（**未滚动**状态下） |
| 导航方式 | 无路由库，按文本 `click()` 侧栏/子页按钮；每次切换后等待 2.4–3.0s，并校验 `#root.innerText.length>60` 且 `.wb-step-card` 有实际高度，白屏则重试（最多 4 次） |

### 0.1 复现前必须做的状态重置（重要）

页面**没有 URL 路由**，且当前视图/平台会写入 `localStorage`。若不清空，冷启动会落回上次停留的页面（实测：未清空时默认落在「薪酬核算 / 核算批次」，页面结构与基线完全不同）。

复现步骤：

1. `localStorage.clear(); sessionStorage.clear();` → `Page.navigate('http://localhost:3000/')`
2. 默认落在「数据采集 / 新建采集」
3. 再按上表方式点击侧栏一级 → 子页按钮

涉及的持久化键：`app_theme`、`appConfig`、`taskHistory`、`taskStatsMap`、`workbench_task_kind`、`workbench_download_platform`、`app_workspace_id`、`download-last-task:shared:<id>`。

### 0.2 测量脚本位置（不进入项目 src/）

`C:\Users\EDY\WorkBuddy\2026-11-17-10-45-07\.tmp_qa\`：`cdp.mjs`（CDP 封装）、`measure2.mjs`（4 视口 × 5 页面主测量）、`extra3.mjs`（灯塔同名控件 / 平台切换）、`console.mjs`（控制台日志）。原始数据：`result2.json`。

---

## 1. 主数据表（基准视口 1440×900）

| 指标（测法） | 采集新建 | 任务中心 | 核算批次 | 扣款规则 | 价格审批 |
| --- | --- | --- | --- | --- | --- |
| `document.body.scrollHeight`（px） | **918** | 900 | 900 | 900 | 900 |
| 视口高度（px） | 900 | 900 | 900 | 900 | 900 |
| **屏数** = scrollHeight/viewportH | **1.02** | 1.00 | 1.00 | 1.00 | 1.00 |
| 页面主操作按钮 | 开始下载 | 整理已完成 | 选择模板 | 保存后续默认扣款 | 刷新待办 |
| 主操作 `rect.top`（px） | **405** | 113 | 178 | 106 | 141 |
| `rect.left`（px） | 1095 | 1053 | 1242 | 1257 | 1294 |
| 未滚动即可见 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 按钮 disabled（静息态） | ⚠️ 是（未选资料） | 否 | 否 | ⚠️ 是 | 否 |
| DOM 最大嵌套层深（`#root` 起算） | **15** | 16 | 12 | 14 | 11 |
| 卡片/边框容器最大嵌套层数（见 §3.2 口径） | 3 | 3 | 3 | **4** | 3 |
| 处于 ≥3 层卡片容器内的文本节点数 | 9 | 6 | 3 | **611**（其中 **200** 个在 ≥4 层） | 2 |
| `border-style:dashed` 可见元素数 | **3** | 0 | 0 | 0 | **2** |
| `animate-spin` 元素数（静息态） | 0 | 0 | 0 | 0 | 0 |
| 合成 `.animate-spin` 的 `animationName` | `none` | `none` | `none` | `none` | `none` |
| 可见「灯塔」同名控件数 | **1**（下拉展开后 **2**） | 1 | 1 | 1 | 1 |
| 控制台 error / warning | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `body` 背景 vs `.workbench-app` 背景 | 不一致 | 不一致 | 不一致 | 不一致 | 不一致 |

> 「页面主操作按钮」对采集新建另测了 `开始任务`：**未找到**（DOM 中不存在该文案按钮，基线里只有「开始下载」）。

---

## 2. 四档视口对照

### 2.1 屏数（`body.scrollHeight / innerHeight`）

| 视口 | 采集新建 | 任务中心 | 核算批次 | 扣款规则 | 价格审批 |
| --- | --- | --- | --- | --- | --- |
| 1440×900 | **1.02** | 1.00 | 1.00 | 1.00 | 1.00 |
| 1366×768 | **1.29** | 1.00 | 1.00 | 1.00 | 1.00 |
| 1024×768 | **2.02** | 1.03 | 1.00 | 1.00 | 1.00 |
| 375×667 | **3.85** | 1.82 | 1.30 | 1.67 | 1.04 |

原始 scrollHeight（px）：1440 → 918；1366 → 988；1024 → 1549；375 → **2569**（采集新建）。

### 2.2 主操作按钮 `rect.top`（px）/ 是否需滚动才可见

| 视口 | 采集新建（开始下载） | 任务中心（整理已完成） | 核算批次（选择模板） | 扣款规则（保存后续默认扣款） | 价格审批（刷新待办） |
| --- | --- | --- | --- | --- | --- |
| 1440×900 | 405 / 可见 | 113 / 可见 | 178 / 可见 | 106 / 可见 | 141 / 可见 |
| 1366×768 | 405 / 可见 | 113 / 可见 | 178 / 可见 | 106 / 可见 | 141 / 可见 |
| 1024×768 | 405 / 可见 | 113 / 可见 | 178 / 可见 | 106 / 可见 | 141 / 可见 |
| 375×667 | **2298 / 需滚动 ≈3.4 屏** | 283 / 可见 | 327 / 可见 | 280 / 可见 | 252 / 可见 |

### 2.3 采集新建三步卡片的实际位置（px，top–bottom）

| 视口 | Step 01 选择资料 | Step 02 范围与账期配置 | Step 03 |
| --- | --- | --- | --- |
| 1440×900 | 165–719 ✅ | 731–850 ✅ | 未渲染（未选资料时不出现） |
| 1366×768 | 165–789 ❌（超出 768） | 801–920 ❌ | 未渲染 |
| 1024×768 | 165–1303 ❌ | 1315–1481 ❌ | 未渲染 |
| 375×667 | 需滚动（正文区 180–2409） | — | — |

### 2.4 平台切换对页面高度的影响（1440×900，采集新建）

| 平台 | scrollHeight | 屏数 | Step 01 / Step 02 |
| --- | --- | --- | --- |
| 风神数据 | 918 | 1.02 | 165–719 / 731–850 |
| 蓝橙数据 | 900 | 1.00 | 165–461 / 473–593 |
| 发薪平台 | 900 | 1.00 | 165–507 / 519–639 |
| 小象灯塔 | 900 | 1.00 | 165–496 / 508–628 |

> 结论：**任一平台在 1440×900 下都 ≈1 屏**；页面变高的原因是「视口变窄」（1024 → 2.02 屏，375 → 3.85 屏）。

---

## 3. 逐项明细

### 3.1 主操作按钮可达性
- 采集新建在 1440/1366/1024 三档 `开始下载` 恒在 `top=405`（位于右侧 300px 宽栏 `wb-compact-rail-bottom` 内），**首屏可见**；
- 375×667 时右栏塌到主区下方 → `top=2298`，需滚动约 3.4 屏才能触达；且此时按钮 `disabled`（提示「请先在 Step 01 勾选至少 1 类资料」）。
- 1024×768 时 Step 02 顶部 1315px、底部 1481px，**必须滚动**；1366×768 时 Step 01 底部 789px 已超出 768。

### 3.2 DOM 嵌套深度 / 卡套卡

**「卡片」口径（严格）**：元素可见（rect>1px 且非 `display:none`/`visibility:hidden`）、有 `border-width>0` 且 `border-style≠none`、`border-radius ≥ 6px`，并排除表格语义标签（`table/thead/tbody/tr/td/th`）与列表标签（`ul/li`）。统计单位为「直接含 ≥2 字文本节点的元素」，沿 `parentElement` 上溯计数。

- 最大层深 11–16 层（`#root` 起算），最深为任务中心 16 层：
  `workbench-app > wb-shell > wb-viewport > wb-main > section > relative > div > div > tc-center > tc-searchbar > tc-filters > div > tc-filter-date-item > wb-datepicker > wb-datepicker-trigger > wb-dp-trigger-value`
- 采集新建 15 层：`... > wb-main > section > relative > rounded-xl > wb-download-main > wb-step-card > wb-source-group > grid > flex > wb-dataset-body > wb-dataset-top-row > wb-dataset-title`
- **「卡套卡」结构在 5 个页面全部存在（≥3 层）**，典型链路：
  | 页面 | 最大层数 | 链路（外 → 内） |
  | --- | --- | --- |
  | 采集新建 | 3 | `wb-step-card > wb-dataset-category-bar > wb-dataset-cat-btn` |
  | 任务中心 | 3 | `tc-center > wb-quick-filters > button` |
  | 核算批次 | 3 | `pq-mode-bar > wb-segment > is-active` |
  | 扣款规则 | **4** | `wb-inline-subview-card > station-exceptions > wb-deduction-scroll > wb-button` |
  | 价格审批 | 3 | `wb-approval-card > approval-scope > wb-button` |
- **「虚线框」**：`border-style:dashed` 的可见元素 —— 采集新建 **3** 处（均在右栏 `wb-compact-*` 预览区）、价格审批 **2** 处（外层审批卡片 + 内层空态框，形成「卡套虚线框」）、其余 3 页 0 处。
- 量级差异极大：价格审批仅 2 个文本节点在 ≥3 层卡片内，扣款规则高达 **611** 个（其中 200 个在 ≥4 层），是"卡套卡"最重的页面。
- 截图佐证：`baseline/price-approval-1440x900.png`（卡内虚线框套虚线空态框）、`baseline/collect-new-1440x900.png`（右栏三层嵌套卡片）、`baseline/deduction-rule-1440x900.png`。

### 3.3 加载图标是否旋转
- 5 个页面在**静息态均无 `animate-spin` 元素**（`document.querySelectorAll('[class*="animate-spin"]').length === 0`），也无 `svg.lucide-loader-*` 图标；
- 因此改用 **CSS 级联探针**测量：向 `.workbench-app` 内注入 `<div class="animate-spin">` 后读计算值 —— 结果 `animationName: none`、`animationDuration: 0s`；同样测 `.animate-breathe`、`.animate-in` 亦为 `none`；
- 根因定位（`src/workbench.css`，单行压缩文件）：
  `.workbench-app,.workbench-app *,.workbench-app :before,.workbench-app :after{…;animation:none!important}` —— 全局通配禁用。

### 3.4 「灯塔」同名控件
| 状态 | 可见「灯塔」控件 | 位置（`rect.left,top`） | 所属控件 |
| --- | --- | --- | --- |
| 1440×900 收起 | 1 | (1281, 22) | `button.wb-connection-trigger`（顶栏「平台登录 风神 蓝橙 商翼 灯塔 本来」） |
| 1440×900 展开「平台登录」下拉 | **2** | (1281, 22) + (1006, 507) | 前者同上；后者 `h3.wb-platform-name`，位于 `wb-connection-dropdown` 面板「数据源平台通道 · 5/5 已就绪」列表内 |
| 375×667 收起 | 0 | — | 顶栏 chip 行隐藏，仅剩「平台登录」文字 |
| 375×667 展开下拉 | 1 | (**−174**, 551) | `h3.wb-platform-name`；**横向溢出到视口左侧外（left=-174px）**，375px 下下拉面板超出屏幕 |

> 另：Step 01 的平台卡片文案为「小象灯塔」（非「灯塔」），1440 下其文字 span 宽 0 不单独可见，属正常；不构成同名重复。

### 3.5 控制台
- 全量导航扫描（数据采集→新建采集→任务中心→薪资核算→核算批次→扣款规则→模板中心→价格审批）：`Runtime.consoleAPICalled` + `Runtime.exceptionThrown` + `Log.entryAdded` 合计 **0 条 error / 0 条 warning**；
- 冷缓存首次加载时曾捕获 **1 条** `Log.entryAdded[error]`：`Failed to load resource: 404 (Not Found) http://localhost:3000/favicon.ico`（有缓存后不再出现，属静态资源缺失，不阻塞渲染）。
- 因此「首条内容」= 上述 favicon 404；无 JS 运行时异常。

### 3.6 首屏背景色
| 元素 | 计算值 |
| --- | --- |
| `document.body` | `oklch(0.208 0.042 265.755)`（= Tailwind `bg-slate-900`，来自 `index.html` 的 `body` class） |
| `.workbench-app` | `rgb(248, 250, 252)`（`--wb-bg`） |

**两者不一致**，5 个页面、4 档视口全部如此。当前视觉上不可见（`.workbench-app` 铺满且不透明），但属于改造后要收敛的隐性冲突（深色 `body` 一旦出现 1px 缝隙/透明区即露出深底）。

### 3.7 窄屏观感问题（截图可见，供改造对账）

- **1024×768**（`collect-new-1024x768.png`）：4 张平台切换卡文案被截成「风…」「蓝…」「发…」「小…」，平台名与副标题均不可读；Step 01 内 15 张资料卡挤成 3 列窄条，描述文字断成 4 行，出现「城市·账期」标签溢出卡片边界。此时页高 1549px（2.02 屏）。
- **375×667**（`collect-new-375x667.png`）：侧栏塌为顶部 tab 条，4 张平台卡改为纵向堆叠，页高 2569px（3.85 屏），主操作按钮沉到 2298px。
- **价格审批 1440×900**（`price-approval-1440x900.png`）：内容在 ~393px 处结束，下方留出约 500px 纯白空白；卡片内还有一圈虚线空态框，构成「卡套虚线框」。页高恰好 900px（无滚动），空白不是"页面截断"而是空态高度失控的观感问题。
- **扣款规则 1440×900**（`deduction-rule-1440x900.png`）：单页内 611 个文本节点处在 ≥3 层边框容器中，是"卡套卡"最密集的页面。

---

## 4. 静态计数（命令行，可复现）

| 指标 | 实测值 | 命令 |
| --- | --- | --- |
| `src/index.css` 体积 | 55 029 B（53.7 KB），2 608 行 | `wc -c`, `wc -l` |
| `src/index.css` `!important` 次数 | **320** | `grep -o '!important' src/index.css \| wc -l` |
| `src/index.css` 规则数（`{` 计数） | **344** | `grep -o '{' src/index.css \| wc -l` |
| `src/workbench.css` 体积 | **140 790 B（137.5 KB）**，行数 **0**（单行无换行压缩） | `wc -c`, `wc -l` |
| `src/workbench.css` 规则数 | **1 572** | `grep -o '{' src/workbench.css \| wc -l` |
| `src/workbench.css` `!important` 次数 | 21 | `grep -o '!important' src/workbench.css \| wc -l` |
| `src/workbench.css` `@media` 出现次数 | 23（去重 12 条） | `grep -o '@media[^{]*'` |
| `@media` 断点取值去重（workbench.css） | `420, 480, 600, 700, 760, 800, 1000, 1023, 1024(min-width), 1100, 1180` = **11 种宽度** + `prefers-reduced-motion:reduce` | 同上 |
| `@media` 断点取值去重（index.css） | `560, 640, 720, 760, 900, 960, 1100, 1240` = **8 种**（`760/1100` 与上表重复） | 同上 |
| 两文件断点并集 | `420, 480, 560, 600, 640, 700, 720, 760, 800, 900, 960, 1000, 1023, 1024, 1100, 1180, 1240` = **17 种** | 同上 |
| `1280px` 断点是否存在 | **不存在**（`src/index.css`、`src/workbench.css` 均无 `1280`） | `grep -c 1280px` |
| `src/` 内 `animation:none` 位置 | **2 处，均在 `src/workbench.css`**：① 全局 `.workbench-app,.workbench-app *,…:before,…:after{…animation:none!important}`；② `.animate-breathe,.animate-breathe-glow,.animate-in{animation:none}`。`.tsx/.ts` 内 0 处 | `grep -o "animation:none" src/*` |
| `dist/assets` JS | `index-lhtElpwM.js` = **599 075 B（585.0 KB）** | `ls -l` |
| `dist/assets` CSS | `index-BK1ho3x3.css` = **215 109 B（210.1 KB）** | `ls -l` |
| `dist/assets/aistudio/`（图片） | 7 个 PNG，合计 **3.5 MB**（最大 `image_31b5df0d.png` 313 KB） | `du -sh` |
| `dist/server.js` | 87 265 B | `ls -l` |
| `npm run lint`（`tsc --noEmit`，TypeScript 7.0.2） | **通过**，exit code 0，无任何输出 | `npm run lint` |

---

## 5. 截图索引（相对 `docs/ui-rework/baseline/`）

命名：`{page}-{width}x{height}.png`，像素尺寸与文件名一致，单张均 < 400 KB。

| 页面 | 1440×900 | 1366×768 | 1024×768 | 375×667 |
| --- | --- | --- | --- | --- |
| 采集新建 | `collect-new-1440x900.png` (173.1 KB) | `collect-new-1366x768.png` (148.9 KB) | `collect-new-1024x768.png` (86.3 KB) | `collect-new-375x667.png` (36.1 KB) |
| 任务中心 | `task-center-1440x900.png` (84.4 KB) | `task-center-1366x768.png` (82.7 KB) | `task-center-1024x768.png` (76.3 KB) | `task-center-375x667.png` (29.0 KB) |
| 核算批次 | `payroll-batch-1440x900.png` (60.1 KB) | `payroll-batch-1366x768.png` (58.7 KB) | `payroll-batch-1024x768.png` (51.9 KB) | `payroll-batch-375x667.png` (31.4 KB) |
| 扣款规则 | `deduction-rule-1440x900.png` (68.8 KB) | `deduction-rule-1366x768.png` (67.6 KB) | `deduction-rule-1024x768.png` (62.2 KB) | `deduction-rule-375x667.png` (34.4 KB) |
| 价格审批 | `price-approval-1440x900.png` (46.8 KB) | `price-approval-1366x768.png` (44.7 KB) | `price-approval-1024x768.png` (42.2 KB) | `price-approval-375x667.png` (24.4 KB) |

---

## 6. 与 PRD 基线声明的一致性核对

| PRD 声明 | 实测 | 判定 | 说明 |
| --- | --- | --- | --- |
| Step02（城市/站点）落在 **~1600px** 之下 | 1440×900：Step02 顶部 **731px**、底部 850px；1366×768：801px；1024×768：**1315px**；375×667：正文区高 2409px | ❌ 不一致 | 只有 **1024×768**（1549px 页高）接近 PRD 的 ~1600px。1440×900 下 Step02 首屏即见 |
| 1440×900 需 ≥2 次滚动 | 1440×900 页高 918px，超出仅 18px，**1 次微小滚动到底**；Step01/Step02 均可见 | ❌ 不一致 | 推测 PRD 的「~1600px」实测于 1024×768 或带 DevTools 的窄窗口 |
| 纵向 ≈**4.5 屏** | 1440 = 1.02 屏；1366 = 1.29；1024 = 2.02；375 = **3.85**（最大） | ❌ 不一致 | 四档中最接近的 375×667 也只有 3.85 屏 |
| `!important` **320 条** | `src/index.css` = **320** 条（另 `workbench.css` 21 条） | ✅ 一致 | 逐字匹配 |
| 断点 **12 种**（420/480/600/700/760/800/1000/1023/1024/1100/1180/**1280**） | workbench.css **11 种宽度** + 1 条 `prefers-reduced-motion`；index.css 8 种；并集 **17 种**；**无 1280px** | ❌ 不一致 | PRD 列的 1280 在全项目 CSS 中不存在；漏计 index.css 的 560/640/720/900/960/1240 |
| Loader2 **全部不转** / `animation:none` 全局禁用 | 全局规则确实存在（`.workbench-app *{…animation:none!important}`）；CSS 级联探针 `.animate-spin → animationName:none, 0s` | ✅ 一致 | 但**静息态 5 个页面均无 `animate-spin` 元素**，「可见旋转为 0」只能通过注入探针验证，非页面实测 |
| `grep -c "animation:none" src/*.css` = 现状非 0 | `src/workbench.css` = 2 处，`src/index.css` = 0 处 | ✅ 一致（口径需修正） | PRD 的 `src/*.css` 通配不会匹配到 `workbench.css` 内**单行内容里的第 2+ 次**出现，验收 grep 建议用 `grep -o` 统计 |
| 存在「卡套卡套虚线框」三层结构 | 5 个页面全部存在 ≥3 层卡片嵌套（最大 4 层）；`dashed` 元素：采集 3 / 审批 2；扣款规则 **611** 个文本节点在 ≥3 层卡片内（200 个 ≥4 层） | ✅ 一致 | 见 §3.2 口径、链路与截图佐证 |
| 存在两个「灯塔」同名控件 | 收起态 1 个；**展开「平台登录」下拉后 2 个**（顶栏 chip + 下拉面板 H3） | ⚠️ 条件成立 | 仅在平台登录下拉展开时同时可见；375×667 展开后该 H3 溢出到 `left:-174px` |
| `workbench.css` 140KB 单行无源码 | 140 790 B（137.5 KB），换行数 0，1 572 条规则 | ✅ 一致 | — |
| `index.css` 56KB / 344 条规则 | 55 029 B（53.7 KB）/ 344 条 | ✅ 一致 | — |
| 控制台无报错 | 0 error / 0 warning（冷缓存首次加载有 1 条 `favicon.ico` 404） | ✅ 一致 | favicon 缺失可顺手补 |
| 首屏背景一致 | `body` = `oklch(0.208 0.042 265.755)` vs `.workbench-app` = `rgb(248,250,252)`，**不一致** | ❌ 新增发现 | PRD 未列此项，建议纳入改造验收 |

---

## 7. 无法测量项（不估算）

| 项 | 原因 |
| --- | --- |
| 「Loader2 在真实加载中是否旋转」 | 5 个页面静息态**不存在** `animate-spin` / `lucide-loader-*` 元素；触发真实加载需调用后端下载/核算/审批接口，属写操作区（可能落盘/改库），本次只读测量不做。已改用 CSS 级联注入探针给出等价结论（`animationName:none`） |
| 移动端触摸滚动真实手感 / iOS Safari 表现 | 仅 Chrome headless 桌面内核，无真机；375×667 为 CDP 视口模拟（`mobile:false`） |
| `npm run build` 产物是否与 `dist/` 一致 | 任务要求只读，不做构建；`dist/` 为 2026-11-16 14:09 的历史产物，体积数据仅作参考 |
| 首屏渲染耗时（FCP/LCP） | 任务未要求且 dev 模式下 Vite 未压缩模块，数值对改造前后对比无意义 |
