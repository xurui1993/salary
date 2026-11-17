/**
 * 平台字典单一数据源（D1：6 个 key 不合并）。
 *
 * 命名口径：
 * - `displayName`：列表 / 卡片 / 弹层标题使用（允许较长，如「灯塔（手动上传）」）。
 * - `shortName`：≤4 字徽标与状态灯使用（全站 `灯塔` 仅归属于 `xiaoxiang`）。
 * - `label`：历史字段，等价于 `shortName`，保留以兼容既有消费方。
 *
 * 约束：本文件为纯数据 + 纯函数，不引入任何依赖，不得包含 DOM 逻辑。
 */

/** 平台字典键：6 个，`dengta` 与 `xiaoxiang` 是两个独立 key，禁止合并。 */
export type SystemKey = 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang' | 'benlai' | 'dengta';

/** 出现在采集侧（列表 / 卡片 / 状态灯）的 5 个 key，不含 `dengta`。 */
export type ConnectionChipKey = 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang' | 'benlai';

/** 平台所属业务面：采集侧还是核算侧。 */
export type PlatformSurface = 'collection' | 'payroll';

/** 头部状态灯 / 徽标短名联合，保持字面量类型以约束调用方。 */
export type ConnectionShortName = '风神' | '蓝橙' | '商翼' | '灯塔' | '本来';

/** 单个平台的完整字典条目。 */
export interface SystemMetaItem {
  /** 字典键。 */
  key: SystemKey;
  /** 全名：列表、卡片、弹层标题。 */
  displayName: string;
  /** 短名：≤4 字徽标 / 状态灯。 */
  shortName: string;
  /**
   * 历史字段：保持改造前字面量（零视觉变更）。
   *
   * 仅供未迁移的旧消费方（如采集页系统筛选条）继续读取；新代码请使用
   * `displayName`（列表/卡片/弹层）或 `shortName`（徽标/状态灯）。
   */
  label: string;
  /** 业务归属说明。 */
  businessLine: string;
  /** 采集 / 核算能力说明。 */
  description: string;
  /** 所属业务面。 */
  surface: PlatformSurface;
  /** 是否为规划中（未接入自动采集）。 */
  planned?: boolean;
}

/** 头部平台状态项（5 个，不含 `dengta`）。 */
export interface ConnectionChip {
  key: ConnectionChipKey;
  displayName: string;
  shortName: ConnectionShortName;
  surface: 'collection';
}

/** 采集页 4 个下载模块（`payout` 为合成项，不对应单个 key）。 */
export type DownloadModuleId = 'fengshen' | 'lanorange' | 'payout' | 'xiaoxiang';

/** 下载模块标签派生结果。 */
export interface DownloadModuleLabel {
  id: DownloadModuleId;
  /** 模块短标签（导航卡标题）。 */
  label: string;
  /** 模块长标签（页头标题）。 */
  navLabel: string;
}

/** 平台字典本体：6 条，顺序即展示顺序。 */
export const SYSTEM_META: SystemMetaItem[] = [
  {
    key: 'fengshen',
    displayName: '风神',
    shortName: '风神',
    label: '风神',
    businessLine: '淘宝闪购自有系统',
    description: '配送费、违规扣款、月度UB账单、骑手绑定、欺诈/问题单等核心账单数据源。',
    surface: 'collection',
  },
  {
    key: 'lanorange',
    displayName: '蓝橙',
    shortName: '蓝橙',
    label: '蓝橙',
    businessLine: '原雷神',
    description: '原雷神 · 骑手人事档案、兼职价格档案、离职/批量离职、请假等内部人事数据源。',
    surface: 'collection',
  },
  {
    key: 'baize',
    displayName: '商翼',
    shortName: '商翼',
    label: '商翼',
    businessLine: '商翼系统',
    description: '商翼全部员工原表独立下载；不随兼职核算自动补齐。',
    surface: 'collection',
  },
  {
    key: 'xiaoxiang',
    displayName: '小象灯塔',
    shortName: '灯塔',
    label: '灯塔',
    businessLine: '美团灯塔系统',
    description: '商配送骑手订单明细与日维度骑手分析，独立下载。',
    surface: 'collection',
  },
  {
    key: 'benlai',
    displayName: '本来人力',
    shortName: '本来',
    label: '本来人力', // 改造前口径，保持不变

    businessLine: '本来人力商户端',
    description: '企业全量灵工档案与签约状态；签约城市用于发薪平台绑定判定。',
    surface: 'collection',
  },
  {
    key: 'dengta',
    displayName: '灯塔（手动上传）',
    shortName: '灯塔手动',
    label: '灯塔手动',
    businessLine: '美团灯塔系统',
    description: '灯塔薪资申请表与配送资料手动上传核算。',
    surface: 'payroll',
  },
];

