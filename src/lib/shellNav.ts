import type { DownloadPlatform } from './downloadModules';
import type { PayrollSubView, PlatformDotTone, PlatformStatusMap } from './workbench';
import { getPlatformStatusCluster } from './workbench';

export type NavGroupId = 'collection' | 'reports' | 'payroll' | 'approval' | 'history' | 'admin';

export interface ShellNavState {
  workspaceView: 'create' | 'history' | 'approval' | 'price-export' | 'pickup' | 'accounts';
  taskKind: 'download' | 'generate' | 'payroll';
  downloadPlatform: DownloadPlatform;
  payrollSubView: PayrollSubView;
  reportId?: string;
}

export type ShellCommandAction =
  | { type: 'platform'; platform: DownloadPlatform }
  | { type: 'report'; reportId: string }
  | { type: 'payroll'; subView: PayrollSubView }
  | { type: 'workspace'; view: 'approval' | 'price-export' | 'history' | 'pickup' | 'accounts' }
  | { type: 'open-dock' }
  | { type: 'open-logs' }
  | { type: 'toggle-sidebar' };

export type QuickTargetId =
  | 'platform:fengshen'
  | 'platform:lanorange'
  | 'platform:payout'
  | 'platform:xiaoxiang'
  | 'report:payment_binding'
  | 'report:abnormal_followup'
  | 'report:abnormal_riders'
  | 'report:problem'
  | 'payroll:batches'
  | 'payroll:deductions'
  | 'payroll:templates'
  | 'workspace:approval'
  | 'workspace:price-export'
  | 'workspace:history'
  | 'workspace:pickup'
  | 'workspace:accounts';

export interface QuickTargetMeta {
  id: QuickTargetId;
  groupId: NavGroupId;
  label: string;
  shortLabel: string;
  moduleLabel: string;
  hint: string;
  accent: 'sapphire' | 'amber' | 'emerald' | 'violet' | 'slate';
  action: ShellCommandAction;
}

export interface BreadcrumbSibling {
  id: string;
  label: string;
  hint?: string;
  active: boolean;
  action: ShellCommandAction;
}

export interface BreadcrumbModel {
  groupId: NavGroupId;
  moduleLabel: string;
  viewLabel: string;
  siblings: BreadcrumbSibling[];
}

export interface ShellCommandItem {
  id: string;
  group: '数据采集' | '业务报表' | '薪资核算' | '价格审批' | '全局调度' | '系统管理';
  label: string;
  subtitle: string;
  keywords: string[];
  shortcut?: string;
  active: boolean;
  action: ShellCommandAction;
}

export interface SpecialReportSubModuleMeta {
  id: 'payment_binding' | 'abnormal_followup' | 'abnormal_riders' | 'problem';
  label: string;
  shortLabel: string;
  hint: string;
  subtitle: string;
  keywords: string[];
}

export const SPECIAL_REPORT_SUBMODULES: SpecialReportSubModuleMeta[] = [
  {
    id: 'payment_binding',
    label: '支付绑定',
    shortLabel: '支付绑定',
    hint: '按城市按月关联收薪绑定与发薪档案',
    subtitle: '自动关联风神收薪绑定与蓝橙、商翼及本来人力档案，输出多城汇总',
    keywords: ['payment', 'binding', 'zfbd', '支付', '绑定', '业务报表', '专项报表'],
  },
  {
    id: 'abnormal_followup',
    label: '异常跟进',
    shortLabel: '异常跟进',
    hint: '按城市按月排查物资、UB账单与档案异常',
    subtitle: '以支付绑定为基准，关联物资租用、月度 UB 账单与价格档案定位异常',
    keywords: ['abnormal', 'followup', 'ycgj', '异常', '跟进', '业务报表', '专项报表'],
  },
  {
    id: 'abnormal_riders',
    label: '异常名单',
    shortLabel: '异常名单',
    hint: '全城全量汇总蓝橙离职、请假与骑手档案',
    subtitle: '固定全城全量汇总蓝橙 5 类离职、请假与骑手档案，免选城市与月份',
    keywords: ['abnormal', 'riders', 'ycmd', 'yczl', '异常', '名单', '整理', '全量', '业务报表', '专项报表'],
  },
  {
    id: 'problem',
    label: '问题单',
    shortLabel: '问题单',
    hint: '按城市与日期范围生成风神问题单汇总及明细',
    subtitle: '按城市与日期范围采集风神问题单并过滤取分离站点，生成汇总与明细工作簿',
    keywords: ['problem', 'wtd', '问题单', '风神', '业务报表', '专项报表'],
  },
];

