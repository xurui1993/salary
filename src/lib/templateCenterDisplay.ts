export interface TemplateRecord {
  filename: string;
  business_line?: string;
  scope?: string;
  size: number;
  mtime?: number;
  content_version?: string;
  header_count?: number;
  sheet_count?: number;
  available?: boolean;
  builtin?: boolean;
  custom?: boolean;
  updated?: boolean;
  error?: string;
}

export interface TemplateTableRowModel {
  filename: string;
  cityName: string;
  regionTag: string;
  businessTag: '淘宝闪购' | '美团小象';
  templateTypeText: string;
  fileSizeText: string;
  specAndSizeText: string;
  statusLabel: string;
  statusTone: 'ready' | 'error';
  sourceBadge: '' | '自定义' | '已修改';
  available: boolean;
  builtin: boolean;
  errorText: string;
}

export const TEMPLATE_REGION_GROUPS: { id: string; label: string; cities: string[] }[] = [
  { id: 'all', label: '全部地区', cities: [] },
  { id: 'south', label: '华南', cities: ['广州', '深圳', '东莞', '韶关', '三亚'] },
  { id: 'east', label: '华东', cities: ['上海', '宁波', '泉州', '杭州', '苏州', '南京'] },
  { id: 'north', label: '华北与东北', cities: ['北京', '天津', '保定', '大连'] },
];

const BUILTIN_CITIES = ['三亚', '上海', '东莞', '保定', '北京', '大连', '天津', '宁波', '广州', '泉州', '深圳', '韶关'] as const;

const BUILTIN_CITY_SIZES: Record<string, number> = {
  三亚: 24371,
  泉州: 69632,
  韶关: 22733,
};

export const INITIAL_TEMPLATE_SEED: TemplateRecord[] = [
  ...BUILTIN_CITIES.map(city => ({
    filename: `${city}-template.xlsx`,
    business_line: '淘宝闪购',
    scope: city,
    size: BUILTIN_CITY_SIZES[city] ?? 22835,
    header_count: 10,
    sheet_count: 11,
    available: true,
    builtin: true,
  })),
  {
    filename: '小象-template.xlsx',
    business_line: '美团灯塔',
    scope: '灯塔业务',
    size: 23962,
    header_count: 22,
    sheet_count: 14,
    available: true,
    builtin: true,
  },
];

let cachedTemplates: TemplateRecord[] | null = null;
let cachedHasCustomizations = false;
let preloadPromise: Promise<{ templates: TemplateRecord[]; hasCustomizations: boolean }> | null = null;

export function getMemoryCachedTemplates(): {
  templates: TemplateRecord[];
  hasCustomizations: boolean;
  isLoadedFromServer: boolean;
} {
  if (cachedTemplates) {
    return {
      templates: cachedTemplates,
      hasCustomizations: cachedHasCustomizations,
      isLoadedFromServer: true,
    };
  }
  return {
    templates: INITIAL_TEMPLATE_SEED,
    hasCustomizations: false,
    isLoadedFromServer: false,
  };
}

export function setMemoryCachedTemplates(templates: TemplateRecord[], hasCustomizations = false): void {
  cachedTemplates = templates;
  cachedHasCustomizations = Boolean(hasCustomizations);
}

export function preloadSystemTemplates(force = false): Promise<{
  templates: TemplateRecord[];
  hasCustomizations: boolean;
}> {
  if (!force && cachedTemplates) {
    return Promise.resolve({
      templates: cachedTemplates,
      hasCustomizations: cachedHasCustomizations,
    });
  }
  if (!force && preloadPromise) {
    return preloadPromise;
  }
  preloadPromise = fetch('/api/templates/list', {
    signal: AbortSignal.timeout(10000),
  })
    .then(async res => {
      const data = await res.json();
      if (!res.ok || !data.success || !Array.isArray(data.templates)) {
        throw new Error(data.error || '模板列表读取失败');
      }
      const list = data.templates as TemplateRecord[];
      const hasCust = Boolean(data.has_customizations);
      setMemoryCachedTemplates(list, hasCust);
      return { templates: list, hasCustomizations: hasCust };
    })
    .finally(() => {
      preloadPromise = null;
    });
  return preloadPromise;
}

export function resolveTemplateBusinessTag(item: Pick<TemplateRecord, 'filename' | 'business_line'>): '淘宝闪购' | '美团小象' {
  const line = (item.business_line || '').trim();
  if (line === '美团灯塔' || line === '美团小象') {
    return '美团小象';
  }
  if (line === '淘宝闪购') {
    return '淘宝闪购';
  }
  const lower = (item.filename || '').toLowerCase();
  if (lower.includes('小象') || lower.includes('灯塔') || lower.includes('美团') || lower.includes('xiaoxiang')) {
    return '美团小象';
  }
  return '淘宝闪购';
}

