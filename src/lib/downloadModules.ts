import { isBaize, isBenlai, datasetGroup } from './downloadCenterLogic';
import { inferTaskKind, isGenerator } from './taskCatalog';
import { downloadModuleLabels, type DownloadModuleId } from './platformCatalog';

export type DownloadPlatform = 'fengshen' | 'lanorange' | 'lanorange_mdr' | 'payout' | 'xiaoxiang';
export type RecordModule = DownloadPlatform | 'generate';

/**
 * 从平台字典派生 4 个下载模块的标题对（单一数据源，禁止在此硬编码平台名）。
 *
 * @param id 下载模块 id。
 * @returns `label`（导航卡短标签）与 `navLabel`（页头长标签）。
 */
function moduleLabels(id: DownloadModuleId): {label: string; navLabel: string} {
  const found = downloadModuleLabels().find(item => item.id === id);
  return found ? {label: found.label, navLabel: found.navLabel} : {label: id, navLabel: id};
}


export const DOWNLOAD_PLATFORMS: Array<{
  id: DownloadPlatform;
  label: string;
  navLabel: string;
  badgeLabel: string;
  desc: string;
  iconKey: string;
}> = [
  {
    id: 'fengshen',
    ...moduleLabels('fengshen'),
    badgeLabel: '闪购账单与考勤明细',
    desc: '配送费、违规扣款、UB账单、风控运单与考勤源表采集',
    iconKey: 'compass',
  },
  {
    id: 'lanorange',
    ...moduleLabels('lanorange'),
    badgeLabel: '原雷神人事与价格',
    desc: '骑手人事档案、兼职价格、离职/批量离职与请假全量表',
    iconKey: 'layers',
  },
  {
    id: 'lanorange_mdr',
    ...moduleLabels('lanorange_mdr'),
    badgeLabel: '蓝橙新系统',
    desc: '骑手档案、离职请假、兼全职变更、佣金代领与兼职价格档案原始导出',
    iconKey: 'building-2',
  },
  {
    id: 'payout',
    ...moduleLabels('payout'),
    badgeLabel: '白泽商翼 + 本来人力',
    desc: '商翼员工档案与本来人力灵工签约档案全站直采',
    iconKey: 'users-round',
  },
  {
    id: 'xiaoxiang',
    ...moduleLabels('xiaoxiang'),
    badgeLabel: '美团商配送看板',
    desc: '日维度骑手分析、骑手档案、订单/客诉/评价及周通知附件合并',
    iconKey: 'radar',
  },
];

export function moduleAcceptsDataset(id: string, platform: DownloadPlatform): boolean {
  if (inferTaskKind([id]) !== 'download') return false;
  if (platform === 'payout') return isBaize(id) || isBenlai(id);
  return datasetGroup(id) === platform;
}

export function inferDatasetPlatform(id: string): DownloadPlatform {
  if (isBaize(id) || isBenlai(id)) return 'payout';
  if (datasetGroup(id) === 'xiaoxiang') return 'xiaoxiang';
  if (!isGenerator(id) && datasetGroup(id) === 'lanorange_mdr') return 'lanorange_mdr';
  if (!isGenerator(id) && datasetGroup(id) === 'lanorange') return 'lanorange';
  return 'fengshen';
}

export function toggleCrossPlatformDataset(currentIds: string[], targetId: string): string[] {
  if (currentIds.includes(targetId)) {
    return currentIds.filter(id => id !== targetId);
  }
  return [...currentIds, targetId];
}

export function groupDatasetsByPlatform(datasetIds: string[]): Record<DownloadPlatform, string[]> {
  const grouped: Record<DownloadPlatform, string[]> = {
    fengshen: [],
    lanorange: [],
    lanorange_mdr: [],
    payout: [],
    xiaoxiang: [],
  };
  for (const id of datasetIds) {
    const plat = inferDatasetPlatform(id);
    grouped[plat].push(id);
  }
  return grouped;
}

