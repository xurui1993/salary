import { useSyncExternalStore } from 'react';

export type ChannelMode = 'personal' | 'shared';

export type PlatformChannelKey =
  | 'fengshen'
  | 'lanorange'
  | 'lanorange_mdr'
  | 'baize'
  | 'xiaoxiang'
  | 'benlai';

export type BusinessModuleKey = 'collection' | 'reports' | 'payroll' | 'approval';

export type ModuleGroupKey = 'collection' | 'reports' | 'payroll' | 'admin';

export interface DatasetOverride {
  title?: string;
  desc?: string;
}

export interface GlobalWorkbenchConfig {
  version: number;
  updated_at: number;
  channel_modes: Record<PlatformChannelKey, ChannelMode>;
  module_permissions: Record<BusinessModuleKey, boolean>;
  module_names: {
    groups: Record<string, string>;
    items: Record<string, string>;
  };
  dataset_overrides: Record<string, DatasetOverride>;
}

export interface PlatformChannelMeta {
  key: PlatformChannelKey;
  defaultLabel: string;
  defaultMode: ChannelMode;
  usePermissionKey:
    | 'fengshen_use'
    | 'lanorange_use'
    | 'lanorange_mdr_use'
    | 'baize_use'
    | 'xiaoxiang_use'
    | 'benlai_use';
  badge: string;
  desc: string;
  relatedModules: string;
}

export interface BusinessModuleMeta {
  key: BusinessModuleKey;
  defaultLabel: string;
  desc: string;
}

export interface ModuleGroupCatalogItem {
  id: ModuleGroupKey;
  defaultLabel: string;
  desc: string;
}

export interface SubmoduleCatalogItem {
  id: string;
  groupId: ModuleGroupKey;
  defaultLabel: string;
  hint: string;
}

export interface DatasetCatalogItem {
  id: string;
  category: 'fengshen' | 'lanorange' | 'lanorange_mdr' | 'payout' | 'xiaoxiang' | 'reports';
  categoryLabel: string;
  defaultTitle: string;
  defaultDesc: string;
  scopeTag: string;
}

export const PLATFORM_CHANNEL_CATALOG: PlatformChannelMeta[] = [
  {
    key: 'fengshen',
    defaultLabel: '风神',
    defaultMode: 'personal',
    usePermissionKey: 'fengshen_use',
    badge: '淘宝闪购自有系统',
    desc: '配送费、违规扣款、UB账单、考勤及兼职核算主数据源',
    relatedModules: '风神数据 / 支付绑定 / 异常跟进 / 问题单 / 兼职核算',
  },
  {
    key: 'lanorange',
    defaultLabel: '蓝橙',
    defaultMode: 'personal',
    usePermissionKey: 'lanorange_use',
    badge: '原雷神人事与审批',
    desc: '骑手档案、兼职价格、离职请假及每日价格批量审批',
    relatedModules: '蓝橙数据 / 价格审批 / 异常名单 / 支付绑定',
  },
  {
    key: 'lanorange_mdr',
    defaultLabel: '新蓝橙',
    defaultMode: 'personal',
    usePermissionKey: 'lanorange_mdr_use',
    badge: '蓝橙新系统 (MDR)',
    desc: '新系统骑手档案、离职请假、兼全职变更与佣金代领',
    relatedModules: '新蓝橙数据',
  },
  {
    key: 'baize',
    defaultLabel: '商翼',
    defaultMode: 'personal',
    usePermissionKey: 'baize_use',
    badge: '白泽商翼商户端',
    desc: '商翼全部员工原表与发薪平台绑定判定',
    relatedModules: '发薪平台 / 支付绑定',
  },
  {
    key: 'xiaoxiang',
    defaultLabel: '小象灯塔',
    defaultMode: 'shared',
    usePermissionKey: 'xiaoxiang_use',
    badge: '美团灯塔 + 知了看板',
    desc: '日维度骑手分析、骑手档案、订单/客诉明细及小象核算',
    relatedModules: '小象灯塔 / 兼职核算（小象）',
  },
  {
    key: 'benlai',
    defaultLabel: '本来人力',
    defaultMode: 'shared',
    usePermissionKey: 'benlai_use',
    badge: '灵工签约档案',
    desc: '企业全量灵工签约档案与签约城市绑定判定',
    relatedModules: '发薪平台 / 支付绑定',
  },
];

