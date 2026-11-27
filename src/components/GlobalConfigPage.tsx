import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Layers,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Type,
  X,
} from 'lucide-react';
import {
  fetchGlobalWorkbenchConfig,
  resetGlobalWorkbenchConfig,
  updateGlobalWorkbenchConfig,
} from '../lib/workspaceAuth';
import {
  cloneGlobalWorkbenchConfig,
  countGlobalConfigCustomizations,
  DATASET_CONFIG_CATALOG,
  MODULE_GROUP_CATALOG,
  normalizeGlobalWorkbenchConfig,
  setGlobalWorkbenchConfig,
  SUBMODULE_CATALOG,
  useGlobalWorkbenchConfig,
  type GlobalWorkbenchConfig,
} from '../lib/workbenchConfig';

export type GlobalConfigTab = 'names' | 'datasets';

interface GlobalConfigPageProps {
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

const INPUT_BASE =
  'w-full h-8 rounded-lg border border-slate-200/90 bg-white px-2.5 text-[12.5px] text-[#18191C] placeholder:text-[#9499A0] transition duration-150 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15';

function namingSnapshotKey(cfg: GlobalWorkbenchConfig): string {
  const norm = normalizeGlobalWorkbenchConfig(cfg);
  return JSON.stringify({
    module_names: norm.module_names,
    dataset_overrides: norm.dataset_overrides,
  });
}

export function GlobalConfigPage({ onToast }: GlobalConfigPageProps) {
  const liveConfig = useGlobalWorkbenchConfig();
  const [draft, setDraft] = useState<GlobalWorkbenchConfig>(() =>
    cloneGlobalWorkbenchConfig(liveConfig),
  );
  const [activeTab, setActiveTab] = useState<GlobalConfigTab>('names');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmResetNaming, setConfirmResetNaming] = useState(false);

  const onToastRef = useRef(onToast);
  onToastRef.current = onToast;

  const isDirty = useMemo(
    () => namingSnapshotKey(draft) !== namingSnapshotKey(liveConfig),
    [draft, liveConfig],
  );

