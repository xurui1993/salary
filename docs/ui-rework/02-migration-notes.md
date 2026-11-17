# 02 · 迁移说明（T1–T5 收口记录）

> 执行人：Alex（工程师）｜最后更新：2026-11-17
> 适用版本：`src/` 当前状态（T5 结束时）｜快照：`docs/ui-rework/_snapshot-T5-before.zip`

---

## 1. 分层模型（现状）

CSS 只从 `main.tsx → index.css` 一处进入，顺序即级联优先级，**不使用 `@layer`**（无层样式恒胜于有层样式，把新层放进 `@layer` 会被 `workbench.css` 反过来压制）。

| 层 | 文件 | 职责 | `!important` |
| --- | --- | --- | --- |
| L0 兼容（只读） | `src/workbench.css` | 1572 条历史 `wb-*` 基础样式；本阶段**未改动**（mtime 仍为 11:30） | 21（历史） |
| L1 令牌 | `src/styles/tokens.css` | `--wbx-*` 全集 + `--wb-*` 桥接 | 0 |
| L2 基底 | `src/styles/base.css` | 排版、`wbx-spin`、focus-visible、滚动条、`wbx-visually-hidden` | 0 |
| L3 布局 | `src/styles/layout.css` | 外壳栅格 `wbx-shell/sidebar/header/main/page` + 三档断点 | 0 |
| L4 组件 | `src/styles/components.css` | `wbx-card/btn/pill/tabs/toolbar/table/empty/skeleton/field/scroll` | 0 |
| L5 页面 | `src/styles/pages.css` + `pages/{collection,payroll,approval}.css` | 只放「某页才成立」的组合规则 | 0 |
| 迁移中残留 | `src/index.css` | 逐批搬空的旧覆盖层 | **265**（起始 320） |

导入顺序（`src/index.css` 首部）：

```css
@import "tailwindcss";
@import "./styles/tokens.css";
@import "./styles/base.css";
@import "./styles/layout.css";
@import "./styles/components.css";
@import "./styles/pages.css";   /* 内含 pages/collection|payroll|approval.css */
```

> 注意：`@import` 必须位于 `index.css` 内所有规则之前，否则整条声明被浏览器忽略。
> 因此新层规则的**特异性必须 ≥ 0,2,0** 才能真正覆盖 `index.css` 尾部的遗留规则；凡遇到 `!important` 只能从被覆盖者身上撤销（删旧规则），不能在新层加。

---

## 2. `index.css` 收口批次（320 → 265）

| 批次 | 动作 | 删除规则数 | `!important` 变化 | 留痕 |
| --- | --- | --- | --- | --- |
| 起始 | — | — | 320 | — |
| B2-1 | 删除「全类名在 `src/**/*.tsx|ts` 中已无引用」的死规则（`.wb-panel`、`.rb-rail-item-text`、`.wb-approval-empty-state`、`.wb-scenario-pills`、`.wb-preset-add-trigger`、`.wb-sidebar-bottom-status` 等 40 条） | 40 | 320 → **294** | 每条替换为 `/* migrated -> src/styles/pages/*.css (dead selector: …) */` |
| B2-2 | 整节删除 §9「价格审批与任务中心覆盖层」（`.wb-approval-card/.wb-approval-table/.tc-center` 等） | 1 节 | 294 → **265** | `/* migrated -> src/styles/pages/approval.css + collection.css (原 §9 …) */` |
| B2-3 | **尝试**整节删除 §21「发薪平台统一双源工作区」93 条 → 172 | 已回滚 | 172 → 265 | 见 §4 |

**验证方式**：每批 `npx tsc --noEmit` + `npm run build` + 6 页截图（采集 / 任务中心 / 核算批次 / 扣款规则 / **发薪平台** / 价格审批）落 `docs/ui-rework/after-t5/b2-batchN/`。

---

## 3. 被 `wbx-*` 取代的类名对照

