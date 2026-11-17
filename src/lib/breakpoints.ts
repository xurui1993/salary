/**
 * 断点单一数据源（D6：只做 1280 / 1024 / 768 三档）。
 *
 * 与 CSS 的对应关系（`src/styles/layout.css`）：
 * - `@media (max-width:1280px)` → 侧栏强制折叠 64px，隐藏品牌副标题
 * - `@media (max-width:1024px)` → 页内边距收到 16px
 * - `@media (max-width:768px)`  → 侧栏改抽屉 + 遮罩，头部出现汉堡键
 *
 * 约束：本文件不引入任何新依赖，只使用 `window.matchMedia` / `resize` 事件。
 */

/** 三档断点常量（px）。 */
export const BP = {
  /** 大屏：>1280 展开侧栏 */
  lg: 1280,
  /** 中屏：1024–1280 折叠图标栏 */
  md: 1024,
  /** 小屏：<768 抽屉导航 */
  sm: 768,
} as const;

/** 视口档位。 */
export type BreakpointTier = 'lg' | 'md' | 'sm' | 'xs';

/**
 * 纯函数：宽度 → 档位。
 *
 * @param width 视口宽度（px）。
 * @returns `lg`（>1280）/ `md`（1025–1280）/ `sm`（769–1024）/ `xs`（≤768）。
 */
export function tierForWidth(width: number): BreakpointTier {
  if (width > BP.lg) return 'lg';
  if (width > BP.md) return 'md';
  if (width > BP.sm) return 'sm';
  return 'xs';
}

/**
 * 纯函数：该宽度下侧栏是否必须处于折叠（64px）形态。
 *
 * @param width 视口宽度（px）。
 * @returns `true` 表示折叠。
 */
export function isCollapsedAtWidth(width: number): boolean {
  return width <= BP.lg;
}

/**
 * 纯函数：该宽度下侧栏是否必须改为抽屉（浮层 + 遮罩）。
 *
 * @param width 视口宽度（px）。
 * @returns `true` 表示抽屉形态。
 */
export function isDrawerAtWidth(width: number): boolean {
  return width <= BP.sm;
}

/**
 * 读取当前视口宽度（无 `window` 时回退到 1440，保证可单测）。
 *
 * @returns 视口宽度（px）。
 */
export function currentViewportWidth(): number {
  if (typeof window === 'undefined') return 1440;
  return window.innerWidth || 1440;
}
