import type { QuickTargetId } from './shellNav';

export interface NavHistoryState {
  entries: QuickTargetId[];
  index: number;
}

export function createNavHistory(initialTarget: QuickTargetId): NavHistoryState {
  return {
    entries: [initialTarget],
    index: 0,
  };
}

export function pushNavHistory(
  state: NavHistoryState,
  target: QuickTargetId,
  maxLength = 24,
): NavHistoryState {
  if (state.entries[state.index] === target) {
    return state;
  }
  const truncated = state.entries.slice(0, state.index + 1);
  truncated.push(target);
  if (truncated.length > maxLength) {
    const overflow = truncated.length - maxLength;
    const trimmed = truncated.slice(overflow);
    return {
      entries: trimmed,
      index: trimmed.length - 1,
    };
  }
  return {
    entries: truncated,
    index: truncated.length - 1,
  };
}

export function canStepBack(state: NavHistoryState): boolean {
  return state.index > 0;
}

export function canStepForward(state: NavHistoryState): boolean {
  return state.index >= 0 && state.index < state.entries.length - 1;
}

export function stepNavHistory(
  state: NavHistoryState,
  direction: 'back' | 'forward',
): { nextState: NavHistoryState; target: QuickTargetId | null } {
  if (direction === 'back') {
    if (!canStepBack(state)) return { nextState: state, target: null };
    const nextIndex = state.index - 1;
    return {
      nextState: { entries: state.entries, index: nextIndex },
      target: state.entries[nextIndex] ?? null,
    };
  }
  if (!canStepForward(state)) return { nextState: state, target: null };
  const nextIndex = state.index + 1;
  return {
    nextState: { entries: state.entries, index: nextIndex },
    target: state.entries[nextIndex] ?? null,
  };
}

export type DispatchIslandMode = 'running' | 'error' | 'idle';

export interface DispatchIslandInput {
  runningTask: string | null;
  progress: number;
  progressText: string;
  activeDownloadCount: number;
  approvalActiveCount: number;
  errorLogCount: number;
  readyChannelCount: number;
  totalChannelCount: number;
}

export interface DispatchIslandModel {
  mode: DispatchIslandMode;
  primaryText: string;
  secondaryText: string;
  progressPct: number | null;
  indeterminate: boolean;
  action: 'open-logs' | 'open-history' | 'open-cmdk';
}

export function resolveDispatchIslandState(input: DispatchIslandInput): DispatchIslandModel {
  const totalRunning =
    (input.runningTask ? 1 : 0) +
    Math.max(0, input.activeDownloadCount) +
    Math.max(0, input.approvalActiveCount);

  if (totalRunning > 0) {
    const clampedPct = Number.isFinite(input.progress)
      ? Math.max(0, Math.min(100, Math.round(input.progress)))
      : 0;
    const hasDeterminateProgress = Boolean(input.runningTask) && clampedPct > 0 && clampedPct < 100;
    const cleanText = (input.progressText || '').trim();
    const primaryText =
      cleanText ||
      (input.runningTask
        ? '核算引擎执行中'
        : input.activeDownloadCount > 0
          ? `${input.activeDownloadCount} 项资料采集中`
          : `${input.approvalActiveCount} 项价格审批处理中`);
    return {
      mode: 'running',
      primaryText,
      secondaryText: hasDeterminateProgress
        ? `${clampedPct}%`
        : `${totalRunning} 项运行中`,
      progressPct: hasDeterminateProgress ? clampedPct : null,
      indeterminate: !hasDeterminateProgress,
      action: input.runningTask ? 'open-logs' : 'open-history',
    };
  }

  if (input.errorLogCount > 0) {
    return {
      mode: 'error',
      primaryText: `检测到 ${input.errorLogCount} 条运行异常`,
      secondaryText: '查看日志',
      progressPct: null,
      indeterminate: false,
      action: 'open-logs',
    };
  }

  return {
    mode: 'idle',
    primaryText: '跳转模块、平台或操作…',
    secondaryText:
      input.totalChannelCount > 0
        ? `${input.readyChannelCount}/${input.totalChannelCount} 通道在线`
        : '⌘K',
    progressPct: null,
    indeterminate: false,
    action: 'open-cmdk',
  };
}

export const PLATFORM_MATRIX_GLYPHS: Record<string, { glyph: string; name: string }> = {
  fengshen: { glyph: '风', name: '风神' },
  lanorange: { glyph: '蓝', name: '蓝橙' },
  baize: { glyph: '商', name: '商翼' },
  benlai: { glyph: '本', name: '本来' },
  xiaoxiang: { glyph: '象', name: '灯塔' },
};
