import React, { useState, useEffect, useCallback } from 'react';
import {
  Monitor,
  Laptop,
  Sparkles,
  RotateCcw,
  BookmarkPlus,
  Check,
  Sliders,
  Maximize2,
  PanelLeft,
  Eye,
  Trash2,
  Layers,
  Info,
  ArrowRightLeft,
} from 'lucide-react';
import {
  BUILT_IN_DISPLAY_PRESETS,
  DEFAULT_DISPLAY_CONFIG,
  DESKTOP_27_PARAMS,
  LAPTOP_15_PARAMS,
  clampUiScale,
  computeDisplayCssTokens,
  resolveEffectiveDisplayParams,
  sanitizeDisplayPresetList,
  type DisplayAdaptationConfig,
  type DisplayAdaptationMode,
  type DisplayAdaptationParams,
  type DisplayAdaptationPreset,
  type DisplayContentWidth,
  type DisplayDensity,
  type DisplaySidebarBehavior,
  type ScreenEnvironmentSnapshot,
} from '../lib/displayAdaptation';

export interface DisplayAdaptationPageProps {
  apiFetch: (input: string, init?: RequestInit) => Promise<Response>;
  config: DisplayAdaptationConfig;
  screenEnv: ScreenEnvironmentSnapshot;
  sidebarCollapsed: boolean;
  onUpdateConfig: (next: DisplayAdaptationConfig) => void;
  onResetDefault: () => void;
  onSetSidebarCollapsed?: (collapsed: boolean) => void;
  onToast?: (message: string, type?: 'success' | 'error' | 'info' | 'warn') => void;
}

const QUICK_SCALE_STOPS: { value: number; tag?: string }[] = [
  { value: 87.5 },
  { value: 90 },
  { value: 92.5, tag: '15.6寸推荐' },
  { value: 95 },
  { value: 97.5 },
  { value: 100, tag: '27寸推荐' },
  { value: 105 },
  { value: 110 },
];

