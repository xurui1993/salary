import type { DeductionEntry } from '../components/DeductionAmounts';

export type DeductionCategoryId = 'all' | 'violation' | 'tools' | 'fund_monthly' | 'xiaoxiang_fees' | 'extended';

export interface DeductionCategorySpec {
  id: Exclude<DeductionCategoryId, 'all'>;
  label: string;
  description: string;
  unitHint: string;
  columns: string[];
}

export const CONFIG_RULE_COLUMNS = [
  '投诉',
  '差评',
  '违规虚假',
  '物流责',
  '不准时单',
  '超时',
  'T10',
  '工具费',
  '代领费率',
  '安全基金',
  '使用费',
  '非蜂卡',
  '月费',
] as const;

export const CONFIG_RULE_COLUMNS_WITH_THRESHOLDS = [
  '投诉',
  '差评',
  '违规虚假',
  '物流责',
  '不准时单',
  '超时',
  'T10',
  '工具费',
  '代领费率',
  '安全基金',
  '安全基金_maxDays',
  '使用费',
  '使用费_maxDays',
  '非蜂卡',
  '月费',
] as const;

export const COLUMN_DISPLAY_LABELS: Record<string, string> = {
  安全基金_maxDays: '安全基金天数阈值',
  使用费_maxDays: '使用费天数阈值',
};

export function columnDisplayLabel(column: string): string {
  return COLUMN_DISPLAY_LABELS[column] || column;
}

export function normalizeConfigColumnKey(key: unknown): string {
  const text = String(key ?? '').trim();
  const matched = Object.entries(COLUMN_DISPLAY_LABELS).find(([, label]) => label === text);
  return matched ? matched[0] : text;
}

function normalizeConfigRecord(row: Record<string, unknown>): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    normalized[normalizeConfigColumnKey(key)] = value;
  }
  return normalized;
}

export const DEDUCTION_CATEGORY_TEMPLATES: DeductionCategorySpec[] = [
  {
    id: 'violation',
    label: '违规与时效扣款',
    description: '投诉、差评、违规虚假、物流责及不准时/超时/T10 履约扣款口径',
    unitHint: '元/单或元/次',
    columns: ['投诉', '差评', '违规虚假', '物流责', '不准时单', '超时', 'T10'],
  },
  {
    id: 'tools',
    label: '工具与代领费率',
    description: '工服装备、物料工具费及佣金代领比例/金额扣款口径',
    unitHint: '元或费率',
    columns: ['工具费', '代领费率'],
  },
  {
    id: 'fund_monthly',
    label: '保障基金与月费',
    description: '安全基金、平台使用费、非蜂卡及固定月费日常扣款口径',
    unitHint: '元/天或元/月',
    columns: ['安全基金', '安全基金_maxDays', '使用费', '使用费_maxDays', '非蜂卡', '月费'],
  },
  {
    id: 'xiaoxiang_fees',
    label: '小象超市费用',
    description: '小象超市保险费、循环物资使用费及附加险扣款口径',
    unitHint: '元/天或元/月',
    columns: ['保险费', '循环物资使用费', '附加险'],
  },
];

export const ALL_MONETARY_COLUMNS = new Set<string>([
  ...CONFIG_RULE_COLUMNS,
  '保险费',
  '循环物资使用费',
  '附加险',
]);

export const DEDUCTION_COLUMN_UNIT: Record<string, string> = {
  投诉: '元/次',
  差评: '元/次',
  违规虚假: '元/次',
  物流责: '元/次',
  不准时单: '元/单',
  超时: '元/单',
  T10: '元/单',
  工具费: '元',
  代领费率: '费率/比例',
  安全基金: '元/天',
  安全基金_maxDays: '天',
  使用费: '元/天',
  使用费_maxDays: '天',
  非蜂卡: '元/天',
  月费: '元/月',
  保险费: '元/天',
  循环物资使用费: '元/天',
  附加险: '元/月',
};

