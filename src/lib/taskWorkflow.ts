import { datasetGroup } from './downloadCenterLogic';
import {
  SPECIAL_REPORT_SUBMODULES,
  type ShellCommandAction,
  type ShellNavState,
} from './shellNav';

export const AUTO_JUMP_STORAGE_KEY = 'workbench_auto_jump_task_center';

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface TaskReturnTarget {
  label: string;
  action: ShellCommandAction;
}

export interface TaskNotificationRecord {
  id: string;
  status: string;
  kind?: string;
  title?: string;
  datasets?: string[];
  cities?: string[];
  available_files?: number;
  failed_items?: number;
  summary_issue?: boolean;
  action_run_id?: string;
  current_action?: string;
  error?: string;
}

export interface TaskStatusAlert {
  key: string;
  taskId: string;
  kind: 'completed' | 'blocked';
  status: string;
  title: string;
  subtitle: string;
  primarySystem: string;
  canOpenDir: boolean;
  needsAuth: boolean;
  createdAt: number;
}

export const RUNNING_TASK_STATUSES = new Set([
  'queued',
  'running',
  'preparing',
  'cancelling',
  'stopping',
]);

export const WAITING_BLOCKED_STATUSES = new Set([
  'waiting_login',
  'waiting_manual',
]);

export const FAILURE_BLOCKED_STATUSES = new Set([
  'error',
  'failed',
  'interrupted',
  'partial',
]);

export const ACTIVE_OR_WAITING_STATUSES = new Set([
  ...RUNNING_TASK_STATUSES,
  ...WAITING_BLOCKED_STATUSES,
]);

const PLATFORM_LABELS: Record<string, string> = {
  fengshen: '风神数据',
  lanorange: '蓝橙数据',
  payout: '发薪平台',
  xiaoxiang: '小象灯塔',
};

const PAYROLL_SUBVIEW_LABELS: Record<string, string> = {
  batches: '兼职核算',
  deductions: '扣款配置',
  templates: '模板中心',
};

export function readAutoJumpPreference(storage?: StorageLike | null): boolean {
  const target = storage === undefined ? getSafeLocalStorage() : storage;
  if (!target) return true;
  try {
    const raw = target.getItem(AUTO_JUMP_STORAGE_KEY);
    if (raw === '0' || raw === 'false') return false;
    return true;
  } catch {
    return true;
  }
}

export function writeAutoJumpPreference(enabled: boolean, storage?: StorageLike | null): void {
  const target = storage === undefined ? getSafeLocalStorage() : storage;
  if (!target) return;
  try {
    target.setItem(AUTO_JUMP_STORAGE_KEY, enabled ? '1' : '0');
  } catch {
    // Ignore restricted storage environments.
  }
}

function getSafeLocalStorage(): StorageLike | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Ignore SSR or restricted contexts.
  }
  return null;
}

export function buildTaskReturnTarget(state: ShellNavState): TaskReturnTarget | null {
  if (
    state.workspaceView === 'history' ||
    state.workspaceView === 'pickup' ||
    state.workspaceView === 'accounts' ||
    state.workspaceView === 'platform-auth'
  ) {
    return null;
  }

  if (state.workspaceView === 'approval') {
    return {
      label: '返回价格审批',
      action: { type: 'workspace', view: 'approval' },
    };
  }
  if (state.workspaceView === 'price-export') {
    return {
      label: '返回每日价格',
      action: { type: 'workspace', view: 'price-export' },
    };
  }
  if (state.taskKind === 'generate') {
    const report =
      SPECIAL_REPORT_SUBMODULES.find(item => item.id === state.reportId) ||
      SPECIAL_REPORT_SUBMODULES[0];
    return {
      label: `返回${report.label}`,
      action: { type: 'report', reportId: report.id },
    };
  }
  if (state.taskKind === 'payroll') {
    const subLabel = PAYROLL_SUBVIEW_LABELS[state.payrollSubView] || '兼职核算';
    return {
      label: `返回${subLabel}`,
      action: { type: 'payroll', subView: state.payrollSubView },
    };
  }

  const platformLabel = PLATFORM_LABELS[state.downloadPlatform] || '风神数据';
  return {
    label: `返回${platformLabel}`,
    action: { type: 'platform', platform: state.downloadPlatform },
  };
}