export const BUSINESS_MODULE_CATALOG: BusinessModuleMeta[] = [
  {
    key: 'collection',
    defaultLabel: '数据采集',
    desc: '风神、蓝橙、新蓝橙、发薪平台、小象灯塔数据采集与任务下载',
  },
  {
    key: 'reports',
    defaultLabel: '业务报表',
    desc: '支付绑定、异常跟进、异常名单与问题单汇总生成',
  },
  {
    key: 'payroll',
    defaultLabel: '薪资核算',
    desc: '兼职核算队列、扣款配置与标准模板中心',
  },
  {
    key: 'approval',
    defaultLabel: '价格审批',
    desc: '蓝橙待办审批列表与每日价格表导出',
  },
];

export const MODULE_GROUP_CATALOG: ModuleGroupCatalogItem[] = [
  { id: 'collection', defaultLabel: '数据采集', desc: '左侧导航一级模块分组名称' },
  { id: 'reports', defaultLabel: '业务报表', desc: '左侧导航一级模块分组名称' },
  { id: 'payroll', defaultLabel: '薪资核算', desc: '左侧导航一级模块分组名称' },
  { id: 'admin', defaultLabel: '平台管理', desc: '左侧导航一级模块分组名称' },
];

export const SUBMODULE_CATALOG: SubmoduleCatalogItem[] = [
  { id: 'platform:fengshen', groupId: 'collection', defaultLabel: '风神数据', hint: '数据采集 · 子模块' },
  { id: 'platform:lanorange', groupId: 'collection', defaultLabel: '蓝橙数据', hint: '数据采集 · 子模块' },
  { id: 'platform:lanorange_mdr', groupId: 'collection', defaultLabel: '新蓝橙数据', hint: '数据采集 · 子模块' },
  { id: 'platform:payout', groupId: 'collection', defaultLabel: '发薪平台', hint: '数据采集 · 子模块' },
  { id: 'platform:xiaoxiang', groupId: 'collection', defaultLabel: '小象灯塔', hint: '数据采集 · 子模块' },
  { id: 'workspace:history', groupId: 'collection', defaultLabel: '任务下载', hint: '数据采集 · 子模块' },
  { id: 'report:payment_binding', groupId: 'reports', defaultLabel: '支付绑定', hint: '业务报表 · 子模块' },
  { id: 'report:abnormal_followup', groupId: 'reports', defaultLabel: '异常跟进', hint: '业务报表 · 子模块' },
  { id: 'report:abnormal_riders', groupId: 'reports', defaultLabel: '异常名单', hint: '业务报表 · 子模块' },
  { id: 'report:problem', groupId: 'reports', defaultLabel: '问题单', hint: '业务报表 · 子模块' },
  { id: 'payroll:batches', groupId: 'payroll', defaultLabel: '兼职核算', hint: '薪资核算 · 子模块' },
  { id: 'payroll:deductions', groupId: 'payroll', defaultLabel: '扣款配置', hint: '薪资核算 · 子模块' },
  { id: 'payroll:templates', groupId: 'payroll', defaultLabel: '模板中心', hint: '薪资核算 · 子模块' },
  { id: 'workspace:approval', groupId: 'payroll', defaultLabel: '价格审批', hint: '薪资核算 · 子模块' },
  { id: 'workspace:pickup', groupId: 'admin', defaultLabel: '组内共享', hint: '平台管理 · 子模块' },
  { id: 'workspace:platform-auth', groupId: 'admin', defaultLabel: '授权管理', hint: '平台管理 · 子模块' },
  { id: 'workspace:accounts', groupId: 'admin', defaultLabel: '用户权限分配', hint: '平台管理 · 子模块' },
  { id: 'workspace:global-config', groupId: 'admin', defaultLabel: '全局配置', hint: '平台管理 · 子模块' },
];

