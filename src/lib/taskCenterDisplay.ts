import { isGlobalDataset } from './downloadCenterLogic';

export type TaskPlatformTone = 'fengshen' | 'xiaoxiang' | 'lanorange' | 'payout' | 'neutral';

export interface TaskDisplayRecord {
  id: string;
  kind: string;
  title?: string;
  price_id?: string;
  cities: string[];
  datasets: string[];
  start: string;
  end: string;
  status: string;
  created_at: string;
  updated_at?: string;
  elapsed_seconds?: number;
  error?: string;
  files: { id: string; run_id?: string; name: string; city?: string; bytes: number; available?: boolean; unavailable_reason?: string }[];
  source_files?: { id: string; run_id?: string; name: string; city?: string; bytes: number; available?: boolean; unavailable_reason?: string }[];
  available_files: number;
  failed_items: number;
  completed_items: number;
  total_items: number;
  summary_issue?: boolean;
}

export interface TaskPrimaryAction {
  type: 'restore' | 'attention' | 'download' | 'price';
  label: string;
  tone: 'primary' | 'warn' | 'danger' | 'neutral';
}

const KNOWN_PREFIXES = [
  '风神',
  '灯塔',
  '小象灯塔',
  '蓝橙',
  '蓝橙价格审批',
  '待审每日价格导出',
  '商翼',
  '本来人力',
  '业务报表',
  '资料下载',
  '价格审批',
  '每日价格',
];

/**
 * 去除任务标题中与「来源 / 类型」列重复的前缀，让首列只保留核心业务内容。
 */
export function cleanTaskTitle(rawTitle: string, platformName?: string, kindLabel?: string): string {
  const trimmed = (rawTitle || '').trim();
  if (!trimmed) return '未命名任务';
  const prefixes = new Set(KNOWN_PREFIXES);
  if (platformName) prefixes.add(platformName.trim());
  if (kindLabel) prefixes.add(kindLabel.trim());

  const sepMatch = /^([^·\-—:：]{2,12})\s*[·\-—:：]\s*(.+)$/.exec(trimmed);
  if (sepMatch) {
    const head = sepMatch[1].trim();
    const rest = sepMatch[2].trim();
    if (rest && prefixes.has(head)) {
      return rest;
    }
  }
  return trimmed;
}

const INTERNAL_TASK_PREFIX = /^(?:approval|price-export|payroll_source|payroll|generate|download)[:_]/;

/**
 * 内部任务 ID 带类型前缀与长哈希；界面只显示与交付目录一致的 6 位短编号，完整值放悬停提示。
 */
export function displayTaskNumber(id: string): string {
  const body = (id || '').trim().replace(INTERNAL_TASK_PREFIX, '');
  return /^[0-9a-f]{8,}$/i.test(body) ? body.slice(0, 6).toUpperCase() : body;
}

export function platformTone(platformName: string): TaskPlatformTone {
  if (/风神/.test(platformName)) return 'fengshen';
  if (/灯塔|小象/.test(platformName)) return 'xiaoxiang';
  if (/蓝橙/.test(platformName)) return 'lanorange';
  if (/商翼|本来/.test(platformName)) return 'payout';
  return 'neutral';
}

function cleanDatasetDisplayLabel(rawLabel: string, platformName?: string): string {
  let label = rawLabel
    .replace(/[（(](?:生成表|灯塔|小象灯塔|全量|风神|蓝橙|商翼|本来人力)[）)]/g, '')
    .trim();
  const redundantHeads = [
    ...(platformName ? [platformName.trim()] : []),
    '本来人力',
    '小象灯塔',
    '风神',
    '灯塔',
    '蓝橙',
    '商翼',
  ].filter(Boolean);
  for (const head of redundantHeads) {
    if (label.startsWith(head) && label.length > head.length + 1) {
      label = label.slice(head.length).replace(/^[\s·\-—:：]+/, '').trim();
      break;
    }
  }
  return label || rawLabel.trim();
}

/**
 * 规范化任务内容展示：优先按结构化资料项精简拼接（最多显示 2 项 + 「等N项」），
 * 去除与「覆盖范围」「业务周期」「来源/类型」重复的城市、月份与平台前缀，保持列表整齐清爽。
 */