| 旧类（`workbench.css` / `index.css`） | 新类（`src/styles/`） | 页面 | 引入批次 |
| --- | --- | --- | --- |
| `.wb-step-card`（步骤卡） | `.wbx-card.wbx-step` | 采集 | T3 |
| `.wb-task-preview.wb-preview-compact` + `.wb-compact-*`（右栏） | `.wbx-rail` / `.wbx-rail__card` / `.wbx-rail__facts` / `.wbx-rail__selected` | 采集 | T3 |
| `.wb-dataset-category-bar` | `.wbx-datasetbar` | 采集 | T3 |
| `.wb-platform-switcher-bar`（4 列固定） | `.wbx-collection .wbx-platformbar`（≥1281 四列 / ≤1280 2×2） | 采集 | T3 |
| `.wb-preset-add-trigger`（虚线按钮） | `.wbx-preset-trigger`（实线） | 采集 | T3 |
| `.tc-table` + `.tc-status` | `.wbx-table` + `.wbx-pill` + `statusSemantics` | 任务中心 | T3 |
| `.pq-state` | `.wbx-pill` + `toneClass(state.tone)` | 核算批次 | T4 |
| `.wb-empty` / `.pq-empty` / `.wb-approval-empty-state` | `.wbx-empty`（`EmptyState`） | 全部 | T2/T4/T5 |
| `.wb-inline-subview-card`（扣款页外壳） | `.wbx-card.wbx-subview` + `.wbx-deduction` | 扣款规则 | T4 |
| `.city-deduction-default` / `.station-exceptions`（卡内二次描边） | `.wbx-panel` / `.wbx-disclosure` | 扣款规则 | T4 |
| `.wb-deduction-stat-pill`（span） | `.wbx-pill`（button + `aria-pressed`） | 扣款规则 | T4 |
| `.wb-approval-card`（两张并列卡） | `.wbx-section` + `.wbx-section__head/__title`（标题 + 分割线） | 价格审批 | T5 |

> 旧 `wb-*` 类**全部保留在 DOM 上**（双轨并行），因此删规则前必须确认该类已不再被任何组件渲染，或该页已有 `wbx-*` 等价实现。

---

## 4. 未达 ≤150 的原因（阻塞项，带证据）

§21「发薪平台统一双源工作区」共 93 条 `!important`，是 `发薪平台` 页（采集页 4 个平台之一）唯一的样式来源。实测删除后该页**破相**：

- 两张来源卡（`.wb-payout-source-card`）退化为纵向平铺文本，失去卡片边框/两列栅格
- 「采集范围 / 导出字段 / 核算用途」由 `dl/dt/dd` 两列对照变成纯文本堆叠
- 截图对照：`docs/ui-rework/after-t5/b2-batch3/b3-payout-1440x900.png`（破相）vs `after-t5/b2-before/before-payout-1440x900.png`（正常）

按「发现破相立即回滚」的规则，该批已整节还原（`265`）。

同类情况：`.wb-compact-*`（§6 的 48 条）仍被 `ReportBuilder.tsx` 使用；§10（23 条）属于报表构建器。

**结论**：`265 − 93（§21，待发薪工作区换装）− 23（§10，待报表构建器换装）= 149`，即 ≤150 的收口门槛必须在**再完成两个页面的换装**后才会自然达成，不能靠删样式硬压。

---

## 4.1 T6-1 实际执行结果（2026-11-17 主理人接手完成）

**关键发现（修正 §4 的预算假设）**：`§21` 注释区间（原 1394–1998 行）是一个「大杂烩节」，93 条 `!important` 中**大部分不属于发薪平台**——日期触发器窄屏（`.wb-dp-*` 5 条）、侧栏 flat-nav 与子视图切换（`.wb-sidebar-flat-nav` / `.wb-subview-*`）、扣款筛选栏、模板中心（`.wb-template-*`）、核算批次容器（`.pq-workbench`）、价格审批卡（`.wb-approval-card`）等全局规则都混在其中。真正 `wb-payout-*` 专属的规则共 253 行、**仅 1 条 `!important`**（且与 §2 同值冗余）。B2-3 整节删除破相的直接原因即在此。