export function resolveCityRegionLabel(cityName: string, businessTag: '淘宝闪购' | '美团小象'): string {
  if (businessTag === '美团小象') return '全国通用';
  for (const group of TEMPLATE_REGION_GROUPS) {
    if (group.id !== 'all' && group.cities.includes(cityName)) {
      return group.label;
    }
  }
  return '其他城市';
}

export function buildTemplateTableRow(item: TemplateRecord): TemplateTableRowModel {
  const businessTag = resolveTemplateBusinessTag(item);
  const rawBase = item.filename.replace(/-template\.xlsx$/i, '').replace(/\.xlsx$/i, '');
  const rawScope = (item.scope || rawBase).trim();
  const isDefaultXiaoxiang =
    businessTag === '美团小象' && (rawScope === '灯塔业务' || rawScope === '小象' || item.filename === '小象-template.xlsx');

  const cityName = isDefaultXiaoxiang ? '小象灯塔' : rawScope;
  const regionTag = resolveCityRegionLabel(rawScope, businessTag);
  const templateTypeText = businessTag === '美团小象' ? '众包/灯塔薪资申请表' : '闪购兼职薪资申请表';

  const defaultCols = businessTag === '美团小象' ? 22 : 10;
  const colCount = item.header_count && item.header_count > 0 ? item.header_count : defaultCols;
  const kbText = item.size > 0 ? `${(item.size / 1024).toFixed(1)} KB` : '—';
  const specAndSizeText = item.available === false ? kbText : `${colCount} 列标准表头 · ${kbText}`;

  const available = item.available !== false;
  let sourceBadge: '' | '自定义' | '已修改' = '';
  if (item.custom) {
    sourceBadge = '自定义';
  } else if (item.updated) {
    sourceBadge = '已修改';
  }

  return {
    filename: item.filename,
    cityName,
    regionTag,
    businessTag,
    templateTypeText,
    fileSizeText: kbText,
    specAndSizeText,
    statusLabel: available ? '已校验' : '不可用',
    statusTone: available ? 'ready' : 'error',
    sourceBadge,
    available,
    builtin: item.builtin !== false && !item.custom,
    errorText: item.error || '',
  };
}

export function filterAndSortTemplateRows(
  templates: TemplateRecord[],
  options: {
    search: string;
    category: 'all' | '淘宝闪购' | '美团小象';
    regionFilter?: string;
  },
): { record: TemplateRecord; row: TemplateTableRowModel }[] {
  const keyword = options.search.trim().toLowerCase();
  const activeRegion = options.regionFilter
    ? TEMPLATE_REGION_GROUPS.find(g => g.id === options.regionFilter)
    : undefined;

  const matched = templates
    .map(record => ({ record, row: buildTemplateTableRow(record) }))
    .filter(({ record, row }) => {
      if (options.category !== 'all' && row.businessTag !== options.category) {
        return false;
      }
      if (activeRegion && activeRegion.cities.length > 0) {
        const rawCity = (record.scope || record.filename.replace(/-template\.xlsx$/i, '')).trim();
        if (!activeRegion.cities.includes(rawCity)) {
          return false;
        }
      }
      if (keyword) {
        const hay = `${row.cityName} ${row.filename} ${row.businessTag} ${row.templateTypeText} ${row.regionTag}`.toLowerCase();
        if (!hay.includes(keyword)) {
          return false;
        }
      }
      return true;
    });

  return matched.sort((a, b) => {
    // Keep custom/updated templates or standard order clean: 淘宝闪购 first, 美团小象 second
    const rankA = a.row.businessTag === '美团小象' ? 1 : 0;
    const rankB = b.row.businessTag === '美团小象' ? 1 : 0;
    if (rankA !== rankB) return rankA - rankB;
    return a.row.cityName.localeCompare(b.row.cityName, 'zh-CN');
  });
}

export function validateTemplateFormInput(input: {
  scope: string;
  mode: 'generate' | 'upload';
  hasFile: boolean;
  isEdit?: boolean;
}): string {
  const clean = input.scope.trim().replace(/-template\.xlsx$/i, '').replace(/\.xlsx$/i, '').trim();
  if (!clean) {
    return '请输入城市或模板适用名称（如：杭州、成都）';
  }
  if (clean.length > 36 || /[/\\:*?"<>|]|\.\./.test(clean)) {
    return '名称不可包含特殊路径符号且需在 36 个字符以内';
  }
  if (!input.isEdit && input.mode === 'upload' && !input.hasFile) {
    return '请选择需要上传的本地 .xlsx 模板文件';
  }
  return '';
}
