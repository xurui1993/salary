import type { DownloadPlatform } from './downloadModules';
import type { PayrollSubView, PlatformDotTone, PlatformStatusMap } from './workbench';
import { getPlatformStatusCluster } from './workbench';
import {
  getGlobalWorkbenchConfig,
  isBusinessModuleEnabled,
  isPlatformShared,
  resolveModuleGroupLabel,
  resolveSubmoduleLabel,
  type GlobalWorkbenchConfig,
  type PlatformChannelKey,
} from './workbenchConfig';

export type NavGroupId = 'collection' | 'reports' | 'payroll' | 'approval' | 'history' | 'admin';

export interface ShellNavState {
  workspaceView:
    | 'create'
    | 'history'
    | 'approval'
    | 'price-export'
    | 'pickup'
    | 'accounts'
    | 'platform-auth'
    | 'global-config';
  taskKind: 'download' | 'generate' | 'payroll';
  downloadPlatform: DownloadPlatform;
  payrollSubView: PayrollSubView;
  reportId?: string;
}

export type ShellCommandAction =
  | { type: 'platform'; platform: DownloadPlatform }
  | { type: 'report'; reportId: string }
  | { type: 'payroll'; subView: PayrollSubView }
  | {
      type: 'workspace';
      view:
        | 'approval'
        | 'price-export'
        | 'history'
        | 'pickup'
        | 'accounts'
        | 'platform-auth'
        | 'global-config';
    }
  | { type: 'open-dock'; source?: string }
  | { type: 'open-logs' }
  | { type: 'toggle-sidebar' };

export type QuickTargetId =
  | 'platform:fengshen'
  | 'platform:lanorange'
  | 'platform:lanorange_mdr'
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
  | 'workspace:platform-auth'
  | 'workspace:accounts'
  | 'workspace:global-config';

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
  group: string;
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
    id: 'platform:lanorange_mdr',
    groupId: 'collection',
    label: '新蓝橙数据',
    shortLabel: '新蓝橙',
    moduleLabel: '数据采集',
    hint: '新系统人事与兼职价格',
    accent: 'amber',
    action: { type: 'platform', platform: 'lanorange_mdr' },
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
    groupId: 'collection',
    label: '任务下载',
    shortLabel: '下载',
    moduleLabel: '数据采集',
    hint: '进度追踪与打包领取',
    accent: 'slate',
    action: { type: 'workspace', view: 'history' },
  },
  {
    id: 'workspace:pickup',
    groupId: 'history',
    label: '组内共享',
    shortLabel: '共享',
    moduleLabel: '平台管理',
    hint: '本机成品与局域网组内共享文件领取',
    accent: 'slate',
    action: { type: 'workspace', view: 'pickup' },
  },
  {
    id: 'workspace:platform-auth',
    groupId: 'admin',
    label: '授权管理',
    shortLabel: '授权',
    moduleLabel: '平台管理',
    hint: '五大业务平台账户绑定、切换与连通性巡检',
    accent: 'sapphire',
    action: { type: 'workspace', view: 'platform-auth' },
  },
  {
    id: 'workspace:accounts',
    groupId: 'admin',
    label: '用户权限分配',
    shortLabel: '权限',
    moduleLabel: '平台管理',
    hint: '成员建号、通道与模块分配、权限勾选与安全审计',
    accent: 'sapphire',
    action: { type: 'workspace', view: 'accounts' },
  },
  {
    id: 'workspace:global-config',
    groupId: 'admin',
    label: '全局配置',
    shortLabel: '配置',
    moduleLabel: '平台管理',
    hint: '一二级模块名称与数据采集资料主副标题自定义',
    accent: 'sapphire',
    action: { type: 'workspace', view: 'global-config' },
  },
];

const QUICK_TARGET_MAP = new Map<QuickTargetId, QuickTargetMeta>(
  QUICK_TARGETS.map(item => [item.id, item]),
);

export function getQuickTargetMeta(id: QuickTargetId): QuickTargetMeta | undefined {
  return QUICK_TARGET_MAP.get(id);
}