export function resolveNotificationTitle(
  record: TaskNotificationRecord,
  datasetLabel?: (id: string) => string,
): string {
  const rawTitle = (record.title || '').trim();
  if (rawTitle) return rawTitle.replaceAll('（生成表）', '');
  const datasets = record.datasets || [];
  if (datasets.length > 0) {
    const names = datasets.map(id => (datasetLabel ? datasetLabel(id) : id));
    const joined = names.slice(0, 2).join('、').replaceAll('（生成表）', '');
    return names.length > 2 ? `${joined} 等 ${names.length} 项` : joined;
  }
  return '后台采集任务';
}

export function computeTaskHeaderCounts(records: ReadonlyArray<{ status: string }>): {
  activeCount: number;
  attentionCount: number;
  readyCount: number;
} {
  let activeCount = 0;
  let attentionCount = 0;
  let readyCount = 0;
  for (const r of records) {
    if (RUNNING_TASK_STATUSES.has(r.status)) {
      activeCount += 1;
    } else if (WAITING_BLOCKED_STATUSES.has(r.status)) {
      attentionCount += 1;
    } else if (r.status === 'success') {
      readyCount += 1;
    } else if (FAILURE_BLOCKED_STATUSES.has(r.status)) {
      attentionCount += 1;
    }
  }
  return { activeCount, attentionCount, readyCount };
}

export function detectTaskNotifications(
  prevSnapshot: ReadonlyMap<string, string> | null,
  nextRecords: ReadonlyArray<TaskNotificationRecord>,
  seenKeys: ReadonlySet<string>,
  options: {
    now?: number;
    datasetLabel?: (id: string) => string;
  } = {},
): {
  alerts: TaskStatusAlert[];
  nextSnapshot: Map<string, string>;
} {
  const nextSnapshot = new Map<string, string>();
  for (const record of nextRecords) {
    if (record?.id) {
      nextSnapshot.set(record.id, record.status);
    }
  }

  // Never emit alerts during initial hydration.
  if (prevSnapshot === null) {
    return { alerts: [], nextSnapshot };
  }

  const now = options.now ?? Date.now();
  const alerts: TaskStatusAlert[] = [];

  for (const record of nextRecords) {
    if (!record?.id) continue;
    const prevStatus = prevSnapshot.get(record.id);
    if (!prevStatus || prevStatus === record.status) continue;

    const dedupeKey = `${record.id}:${record.status}`;
    if (seenKeys.has(dedupeKey)) continue;

    const wasActiveOrWaiting = ACTIVE_OR_WAITING_STATUSES.has(prevStatus);
    const wasRunning = RUNNING_TASK_STATUSES.has(prevStatus);
    const title = resolveNotificationTitle(record, options.datasetLabel);
    const firstDataset = record.datasets?.[0] || '';
    const primarySystem = firstDataset ? datasetGroup(firstDataset) || 'fengshen' : 'fengshen';

    if (wasActiveOrWaiting && record.status === 'success') {
      const fileCount = record.available_files ?? 0;
      alerts.push({
        key: dedupeKey,
        taskId: record.id,
        kind: 'completed',
        status: record.status,
        title,
        subtitle: fileCount > 0 ? `已生成 ${fileCount} 个结果文件，可直接打开目录或下载` : '任务执行完成，可查看详情与结果',
        primarySystem,
        canOpenDir: record.kind !== 'approval' && record.kind !== 'price-export',
        needsAuth: false,
        createdAt: now,
      });
      continue;
    }

    if (wasRunning && WAITING_BLOCKED_STATUSES.has(record.status)) {
      const needsAuth = record.status === 'waiting_login';
      alerts.push({
        key: dedupeKey,
        taskId: record.id,
        kind: 'blocked',
        status: record.status,
        title,
        subtitle: needsAuth
          ? '平台登录态已失效或需要扫码验证，请验证后继续执行'
          : record.current_action || '任务暂停，需要人工确认后继续',
        primarySystem,
        canOpenDir: false,
        needsAuth,
        createdAt: now,
      });
      continue;
    }

    if (wasActiveOrWaiting && FAILURE_BLOCKED_STATUSES.has(record.status)) {
      const isPartial = record.status === 'partial';
      alerts.push({
        key: dedupeKey,
        taskId: record.id,
        kind: 'blocked',
        status: record.status,
        title,
        subtitle: isPartial
          ? `部分分项失败（${record.failed_items || 1} 项），已生成文件可先查看`
          : record.error || '执行过程中遇到异常，请进入任务中心查看原因',
        primarySystem,
        canOpenDir: isPartial && (record.available_files ?? 0) > 0,
        needsAuth: false,
        createdAt: now,
      });
    }
  }

  return { alerts, nextSnapshot };
}
