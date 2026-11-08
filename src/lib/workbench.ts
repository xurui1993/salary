export type DeductionRow = Record<string, string | number | boolean | null>;
export function validateDeductionRows(value: unknown): DeductionRow[] {
  if (!Array.isArray(value) || !value.length) throw new Error('配置必须包含至少一个站点');
  const keys = new Set<string>();
  for (const row of value) {
    if (!row || typeof row !== 'object' || Array.isArray(row) || !String(row['城市'] || '').trim() || !String(row['团队名称'] || '').trim()) throw new Error('每个站点都需要城市和团队名称');
    const key = JSON.stringify([row['城市'], row['团队名称'], row['团队ID'] || '']);
    if (keys.has(key)) throw new Error('存在重复站点，请核对城市、团队名称和团队 ID');
    keys.add(key);
    for (const value of Object.values(row)) {
      if (value !== null && !['string', 'number', 'boolean'].includes(typeof value)) throw new Error('配置字段必须为文本、数字或开关');
      if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('金额必须为有效数字');
    }
  }
  return value;
}

export function connectionLabel(state?: string) {
  if (state === 'partial') return '部分已验证';
  if (state === 'ready') return '已连接';
  if (state === 'unknown') return '状态未知';
  if (state === 'planned') return '待接入';
  if (['saved'].includes(state || '')) return '待验证';
  if (['starting', 'refreshing', 'sending', 'verifying'].includes(state || '')) return '检查中';
  if (['waiting_login', 'login_required', 'sms_sent', 'manual_required'].includes(state || '')) return '需要验证';
  if (state === 'error') return '连接异常';
  return '未连接';
}

export function connectionSummary(systems: {state?: string; offline?: boolean}[]): string {
  if (!systems.length || systems.some(system => system.offline || system.state === 'unknown' || !system.state)) return '状态未知';
  if (systems.every(system => system.state === 'ready')) return '连接正常';
  if (systems.some(system => system.state === 'error')) return '连接异常';
  if (systems.some(system => ['partial','waiting_login', 'login_required', 'sms_sent', 'manual_required'].includes(system.state || ''))) return '需验证';
  if (systems.some(system => ['starting', 'refreshing'].includes(system.state || ''))) return '连接中';
  return '需连接';
}

export type SystemKey = 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang' | 'dengta';

export interface SystemMetaItem {
  key: SystemKey;
  label: '风神' | '蓝橙' | '商翼' | '小象灯塔' | '灯塔';
  businessLine: string;
  description: string;
  planned?: boolean;
}

export const SYSTEM_META: SystemMetaItem[] = [
  { key: 'fengshen', label: '风神', businessLine: '淘宝闪购自有系统', description: '配送费、违规扣款、月度UB账单、骑手绑定、欺诈/问题单等核心账单数据源。' },
  { key: 'lanorange', label: '蓝橙', businessLine: '原雷神', description: '原雷神 · 骑手人事档案、兼职价格档案、离职/批量离职、请假等内部人事数据源。' },
  { key: 'baize', label: '商翼', businessLine: '商翼系统', description: '商翼全部员工原表独立下载；不随兼职核算自动补齐。' },
  { key: 'xiaoxiang', label: '灯塔', businessLine: '美团灯塔系统', description: '商配送骑手订单明细与日维度骑手分析，独立下载。' },
  { key: 'dengta', label: '灯塔', businessLine: '美团灯塔系统', description: '灯塔薪资申请表与配送资料手动上传核算。' },
];

export type BillingPeriodPreset =
  | 'last_full_month'
  | 'current_first_half'
  | 'last_second_half'
  | 'current_month_to_date';

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function daysInMonth(year: number, month1Based: number): number {
  return new Date(Date.UTC(year, month1Based, 0)).getUTCDate();
}

export function computeBillingPeriodRange(
  preset: BillingPeriodPreset,
  referenceDateStr: string,
): { start: string; end: string; label: string } {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(referenceDateStr.trim());
  const now = match
    ? { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) }
    : { year: 2026, month: 1, day: 15 };

  const prevYear = now.month === 1 ? now.year - 1 : now.year;
  const prevMonth = now.month === 1 ? 12 : now.month - 1;
  const prevMonthDays = daysInMonth(prevYear, prevMonth);

  if (preset === 'last_full_month') {
    return {
      start: `${prevYear}-${pad2(prevMonth)}-01`,
      end: `${prevYear}-${pad2(prevMonth)}-${pad2(prevMonthDays)}`,
      label: '上月整月',
    };
  }
  if (preset === 'current_first_half') {
    return {
      start: `${now.year}-${pad2(now.month)}-01`,
      end: `${now.year}-${pad2(now.month)}-15`,
      label: '本月1-15日',
    };
  }
  if (preset === 'last_second_half') {
    return {
      start: `${prevYear}-${pad2(prevMonth)}-16`,
      end: `${prevYear}-${pad2(prevMonth)}-${pad2(prevMonthDays)}`,
      label: '上月16-月末',
    };
  }
  return {
    start: `${now.year}-${pad2(now.month)}-01`,
    end: `${now.year}-${pad2(now.month)}-${pad2(now.day)}`,
    label: '本月至今',
  };
}

export function computeLighthousePeriodRange(
  preset: BillingPeriodPreset,
  referenceDateStr: string,
): { start: string; end: string; label: string; blocked: boolean } {
  const range = computeBillingPeriodRange(preset, referenceDateStr);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(referenceDateStr.trim());
  if (!match) return { ...range, blocked: false };
  const latest = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  latest.setUTCDate(latest.getUTCDate() - 1);
  const latestStr = latest.toISOString().slice(0, 10);
  if (preset === 'current_first_half' && range.end > latestStr) {
    return { ...range, end: latestStr, blocked: true };
  }
  if (range.end > latestStr) {
    return { ...range, end: latestStr, blocked: range.start > latestStr };
  }
  return { ...range, blocked: false };
}

export function buildRecentMonths(referenceDateStr: string, count = 12): string[] {
  const match = /^(\d{4})-(\d{2})/.exec(referenceDateStr.trim());
  const year = match ? Number(match[1]) : 2026;
  const month = match ? Number(match[2]) : 1;
  return Array.from({ length: count }, (_, index) => {
    const value = new Date(Date.UTC(year, month - 1 - index, 1));
    return `${value.getUTCFullYear()}-${pad2(value.getUTCMonth() + 1)}`;
  });
}