export const DisplayAdaptationPage: React.FC<DisplayAdaptationPageProps> = ({
  apiFetch,
  config,
  screenEnv,
  sidebarCollapsed,
  onUpdateConfig,
  onResetDefault,
  onSetSidebarCollapsed,
  onToast,
}) => {
  const [customPresets, setCustomPresets] = useState<DisplayAdaptationPreset[]>([]);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [savingPreset, setSavingPreset] = useState(false);
  const [newPresetName, setNewPresetName] = useState('');
  const [newPresetTarget, setNewPresetTarget] = useState<'desktop_27' | 'laptop_15' | 'custom'>(
    screenEnv.detectedClass === 'laptop_15' ? 'laptop_15' : 'desktop_27',
  );
  const [showSaveInput, setShowSaveInput] = useState(false);
  const [previewCompareMode, setPreviewCompareMode] = useState<'current' | 'desktop_27' | 'laptop_15'>('current');

  const { effectiveClass, params: effectiveParams } = resolveEffectiveDisplayParams(
    config,
    screenEnv.detectedClass,
  );
  const tokens = computeDisplayCssTokens(config, screenEnv.detectedClass);

  const loadCustomPresets = useCallback(async () => {
    setLoadingPresets(true);
    try {
      const res = await apiFetch('/api/workbench/display-presets');
      if (res.ok) {
        const data = await res.json();
        setCustomPresets(sanitizeDisplayPresetList(data?.presets));
      }
    } catch {
      // ignore transient network errors
    } finally {
      setLoadingPresets(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    void loadCustomPresets();
  }, [loadCustomPresets]);

  const handleSelectMode = (mode: DisplayAdaptationMode) => {
    if (mode === 'auto') {
      const targetParams =
        screenEnv.detectedClass === 'laptop_15' ? LAPTOP_15_PARAMS : DESKTOP_27_PARAMS;
      onUpdateConfig({
        mode: 'auto',
        ...targetParams,
        activePresetId: 'builtin_auto',
      });
      if (onSetSidebarCollapsed) {
        onSetSidebarCollapsed(false);
      }
      onToast?.(
        `已启用智能自动识别：当前匹配「${screenEnv.detectedLabel}」方案`,
        'success',
      );
      return;
    }

    if (mode === 'desktop_27') {
      onUpdateConfig({
        mode: 'desktop_27',
        ...DESKTOP_27_PARAMS,
        activePresetId: 'builtin_desktop_27',
      });
      if (onSetSidebarCollapsed) {
        onSetSidebarCollapsed(false);
      }
      onToast?.('已切换为「公司 27 寸办公大屏」标准舒展预设', 'success');
      return;
    }

    if (mode === 'laptop_15') {
      onUpdateConfig({
        mode: 'laptop_15',
        ...LAPTOP_15_PARAMS,
        activePresetId: 'builtin_laptop_15',
      });
      if (onSetSidebarCollapsed) {
        onSetSidebarCollapsed(false);
      }
      onToast?.('已切换为「家里 15.6 寸笔记本」紧凑防截断预设', 'success');
      return;
    }

    onUpdateConfig({
      ...config,
      mode: 'custom',
      activePresetId: null,
    });
  };

  const handlePatchCustomParam = (patch: Partial<DisplayAdaptationParams>) => {
    const nextParams: DisplayAdaptationParams = {
      ...effectiveParams,
      ...patch,
    };
    onUpdateConfig({
      mode: 'custom',
      ...nextParams,
      activePresetId: null,
    });
    if (patch.sidebarBehavior === 'auto_collapse' && onSetSidebarCollapsed) {
      if (screenEnv.detectedClass === 'laptop_15') {
        onSetSidebarCollapsed(true);
      }
    } else if (
      patch.sidebarBehavior &&
      patch.sidebarBehavior !== 'auto_collapse' &&
      sidebarCollapsed &&
      onSetSidebarCollapsed
    ) {
      onSetSidebarCollapsed(false);
    }
  };

  const handleApplyPreset = (preset: DisplayAdaptationPreset) => {
    const mode: DisplayAdaptationMode =
      preset.id === 'builtin_desktop_27'
        ? 'desktop_27'
        : preset.id === 'builtin_laptop_15'
          ? 'laptop_15'
          : 'custom';
    onUpdateConfig({
      mode,
      uiScale: preset.uiScale,
      fontOffset: preset.fontOffset,
      contentWidth: preset.contentWidth,
      density: preset.density,
      sidebarBehavior: preset.sidebarBehavior,
      activePresetId: preset.id,
    });
    if (preset.sidebarBehavior === 'auto_collapse' && onSetSidebarCollapsed) {
      onSetSidebarCollapsed(screenEnv.detectedClass === 'laptop_15');
    } else if (onSetSidebarCollapsed && sidebarCollapsed) {
      onSetSidebarCollapsed(false);
    }
    onToast?.(`已应用预设「${preset.name}」`, 'success');
  };

  const handleSaveCustomPreset = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newPresetName.trim();
    if (!trimmed) {
      onToast?.('请输入预设名称，例如：家里15.6寸笔记本紧凑方案', 'warn');
      return;
    }
    setSavingPreset(true);
    try {
      const res = await apiFetch('/api/workbench/display-presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: trimmed,
          targetScreen: newPresetTarget,
          uiScale: effectiveParams.uiScale,
          fontOffset: effectiveParams.fontOffset,
          contentWidth: effectiveParams.contentWidth,
          density: effectiveParams.density,
          sidebarBehavior: effectiveParams.sidebarBehavior,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || '保存预设失败');
      }
      const nextList = sanitizeDisplayPresetList(data?.presets);
      setCustomPresets(nextList);
      if (data?.preset?.id) {
        onUpdateConfig({
          ...config,
          mode: 'custom',
          ...effectiveParams,
          activePresetId: data.preset.id,
        });
      }
      setNewPresetName('');
      setShowSaveInput(false);
      onToast?.(`预设「${trimmed}」已保存，可在任意电脑登录一键套用`, 'success');
    } catch (err) {
      onToast?.(err instanceof Error ? err.message : '保存预设失败', 'error');
    } finally {
      setSavingPreset(false);
    }
  };

  const handleDeleteCustomPreset = async (preset: DisplayAdaptationPreset) => {
    try {
      const res = await apiFetch(
        `/api/workbench/display-presets/${encodeURIComponent(preset.id)}`,
        {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: preset.id }),
        },
      );
      if (res.ok) {
        const data = await res.json();
        setCustomPresets(sanitizeDisplayPresetList(data?.presets));
        onToast?.(`已删除预设「${preset.name}」`, 'info');
      }
    } catch {
      onToast?.('删除预设失败', 'error');
    }
  };

  // 计算预览区的模拟参数
  const previewParams: DisplayAdaptationParams =
    previewCompareMode === 'desktop_27'
      ? DESKTOP_27_PARAMS
      : previewCompareMode === 'laptop_15'
        ? LAPTOP_15_PARAMS
        : effectiveParams;

  const estimatedVisibleRows =
    previewParams.density === 'compact'
      ? Math.round(16 * (100 / previewParams.uiScale))
      : previewParams.density === 'comfortable'
        ? Math.round(11 * (100 / previewParams.uiScale))
        : Math.round(13 * (100 / previewParams.uiScale));

  const effectiveHorizontalWorkspacePx = Math.max(
    640,
    Math.round(
      screenEnv.viewportWidth -
        (tokens.shouldCollapseSidebarOnLaptop || sidebarCollapsed ? 68 : tokens.sidebarWidthPx) -
        tokens.shellGapPx -
        tokens.shellPadYPx * 2,
    ),
  );

  const isDefaultState =
    config.mode === DEFAULT_DISPLAY_CONFIG.mode &&
    config.activePresetId === DEFAULT_DISPLAY_CONFIG.activePresetId;

  return (
    <div className="space-y-4 pb-6" data-testid="display-adaptation-page">
      {/* 顶部标题与当前屏幕硬件实时感知舱 */}
      <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-lg font-bold tracking-tight text-slate-900">
                跨屏界面适配中心
              </h1>
              <span
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-0.5 text-xs font-semibold ${
                  screenEnv.detectedClass === 'laptop_15'
                    ? 'bg-amber-50 text-amber-800 border border-amber-200/80'
                    : 'bg-sky-50 text-sky-800 border border-sky-200/80'
                }`}
                data-testid="detected-screen-badge"
              >
                {screenEnv.detectedClass === 'laptop_15' ? (
                  <Laptop className="h-3.5 w-3.5 text-amber-600" />
                ) : (
                  <Monitor className="h-3.5 w-3.5 text-sky-600" />
                )}
                当前识别：{screenEnv.detectedLabel}
              </span>
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 border border-emerald-200/80 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                <Check className="h-3.5 w-3.5 text-emerald-600" />
                本机独立生效（跨设备互不覆盖）
              </span>
            </div>
            <p className="text-xs text-slate-500">
              针对公司 27 寸显示器与家里 15.6 寸笔记本跨屏办公优化，支持自动识别屏幕尺寸、全局字号缩放、防截断满宽画布与跨设备预设同步。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={() => setShowSaveInput(prev => !prev)}
              data-testid="open-save-preset-btn"
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:border-slate-300 transition-colors cursor-pointer"
            >
              <BookmarkPlus className="h-3.5 w-3.5 text-sky-600" />
              保存当前为预设
            </button>
            <button
              type="button"
              onClick={() => {
                onResetDefault();
                if (onSetSidebarCollapsed) onSetSidebarCollapsed(false);
                onToast?.('已恢复默认智能自动适配设置', 'info');
              }}
              disabled={isDefaultState}
              data-testid="reset-display-default-btn"
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-colors ${
                isDefaultState
                  ? 'border-slate-100 bg-slate-50 text-slate-400 cursor-not-allowed'
                  : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300 cursor-pointer'
              }`}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              恢复默认设置
            </button>
          </div>
        </div>

        {/* 保存自定义预设折叠表单 */}
        {showSaveInput && (
          <form
            onSubmit={handleSaveCustomPreset}
            className="mt-4 flex flex-col gap-3 rounded-xl border border-sky-200 bg-sky-50/50 p-3.5 sm:flex-row sm:items-center"
            data-testid="save-preset-form"
          >
            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={newPresetName}
                onChange={e => setNewPresetName(e.target.value)}
                placeholder="输入预设名称，如：家里 15.6 寸笔记本精简方案 / 公司 27 寸大屏护眼"
                data-testid="preset-name-input"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-800 focus:border-sky-500 focus:outline-none"
              />
            </div>
            <div className="flex items-center gap-2">
              <select
                value={newPresetTarget}
                onChange={e =>
                  setNewPresetTarget(e.target.value as 'desktop_27' | 'laptop_15' | 'custom')
                }
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 focus:border-sky-500 focus:outline-none"
              >
                <option value="desktop_27">适用：27 寸办公显示器</option>
                <option value="laptop_15">适用：15.6 寸笔记本</option>
                <option value="custom">适用：通用自定义</option>
              </select>
              <button
                type="submit"
                disabled={savingPreset}
                data-testid="confirm-save-preset-btn"
                className="rounded-lg bg-sky-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50 cursor-pointer"
              >
                {savingPreset ? '保存中...' : '确认保存'}
              </button>
              <button
                type="button"
                onClick={() => setShowSaveInput(false)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50 cursor-pointer"
              >
                取消
              </button>
            </div>
          </form>
        )}

        {/* 硬件环境与当前生效指标 4 格遥测条 */}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3.5 py-2.5">
            <div className="text-[11px] font-medium text-slate-500">当前浏览器逻辑视口</div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span
                className="text-sm font-bold text-slate-900 font-mono tabular-nums"
                data-testid="viewport-resolution-text"
              >
                {screenEnv.viewportWidth} × {screenEnv.viewportHeight}
              </span>
              <span className="text-[11px] text-slate-500 font-mono tabular-nums">
                DPR {screenEnv.devicePixelRatio}x
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3.5 py-2.5">
            <div className="text-[11px] font-medium text-slate-500">显示器屏幕分辨率</div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span className="text-sm font-bold text-slate-900 font-mono tabular-nums">
                {screenEnv.screenWidth} × {screenEnv.screenHeight}
              </span>
              <span className="text-[11px] text-slate-500">
                {screenEnv.detectedClass === 'laptop_15' ? '笔记本视口' : '桌面宽屏'}
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3.5 py-2.5">
            <div className="text-[11px] font-medium text-slate-500">当前生效缩放与根字号</div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span
                className="text-sm font-bold text-sky-700 font-mono tabular-nums"
                data-testid="effective-scale-text"
              >
                {effectiveParams.uiScale}%
              </span>
              <span className="text-[11px] text-slate-500 font-mono tabular-nums">
                基准 {tokens.rootFontSizePx}px
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3.5 py-2.5">
            <div className="text-[11px] font-medium text-slate-500">工作区可用横向宽度</div>
            <div className="mt-0.5 flex items-baseline gap-1.5">
              <span className="text-sm font-bold text-slate-900 font-mono tabular-nums">
                {effectiveHorizontalWorkspacePx}px
              </span>
              <span className="text-[11px] text-slate-500">
                {effectiveParams.contentWidth === 'full'
                  ? '100% 满宽'
                  : effectiveParams.contentWidth === 'wide'
                    ? '1760px 宽屏'
                    : '1380px 标准'}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 核心跨屏模式一键切换（3 张主模式卡片） */}
      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3" aria-label="核心屏幕适配模式">
        {/* 模式 1：智能自动识别 */}
        <button
          type="button"
          onClick={() => handleSelectMode('auto')}
          data-testid="mode-card-auto"
          className={`group relative flex flex-col justify-between rounded-2xl border p-4 text-left transition-all cursor-pointer ${
            config.mode === 'auto'
              ? 'border-sky-500 bg-sky-50/40 shadow-sm ring-1 ring-sky-500/30'
              : 'border-slate-200/90 bg-white hover:border-slate-300 hover:bg-slate-50/40'
          }`}
        >
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="inline-flex items-center gap-2">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-xl ${
                    config.mode === 'auto'
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-100 text-slate-700 group-hover:bg-slate-200'
                  }`}
                >
                  <Sparkles className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-bold text-slate-900">智能自动适配</div>
                  <div className="text-[11px] text-slate-500">推荐 · 按当前屏幕自动切换</div>
                </div>
              </div>
              <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                  config.mode === 'auto'
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-100 text-slate-600'
                }`}
              >
                {config.mode === 'auto' ? '当前启用' : '一键启用'}
              </span>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate-600">
              自动检测浏览器视口与系统缩放：在公司 27 寸显示器自动应用 100% 宽屏舒展布局，在家里 15.6 寸笔记本自动切换 92.5% 紧凑满宽布局。
            </p>
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-slate-200/70 pt-2.5 text-[11px] font-medium text-slate-600">
            <span>当前触发方案：</span>
            <span className="font-semibold text-sky-700">
              {screenEnv.detectedClass === 'laptop_15'
                ? '15.6 寸笔记本紧凑 (92.5%)'
                : '27 寸办公大屏标准 (100%)'}
            </span>
          </div>
        </button>

        {/* 模式 2：公司 27 寸办公大屏预设 */}
        <button
          type="button"
          onClick={() => handleSelectMode('desktop_27')}
          data-testid="mode-card-desktop-27"
          className={`group relative flex flex-col justify-between rounded-2xl border p-4 text-left transition-all cursor-pointer ${
            config.mode === 'desktop_27'
              ? 'border-sky-500 bg-sky-50/40 shadow-sm ring-1 ring-sky-500/30'
              : 'border-slate-200/90 bg-white hover:border-slate-300 hover:bg-slate-50/40'
          }`}
        >
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="inline-flex items-center gap-2">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-xl ${
                    config.mode === 'desktop_27'
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-100 text-slate-700 group-hover:bg-slate-200'
                  }`}
                >
                  <Monitor className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-bold text-slate-900">公司 27 寸办公大屏</div>
                  <div className="text-[11px] text-slate-500">1920×1080 / 2K / 4K 桌面显示器</div>
                </div>
              </div>
              <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                  config.mode === 'desktop_27'
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-100 text-slate-600'
                }`}
              >
                {config.mode === 'desktop_27' ? '当前固定' : '一键切换'}
              </span>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate-600">
              针对 27 寸宽屏视野设计：100% 标准字号与行高、1760px 宽屏工作区画布、238px 完整导航栏，多列核算报表呼吸感充裕。
            </p>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-200/70 pt-2.5 text-[11px] font-mono text-slate-600">
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">缩放 100%</span>
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">宽屏 1760px</span>
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">标准密度</span>
          </div>
        </button>

        {/* 模式 3：家里 15.6 寸笔记本预设 */}
        <button
          type="button"
          onClick={() => handleSelectMode('laptop_15')}
          data-testid="mode-card-laptop-15"
          className={`group relative flex flex-col justify-between rounded-2xl border p-4 text-left transition-all cursor-pointer ${
            config.mode === 'laptop_15'
              ? 'border-sky-500 bg-sky-50/40 shadow-sm ring-1 ring-sky-500/30'
              : 'border-slate-200/90 bg-white hover:border-slate-300 hover:bg-slate-50/40'
          }`}
        >
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="inline-flex items-center gap-2">
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-xl ${
                    config.mode === 'laptop_15'
                      ? 'bg-sky-600 text-white'
                      : 'bg-slate-100 text-slate-700 group-hover:bg-slate-200'
                  }`}
                >
                  <Laptop className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-bold text-slate-900">家里 15.6 寸笔记本</div>
                  <div className="text-[11px] text-slate-500">1080p (125%缩放) / 1440×900 笔记本</div>
                </div>
              </div>
              <span
                className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                  config.mode === 'laptop_15'
                    ? 'bg-sky-600 text-white'
                    : 'bg-slate-100 text-slate-600'
                }`}
              >
                {config.mode === 'laptop_15' ? '当前固定' : '一键切换'}
              </span>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate-600">
              解决笔记本显示偏大或表格拥挤：92.5% 全局精炼缩放、100% 满宽无留白防截断、204px 收窄侧栏，同屏多看 25% 数据行。
            </p>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-slate-200/70 pt-2.5 text-[11px] font-mono text-slate-600">
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">缩放 92.5%</span>
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">满宽 100%</span>
            <span className="rounded bg-white px-1.5 py-0.5 border border-slate-200">紧凑防截断</span>
          </div>
        </button>
      </section>

      {/* 下方双栏工作台：左侧 3 组精细调节面板 + 右侧实时可视化对比预览与跨设备预设库 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* 左栏：精细化调节（占 7 列） */}
        <div className="space-y-4 xl:col-span-7">
          {/* 1. 全局界面缩放比例与字号微调 */}
          <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Sliders className="h-4 w-4 text-sky-600" />
                <h2 className="text-sm font-bold text-slate-900">
                  1. 全局界面缩放比例与字号微调
                </h2>
              </div>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-mono font-semibold text-slate-700 tabular-nums">
                当前：{effectiveParams.uiScale}% · 根字号 {tokens.rootFontSizePx}px
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              针对 Windows 笔记本 125%/150% 系统缩放导致的界面偏大，可单独下调工作台缩放比例而不影响浏览器其他网页。
            </p>

            {/* 滑块与微调步进按钮 */}
            <div className="mt-4 space-y-3">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() =>
                    handlePatchCustomParam({
                      uiScale: clampUiScale(effectiveParams.uiScale - 2.5),
                    })
                  }
                  data-testid="scale-step-down"
                  className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 cursor-pointer"
                >
                  -2.5%
                </button>
                <input
                  type="range"
                  min={85}
                  max={115}
                  step={2.5}
                  value={effectiveParams.uiScale}
                  onChange={e =>
                    handlePatchCustomParam({ uiScale: clampUiScale(Number(e.target.value)) })
                  }
                  aria-label="全局界面缩放百分比"
                  data-testid="ui-scale-slider"
                  className="h-2 flex-1 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-sky-600"
                />
                <button
                  type="button"
                  onClick={() =>
                    handlePatchCustomParam({
                      uiScale: clampUiScale(effectiveParams.uiScale + 2.5),
                    })
                  }
                  data-testid="scale-step-up"
                  className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 cursor-pointer"
                >
                  +2.5%
                </button>
              </div>

              {/* 常用比例快捷档位 */}
              <div className="flex flex-wrap items-center gap-1.5">
                {QUICK_SCALE_STOPS.map(stop => {
                  const active = Math.abs(effectiveParams.uiScale - stop.value) < 0.1;
                  return (
                    <button
                      key={stop.value}
                      type="button"
                      onClick={() => handlePatchCustomParam({ uiScale: stop.value })}
                      data-testid={`scale-stop-${stop.value}`}
                      className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-mono font-semibold transition-colors cursor-pointer ${
                        active
                          ? 'border-sky-500 bg-sky-50 text-sky-700'
                          : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      <span>{stop.value}%</span>
                      {stop.tag && (
                        <span className="font-sans text-[10px] font-normal text-slate-500">
                          ({stop.tag})
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 字号层级微调 */}
            <div className="mt-4 border-t border-slate-100 pt-3.5">
              <div className="mb-2 text-xs font-semibold text-slate-700">文字字阶补偿微调</div>
              <div className="grid grid-cols-3 gap-2.5">
                {(
                  [
                    {
                      value: -1 as const,
                      label: '紧凑字阶 (-1px)',
                      desc: '适合 15.6 寸小屏展示长表头与多字段',
                    },
                    {
                      value: 0 as const,
                      label: '标准字阶 (默认)',
                      desc: '遵循基准排版比例，清晰锐利',
                    },
                    {
                      value: 1 as const,
                      label: '舒展大字 (+1px)',
                      desc: '适合 27 寸高分屏远距离阅读',
                    },
                  ] as const
                ).map(item => {
                  const active = effectiveParams.fontOffset === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => handlePatchCustomParam({ fontOffset: item.value })}
                      data-testid={`font-offset-${item.value}`}
                      className={`rounded-xl border p-2.5 text-left transition-all cursor-pointer ${
                        active
                          ? 'border-sky-500 bg-sky-50/50 text-sky-900'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <div className="text-xs font-bold">{item.label}</div>
                      <div className="mt-0.5 text-[11px] text-slate-500">{item.desc}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>

          {/* 2. 页面宽度与卡片/表格排版密度 */}
          <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
            <div className="flex items-center gap-2">
              <Maximize2 className="h-4 w-4 text-sky-600" />
              <h2 className="text-sm font-bold text-slate-900">
                2. 页面宽度与卡片列数/表格密度适配
              </h2>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              27 寸显示器可开启宽屏或居中画布保持视线聚焦；15.6 寸笔记本开启 100% 满宽与紧凑密度可彻底消除横向截断。
            </p>

            <div className="mt-3.5">
              <div className="mb-2 text-xs font-semibold text-slate-700">主工作区画布最大宽度</div>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                {(
                  [
                    {
                      id: 'standard' as DisplayContentWidth,
                      label: '标准居中 (1380px)',
                      desc: '两侧适度留白，视线集中',
                    },
                    {
                      id: 'wide' as DisplayContentWidth,
                      label: '27寸宽屏舒展 (1760px)',
                      desc: '27 寸显示器默认，多列卡片均衡',
                    },
                    {
                      id: 'full' as DisplayContentWidth,
                      label: '15.6寸满宽无留白 (100%)',
                      desc: '笔记本推荐，释放全部横向空间',
                    },
                  ] as const
                ).map(item => {
                  const active = effectiveParams.contentWidth === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => handlePatchCustomParam({ contentWidth: item.id })}
                      data-testid={`content-width-${item.id}`}
                      className={`rounded-xl border p-3 text-left transition-all cursor-pointer ${
                        active
                          ? 'border-sky-500 bg-sky-50/50 text-sky-900'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <div className="text-xs font-bold">{item.label}</div>
                      <div className="mt-1 text-[11px] text-slate-500">{item.desc}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="mt-4 border-t border-slate-100 pt-3.5">
              <div className="mb-2 text-xs font-semibold text-slate-700">表格行高与卡片间距密度</div>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                {(
                  [
                    {
                      id: 'compact' as DisplayDensity,
                      label: '紧凑高密 (笔记本推荐)',
                      desc: '收紧表格行高与外边距，一屏多展示 25% 行数',
                    },
                    {
                      id: 'standard' as DisplayDensity,
                      label: '标准均衡 (27寸默认)',
                      desc: '兼顾信息密度与呼吸感的标准间距',
                    },
                    {
                      id: 'comfortable' as DisplayDensity,
                      label: '舒展宽松 (大屏护眼)',
                      desc: '加大卡片内边距与行高，长时间审单更轻松',
                    },
                  ] as const
                ).map(item => {
                  const active = effectiveParams.density === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => handlePatchCustomParam({ density: item.id })}
                      data-testid={`density-${item.id}`}
                      className={`rounded-xl border p-3 text-left transition-all cursor-pointer ${
                        active
                          ? 'border-sky-500 bg-sky-50/50 text-sky-900'
                          : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                      }`}
                    >
                      <div className="text-xs font-bold">{item.label}</div>
                      <div className="mt-1 text-[11px] text-slate-500">{item.desc}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          </section>

          {/* 3. 左侧导航栏与工作区间距自适应 */}
          <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <PanelLeft className="h-4 w-4 text-sky-600" />
                <h2 className="text-sm font-bold text-slate-900">
                  3. 左侧导航栏与工作区间距自适应
                </h2>
              </div>
              {onSetSidebarCollapsed && (
                <button
                  type="button"
                  onClick={() => onSetSidebarCollapsed(!sidebarCollapsed)}
                  data-testid="quick-toggle-sidebar-btn"
                  className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 cursor-pointer"
                >
                  {sidebarCollapsed ? '立即展开侧栏' : '立即收起为图标轨'}
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              控制在 15.6 寸笔记本上自动收窄左侧导航栏宽度或折叠为 68px 图标轨，为右侧业务表格让出更多水平空间。
            </p>

            <div className="mt-3.5 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {(
                [
                  {
                    id: 'standard' as DisplaySidebarBehavior,
                    label: '标准全展开侧栏 (238px)',
                    desc: '27 寸显示器推荐，完整显示分组与状态徽章',
                  },
                  {
                    id: 'compact' as DisplaySidebarBehavior,
                    label: '笔记本精简窄栏 (204px)',
                    desc: '15.6 寸笔记本推荐，保留文字同时收窄 34px',
                  },
                  {
                    id: 'auto_collapse' as DisplaySidebarBehavior,
                    label: '笔记本自动折叠图标轨 (68px)',
                    desc: '检测到 15.6 寸屏幕时自动收起为图标轨，释放 170px',
                  },
                ] as const
              ).map(item => {
                const active = effectiveParams.sidebarBehavior === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handlePatchCustomParam({ sidebarBehavior: item.id })}
                    data-testid={`sidebar-behavior-${item.id}`}
                    className={`rounded-xl border p-3 text-left transition-all cursor-pointer ${
                      active
                        ? 'border-sky-500 bg-sky-50/50 text-sky-900'
                        : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <div className="text-xs font-bold">{item.label}</div>
                    <div className="mt-1 text-[11px] text-slate-500">{item.desc}</div>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        {/* 右栏：实时可视化对比预览 + 跨设备预设库（占 5 列） */}
        <div className="space-y-4 xl:col-span-5">
          {/* 实时可视化预览对比舱 */}
          <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Eye className="h-4 w-4 text-sky-600" />
                <h2 className="text-sm font-bold text-slate-900">实时排版密度与跨屏仿真对比</h2>
              </div>
              <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setPreviewCompareMode('current')}
                  className={`rounded-md px-2 py-1 font-semibold cursor-pointer ${
                    previewCompareMode === 'current'
                      ? 'bg-white text-sky-700 shadow-2xs'
                      : 'text-slate-600'
                  }`}
                >
                  当前配置
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewCompareMode('desktop_27')}
                  className={`rounded-md px-2 py-1 font-semibold cursor-pointer ${
                    previewCompareMode === 'desktop_27'
                      ? 'bg-white text-sky-700 shadow-2xs'
                      : 'text-slate-600'
                  }`}
                >
                  对比27寸
                </button>
                <button
                  type="button"
                  onClick={() => setPreviewCompareMode('laptop_15')}
                  className={`rounded-md px-2 py-1 font-semibold cursor-pointer ${
                    previewCompareMode === 'laptop_15'
                      ? 'bg-white text-sky-700 shadow-2xs'
                      : 'text-slate-600'
                  }`}
                >
                  对比15.6寸
                </button>
              </div>
            </div>

            {/* 迷你工作台比例仿真器 */}
            <div className="mt-3.5 rounded-xl border border-slate-200 bg-slate-100/80 p-3">
              <div className="mb-2 flex items-center justify-between text-[11px] text-slate-600">
                <span className="font-semibold">
                  {previewCompareMode === 'current'
                    ? `当前生效方案（缩放 ${previewParams.uiScale}%）`
                    : previewCompareMode === 'desktop_27'
                      ? '公司 27 寸大屏方案（缩放 100%）'
                      : '家里 15.6 寸笔记本方案（缩放 92.5%）'}
                </span>
                <span className="font-mono">
                  单屏预估可见约 <strong className="text-sky-700">{estimatedVisibleRows}</strong> 行记录
                </span>
              </div>

              <div className="flex gap-2 rounded-lg border border-slate-200/90 bg-white p-2.5 shadow-2xs">
                {/* 模拟侧栏 */}
                <div
                  className={`flex flex-col justify-between rounded-md border border-slate-200/80 bg-slate-50 p-1.5 transition-all ${
                    previewParams.sidebarBehavior === 'auto_collapse'
                      ? 'w-7 items-center'
                      : previewParams.sidebarBehavior === 'compact'
                        ? 'w-20'
                        : 'w-24'
                  }`}
                >
                  <div className="space-y-1 w-full">
                    <div className="h-2.5 rounded bg-sky-500/20 border border-sky-400/30" />
                    <div className="h-2 rounded bg-slate-200/80" />
                    <div className="h-2 rounded bg-slate-200/80" />
                    <div className="h-2 rounded bg-slate-200/80" />
                  </div>
                  <div className="mt-3 text-[9px] font-mono text-slate-400 text-center">
                    {previewParams.sidebarBehavior === 'auto_collapse'
                      ? '68px'
                      : previewParams.sidebarBehavior === 'compact'
                        ? '204px'
                        : '238px'}
                  </div>
                </div>

                {/* 模拟右侧主舞台与表格行密度 */}
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex items-center justify-between rounded bg-slate-50 px-2 py-1 border border-slate-200/70">
                    <span className="text-[10px] font-semibold text-slate-700">
                      薪资核算 / 支付绑定明细表
                    </span>
                    <span className="text-[10px] font-mono text-sky-700">
                      {previewParams.contentWidth === 'full'
                        ? '满宽 100%'
                        : previewParams.contentWidth === 'wide'
                          ? '宽屏 1760px'
                          : '标准 1380px'}
                    </span>
                  </div>

                  <div className="overflow-hidden rounded border border-slate-200/80">
                    <div className="grid grid-cols-4 bg-slate-50 px-2 py-1 text-[10px] font-semibold text-slate-500 border-b border-slate-200/80">
                      <span>城市站点</span>
                      <span>骑手姓名</span>
                      <span>账单周期</span>
                      <span className="text-right">实发金额</span>
                    </div>
                    {[
                      { city: '杭州·西湖站', rider: '张明远', period: '2026-11', amt: '¥6,420.00' },
                      { city: '上海·静安站', rider: '李思源', period: '2026-11', amt: '¥7,185.50' },
                      { city: '苏州·园区站', rider: '王海峰', period: '2026-11', amt: '¥5,930.00' },
                    ].map((row, idx) => (
                      <div
                        key={idx}
                        className={`grid grid-cols-4 items-center px-2 border-b last:border-b-0 border-slate-100 text-slate-700 transition-all ${
                          previewParams.density === 'compact'
                            ? 'py-1 text-[10.5px]'
                            : previewParams.density === 'comfortable'
                              ? 'py-2 text-xs'
                              : 'py-1.5 text-[11px]'
                        }`}
                      >
                        <span className="truncate font-medium">{row.city}</span>
                        <span>{row.rider}</span>
                        <span className="font-mono text-slate-500">{row.period}</span>
                        <span className="text-right font-mono font-semibold text-slate-900">
                          {row.amt}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* 跨设备预设库（系统内置 + 个人保存） */}
          <section className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-sky-600" />
                <h2 className="text-sm font-bold text-slate-900">跨设备预设库（一键套用）</h2>
              </div>
              <span className="text-[11px] text-slate-500">
                共 {BUILT_IN_DISPLAY_PRESETS.length + customPresets.length} 套方案
              </span>
            </div>

            <div className="mt-2 flex items-start gap-2 rounded-xl border border-slate-200/80 bg-slate-50/70 p-2.5 text-[11px] leading-relaxed text-slate-600">
              <Info className="h-3.5 w-3.5 shrink-0 text-sky-600 mt-0.5" />
              <span>
                <strong>跨设备策略：</strong>当前激活的界面适配保存在本机浏览器中（公司 27 寸电脑与家里 15.6 寸笔记本互不干扰）；下方保存的自定义预设跟随您的工作空间账号同步，方便换电脑时一键套用。
              </span>
            </div>

            <div className="mt-3.5 space-y-2" data-testid="preset-library-list">
              {[...BUILT_IN_DISPLAY_PRESETS, ...customPresets].map(preset => {
                const isCurrentPreset =
                  config.activePresetId === preset.id ||
                  (config.mode === 'desktop_27' && preset.id === 'builtin_desktop_27') ||
                  (config.mode === 'laptop_15' && preset.id === 'builtin_laptop_15');

                return (
                  <div
                    key={preset.id}
                    data-testid={`preset-item-${preset.id}`}
                    className={`flex items-center justify-between gap-2.5 rounded-xl border p-3 transition-all ${
                      isCurrentPreset
                        ? 'border-sky-400 bg-sky-50/40'
                        : 'border-slate-200/90 bg-white hover:border-slate-300'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-bold text-slate-900 truncate">
                          {preset.name}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            preset.targetScreen === 'laptop_15'
                              ? 'bg-amber-50 text-amber-700 border border-amber-200/70'
                              : preset.targetScreen === 'desktop_27'
                                ? 'bg-sky-50 text-sky-700 border border-sky-200/70'
                                : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {preset.targetScreen === 'laptop_15'
                            ? '15.6寸'
                            : preset.targetScreen === 'desktop_27'
                              ? '27寸'
                              : '自定义'}
                        </span>
                        {!preset.builtIn && (
                          <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700 border border-violet-200/70">
                            账号同步
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] font-mono text-slate-500">
                        <span>缩放 {preset.uiScale}%</span>
                        <span>·</span>
                        <span>
                          {preset.contentWidth === 'full'
                            ? '满宽 100%'
                            : preset.contentWidth === 'wide'
                              ? '宽屏 1760px'
                              : '标准 1380px'}
                        </span>
                        <span>·</span>
                        <span>
                          {preset.density === 'compact'
                            ? '紧凑密度'
                            : preset.density === 'comfortable'
                              ? '宽松密度'
                              : '标准密度'}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleApplyPreset(preset)}
                        data-testid={`apply-preset-${preset.id}`}
                        className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                          isCurrentPreset
                            ? 'bg-sky-600 text-white'
                            : 'border border-slate-200 bg-slate-50 text-slate-700 hover:bg-sky-50 hover:text-sky-700 hover:border-sky-200'
                        }`}
                      >
                        {isCurrentPreset ? (
                          <>
                            <Check className="h-3.5 w-3.5" />
                            已套用
                          </>
                        ) : (
                          <>
                            <ArrowRightLeft className="h-3.5 w-3.5" />
                            套用
                          </>
                        )}
                      </button>
                      {!preset.builtIn && (
                        <button
                          type="button"
                          onClick={() => void handleDeleteCustomPreset(preset)}
                          title="删除此自定义预设"
                          aria-label={`删除预设 ${preset.name}`}
                          data-testid={`delete-preset-${preset.id}`}
                          className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-400 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 cursor-pointer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}

              {loadingPresets && (
                <div className="py-2 text-center text-xs text-slate-400">正在同步预设列表...</div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