export function formatTaskContentDisplay(
  task: Pick<TaskDisplayRecord, 'kind' | 'title' | 'datasets' | 'cities'>,
  options: {
    datasetLabel: (id: string) => string;
    platformName?: string;
    kindLabel?: string;
  },
): { short: string; full: string } {
  const rawTitle = (task.title || '').trim();
  const rawLabels = Array.from(
    new Set(
      (task.datasets || [])
        .map(id => options.datasetLabel(id).replaceAll('（生成表）', '').trim())
        .filter(Boolean),
    ),
  );

  if (rawLabels.length > 0) {
    const cleanLabels = Array.from(
      new Set(rawLabels.map(label => cleanDatasetDisplayLabel(label, options.platformName)).filter(Boolean)),
    );
    const full = rawLabels.join('、');
    if (cleanLabels.length === 1) return { short: cleanLabels[0], full };
    if (cleanLabels.length === 2) return { short: `${cleanLabels[0]}、${cleanLabels[1]}`, full };
    return { short: `${cleanLabels[0]}、${cleanLabels[1]} 等${cleanLabels.length}项`, full };
  }

  let normalized = cleanTaskTitle(rawTitle, options.platformName, options.kindLabel);
  if (normalized === '未命名任务') {
    if (task.kind === 'approval') return { short: '价格批量审批', full: '价格批量审批' };
    if (task.kind === 'price-export') return { short: '待审每日价格导出', full: '待审每日价格导出' };
    return { short: normalized, full: normalized };
  }

  // 去除前导城市列表（如「上海/深圳/广州 」「华东 4 城 」）与前导月份（如「10月」「2026年10月」）
  const cityNames = (task.cities || []).map(c => c.trim()).filter(c => c && c !== '全量' && c !== '按业务筛选范围');
  if (cityNames.length) {
    const escaped = cityNames.map(c => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    const leadingCitiesRe = new RegExp(`^(?:(?:${escaped})(?:\\s*[/、,，]\\s*(?:${escaped}))*)\\s+`);
    normalized = normalized.replace(leadingCitiesRe, '');
    const trailingParenCitiesRe = new RegExp(`[（(](?:${escaped})(?:\\s*[/、,，]\\s*(?:${escaped}))*[）)]$`);
    normalized = normalized.replace(trailingParenCitiesRe, '');
  }
  normalized = normalized
    .replace(/^(?:华东|华南|华北|西南|西北|东北|华中)?\s*\d+\s*城\s+/, '')
    .replace(/^(?:\d{4}年)?\d{1,2}月(?:\s*)/, '')
    .replace(/[（(](?:全量|全授权城市|全部城市)[）)]/g, '')
    .replace(/\s*(?:同步任务|全量拉取|巡检)$/, '')
    .trim();

  const short = normalized || cleanTaskTitle(rawTitle, options.platformName, options.kindLabel);
  return { short, full: rawTitle || short };
}

export function formatCitiesCompact(cities: string[], datasets: string[] = []): { short: string; full: string } {
  const list = (cities || []).map(c => c.trim()).filter(Boolean);
  if (!list.length) {
    if (datasets.length > 0 && datasets.every(isGlobalDataset)) {
      return { short: '全量', full: '全量数据' };
    }
    return { short: '全部城市', full: '全部城市' };
  }
  if (list.length === 1 && list[0] === '全量') {
    return { short: '全量', full: '全量范围' };
  }
  if (list.length === 1 && list[0] === '按业务筛选范围') {
    return { short: '按筛选范围', full: '按业务筛选范围' };
  }
  const full = list.join('、');
  if (list.length <= 2) return { short: full, full };
  return { short: `${list[0]}等${list.length}城`, full };
}

function shortDate(value?: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec((value || '').trim());
  return match ? `${match[2]}.${match[3]}` : (value || '').trim();
}

export function formatPeriodCompact(
  start: string,
  end: string,
  datasets: string[],
  kind?: string,
): { short: string; full: string } {
  if (!datasets.length) {
    if (kind === 'approval') return { short: '单次审批', full: '价格批量审批批次' };
    if (kind === 'price-export') return { short: '按筛选范围', full: '按业务筛选范围导出' };
    return { short: '—', full: '详见业务记录' };
  }
  if (datasets.every(isGlobalDataset)) return { short: '全量数据', full: '全量数据' };
  if (datasets.every(id => id === 'rider_archive')) return { short: '当前快照', full: '当前最新快照' };
  const s = shortDate(start);
  const e = shortDate(end);
  if (s && e) {
    if (s === e) return { short: s, full: start };
    return { short: `${s} - ${e}`, full: `${start} 至 ${end}` };
  }
  const fallback = s || e || '—';
  return { short: fallback, full: start || end || '—' };
}

export function canPermanentlyDeleteTask(task: Pick<TaskDisplayRecord, 'status'>): boolean {
  return !['queued', 'running', 'waiting_login', 'waiting_manual', 'cancelling', 'preparing', 'stopping'].includes(
    task.status,
  );
}

/**
 * 列表紧凑时间：今天/昨天仅显示时分，跨天显示 MM-DD HH:mm，悬停展示完整时间。
 */
export function formatCompactTimestamp(iso?: string, nowMs: number = Date.now()): { short: string; full: string } {
  if (!iso) return { short: '—', full: '—' };
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return { short: iso, full: iso };

  const full = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);

  const fmtParts = (d: Date) => {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(d);
    const get = (t: string) => parts.find(p => p.type === t)?.value || '';
    return {
      ymd: `${get('year')}-${get('month')}-${get('day')}`,
      md: `${get('month')}-${get('day')}`,
      hm: `${get('hour')}:${get('minute')}`,
    };
  };

  const target = fmtParts(date);
  const today = fmtParts(new Date(nowMs));
  const yesterday = fmtParts(new Date(nowMs - 86_400_000));

  if (target.ymd === today.ymd) {
    return { short: `今天 ${target.hm}`, full };
  }
  if (target.ymd === yesterday.ymd) {
    return { short: `昨天 ${target.hm}`, full };
  }
  return { short: `${target.md.replace('-', '.')} ${target.hm}`, full };
}