export function computeMonthSelectionRange(
  monthStr: string,
  referenceDateStr: string,
  options: { capAtYesterday?: boolean } = {},
): { start: string; end: string } {
  const monthMatch = /^(\d{4})-(\d{2})$/.exec(monthStr.trim());
  const refTrimmed = referenceDateStr.trim();
  const refMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(refTrimmed);

  let effectiveToday = refTrimmed;
  if (options.capAtYesterday && refMatch) {
    const yesterday = new Date(Date.UTC(Number(refMatch[1]), Number(refMatch[2]) - 1, Number(refMatch[3])));
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    effectiveToday = yesterday.toISOString().slice(0, 10);
  }

  if (!monthMatch) {
    return {
      start: `${effectiveToday.slice(0, 7)}-01`,
      end: effectiveToday,
    };
  }
  const year = Number(monthMatch[1]);
  const month = Number(monthMatch[2]);
  const ym = `${year}-${pad2(month)}`;
  const start = `${ym}-01`;
  if (refMatch && refTrimmed.slice(0, 7) === ym) {
    return { start, end: effectiveToday < start ? start : effectiveToday };
  }
  const lastDay = daysInMonth(year, month);
  return { start, end: `${ym}-${pad2(lastDay)}` };
}

export interface BuiltinScenarioPreset {
  id: string;
  name: string;
  systemTag: '风神' | '蓝橙';
  description: string;
  datasets: string[];
}

export const BUILTIN_DOWNLOAD_SCENARIOS: BuiltinScenarioPreset[] = [
  {
    id: 'shangou_monthly_payroll',
    name: '闪购月度核算包',
    systemTag: '风神',
    description: '配送费 + 违规扣款 + 月度UB账单 + 骑手风神绑定 + 骑手信息',
    datasets: ['delivery_fee', 'penalty', 'rider_monthly', 'receive_account', 'rider_info'],
  },
  {
    id: 'shangou_daily_monitor',
    name: '闪购日常监控包',
    systemTag: '风神',
    description: '骑手数据明细 + 欺诈单 + 问题单',
    datasets: ['rider_detail', 'fraud', 'problem'],
  },
  {
    id: 'lanorange_hr_full',
    name: '蓝橙人事全量包',
    systemTag: '蓝橙',
    description: '骑手档案 + 价格档案 + 离职/批量离职 + 请假全量表',
    datasets: [
      'lanorange_rider_archive',
      'lanorange_part_price',
      'lanorange_rider_quit',
      'lanorange_batch_quit',
      'lanorange_rider_leave',
    ],
  },
];

export function inferDatasetSystemTag(datasetId: string, mode?: string): '风神' | '蓝橙' | '商翼' | '小象灯塔' | '灯塔' {
  if (mode === 'xiaoxiang') return '灯塔';
  const normalized = (datasetId || '').toLowerCase();
  if (normalized === 'rider_daily' || normalized === 'rider_archive' || normalized === 'detail_orders' || normalized === 'detail_kesu' || normalized === 'detail_reviews' || normalized === 'rider_order_detail' || normalized === 'xiaoxiang_attendance_detail') return '灯塔';
  if (normalized.includes('shangyi') || normalized.includes('baize')) return '商翼';
  if (normalized.startsWith('lanorange') || normalized === 'abnormal_riders' || normalized === 'part_price' || normalized === 'rider_profile') {
    return '蓝橙';
  }
  return '风神';
}

export interface GenerationReportCardMeta {
  id: 'payment_binding' | 'abnormal_followup' | 'abnormal_riders';
  title: string;
  systems: ('风神' | '蓝橙')[];
  granularity: string;
  summary: string;
  requiresCityAndDate: boolean;
}

export const GENERATION_REPORT_CARDS: GenerationReportCardMeta[] = [
  {
    id: 'payment_binding',
    title: '骑手支付绑定',
    systems: ['风神', '蓝橙'],
    granularity: '按城市 · 按月拆分',
    summary: '自动关联风神收薪绑定与原雷神人事档案，输出周期内有单骑手支付绑定表及多城汇总。',
    requiresCityAndDate: true,
  },
  {
    id: 'abnormal_followup',
    title: '异常骑手跟进',
    systems: ['风神', '蓝橙'],
    granularity: '按城市 · 按月拆分',
    summary: '以支付绑定为基准，关联物资租用、月度UB账单、价格与骑手档案，定位异常待跟进名单。',
    requiresCityAndDate: true,
  },
  {
    id: 'abnormal_riders',
    title: '异常骑手整理',
    systems: ['蓝橙'],
    granularity: '全部城市 · 全量交付',
    summary: '自动汇总原雷神 5 类离职、请假与骑手档案，无需风神登录即可生成全城异常整理工作簿。',
    requiresCityAndDate: false,
  },
];

export interface PayrollModeCardMeta {
  id: 'fengshen' | 'manual' | 'xiaoxiang';
  title: string;
  systems: ('风神' | '蓝橙' | '灯塔')[];
  subtitle: string;
  badge?: string;
}

export const PAYROLL_MODE_CARDS: PayrollModeCardMeta[] = [
  {
    id: 'fengshen',
    title: '淘宝闪购 · 自动齐套',
    systems: ['风神', '蓝橙'],
    subtitle: '上传薪资申请表后，自动拉取风神账单与原雷神人事档案',
    badge: '推荐',
  },
  {
    id: 'manual',
    title: '淘宝闪购 · 手动上传',
    systems: ['风神', '蓝橙'],
    subtitle: '随薪资申请表一并上传或逐项补传风神与原雷神原始资料',
  },
  {
    id: 'xiaoxiang',
    title: '美团灯塔 · 手动上传',
    systems: ['灯塔'],
    subtitle: '上传灯塔薪资申请表与日期配送单',
    badge: '独立引擎',
  },
];

export function extractDeductionColumns(rows: DeductionRow[]): {
  metaColumns: string[];
  deductionColumns: string[];
} {
  const metaColumns = ['城市', '团队名称', '团队ID'];
  const metaSet = new Set(metaColumns);
  const seen = new Set<string>();
  const deductionColumns: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (metaSet.has(key) || seen.has(key) || key.endsWith('_isKw') || key === '说明') continue;
      seen.add(key);
      deductionColumns.push(key);
    }
  }
  return { metaColumns, deductionColumns };
}