export const DATASET_CONFIG_CATALOG: DatasetCatalogItem[] = [
  // 风神数据
  { id: 'invitation_records', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·全量', defaultTitle: '邀请记录', defaultDesc: '支持多选城市，分别下载各城市全部邀请记录' },
  { id: 'attendance_detail', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '骑手出勤明细', defaultDesc: '支持多选城市，按近90天内的日期下载各城市出勤明细' },
  { id: 'delivery_fee', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '配送费', defaultDesc: '站点完单量、基础费与补贴' },
  { id: 'penalty', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '违规扣款', defaultDesc: '投诉、超时与差评扣款明细' },
  { id: 'rider_monthly', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·按月', defaultTitle: '月度 UB 账单', defaultDesc: '自然月骑手 UB 综合核算账单' },
  { id: 'fraud', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '欺诈单', defaultDesc: '虚假妥投、刷单与风控明细' },
  { id: 'problem', category: 'fengshen', categoryLabel: '风神数据 / 业务报表', scopeTag: '城市·账期', defaultTitle: '问题单', defaultDesc: '配送异常、餐损与判责明细' },
  { id: 'receive_account', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·按月', defaultTitle: '骑手风神绑定', defaultDesc: '收薪账户与风神身份绑定明细' },
  { id: 'rider_detail', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '骑手数据明细', defaultDesc: '日均单量、在线时长与准时率' },
  { id: 'rider_info', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·快照', defaultTitle: '骑手信息导出', defaultDesc: '在网骑手身份、站点与入职表' },
  { id: 'goods_rent', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·快照', defaultTitle: '物资租用登记', defaultDesc: '工服、餐箱及电池领用扣款表' },
  { id: 'delivery_waybill', category: 'fengshen', categoryLabel: '风神数据', scopeTag: '城市·账期', defaultTitle: '运单数据', defaultDesc: '按运单终态时间导出城市运单明细，支持全城送标品筛选' },

  // 蓝橙数据
  { id: 'lanorange_rider_quit', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '骑手离职', defaultDesc: '全城骑手正常离职审批与交接明细' },
  { id: 'lanorange_rider_report', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '离职报备', defaultDesc: '各站点上报骑手离职报备流水记录' },
  { id: 'lanorange_batch_quit', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '批量离职', defaultDesc: '站点集中清退与批量离职归档记录' },
  { id: 'lanorange_rider_leave', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '骑手请假', defaultDesc: '全部城市骑手病事假、休假审批表' },
  { id: 'lanorange_identity_change', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '骑手兼全职变更', defaultDesc: '专送与众包兼全职身份转换记录表' },
  { id: 'lanorange_salary_replace', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '佣金代领', defaultDesc: '骑手薪资佣金代发代领授权关系表' },
  { id: 'lanorange_part_price', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '按月', defaultTitle: '价格档案', defaultDesc: '各城市站点兼职阶梯单价与补贴表' },
  { id: 'lanorange_rider_archive', category: 'lanorange', categoryLabel: '蓝橙数据', scopeTag: '全城·全量', defaultTitle: '骑手档案', defaultDesc: '原雷神在职与离职骑手人事总档案' },

  // 新蓝橙数据
  { id: 'lcmdr_archive', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '骑手档案', defaultDesc: '新蓝橙系统骑手在职与离职人事档案明细' },
  { id: 'lcmdr_exit', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '骑手离职', defaultDesc: '新蓝橙系统骑手离职审批与结算明细' },
  { id: 'lcmdr_batch_exit', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '批量离职', defaultDesc: '新蓝橙系统批量离职处理归档明细' },
  { id: 'lcmdr_exit_report', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '离职报备', defaultDesc: '新蓝橙系统站点上报离职报备记录' },
  { id: 'lcmdr_leave', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '骑手请假', defaultDesc: '新蓝橙系统骑手请假与休假审批明细' },
  { id: 'lcmdr_type_change', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·全量', defaultTitle: '骑手兼全职变更', defaultDesc: '新蓝橙系统兼职与全职身份转换记录' },
  { id: 'lcmdr_commission_proxy', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·按月', defaultTitle: '佣金代领', defaultDesc: '新蓝橙系统按月佣金代发代领明细表' },
  { id: 'lcmdr_part_price', category: 'lanorange_mdr', categoryLabel: '新蓝橙数据', scopeTag: '城市·按月', defaultTitle: '兼职价格档案', defaultDesc: '新蓝橙系统各城市站点兼职阶梯单价表' },

  // 发薪平台
  { id: 'baize_employees', category: 'payout', categoryLabel: '发薪平台', scopeTag: '全站·全量', defaultTitle: '商翼员工资料', defaultDesc: '导出商翼系统全量在职与离职员工原始档案表，独立归档不参与兼职自动补齐' },
  { id: 'benlai_employees', category: 'payout', categoryLabel: '发薪平台', scopeTag: '全城·全量', defaultTitle: '本来人力灵工资料', defaultDesc: '导出本来人力全量灵工档案与实时签约城市，用于发薪平台绑定判定' },

  // 小象灯塔
  { id: 'rider_daily', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '日维度骑手分析', defaultDesc: '商配送骑手日维度单量与人效分析' },
  { id: 'rider_archive', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·快照', defaultTitle: '骑手档案', defaultDesc: '灯塔全城骑手身份与站点归属快照' },
  { id: 'detail_orders', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '配送订单明细', defaultDesc: '商配送逐单运单状态与时效距离表' },
  { id: 'detail_kesu', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '配送客诉明细', defaultDesc: '商配送客户投诉、索赔与判责明细' },
  { id: 'detail_reviews', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '配送评价明细', defaultDesc: '订单客户星级评价与好差评标签表' },
  { id: 'rider_order_detail', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '骑手订单明细', defaultDesc: '灯塔周通知【商配送】骑手订单明细附件按数据日期区间合并' },
  { id: 'xiaoxiang_attendance_detail', category: 'xiaoxiang', categoryLabel: '小象灯塔', scopeTag: '全城·日期', defaultTitle: '骑手出勤明细', defaultDesc: '灯塔「合作商数据下发」通知骑手出勤明细附件按数据日期区间合并' },

  // 业务报表生成项
  { id: 'payment_binding', category: 'reports', categoryLabel: '业务报表', scopeTag: '生成·按月', defaultTitle: '支付绑定', defaultDesc: '自动关联风神收薪绑定与蓝橙、发薪档案，输出支付绑定及多城汇总' },
  { id: 'abnormal_followup', category: 'reports', categoryLabel: '业务报表', scopeTag: '生成·按月', defaultTitle: '异常跟进', defaultDesc: '以支付绑定为基准，关联物资、UB账单与价格档案，输出异常待跟进表' },
  { id: 'abnormal_riders', category: 'reports', categoryLabel: '业务报表', scopeTag: '生成·全量', defaultTitle: '异常名单', defaultDesc: '固定全城全量汇总蓝橙离职、请假与骑手档案（免选城市与月份）' },
];

export const DEFAULT_GLOBAL_WORKBENCH_CONFIG: GlobalWorkbenchConfig = {
  version: 1,
  updated_at: 0,
  channel_modes: {
    fengshen: 'personal',
    lanorange: 'personal',
    lanorange_mdr: 'personal',
    baize: 'personal',
    xiaoxiang: 'shared',
    benlai: 'shared',
  },
  module_permissions: {
    collection: true,
    reports: true,
    payroll: true,
    approval: true,
  },
  module_names: {
    groups: {},
    items: {},
  },
  dataset_overrides: {},
};

const GROUP_DEFAULT_MAP = new Map(MODULE_GROUP_CATALOG.map(g => [g.id, g.defaultLabel]));
const ITEM_DEFAULT_MAP = new Map(SUBMODULE_CATALOG.map(i => [i.id, i.defaultLabel]));

export function cloneGlobalWorkbenchConfig(cfg: GlobalWorkbenchConfig): GlobalWorkbenchConfig {
  return {
    version: cfg.version,
    updated_at: cfg.updated_at,
    channel_modes: { ...cfg.channel_modes },
    module_permissions: { ...cfg.module_permissions },
    module_names: {
      groups: { ...cfg.module_names.groups },
      items: { ...cfg.module_names.items },
    },
    dataset_overrides: Object.fromEntries(
      Object.entries(cfg.dataset_overrides).map(([k, v]) => [k, { ...v }]),
    ),
  };
}

export function normalizeGlobalWorkbenchConfig(
  raw?: Partial<GlobalWorkbenchConfig> | null,
): GlobalWorkbenchConfig {
  const base = cloneGlobalWorkbenchConfig(DEFAULT_GLOBAL_WORKBENCH_CONFIG);
  if (!raw || typeof raw !== 'object') return base;
  if (typeof raw.version === 'number' && Number.isFinite(raw.version) && raw.version >= 1) {
    base.version = Math.floor(raw.version);
  }
  if (typeof raw.updated_at === 'number' && Number.isFinite(raw.updated_at)) {
    base.updated_at = raw.updated_at;
  }
  if (raw.channel_modes && typeof raw.channel_modes === 'object') {
    for (const meta of PLATFORM_CHANNEL_CATALOG) {
      const mode = raw.channel_modes[meta.key];
      if (mode === 'personal' || mode === 'shared') {
        base.channel_modes[meta.key] = mode;
      }
    }
  }
  if (raw.module_permissions && typeof raw.module_permissions === 'object') {
    for (const mod of BUSINESS_MODULE_CATALOG) {
      if (typeof raw.module_permissions[mod.key] === 'boolean') {
        base.module_permissions[mod.key] = raw.module_permissions[mod.key];
      }
    }
  }
  if (raw.module_names && typeof raw.module_names === 'object') {
    if (raw.module_names.groups && typeof raw.module_names.groups === 'object') {
      for (const [k, v] of Object.entries(raw.module_names.groups)) {
        if (typeof v === 'string') {
          const clean = v.trim();
          const def = GROUP_DEFAULT_MAP.get(k as ModuleGroupKey);
          if (clean && clean !== def) {
            base.module_names.groups[k] = clean;
          }
        }
      }
    }
    if (raw.module_names.items && typeof raw.module_names.items === 'object') {
      for (const [k, v] of Object.entries(raw.module_names.items)) {
        if (typeof v === 'string') {
          const clean = v.trim();
          const def = ITEM_DEFAULT_MAP.get(k);
          if (clean && clean !== def) {
            base.module_names.items[k] = clean;
          }
        }
      }
    }
  }
  if (raw.dataset_overrides && typeof raw.dataset_overrides === 'object') {
    for (const [dsId, entry] of Object.entries(raw.dataset_overrides)) {
      if (!entry || typeof entry !== 'object') continue;
      const title = typeof entry.title === 'string' ? entry.title.trim() : '';
      const desc = typeof entry.desc === 'string' ? entry.desc.trim() : '';
      if (title || desc) {
        base.dataset_overrides[dsId] = {
          ...(title ? { title } : {}),
          ...(desc ? { desc } : {}),
        };
      }
    }
  }
  return base;
}

let _currentConfig: GlobalWorkbenchConfig = cloneGlobalWorkbenchConfig(DEFAULT_GLOBAL_WORKBENCH_CONFIG);
const _listeners = new Set<() => void>();

export function getGlobalWorkbenchConfig(): GlobalWorkbenchConfig {
  return _currentConfig;
}

export function setGlobalWorkbenchConfig(
  next?: Partial<GlobalWorkbenchConfig> | null,
): GlobalWorkbenchConfig {
  const normalized = normalizeGlobalWorkbenchConfig(next);
  _currentConfig = normalized;
  for (const listener of _listeners) {
    listener();
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('workbench:global-config-changed', { detail: normalized }));
  }
  return normalized;
}

function subscribeConfig(listener: () => void): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}

export function useGlobalWorkbenchConfig(): GlobalWorkbenchConfig {
  return useSyncExternalStore(subscribeConfig, getGlobalWorkbenchConfig, getGlobalWorkbenchConfig);
}

export function resolveChannelMode(
  platform: PlatformChannelKey,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): ChannelMode {
  return cfg.channel_modes[platform] === 'shared' ? 'shared' : 'personal';
}

export function isPlatformShared(
  platform: PlatformChannelKey,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): boolean {
  return resolveChannelMode(platform, cfg) === 'shared';
}

export function isBusinessModuleEnabled(
  moduleKey: BusinessModuleKey,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): boolean {
  return cfg.module_permissions[moduleKey] !== false;
}

export function resolveModuleGroupLabel(
  groupId: string,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): string {
  const custom = cfg.module_names.groups[groupId]?.trim();
  if (custom) return custom;
  return GROUP_DEFAULT_MAP.get(groupId as ModuleGroupKey) || groupId;
}

export function resolveSubmoduleLabel(
  itemId: string,
  fallback?: string,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): string {
  const custom = cfg.module_names.items[itemId]?.trim();
  if (custom) return custom;
  return ITEM_DEFAULT_MAP.get(itemId) || fallback || itemId;
}

export function resolveDatasetCardCopy(
  datasetId: string,
  defaultTitle: string,
  defaultDesc: string,
  cfg: GlobalWorkbenchConfig = _currentConfig,
): { title: string; desc: string } {
  const override = cfg.dataset_overrides[datasetId];
  return {
    title: override?.title?.trim() || defaultTitle,
    desc: override?.desc?.trim() || defaultDesc,
  };
}

export interface DynamicPermissionItem {
  key: string;
  label: string;
  desc: string;
  globallyPaused?: boolean;
}

export interface DynamicPermissionGroup {
  id: 'modules' | 'shared_channels';
  title: string;
  items: DynamicPermissionItem[];
}

export function getDynamicPermissionGroups(
  cfg: GlobalWorkbenchConfig = _currentConfig,
): DynamicPermissionGroup[] {
  const moduleItems: DynamicPermissionItem[] = [
    {
      key: 'collection',
      label: resolveModuleGroupLabel('collection', cfg),
      desc: `${resolveSubmoduleLabel('platform:fengshen', '风神数据', cfg)}、${resolveSubmoduleLabel('platform:lanorange', '蓝橙数据', cfg)}、${resolveSubmoduleLabel('platform:payout', '发薪平台', cfg)}等原始资料采集`,
      globallyPaused: !isBusinessModuleEnabled('collection', cfg),
    },
    {
      key: 'reports',
      label: resolveModuleGroupLabel('reports', cfg),
      desc: `${resolveSubmoduleLabel('report:payment_binding', '支付绑定', cfg)}、${resolveSubmoduleLabel('report:abnormal_followup', '异常跟进', cfg)}、${resolveSubmoduleLabel('report:abnormal_riders', '异常名单', cfg)}与${resolveSubmoduleLabel('report:problem', '问题单', cfg)}`,
      globallyPaused: !isBusinessModuleEnabled('reports', cfg),
    },
    {
      key: 'payroll',
      label: resolveModuleGroupLabel('payroll', cfg),
      desc: `${resolveSubmoduleLabel('payroll:batches', '兼职核算', cfg)}、${resolveSubmoduleLabel('payroll:deductions', '扣款配置', cfg)}与${resolveSubmoduleLabel('payroll:templates', '模板中心', cfg)}`,
      globallyPaused: !isBusinessModuleEnabled('payroll', cfg),
    },
    {
      key: 'approval',
      label: resolveSubmoduleLabel('workspace:approval', '价格审批', cfg),
      desc: '蓝橙待办审批列表与每日价格导出',
      globallyPaused: !isBusinessModuleEnabled('approval', cfg),
    },
  ];

  const sharedPlatforms = PLATFORM_CHANNEL_CATALOG.filter(
    item => resolveChannelMode(item.key, cfg) === 'shared',
  );

  const sharedItems: DynamicPermissionItem[] = sharedPlatforms.map(plat => ({
    key: plat.usePermissionKey,
    label: `共享${plat.defaultLabel}`,
    desc: `复用主机${plat.defaultLabel}连接执行数据采集与关联查询`,
  }));

  const sharedNamesSummary = sharedPlatforms.length
    ? sharedPlatforms.map(p => p.defaultLabel).join('与')
    : '当前无共享平台';

  sharedItems.push({
    key: 'shared_auth_manage',
    label: '维护共享连接',
    desc: sharedPlatforms.length
      ? `允许登录或断开共享通道（${sharedNamesSummary}）`
      : '当前所有平台均为个人独立通道；设为共享后将在此生效',
  });

  return [
    {
      id: 'modules',
      title: '业务模块',
      items: moduleItems,
    },
    {
      id: 'shared_channels',
      title: '共享通道',
      items: sharedItems,
    },
  ];
}

export function countGlobalConfigCustomizations(
  cfg: GlobalWorkbenchConfig = _currentConfig,
): { channels: number; modules: number; names: number; datasets: number } {
  let channels = 0;
  for (const meta of PLATFORM_CHANNEL_CATALOG) {
    if (cfg.channel_modes[meta.key] !== meta.defaultMode) channels += 1;
  }
  let modules = 0;
  for (const mod of BUSINESS_MODULE_CATALOG) {
    if (cfg.module_permissions[mod.key] !== true) modules += 1;
  }
  const names =
    Object.keys(cfg.module_names.groups).length + Object.keys(cfg.module_names.items).length;
  const datasets = Object.keys(cfg.dataset_overrides).length;
  return { channels, modules, names, datasets };
}

export interface PlatformChannelPartition {
  shared: PlatformChannelMeta[];
  personal: PlatformChannelMeta[];
  allShared: PlatformChannelMeta[];
  allPersonal: PlatformChannelMeta[];
}

export function partitionPlatformChannels(
  cfg: GlobalWorkbenchConfig = _currentConfig,
  rawQuery = '',
): PlatformChannelPartition {
  const q = rawQuery.trim().toLowerCase();
  const allShared: PlatformChannelMeta[] = [];
  const allPersonal: PlatformChannelMeta[] = [];
  for (const item of PLATFORM_CHANNEL_CATALOG) {
    if (resolveChannelMode(item.key, cfg) === 'shared') {
      allShared.push(item);
    } else {
      allPersonal.push(item);
    }
  }
  if (!q) {
    return { shared: allShared, personal: allPersonal, allShared, allPersonal };
  }
  const matches = (item: PlatformChannelMeta) =>
    `${item.defaultLabel} ${item.key} ${item.badge} ${item.desc} ${item.relatedModules}`
      .toLowerCase()
      .includes(q);
  return {
    shared: allShared.filter(matches),
    personal: allPersonal.filter(matches),
    allShared,
    allPersonal,
  };
}

export interface BusinessModulePartition {
  enabled: BusinessModuleMeta[];
  paused: BusinessModuleMeta[];
  allEnabled: BusinessModuleMeta[];
  allPaused: BusinessModuleMeta[];
}

export function partitionBusinessModules(
  cfg: GlobalWorkbenchConfig = _currentConfig,
  rawQuery = '',
): BusinessModulePartition {
  const q = rawQuery.trim().toLowerCase();
  const allEnabled: BusinessModuleMeta[] = [];
  const allPaused: BusinessModuleMeta[] = [];
  for (const mod of BUSINESS_MODULE_CATALOG) {
    if (isBusinessModuleEnabled(mod.key, cfg)) {
      allEnabled.push(mod);
    } else {
      allPaused.push(mod);
    }
  }
  if (!q) {
    return { enabled: allEnabled, paused: allPaused, allEnabled, allPaused };
  }
  const matches = (mod: BusinessModuleMeta) => {
    const resolvedName =
      mod.key === 'approval'
        ? resolveSubmoduleLabel('workspace:approval', mod.defaultLabel, cfg)
        : resolveModuleGroupLabel(mod.key, cfg);
    return `${resolvedName} ${mod.defaultLabel} ${mod.key} ${mod.desc}`
      .toLowerCase()
      .includes(q);
  };
  return {
    enabled: allEnabled.filter(matches),
    paused: allPaused.filter(matches),
    allEnabled,
    allPaused,
  };
}

export function applyPlatformChannelMode(
  cfg: GlobalWorkbenchConfig,
  key: PlatformChannelKey,
  mode: ChannelMode,
): Record<PlatformChannelKey, ChannelMode> {
  return {
    ...cfg.channel_modes,
    [key]: mode,
  };
}

export function applyBusinessModuleEnabled(
  cfg: GlobalWorkbenchConfig,
  key: BusinessModuleKey,
  enabled: boolean,
): Record<BusinessModuleKey, boolean> {
  return {
    ...cfg.module_permissions,
    [key]: enabled,
  };
}

