export type DisplayAdaptationMode = 'auto' | 'desktop_27' | 'laptop_15' | 'custom';
export type DisplayScreenClass = 'desktop_27' | 'laptop_15';
export type DisplayContentWidth = 'standard' | 'wide' | 'full';
export type DisplayDensity = 'compact' | 'standard' | 'comfortable';
export type DisplaySidebarBehavior = 'standard' | 'compact' | 'auto_collapse';

export interface DisplayAdaptationParams {
  /** UI 缩放百分比：85 ~ 115，步进 2.5 */
  uiScale: number;
  /** 字号层级微调：-1 (紧凑 -1px) | 0 (标准) | 1 (舒展 +1px) */
  fontOffset: -1 | 0 | 1;
  /** 工作区主画布最大宽度策略 */
  contentWidth: DisplayContentWidth;
  /** 表格与卡片排版密度 */
  density: DisplayDensity;
  /** 左侧导航栏宽度与折叠策略 */
  sidebarBehavior: DisplaySidebarBehavior;
}

export interface DisplayAdaptationConfig extends DisplayAdaptationParams {
  mode: DisplayAdaptationMode;
  activePresetId?: string | null;
  updatedAt?: string;
}

export interface DisplayAdaptationPreset extends DisplayAdaptationParams {
  id: string;
  name: string;
  targetScreen: 'desktop_27' | 'laptop_15' | 'custom';
  builtIn?: boolean;
  updatedAt?: string;
}

export interface ScreenEnvironmentSnapshot {
  viewportWidth: number;
  viewportHeight: number;
  screenWidth: number;
  screenHeight: number;
  devicePixelRatio: number;
  detectedClass: DisplayScreenClass;
  detectedLabel: string;
  detectedReason: string;
  recommendedModeLabel: string;
}

export interface ComputedDisplayCssTokens {
  effectiveClass: DisplayScreenClass;
  effectiveParams: DisplayAdaptationParams;
  rootFontSizePx: number;
  scaleFactor: number;
  sidebarWidthPx: number;
  shouldCollapseSidebarOnLaptop: boolean;
  headerHeightPx: number;
  mainMaxWidthCss: string;
  shellGapPx: number;
  shellPadCss: string;
  shellPadYPx: number;
  shellPadY2Px: number;
  fs2xsPx: number;
  fsXsPx: number;
  fsSmPx: number;
  fsBasePx: number;
  fsMdPx: number;
  fsLgPx: number;
  fsXlPx: number;
  fs2xlPx: number;
}

export const DISPLAY_CONFIG_STORAGE_KEY = 'wbx_display_adaptation_v1';

/** 公司 27 寸显示器标准舒展参数 */
export const DESKTOP_27_PARAMS: DisplayAdaptationParams = {
  uiScale: 100,
  fontOffset: 0,
  contentWidth: 'wide',
  density: 'standard',
  sidebarBehavior: 'standard',
};

/** 家里 15.6 寸笔记本精炼紧凑参数（防截断、收窄留白、提效一屏信息量） */
export const LAPTOP_15_PARAMS: DisplayAdaptationParams = {
  uiScale: 92.5,
  fontOffset: 0,
  contentWidth: 'full',
  density: 'compact',
  sidebarBehavior: 'compact',
};

export const DEFAULT_DISPLAY_CONFIG: DisplayAdaptationConfig = {
  mode: 'auto',
  ...DESKTOP_27_PARAMS,
  activePresetId: 'builtin_auto',
};

