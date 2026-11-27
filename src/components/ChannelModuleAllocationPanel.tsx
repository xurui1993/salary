import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Plus, X } from 'lucide-react';
import {
  partitionBusinessModules,
  partitionPlatformChannels,
  resolveModuleGroupLabel,
  resolveSubmoduleLabel,
  type BusinessModuleKey,
  type ChannelMode,
  type GlobalWorkbenchConfig,
  type PlatformChannelKey,
} from '../lib/workbenchConfig';

export interface ChannelModuleAllocationPanelProps {
  globalConfig: GlobalWorkbenchConfig;
  searchQuery?: string;
  saving?: boolean;
  onMovePlatform: (key: PlatformChannelKey, nextMode: ChannelMode) => void;
  onMoveModule: (key: BusinessModuleKey, nextEnabled: boolean) => void;
}

type LanePopoverKey =
  | 'platform:shared'
  | 'platform:personal'
  | 'module:enabled'
  | 'module:paused';

interface DualLaneItem {
  id: string;
  label: string;
  subtitle?: string;
  tooltip: string;
}

interface DualLaneSpec {
  popoverKey: LanePopoverKey;
  title: string;
  alias?: string;
  oppositeTitle: string;
  addButtonLabel: string;
  emptyWhenAll: string;
  tone: 'sky' | 'teal' | 'amber';
  totalCount: number;
  unit: string;
  items: DualLaneItem[];
  candidates: DualLaneItem[];
  onAdd: (id: string, remainingCount: number) => void;
  onRemove: (id: string) => void;
}

const LANE_TONE_STYLES: Record<
  DualLaneSpec['tone'],
  {
    container: string;
    head: string;
    title: string;
    addBtnHover: string;
    chipHover: string;
    menuItemHover: string;
    menuAction: string;
  }
> = {
  sky: {
    container: 'border-sky-200/75 bg-sky-50/35',
    head: 'border-sky-200/50',
    title: 'text-[#0369A1]',
    addBtnHover: 'hover:border-sky-300 hover:bg-sky-50 hover:text-[#026AA2]',
    chipHover: 'hover:border-sky-300/90 hover:bg-sky-50/60',
    menuItemHover: 'hover:bg-sky-50/90',
    menuAction: 'text-[#026AA2]',
  },
  teal: {
    container: 'border-emerald-200/75 bg-emerald-50/35',
    head: 'border-emerald-200/50',
    title: 'text-[#0F766E]',
    addBtnHover: 'hover:border-emerald-300 hover:bg-emerald-50 hover:text-[#0F766E]',
    chipHover: 'hover:border-emerald-300/90 hover:bg-emerald-50/60',
    menuItemHover: 'hover:bg-emerald-50/90',
    menuAction: 'text-[#0F766E]',
  },
  amber: {
    container: 'border-amber-200/80 bg-amber-50/35',
    head: 'border-amber-200/55',
    title: 'text-amber-700',
    addBtnHover: 'hover:border-amber-300 hover:bg-amber-50 hover:text-amber-700',
    chipHover: 'hover:border-amber-300/90 hover:bg-amber-50/60',
    menuItemHover: 'hover:bg-amber-50/90',
    menuAction: 'text-amber-700',
  },
};

