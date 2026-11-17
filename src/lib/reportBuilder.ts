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
  const monthChunks = sortedMonths.length > 0 ? buildReportMonthChunks(sortedMonths, today || '') : [];
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
      monthChunks,
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
  const range = primaryScoped
    ? monthChunks.length > 0
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
}

export interface GenerateBatchOptions {
  includeSeparation?: boolean;
  excludeSeparation?: boolean;
  selectedMonths?: string[];
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

    if (isAll) {
      payloads.push({
        task_kind: 'generate',
        generation_target: report.id,
        datasets: [report.id],
        cities: ['全部城市'],
        start: today,
        end: today,
        ...(isLanorangeTarget ? { lanorange_full_delivery: true } : {}),
      });
      continue;
    }

    if (chunks.length > 0) {
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
    });
  }
  return payloads;
}

export const DEFAULT_REPORT_DEFINITIONS: ReportDefinition[] = [
  {
    id: 'payment_binding',
    label: '骑手支付绑定',
    scope: 'city_month',
    systems: ['风神', '蓝橙', '商翼', '本来人力'],
    sources: [],
    station_rule: 'separation',
  },
  {
    id: 'abnormal_followup',
    label: '异常骑手跟进',
    scope: 'city_month',
    systems: ['风神', '蓝橙', '商翼'],
    sources: [],
    station_rule: 'separation',
  },
  {
    id: 'abnormal_riders',
    label: '异常骑手整理',
    scope: 'all',
    systems: ['蓝橙'],
    sources: [],
    station_rule: 'none',
  },
];

export function resolveReportDefinitions(
  selectedIds: string[],
  availableGenerators: ReportDefinition[] = [],
): ReportDefinition[] {
  const byId = new Map<string, ReportDefinition>();
  for (const def of DEFAULT_REPORT_DEFINITIONS) byId.set(def.id, def);
  for (const def of availableGenerators) byId.set(def.id, def);
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