**实际动作**：
- `wb-payout-*` 专属规则整体迁入 `src/styles/pages/payout.css`（231 行 / 0 强制声明 / 类名不变 / JSX 未动，视觉等价）
- accent 色令牌化：`#0284c7`/`#0369a1`→`var(--wbx-primary)`，`#f0f9ff`/`#e0f2fe`→`var(--wbx-primary-soft)`，`#bae6fd`→`rgba(15,110,140,.28)`，焦点环→`var(--wbx-focus)`（PRD「单一主色」）
- 原 900px 断点收敛为 768px（PRD 断点规范）
- 删除与 §2 同值的冗余规则 1 条；死规则注释行清理
- `index.css` 原位留迁移注释；`pages.css` 增加 `@import "./pages/payout.css"`

**结果**：`265 → 264`（−1，远低于原预算 −93，原因如上）；发薪平台页换装完成，视觉翻新覆盖 6/6 页面。

**验证**：`tsc --noEmit` exit 0；`npm run build` 成功（主 chunk 380,755 B / CSS 247,294 B）；发薪平台页 1440/1024/375 三档截图 `after-t6/`——两张来源卡保持两列、`dl` 两列对照完整、主色统一、375 无横向溢出（`scrollWidth==clientWidth==375`）、控制台 0 error。

**修正后的 T6 剩余预算**：`264 − 5（dp 触发器）− 48（§6 报表构建器）− 23（§10）− …`，见 §6 更新后表格。

---

## 5. 回滚方法

| 场景 | 操作 |
| --- | --- |
| 回滚到某个批次之前 | 解压对应快照覆盖 `src/`：`_snapshot-T2-before?`→T3 用 `_snapshot-T3-before.zip`、T4 用 `_snapshot-T4-before.zip`、T5 用 `_snapshot-T5-before.zip`（均只含 `src/`） |
| 只回滚某次 CSS 收口 | 在 `src/index.css` 里搜索 `/* migrated ->` 行，把该行替换回删除前的规则块（快照 zip 内 `src/index.css` 为原文） |
| 校验回滚是否干净 | `npx tsc --noEmit` + `npm run build` + 6 页截图（见 §2） |

> 快照目录：`docs/ui-rework/_snapshot-T{3,4,5}-before.zip`；解压后直接覆盖 `src/` 即可（不含 `dist/`、`backend/`）。

---

## 7. BugFix 记录：激活/悬浮项图标空白（2026-11-17）

**现象**：侧栏激活项（或悬浮项）图标呈「空白白方块」，罗盘/钱包/美元徽章不可见。

**根因**：T2 外壳换装时新层只覆盖了图标**容器**的 color/background，漏掉了 L0 旧规则对 **svg 子元素**的锁定：
`workbench.css` 内 `.wb-sidebar-item[aria-pressed=true] .wb-sidebar-icon svg{color:#fff}`（原设计为紫蓝渐变底 + 白图标，PRD 已弃用该视觉）。新层把容器底色改为白色后，旧规则的白色 svg 与白底叠加 → **白底白图标 = 空白框**。

**修复**（`src/styles/layout.css` L71–L77，新层追加、0 个 `!important`）：
- `.wbx-nav__item[aria-pressed="true"] .wbx-nav__icon svg { color: var(--wbx-primary) }` —— 激活项图标恢复深青
- `.wbx-nav__item:hover:not(:disabled) .wbx-nav__icon { color/background }` 与对应 svg 规则 —— hover 态同步统一，覆盖旧层灰底

**验证**（无头 Chrome 1440×900）：
- 三项 svg `color/stroke` 与容器 color 一致：激活项 rgb(15,110,140)、非激活 rgb(91,101,115)，可见性全部通过
- `Input.dispatchMouseEvent` 模拟悬浮「价格审批」：icon 白底 + rgb(27,36,48) 深色图标 ✓
- 2× 截图：`docs/ui-rework/bug-fix-sidebar-2x.png` / `bug-fix-hover-2x.png`
- `npm run build` 成功

**经验教训（已记入团队测试纪律）**：视觉验收必须包含 **hover / active 交互态**的计算样式抽查（svg stroke/颜色），仅静态截图无法发现「白底白图标」类缺陷；无头测试默认无鼠标，hover 态需用 `Input.dispatchMouseEvent` 显式注入。

---

## 8. BugFix 记录：月份 chip 文字叠印（2026-11-17）

**现象**：勾选月度资料后，Step02 账期卡的月份 chip 内「2026-11」与「11-01 ~ 11-17」文字重叠拖影。