export const RAIL_GROUP_ORDER: NavGroupId[] = ['collection', 'reports', 'payroll', 'approval', 'history'];

export const QUICK_TARGETS: QuickTargetMeta[] = [
  {
    id: 'platform:fengshen',
    groupId: 'collection',
    label: '风神数据',
    shortLabel: '风神',
    moduleLabel: '数据采集',
    hint: '配送费、扣款与账单采集',
    accent: 'sapphire',
    action: { type: 'platform', platform: 'fengshen' },
  },
  {
    id: 'platform:lanorange',
    groupId: 'collection',
    label: '蓝橙数据',
    shortLabel: '蓝橙',
    moduleLabel: '数据采集',
    hint: '原雷神人事与兼职价格',
    accent: 'amber',
    action: { type: 'platform', platform: 'lanorange' },
  },
  {
    id: 'platform:payout',
    groupId: 'collection',
    label: '发薪平台',
    shortLabel: '发薪',
    moduleLabel: '数据采集',
    hint: '白泽商翼 · 本来人力',
    accent: 'emerald',
    action: { type: 'platform', platform: 'payout' },
  },
  {
    id: 'platform:xiaoxiang',
    groupId: 'collection',
    label: '小象灯塔',
    shortLabel: '灯塔',
    moduleLabel: '数据采集',
    hint: '美团商配送日维度看板',
    accent: 'violet',
    action: { type: 'platform', platform: 'xiaoxiang' },
  },
  ...SPECIAL_REPORT_SUBMODULES.map(report => ({
    id: `report:${report.id}` as QuickTargetId,
    groupId: 'reports' as NavGroupId,
    label: report.label,
    shortLabel: report.shortLabel,
    moduleLabel: '业务报表',
    hint: report.hint,
    accent: 'sapphire' as const,
    action: { type: 'report' as const, reportId: report.id },
  })),
  {
    id: 'payroll:batches',
    groupId: 'payroll',
    label: '兼职核算',
    shortLabel: '核算',
    moduleLabel: '薪资核算',
    hint: '申请表上传与自动齐套',
    accent: 'sapphire',
    action: { type: 'payroll', subView: 'batches' },
  },
  {
    id: 'payroll:deductions',
    groupId: 'payroll',
    label: '扣款配置',
    shortLabel: '扣款',
    moduleLabel: '薪资核算',
    hint: '站点默认扣款与关键词',
    accent: 'amber',
    action: { type: 'payroll', subView: 'deductions' },
  },
  {
    id: 'payroll:templates',
    groupId: 'payroll',
    label: '模板中心',
    shortLabel: '模板',
    moduleLabel: '薪资核算',
    hint: '闪购与小象标准 Excel',
    accent: 'emerald',
    action: { type: 'payroll', subView: 'templates' },
  },
  {
    id: 'workspace:approval',
    groupId: 'payroll',
    label: '价格审批',
    shortLabel: '审批',
    moduleLabel: '薪资核算',
    hint: '跨页勾选与批量同意',
    accent: 'amber',
    action: { type: 'workspace', view: 'approval' },
  },
  {
    id: 'workspace:history',
    groupId: 'history',
    label: '任务中心',
    shortLabel: '任务',
    moduleLabel: '全局交付',
    hint: '进度追踪与打包领取',
    accent: 'slate',
    action: { type: 'workspace', view: 'history' },
  },
  {
    id: 'workspace:pickup',
    groupId: 'history',
    label: '文件领取',
    shortLabel: '领取',
    moduleLabel: '全局交付',
    hint: '本机成品与共享电脑文件领取',
    accent: 'slate',
    action: { type: 'workspace', view: 'pickup' },
  },
  {
    id: 'workspace:accounts',
    groupId: 'admin',
    label: '账户与权限',
    shortLabel: '权限',
    moduleLabel: '系统管理',
    hint: '成员审批、独立空间与安全审计',
    accent: 'sapphire',
    action: { type: 'workspace', view: 'accounts' },
  },
];