export function normalizeStationName(value: unknown): string {
  return String(value ?? '').trim().replace(/_?新专送/g, '');
}

export function normalizeCityName(value: unknown): string {
  return String(value ?? '').trim().replace(/市$/, '');
}

export function isMonetaryColumn(column: string): boolean {
  return ALL_MONETARY_COLUMNS.has(column);
}

export function hasNonZeroDeduction(row: Record<string, any>, columns: string[]): boolean {
  const sourceCharge = String(row['招聘来源'] || '').replace(/^0(?:\.0)?$/, '').trim();
  if (sourceCharge) return true;
  return columns.some(col => {
    if (col === '招聘来源' || col.endsWith('_maxDays')) return false;
    const val = row[col];
    return val != null && val !== '' && Number(val) !== 0;
  });
}

export function buildDeductionCategories(columns?: string[]): DeductionCategorySpec[] {
  const sourceColumns = columns && columns.length ? columns : [...CONFIG_RULE_COLUMNS];
  const colSet = new Set(sourceColumns);
  const assigned = new Set<string>();
  const groups: DeductionCategorySpec[] = [];

  for (const spec of DEDUCTION_CATEGORY_TEMPLATES) {
    const present = spec.columns.filter(col => colSet.has(col));
    if (present.length > 0) {
      groups.push({ ...spec, columns: present });
      present.forEach(col => assigned.add(col));
    }
  }

  const extras = sourceColumns.filter(col => !assigned.has(col));
  if (extras.length > 0) {
    groups.push({
      id: 'extended',
      label: '扩展与阈值字段',
      description: '历史兼容字段、按天阈值上限与特殊补贴口径',
      unitHint: '天数或兼容项',
      columns: extras,
    });
  }

  return groups;
}

export function visibleColumnsForCategory(columns: string[], categoryId: DeductionCategoryId): string[] {
  if (!columns.length || categoryId === 'all') return columns;
  const groups = buildDeductionCategories(columns);
  const matched = groups.find(group => group.id === categoryId);
  return matched ? matched.columns : columns;
}

export function categoryLabelForColumn(column: string): string {
  for (const spec of DEDUCTION_CATEGORY_TEMPLATES) {
    if (spec.columns.includes(column)) return spec.label;
  }
  return '扩展字段';
}

export interface CityProgressSummary {
  cityId: string;
  cityName: string;
  totalStations: number;
  configuredStations: number;
  pendingStations: number;
  overrideStations: number;
  editedStations: number;
  cityDefaultConfigured: boolean;
  cityDefaultEdited: boolean;
}

export function summarizeCitiesProgress(
  cities: DeductionEntry[],
  entries: DeductionEntry[],
  directoryCities: Array<{ id: string; name: string; station_count?: number | null }> = [],
): CityProgressSummary[] {
  const byCity = new Map<string, CityProgressSummary>();

  const ensureCity = (cityId: string, cityName: string) => {
    let item = byCity.get(cityId);
    if (!item) {
      item = {
        cityId,
        cityName,
        totalStations: 0,
        configuredStations: 0,
        pendingStations: 0,
        overrideStations: 0,
        editedStations: 0,
        cityDefaultConfigured: false,
        cityDefaultEdited: false,
      };
      byCity.set(cityId, item);
    }
    return item;
  };

  for (const dirCity of directoryCities) {
    ensureCity(dirCity.id, dirCity.name);
  }

  for (const cityEntry of cities) {
    const item = ensureCity(cityEntry.station.city_id, cityEntry.station.city);
    item.cityDefaultConfigured = Boolean(cityEntry.configured);
    item.cityDefaultEdited = Boolean(cityEntry.edited);
  }

  for (const entry of entries) {
    const item = ensureCity(entry.station.city_id, entry.station.city);
    item.totalStations += 1;
    if (entry.configured) {
      item.configuredStations += 1;
    } else {
      item.pendingStations += 1;
    }
    if (entry.station_override) {
      item.overrideStations += 1;
    }
    if (entry.edited) {
      item.editedStations += 1;
    }
  }

  return Array.from(byCity.values());
}