export const BUILT_IN_DISPLAY_PRESETS: DisplayAdaptationPreset[] = [
  {
    id: 'builtin_desktop_27',
    name: '公司 27 寸宽屏标准预设',
    targetScreen: 'desktop_27',
    builtIn: true,
    ...DESKTOP_27_PARAMS,
  },
  {
    id: 'builtin_laptop_15',
    name: '家里 15.6 寸笔记本紧凑预设',
    targetScreen: 'laptop_15',
    builtIn: true,
    ...LAPTOP_15_PARAMS,
  },
  {
    id: 'builtin_laptop_15_max',
    name: '15.6 寸笔记本极简大视野（侧栏自动收起）',
    targetScreen: 'laptop_15',
    builtIn: true,
    uiScale: 90,
    fontOffset: -1,
    contentWidth: 'full',
    density: 'compact',
    sidebarBehavior: 'auto_collapse',
  },
  {
    id: 'builtin_desktop_27_comfort',
    name: '27 寸大屏护眼大字预设',
    targetScreen: 'desktop_27',
    builtIn: true,
    uiScale: 105,
    fontOffset: 1,
    contentWidth: 'wide',
    density: 'comfortable',
    sidebarBehavior: 'standard',
  },
];

export function clampUiScale(raw: unknown, fallback = 100): number {
  const num = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(num)) return fallback;
  const clamped = Math.min(115, Math.max(85, num));
  return Math.round(clamped * 2) / 2;
}

export function normalizeFontOffset(raw: unknown): -1 | 0 | 1 {
  const num = typeof raw === 'number' ? raw : Number(raw);
  if (num <= -1) return -1;
  if (num >= 1) return 1;
  return 0;
}

export function normalizeContentWidth(raw: unknown, fallback: DisplayContentWidth = 'wide'): DisplayContentWidth {
  if (raw === 'standard' || raw === 'wide' || raw === 'full') return raw;
  return fallback;
}

export function normalizeDensity(raw: unknown, fallback: DisplayDensity = 'standard'): DisplayDensity {
  if (raw === 'compact' || raw === 'standard' || raw === 'comfortable') return raw;
  return fallback;
}

export function normalizeSidebarBehavior(
  raw: unknown,
  fallback: DisplaySidebarBehavior = 'standard',
): DisplaySidebarBehavior {
  if (raw === 'standard' || raw === 'compact' || raw === 'auto_collapse') return raw;
  return fallback;
}

export function normalizeAdaptationMode(raw: unknown): DisplayAdaptationMode {
  if (raw === 'auto' || raw === 'desktop_27' || raw === 'laptop_15' || raw === 'custom') {
    return raw;
  }
  return 'auto';
}

export function sanitizeDisplayConfig(raw: unknown): DisplayAdaptationConfig {
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_DISPLAY_CONFIG };
  }
  const obj = raw as Record<string, unknown>;
  const mode = normalizeAdaptationMode(obj.mode);
  const base = mode === 'laptop_15' ? LAPTOP_15_PARAMS : DESKTOP_27_PARAMS;
  return {
    mode,
    uiScale: clampUiScale(obj.uiScale, base.uiScale),
    fontOffset: obj.fontOffset !== undefined ? normalizeFontOffset(obj.fontOffset) : base.fontOffset,
    contentWidth: normalizeContentWidth(obj.contentWidth, base.contentWidth),
    density: normalizeDensity(obj.density, base.density),
    sidebarBehavior: normalizeSidebarBehavior(obj.sidebarBehavior, base.sidebarBehavior),
    activePresetId: typeof obj.activePresetId === 'string' ? obj.activePresetId : null,
    updatedAt: typeof obj.updatedAt === 'string' ? obj.updatedAt : undefined,
  };
}

export function sanitizeDisplayPresetList(raw: unknown): DisplayAdaptationPreset[] {
  if (!Array.isArray(raw)) return [];
  const list: DisplayAdaptationPreset[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const obj = item as Record<string, unknown>;
    const id = typeof obj.id === 'string' ? obj.id.trim() : '';
    const name = typeof obj.name === 'string' ? obj.name.trim() : '';
    if (!id || !name) continue;
    const targetScreen =
      obj.targetScreen === 'desktop_27' || obj.targetScreen === 'laptop_15' || obj.targetScreen === 'custom'
        ? obj.targetScreen
        : 'custom';
    list.push({
      id,
      name,
      targetScreen,
      builtIn: Boolean(obj.builtIn),
      uiScale: clampUiScale(obj.uiScale, 100),
      fontOffset: normalizeFontOffset(obj.fontOffset),
      contentWidth: normalizeContentWidth(obj.contentWidth, 'wide'),
      density: normalizeDensity(obj.density, 'standard'),
      sidebarBehavior: normalizeSidebarBehavior(obj.sidebarBehavior, 'standard'),
      updatedAt: typeof obj.updatedAt === 'string' ? obj.updatedAt : undefined,
    });
  }
  return list;
}