/**
 * 为列表行收敛唯一场景主操作，消除「查看进度 + 详情」「停止 + 停止并移出」等重复按钮噪音。
 */
export function resolveTaskPrimaryAction(
  task: Pick<TaskDisplayRecord, 'status' | 'kind' | 'price_id' | 'available_files' | 'failed_items' | 'summary_issue'>,
  archived = false,
): TaskPrimaryAction | null {
  if (archived) {
    return { type: 'restore', label: '恢复', tone: 'primary' };
  }
  if (task.status === 'waiting_login' || task.status === 'waiting_manual') {
    return { type: 'attention', label: '去验证', tone: 'warn' };
  }
  if (task.status === 'needs_review') {
    return { type: 'attention', label: '去核实', tone: 'warn' };
  }
  if (['error', 'failed', 'interrupted'].includes(task.status)) {
    return { type: 'attention', label: '查看原因', tone: 'danger' };
  }
  if (task.status === 'partial' || (task.failed_items > 0 && task.status !== 'running' && task.status !== 'queued') || task.summary_issue) {
    return { type: 'attention', label: '处理异常', tone: 'warn' };
  }
  if (task.status === 'success') {
    if (task.price_id && task.kind === 'approval') {
      return { type: 'price', label: '看回执', tone: 'primary' };
    }
    if (task.available_files > 0) {
      return { type: 'download', label: '下载', tone: 'primary' };
    }
  }
  return null;
}

const ACTIVE_DIR_BLOCKED_STATUSES = new Set([
  'queued',
  'running',
  'waiting_login',
  'waiting_manual',
  'cancelling',
  'preparing',
  'stopping',
]);

/**
 * 判断任务行是否可在操作列展示「打开本地结果目录」快捷按钮。
 */
export function canOpenTaskResultDirectory(
  task: Pick<TaskDisplayRecord, 'status' | 'kind' | 'available_files'>,
  archived = false,
): boolean {
  if (archived) return false;
  if (task.available_files > 0) return true;
  if (ACTIVE_DIR_BLOCKED_STATUSES.has(task.status)) return false;
  if (task.kind === 'approval' && task.status === 'success') return true;
  if (task.kind === 'price-export') return task.available_files > 0;
  if (task.status === 'empty') return false;
  return ['success', 'partial', 'error', 'failed', 'interrupted', 'cancelled', 'stopped'].includes(task.status);
}