export interface CityCardGroup {
  summary: CityProgressSummary;
  cityEntry: DeductionEntry | null;
  stations: DeductionEntry[];
}

export function groupDeductionsByCity(
  cities: DeductionEntry[],
  entries: DeductionEntry[],
  directoryCities: Array<{ id: string; name: string; station_count?: number | null }> = [],
  filters: {
    cityFilter?: string;
    citySearch?: string;
    stationSearch?: string;
    onlyPendingCities?: boolean;
    onlyUnconfigured?: boolean;
  } = {},
): CityCardGroup[] {
  const summaries = summarizeCitiesProgress(cities, entries, directoryCities);
  const cityById = new Map<string, DeductionEntry>();
  for (const c of cities) {
    cityById.set(c.station.city_id, c);
  }
  const entriesByCity = new Map<string, DeductionEntry[]>();
  for (const e of entries) {
    const list = entriesByCity.get(e.station.city_id) || [];
    list.push(e);
    entriesByCity.set(e.station.city_id, list);
  }

  const cityQuery = (filters.citySearch || '').trim().toLowerCase();
  const stationQuery = (filters.stationSearch || '').trim().toLowerCase();
  const hasStationFilter = Boolean(stationQuery || filters.onlyUnconfigured);

  const groups: CityCardGroup[] = [];
  for (const summary of summaries) {
    if (filters.cityFilter && summary.cityId !== filters.cityFilter) continue;
    if (
      filters.onlyPendingCities &&
      summary.pendingStations === 0 &&
      summary.totalStations > 0 &&
      summary.cityDefaultConfigured
    ) {
      continue;
    }

    const rawStations = entriesByCity.get(summary.cityId) || [];
    const filteredStations = rawStations.filter(item => {
      if (filters.onlyUnconfigured && item.configured) return false;
      if (stationQuery) {
        const hay = `${item.station.name} ${item.station.id} ${item.station.city}`.toLowerCase();
        if (!hay.includes(stationQuery)) return false;
      }
      return true;
    });

    if (cityQuery) {
      const cityHit =
        summary.cityName.toLowerCase().includes(cityQuery) ||
        summary.cityId.toLowerCase().includes(cityQuery);
      if (!cityHit && filteredStations.length === 0) continue;
    }

    if (hasStationFilter && filteredStations.length === 0) continue;

    groups.push({
      summary,
      cityEntry: cityById.get(summary.cityId) || null,
      stations: filteredStations,
    });
  }

  return groups;
}

export function summarizeStationRow(
  entry: DeductionEntry,
  columns: string[],
): string {
  const activeCols = columns.filter(c => !c.endsWith('_maxDays'));
  if (!activeCols.length) return '暂无字段';
  const filled: string[] = [];
  let zeroCount = 0;
  let blankCount = 0;

  for (const col of activeCols) {
    const val = entry.row[col];
    if (val === null || val === undefined || val === '') {
      blankCount += 1;
    } else if (typeof val === 'number' && val === 0) {
      zeroCount += 1;
    } else {
      filled.push(`${col} ${val}`);
    }
  }

  if (blankCount === activeCols.length) {
    return `待填写 ${blankCount} 项`;
  }
  const head = filled.slice(0, 3).join(' · ');
  const extra = filled.length > 3 ? ` +${filled.length - 3}项` : '';
  if (filled.length > 0 && blankCount === 0) {
    return `${head}${extra}`;
  }
  if (filled.length > 0) {
    return `${head}${extra} · 待填 ${blankCount}`;
  }
  if (zeroCount === activeCols.length) {
    return entry.zero_confirmed ? '已确认零扣款' : '全 0（待确认）';
  }
  return `已填 ${zeroCount} 项为 0 · 待填 ${blankCount}`;
}