export function classifyTemplateCategory(filename: string): {
  tag: '淘宝闪购' | '美团小象' | '通用模板';
  badgeClass: string;
} {
  const lower = (filename || '').toLowerCase();
  if (lower.includes('小象') || lower.includes('灯塔') || lower.includes('美团') || lower.includes('xiaoxiang')) {
    return { tag: '美团小象', badgeClass: 'is-dengta' };
  }
  if (lower.includes('闪购') || lower.includes('风神') || lower.includes('template') || lower.includes('兼职')) {
    return { tag: '淘宝闪购', badgeClass: 'is-fengshen' };
  }
  return { tag: '通用模板', badgeClass: 'is-lanorange' };
}

export function getWorkbenchBreadcrumb(
  workspaceView: 'create' | 'history' | 'approval' | 'price-export',
  taskKind: 'download' | 'generate' | 'payroll',
): { section: string; title: string; subtitle: string } {
  if (workspaceView === 'approval') return {section:'业务审批',title:'蓝橙价格审批',subtitle:'筛选本人价格提审，跨页勾选后预览并批量同意当前节点'};
  if (workspaceView === 'price-export') return {section:'蓝橙价格',title:'待审每日价格导出',subtitle:'获取有权限站点的最新待审版本，生成骑手每日价格Excel'};
  if (workspaceView === 'history') {
    return {
      section: '任务与归档',
      title: '任务与产出中心',
      subtitle: '统一查看任务、下载结果和整理历史记录',
    };
  }
  if (taskKind === 'generate') {
    return {
      section: '新建业务',
      title: '业务报表生成',
      subtitle: '选择目标业务报表，系统自动关联风神与蓝橙底层资料生成成品表',
    };
  }
  if (taskKind === 'payroll') {
    return {
      section: '新建业务',
      title: '兼职薪资结算',
      subtitle: '上传申请表，自动识别范围并准备资料、核算，完成后下载结果',
    };
  }
  return {
    section: '新建业务',
    title: '资料下载采集',
    subtitle: '风神按城市与账期采集，蓝橙全量交付，商翼员工原表独立下载；灯塔手动上传',
  };
}

export function getPayrollSidebarBadge(
  status?: string,
  isRunning?: boolean,
): { label: string; tone: 'active' | 'warn' | 'ready' | 'done' } | null {
  if (isRunning || status === 'calculating' || status === 'preparing') {
    return { label: '核算中', tone: 'active' };
  }
  if (status === 'pending_download' || status === 'waiting_materials') {
    return { label: '待补齐', tone: 'warn' };
  }
  if (status === 'ready') {
    return { label: '待核算', tone: 'ready' };
  }
  if (status === 'calculated') {
    return { label: '已出表', tone: 'done' };
  }
  return null;
}

export interface SidebarNavItemSpec {
  id: string;
  label: string;
  iconKey:
    | 'compass'
    | 'layers'
    | 'users-round'
    | 'radar'
    | 'bar-chart-3'
    | 'wallet-cards'
    | 'badge-dollar-sign'
    | 'folder-check'
    | 'sliders-horizontal'
    | 'file-spreadsheet';
}

export interface SidebarNavGroupSpec {
  id: 'collection' | 'business' | 'archive';
  title: '数据采集' | '核算与业务' | '归档与配置';
  items: SidebarNavItemSpec[];
}

export const SIDEBAR_NAV_GROUPS: SidebarNavGroupSpec[] = [
  {
    id: 'collection',
    title: '数据采集',
    items: [
      { id: 'fengshen', label: '风神数据', iconKey: 'compass' },
      { id: 'lanorange', label: '蓝橙数据', iconKey: 'layers' },
      { id: 'baize', label: '白泽商翼', iconKey: 'users-round' },
      { id: 'xiaoxiang', label: '小象灯塔', iconKey: 'radar' },
    ],
  },
  {
    id: 'business',
    title: '核算与业务',
    items: [
      { id: 'generate', label: '专项报表', iconKey: 'bar-chart-3' },
      { id: 'payroll', label: '薪资核算', iconKey: 'wallet-cards' },
      { id: 'approval', label: '价格审批', iconKey: 'badge-dollar-sign' },
    ],
  },
  {
    id: 'archive',
    title: '归档与配置',
    items: [
      { id: 'history', label: '任务中心', iconKey: 'folder-check' },
      { id: 'deductions', label: '扣款规则', iconKey: 'sliders-horizontal' },
      { id: 'templates', label: '模板中心', iconKey: 'file-spreadsheet' },
    ],
  },
];

export interface HeaderModuleContext {
  groupLabel: '数据采集' | '核算与业务' | '归档与配置';
  title: string;
  subtitle: string;
  iconKey: SidebarNavItemSpec['iconKey'];
}

export function getHeaderModuleContext(
  workspaceView: 'create' | 'history' | 'approval' | 'price-export',
  taskKind: 'download' | 'generate' | 'payroll',
  downloadPlatform: 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang',
  historyAll: boolean,
): HeaderModuleContext {
  if (workspaceView === 'approval' || workspaceView === 'price-export') {
    return {
      groupLabel: '核算与业务',
      title: '价格审批',
      subtitle: workspaceView === 'approval'
        ? '筛选本人蓝橙价格提审，跨页勾选后预览并批量审批'
        : '拉取有权限站点的最新待审版本，导出骑手每日价格表',
      iconKey: 'badge-dollar-sign',
    };
  }
  if (workspaceView === 'history' && historyAll) {
    return {
      groupLabel: '归档与配置',
      title: '任务中心',
      subtitle: '统一查看任务、下载结果和整理历史记录',
      iconKey: 'folder-check',
    };
  }
  if (taskKind === 'generate') {
    return {
      groupLabel: '核算与业务',
      title: '专项报表',
      subtitle: '骑手支付绑定、异常骑手跟进、异常骑手整理自动关联生成',
      iconKey: 'bar-chart-3',
    };
  }
  if (taskKind === 'payroll') {
    return {
      groupLabel: '核算与业务',
      title: '薪资核算',
      subtitle: '上传薪资申请表，自动识别范围、齐套资料并执行兼职核算',
      iconKey: 'wallet-cards',
    };
  }
  if (downloadPlatform === 'lanorange') {
    return {
      groupLabel: '数据采集',
      title: '蓝橙数据',
      subtitle: '原雷神骑手档案、兼职价格、离职与请假全量资料采集',
      iconKey: 'layers',
    };
  }
  if (downloadPlatform === 'baize') {
    return {
      groupLabel: '数据采集',
      title: '白泽商翼',
      subtitle: '商翼系统全量员工原始档案独立下载与记录巡检',
      iconKey: 'users-round',
    };
  }
  if (downloadPlatform === 'xiaoxiang') {
    return {
      groupLabel: '数据采集',
      title: '小象灯塔',
      subtitle: '灯塔商配送日维度骑手分析、骑手档案与订单明细采集',
      iconKey: 'radar',
    };
  }
  return {
    groupLabel: '数据采集',
    title: '风神数据',
    subtitle: '按城市与账期采集配送费、违规扣款、UB账单及考勤源表',
    iconKey: 'compass',
  };
}