**根因**：`index.css` 旧规则 `.wb-month-grid-3 { grid-template-columns: repeat(3, 1fr) !important }` 是按**全宽单卡**（~1200px，3 列各 390px）设计的。T3 把城市与账期改为两列同排后，账期卡最窄 ~371px，3 列锁定使每张 chip 仅 117px，而 chip 内容（checkbox 16 + 月份 56 + 日期范围 83 ≈ 163px）溢出 46px，叠印到相邻位置。因带 `!important`，新层（0 强制声明约束）无法覆盖，必须按迁移硬约束**原位改旧规则**。

**修复**（`src/index.css` L65–72）：删除 3 条 `!important`，改为自适应列 `repeat(auto-fill, minmax(180px, 1fr))` —— 全宽 6 列 / 两列布局 2 列 / 窄屏自动 1 列，原 640px 断点兜底一并移除。`!important` 计数 264 → **261**。

**验证**：实测 gridCols 由 `117px×3` → `180.5px×2`，`overlap=false`、无卡片溢出；复现路径（勾选「骑手数据明细」）截图 `bug-month-fixed.png` 文字分离清晰；`tsc` exit 0、`npm run build` 成功。

**经验教训**：T3 引入的「两列布局」改变了旧规则的设计前提（全宽单卡），**改动布局结构时必须复核同页所有旧覆盖规则的宽度假设**，尤其带 `!important` 锁死的 grid/宽度声明。

---

## 9. T6-0 验收记录（2026-11-17，主理人实测）

环境恢复（并行会话重启服务链，403 消失）后由主理人完成交互态验收，脚本 `C:\Users\EDY\WorkBuddy\2026-11-17-10-45-07\.tmp_t3\probe60.mjs`（修复了其 `OUTDIR` 未定义笔误）。

| 验收点 | 目标 | 实测 | 结论 |
| --- | --- | --- | --- |
| P0-1 扣款 1440 下方空白 | <80px | **-217**（内容超出视口，scrollH 1165，无空白） | ✅ |
| P0-1 例外表展开后层级 | ≤2 | **2** | ✅ |
| P0-1 1024 堆叠 + 默认展开 | 堆叠 / open | `stacked:true`、`open:true`、blankBelow **-207** | ✅ |
| P0-2 城市卡换行 | 单行 | 「深圳 18站」chipH=35px、`nameWrapped:false`、站数 `nowrap` | ✅ |
| P0-2 hover 态 | 无破相 | 边框 `rgb(203,213,225)` / 底 `rgb(248,250,252)` | ✅ |
| P0-3 只看已选 | 过滤生效 | 点击后 15 → **2** 张卡，文案「只看已选 2」，`aria-pressed` 切换 | ✅ |
| P1-4 头部宽度释放 | ~330px | actions 总宽 456 → **126px**（trigger 74px）；Dock 面板展开后摘要 **5 chips**（风神/蓝橙/商翼/灯塔/本来）、面板 440px | ✅ |
| P1-6 快照按钮 primary | 主色 | `rgb(15,110,140)` + `wbx-btn--primary`，全页 primary 按钮 1 个 | ✅ |
| 控制台 | 0 error | 仅 favicon 404（基线既有） | ✅ |

截图：`docs/ui-rework/after-t60/`（city-hover / category-hover / dock-summary / deduction-1024-stacked）。

**遗留微调**：P1-6 分隔符实测 1 个（工程师报 2 个）——某分组在当前数据条件下未渲染，属条件渲染非缺陷；下批触及工具行时复核。

**后端 403 复盘**：并行会话 15:07 独立启动 uvicorn（父进程非 Node），绕过 `server.ts` spawn 注入 `FENGSHEN_DOWNLOAD_PROXY_SECRET` 的机制 → 全部下载 API 403「下载访问来源无效」（`backend/download_accounts.py:51`）。并行会话重启服务链后恢复。**教训：后端鉴权协议（proxy secret）依赖 Node→uvicorn 的父子进程启动方式，独立启动后端必然 403。**

---

## 9.1 T6-0b 视觉精修验收（2026-11-17，主理人复核）

用户截图指出两处：城市卡截断/孤卡、月份 chip 叠印。根因同型——**旧层 `!important` 锁死的列宽假设在 T3 两列布局下过期**。