export interface DynamicPlatformScopeReq {
  hasSelection: boolean;
  needsCity: boolean;
  cityOptional: boolean;
  needsDate: boolean;
  needsSeparationRule: boolean;
  autoScopeBadge: string | null;
  autoScopeDesc: string | null;
}

const FENGSHEN_NO_DATE_DATASETS = new Set([
  'invitation_records',
  'rider_info',
  'goods_rent',
]);

export function computeDynamicScopeRequirements(
  platform: DownloadPlatform,
  platformDatasets: string[],
): DynamicPlatformScopeReq {
  if (platformDatasets.length === 0) {
    return {
      hasSelection: false,
      needsCity: false,
      cityOptional: false,
      needsDate: false,
      needsSeparationRule: false,
      autoScopeBadge: '待选择资料',
      autoScopeDesc: '请先在「01 选择资料」勾选需要采集的数据表，系统将根据所选资料自动展开所需的城市与账期配置。',
    };
  }

  if (platform === 'payout') {
    return {
      hasSelection: true,
      needsCity: false,
      cityOptional: false,
      needsDate: false,
      needsSeparationRule: false,
      autoScopeBadge: '全站全城 · 实时全量快照',
      autoScopeDesc: '白泽商翼与本来人力均按账号授权范围全量直采最新档案，无需配置城市或月份账期。',
    };
  }

  if (platform === 'lanorange_mdr') {
    const needsDate = platformDatasets.some(id => id === 'lcmdr_part_price' || id === 'lcmdr_commission_proxy');
    return {
      hasSelection: true,
      needsCity: true,
      cityOptional: false,
      needsDate,
      needsSeparationRule: false,
      autoScopeBadge: needsDate ? null : '账号授权范围 · 城市必选',
      autoScopeDesc: needsDate
        ? null
        : '新蓝橙所选资料按账号授权范围导出：请选择城市；价格档案与佣金代领按月份筛选，其余资料导出最新全量。',
    };
  }

  if (platform === 'lanorange') {
    const needsDate = platformDatasets.includes('lanorange_part_price');
    return {
      hasSelection: true,
      needsCity: true,
      cityOptional: true,
      needsDate,
      needsSeparationRule: false,
      autoScopeBadge: needsDate ? null : '全量最新人事档案 · 免选月份',
      autoScopeDesc: needsDate
        ? null
        : '当前所选蓝橙人事表均按最新全量状态导出，无需选择月份；可按需筛选合作城市或直接默认全城导出。',
    };
  }

  if (platform === 'xiaoxiang') {
    const archiveOnly = platformDatasets.every(id => id === 'rider_archive');
    return {
      hasSelection: true,
      needsCity: !archiveOnly,
      cityOptional: true,
      needsDate: !archiveOnly,
      needsSeparationRule: false,
      autoScopeBadge: archiveOnly ? '全城站点 · 实时档案快照' : null,
      autoScopeDesc: archiveOnly
        ? '「骑手档案（灯塔）」直接导出当前账号下全部站点在网快照，无需配置城市与日期范围。'
        : null,
    };
  }

  // fengshen (raw collection datasets only; business reports live in dedicated 业务报表 module)

  const needsDate = platformDatasets.some(id => !FENGSHEN_NO_DATE_DATASETS.has(id));
  const merchantOnly = platformDatasets.every(id => id === 'invitation_records' || id === 'attendance_detail');

  return {
    hasSelection: true,
    needsCity: true,
    cityOptional: false,
    needsDate,
    needsSeparationRule: !merchantOnly,
    autoScopeBadge: !needsDate ? '当前快照资料 · 免选月份账期' : null,
    autoScopeDesc: !needsDate
      ? '当前所选资料（如骑手信息导出、物资租用登记、邀请记录）均为实时全量快照，仅需选择目标城市即可提交。'
      : null,
  };
}

export function matchesRecordModule(
  record: { kind?: string; datasets: string[] },
  module?: RecordModule,
): boolean {
  if (!module) return true;
  const kind = record.kind || inferTaskKind(record.datasets);
  if (module === 'generate') return kind === 'generate';
  return kind === 'download' && record.datasets.some(id => moduleAcceptsDataset(id, module));
}

