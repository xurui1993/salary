import {
  areMonthsContiguous,
  buildMultiMonthRunRanges,
  toggleMultiMonthSelection,
  type MonthRunChunk,
} from './workbench';

export interface ReportDefinition {
  id: string;
  label: string;
  scope: 'all' | 'city_month' | 'city_range';
  description?: string;
  systems?: string[];
  sources: string[];
  station_rule?: 'separation' | 'none' | string;
}

export interface ReportMonthOption {
  month: string;
  label: string;
  shortTag: string;
  start: string;
  end: string;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function validDate(value: string): boolean {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(`${value}T00:00:00Z`)) &&
    new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
  );
}

export function monthBounds(month: string): { start: string; end: string } | null {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return null;
  const [year, m] = month.split('-').map(Number);
  const lastDay = new Date(Date.UTC(year, m, 0)).getUTCDate();
  return { start: `${month}-01`, end: `${month}-${pad2(lastDay)}` };
}

export function computeOrderWindowBounds(
  today: string,
  windowDays = 60,
): { earliest: string; latest: string } {
  const safeDays = Math.max(1, Math.floor(windowDays || 60));
  if (!validDate(today)) {
    return { earliest: today || '', latest: today || '' };
  }
  const earliestDate = new Date(`${today}T00:00:00Z`);
  earliestDate.setUTCDate(earliestDate.getUTCDate() - safeDays + 1);
  return {
    earliest: earliestDate.toISOString().slice(0, 10),
    latest: today,
  };
}

export function isWithinOrderWindow(
  start: string,
  end: string,
  today: string,
  windowDays = 60,
): boolean {
  if (!validDate(start) || !validDate(end) || start > end) return false;
  if (!validDate(today)) return true;
  const { earliest, latest } = computeOrderWindowBounds(today, windowDays);
  return start >= earliest && end <= latest;
}

export function reportRange(
  report: ReportDefinition | undefined | null,
  start: string,
  end: string,
  today?: string,
): { start: string; end: string; months: number } | null {
  if (!report || !['all', 'city_month', 'city_range'].includes(report.scope)) return null;
  if (report.scope === 'all') return { start: '', end: '', months: 0 };
  if (!validDate(start) || !validDate(end) || start > end) return null;
  if (report.scope === 'city_range') {
    return today && end > today ? null : { start, end, months: 0 };
  }
  const first = start.slice(0, 7);
  const last = end.slice(0, 7);
  if (today && last > today.slice(0, 7)) return null;
  const [year, month] = last.split('-').map(Number);
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const [firstYear, firstMonth] = first.split('-').map(Number);
  const months = (year - firstYear) * 12 + month - firstMonth + 1;
  if (months > 1200) return null;
  const lastDate = `${last}-${pad2(lastDay)}`;
  return {
    start: `${first}-01`,
    end: today && lastDate > today ? today : lastDate,
    months,
  };
}

export function resolveReportMonthBounds(
  month: string,
  today?: string,
): { start: string; end: string } | null {
  const bounds = monthBounds(month);
  if (!bounds) return null;
  if (today && validDate(today)) {
    const todayMonth = today.slice(0, 7);
    if (month > todayMonth) return null;
    if (month === todayMonth && bounds.end > today) {
      return { start: bounds.start, end: today };
    }
  }
  return bounds;
}

export function buildRecentReportMonths(today: string, count = 3): ReportMonthOption[] {
  const match = /^(\d{4})-(\d{2})/.exec((today || '').trim());
  const year = match ? Number(match[1]) : 2026;
  const month = match ? Number(match[2]) : 1;
  const safeCount = Math.max(1, count);

  return Array.from({ length: safeCount }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1 - index, 1));
    const y = date.getUTCFullYear();
    const m = date.getUTCMonth() + 1;
    const ym = `${y}-${pad2(m)}`;
    const bounds = resolveReportMonthBounds(ym, today) || monthBounds(ym)!;
    const shortTag = index === 0 ? '本月' : index === 1 ? '上月' : `前${index}月`;
    return {
      month: ym,
      label: `${y}年${pad2(m)}月`,
      shortTag,
      start: bounds.start,
      end: bounds.end,
    };
  });
}