export interface StageHeaderMeta {
  title: string;
  createTabLabel: '新建下载' | '生成报表';
  historyTabLabel: '本模块记录';
  subtitle: string;
}

export function getStageHeaderMeta(
  taskKind: 'download' | 'generate',
  platform?: 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang',
  view: 'create' | 'history' = 'create',
): StageHeaderMeta {
  if (taskKind === 'generate') {
    return {
      title: '业务报表',
      createTabLabel: '生成报表',
      historyTabLabel: '本模块记录',
      subtitle:
        view === 'history'
          ? '查看本模块已生成的业务报表进度并领取产出文件。'
          : '选择目标表，系统自动关联来源资料。',
    };
  }
  const titleMap: Record<'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang', string> = {
    fengshen: '风神下载',
    lanorange: '蓝橙下载',
    baize: '商翼下载',
    xiaoxiang: '灯塔下载',
  };
  const title = platform ? titleMap[platform] : '资料下载';
  return {
    title,
    createTabLabel: '新建下载',
    historyTabLabel: '本模块记录',
    subtitle:
      view === 'history'
        ? '查看本模块采集任务进度、核对分项状态并领取产出文件。'
        : '选择所需资料，再确认处理范围。',
  };
}


export type PlatformDotTone = 'ready' | 'warn' | 'busy' | 'idle';

export interface PlatformStatusChip {
  key: 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang';
  shortLabel: '风神' | '蓝橙' | '商翼' | '灯塔';
  tone: PlatformDotTone;
  statusText: string;
}

export function getPlatformStatusCluster(
  states: Record<string, { state?: string; busy?: boolean; offline?: boolean } | undefined>,
  fengshenFallback?: { state?: string; busy?: boolean; offline?: boolean } | null,
): PlatformStatusChip[] {
  const defs: { key: PlatformStatusChip['key']; shortLabel: PlatformStatusChip['shortLabel'] }[] = [
    { key: 'fengshen', shortLabel: '风神' },
    { key: 'lanorange', shortLabel: '蓝橙' },
    { key: 'baize', shortLabel: '商翼' },
    { key: 'xiaoxiang', shortLabel: '灯塔' },
  ];
  return defs.map(({ key, shortLabel }) => {
    const raw = states[key] || (key === 'fengshen' ? fengshenFallback || {} : {});
    const state = raw?.state || '';
    if (raw?.offline) {
      return { key, shortLabel, tone: 'idle', statusText: '状态未知' };
    }
    if (state === 'ready') {
      return { key, shortLabel, tone: 'ready', statusText: '已连接' };
    }
    if (raw?.busy || ['starting', 'refreshing', 'sending', 'verifying'].includes(state)) {
      return { key, shortLabel, tone: 'busy', statusText: '连接中' };
    }
    if (['waiting_login', 'login_required', 'sms_sent', 'manual_required', 'partial', 'error'].includes(state)) {
      return { key, shortLabel, tone: 'warn', statusText: connectionLabel(state) };
    }
    return { key, shortLabel, tone: 'idle', statusText: connectionLabel(state) };
  });
}

export function getPlatformCardBadge(
  value: { state?: string; offline?: boolean; busy?: boolean; cancelling?: boolean; release_state?: string },
  pendingAction?: string,
): { label: string; tone: PlatformDotTone } {
  if (pendingAction === 'logout') return { label: '退出中', tone: 'busy' };
  if (pendingAction === 'verify') return { label: '验证中', tone: 'busy' };
  if (value.offline) return { label: '连接不可用', tone: 'idle' };
  if (value.cancelling) return { label: '退出中', tone: 'busy' };
  if (value.state === 'ready') return { label: '已连接', tone: 'ready' };
  if (
    ['releasing', 'timeout', 'terminated', 'unconfirmed', 'starting', 'checking', 'refreshing', 'sending', 'verifying'].includes(
      value.release_state || value.state || '',
    )
  ) {
    return { label: '连接中', tone: 'busy' };
  }
  if (
    ['waiting_login', 'sms_sent', 'manual_required', 'saved'].includes(value.state || '') ||
    (value.state === 'login_required' && value.busy)
  ) {
    return { label: '需验证', tone: 'warn' };
  }
  if (value.state === 'partial') return { label: '部分可用', tone: 'warn' };
  if (value.state === 'unknown') return { label: '状态待确认', tone: 'idle' };
  return { label: '未登录', tone: 'idle' };
}


export interface NotificationTaskFile {
  id: string;
  name: string;
  city: string;
  bytes: number;
  url?: string;
}

export interface NotificationTaskItem {
  id: string;
  title: string;
  scopeText: string;
  periodText?: string;
  systemTag: '风神' | '蓝橙' | '商翼' | '小象灯塔' | '灯塔';
  kind: 'download' | 'generate' | 'payroll' | 'approval' | 'price-export';
  status: 'running' | 'blocked' | 'completed' | 'failed';
  progress?: number;
  phaseText?: string;
  availableFiles: number;
  claimed?: boolean;
  createdAt?: string;
  batchId?: string;
  outputPath?: string;
  actionRunId?: string;
  platformKey?: 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang';
  files?: NotificationTaskFile[];
}

export interface DownloadCapsuleState {
  mode: 'running' | 'blocked' | 'completed' | 'idle';
  tone: 'active' | 'warn' | 'ready' | 'idle';
  label: string;
  progress?: number;
  runningCount: number;
  blockedCount: number;
  unclaimedCount: number;
  unclaimedFileCount: number;
  failedCount?: number;
  totalCount: number;
}