const QUICK_TARGET_MAP = new Map<QuickTargetId, QuickTargetMeta>(
  QUICK_TARGETS.map(item => [item.id, item]),
);

export function getQuickTargetMeta(id: QuickTargetId): QuickTargetMeta | undefined {
  return QUICK_TARGET_MAP.get(id);
}

export function getActiveNavGroup(state: Pick<ShellNavState, 'workspaceView' | 'taskKind'>): NavGroupId {
  if (state.workspaceView === 'accounts') return 'admin';
  if (state.workspaceView === 'history' || state.workspaceView === 'pickup') return 'history';
  if (state.workspaceView === 'approval' || state.workspaceView === 'price-export') return 'payroll';
  if (state.taskKind === 'payroll') return 'payroll';
  if (state.taskKind === 'generate') return 'reports';
  return 'collection';
}

export function getRailIndex(groupId: NavGroupId): number {
  const idx = RAIL_GROUP_ORDER.indexOf(groupId);
  return idx >= 0 ? idx : 0;
}

export function getCurrentQuickTargetId(state: ShellNavState): QuickTargetId {
  const groupId = getActiveNavGroup(state);
  if (groupId === 'admin') return 'workspace:accounts';
  if (groupId === 'history') return state.workspaceView === 'pickup' ? 'workspace:pickup' : 'workspace:history';
  if (state.workspaceView === 'approval' || state.workspaceView === 'price-export') {
    return 'workspace:approval';
  }
  if (groupId === 'payroll') {
    return `payroll:${state.payrollSubView}` as QuickTargetId;
  }
  if (groupId === 'reports') {
    const targetId = SPECIAL_REPORT_SUBMODULES.find(item => item.id === state.reportId)?.id || SPECIAL_REPORT_SUBMODULES[0].id;
    return `report:${targetId}` as QuickTargetId;
  }
  return `platform:${state.downloadPlatform}` as QuickTargetId;
}

export function sanitizeStoredTargets(raw: unknown, maxItems = 4): QuickTargetId[] {
  if (!Array.isArray(raw)) return [];
  const valid: QuickTargetId[] = [];
  for (const entry of raw) {
    if (typeof entry === 'string' && QUICK_TARGET_MAP.has(entry as QuickTargetId)) {
      const id = entry as QuickTargetId;
      if (!valid.includes(id)) valid.push(id);
      if (valid.length >= maxItems) break;
    }
  }
  return valid;
}

export function togglePinnedTarget(
  currentPins: ReadonlyArray<QuickTargetId>,
  targetId: QuickTargetId,
  maxPins = 4,
): QuickTargetId[] {
  if (!QUICK_TARGET_MAP.has(targetId)) return [...currentPins];
  if (currentPins.includes(targetId)) {
    return currentPins.filter(id => id !== targetId);
  }
  return [targetId, ...currentPins].slice(0, maxPins);
}

export function recordRecentTarget(
  currentRecent: ReadonlyArray<QuickTargetId>,
  targetId: QuickTargetId,
  maxRecent = 4,
): QuickTargetId[] {
  if (!QUICK_TARGET_MAP.has(targetId)) return [...currentRecent];
  const next = [targetId, ...currentRecent.filter(id => id !== targetId)];
  return next.slice(0, maxRecent);
}

export function getPlatformChannelStatus(
  platformId: DownloadPlatform,
  statuses: PlatformStatusMap,
): { tone: PlatformDotTone; statusText: string } {
  const cluster = getPlatformStatusCluster(statuses);
  const byKey = new Map(cluster.map(item => [item.key, item]));

  if (platformId === 'payout') {
    const baize = byKey.get('baize');
    const benlai = byKey.get('benlai');
    const pair = [baize, benlai].filter(Boolean);
    const readyCount = pair.filter(item => item!.tone === 'ready').length;
    if (readyCount === 2) return { tone: 'ready', statusText: '商翼/本来均已连' };
    if (pair.some(item => item!.tone === 'busy')) return { tone: 'busy', statusText: '通道检查中' };
    if (readyCount === 1) return { tone: 'ready', statusText: '1/2 通道已连接' };
    if (pair.some(item => item!.tone === 'warn')) return { tone: 'warn', statusText: '需登录验证' };
    return { tone: 'idle', statusText: '未连接' };
  }

  const chip = byKey.get(platformId);
  if (!chip) return { tone: 'idle', statusText: '未连接' };
  return { tone: chip.tone, statusText: chip.statusText };
}