/**
 * 识别当前屏幕环境：区分公司 27 寸桌面显示器与家里 15.6 寸笔记本屏幕
 * - 15.6 寸笔记本常见逻辑分辨率：1280×720、1366×768、1440×900、1536×864（1080p + Windows 125% 缩放）、1600×900，或视口高度 <= 920px 且宽度 <= 1680px
 * - 27 寸桌面显示器常见逻辑分辨率：1920×1080 (100%)、2048×1152、2560×1440 (2K)、3840×2160 (4K)
 */
export function detectScreenEnvironment(input?: {
  viewportWidth?: number;
  viewportHeight?: number;
  screenWidth?: number;
  screenHeight?: number;
  devicePixelRatio?: number;
}): ScreenEnvironmentSnapshot {
  const hasWindow = typeof window !== 'undefined';
  const viewportWidth = Math.max(
    320,
    Math.round(input?.viewportWidth ?? (hasWindow ? window.innerWidth : 1920)),
  );
  const viewportHeight = Math.max(
    320,
    Math.round(input?.viewportHeight ?? (hasWindow ? window.innerHeight : 1080)),
  );
  const screenWidth = Math.max(
    viewportWidth,
    Math.round(input?.screenWidth ?? (hasWindow && window.screen ? window.screen.width : viewportWidth)),
  );
  const screenHeight = Math.max(
    viewportHeight,
    Math.round(input?.screenHeight ?? (hasWindow && window.screen ? window.screen.height : viewportHeight)),
  );
  const rawDpr = input?.devicePixelRatio ?? (hasWindow ? window.devicePixelRatio || 1 : 1);
  const devicePixelRatio = Math.round(Math.max(1, rawDpr) * 100) / 100;

  // 判断是否为 15.6 寸笔记本形态：
  // 1) 逻辑视口宽度 <= 1680（覆盖 1366、1440、1536 [1080p@125%]、1600）
  // 2) 或者逻辑视口宽度 <= 1740 且视口高度 <= 940 且 DPR >= 1.2（高分屏笔记本缩放）
  const isLaptopViewport =
    viewportWidth <= 1680 ||
    (viewportWidth <= 1740 && viewportHeight <= 940) ||
    (screenWidth <= 1680 && viewportHeight <= 960);

  if (isLaptopViewport) {
    const scaleHint =
      devicePixelRatio > 1.05
        ? `系统缩放约 ${Math.round(devicePixelRatio * 100)}%`
        : '标准像素密度';
    return {
      viewportWidth,
      viewportHeight,
      screenWidth,
      screenHeight,
      devicePixelRatio,
      detectedClass: 'laptop_15',
      detectedLabel: '15.6 寸笔记本屏幕',
      detectedReason: `逻辑视口 ${viewportWidth}×${viewportHeight}（${scaleHint}），建议启用 92.5% 紧凑缩放与满宽无截断布局`,
      recommendedModeLabel: '15.6 寸笔记本紧凑模式',
    };
  }

  return {
    viewportWidth,
    viewportHeight,
    screenWidth,
    screenHeight,
    devicePixelRatio,
    detectedClass: 'desktop_27',
    detectedLabel: '27 寸桌面大屏显示器',
    detectedReason: `逻辑视口 ${viewportWidth}×${viewportHeight}（DPR ${devicePixelRatio}x），空间充裕，建议启用 100% 标准比例与宽屏舒展画布`,
    recommendedModeLabel: '27 寸办公大屏舒展模式',
  };
}