  // Sync incoming external liveConfig only when naming draft has no unsaved edits
  const isDirtyRef = useRef(isDirty);
  isDirtyRef.current = isDirty;
  useEffect(() => {
    if (!isDirtyRef.current) {
      setDraft(cloneGlobalWorkbenchConfig(liveConfig));
    }
  }, [liveConfig]);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchGlobalWorkbenchConfig();
      if (res?.config) {
        const synced = setGlobalWorkbenchConfig(res.config);
        setDraft(cloneGlobalWorkbenchConfig(synced));
      }
      onToastRef.current('已刷新全局名称配置', 'info');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '刷新全局配置失败', 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchGlobalWorkbenchConfig()
      .then(res => {
        if (res?.config && !isDirtyRef.current) {
          const synced = setGlobalWorkbenchConfig(res.config);
          setDraft(cloneGlobalWorkbenchConfig(synced));
        }
      })
      .catch(() => {});
  }, []);

  const stats = useMemo(() => countGlobalConfigCustomizations(draft), [draft]);

  const q = searchQuery.trim().toLowerCase();

  const filteredGroups = useMemo(() => {
    if (!q) return MODULE_GROUP_CATALOG;
    return MODULE_GROUP_CATALOG.filter(item => {
      const cur = draft.module_names.groups[item.id] || '';
      return `${item.defaultLabel} ${item.id} ${cur} ${item.desc}`.toLowerCase().includes(q);
    });
  }, [q, draft.module_names.groups]);

  const groupedSubmodules = useMemo(() => {
    return MODULE_GROUP_CATALOG.map(group => {
      const items = SUBMODULE_CATALOG.filter(sub => {
        if (sub.groupId !== group.id) return false;
        if (!q) return true;
        const cur = draft.module_names.items[sub.id] || '';
        return `${sub.defaultLabel} ${sub.id} ${cur} ${sub.hint} ${group.defaultLabel}`
          .toLowerCase()
          .includes(q);
      });
      return { group, items };
    }).filter(entry => entry.items.length > 0);
  }, [q, draft.module_names.items]);

  const groupedDatasets = useMemo(() => {
    const categories: { key: string; label: string; items: typeof DATASET_CONFIG_CATALOG }[] = [];
    const byKey = new Map<string, (typeof categories)[number]>();
    for (const ds of DATASET_CONFIG_CATALOG) {
      const ov = draft.dataset_overrides[ds.id];
      const matches =
        !q ||
        `${ds.defaultTitle} ${ds.defaultDesc} ${ds.id} ${ds.categoryLabel} ${ov?.title || ''} ${ov?.desc || ''}`
          .toLowerCase()
          .includes(q);
      if (!matches) continue;
      let bucket = byKey.get(ds.category);
      if (!bucket) {
        bucket = { key: ds.category, label: ds.categoryLabel, items: [] };
        byKey.set(ds.category, bucket);
        categories.push(bucket);
      }
      bucket.items.push(ds);
    }
    return categories;
  }, [q, draft.dataset_overrides]);

  const setGroupName = (groupId: string, val: string) => {
    setDraft(prev => {
      const nextGroups = { ...prev.module_names.groups };
      if (!val.trim()) {
        delete nextGroups[groupId];
      } else {
        nextGroups[groupId] = val;
      }
      return {
        ...prev,
        module_names: {
          ...prev.module_names,
          groups: nextGroups,
        },
      };
    });
  };

  const setSubmoduleName = (itemId: string, val: string) => {
    setDraft(prev => {
      const nextItems = { ...prev.module_names.items };
      if (!val.trim()) {
        delete nextItems[itemId];
      } else {
        nextItems[itemId] = val;
      }
      return {
        ...prev,
        module_names: {
          ...prev.module_names,
          items: nextItems,
        },
      };
    });
  };

  const setDatasetOverrideField = (
    datasetId: string,
    field: 'title' | 'desc',
    val: string,
  ) => {
    setDraft(prev => {
      const current = prev.dataset_overrides[datasetId] || {};
      const nextEntry = {
        ...current,
        [field]: val,
      };
      const cleanTitle = (nextEntry.title || '').trim();
      const cleanDesc = (nextEntry.desc || '').trim();
      const nextOverrides = { ...prev.dataset_overrides };
      if (!cleanTitle && !cleanDesc) {
        delete nextOverrides[datasetId];
      } else {
        nextOverrides[datasetId] = {
          ...(nextEntry.title !== undefined ? { title: nextEntry.title } : {}),
          ...(nextEntry.desc !== undefined ? { desc: nextEntry.desc } : {}),
        };
      }
      return {
        ...prev,
        dataset_overrides: nextOverrides,
      };
    });
  };

  const resetDatasetOverride = (datasetId: string) => {
    setDraft(prev => {
      const nextOverrides = { ...prev.dataset_overrides };
      delete nextOverrides[datasetId];
      return {
        ...prev,
        dataset_overrides: nextOverrides,
      };
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const normalized = normalizeGlobalWorkbenchConfig(draft);
      const res = await updateGlobalWorkbenchConfig({
        module_names: normalized.module_names,
        dataset_overrides: normalized.dataset_overrides,
      });
      const synced = setGlobalWorkbenchConfig(res.config);
      setDraft(cloneGlobalWorkbenchConfig(synced));
      onToast('全局名称配置已保存并同步至所有终端', 'success');
    } catch (err) {
      onToast(err instanceof Error ? err.message : '保存全局配置失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmResetNaming = async () => {
    setSaving(true);
    try {
      const res = await resetGlobalWorkbenchConfig('naming');
      const synced = setGlobalWorkbenchConfig(res.config);
      setDraft(cloneGlobalWorkbenchConfig(synced));
      setConfirmResetNaming(false);
      onToast('已恢复全部默认模块与资料名称', 'success');
    } catch (err) {
      onToast(err instanceof Error ? err.message : '恢复默认名称失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const totalNamingCustomCount = stats.names + stats.datasets;

  return (
    <div className="w-full space-y-3 pb-6" data-testid="global-config-page">
      {/* 紧凑单行顶栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-0.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0">
          <h1 className="text-[17px] font-semibold tracking-tight text-[#18191C] leading-none">
            全局配置
          </h1>
          <span
            className="hidden sm:inline-block h-3.5 w-px bg-slate-200 self-center"
            aria-hidden="true"
          />
          <p className="text-[12px] text-[#61666D] tabular-nums flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span>
              模块名称自定义 <strong className="font-semibold text-[#18191C]">{stats.names}</strong> 项
            </span>
            <span className="text-slate-300" aria-hidden="true">·</span>
            <span>
              资料文案自定义 <strong className="font-semibold text-[#18191C]">{stats.datasets}</strong> 项
            </span>
            {isDirty && (
              <>
                <span className="text-slate-300" aria-hidden="true">·</span>
                <span className="text-amber-600 font-medium">有未保存修改</span>
              </>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            type="button"
            disabled={loading || saving}
            onClick={() => void handleRefresh()}
            aria-label="刷新全局配置"
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#4E5969] transition cursor-pointer disabled:opacity-55 whitespace-nowrap shrink-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            type="button"
            disabled={saving || (totalNamingCustomCount === 0 && !isDirty)}
            onClick={() => setConfirmResetNaming(true)}
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-slate-600 transition cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            恢复默认名称
          </button>
          {isDirty && (
            <button
              type="button"
              disabled={saving}
              onClick={() => setDraft(cloneGlobalWorkbenchConfig(liveConfig))}
              className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-slate-600 transition cursor-pointer whitespace-nowrap shrink-0"
            >
              放弃修改
            </button>
          )}
          <button
            type="button"
            disabled={!isDirty || saving}
            onClick={() => void handleSave()}
            className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer shadow-xs disabled:opacity-45 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? '保存中…' : '保存并全局同步'}
          </button>
        </div>
      </div>

      {/* 单层高纯净白主容器 */}
      <div className="rounded-xl border border-slate-200/85 bg-white overflow-hidden">
        {/* 顶部标签与搜索栏 */}
        <div className="px-3.5 py-2 border-b border-slate-100 bg-slate-50/45 flex flex-wrap items-center justify-between gap-2.5">
          <div
            className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-slate-100/85 border border-slate-200/60"
            role="tablist"
            aria-label="全局配置分类"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'names'}
              onClick={() => setActiveTab('names')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer whitespace-nowrap ${
                activeTab === 'names'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              <Layers className="w-3.5 h-3.5 text-slate-400" />
              模块与子模块名称
              {stats.names > 0 && (
                <span className="text-[11px] tabular-nums text-[#0086C4] font-semibold">
                  {stats.names}
                </span>
              )}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'datasets'}
              onClick={() => setActiveTab('datasets')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer whitespace-nowrap ${
                activeTab === 'datasets'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              <Type className="w-3.5 h-3.5 text-slate-400" />
              资料名称与副标题
              {stats.datasets > 0 && (
                <span className="text-[11px] tabular-nums text-[#0086C4] font-semibold">
                  {stats.datasets}
                </span>
              )}
            </button>
          </div>

          <div className="relative w-56 sm:w-64">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="搜索模块或资料名称..."
              aria-label="搜索全局配置项"
              className={`${INPUT_BASE} pl-8 pr-7`}
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="清空配置搜索"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* ===================== 标签页 1：模块与子模块名称 ===================== */}
        {activeTab === 'names' && (
          <div className="divide-y divide-slate-100">
            <section className="p-4 sm:p-5 space-y-3" aria-label="一级模块分组名称">
              <div>
                <h2 className="text-[13.5px] font-semibold text-[#18191C]">
                  一级模块分组名称
                </h2>
                <p className="text-[11.5px] text-slate-500 mt-0.5">
                  修改后同步作用于左侧导航分组标题、顶部面包屑以及用户权限分配展示名称
                </p>
              </div>

              {filteredGroups.length === 0 ? (
                <div className="py-6 text-center text-[12.5px] text-slate-400">
                  未找到匹配的一级分组
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  {filteredGroups.map(group => {
                    const currentVal = draft.module_names.groups[group.id] ?? '';
                    const isCustomized =
                      Boolean(currentVal.trim()) && currentVal.trim() !== group.defaultLabel;
                    return (
                      <div
                        key={group.id}
                        className="rounded-xl border border-slate-200/80 p-3 space-y-2 bg-white"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12px] font-semibold text-[#18191C]">
                            默认：{group.defaultLabel}
                          </span>
                          {isCustomized && (
                            <button
                              type="button"
                              onClick={() => setGroupName(group.id, '')}
                              className="text-[11px] font-medium text-[#0086C4] hover:underline cursor-pointer"
                            >
                              还原
                            </button>
                          )}
                        </div>
                        <input
                          type="text"
                          value={currentVal}
                          onChange={e => setGroupName(group.id, e.target.value)}
                          placeholder={group.defaultLabel}
                          aria-label={`${group.defaultLabel}显示名称`}
                          className={INPUT_BASE}
                        />
                        <p className="text-[11px] text-slate-400">{group.desc}</p>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="p-4 sm:p-5 space-y-4" aria-label="子模块显示名称">
              <div>
                <h2 className="text-[13.5px] font-semibold text-[#18191C]">
                  子模块显示名称
                </h2>
                <p className="text-[11.5px] text-slate-500 mt-0.5">
                  留空即恢复使用默认名称；保存后所有终端导航与页头上下文同步更新
                </p>
              </div>

              {groupedSubmodules.length === 0 ? (
                <div className="py-8 text-center text-[12.5px] text-slate-400">
                  未找到匹配的子模块名称
                </div>
              ) : (
                <div className="space-y-4">
                  {groupedSubmodules.map(({ group, items }) => (
                    <div key={group.id} className="space-y-2">
                      <div className="text-[11.5px] font-semibold text-slate-500 px-0.5">
                        {draft.module_names.groups[group.id]?.trim() || group.defaultLabel}（{items.length}）
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                        {items.map(sub => {
                          const currentVal = draft.module_names.items[sub.id] ?? '';
                          const isCustomized =
                            Boolean(currentVal.trim()) && currentVal.trim() !== sub.defaultLabel;
                          return (
                            <div
                              key={sub.id}
                              className="rounded-lg border border-slate-200/80 px-3 py-2.5 space-y-1.5 bg-white"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-[12px] font-medium text-slate-600 truncate">
                                  默认：{sub.defaultLabel}
                                </span>
                                {isCustomized && (
                                  <button
                                    type="button"
                                    onClick={() => setSubmoduleName(sub.id, '')}
                                    className="text-[11px] font-medium text-[#0086C4] hover:underline cursor-pointer shrink-0"
                                  >
                                    还原
                                  </button>
                                )}
                              </div>
                              <input
                                type="text"
                                value={currentVal}
                                onChange={e => setSubmoduleName(sub.id, e.target.value)}
                                placeholder={sub.defaultLabel}
                                aria-label={`${sub.defaultLabel}子模块名称`}
                                className={INPUT_BASE}
                              />
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {/* ===================== 标签页 2：资料名称与副标题 ===================== */}
        {activeTab === 'datasets' && (
          <div className="p-4 sm:p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-[13.5px] font-semibold text-[#18191C]">
                  数据采集资料项与业务报表卡片文案
                </h2>
                <p className="text-[11.5px] text-slate-500 mt-0.5">
                  修改「01 选择资料」中各资料卡片的主名称及副标题说明；留空即自动沿用系统默认文案
                </p>
              </div>
              <span className="text-[11.5px] text-slate-400 tabular-nums">
                共 {DATASET_CONFIG_CATALOG.length} 项资料
              </span>
            </div>

            {groupedDatasets.length === 0 ? (
              <div className="py-10 text-center text-[12.5px] text-slate-400">
                未找到匹配的资料项
              </div>
            ) : (
              <div className="space-y-5">
                {groupedDatasets.map(cat => (
                  <div key={cat.key} className="space-y-2">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
                      <span className="text-[12px] font-semibold text-[#18191C]">
                        {cat.label}
                      </span>
                      <span className="text-[11px] text-slate-400 tabular-nums">
                        {cat.items.length} 项
                      </span>
                    </div>

                    <div className="divide-y divide-slate-100 rounded-xl border border-slate-200/80 overflow-hidden">
                      {cat.items.map(ds => {
                        const override = draft.dataset_overrides[ds.id];
                        const curTitle = override?.title ?? '';
                        const curDesc = override?.desc ?? '';
                        const hasOverride =
                          (Boolean(curTitle.trim()) && curTitle.trim() !== ds.defaultTitle) ||
                          (Boolean(curDesc.trim()) && curDesc.trim() !== ds.defaultDesc);

                        return (
                          <div
                            key={ds.id}
                            className="p-3 bg-white hover:bg-slate-50/45 grid grid-cols-1 lg:grid-cols-[200px_220px_minmax(0,1fr)_auto] gap-2.5 items-center"
                          >
                            <div className="min-w-0">
                              <div className="text-[12.5px] font-semibold text-[#18191C] truncate">
                                {ds.defaultTitle}
                              </div>
                              <div className="text-[11px] text-slate-400 truncate mt-0.5">
                                {ds.scopeTag} · {ds.id}
                              </div>
                            </div>

                            <input
                              type="text"
                              value={curTitle}
                              onChange={e => setDatasetOverrideField(ds.id, 'title', e.target.value)}
                              placeholder={`默认标题：${ds.defaultTitle}`}
                              aria-label={`${ds.defaultTitle}名称`}
                              className={INPUT_BASE}
                            />

                            <input
                              type="text"
                              value={curDesc}
                              onChange={e => setDatasetOverrideField(ds.id, 'desc', e.target.value)}
                              placeholder={`默认副标题：${ds.defaultDesc}`}
                              aria-label={`${ds.defaultTitle}副标题`}
                              className={INPUT_BASE}
                            />

                            <div className="flex items-center justify-end lg:w-12">
                              {hasOverride ? (
                                <button
                                  type="button"
                                  onClick={() => resetDatasetOverride(ds.id)}
                                  className="text-[11.5px] font-medium text-[#0086C4] hover:underline cursor-pointer"
                                >
                                  还原
                                </button>
                              ) : (
                                <span className="text-[11px] text-slate-300">默认</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ===================== 恢复默认名称确认弹窗 ===================== */}
      {confirmResetNaming &&
        createPortal(
          <div
            className="fixed inset-0 z-[1000] flex items-center justify-center bg-slate-900/40 backdrop-blur-[2px] p-4"
            role="dialog"
            aria-modal="true"
            aria-label="确认恢复默认名称"
          >
            <div className="w-full max-w-sm rounded-2xl bg-white border border-slate-200/90 shadow-xl p-5 space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-amber-50 border border-amber-200/80 text-amber-600 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-4.5 h-4.5" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-[14px] font-semibold text-[#18191C]">
                    确认恢复全部默认名称？
                  </h3>
                  <p className="text-[12px] text-slate-500 leading-relaxed">
                    将清除所有自定义的一二级模块名称以及资料主副标题文案，不影响「用户权限分配」中已设置的通道与模块分配。
                  </p>
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => setConfirmResetNaming(false)}
                  className="h-8 px-3.5 rounded-lg border border-slate-200 text-[12px] font-medium text-slate-600 hover:bg-slate-50 cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void handleConfirmResetNaming()}
                  className="h-8 px-4 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-55"
                >
                  {saving ? '处理中…' : '确认恢复默认'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