export function selectReportMonthRange(
  currentStart: string,
  currentEnd: string,
  clickedMonth: string,
  mode: 'single' | 'range',
  allowedMonths: string[],
  today?: string,
): { start: string; end: string } | null {
  if (!allowedMonths.includes(clickedMonth)) return null;
  const clickedBounds = resolveReportMonthBounds(clickedMonth, today);
  if (!clickedBounds) return null;

  if (mode === 'single') {
    return clickedBounds;
  }

  const startYm = /^\d{4}-\d{2}/.test(currentStart) ? currentStart.slice(0, 7) : '';
  const endYm = /^\d{4}-\d{2}/.test(currentEnd) ? currentEnd.slice(0, 7) : '';
  const hasSingleValidSelection =
    startYm &&
    endYm &&
    startYm === endYm &&
    allowedMonths.includes(startYm);

  if (hasSingleValidSelection && clickedMonth !== startYm) {
    const first = startYm < clickedMonth ? startYm : clickedMonth;
    const last = startYm < clickedMonth ? clickedMonth : startYm;
    const firstBounds = resolveReportMonthBounds(first, today);
    const lastBounds = resolveReportMonthBounds(last, today);
    if (firstBounds && lastBounds) {
      return { start: firstBounds.start, end: lastBounds.end };
    }
  }

  return clickedBounds;
}

export function deriveSelectedMonthsFromRange(
  start: string,
  end: string,
  allowedMonths: string[],
): string[] {
  if (!validDate(start) || !validDate(end) || start > end) return [];
  const firstYm = start.slice(0, 7);
  const lastYm = end.slice(0, 7);
  return [...new Set(allowedMonths)]
    .filter(m => m >= firstYm && m <= lastYm)
    .sort();
}

export function toggleReportMonthSelection(
  currentMonths: string[],
  targetMonth: string,
  allowedMonths: string[],
): string[] {
  if (!allowedMonths.includes(targetMonth)) return currentMonths;
  if (!currentMonths.some(m => allowedMonths.includes(m))) {
    return [targetMonth];
  }
  return toggleMultiMonthSelection(currentMonths, targetMonth, allowedMonths);
}

export function buildReportMonthChunks(
  selectedMonths: string[],
  today: string,
): MonthRunChunk[] {
  return buildMultiMonthRunRanges(selectedMonths, today);
}

export function toggleReportSelection(
  selectedIds: string[],
  id: string,
  orderedReportIds?: string[],
): string[] {
  const exists = selectedIds.includes(id);
  const next = exists
    ? selectedIds.filter(item => item !== id)
    : [...selectedIds, id];
  if (!orderedReportIds?.length) return next;
  const orderMap = new Map(orderedReportIds.map((rid, idx) => [rid, idx]));
  return [...next].sort(
    (a, b) => (orderMap.get(a) ?? Number.MAX_SAFE_INTEGER) - (orderMap.get(b) ?? Number.MAX_SAFE_INTEGER),
  );
}

export interface SelectedReportsScopeSummary {
  needsCity: boolean;
  needsDate: boolean;
  needsSeparation: boolean;
  allGlobal: boolean;
  systems: string[];
  sources: string[];
  effectiveScope: 'none' | 'all' | 'city_month' | 'city_range';
  range: { start: string; end: string; months: number } | null;
  selectedMonths: string[];
  monthChunks: MonthRunChunk[];
  contiguousMonths: boolean;
}