export function resolveEffectiveDisplayParams(
  config: DisplayAdaptationConfig,
  detectedClass: DisplayScreenClass,
): { effectiveClass: DisplayScreenClass; params: DisplayAdaptationParams } {
  if (config.mode === 'auto') {
    const params = detectedClass === 'laptop_15' ? LAPTOP_15_PARAMS : DESKTOP_27_PARAMS;
    return { effectiveClass: detectedClass, params: { ...params } };
  }
  if (config.mode === 'desktop_27') {
    return { effectiveClass: 'desktop_27', params: { ...DESKTOP_27_PARAMS } };
  }
  if (config.mode === 'laptop_15') {
    return { effectiveClass: 'laptop_15', params: { ...LAPTOP_15_PARAMS } };
  }
  return {
    effectiveClass: detectedClass,
    params: {
      uiScale: clampUiScale(config.uiScale, 100),
      fontOffset: normalizeFontOffset(config.fontOffset),
      contentWidth: normalizeContentWidth(config.contentWidth, 'wide'),
      density: normalizeDensity(config.density, 'standard'),
      sidebarBehavior: normalizeSidebarBehavior(config.sidebarBehavior, 'standard'),
    },
  };
}

export function computeDisplayCssTokens(
  config: DisplayAdaptationConfig,
  detectedClass: DisplayScreenClass,
): ComputedDisplayCssTokens {
  const { effectiveClass, params } = resolveEffectiveDisplayParams(config, detectedClass);
  const scaleFactor = clampUiScale(params.uiScale, 100) / 100;
  const fontDelta = params.fontOffset * 0.75;

  // 根字号（驱动 Tailwind 所有 rem 单位整体等比缩放）
  const rootFontSizePx = Math.round((16 * scaleFactor + fontDelta * 0.45) * 100) / 100;

  const roundPx = (base: number) =>
    Math.round((base * scaleFactor + fontDelta) * 10) / 10;

  let sidebarWidthPx = 238;
  if (params.sidebarBehavior === 'compact') {
    sidebarWidthPx = 212;
  } else if (params.sidebarBehavior === 'auto_collapse') {
    sidebarWidthPx = effectiveClass === 'laptop_15' ? 212 : 232;
  } else {
    sidebarWidthPx = Math.round(238 * Math.min(1.04, Math.max(0.92, scaleFactor)));
  }

  const shouldCollapseSidebarOnLaptop =
    params.sidebarBehavior === 'auto_collapse' && effectiveClass === 'laptop_15';

  let mainMaxWidthCss = '1760px';
  if (params.contentWidth === 'standard') {
    mainMaxWidthCss = '1380px';
  } else if (params.contentWidth === 'full') {
    mainMaxWidthCss = '100%';
  } else {
    mainMaxWidthCss = '1760px';
  }

  const isCompactSpace =
    params.density === 'compact' ||
    (config.mode !== 'desktop_27' && effectiveClass === 'laptop_15' && params.density !== 'comfortable');

  const shellGapPx = isCompactSpace ? 10 : params.density === 'comfortable' ? 16 : 14;
  const shellPadYPx = isCompactSpace ? 8 : 12;
  const shellPadY2Px = shellPadYPx * 2;
  const shellPadCss = isCompactSpace
    ? '8px 10px 8px 8px'
    : params.density === 'comfortable'
      ? '14px 18px 14px 14px'
      : '12px 16px 12px 12px';

  const headerHeightPx = isCompactSpace ? 52 : params.density === 'comfortable' ? 60 : 56;

  return {
    effectiveClass,
    effectiveParams: params,
    rootFontSizePx,
    scaleFactor,
    sidebarWidthPx,
    shouldCollapseSidebarOnLaptop,
    headerHeightPx,
    mainMaxWidthCss,
    shellGapPx,
    shellPadCss,
    shellPadYPx,
    shellPadY2Px,
    fs2xsPx: roundPx(11),
    fsXsPx: roundPx(12),
    fsSmPx: roundPx(13.5),
    fsBasePx: roundPx(14),
    fsMdPx: roundPx(15.5),
    fsLgPx: roundPx(17.5),
    fsXlPx: roundPx(20.5),
    fs2xlPx: roundPx(25),
  };
}