export interface PaginatedSlice<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  startIndex: number;
  endIndex: number;
}

export function paginateEntries<T>(items: T[], page: number, pageSize = 30): PaginatedSlice<T> {
  const safeSize = Math.max(1, Math.floor(pageSize));
  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / safeSize));
  const safePage = Math.min(Math.max(1, Math.floor(page)), totalPages);
  const startIndex = (safePage - 1) * safeSize;
  const slice = items.slice(startIndex, startIndex + safeSize);
  const endIndex = startIndex + slice.length;
  return {
    items: slice,
    total,
    page: safePage,
    pageSize: safeSize,
    totalPages,
    startIndex,
    endIndex,
  };
}

export interface ConfigImportResult {
  updatedCities: DeductionEntry[];
  updatedEntries: DeductionEntry[];
  matchedCityCount: number;
  matchedStationCount: number;
  unmatchedRows: Array<{ index: number; city: string; teamName: string; reason: string }>;
}

function parseImportValue(rawValue: unknown, column: string): string | number | boolean | null {
  if (rawValue === undefined || rawValue === null || rawValue === '') return null;
  if (typeof rawValue === 'boolean') return rawValue;
  if (column.endsWith('_maxDays')) {
    const num = typeof rawValue === 'number' ? rawValue : Number(String(rawValue).trim());
    return Number.isFinite(num) && num > 0 ? num : null;
  }
  if (column === '招聘来源') return String(rawValue).trim();
  const num = typeof rawValue === 'number' ? rawValue : Number(String(rawValue).trim());
  if (Number.isFinite(num)) return num;
  return String(rawValue).trim();
}

export function applyConfigRuleRows(
  rawRows: unknown[],
  cities: DeductionEntry[],
  entries: DeductionEntry[],
  columns: string[],
): ConfigImportResult {
  const nextCities = cities.map(item => ({ ...item, row: { ...item.row } }));
  const nextEntries = entries.map(item => ({ ...item, row: { ...item.row } }));
  let matchedCityCount = 0;
  let matchedStationCount = 0;
  const unmatchedRows: Array<{ index: number; city: string; teamName: string; reason: string }> = [];

  rawRows.forEach((raw, idx) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      unmatchedRows.push({ index: idx + 1, city: '', teamName: '', reason: '行数据格式无效' });
      return;
    }
    const record = normalizeConfigRecord(raw as Record<string, unknown>);
    const cityName = String(record['城市'] ?? '').trim();
    const teamName = String(record['团队名称'] ?? record['站点名称'] ?? '').trim();
    const teamId = String(record['团队ID'] ?? record['站点ID'] ?? '').trim();

    if (!cityName || !teamName) {
      unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '缺少城市或团队名称' });
      return;
    }

    const patchRow = (targetRow: Record<string, any>) => {
      for (const col of columns) {
        if (col in record) {
          const parsed = parseImportValue(record[col], col);
          if (col.endsWith('_maxDays')) {
            targetRow[col] = parsed;
          } else if (parsed !== null) {
            targetRow[col] = parsed;
          }
        }
      }
    };

    const isCityScope =
      teamId === '*' ||
      ['城市统一扣款', '城市默认', '城市默认扣款', '*'].includes(normalizeStationName(teamName));

    if (isCityScope) {
      const matchedCity = nextCities.find(
        c => normalizeCityName(c.station.city) === normalizeCityName(cityName),
      );
      if (!matchedCity) {
        unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '未在后台目录找到该城市' });
        return;
      }
      patchRow(matchedCity.row);
      matchedCity.edited = true;
      matchedCity.zero_confirmed = !hasNonZeroDeduction(matchedCity.row, columns);
      matchedCityCount += 1;
      return;
    }

    const cityNorm = normalizeCityName(cityName);
    const teamNorm = normalizeStationName(teamName);
    const matchedEntry = nextEntries.find(e => {
      if (teamId && e.station.id === teamId) return true;
      return (
        normalizeCityName(e.station.city) === cityNorm &&
        normalizeStationName(e.station.name) === teamNorm
      );
    });

    if (!matchedEntry) {
      unmatchedRows.push({
        index: idx + 1,
        city: cityName,
        teamName,
        reason: '未在当前平台站点目录找到对应团队',
      });
      return;
    }

    patchRow(matchedEntry.row);
    matchedEntry.edited = true;
    matchedEntry.zero_confirmed = !hasNonZeroDeduction(matchedEntry.row, columns);
    matchedStationCount += 1;
  });

  return {
    updatedCities: nextCities,
    updatedEntries: nextEntries,
    matchedCityCount,
    matchedStationCount,
    unmatchedRows,
  };
}