export function computeDownloadCapsuleState(tasks: NotificationTaskItem[]): DownloadCapsuleState {
  const runningTasks = tasks.filter(item => item.status === 'running');
  const blockedTasks = tasks.filter(item => item.status === 'blocked');
  const failedTasks = tasks.filter(item => item.status === 'failed');
  const unclaimedTasks = tasks.filter(
    item => item.status === 'completed' && item.availableFiles > 0 && !item.claimed,
  );
  const unclaimedFileCount = unclaimedTasks.reduce((sum, item) => sum + item.availableFiles, 0);

  if (blockedTasks.length > 0) {
    return {
      mode: 'blocked',
      tone: 'warn',
      label: `${blockedTasks.length} 项任务等待登录验证`,
      runningCount: runningTasks.length,
      blockedCount: blockedTasks.length,
      unclaimedCount: unclaimedTasks.length,
      unclaimedFileCount,
      failedCount: failedTasks.length,
      totalCount: tasks.length,
    };
  }

  if (runningTasks.length > 0) {
    const first = runningTasks[0];
    const avgProgress = Math.max(
      1,
      Math.min(
        99,
        Math.round(
          runningTasks.reduce((sum, item) => sum + (item.progress ?? 50), 0) / runningTasks.length,
        ),
      ),
    );
    const label =
      runningTasks.length === 1
        ? `${first.title} (${Math.round(first.progress ?? avgProgress)}%)`
        : `${runningTasks.length} 项任务进行中 (${avgProgress}%)`;
    return {
      mode: 'running',
      tone: 'active',
      label,
      progress: avgProgress,
      runningCount: runningTasks.length,
      blockedCount: 0,
      unclaimedCount: unclaimedTasks.length,
      unclaimedFileCount,
      failedCount: failedTasks.length,
      totalCount: tasks.length,
    };
  }

  if (unclaimedTasks.length > 0) {
    return {
      mode: 'completed',
      tone: 'ready',
      label: `下载已完成 · ${unclaimedFileCount} 份文件待领取`,
      runningCount: 0,
      blockedCount: 0,
      unclaimedCount: unclaimedTasks.length,
      unclaimedFileCount,
      failedCount: failedTasks.length,
      totalCount: tasks.length,
    };
  }

  return {
    mode: 'idle',
    tone: 'idle',
    label: tasks.length > 0 ? `下载通知 · ${tasks.length}` : '下载通知',
    runningCount: 0,
    blockedCount: 0,
    unclaimedCount: 0,
    unclaimedFileCount: 0,
    failedCount: failedTasks.length,
    totalCount: tasks.length,
  };
}

export type NotificationFilterTab = 'all' | 'downloading' | 'completed' | 'failed';

export function filterNotificationTasks(
  tasks: NotificationTaskItem[],
  filter: NotificationFilterTab,
): NotificationTaskItem[] {
  if (filter === 'downloading') {
    return tasks.filter(item => item.status === 'running' || item.status === 'blocked');
  }
  if (filter === 'completed') {
    return tasks.filter(item => item.status === 'completed');
  }
  if (filter === 'failed') {
    return tasks.filter(item => item.status === 'failed');
  }
  return tasks;
}

export function toggleNotificationFilterTab(
  current: NotificationFilterTab,
  clicked: 'downloading' | 'completed' | 'failed',
): NotificationFilterTab {
  return current === clicked ? 'all' : clicked;
}

export function getDefaultSeedNotifications(): NotificationTaskItem[] {
  return [
    {
      id: 'seed_fengshen_active',
      title: '风神采集中 · 宁波等3城',
      scopeText: '宁波、杭州、上海 · 配送费、违规扣款',
      periodText: '2026-09-01 ~ 2026-09-30',
      systemTag: '风神',
      kind: 'download',
      status: 'running',
      progress: 65,
      phaseText: '正在导出并合并城市账单分片',
      availableFiles: 0,
      platformKey: 'fengshen',
      createdAt: '刚刚',
    },
    {
      id: 'seed_fengshen_ready',
      title: '闪购月度核算包 · 深圳、广州',
      scopeText: '深圳、广州 · 配送费 + 月度UB账单 + 骑手绑定',
      periodText: '2026-09-01 ~ 2026-09-30',
      systemTag: '风神',
      kind: 'download',
      status: 'completed',
      progress: 100,
      phaseText: '已完成校验与归档',
      availableFiles: 2,
      claimed: false,
      platformKey: 'fengshen',
      createdAt: '10 分钟前',
      files: [
        { id: 'f1', name: '深圳_广州_闪购月度核算汇总_202609.xlsx', city: '深圳、广州', bytes: 428032 },
        { id: 'f2', name: '深圳_广州_风神骑手绑定与UB明细_202609.csv', city: '深圳、广州', bytes: 194560 },
      ],
    },
    {
      id: 'seed_shangyi_ready',
      title: '商翼员工资料（全量）',
      scopeText: '全部城市 · 商翼系统全量员工原始档案',
      periodText: '全量快照',
      systemTag: '商翼',
      kind: 'download',
      status: 'completed',
      progress: 100,
      phaseText: '已完成全量导出',
      availableFiles: 1,
      claimed: false,
      platformKey: 'baize',
      createdAt: '25 分钟前',
      files: [
        { id: 'f3', name: '商翼全量员工原始档案_202610.xlsx', city: '全部城市', bytes: 612352 },
      ],
    },
    {
      id: 'seed_lanorange_failed',
      title: '蓝橙骑手档案 · 导出异常',
      scopeText: '全部站点 · 蓝橙全量骑手原始档案',
      periodText: '全量快照',
      systemTag: '蓝橙',
      kind: 'download',
      status: 'failed',
      availableFiles: 0,
      claimed: false,
      platformKey: 'lanorange',
      createdAt: '30 分钟前',
      phaseText: '导出请求超时，请在任务中心重试或检查配置',
    },
  ];
}

export type DatasetCardTone = 'city' | 'monthly' | 'snapshot' | 'merchant' | 'full' | 'lighthouse';

export interface DatasetCardMeta {
  id: string;
  title: string;
  scopeTag: string;
  tone: DatasetCardTone;
  desc: string;
}