/**
 * 仅在存在真实异常、阻塞或空数据时返回一行诊断说明；健康任务返回空串以保持首列极致清爽。
 */
export function computeTaskDiagnosticNote(
  task: Pick<TaskDisplayRecord, 'status' | 'error' | 'failed_items' | 'completed_items' | 'total_items'>,
): { text: string; tone: 'warn' | 'error' | 'muted' } | null {
  const err = (task.error || '').trim();
  if (['error', 'failed', 'interrupted'].includes(task.status)) {
    return { text: err || '执行遇到异常，点击查看原因并处理', tone: 'error' };
  }
  if (['waiting_login', 'waiting_manual', 'partial'].includes(task.status)) {
    if (err) return { text: err, tone: 'warn' };
    if (task.failed_items > 0) {
      return { text: `${task.failed_items} 项未完成，已有文件可先下载`, tone: 'warn' };
    }
    return {
      text: task.status === 'waiting_login' ? '平台登录态失效，请重新授权后继续' : '等待人工安全验证完成后继续',
      tone: 'warn',
    };
  }
  if (task.status === 'empty') {
    return { text: err || '所选区间无业务数据，未生成空文件', tone: 'muted' };
  }
  return null;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB';
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

export interface TaskTimelineStep {
  time: string;
  text: string;
  tone?: 'normal' | 'warn' | 'error' | 'success';
}

export function buildTaskTimelineSteps(task: TaskDisplayRecord, platformName: string): TaskTimelineStep[] {
  const clock = (iso?: string) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return '—';
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(d);
  };

  const steps: TaskTimelineStep[] = [
    {
      time: clock(task.created_at),
      text: `任务已创建（${platformName} · 共 ${Math.max(1, task.total_items)} 项采集/生成子任务）`,
      tone: 'normal',
    },
  ];

  if (task.status === 'queued') {
    steps.push({ time: '当前', text: '正在排队等待采集通道释放', tone: 'normal' });
    return steps;
  }

  if (task.completed_items > 0 && task.status !== 'success') {
    steps.push({
      time: clock(task.updated_at || task.created_at),
      text: `已完成 ${task.completed_items} / ${Math.max(1, task.total_items)} 项，产出 ${task.available_files} 个可用文件`,
      tone: 'normal',
    });
  }

  if (task.status === 'running') {
    steps.push({ time: '进行中', text: '后台持续同步中，完成后将自动归档结果文件', tone: 'normal' });
  } else if (task.status === 'waiting_login' || task.status === 'waiting_manual') {
    steps.push({
      time: clock(task.updated_at),
      text: task.error || '任务已暂停，等待完成平台认证或人工验证后自动继续',
      tone: 'warn',
    });
  } else if (task.status === 'partial') {
    steps.push({
      time: clock(task.updated_at),
      text: task.error || `部分完成：成功 ${task.completed_items} 项，失败 ${task.failed_items} 项`,
      tone: 'warn',
    });
  } else if (['error', 'failed', 'interrupted'].includes(task.status)) {
    steps.push({
      time: clock(task.updated_at),
      text: task.error || '任务执行中断，请核对原因后重新发起',
      tone: 'error',
    });
  } else if (task.status === 'cancelled' || task.status === 'cancelling') {
    steps.push({
      time: clock(task.updated_at),
      text: task.status === 'cancelling' ? '正在安全中止执行中的子请求' : '任务已手动停止，历史记录已保留',
      tone: 'normal',
    });
  } else if (task.status === 'empty') {
    steps.push({
      time: clock(task.updated_at),
      text: task.error || '平台返回 0 条业务记录，未生成空文件',
      tone: 'normal',
    });
  } else if (task.status === 'success') {
    steps.push({
      time: clock(task.updated_at),
      text: `全部 ${Math.max(1, task.total_items)} 项处理完成，已归档 ${task.available_files} 个可下载结果文件`,
      tone: 'success',
    });
  }

  return steps;
}

export type TaskAuthSystem = 'fengshen' | 'baize' | 'benlai' | 'xiaoxiang' | 'lanorange';

const XIAOXIANG_DATASETS = new Set([
  'rider_daily',
  'rider_archive',
  'detail_orders',
  'detail_kesu',
  'detail_reviews',
  'rider_order_detail',
  'xiaoxiang_attendance_detail',
]);