export function summarizeSelectedReportsScope(
  selectedReports: ReportDefinition[],
  start: string,
  end: string,
  today?: string,
  selectedMonths?: string[],
): SelectedReportsScopeSummary {
  const sortedMonths = selectedMonths
    ? [...new Set(selectedMonths.filter(m => /^\d{4}-\d{2}$/.test(m)))].sort()
    : [];
  const rawMonthChunks = sortedMonths.length > 0 ? buildReportMonthChunks(sortedMonths, today || '') : [];
  const contiguousMonths = areMonthsContiguous(sortedMonths);

  if (!selectedReports.length) {
    return {
      needsCity: false,
      needsDate: false,
      needsSeparation: false,
      allGlobal: false,
      systems: [],
      sources: [],
      effectiveScope: 'none',
      range: null,
      selectedMonths: sortedMonths,
      monthChunks: rawMonthChunks,
      contiguousMonths,
    };
  }
  const scopedReports = selectedReports.filter(report => report.scope !== 'all');
  const needsCity = scopedReports.length > 0;
  const needsDate = scopedReports.length > 0;
  const needsSeparation = scopedReports.some(report => report.station_rule === 'separation');
  const allGlobal = !needsCity;
  const systems = Array.from(
    new Set(selectedReports.flatMap(report => report.systems || [])),
  );
  const sources = Array.from(
    new Set(selectedReports.flatMap(report => report.sources || [])),
  );
  const primaryScoped = scopedReports[0];
  const effectiveScope: SelectedReportsScopeSummary['effectiveScope'] = primaryScoped
    ? primaryScoped.scope
    : 'all';
  const monthChunks = primaryScoped?.scope === 'city_month' ? rawMonthChunks : [];
  const range = primaryScoped
    ? primaryScoped.scope === 'city_month' && monthChunks.length > 0
      ? {
          start: monthChunks[0].start,
          end: monthChunks[monthChunks.length - 1].end,
          months: sortedMonths.length,
        }
      : reportRange(primaryScoped, start, end, today)
    : reportRange(selectedReports[0], start, end, today);

  return {
    needsCity,
    needsDate,
    needsSeparation,
    allGlobal,
    systems,
    sources,
    effectiveScope,
    range,
    selectedMonths: sortedMonths,
    monthChunks,
    contiguousMonths,
  };
}

export type BindingPlatform = '本来人力' | '商翼';

export interface GenerateRunPayload {
  task_kind: 'generate';
  generation_target: string;
  datasets: string[];
  cities: string[];
  start: string;
  end: string;
  lanorange_full_delivery?: boolean;
  include_separation?: boolean;
  exclude_separation?: boolean;
  refresh_history?: boolean;
  binding_platforms?: Record<string, BindingPlatform>;
}

export interface GenerateBatchOptions {
  includeSeparation?: boolean;
  excludeSeparation?: boolean;
  refreshHistory?: boolean;
  selectedMonths?: string[];
  bindingPlatforms?: Record<string, BindingPlatform>;
}

export function buildGenerateBatchPayloads(
  selectedReports: ReportDefinition[],
  cities: string[],
  start: string,
  end: string,
  today: string,
  optionsOrIncludeSeparation: boolean | GenerateBatchOptions = false,
): GenerateRunPayload[] {
  const options: GenerateBatchOptions =
    typeof optionsOrIncludeSeparation === 'boolean'
      ? { includeSeparation: optionsOrIncludeSeparation }
      : optionsOrIncludeSeparation;

  const chunks = options.selectedMonths?.length
    ? buildReportMonthChunks(options.selectedMonths, today)
    : [];

  const payloads: GenerateRunPayload[] = [];
  for (const report of selectedReports) {
    const isAll = report.scope === 'all';
    const isLanorangeTarget = report.id.startsWith('lanorange_') || report.id === 'abnormal_riders';
    const separationField: Partial<GenerateRunPayload> =
      report.station_rule === 'separation' && !isAll
        ? options.excludeSeparation !== undefined
          ? { exclude_separation: options.excludeSeparation }
          : options.includeSeparation
            ? { include_separation: true }
            : {}
        : {};
    const platformOverrides =
      report.id === 'payment_binding' || report.id === 'abnormal_followup'
        ? Object.fromEntries(
            Object.entries(options.bindingPlatforms || {}).filter(([city]) => cities.includes(city)),
          )
        : {};
    const platformField: Partial<GenerateRunPayload> = Object.keys(platformOverrides).length
      ? { binding_platforms: platformOverrides }
      : {};
    const refreshField: Partial<GenerateRunPayload> =
      report.id === 'problem' && options.refreshHistory ? { refresh_history: true } : {};

    if (isAll) {
      payloads.push({
        task_kind: 'generate',
        generation_target: report.id,
        datasets: [report.id],
        cities: ['全部城市'],
        start: today,
        end: today,
        ...(isLanorangeTarget ? { lanorange_full_delivery: true } : {}),
        ...platformField,
      });
      continue;
    }

    if (report.scope === 'city_month' && chunks.length > 0) {
      for (const chunk of chunks) {
        payloads.push({
          task_kind: 'generate',
          generation_target: report.id,
          datasets: [report.id],
          cities: [...cities],
          start: chunk.start,
          end: chunk.end,
          ...(isLanorangeTarget ? { lanorange_full_delivery: true } : {}),
          ...separationField,
          ...platformField,
        });
      }
      continue;
    }

    const computed = reportRange(report, start, end, today);
    payloads.push({
      task_kind: 'generate',
      generation_target: report.id,
      datasets: [report.id],
      cities: [...cities],
      start: computed?.start || start,
      end: computed?.end || end,
      ...(isLanorangeTarget ? { lanorange_full_delivery: true } : {}),
      ...separationField,
      ...refreshField,
      ...platformField,
    });
  }
  return payloads;
}