export function applyDisplayAdaptationToDocument(
  config: DisplayAdaptationConfig,
  detectedClass: DisplayScreenClass,
  doc: Document | null = typeof document !== 'undefined' ? document : null,
): ComputedDisplayCssTokens {
  const tokens = computeDisplayCssTokens(config, detectedClass);
  if (!doc || !doc.documentElement) return tokens;

  const root = doc.documentElement;
  root.style.fontSize = `${tokens.rootFontSizePx}px`;
  root.style.setProperty('--wbx-sidebar-w', `${tokens.sidebarWidthPx}px`);
  root.style.setProperty('--wbx-header-h', `${tokens.headerHeightPx}px`);
  root.style.setProperty('--wbx-main-max', tokens.mainMaxWidthCss);
  root.style.setProperty('--wbx-shell-gap', `${tokens.shellGapPx}px`);
  root.style.setProperty('--wbx-shell-pad', tokens.shellPadCss);
  root.style.setProperty('--wbx-shell-pad-y', `${tokens.shellPadYPx}px`);
  root.style.setProperty('--wbx-shell-pad-y2', `${tokens.shellPadY2Px}px`);

  root.style.setProperty('--wbx-fs-2xs', `${tokens.fs2xsPx}px`);
  root.style.setProperty('--wbx-fs-xs', `${tokens.fsXsPx}px`);
  root.style.setProperty('--wbx-fs-sm', `${tokens.fsSmPx}px`);
  root.style.setProperty('--wbx-fs-base', `${tokens.fsBasePx}px`);
  root.style.setProperty('--wbx-fs-md', `${tokens.fsMdPx}px`);
  root.style.setProperty('--wbx-fs-lg', `${tokens.fsLgPx}px`);
  root.style.setProperty('--wbx-fs-xl', `${tokens.fsXlPx}px`);
  root.style.setProperty('--wbx-fs-2xl', `${tokens.fs2xlPx}px`);

  root.setAttribute('data-display-mode', config.mode);
  root.setAttribute('data-display-screen', tokens.effectiveClass);
  root.setAttribute('data-display-density', tokens.effectiveParams.density);
  root.setAttribute('data-display-content-width', tokens.effectiveParams.contentWidth);
  root.setAttribute('data-display-sidebar', tokens.effectiveParams.sidebarBehavior);

  return tokens;
}

export function formatDisplayAdaptationBadge(
  config: DisplayAdaptationConfig,
  detectedClass: DisplayScreenClass,
): string {
  const { params } = resolveEffectiveDisplayParams(config, detectedClass);
  if (config.mode === 'auto') {
    return detectedClass === 'laptop_15' ? '15.6寸' : '27寸';
  }
  if (config.mode === 'desktop_27') return '27寸';
  if (config.mode === 'laptop_15') return '15.6寸';
  return `${params.uiScale}%`;
}

export function loadLocalDisplayConfig(): DisplayAdaptationConfig {
  try {
    const raw = localStorage.getItem(DISPLAY_CONFIG_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_DISPLAY_CONFIG };
    return sanitizeDisplayConfig(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_DISPLAY_CONFIG };
  }
}

export function saveLocalDisplayConfig(config: DisplayAdaptationConfig): void {
  try {
    localStorage.setItem(
      DISPLAY_CONFIG_STORAGE_KEY,
      JSON.stringify({
        ...config,
        updatedAt: new Date().toISOString(),
      }),
    );
  } catch {
    // ignore storage quota errors
  }
}