/**
 * 根据任务数据集或业务类型解析需要触发认证/验证的来源平台标识。
 */
export function resolveTaskAuthSystem(
  task: Pick<TaskDisplayRecord, 'kind' | 'price_id' | 'datasets'>,
): TaskAuthSystem {
  if (task.price_id || task.kind === 'approval' || task.kind === 'price-export') {
    return 'lanorange';
  }
  const sets = task.datasets || [];
  if (sets.some(id => id === 'baize_employees')) return 'baize';
  if (sets.some(id => id === 'benlai_employees')) return 'benlai';
  if (sets.some(id => id === 'lanorange_summary')) return 'lanorange';
  if (sets.some(id => XIAOXIANG_DATASETS.has(id))) return 'xiaoxiang';
  return 'fengshen';
}

export function isTaskRetryable(task: Pick<TaskDisplayRecord, 'status' | 'kind'>): boolean {
  if (!['download', 'generate', 'payroll_source'].includes(task.kind)) return false;
  return ['error', 'failed', 'interrupted', 'partial', 'cancelled'].includes(task.status);
}

export type TaskDatePreset = 'today' | '7d' | 'month';

export function computeDatePresetRange(
  preset: TaskDatePreset,
  nowMs: number = Date.now(),
): { from: string; to: string } {
  const toYmd = (ms: number) => {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date(ms));
    const get = (t: string) => parts.find(p => p.type === t)?.value || '';
    return `${get('year')}-${get('month')}-${get('day')}`;
  };
  const today = toYmd(nowMs);
  if (preset === 'today') {
    return { from: today, to: today };
  }
  if (preset === '7d') {
    return { from: toYmd(nowMs - 6 * 86_400_000), to: today };
  }
  return { from: `${today.slice(0, 7)}-01`, to: today };
}

export interface TaskBatchSelectionSummary {
  total: number;
  downloadableIds: string[];
  downloadableCount: number;
  skippedDownloadCount: number;
  activeIds: string[];
  activeCount: number;
}

const BATCH_ACTIVE_SET = new Set([
  'queued',
  'running',
  'waiting_login',
  'waiting_manual',
  'preparing',
]);

/**
 * 智能拆分已选任务中的「可打包下载子集」与「可停止运行中子集」，避免全选混入不可下载任务导致按钮整体失效。
 */
export function summarizeTaskBatchSelection(
  chosen: Pick<TaskDisplayRecord, 'id' | 'kind' | 'status' | 'available_files'>[],
): TaskBatchSelectionSummary {
  const downloadableIds = chosen
    .filter(r => ['download', 'generate', 'payroll_source'].includes(r.kind) && r.available_files > 0)
    .slice(0, 20)
    .map(r => r.id);
  const activeIds = chosen
    .filter(r => BATCH_ACTIVE_SET.has(r.status))
    .map(r => r.id);
  return {
    total: chosen.length,
    downloadableIds,
    downloadableCount: downloadableIds.length,
    skippedDownloadCount: Math.max(0, chosen.length - downloadableIds.length),
    activeIds,
    activeCount: activeIds.length,
  };
}

export type TaskCenterSortKey = 'created_desc' | 'elapsed_desc' | 'files_desc';

export function sortTaskDisplayRecords<T extends Pick<TaskDisplayRecord, 'created_at' | 'elapsed_seconds' | 'available_files'>>(
  records: T[],
  sortKey: TaskCenterSortKey,
): T[] {
  const copy = [...records];
  if (sortKey === 'created_desc') {
    copy.sort((a, b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0));
    return copy;
  }
  if (sortKey === 'elapsed_desc') {
    copy.sort((a, b) => (b.elapsed_seconds || 0) - (a.elapsed_seconds || 0));
  } else if (sortKey === 'files_desc') {
    copy.sort((a, b) => (b.available_files || 0) - (a.available_files || 0));
  }
  return copy;
}

export interface TaskProgressPopoverData {
  badgeLabel: string;
  tone: 'active' | 'waiting' | 'success' | 'error' | 'muted';
  percent: number | null;
  elapsedLabel: string;
  elapsedValue: string;
  currentNode: string;
  metrics: Array<{
    label: string;
    value: string;
    tone?: 'default' | 'accent' | 'warn' | 'danger' | 'success';
  }>;
  footnote?: string;
}