/** 头部状态灯短名的字面量映射，用于保持 `ConnectionShortName` 的联合类型约束。 */
const CHIP_SHORT_NAMES: Record<ConnectionChipKey, ConnectionShortName> = {
  fengshen: '风神',
  lanorange: '蓝橙',
  baize: '商翼',
  xiaoxiang: '灯塔',
  benlai: '本来',
};

/** 头部状态灯顺序（5 个，`dengta` 不参与）。 */
const CHIP_KEYS: ConnectionChipKey[] = ['fengshen', 'lanorange', 'baize', 'xiaoxiang', 'benlai'];

/** 采集侧 4 个下载模块的标题对（`payout` 为合成项）。 */
const DOWNLOAD_MODULE_LABELS: DownloadModuleLabel[] = [
  { id: 'fengshen', label: '风神', navLabel: '风神数据' },
  { id: 'lanorange', label: '蓝橙', navLabel: '蓝橙数据' },
  { id: 'payout', label: '发薪平台', navLabel: '发薪平台' },
  { id: 'xiaoxiang', label: '灯塔', navLabel: '小象灯塔' },
];

/**
 * 按 key 读取字典条目；未知 key 抛错以便在开发期暴露拼写问题。
 *
 * @param key 平台字典键。
 * @returns 对应的字典条目。
 */
export function systemMeta(key: SystemKey): SystemMetaItem {
  const found = SYSTEM_META.find(item => item.key === key);
  if (!found) throw new Error(`未知平台 key: ${String(key)}`);
  return found;
}

/**
 * 读取平台全名。
 *
 * @param key 平台字典键。
 * @returns 全名，如 `小象灯塔` / `灯塔（手动上传）`。
 */
export function systemLabel(key: SystemKey): string {
  return systemMeta(key).displayName;
}

/**
 * 读取平台短名（≤4 字徽标）。
 *
 * @param key 平台字典键。
 * @returns 短名，如 `灯塔` / `灯塔手动`。
 */
export function systemShortLabel(key: SystemKey): string {
  return systemMeta(key).shortName;
}

/**
 * 头部状态灯数据（5 项，顺序固定，`dengta` 不进入该集合）。
 *
 * @returns 5 个头部状态项的只读拷贝。
 */
export function connectionChips(): ConnectionChip[] {
  return CHIP_KEYS.map(key => ({
    key,
    displayName: systemLabel(key),
    shortName: CHIP_SHORT_NAMES[key],
    surface: 'collection' as const,
  }));
}

/**
 * 采集侧平台集合（4 个 `surface='collection'` 之外的采集通道，含 `dengta` 排除）。
 *
 * @returns `surface='collection'` 的字典条目。
 */
export function collectionSystems(): SystemMetaItem[] {
  return SYSTEM_META.filter(item => item.surface === 'collection');
}

/**
 * 采集页 4 个下载模块的标签派生（`payout` 为合成项，其余来自字典）。
 *
 * @returns 4 个下载模块的 `label` / `navLabel`。
 */
export function downloadModuleLabels(): DownloadModuleLabel[] {
  return DOWNLOAD_MODULE_LABELS.map(item => ({ ...item }));
}