export const DEFAULT_REPORT_DEFINITIONS: ReportDefinition[] = [
  {
    id: 'payment_binding',
    label: '支付绑定',
    scope: 'city_month',
    description: '自动关联风神收薪绑定与蓝橙、商翼及本来人力档案，输出周期内有单支付绑定表及多城汇总。',
    systems: ['风神', '蓝橙', '商翼', '本来人力'],
    sources: [],
    station_rule: 'separation',
  },
  {
    id: 'abnormal_followup',
    label: '异常跟进',
    scope: 'city_month',
    description: '以支付绑定为基准，关联物资租用、月度 UB 账单、价格与骑手档案，定位异常待跟进名单。',
    systems: ['风神', '蓝橙', '商翼', '本来人力'],
    sources: [],
    station_rule: 'separation',
  },
  {
    id: 'abnormal_riders',
    label: '异常名单',
    scope: 'all',
    description: '自动汇总蓝橙 5 类离职、请假与骑手档案，无需风神登录即可生成全城异常名单工作簿。',
    systems: ['蓝橙'],
    sources: [],
    station_rule: 'none',
  },
  {
    id: 'problem',
    label: '问题单',
    scope: 'city_range',
    description: '按城市与日期范围采集风神问题单并过滤取分离站点，生成问题单汇总与明细工作簿。',
    systems: ['风神'],
    sources: ['风神问题单（按城市日期范围采集并应用取分离站点过滤）'],
    station_rule: 'separation',
  },
];

export function mergeAvailableReports(
  availableGenerators: ReportDefinition[] = [],
): ReportDefinition[] {
  const byId = new Map<string, ReportDefinition>();
  for (const def of DEFAULT_REPORT_DEFINITIONS) {
    byId.set(def.id, { ...def });
  }
  for (const gen of availableGenerators) {
    const existing = byId.get(gen.id);
    if (existing) {
      byId.set(gen.id, {
        ...existing,
        ...gen,
        label: existing.label,
        description: existing.description || gen.description,
        systems: gen.systems?.length ? gen.systems : existing.systems,
        sources: gen.sources?.length ? gen.sources : existing.sources,
      });
    } else {
      byId.set(gen.id, gen);
    }
  }
  return Array.from(byId.values());
}

export function resolveReportDefinitions(
  selectedIds: string[],
  availableGenerators: ReportDefinition[] = [],
): ReportDefinition[] {
  const merged = mergeAvailableReports(availableGenerators);
  const byId = new Map(merged.map(def => [def.id, def]));
  return selectedIds
    .map(id => byId.get(id))
    .filter((def): def is ReportDefinition => Boolean(def));
}

export interface UnifiedDownloadSubmissionInput<T extends { task_kind?: 'download' | 'generate'; datasets: string[]; cities: string[]; start: string; end: string }> {
  selectedDatasets: string[];
  availableGenerators?: ReportDefinition[];
  rawSelection: T;
  rawMonthChunks?: MonthRunChunk[];
  isMultiBatchRawMonth?: boolean;
  cities: string[];
  start: string;
  end: string;
  today: string;
  excludeSeparation: boolean;
  selectedMonths?: string[];
  isGeneratorFn: (id: string) => boolean;
}

export function buildUnifiedSubmissionPayloads<
  T extends { task_kind?: 'download' | 'generate'; datasets: string[]; cities: string[]; start: string; end: string },