| 改动 | 内容 |
| --- | --- |
| A 城市网格 | `index.css` §3：删 2 条 `!important`，固定 6 列 → `repeat(auto-fill, minmax(132px,1fr))`，删除 ≤1240/≤760 两个断点块 |
| B 月份网格 | `minmax(180px,1fr)` → `minmax(200px,1fr)`（实测 chip 内容真实需求 ≈199px，180 会溢出） |
| C 溢出兜底 | `collection.css` 新层补 `overflow:hidden + ellipsis`（旧层只有 `nowrap` 无 ellipsis，文字溢出盒子即叠印机制） |
| D 下架城市 | 已下架城市只渲染下架徽标，不再并列站数（信息冗余且挤占宽度） |

**主理人独立复核（全新 profile + 单次导航）**：

| 指标 | 1440×900 | 1024×768 | 判定 |
| --- | --- | --- | --- |
| 采集页屏数 | **1.00**（scrollH 900） | **1.28**（scrollH 986，目标 ≤1.4） | ✅ 无回归 |
| 城市网格 | 5 列 × 152px，高 121px | 3 列 × 184px，高 207px | ✅ |
| 城市名截断 | 无（`scrollWidth ≤ clientWidth`） | 无 | ✅ |
| 月份 chip 标题/范围 | 间距 183px，**不相交** | 间距 84px，不相交 | ✅ |
| `!important` | 261 → **258**（删城市网格 3 条） | 新层仍 0 | ✅ |

**顺带关闭 T6-0 遗留**：工具行分隔符只渲染 1 个的根因是上次插入点 `'清空城市' : '全选城市'` 命中了蓝橙分支的同名按钮，风神分支因此少一个；现已定位修复，DOM 实测 2 个分隔符、三组分组成立。

**遗留**：① 13 城市奇数，末行尾差卡（需末行居中/弹性布局解决）；② 1024 下月份卡 hover 注入未命中（指针落在间隙），1440 已验证；③ 城市卡 hover 仍是旧层观感（浅边框+浅底无阴影），可后续增强。

---

## 9.2 T6-1a/T6-1b 验收（薪资核算页重构，2026-11-17）

**结构合并**：页面级「所选任务」section 删除（`document.querySelector('.pq-detail')` = null）→ 改为表格行内展开（`<tr class="pq-row-detail">` + chevron `aria-expanded`）；任务动态日志随详情下沉（标题改「任务动态」）；页面级仅留一条「全部业务记录（N）」跨任务折叠。

**关键误读修复**：截图里「第 4 个灰 tab」实为 `.pq-mode-hint` 提示「上传后自动执行」与真 tab 同排同排版所致。已移至 `.pq-mode-bar` 行尾（`margin-left:auto`）+ `.wbx-hint` 弱化样式。实测两档均不相交（1440：tabs 281–567 / hint 1315–1399；1024：97–383 / 907–991），hint 色 rgb(91,101,115)、背景透明、边框 0px。

**视觉控件**：模板条改 `.wbx-toolbar`（左侧图标+标题+副说明，右侧「排除取分离站点 → 选择模板 → 标准模板」成组右对齐，顺带补上此前非空态未渲染的 `separationOption` 复选框）；卡头计数改「N 个任务 · N 运行中 · N 已完成」；列宽固定 44/320/140/90/200/120（实测 ±0px）、操作列 sticky right；进度格三行压两行；状态统一 `wbx-pill` + 5 tone。

**主理人独立复核（1440 真实页面）**：scrollH 900 / **1.00 屏**；tabs 3 项，激活 rgb(15,110,140) 白底、未选中 rgb(28,52,76) 非禁用灰；hint 与 tabs 不相交；页面级详情已移除；控制台 0 error。

**旧层隐患（新层已覆盖，待 T6-2 清）**：`workbench.css` 内 `@media (width<=1100px)` 仍把 `.pq-applicants`、`.pq-mode-hint` 整块 `display:none`。本批未动该压缩产物，改由新层以更高特异性恢复（`.wbx-payroll .pq-mode-hint{display:inline-flex}`、`.wbx-payroll .pq-applicants{display:table-cell}`，0 强制声明）。**建议 T6-2 以精确字符串手术删除该 media 块中的两条 display:none**，否则窄屏下任何未覆盖场景仍会隐藏。