export function getBreadcrumbModel(state: ShellNavState): BreadcrumbModel {
  const groupId = getActiveNavGroup(state);

  if (groupId === 'collection') {
    const platforms: { id: DownloadPlatform; label: string; hint: string }[] = [
      { id: 'fengshen', label: '风神数据', hint: '配送费、违规扣款与考勤源表' },
      { id: 'lanorange', label: '蓝橙数据', hint: '人事档案、离职请假与价格表' },
      { id: 'payout', label: '发薪平台', hint: '白泽商翼与本来人力' },
      { id: 'xiaoxiang', label: '小象灯塔', hint: '商配送日维度分析与订单明细' },
    ];
    const current = platforms.find(item => item.id === state.downloadPlatform) || platforms[0];
    return {
      groupId,
      moduleLabel: '数据采集',
      viewLabel: current.label,
      siblings: platforms.map(item => ({
        id: item.id,
        label: item.label,
        hint: item.hint,
        active: item.id === current.id,
        action: { type: 'platform', platform: item.id },
      })),
    };
  }

  if (groupId === 'reports') {
    const current =
      SPECIAL_REPORT_SUBMODULES.find(item => item.id === state.reportId) ||
      SPECIAL_REPORT_SUBMODULES[0];
    return {
      groupId,
      moduleLabel: '业务报表',
      viewLabel: current.label,
      siblings: SPECIAL_REPORT_SUBMODULES.map(item => ({
        id: item.id,
        label: item.label,
        hint: item.hint,
        active: item.id === current.id,
        action: { type: 'report', reportId: item.id },
      })),
    };
  }

  if (groupId === 'payroll') {
    const isApproval = state.workspaceView === 'approval' || state.workspaceView === 'price-export';
    const subViews: { id: string; label: string; hint: string; active: boolean; action: ShellCommandAction }[] = [
      {
        id: 'batches',
        label: '兼职核算',
        hint: '上传申请表与自动化核算',
        active: !isApproval && state.payrollSubView === 'batches',
        action: { type: 'payroll', subView: 'batches' },
      },
      {
        id: 'deductions',
        label: '扣款配置',
        hint: '站点默认扣款与关键词配置',
        active: !isApproval && state.payrollSubView === 'deductions',
        action: { type: 'payroll', subView: 'deductions' },
      },
      {
        id: 'templates',
        label: '模板中心',
        hint: '闪购与小象标准核算模板',
        active: !isApproval && state.payrollSubView === 'templates',
        action: { type: 'payroll', subView: 'templates' },
      },
      {
        id: 'approval',
        label: '价格审批',
        hint: '筛选本人提审并跨页批量审批',
        active: isApproval,
        action: { type: 'workspace', view: 'approval' },
      },
    ];
    const current = subViews.find(item => item.active) || subViews[0];
    return {
      groupId: 'payroll',
      moduleLabel: '薪资核算',
      viewLabel: current.label,
      siblings: subViews,
    };
  }

  if (groupId === 'admin') {
    return {
      groupId: 'admin',
      moduleLabel: '系统管理',
      viewLabel: '账户与权限',
      siblings: [
        {
          id: 'accounts',
          label: '账户与权限',
          hint: '成员注册审批、独立空间隔离与安全审计日志',
          active: true,
          action: { type: 'workspace', view: 'accounts' },
        },
      ],
    };
  }

  const isPickup = state.workspaceView === 'pickup';
  return {
    groupId: 'history',
    moduleLabel: '全局交付',
    viewLabel: isPickup ? '文件领取' : '任务中心',
    siblings: [
      {
        id: 'history',
        label: '任务中心',
        hint: '全部历史任务与文件下载',
        active: !isPickup,
        action: { type: 'workspace', view: 'history' },
      },
      {
        id: 'pickup',
        label: '文件领取',
        hint: '本机成品与共享电脑文件一键获取',
        active: isPickup,
        action: { type: 'workspace', view: 'pickup' },
      },
    ],
  };
}