const DATASET_CARD_META_MAP: Record<string, Omit<DatasetCardMeta, 'id'>> = {
  // 风神数据
  invitation_records: {
    title: '邀请记录',
    scopeTag: '城市·全量',
    tone: 'city',
    desc: '支持多选城市，分别下载各城市全部邀请记录',
  },
  attendance_detail: {
    title: '骑手出勤明细',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '支持多选城市，按近90天内的日期下载各城市出勤明细',
  },
  delivery_fee: {
    title: '配送费',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '城市站点完单量、基础配送费与补贴',
  },
  penalty: {
    title: '违规扣款',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '投诉、超时、差评等违规罚扣流水',
  },
  rider_monthly: {
    title: '月度 UB 账单',
    scopeTag: '城市·按月',
    tone: 'monthly',
    desc: '自然月度骑手UB综合核算汇总账单',
  },
  fraud: {
    title: '欺诈单',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '异常虚假妥投、刷单及风控稽核表',
  },
  problem: {
    title: '问题单',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '配送异常、餐损及物流责任判定表',
  },
  receive_account: {
    title: '骑手风神绑定',
    scopeTag: '城市·按月',
    tone: 'monthly',
    desc: '骑手收薪账户与风神身份绑定关系',
  },
  rider_detail: {
    title: '骑手数据明细',
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '骑手日均单量、时长与准时率明细',
  },
  rider_info: {
    title: '骑手信息导出',
    scopeTag: '城市·快照',
    tone: 'snapshot',
    desc: '在网骑手基础身份、团队与入职表',
  },
  goods_rent: {
    title: '物资租用登记',
    scopeTag: '城市·快照',
    tone: 'snapshot',
    desc: '工服、餐箱及电池领用扣款登记表',
  },
  // 蓝橙数据
  lanorange_rider_quit: {
    title: '骑手离职',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '全城骑手正常离职审批与交接明细',
  },
  lanorange_rider_report: {
    title: '离职报备',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '各站点上报骑手离职报备流水记录',
  },
  lanorange_batch_quit: {
    title: '批量离职',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '站点集中清退与批量离职归档记录',
  },
  lanorange_rider_leave: {
    title: '骑手请假',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '全部城市骑手病事假、休假审批表',
  },
  lanorange_identity_change: {
    title: '骑手兼全职变更',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '专送与众包兼全职身份转换记录表',
  },
  lanorange_salary_replace: {
    title: '佣金代领',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '骑手薪资佣金代发代领授权关系表',
  },
  lanorange_part_price: {
    title: '价格档案',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '各城市站点兼职阶梯单价与补贴表',
  },
  lanorange_rider_archive: {
    title: '骑手档案',
    scopeTag: '全城·全量',
    tone: 'full',
    desc: '原雷神在职与离职骑手人事总档案',
  },
  // 白泽商翼
  baize_employees: {
    title: '商翼员工资料',
    scopeTag: '全站·全量',
    tone: 'full',
    desc: '导出商翼系统全量在职与离职员工原始档案表，独立归档不参与兼职自动补齐',
  },
  // 小象灯塔
  rider_daily: {
    title: '日维度骑手分析',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '商配送骑手日维度单量与人效分析',
  },
  rider_archive: {
    title: '骑手档案',
    scopeTag: '全城·快照',
    tone: 'lighthouse',
    desc: '灯塔全城骑手身份与站点归属快照',
  },
  detail_orders: {
    title: '配送订单明细',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '商配送逐单运单状态与时效距离表',
  },
  detail_kesu: {
    title: '配送客诉明细',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '商配送客户投诉、索赔与判责明细',
  },
  detail_reviews: {
    title: '配送评价明细',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '订单客户星级评价与好差评标签表',
  },
  rider_order_detail: {
    title: '骑手订单明细',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '灯塔周通知【商配送】骑手订单明细附件按数据日期区间合并',
  },
  xiaoxiang_attendance_detail: {
    title: '骑手出勤明细',
    scopeTag: '全城·日期',
    tone: 'lighthouse',
    desc: '灯塔「合作商数据下发」通知骑手出勤明细附件按数据日期区间合并',
  },
};

export function getDatasetCardMeta(datasetId: string, rawLabel?: string): DatasetCardMeta {
  const cleanLabel = (rawLabel || datasetId)
    .replaceAll('白泽', '商翼')
    .replaceAll('小象灯塔', '灯塔')
    .replaceAll('小象', '灯塔')
    .replace(/（灯塔）$/, '');
  const known = DATASET_CARD_META_MAP[datasetId];
  if (known) {
    return {
      id: datasetId,
      title: known.title || cleanLabel,
      scopeTag: known.scopeTag,
      tone: known.tone,
      desc: known.desc,
    };
  }
  if (datasetId.startsWith('lanorange_')) {
    return {
      id: datasetId,
      title: cleanLabel,
      scopeTag: '全城·全量',
      tone: 'full',
      desc: '蓝橙系统全量人事与业务归档数据表',
    };
  }
  return {
    id: datasetId,
    title: cleanLabel,
    scopeTag: '城市·账期',
    tone: 'city',
    desc: '按所选城市与业务账期采集导出原表',
  };
}

export interface CalendarDayCell {
  dateStr: string;
  year: number;
  month: number;
  day: number;
  inCurrentMonth: boolean;
  isWeekend: boolean;
  isToday: boolean;
  isSelected: boolean;
  isRangeStart: boolean;
  isRangeEnd: boolean;
  isInRange: boolean;
  isDisabled: boolean;
}

export interface CalendarGridOptions {
  selectedDate?: string;
  todayDate?: string;
  rangeStart?: string;
  rangeEnd?: string;
  minDate?: string;
  maxDate?: string;
}

const WEEKDAY_NAMES_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] as const;