export function buildTaskProgressPopoverData(
  task: Pick<
    TaskDisplayRecord,
    'status' | 'created_at' | 'updated_at' | 'completed_items' | 'total_items' | 'failed_items' | 'available_files' | 'error'
  > & { files?: TaskDisplayRecord['files'] },
  options: {
    statusLabel: string;
    tone: 'active' | 'waiting' | 'success' | 'error' | 'muted';
    percent: number | null;
    elapsedText: string;
    platformName?: string;
    diagNote?: { text: string; tone: 'warn' | 'error' | 'muted' } | null;
    nowMs?: number;
  },
): TaskProgressPopoverData {
  const total = Math.max(1, task.total_items || 0);
  const completed = Math.max(0, Math.min(total, task.completed_items || 0));
  const failed = Math.max(0, task.failed_items || 0);
  const availableFiles =
    typeof task.available_files === 'number'
      ? Math.max(0, task.available_files)
      : Array.isArray(task.files)
        ? task.files.filter((file) => file.available !== false).length
        : 0;
  const platformPrefix = options.platformName ? `${options.platformName}` : '来源平台';

  let currentNode = options.diagNote?.text || '';
  if (!currentNode) {
    switch (task.status) {
      case 'queued':
        currentNode = `已进入调度队列，等待 ${platformPrefix} 采集通道释放`;
        break;
      case 'running':
      case 'preparing':
        currentNode = `正在抓取并校验 ${platformPrefix} 业务数据（已完成 ${completed} / ${total} 项）`;
        break;
      case 'cancelling':
      case 'stopping':
        currentNode = `正在安全中止执行中的子项请求（已完成 ${completed} / ${total} 项）`;
        break;
      case 'waiting_login':
        currentNode = `等待完成 ${platformPrefix} 登录授权后自动恢复采集`;
        break;
      case 'waiting_manual':
        currentNode = `触发 ${platformPrefix} 安全校验，完成人工验证后继续执行`;
        break;
      case 'partial':
        currentNode = `已完成 ${completed} 项，${failed || 1} 项待处理，已有文件可先行下载`;
        break;
      case 'success':
        currentNode = `全部 ${total} 项已采集完成，归档 ${availableFiles} 个可下载文件`;
        break;
      case 'cancelled':
        currentNode = '任务已手动停止，历史执行记录与已有文件已保留';
        break;
      case 'empty':
        currentNode = '所选范围未返回业务记录，未生成空白文件';
        break;
      case 'needs_review':
        currentNode = '平台回执状态待核实，请点击「去核实」确认最终结果';
        break;
      default:
        currentNode = task.error || '正在同步任务执行状态';
        break;
    }
  }

  const created = formatCompactTimestamp(task.created_at, options.nowMs);
  const metrics: TaskProgressPopoverData['metrics'] = [
    {
      label: '子项进度',
      value: `${completed} / ${total} 项`,
      tone: task.status === 'success' ? 'success' : failed > 0 ? 'warn' : 'default',
    },
    {
      label: '创建时间',
      value: created.short,
    },
  ];

  if (failed > 0) {
    metrics.push({
      label: '异常子项',
      value: `${failed} 项失败`,
      tone: 'danger',
    });
  } else if (availableFiles > 0 || task.status === 'success') {
    metrics.push({
      label: '产出文件',
      value: `${availableFiles} 个`,
      tone: availableFiles > 0 ? 'accent' : 'default',
    });
  }

  if (task.updated_at && task.updated_at !== task.created_at) {
    const updated = formatCompactTimestamp(task.updated_at, options.nowMs);
    metrics.push({
      label: task.status === 'success' ? '完成时间' : '最近更新',
      value: updated.short,
    });
  }

  const pct =
    options.percent !== null && Number.isFinite(options.percent)
      ? Math.max(0, Math.min(100, Math.round(options.percent)))
      : task.status === 'success'
        ? 100
        : null;

  return {
    badgeLabel: options.statusLabel,
    tone: options.tone,
    percent: pct,
    elapsedLabel: '任务耗时',
    elapsedValue: options.elapsedText && options.elapsedText !== '—' ? options.elapsedText : '—',
    currentNode,
    metrics: metrics.slice(0, 4),
  };
}