function exportConfigCell(column: string, value: unknown): string | number | boolean | null {
  if (column.endsWith('_maxDays')) {
    const num = Number(value);
    return value == null || value === '' || !Number.isFinite(num) || num <= 0 ? '' : num;
  }
  return (value as string | number | boolean | null) ?? 0;
}

export function buildConfigExportRows(
  cities: DeductionEntry[],
  entries: DeductionEntry[],
  columns: string[],
): Array<Record<string, string | number | boolean | null>> {
  const rows: Array<Record<string, string | number | boolean | null>> = [];
  const ruleCols = columns.length ? columns : [...CONFIG_RULE_COLUMNS];

  for (const city of cities) {
    if (!city.configured && !city.edited) continue;
    const row: Record<string, string | number | boolean | null> = {
      城市: city.station.city,
      团队名称: '城市统一扣款',
      团队ID: '*',
    };
    for (const col of ruleCols) {
      row[columnDisplayLabel(col)] = exportConfigCell(col, city.row[col]);
    }
    rows.push(row);
  }

  for (const entry of entries) {
    const row: Record<string, string | number | boolean | null> = {
      城市: entry.station.city,
      团队名称: entry.station.name,
      团队ID: entry.station.id,
    };
    for (const col of ruleCols) {
      row[columnDisplayLabel(col)] = exportConfigCell(col, entry.row[col]);
    }
    rows.push(row);
  }

  return rows;
}

export interface ProblemRuleItem {
  problem_type: string;
  reason_keyword: string;
  amount: number;
}

export const PROBLEM_RULE_COLUMNS = [
  '城市',
  '团队名称',
  '团队ID',
  '问题单类型',
  '判责原因关键词',
  '单次扣款金额',
] as const;

export function sortProblemRules(rules: ProblemRuleItem[]): ProblemRuleItem[] {
  return [...rules].sort((a, b) => {
    const typeCmp = a.problem_type.localeCompare(b.problem_type, 'zh-CN');
    if (typeCmp !== 0) return typeCmp;
    return a.reason_keyword.localeCompare(b.reason_keyword, 'zh-CN');
  });
}

export function buildProblemRuleExportRows(
  cities: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
  entries: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
): Array<Record<string, string | number>> {
  const rows: Array<Record<string, string | number>> = [];
  for (const city of cities) {
    for (const rule of sortProblemRules(city.problem_rules || [])) {
      rows.push({
        城市: city.station.city,
        团队名称: '城市统一扣款',
        团队ID: '*',
        问题单类型: rule.problem_type,
        判责原因关键词: rule.reason_keyword || '',
        单次扣款金额: rule.amount,
      });
    }
  }
  for (const entry of entries) {
    for (const rule of sortProblemRules(entry.problem_rules || [])) {
      rows.push({
        城市: entry.station.city,
        团队名称: entry.station.name,
        团队ID: entry.station.id,
        问题单类型: rule.problem_type,
        判责原因关键词: rule.reason_keyword || '',
        单次扣款金额: rule.amount,
      });
    }
  }
  return rows;
}