export function getActiveNavGroup(state: Pick<ShellNavState, 'workspaceView' | 'taskKind'>): NavGroupId {
  if (
    state.workspaceView === 'accounts' ||
    state.workspaceView === 'platform-auth' ||
    state.workspaceView === 'global-config'
  ) {
    return 'admin';
  }
  if (state.workspaceView === 'history') return 'collection';
  if (state.workspaceView === 'pickup') return 'history';
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
  if (groupId === 'admin') {
    if (state.workspaceView === 'platform-auth') return 'workspace:platform-auth';
    if (state.workspaceView === 'global-config') return 'workspace:global-config';
    return 'workspace:accounts';
  }
  if (state.workspaceView === 'history') return 'workspace:history';
  if (groupId === 'history') return 'workspace:pickup';
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

export function canMemberAccessDownloadPlatform(
  platformId: DownloadPlatform,
  options: {
    isAdmin?: boolean;
    permissions?: Record<string, boolean>;
    globalConfig?: GlobalWorkbenchConfig;
  } = {},
): boolean {
  const cfg = options.globalConfig || getGlobalWorkbenchConfig();
  if (!options.isAdmin && !isBusinessModuleEnabled('collection', cfg)) {
    return false;
  }
  if (options.isAdmin || !options.permissions) {
    return true;
  }
  if (options.permissions.collection === false) {
    return false;
  }
  if (platformId === 'payout') {
    const baizeShared = isPlatformShared('baize', cfg);
    const benlaiShared = isPlatformShared('benlai', cfg);
    const baizeOk = !baizeShared || options.permissions.baize_use !== false;
    const benlaiOk = !benlaiShared || options.permissions.benlai_use !== false;
    return baizeOk || benlaiOk;
  }
  const chKey = platformId as PlatformChannelKey;
  if (!isPlatformShared(chKey, cfg)) {
    return true;
  }
  return options.permissions[`${chKey}_use`] !== false;
}

export function getBreadcrumbModel(
  state: ShellNavState,
  cfg: GlobalWorkbenchConfig = getGlobalWorkbenchConfig(),
  isAdmin = true,
): BreadcrumbModel {
  const groupId = getActiveNavGroup(state);

  if (groupId === 'collection') {
    const isHistory = state.workspaceView === 'history';
    const platforms: { id: DownloadPlatform; label: string; hint: string }[] = [
      { id: 'fengshen', label: resolveSubmoduleLabel('platform:fengshen', '风神数据', cfg), hint: '配送费、违规扣款与考勤源表' },
      { id: 'lanorange', label: resolveSubmoduleLabel('platform:lanorange', '蓝橙数据', cfg), hint: '人事档案、离职请假与价格表' },
      { id: 'lanorange_mdr', label: resolveSubmoduleLabel('platform:lanorange_mdr', '新蓝橙数据', cfg), hint: '新系统骑手档案、离职请假与价格表' },
      { id: 'payout', label: resolveSubmoduleLabel('platform:payout', '发薪平台', cfg), hint: '白泽商翼与本来人力' },
      { id: 'xiaoxiang', label: resolveSubmoduleLabel('platform:xiaoxiang', '小象灯塔', cfg), hint: '商配送日维度分析与订单明细' },
    ];
    const current = platforms.find(item => item.id === state.downloadPlatform) || platforms[0];
    const historyLabel = resolveSubmoduleLabel('workspace:history', '任务下载', cfg);
    const siblings: BreadcrumbSibling[] = [
      ...platforms.map(item => ({
        id: item.id,
        label: item.label,
        hint: item.hint,
        active: !isHistory && item.id === current.id,
        action: { type: 'platform' as const, platform: item.id },
      })),
      {
        id: 'history',
        label: historyLabel,
        hint: '全部历史任务与文件下载',
        active: isHistory,
        action: { type: 'workspace' as const, view: 'history' as const },
      },
    ];
    return {
      groupId,
      moduleLabel: resolveModuleGroupLabel('collection', cfg),
      viewLabel: isHistory ? historyLabel : current.label,
      siblings,
    };
  }

  if (groupId === 'reports') {
    const current =
      SPECIAL_REPORT_SUBMODULES.find(item => item.id === state.reportId) ||
      SPECIAL_REPORT_SUBMODULES[0];
    return {
      groupId,
      moduleLabel: resolveModuleGroupLabel('reports', cfg),
      viewLabel: resolveSubmoduleLabel(`report:${current.id}`, current.label, cfg),
      siblings: SPECIAL_REPORT_SUBMODULES.map(item => ({
        id: item.id,
        label: resolveSubmoduleLabel(`report:${item.id}`, item.label, cfg),
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
        label: resolveSubmoduleLabel('payroll:batches', '兼职核算', cfg),
        hint: '上传申请表与自动化核算',
        active: !isApproval && state.payrollSubView === 'batches',
        action: { type: 'payroll', subView: 'batches' },
      },
      {
        id: 'deductions',
        label: resolveSubmoduleLabel('payroll:deductions', '扣款配置', cfg),
        hint: '站点默认扣款与关键词配置',
        active: !isApproval && state.payrollSubView === 'deductions',
        action: { type: 'payroll', subView: 'deductions' },
      },
      {
        id: 'templates',
        label: resolveSubmoduleLabel('payroll:templates', '模板中心', cfg),
        hint: '闪购与小象标准核算模板',
        active: !isApproval && state.payrollSubView === 'templates',
        action: { type: 'payroll', subView: 'templates' },
      },
      {
        id: 'approval',
        label: resolveSubmoduleLabel('workspace:approval', '价格审批', cfg),
        hint: '筛选本人提审并跨页批量审批',
        active: isApproval,
        action: { type: 'workspace', view: 'approval' },
      },
    ];
    const current = subViews.find(item => item.active) || subViews[0];
    return {
      groupId: 'payroll',
      moduleLabel: resolveModuleGroupLabel('payroll', cfg),
      viewLabel: current.label,
      siblings: subViews,
    };
  }

  const platformManagementSiblings: BreadcrumbSibling[] = [
    {
      id: 'pickup',
      label: resolveSubmoduleLabel('workspace:pickup', '组内共享', cfg),
      hint: '本机成品与局域网组内共享文件一键获取',
      active: state.workspaceView === 'pickup',
      action: { type: 'workspace', view: 'pickup' },
    },
    {
      id: 'platform-auth',
      label: resolveSubmoduleLabel('workspace:platform-auth', '授权管理', cfg),
      hint: '业务平台系统账户绑定、切换与连通性深度巡检',
      active: state.workspaceView === 'platform-auth',
      action: { type: 'workspace', view: 'platform-auth' },
    },
    ...(isAdmin
      ? [
          {
            id: 'accounts',
            label: resolveSubmoduleLabel('workspace:accounts', '用户权限分配', cfg),
            hint: '成员建号、通道与模块分配、权限勾选与安全审计日志',
            active: state.workspaceView === 'accounts',
            action: { type: 'workspace' as const, view: 'accounts' as const },
          },
          {
            id: 'global-config',
            label: resolveSubmoduleLabel('workspace:global-config', '全局配置', cfg),
            hint: '自定义一二级模块名称及资料下载项名称与副标题',
            active: state.workspaceView === 'global-config',
            action: { type: 'workspace' as const, view: 'global-config' as const },
          },
        ]
      : []),
  ];

  const currentPlatformSibling =
    platformManagementSiblings.find(item => item.active) || platformManagementSiblings[0];

  return {
    groupId: groupId === 'admin' ? 'admin' : 'history',
    moduleLabel: resolveModuleGroupLabel('admin', cfg),
    viewLabel: currentPlatformSibling.label,
    siblings: platformManagementSiblings,
  };
}

export function buildShellCommands(
  state: ShellNavState,
  options: {
    sidebarCollapsed?: boolean;
    isAdmin?: boolean;
    permissions?: Record<string, boolean>;
    globalConfig?: GlobalWorkbenchConfig;
  } = {},
): ShellCommandItem[] {
  const cfg = options.globalConfig || getGlobalWorkbenchConfig();
  const groupId = getActiveNavGroup(state);
  const isCollection = groupId === 'collection';
  const isReports = groupId === 'reports';
  const activeReportId = state.reportId || SPECIAL_REPORT_SUBMODULES[0].id;
  const isPayroll = groupId === 'payroll' && state.workspaceView === 'create';
  const isAdmin = Boolean(options.isAdmin);
  const hasPermissionFilter = Boolean(options.permissions) && !isAdmin;
  const canUseModule = (mod: 'collection' | 'reports' | 'payroll' | 'approval') => {
    if (!isAdmin && !isBusinessModuleEnabled(mod, cfg)) return false;
    return !hasPermissionFilter || options.permissions?.[mod] !== false;
  };
  const canUsePlatform = (platformId: DownloadPlatform) =>
    canMemberAccessDownloadPlatform(platformId, {
      isAdmin,
      permissions: options.permissions,
      globalConfig: cfg,
    });

  const collectionGroupName = resolveModuleGroupLabel('collection', cfg);
  const reportsGroupName = resolveModuleGroupLabel('reports', cfg);
  const payrollGroupName = resolveModuleGroupLabel('payroll', cfg);
  const adminGroupName = resolveModuleGroupLabel('admin', cfg);

  const commands: ShellCommandItem[] = [];

  const isCollectionPlatform = isCollection && state.workspaceView === 'create';
  if (canUseModule('collection')) {
    if (canUsePlatform('fengshen')) {
      commands.push({
        id: 'nav-fengshen',
        group: collectionGroupName,
        label: resolveSubmoduleLabel('platform:fengshen', '风神数据', cfg),
        subtitle: '配送费、违规扣款、UB账单、风控运单与考勤源表采集',
        keywords: ['fengshen', 'fs', '风神', '闪购', '配送费', '扣款', '考勤'],
        active: isCollectionPlatform && state.downloadPlatform === 'fengshen',
        action: { type: 'platform', platform: 'fengshen' },
      });
    }
    if (canUsePlatform('lanorange')) {
      commands.push({
        id: 'nav-lanorange',
        group: collectionGroupName,
        label: resolveSubmoduleLabel('platform:lanorange', '蓝橙数据', cfg),
        subtitle: '骑手档案、兼职价格、离职报备与请假全量采集',
        keywords: ['lanorange', 'lc', '蓝橙', '雷神', '离职', '请假', '骑手档案'],
        active: isCollectionPlatform && state.downloadPlatform === 'lanorange',
        action: { type: 'platform', platform: 'lanorange' },
      });
    }
    if (canUsePlatform('lanorange_mdr')) {
      commands.push({
        id: 'nav-lanorange-mdr',
        group: collectionGroupName,
        label: resolveSubmoduleLabel('platform:lanorange_mdr', '新蓝橙数据', cfg),
        subtitle: '新蓝橙系统骑手档案、离职请假、兼全职变更、佣金代领与价格档案采集',
        keywords: ['lanorange_mdr', 'lcmdr', '新蓝橙', '蓝橙新系统', 'mdr', '离职', '请假', '骑手档案'],
        active: isCollectionPlatform && state.downloadPlatform === 'lanorange_mdr',
        action: { type: 'platform', platform: 'lanorange_mdr' },
      });
    }
    if (canUsePlatform('payout')) {
      commands.push({
        id: 'nav-payout',
        group: collectionGroupName,
        label: resolveSubmoduleLabel('platform:payout', '发薪平台', cfg),
        subtitle: '商翼员工总表与本来人力灵工档案实时直采',
        keywords: ['payout', 'fx', 'baize', 'shangyi', 'benlai', '发薪', '白泽', '商翼', '本来'],
        active: isCollectionPlatform && state.downloadPlatform === 'payout',
        action: { type: 'platform', platform: 'payout' },
      });
    }
    if (canUsePlatform('xiaoxiang')) {
      commands.push({
        id: 'nav-xiaoxiang',
        group: collectionGroupName,
        label: resolveSubmoduleLabel('platform:xiaoxiang', '小象灯塔', cfg),
        subtitle: '商配送日维度骑手分析、档案与订单客诉明细',
        keywords: ['xiaoxiang', 'xx', 'dengta', 'dt', '小象', '灯塔', '美团'],
        active: isCollectionPlatform && state.downloadPlatform === 'xiaoxiang',
        action: { type: 'platform', platform: 'xiaoxiang' },
      });
    }
  }

  commands.push({
    id: 'nav-history',
    group: collectionGroupName,
    label: resolveSubmoduleLabel('workspace:history', '任务下载', cfg),
    subtitle: '查看跨平台任务执行记录并一键打包下载成果文件',
    keywords: ['history', 'task', 'rw', 'rwxz', '任务', '任务下载', '任务管理', '任务中心', '记录', '下载', '归档'],
    active: state.workspaceView === 'history',
    action: { type: 'workspace', view: 'history' },
  });

  if (canUseModule('reports')) {
    commands.push(
      ...SPECIAL_REPORT_SUBMODULES.map(report => ({
        id: `nav-report-${report.id}`,
        group: reportsGroupName,
        label: resolveSubmoduleLabel(`report:${report.id}`, report.label, cfg),
        subtitle: report.subtitle,
        keywords: report.keywords,
        active: isReports && activeReportId === report.id,
        action: { type: 'report' as const, reportId: report.id },
      })),
    );
  }

  if (canUseModule('payroll')) {
    commands.push(
      {
        id: 'nav-payroll-batches',
        group: payrollGroupName,
        label: resolveSubmoduleLabel('payroll:batches', '兼职核算', cfg),
        subtitle: '上传兼职薪资申请表，自动齐套资料并执行核算',
        keywords: ['payroll', 'xz', 'hs', '薪资', '核算', '兼职', '工资'],
        active: isPayroll && state.payrollSubView === 'batches',
        action: { type: 'payroll', subView: 'batches' },
      },
      {
        id: 'nav-payroll-deductions',
        group: payrollGroupName,
        label: resolveSubmoduleLabel('payroll:deductions', '扣款配置', cfg),
        subtitle: '按城市与团队维护站点默认扣款金额及关键词',
        keywords: ['deduction', 'kk', '扣款', '站点', '规则', '配置'],
        active: isPayroll && state.payrollSubView === 'deductions',
        action: { type: 'payroll', subView: 'deductions' },
      },
      {
        id: 'nav-payroll-templates',
        group: payrollGroupName,
        label: resolveSubmoduleLabel('payroll:templates', '模板中心', cfg),
        subtitle: '下载与管理淘宝闪购、美团小象标准 Excel 模板',
        keywords: ['template', 'mb', '模板', 'excel', '下载'],
        active: isPayroll && state.payrollSubView === 'templates',
        action: { type: 'payroll', subView: 'templates' },
      },
    );
  }

  if (canUseModule('approval')) {
    commands.push({
      id: 'nav-approval',
      group: payrollGroupName,
      label: resolveSubmoduleLabel('workspace:approval', '价格审批', cfg),
      subtitle: '筛选本人待审单据，跨页勾选并批量审批',
      keywords: ['approval', 'sp', '审批', '价格', '蓝橙'],
      active: state.workspaceView === 'approval',
      action: { type: 'workspace', view: 'approval' },
    });
  }

  commands.push(
    {
      id: 'nav-pickup',
      group: adminGroupName,
      label: resolveSubmoduleLabel('workspace:pickup', '组内共享', cfg),
      subtitle: '按任务领取本机成品，或浏览局域网组内共享电脑的文件',
      keywords: ['pickup', 'lingqu', 'lq', 'zn', 'gx', '组内共享', '文件', '领取', '共享', '局域网', 'ip'],
      active: state.workspaceView === 'pickup',
      action: { type: 'workspace', view: 'pickup' },
    },
    {
      id: 'nav-platform-auth',
      group: adminGroupName,
      label: resolveSubmoduleLabel('workspace:platform-auth', '授权管理', cfg),
      subtitle: '管理风神、蓝橙、商翼、小象灯塔、本来人力系统账号与连接巡检',
      keywords: ['auth', 'login', 'platform', 'dl', 'pt', 'sq', '授权管理', '平台授权', '平台', '登录', '授权', '通道', '扫码', '换号', '切换'],
      active: state.workspaceView === 'platform-auth',
      action: { type: 'workspace', view: 'platform-auth' },
    },
  );

  if (isAdmin) {
    commands.push(
      {
        id: 'nav-accounts',
        group: adminGroupName,
        label: resolveSubmoduleLabel('workspace:accounts', '用户权限分配', cfg),
        subtitle: '新建成员账号、通道与模块双泳道分配、模块权限勾选及安全审计',
        keywords: ['account', 'admin', 'perm', 'audit', 'zh', 'qx', 'yhqxfp', '用户权限分配', '权限分配', '通道分配', '模块分配', '权限管理', '账户', '权限', '审计'],
        active: state.workspaceView === 'accounts',
        action: { type: 'workspace', view: 'accounts' },
      },
      {
        id: 'nav-global-config',
        group: adminGroupName,
        label: resolveSubmoduleLabel('workspace:global-config', '全局配置', cfg),
        subtitle: '修改一二级模块显示名称及数据采集/报表资料名称与副标题',
        keywords: ['config', 'global', 'pz', 'qjpz', '全局配置', '模块名称', '副标题', '名称配置'],
        active: state.workspaceView === 'global-config',
        action: { type: 'workspace', view: 'global-config' },
      },
    );
  }

  commands.push(
    {
      id: 'act-log-drawer',
      group: adminGroupName,
      label: '打开运行日志终端',
      subtitle: '实时检索、按级别筛选、复制与导出引擎运行日志',
      keywords: ['log', 'rz', 'console', 'terminal', '日志', '终端', '调试', '排查'],
      shortcut: 'L',
      active: false,
      action: { type: 'open-logs' },
    },
    {
      id: 'act-toggle-sidebar',
      group: adminGroupName,
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
