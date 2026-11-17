/**
 * 状态语义单一数据源：5 个 tone + legacy 字面量归一。
 *
 * 设计约束（架构 §7.2）：样式层只认 5 个 tone（`success/warn/danger/progress/neutral`），
 * 全站不允许出现颜色词类名。存量组件（`PayrollQueueWorkbench`、`DownloadRecords`、
 * `SystemConnections`、`App`）输出的历史字面量（`muted`/`active`/`waiting`/`busy`…）
 * 一律经 `normalizeTone()` 归一后使用，**不修改任何压缩 lib 模块里的字面量**。
 *
 * 约束：本文件为纯函数，不引入依赖，不包含 DOM 逻辑。
 */

/** 全站唯一的状态语义色调。 */
export type Tone = 'success' | 'warn' | 'danger' | 'progress' | 'neutral';

/** 采集任务（下载 / 生成）状态色调。 */
export type TaskTone = Tone;

/** 核算批次状态色调。 */
export type PayrollTone = Tone;

/** 平台连接状态色调。 */
export type ConnectionTone = Tone;

/** 5 个 tone 的固定顺序，供色板/图例遍历。 */
export const TONE_ORDER: Tone[] = ['success', 'warn', 'danger', 'progress', 'neutral'];

/** legacy 字面量 → tone 的归一映射（大小写不敏感）。 */
const LEGACY_TONE_MAP: Record<string, Tone> = {
  // 中性
  muted: 'neutral',
  idle: 'neutral',
  info: 'neutral',
  neutral: 'neutral',
  queued: 'neutral',
  queue: 'neutral',
  pending: 'neutral',
  stopping: 'neutral',
  cancelled: 'neutral',
  canceled: 'neutral',
  offline: 'neutral',
  unknown: 'neutral',
  planned: 'neutral',
  disabled: 'neutral',
  // 进行中
  active: 'progress',
  running: 'progress',
  busy: 'progress',
  progress: 'progress',
  preparing: 'progress',
  calculating: 'progress',
  starting: 'progress',
  refreshing: 'progress',
  connecting: 'progress',
  uploading: 'progress',
  processing: 'progress',
  // 警告
  waiting: 'warn',
  warning: 'warn',
  warn: 'warn',
  partial: 'warn',
  busy_partial: 'warn',
  interrupted: 'warn',
  pending_confirmation: 'warn',
  waiting_confirmation: 'warn',
  waiting_login: 'warn',
  waiting_manual: 'warn',
  needs_review: 'warn',
  pending_download: 'warn',
  // 成功
  success: 'success',
  ready: 'success',
  completed: 'success',
  complete: 'success',
  done: 'success',
  finished: 'success',
  // 失败
  error: 'danger',
  failed: 'danger',
  fail: 'danger',
  danger: 'danger',
  critical: 'danger',
};

/**
 * 把任意历史色调字面量归一为 5 个 tone 之一。
 *
 * @param legacyTone 历史字面量（可空、可大小写混写、可带下划线）。
 * @returns 归一后的 tone，未识别时返回 `neutral`。
 */
export function normalizeTone(legacyTone?: string | null): Tone {
  if (!legacyTone) return 'neutral';
  const key = String(legacyTone).trim().toLowerCase();
  return LEGACY_TONE_MAP[key] || 'neutral';
}

/**
 * tone → `wbx-pill` 修饰类名。
 *
 * @param tone 状态语义色调。
 * @returns 形如 `wbx-pill--success` 的类名。
 */
export function toneClass(tone: Tone | string | null | undefined): string {
  return `wbx-pill--${normalizeTone(tone)}`;
}

/**
 * 采集任务状态 → tone。
 *
 * @param status 任务状态字面量（`queued`/`running`/`completed`/`error`…）。
 * @returns 归一后的 tone。
 */
export function taskTone(status?: string | null): Tone {
  return normalizeTone(status);
}

/**
 * 核算批次状态 → tone。
 *
 * @param status 批次状态字面量（`preparing`/`calculating`/`completed`/`failed`…）。
 * @returns 归一后的 tone。
 */
export function payrollTone(status?: string | null): Tone {
  return normalizeTone(status);
}

/**
 * 平台连接状态 → tone。
 *
 * @param state 连接状态：字符串，或 `{state, offline, busy}` 结构（`SystemConnections` 口径）。
 * @returns 归一后的 tone；`offline` 优先判定为 `neutral`。
 */
export function connectionTone(
  state?: string | { state?: string; offline?: boolean; busy?: boolean } | null,
): ConnectionTone {
  if (!state) return 'neutral';
  if (typeof state === 'string') return normalizeTone(state);
  if (state.offline) return 'neutral';
  if (state.state === 'ready') return 'success';
  if (state.state === 'error') return 'danger';
  if (state.busy) return 'progress';
  if (state.state === 'partial') return 'warn';
  return normalizeTone(state.state);
}

/**
 * tone → 状态灯点位类名（`wb-dot` 沿用旧实现的三态映射）。
 *
 * @param tone 状态语义色调。
 * @returns `ready` / `offline` / `busy` / 空串。
 */
export function dotClass(tone: Tone): string {
  if (tone === 'success') return 'ready';
  if (tone === 'warn' || tone === 'danger') return 'offline';
  if (tone === 'progress') return 'busy';
  return '';
}