export function buildCalendarMonthGrid(
  year: number,
  month1Based: number,
  options: CalendarGridOptions = {},
): CalendarDayCell[] {
  const {
    selectedDate = '',
    todayDate = '',
    rangeStart = '',
    rangeEnd = '',
    minDate = '',
    maxDate = '',
  } = options;

  const firstOfMonth = new Date(Date.UTC(year, month1Based - 1, 1));
  // Convert Sunday=0..Saturday=6 into Monday=0..Sunday=6
  const startDowMondayBased = (firstOfMonth.getUTCDay() + 6) % 7;
  const gridStartDate = new Date(Date.UTC(year, month1Based - 1, 1 - startDowMondayBased));

  const validRange =
    /^\d{4}-\d{2}-\d{2}$/.test(rangeStart) &&
    /^\d{4}-\d{2}-\d{2}$/.test(rangeEnd) &&
    rangeStart <= rangeEnd;

  const cells: CalendarDayCell[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStartDate.getTime() + i * 86400000);
    const cellYear = d.getUTCFullYear();
    const cellMonth = d.getUTCMonth() + 1;
    const cellDay = d.getUTCDate();
    const dateStr = `${cellYear}-${pad2(cellMonth)}-${pad2(cellDay)}`;
    const colIndex = i % 7;
    const inCurrentMonth = cellYear === year && cellMonth === month1Based;
    const isWeekend = colIndex === 5 || colIndex === 6;
    const isToday = Boolean(todayDate) && dateStr === todayDate;
    const isSelected = Boolean(selectedDate) && dateStr === selectedDate;
    const isRangeStart = validRange && dateStr === rangeStart;
    const isRangeEnd = validRange && dateStr === rangeEnd;
    const isInRange = validRange && dateStr >= rangeStart && dateStr <= rangeEnd;
    const isDisabled =
      (Boolean(minDate) && dateStr < minDate) ||
      (Boolean(maxDate) && dateStr > maxDate);

    cells.push({
      dateStr,
      year: cellYear,
      month: cellMonth,
      day: cellDay,
      inCurrentMonth,
      isWeekend,
      isToday,
      isSelected,
      isRangeStart,
      isRangeEnd,
      isInRange,
      isDisabled,
    });
  }

  return cells;
}

export interface CalendarMonthCell {
  monthStr: string;
  year: number;
  month: number;
  label: string;
  isCurrentMonth: boolean;
  isSelected: boolean;
  isInRange: boolean;
  isRangeStart: boolean;
  isRangeEnd: boolean;
  isDisabled: boolean;
}

export function buildCalendarYearMonths(
  year: number,
  options: {
    selectedMonth?: string;
    todayMonth?: string;
    rangeStartMonth?: string;
    rangeEndMonth?: string;
    minMonth?: string;
    maxMonth?: string;
  } = {},
): CalendarMonthCell[] {
  const {
    selectedMonth = '',
    todayMonth = '',
    rangeStartMonth = '',
    rangeEndMonth = '',
    minMonth = '',
    maxMonth = '',
  } = options;

  const validRange =
    /^\d{4}-\d{2}$/.test(rangeStartMonth) &&
    /^\d{4}-\d{2}$/.test(rangeEndMonth) &&
    rangeStartMonth <= rangeEndMonth;

  return Array.from({ length: 12 }, (_, idx) => {
    const month = idx + 1;
    const monthStr = `${year}-${pad2(month)}`;
    return {
      monthStr,
      year,
      month,
      label: `${month}月`,
      isCurrentMonth: Boolean(todayMonth) && monthStr === todayMonth,
      isSelected: Boolean(selectedMonth) && monthStr === selectedMonth,
      isRangeStart: validRange && monthStr === rangeStartMonth,
      isRangeEnd: validRange && monthStr === rangeEndMonth,
      isInRange: validRange && monthStr >= rangeStartMonth && monthStr <= rangeEndMonth,
      isDisabled:
        (Boolean(minMonth) && monthStr < minMonth) ||
        (Boolean(maxMonth) && monthStr > maxMonth),
    };
  });
}

export const LANORANGE_PARTNER_CITIES = [
  '保定',
  '北京',
  '潮州',
  '大连',
  '东莞',
  '广州',
  '惠州',
  '宁波',
  '泉州',
  '三亚',
  '汕头',
  '上海',
  '韶关',
  '深圳',
  '台州',
  '天津',
] as const;

const LANORANGE_CITY_SET = new Set<string>(LANORANGE_PARTNER_CITIES);

export function normalizeCityBaseName(name: string): string {
  return (name || '').trim().replace(/市$/, '');
}

export function isLanorangeCityName(name: string): boolean {
  return LANORANGE_CITY_SET.has(normalizeCityBaseName(name));
}

export function sortCitiesWithLanorangeFirst<T extends { name: string; disabled?: boolean }>(
  cities: readonly T[],
): T[] {
  return [...cities].sort((a, b) => {
    const aIsLanorange = isLanorangeCityName(a.name);
    const bIsLanorange = isLanorangeCityName(b.name);
    if (aIsLanorange !== bIsLanorange) {
      return aIsLanorange ? -1 : 1;
    }
    const aDisabled = Boolean(a.disabled);
    const bDisabled = Boolean(b.disabled);
    if (aDisabled !== bDisabled) {
      return aDisabled ? 1 : -1;
    }
    return 0;
  });
}

export function advanceCalendarRangeSelection(
  currentStart: string,
  currentEnd: string,
  clickedDate: string,
  step: 'start' | 'end',
): { start: string; end: string; nextStep: 'start' | 'end'; completed: boolean } {
  const date = (clickedDate || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return {
      start: currentStart,
      end: currentEnd,
      nextStep: step,
      completed: false,
    };
  }
  if (step === 'start' || !/^\d{4}-\d{2}-\d{2}$/.test(currentStart)) {
    return {
      start: date,
      end: date,
      nextStep: 'end',
      completed: false,
    };
  }
  if (date < currentStart) {
    return {
      start: date,
      end: currentStart,
      nextStep: 'start',
      completed: true,
    };
  }
  return {
    start: currentStart,
    end: date,
    nextStep: 'start',
    completed: true,
  };
}