export function buildShellCommands(
  state: ShellNavState,
  options: {
    sidebarCollapsed?: boolean;
    isAdmin?: boolean;
    permissions?: Record<string, boolean>;
  } = {},
): ShellCommandItem[] {
  const groupId = getActiveNavGroup(state);
  const isCollection = groupId === 'collection';
  const isReports = groupId === 'reports';
  const activeReportId = state.reportId || SPECIAL_REPORT_SUBMODULES[0].id;
  const isPayroll = groupId === 'payroll' && state.workspaceView === 'create';
  const hasPermissionFilter = Boolean(options.permissions) && !options.isAdmin;
  const canUse = (key: string) =>
    !hasPermissionFilter || options.permissions?.[key] !== false;

  const commands: ShellCommandItem[] = [];

  if (canUse('collection')) {
    commands.push(
      {
        id: 'nav-fengshen',
        group: '数据采集',
        label: '风神数据',
        subtitle: '配送费、违规扣款、UB账单、风控运单与考勤源表采集',
        keywords: ['fengshen', 'fs', '风神', '闪购', '配送费', '扣款', '考勤'],
        active: isCollection && state.downloadPlatform === 'fengshen',
        action: { type: 'platform', platform: 'fengshen' },
      },
      {
        id: 'nav-lanorange',
        group: '数据采集',
        label: '蓝橙数据',
        subtitle: '骑手档案、兼职价格、离职报备与请假全量采集',
        keywords: ['lanorange', 'lc', '蓝橙', '雷神', '离职', '请假', '骑手档案'],
        active: isCollection && state.downloadPlatform === 'lanorange',
        action: { type: 'platform', platform: 'lanorange' },
      },
      {
        id: 'nav-payout',
        group: '数据采集',
        label: '发薪平台（白泽商翼 + 本来人力）',
        subtitle: '商翼员工总表与本来人力灵工档案实时直采',
        keywords: ['payout', 'fx', 'baize', 'shangyi', 'benlai', '发薪', '白泽', '商翼', '本来'],
        active: isCollection && state.downloadPlatform === 'payout',
        action: { type: 'platform', platform: 'payout' },
      },
    );
    if (canUse('xiaoxiang_use')) {
      commands.push({
        id: 'nav-xiaoxiang',
        group: '数据采集',
        label: '小象灯塔',
        subtitle: '商配送日维度骑手分析、档案与订单客诉明细',
        keywords: ['xiaoxiang', 'xx', 'dengta', 'dt', '小象', '灯塔', '美团'],
        active: isCollection && state.downloadPlatform === 'xiaoxiang',
        action: { type: 'platform', platform: 'xiaoxiang' },
      });
    }
  }

  if (canUse('reports')) {
    commands.push(
      ...SPECIAL_REPORT_SUBMODULES.map(report => ({
        id: `nav-report-${report.id}`,
        group: '业务报表' as const,
        label: report.label,
        subtitle: report.subtitle,
        keywords: report.keywords,
        active: isReports && activeReportId === report.id,
        action: { type: 'report' as const, reportId: report.id },
      })),
    );
  }

  if (canUse('payroll')) {
    commands.push(
      {
        id: 'nav-payroll-batches',
        group: '薪资核算',
        label: '兼职核算',
        subtitle: '上传兼职薪资申请表，自动齐套资料并执行核算',
        keywords: ['payroll', 'xz', 'hs', '薪资', '核算', '兼职', '工资'],
        active: isPayroll && state.payrollSubView === 'batches',
        action: { type: 'payroll', subView: 'batches' },
      },
      {
        id: 'nav-payroll-deductions',
        group: '薪资核算',
        label: '扣款配置',
        subtitle: '按城市与团队维护站点默认扣款金额及关键词',
        keywords: ['deduction', 'kk', '扣款', '站点', '规则', '配置'],
        active: isPayroll && state.payrollSubView === 'deductions',
        action: { type: 'payroll', subView: 'deductions' },
      },
      {
        id: 'nav-payroll-templates',
        group: '薪资核算',
        label: '标准模板中心',
        subtitle: '下载与管理淘宝闪购、美团小象标准 Excel 模板',
        keywords: ['template', 'mb', '模板', 'excel', '下载'],
        active: isPayroll && state.payrollSubView === 'templates',
        action: { type: 'payroll', subView: 'templates' },
      },
    );
  }

  if (canUse('approval')) {
    commands.push({
      id: 'nav-approval',
      group: '薪资核算',
      label: '价格审批',
      subtitle: '筛选本人待审单据，跨页勾选并批量审批',
      keywords: ['approval', 'sp', '审批', '价格', '蓝橙'],
      active: state.workspaceView === 'approval',
      action: { type: 'workspace', view: 'approval' },
    });
  }

  commands.push(
    {
      id: 'nav-history',
      group: '全局调度',
      label: '任务中心',
      subtitle: '查看跨平台任务执行记录并一键打包下载成果文件',
      keywords: ['history', 'task', 'rw', '任务', '记录', '下载', '归档'],
      active: state.workspaceView === 'history',
      action: { type: 'workspace', view: 'history' },
    },
    {
      id: 'nav-pickup',
      group: '全局调度',
      label: '文件领取',
      subtitle: '按任务领取本机成品，或浏览局域网共享电脑的文件',
      keywords: ['pickup', 'lingqu', 'lq', '文件', '领取', '共享', '局域网', 'ip'],
      active: state.workspaceView === 'pickup',
      action: { type: 'workspace', view: 'pickup' },
    },
  );

  if (options.isAdmin) {
    commands.push({
      id: 'nav-accounts',
      group: '系统管理',
      label: '账户与权限',
      subtitle: '审批同事注册申请、配置模块权限与查看安全审计日志',
      keywords: ['account', 'admin', 'perm', 'audit', 'zh', 'qx', '账户', '权限', '审批', '审计'],
      active: state.workspaceView === 'accounts',
      action: { type: 'workspace', view: 'accounts' },
    });
  }

  commands.push(
    {
      id: 'act-platform-dock',
      group: '全局调度',
      label: '打开五大平台连接中心',
      subtitle: '巡检风神、蓝橙、商翼、灯塔、本来登录态与授权',
      keywords: ['auth', 'login', 'dl', 'pt', '平台', '登录', '授权', '通道', '扫码'],
      active: false,
      action: { type: 'open-dock' },
    },
    {
      id: 'act-log-drawer',
      group: '全局调度',
      label: '打开运行日志终端',
      subtitle: '实时检索、按级别筛选、复制与导出引擎运行日志',
      keywords: ['log', 'rz', 'console', 'terminal', '日志', '终端', '调试', '排查'],
      shortcut: 'L',
      active: false,
      action: { type: 'open-logs' },
    },
    {
      id: 'act-toggle-sidebar',
      group: '全局调度',
      label: options.sidebarCollapsed ? '展开左侧情境导航栏' : '收起为极简命令轨',
      subtitle: '在双轨导航舱与 56px 极简深空图标轨之间切换工作区视野',
      keywords: ['sidebar', 'ce', 'nav', '侧栏', '折叠', '收起', '展开'],
      shortcut: '[',
      active: false,
      action: { type: 'toggle-sidebar' },
    },
  );

  return commands;
}

export function filterShellCommands(commands: ShellCommandItem[], rawQuery: string): ShellCommandItem[] {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return commands;

  const tokens = query.split(/\s+/).filter(Boolean);
  const scored: { item: ShellCommandItem; score: number }[] = [];

  for (const item of commands) {
    const label = item.label.toLowerCase();
    const subtitle = item.subtitle.toLowerCase();
    const group = item.group.toLowerCase();
    const keywords = item.keywords.map(k => k.toLowerCase());
    const haystack = `${label} ${subtitle} ${group} ${keywords.join(' ')}`;

    const matchesAll = tokens.every(token => haystack.includes(token));
    if (!matchesAll) continue;

    let score = 0;
    for (const token of tokens) {
      if (label === token) score += 100;
      else if (label.startsWith(token)) score += 60;
      else if (label.includes(token)) score += 40;
      else if (keywords.some(k => k === token)) score += 35;
      else if (keywords.some(k => k.startsWith(token))) score += 25;
      else if (keywords.some(k => k.includes(token))) score += 15;
      else if (group.includes(token)) score += 10;
      else if (subtitle.includes(token)) score += 5;
    }
    scored.push({ item, score });
  }

  return scored.sort((a, b) => b.score - a.score).map(entry => entry.item);
}