export interface UnifiedConfigWorkbookData {
  itemSheetName: string;
  itemHeaders: string[];
  itemRows: Array<Record<string, string | number | boolean | null>>;
  problemSheetName: string;
  problemHeaders: string[];
  problemRows: Array<Record<string, string | number>>;
}

export function buildUnifiedConfigWorkbookData(
  cities: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
  entries: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
  columns: string[],
): UnifiedConfigWorkbookData {
  const ruleCols = columns.length ? columns : [...CONFIG_RULE_COLUMNS];
  return {
    itemSheetName: '城市与站点扣款项',
    itemHeaders: ['城市', '团队名称', '团队ID', ...ruleCols.map(columnDisplayLabel)],
    itemRows: buildConfigExportRows(cities, entries, ruleCols),
    problemSheetName: '问题单关键词扣款',
    problemHeaders: [...PROBLEM_RULE_COLUMNS],
    problemRows: buildProblemRuleExportRows(cities, entries),
  };
}

export interface ClassifiedWorkbookRows {
  itemRows: Array<Record<string, unknown>>;
  problemRows: Array<Record<string, unknown>>;
}

export function classifyImportedWorkbookSheets(
  sheets: Array<{ name: string; rows: unknown[] }>,
  columns: string[] = [...CONFIG_RULE_COLUMNS],
): ClassifiedWorkbookRows {
  const itemRows: Array<Record<string, unknown>> = [];
  const problemRows: Array<Record<string, unknown>> = [];
  const itemColSet = new Set(columns);

  for (const sheet of sheets) {
    const validRows = (sheet.rows || []).filter(
      (r): r is Record<string, unknown> => Boolean(r && typeof r === 'object' && !Array.isArray(r)),
    );
    if (!validRows.length) continue;

    const sampleKeys = new Set<string>();
    validRows.slice(0, 5).forEach(row => {
      Object.keys(row).forEach(k => sampleKeys.add(normalizeConfigColumnKey(k)));
    });

    const looksLikeProblem =
      sampleKeys.has('问题单类型') ||
      sampleKeys.has('问题类型') ||
      sampleKeys.has('单次扣款金额') ||
      sampleKeys.has('判责原因关键词') ||
      /问题单|关键词/.test(sheet.name);

    const looksLikeItems =
      Array.from(sampleKeys).some(k => itemColSet.has(k)) ||
      (!looksLikeProblem && (sampleKeys.has('团队名称') || sampleKeys.has('站点名称') || sampleKeys.has('城市')));

    if (looksLikeProblem) {
      problemRows.push(...validRows);
    } else if (looksLikeItems) {
      itemRows.push(...validRows.map(normalizeConfigRecord));
    }
  }

  return { itemRows, problemRows };
}

export interface ProblemRuleFlatRow {
  key: string;
  scope: 'city' | 'station';
  city: string;
  team_name: string;
  team_id: string;
  problem_type: string;
  reason_keyword: string;
  amount: number;
}

export interface ProblemRuleImportResult {
  updatedCities: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>;
  updatedEntries: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>;
  matchedCityRules: number;
  matchedStationRules: number;
  normalizedRows: ProblemRuleFlatRow[];
  diff: {
    addedCount: number;
    updatedCount: number;
    removedCount: number;
    unchangedCount: number;
  };
  unmatchedRows: Array<{ index: number; city: string; teamName: string; reason: string }>;
}