**待真实数据复测**：全新 profile 队列为空（表格不挂载），卡头真实文案、真实行 pill、行展开、模板条按钮四项仅做了同构 DOM 注入的 CSS 级测量，需在有核算任务的 workspace 复测（探针 `.tmp_t3/probe61.mjs` 已备好）。

---

## 9.3 T6-1c 操作列与进度列精修（2026-11-17）

用户真实数据截图暴露三处问题，根因均为「旧层假设 + 固定列宽冲突」：

| 问题 | 根因 | 修法 |
| --- | --- | --- |
| 进度文案溢出压进操作列 | `PayrollQueueWorkbench.tsx` L49 把 `task.current_action` 拼进状态 pill，pill 无宽度约束 | pill 只留状态 label；动作名降为第二行 `<small class="pq-progress-desc">`；耗时独立第三行 `.pq-elapsed` |
| 「操作」表头与按钮错位 22px | 旧层 `.pq-row-actions-heading{padding-right:22px!important}` vs 内容按钮组右内边距仅 12px | 新层给内容格同样 22px（`.wbx-payroll .pq-table td.pq-ops-cell{padding-right:22px}`），零改旧层；不采用归零方案，因该表头类可能被其他页面复用 |
| 列宽与设定不符 | 旧层 `@media(≤1100px)` 的 `.pq-task-cell{min-width:150px}` 等与新层固定列宽打架 | 新层更高特异性解除三处 min-width，固定列宽全视口生效 |
| 操作按钮不成体系 | 「停止」文字链接 / 「下载」带文字 / 「×」图标按钮混用 | 统一 26×26 `pq-icon-button`（下载/打开目录/停止），文字链接仅留「确认扣款/继续核算/恢复」 |
| sticky 列右侧竖线噪音 | `box-shadow:-8px 0 8px -8px` 过硬 | 改为 1px 左边框、零阴影（全站语言已是边框分隔） |

**实测（注入「运行中 + 长动作名 + 耗时 + 3 图标按钮」样本）**：列宽 44/320/140/90/200/120（±0）；`pillOverflow=false`、`descOverflow=false`（动作名完整显示，不截断）；进度格 right **1058** = 操作列 left **1058**（不侵入）；表头内容右边缘与末按钮右边缘 **Δ0**；操作列 `sticky`/`right:0`/`border-left 1px`/`shadow:none`；hover 注入行底色生效；控制台 0 error。

**主理人补充改动**：将动作名与耗时由「合并一行（省略号截断）」改为**两行完整显示**（动作名一行 + 耗时一行），消除信息缺失；同步更新探针 `probe61c.mjs` 的注入样本为两行结构后复测通过。

**旧层仍待 T6-2 清理**：`.pq-row-actions-heading{padding-right:22px!important}` 与 `@media(≤1100px)` 三处 min-width 依旧留在 `workbench.css`（新层已覆盖，不影响现状）。

---

## 6. 后续批次建议（追到 ≤80）

| 批次 | 目标 | 预计 `!important` | 前置条件 |
| --- | --- | --- | --- |
| T6-1 | ~~发薪平台换装 → 删 §21~~ **已完成**（见 §4.1，实际 265 → 264） | 264 | — |
| T6-2 | 报表构建器 `ReportBuilder` 换装 → 删 §6 余量 + §10 | 264 → ~193 | 报表页复用 `.wbx-rail` |
| T6-3 | 采集页预设弹层（§13/§15/§16）与分类栏（§20） | ~193 → ~162 | 预设相关按钮改 `.wbx-btn` |
| T6-4 | 侧栏（§11/§17）与引导动画（§18）、子视图切换（§21 区间残留） | ~162 → ~120 | `wbx-sidebar` 已就位，可逐步剥离 |
| T6-5 | 重试按钮（§19）、dp 触发器窄屏、零散块 | ~120 → ≤80 | — |

> 每批仍按「删 30–50 条 → tsc/build + 6 页截图 → 破相即回滚」推进，并继续在 `index.css` 原位留 `/* migrated -> … */` 单行注释。