export function ChannelModuleAllocationPanel({
  globalConfig,
  searchQuery = '',
  saving = false,
  onMovePlatform,
  onMoveModule,
}: ChannelModuleAllocationPanelProps) {
  const [openMenu, setOpenMenu] = useState<LanePopoverKey | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!openMenu) return;
    const handleOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpenMenu(null);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenMenu(null);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [openMenu]);

  useEffect(() => {
    if (saving) {
      setOpenMenu(null);
    }
  }, [saving]);

  const platformPartition = useMemo(
    () => partitionPlatformChannels(globalConfig, searchQuery),
    [globalConfig, searchQuery],
  );

  const modulePartition = useMemo(
    () => partitionBusinessModules(globalConfig, searchQuery),
    [globalConfig, searchQuery],
  );

  const trimmedQuery = searchQuery.trim();

  const resolveModuleDisplayLabel = (modKey: BusinessModuleKey, fallback: string) =>
    modKey === 'approval'
      ? resolveSubmoduleLabel('workspace:approval', fallback, globalConfig)
      : resolveModuleGroupLabel(modKey, globalConfig);

  const platformLanes: DualLaneSpec[] = [
    {
      popoverKey: 'platform:shared',
      title: '全局共享通道',
      alias: '（复用主机连接）',
      oppositeTitle: '个人独立通道',
      addButtonLabel: '新增平台',
      emptyWhenAll: '暂无共享平台，点击右上角「新增平台」从个人独立通道移入',
      tone: 'sky',
      totalCount: platformPartition.allShared.length,
      unit: '项',
      items: platformPartition.shared.map(p => ({
        id: p.key,
        label: p.defaultLabel,
        subtitle: p.badge,
        tooltip: `${p.defaultLabel}（${p.badge}）· 关联：${p.relatedModules} · 点击右侧 × 切回个人独立通道`,
      })),
      candidates: platformPartition.allPersonal.map(p => ({
        id: p.key,
        label: p.defaultLabel,
        subtitle: p.badge,
        tooltip: p.desc,
      })),
      onAdd: (id, remaining) => {
        if (remaining <= 0) setOpenMenu(null);
        onMovePlatform(id as PlatformChannelKey, 'shared');
      },
      onRemove: id => {
        onMovePlatform(id as PlatformChannelKey, 'personal');
      },
    },
    {
      popoverKey: 'platform:personal',
      title: '个人独立通道',
      alias: '（各成员独享会话）',
      oppositeTitle: '全局共享通道',
      addButtonLabel: '新增平台',
      emptyWhenAll: '暂无独立通道平台，点击右上角「新增平台」从全局共享通道移入',
      tone: 'teal',
      totalCount: platformPartition.allPersonal.length,
      unit: '项',
      items: platformPartition.personal.map(p => ({
        id: p.key,
        label: p.defaultLabel,
        subtitle: p.badge,
        tooltip: `${p.defaultLabel}（${p.badge}）· 关联：${p.relatedModules} · 点击右侧 × 移入全局共享通道`,
      })),
      candidates: platformPartition.allShared.map(p => ({
        id: p.key,
        label: p.defaultLabel,
        subtitle: p.badge,
        tooltip: p.desc,
      })),
      onAdd: (id, remaining) => {
        if (remaining <= 0) setOpenMenu(null);
        onMovePlatform(id as PlatformChannelKey, 'personal');
      },
      onRemove: id => {
        onMovePlatform(id as PlatformChannelKey, 'shared');
      },
    },
  ];

  const moduleLanes: DualLaneSpec[] = [
    {
      popoverKey: 'module:enabled',
      title: '全局开放模块',
      alias: '（成员按权限可用）',
      oppositeTitle: '全局已暂停模块',
      addButtonLabel: '恢复开放',
      emptyWhenAll: '当前无开放模块，点击右上角「恢复开放」从暂停区移回',
      tone: 'sky',
      totalCount: modulePartition.allEnabled.length,
      unit: '项',
      items: modulePartition.enabled.map(m => {
        const displayName = resolveModuleDisplayLabel(m.key, m.defaultLabel);
        return {
          id: m.key,
          label: displayName,
          subtitle: displayName !== m.defaultLabel ? m.defaultLabel : undefined,
          tooltip: `${displayName}：${m.desc} · 点击右侧 × 暂停对普通成员开放`,
        };
      }),
      candidates: modulePartition.allPaused.map(m => {
        const displayName = resolveModuleDisplayLabel(m.key, m.defaultLabel);
        return {
          id: m.key,
          label: displayName,
          subtitle: m.desc,
          tooltip: m.desc,
        };
      }),
      onAdd: (id, remaining) => {
        if (remaining <= 0) setOpenMenu(null);
        onMoveModule(id as BusinessModuleKey, true);
      },
      onRemove: id => {
        onMoveModule(id as BusinessModuleKey, false);
      },
    },
    {
      popoverKey: 'module:paused',
      title: '全局已暂停模块',
      alias: '（对成员隐藏拦截）',
      oppositeTitle: '全局开放模块',
      addButtonLabel: '暂停模块',
      emptyWhenAll: '暂无暂停模块，所有业务模块均正常开放；可点击右上角「暂停模块」从左侧移入',
      tone: 'amber',
      totalCount: modulePartition.allPaused.length,
      unit: '项',
      items: modulePartition.paused.map(m => {
        const displayName = resolveModuleDisplayLabel(m.key, m.defaultLabel);
        return {
          id: m.key,
          label: displayName,
          subtitle: displayName !== m.defaultLabel ? m.defaultLabel : undefined,
          tooltip: `${displayName}（已暂停）：${m.desc} · 点击右侧 × 恢复全局开放`,
        };
      }),
      candidates: modulePartition.allEnabled.map(m => {
        const displayName = resolveModuleDisplayLabel(m.key, m.defaultLabel);
        return {
          id: m.key,
          label: displayName,
          subtitle: m.desc,
          tooltip: m.desc,
        };
      }),
      onAdd: (id, remaining) => {
        if (remaining <= 0) setOpenMenu(null);
        onMoveModule(id as BusinessModuleKey, false);
      },
      onRemove: id => {
        onMoveModule(id as BusinessModuleKey, true);
      },
    },
  ];

  const renderLane = (lane: DualLaneSpec) => {
    const tone = LANE_TONE_STYLES[lane.tone];
    const isMenuOpen = openMenu === lane.popoverKey;
    return (
      <div
        key={lane.popoverKey}
        className={`flex flex-col min-w-0 rounded-xl border transition-colors ${tone.container}`}
        aria-label={lane.title}
      >
        {/* 泳道头 */}
        <div
          className={`flex items-center justify-between gap-2.5 px-3.5 py-2.5 border-b ${tone.head}`}
        >
          <div className="flex items-baseline gap-1.5 min-w-0 flex-wrap">
            <span className={`text-[13px] font-semibold whitespace-nowrap ${tone.title}`}>
              {lane.title}
            </span>
            {lane.alias && (
              <span className="text-[11.5px] font-normal text-slate-400 whitespace-nowrap">
                {lane.alias}
              </span>
            )}
            <span className="text-[12px] font-medium text-slate-500 tabular-nums whitespace-nowrap">
              {lane.totalCount} {lane.unit}
            </span>
          </div>

          <div className={`relative shrink-0 ${isMenuOpen ? 'z-30' : ''}`}>
            <button
              type="button"
              aria-haspopup="listbox"
              aria-expanded={isMenuOpen}
              aria-label={`${lane.addButtonLabel}到${lane.title}`}
              disabled={saving || lane.candidates.length === 0}
              onClick={() =>
                setOpenMenu(prev => (prev === lane.popoverKey ? null : lane.popoverKey))
              }
              className={`inline-flex items-center gap-1 h-[26px] px-2.5 rounded-md border border-slate-200/90 bg-white text-[11.5px] font-medium text-slate-600 whitespace-nowrap shrink-0 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${tone.addBtnHover}`}
            >
              <Plus className="w-3 h-3" aria-hidden="true" />
              <span>{lane.addButtonLabel}</span>
            </button>

            {isMenuOpen && (
              <div
                role="listbox"
                aria-label={`选择项目移入${lane.title}`}
                className="absolute right-0 top-[calc(100%+6px)] w-64 rounded-xl border border-slate-200/90 bg-white shadow-lg overflow-hidden z-40"
              >
                <div className="px-3 py-2 border-b border-slate-100 bg-slate-50/75 flex items-center justify-between gap-2 text-[11.5px]">
                  <span className="text-slate-500 truncate">从「{lane.oppositeTitle}」移入</span>
                  <button
                    type="button"
                    onClick={() => setOpenMenu(null)}
                    className="text-[#0086C4] font-medium hover:underline cursor-pointer shrink-0"
                  >
                    完成
                  </button>
                </div>
                <div className="max-h-60 overflow-y-auto p-1.5 space-y-0.5">
                  {lane.candidates.map(cand => (
                    <button
                      key={cand.id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      disabled={saving}
                      onClick={() => lane.onAdd(cand.id, lane.candidates.length - 1)}
                      className={`w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg text-left transition cursor-pointer disabled:opacity-50 ${tone.menuItemHover}`}
                    >
                      <div className="min-w-0">
                        <div className="text-[12.5px] font-medium text-[#18191C] truncate">
                          {cand.label}
                        </div>
                        {cand.subtitle && (
                          <div className="text-[11px] text-slate-400 truncate mt-0.5">
                            {cand.subtitle}
                          </div>
                        )}
                      </div>
                      <span
                        className={`inline-flex items-center gap-0.5 text-[11.5px] font-medium whitespace-nowrap shrink-0 ${tone.menuAction}`}
                      >
                        <Plus className="w-3 h-3" aria-hidden="true" />
                        移入
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 泳道内容区 */}
        <div className="flex-1 p-3 min-h-[72px] flex items-start">
          {lane.items.length > 0 ? (
            <div className="flex flex-wrap gap-2 w-full">
              {lane.items.map(item => (
                <span
                  key={item.id}
                  title={item.tooltip}
                  className={`inline-flex items-center gap-1.5 h-8 pl-3 pr-1.5 rounded-lg border border-slate-200/90 bg-white text-[12.5px] font-medium text-[#18191C] whitespace-nowrap transition-colors ${tone.chipHover}`}
                >
                  <span className="leading-none">{item.label}</span>
                  {item.subtitle && (
                    <span className="text-[11px] font-normal text-slate-400 leading-none">
                      · {item.subtitle}
                    </span>
                  )}
                  <button
                    type="button"
                    disabled={saving}
                    aria-label={`从${lane.title}移出${item.label}`}
                    title={`点击移出，将自动归入「${lane.oppositeTitle}」`}
                    onClick={() => lane.onRemove(item.id)}
                    className="inline-flex items-center justify-center w-5 h-5 rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <X className="w-3 h-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-[12px] leading-relaxed text-slate-400">
              {trimmedQuery ? `暂无匹配「${trimmedQuery}」的配置项` : lane.emptyWhenAll}
            </p>
          )}
        </div>
      </div>
    );
  };

  return (
    <div
      ref={containerRef}
      className="divide-y divide-slate-100"
      data-testid="channel-module-allocation-panel"
    >
      {/* 分区 1：数据源通道分配 */}
      <section className="p-4 sm:p-5 space-y-3" aria-label="数据源通道分配">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <h2 className="text-[13.5px] font-semibold text-[#18191C] whitespace-nowrap">
              数据源通道分配
            </h2>
            <span className="text-slate-300" aria-hidden="true">·</span>
            {saving ? (
              <span className="inline-flex items-center gap-1 text-[12px] text-[#0086C4] font-medium">
                <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                同步保存中…
              </span>
            ) : (
              <span className="text-[12px] text-slate-500 tabular-nums flex items-center gap-1.5">
                <span className="text-[#0369A1] font-medium">
                  全局共享 {platformPartition.allShared.length} 项
                </span>
                <span className="text-slate-300" aria-hidden="true">·</span>
                <span className="text-[#0F766E] font-medium">
                  个人独立 {platformPartition.allPersonal.length} 项
                </span>
              </span>
            )}
          </div>
          <span className="text-[11.5px] text-slate-400">
            以下为全局平台默认归属（未在左侧展示的平台默认归入个人独立通道，移入左侧后可在「成员权限」中按人授权）
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 items-stretch">
          {platformLanes.map(renderLane)}
        </div>
      </section>

      {/* 分区 2：业务模块全局开放控制 */}
      <section className="p-4 sm:p-5 space-y-3" aria-label="业务模块全局开放控制">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <h2 className="text-[13.5px] font-semibold text-[#18191C] whitespace-nowrap">
              业务模块全局开放控制
            </h2>
            <span className="text-slate-300" aria-hidden="true">·</span>
            {saving ? (
              <span className="inline-flex items-center gap-1 text-[12px] text-[#0086C4] font-medium">
                <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                同步保存中…
              </span>
            ) : (
              <span className="text-[12px] text-slate-500 tabular-nums flex items-center gap-1.5">
                <span className="text-[#0369A1] font-medium">
                  全局开放 {modulePartition.allEnabled.length} 项
                </span>
                <span className="text-slate-300" aria-hidden="true">·</span>
                <span
                  className={
                    modulePartition.allPaused.length > 0
                      ? 'text-amber-700 font-medium'
                      : 'text-slate-400'
                  }
                >
                  已暂停 {modulePartition.allPaused.length} 项
                </span>
              </span>
            )}
          </div>
          <span className="text-[11.5px] text-slate-400">
            移入右侧暂停区的模块将同步对所有普通成员隐藏与拦截，主机管理员仍可随时访问与恢复
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 items-stretch">
          {moduleLanes.map(renderLane)}
        </div>
      </section>
    </div>
  );
}