export function applyProblemRuleRows(
  rawRows: unknown[],
  cities: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
  entries: Array<DeductionEntry & { problem_rules?: ProblemRuleItem[] }>,
): ProblemRuleImportResult {
  const unmatchedRows: Array<{ index: number; city: string; teamName: string; reason: string }> = [];
  const grouped = new Map<string, ProblemRuleItem[]>();
  const seen = new Set<string>();
  const normalizedRows: ProblemRuleFlatRow[] = [];
  let matchedCityRules = 0;
  let matchedStationRules = 0;

  rawRows.forEach((raw, idx) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      unmatchedRows.push({ index: idx + 1, city: '', teamName: '', reason: '行数据格式无效' });
      return;
    }
    const record = raw as Record<string, unknown>;
    const cityName = String(record['城市'] ?? '').trim();
    const teamName = String(record['团队名称'] ?? record['站点名称'] ?? '').trim();
    const teamId = String(record['团队ID'] ?? record['站点ID'] ?? '').trim();
    const problemType = String(record['问题单类型'] ?? record['问题类型'] ?? '').trim();
    const reasonKeyword = String(record['判责原因关键词'] ?? record['原因关键词'] ?? record['关键词'] ?? '').trim();
    const rawAmount = record['单次扣款金额'] ?? record['扣款金额'] ?? record['金额'];

    if (!cityName || (!teamName && !teamId)) {
      unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '缺少城市或团队标识' });
      return;
    }
    if (!problemType) {
      unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '缺少问题单类型' });
      return;
    }
    const amount = rawAmount === null || rawAmount === undefined || rawAmount === '' ? NaN : Number(rawAmount);
    if (!Number.isFinite(amount) || amount < 0) {
      unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '单次扣款金额必须为非负数字' });
      return;
    }

    const isCityScope =
      teamId === '*' ||
      ['城市统一扣款', '城市默认', '城市默认扣款', '*'].includes(normalizeStationName(teamName));

    let targetKey = '';
    let resolvedCity = cityName;
    let resolvedTeamName = teamName;
    let resolvedTeamId = teamId;
    let scope: 'city' | 'station' = isCityScope ? 'city' : 'station';

    if (isCityScope) {
      const matchedCity = cities.find(
        c => normalizeCityName(c.station.city) === normalizeCityName(cityName),
      );
      if (!matchedCity) {
        unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '未在目录找到对应城市' });
        return;
      }
      targetKey = matchedCity.key;
      resolvedCity = matchedCity.station.city;
      resolvedTeamName = '城市统一扣款';
      resolvedTeamId = '*';
    } else {
      const cityNorm = normalizeCityName(cityName);
      const teamNorm = normalizeStationName(teamName);
      const matchedEntry = entries.find(e => {
        if (teamId && e.station.id === teamId) return true;
        return (
          normalizeCityName(e.station.city) === cityNorm &&
          normalizeStationName(e.station.name) === teamNorm
        );
      });
      if (!matchedEntry) {
        unmatchedRows.push({ index: idx + 1, city: cityName, teamName, reason: '未在目录找到对应站点' });
        return;
      }
      targetKey = matchedEntry.key;
      resolvedCity = matchedEntry.station.city;
      resolvedTeamName = matchedEntry.station.name;
      resolvedTeamId = matchedEntry.station.id;
    }

    const dupKey = `${targetKey}::${problemType}::${reasonKeyword}`;
    if (seen.has(dupKey)) {
      unmatchedRows.push({ index: idx + 1, city: cityName, teamName: resolvedTeamName, reason: '同一站点的问题类型与关键词重复' });
      return;
    }
    seen.add(dupKey);

    if (scope === 'city') matchedCityRules += 1;
    else matchedStationRules += 1;

    const list = grouped.get(targetKey) || [];
    list.push({ problem_type: problemType, reason_keyword: reasonKeyword, amount });
    grouped.set(targetKey, list);
    normalizedRows.push({
      key: targetKey,
      scope,
      city: resolvedCity,
      team_name: resolvedTeamName,
      team_id: resolvedTeamId,
      problem_type: problemType,
      reason_keyword: reasonKeyword,
      amount,
    });
  });

  const oldMap = new Map<string, number>();
  for (const c of cities) {
    for (const r of c.problem_rules || []) {
      oldMap.set(`${c.key}::${r.problem_type}::${r.reason_keyword || ''}`, r.amount);
    }
  }
  for (const e of entries) {
    for (const r of e.problem_rules || []) {
      oldMap.set(`${e.key}::${r.problem_type}::${r.reason_keyword || ''}`, r.amount);
    }
  }

  const newMap = new Map<string, number>();
  for (const row of normalizedRows) {
    newMap.set(`${row.key}::${row.problem_type}::${row.reason_keyword}`, row.amount);
  }

  let addedCount = 0;
  let updatedCount = 0;
  let unchangedCount = 0;
  let removedCount = 0;

  for (const [k, amt] of newMap.entries()) {
    if (!oldMap.has(k)) addedCount += 1;
    else if (oldMap.get(k) !== amt) updatedCount += 1;
    else unchangedCount += 1;
  }
  for (const k of oldMap.keys()) {
    if (!newMap.has(k)) removedCount += 1;
  }

  const updatedCities = cities.map(c => ({
    ...c,
    problem_rules: sortProblemRules(grouped.get(c.key) || []),
  }));
  const updatedEntries = entries.map(e => ({
    ...e,
    problem_rules: sortProblemRules(grouped.get(e.key) || []),
  }));

  return {
    updatedCities,
    updatedEntries,
    matchedCityRules,
    matchedStationRules,
    normalizedRows,
    diff: {
      addedCount,
      updatedCount,
      removedCount,
      unchangedCount,
    },
    unmatchedRows,
  };
}