export function formatDateTriggerMeta(
  value: string,
  mode: 'date' | 'month' | 'range' = 'date',
  placeholder?: string,
  rangeStart?: string,
  rangeEnd?: string,
): { primaryText: string; badgeText: string; isEmpty: boolean } {
  if (mode === 'range') {
    const startTrimmed = (rangeStart || '').trim();
    const endTrimmed = (rangeEnd || '').trim();
    const validStart = /^\d{4}-\d{2}-\d{2}$/.test(startTrimmed);
    const validEnd = /^\d{4}-\d{2}-\d{2}$/.test(endTrimmed);
    if (!validStart || !validEnd || startTrimmed > endTrimmed) {
      return {
        primaryText: placeholder || '选择日期范围',
        badgeText: '',
        isEmpty: true,
      };
    }
    const span = computeDateRangeSpanDays(startTrimmed, endTrimmed);
    return {
      primaryText: `${startTrimmed} 至 ${endTrimmed}`,
      badgeText: span !== null ? `共 ${span} 天` : '',
      isEmpty: false,
    };
  }

  const trimmed = (value || '').trim();
  if (mode === 'month') {
    const match = /^(\d{4})-(\d{2})/.exec(trimmed);
    if (!match) {
      return {
        primaryText: placeholder || '选择月份',
        badgeText: '',
        isEmpty: true,
      };
    }
    return {
      primaryText: `${match[1]}年${match[2]}月`,
      badgeText: `${Number(match[2])}月`,
      isEmpty: false,
    };
  }

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (!match) {
    return {
      primaryText: placeholder || '选择日期',
      badgeText: '',
      isEmpty: true,
    };
  }
  const d = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  const dow = Number.isNaN(d.getTime()) ? '' : WEEKDAY_NAMES_CN[d.getUTCDay()];
  return {
    primaryText: trimmed,
    badgeText: dow,
    isEmpty: false,
  };
}

export function computeDateRangeSpanDays(start?: string, end?: string): number | null {
  if (!start || !end) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) return null;
  if (start > end) return null;
  const ms = Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`);
  if (!Number.isFinite(ms) || ms < 0) return null;
  return Math.round(ms / 86400000) + 1;
}

export interface ExecutionRailSummaryInput {
  datasetsCount: number;
  cities: string[];
  start: string;
  end: string;
  noCity: boolean;
  noDate: boolean;
  archiveOnly: boolean;
  xiaoxiangDated: boolean;
  xiaoxiangOnly: boolean;
  blueOnly: boolean;
  baizeOnly: boolean;
  merchantOnly: boolean;
  merchantSnapshotOnly: boolean;
  merchantDateValid: boolean;
  validDates: boolean;
  includeSeparation: boolean;
  excludeSeparation?: boolean;
  subitemCount: number;
  submitReady: boolean;
}

export interface ExecutionRailSummary {
  cityLabel: string;
  periodText: string;
  periodSpanBadge: string | null;
  thirdRowLabel: string;
  thirdRowValue: string;
  listFooterText: string;
  blockerHint: string;
}

export function buildExecutionRailSummary(input: ExecutionRailSummaryInput): ExecutionRailSummary {
  const {
    datasetsCount,
    cities,
    start,
    end,
    noCity,
    noDate,
    archiveOnly,
    xiaoxiangDated,
    xiaoxiangOnly,
    blueOnly,
    baizeOnly,
    merchantOnly,
    merchantSnapshotOnly,
    merchantDateValid,
    validDates,
    includeSeparation,
    excludeSeparation,
    subitemCount,
    submitReady,
  } = input;

  const cityLabel = cities.length > 0
    ? `${cities.slice(0, 3).join('、')}${cities.length > 3 ? ` 等 ${cities.length} 城` : ''}`
    : archiveOnly
      ? '全部站点快照'
      : xiaoxiangDated
        ? '可访问全部城市'
        : baizeOnly
          ? '全部站点（商翼全量）'
          : blueOnly
            ? '全部城市（全量）'
            : '未选择城市';

  const isSnapshotScope = baizeOnly || noDate;
  const spanDays = !isSnapshotScope ? computeDateRangeSpanDays(start, end) : null;

  let periodText = '全量实时快照';
  let periodSpanBadge: string | null = '不限账期';

  if (!isSnapshotScope) {
    if (!start || !end) {
      periodText = '待选择账期';
      periodSpanBadge = null;
    } else if (start === end) {
      periodText = start;
      periodSpanBadge = '单日';
    } else if (start.slice(0, 4) === end.slice(0, 4)) {
      periodText = `${start} ~ ${end.slice(5)}`;
      periodSpanBadge = spanDays ? `共 ${spanDays} 天` : null;
    } else {
      periodText = `${start} ~ ${end}`;
      periodSpanBadge = spanDays ? `共 ${spanDays} 天` : null;
    }
  }

  let thirdRowLabel = '站点规则';
  let thirdRowValue = '排除取分离';

  if (!noCity && !xiaoxiangOnly) {
    thirdRowLabel = '站点规则';
    thirdRowValue = merchantOnly ? '全部站点' : excludeSeparation !== undefined ? (excludeSeparation ? '排除取分离' : '全部站点（含取分离）') : includeSeparation ? '仅取分离' : '排除取分离';
  } else {
    thirdRowLabel = '交付规格';
    thirdRowValue = baizeOnly
      ? '单份全量原表'
      : blueOnly
        ? `每类 1 份汇总表`
        : archiveOnly
          ? '全城骑手档案快照'
          : `按账期合并导出`;
  }

  let listFooterText = '';
  if (datasetsCount > 0) {
    if (baizeOnly) {
      listFooterText = '商翼全量员工档案 · 独立归档';
    } else if (xiaoxiangOnly) {
      listFooterText = `已选 ${datasetsCount} 类灯塔资料 · 全城自动覆盖`;
    } else if (blueOnly) {
      listFooterText = `已选 ${datasetsCount} 类蓝橙资料 · 全城全量直连`;
    } else if (merchantOnly) {
      listFooterText = `已选 ${datasetsCount} 类商家资料 · ${cities.length || 0} 城全部站点`;
    } else {
      listFooterText = cities.length > 0
        ? `已选 ${datasetsCount} 类资料 · 预计 ${subitemCount} 个采集子项`
        : `已选 ${datasetsCount} 类资料 · 待选择处理城市`;
    }
  }

  let blockerHint = '';
  if (!submitReady) {
    if (datasetsCount === 0) {
      blockerHint = '请先在左侧勾选需要采集的资料';
    } else if (!noCity && cities.length === 0) {
      blockerHint = '请至少选择 1 个处理城市';
    } else if (merchantOnly && !merchantSnapshotOnly && !merchantDateValid) {
      blockerHint = '出勤明细请选择最近 90 天内、早于今天的起止日期';
    } else if (!noDate && !validDates) {
      blockerHint = '开始日期不能晚于结束日期';
    }
  }

  return {
    cityLabel,
    periodText,
    periodSpanBadge,
    thirdRowLabel,
    thirdRowValue,
    listFooterText,
    blockerHint,
  };
}