>(input: UnifiedDownloadSubmissionInput<T>): Array<T | GenerateRunPayload> {
  const {
    selectedDatasets,
    availableGenerators = [],
    rawSelection,
    rawMonthChunks = [],
    isMultiBatchRawMonth = false,
    cities,
    start,
    end,
    today,
    excludeSeparation,
    selectedMonths,
    isGeneratorFn,
  } = input;

  const rawDatasets = selectedDatasets.filter(id => !isGeneratorFn(id));
  const generatorIds = selectedDatasets.filter(id => isGeneratorFn(id));

  const payloads: Array<T | GenerateRunPayload> = [];

  if (rawDatasets.length > 0) {
    if (isMultiBatchRawMonth && rawMonthChunks.length > 1) {
      for (const chunk of rawMonthChunks) {
        payloads.push({
          ...rawSelection,
          task_kind: 'download',
          datasets: rawDatasets,
          start: chunk.start,
          end: chunk.end,
        });
      }
    } else {
      payloads.push({
        ...rawSelection,
        task_kind: 'download',
        datasets: rawDatasets,
      });
    }
  }

  if (generatorIds.length > 0) {
    const reportDefs = resolveReportDefinitions(generatorIds, availableGenerators);
    const reportPayloads = buildGenerateBatchPayloads(
      reportDefs,
      cities,
      start,
      end,
      today,
      { excludeSeparation, selectedMonths },
    );
    payloads.push(...reportPayloads);
  }

  return payloads;
}

export const BINDING_PLATFORM_OPTIONS = [
  { value: '本来人力' as const, label: '本来人力', title: '指定为本来人力平台' },
  { value: '商翼' as const, label: '天津商翼', title: '指定为天津商翼（商翼）' },
] as const;

export interface BindingPlatformPartition<T extends { name: string }> {
  benlai: T[];
  shangyi: T[];
}

/**
 * 二分归类城市绑定平台：左侧为「本来人力」，未在左侧展示的城市全部归入右侧「天津商翼」。
 */
export function partitionCitiesByBindingPlatform<T extends { name: string }>(
  cities: T[],
  bindingPlatforms?: Record<string, string>,
): BindingPlatformPartition<T> {
  const map = bindingPlatforms || {};
  const benlai: T[] = [];
  const shangyi: T[] = [];

  for (const city of cities) {
    if (map[city.name] === '本来人力') {
      benlai.push(city);
    } else {
      shangyi.push(city);
    }
  }

  return { benlai, shangyi };
}

export interface BindingPlatformGroups<T extends { name: string }> {
  benlai: T[];
  shangyi: T[];
  auto: T[];
}

export function groupCitiesByBindingPlatform<T extends { name: string }>(
  cities: T[],
  bindingPlatforms?: Record<string, string>,
): BindingPlatformGroups<T> {
  const map = bindingPlatforms || {};
  const benlai: T[] = [];
  const shangyi: T[] = [];
  const auto: T[] = [];

  for (const city of cities) {
    const val = map[city.name];
    if (val === '本来人力') {
      benlai.push(city);
    } else if (val === '商翼') {
      shangyi.push(city);
    } else {
      auto.push(city);
    }
  }

  return { benlai, shangyi, auto };
}

export function applyCityBindingPlatform(
  current: Record<string, string> | undefined,
  cityName: string,
  platform: string,
): Record<string, string> {
  const next = { ...(current || {}) };
  if (platform === '本来人力' || platform === '商翼') {
    next[cityName] = platform;
  } else {
    delete next[cityName];
  }
  return next;
}

export function applyBatchBindingPlatform(
  current: Record<string, string> | undefined,
  cityNames: string[],
  platform: string,
): Record<string, string> {
  const next = { ...(current || {}) };
  for (const cityName of cityNames) {
    if (platform === '本来人力' || platform === '商翼') {
      next[cityName] = platform;
    } else {
      delete next[cityName];
    }
  }
  return next;
}

export function summarizeBindingPlatforms(
  current: Record<string, string> | undefined,
  orderedCityNames: string[],
): {
  configuredCount: number;
  entries: Array<{ city: string; platform: string }>;
  previewText: string;
} {
  const map = current || {};
  const known = new Set(orderedCityNames);
  const entries: Array<{ city: string; platform: string }> = [];

  for (const city of orderedCityNames) {
    const value = map[city];
    if (value === '本来人力' || value === '商翼') {
      entries.push({ city, platform: value });
    }
  }
  for (const [city, value] of Object.entries(map)) {
    if (!known.has(city) && (value === '本来人力' || value === '商翼')) {
      entries.push({ city, platform: value });
    }
  }

  const head = entries.slice(0, 3).map(e => `${e.city}→${e.platform}`);
  const previewText =
    entries.length === 0
      ? ''
      : entries.length > 3
        ? `${head.join('、')} 等 ${entries.length} 城`
        : head.join('、');

  return {
    configuredCount: entries.length,
    entries,
    previewText,
  };
}