export const COMMON_PROBLEM_TYPES = [
  '餐损责任',
  '虚假送达',
  '态度投诉',
  '配送超时',
  '货损赔付',
  '提前点送达',
  '未穿工服装备',
] as const;

export function upsertProblemRule(
  rules: ProblemRuleItem[],
  nextRule: ProblemRuleItem,
  editIndex?: number,
): { rules: ProblemRuleItem[]; error?: string } {
  const problem_type = String(nextRule.problem_type || '').trim();
  const reason_keyword = String(nextRule.reason_keyword || '').trim();
  const amount = Number(nextRule.amount);
  if (!problem_type) {
    return { rules, error: '请填写问题单类型（如：餐损责任、虚假送达）' };
  }
  if (!Number.isFinite(amount) || amount < 0) {
    return { rules, error: '单次扣款金额须为不小于 0 的数字' };
  }
  const duplicateIndex = rules.findIndex(
    (item, idx) =>
      idx !== editIndex &&
      item.problem_type.trim() === problem_type &&
      (item.reason_keyword || '').trim() === reason_keyword,
  );
  if (duplicateIndex !== -1) {
    return { rules, error: '已存在相同「问题单类型 + 关键词」的扣款规则，请直接修改原条目金额' };
  }
  const normalized: ProblemRuleItem = { problem_type, reason_keyword, amount };
  const next =
    editIndex !== undefined && editIndex >= 0 && editIndex < rules.length
      ? rules.map((item, idx) => (idx === editIndex ? normalized : item))
      : [...rules, normalized];
  return { rules: sortProblemRules(next) };
}

export function removeProblemRule(
  rules: ProblemRuleItem[],
  index: number,
): ProblemRuleItem[] {
  return rules.filter((_, idx) => idx !== index);
}

export function toggleGridCityExpansion(
  expanded: Set<string>,
  cityId: string,
): Set<string> {
  const next = new Set(expanded);
  if (next.has(cityId)) next.delete(cityId);
  else next.add(cityId);
  return next;
}

export function resolveCityChipAction(
  currentCityFilter: string,
  clickedCityId: string,
): { nextCityFilter: string; nextExpandedCities: Set<string> } {
  if (!clickedCityId || currentCityFilter === clickedCityId) {
    return { nextCityFilter: '', nextExpandedCities: new Set() };
  }
  return {
    nextCityFilter: clickedCityId,
    nextExpandedCities: new Set([clickedCityId]),
  };
}
