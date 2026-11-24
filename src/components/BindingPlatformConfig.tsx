import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Plus, Search, X } from 'lucide-react';
import {
  BINDING_PLATFORM_OPTIONS,
  applyBatchBindingPlatform,
  applyCityBindingPlatform,
  partitionCitiesByBindingPlatform,
} from '../lib/reportBuilder';

export interface BindingCityOption {
  id: string;
  name: string;
  disabled?: boolean;
}

export interface BindingPlatformConfigProps {
  cities: BindingCityOption[];
  selectedCities: string[];
  bindingPlatforms?: Record<string, string>;
  onChange?: (next: Record<string, string>) => void;
  saving?: boolean;
  disabled?: boolean;
}

type PlatformKey = '本来人力' | '商翼';

const PLATFORM_LANES: ReadonlyArray<{
  key: PlatformKey;
  oppositeKey: PlatformKey;
  title: string;
  oppositeTitle: string;
  tone: 'benlai' | 'shangyi';
}> = [
  {
    key: '本来人力',
    oppositeKey: '商翼',
    title: '本来人力',
    oppositeTitle: '天津商翼',
    tone: 'benlai',
  },
  {
    key: '商翼',
    oppositeKey: '本来人力',
    title: '天津商翼',
    oppositeTitle: '本来人力',
    tone: 'shangyi',
  },
];

function platformToneClass(value: string): string {
  if (value === '本来人力') return ' is-platform-benlai';
  if (value === '商翼') return ' is-platform-shangyi';
  return '';
}

export function BindingPlatformConfig({
  cities,
  selectedCities,
  bindingPlatforms,
  onChange,
  saving = false,
  disabled = false,
}: BindingPlatformConfigProps) {
  const [addLane, setAddLane] = useState<PlatformKey | null>(null);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const visibleCities = useMemo(() => {
    const keyword = query.trim();
    if (!keyword) return cities;
    return cities.filter(c => c.name.includes(keyword));
  }, [cities, query]);

  const allPartition = useMemo(
    () => partitionCitiesByBindingPlatform(cities, bindingPlatforms),
    [cities, bindingPlatforms],
  );

  const visiblePartition = useMemo(
    () => partitionCitiesByBindingPlatform(visibleCities, bindingPlatforms),
    [visibleCities, bindingPlatforms],
  );

  const controlsDisabled = disabled || saving || !onChange;

  const activeSelectedCities = useMemo(() => {
    const known = new Set(cities.map(c => c.name));
    return selectedCities.filter(name => known.has(name));
  }, [cities, selectedCities]);

  useEffect(() => {
    if (!addLane) return;
    const handleOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setAddLane(null);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAddLane(null);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [addLane]);

  useEffect(() => {
    if (controlsDisabled) {
      setAddLane(null);
    }
  }, [controlsDisabled]);

  const handleMoveCity = (
    cityName: string,
    targetPlatform: PlatformKey,
    closeIfLast = false,
    remainingAfterMove = 1,
  ) => {
    if (controlsDisabled) return;
    if (closeIfLast && remainingAfterMove <= 0) {
      setAddLane(null);
    }
    onChange(applyCityBindingPlatform(bindingPlatforms, cityName, targetPlatform));
  };

  const handleBatchApply = (platformValue: PlatformKey) => {
    if (controlsDisabled || !activeSelectedCities.length) return;
    setAddLane(null);
    onChange(applyBatchBindingPlatform(bindingPlatforms, activeSelectedCities, platformValue));
  };

  return (
    <section
      ref={containerRef}
      className="rb-bind-section"
      aria-label="绑定平台配置（可选）"
    >
      <div className="rb-bind-header">
        <div className="rb-bind-header__left">
          <h3 className="rb-bind-title">绑定平台配置（可选）</h3>
          <span className="rb-bind-sep" aria-hidden="true">·</span>
          {saving ? (
            <span className="rb-bind-meta is-saving">
              <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              保存中…
            </span>
          ) : (
            <span className="rb-bind-meta tabular-nums">
              <span className={allPartition.benlai.length > 0 ? 'is-benlai' : undefined}>
                本来人力 {allPartition.benlai.length} 城
              </span>
              <span className="rb-bind-sep" aria-hidden="true">·</span>
              <span className={allPartition.shangyi.length > 0 ? 'is-shangyi' : undefined}>
                天津商翼 {allPartition.shangyi.length} 城
              </span>
            </span>
          )}
        </div>

        <div className="rb-bind-header__right">
          {activeSelectedCities.length > 0 ? (
            <div className="rb-bind-batch" role="group" aria-label="已选城市批量绑定平台">
              <span className="rb-bind-batch__label tabular-nums">
                已勾 {activeSelectedCities.length} 城设为
              </span>
              <div className="rb-bind-batch__actions">
                {BINDING_PLATFORM_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    type="button"
                    className={`rb-bind-batch__btn${platformToneClass(opt.value)}`}
                    title={`将已勾选的 ${activeSelectedCities.length} 个城市统一归入「${opt.label}」`}
                    disabled={controlsDisabled}
                    onClick={() => handleBatchApply(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <span className="rb-bind-caption">
              当前未勾选处理城市（以下为全局各城默认归属，未在左侧展示的城市默认归入天津商翼 / 白泽商翼）
            </span>
          )}
        </div>
      </div>

      {cities.length > 18 && (
        <div className="rb-bind-search">
          <Search size={13} aria-hidden="true" />
          <input
            type="text"
            aria-label="筛选配置城市"
            placeholder="输入城市名称快速定位…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {query && (
            <button
              type="button"
              className="rb-filter-clear"
              aria-label="清除城市配置筛选"
              onClick={() => setQuery('')}
            >
              <X size={12} />
            </button>
          )}
        </div>
      )}

      <div className="rb-bind-lanes">
        {PLATFORM_LANES.map(lane => {
          const laneCities =
            lane.key === '本来人力' ? visiblePartition.benlai : visiblePartition.shangyi;
          const totalLaneCount =
            lane.key === '本来人力' ? allPartition.benlai.length : allPartition.shangyi.length;
          const selectedInLaneCount =
            activeSelectedCities.length > 0
              ? (lane.key === '本来人力' ? allPartition.benlai : allPartition.shangyi).filter(c =>
                  activeSelectedCities.includes(c.name),
                ).length
              : 0;
          const candidateCities =
            lane.key === '本来人力' ? allPartition.shangyi : allPartition.benlai;
          const isAddOpen = addLane === lane.key;

          return (
            <div
              key={lane.key}
              className={`rb-bind-lane is-${lane.tone}`}
              aria-label={`${lane.title}绑定城市`}
            >
              <div className="rb-bind-lane__head">
                <div className="rb-bind-lane__heading">
                  <span className="rb-bind-lane__title">
                    {lane.title}
                    {lane.key === '商翼' && (
                      <span className="rb-bind-lane__alias" title="对应顶栏平台连接中的「白泽商翼」">
                        （白泽商翼）
                      </span>
                    )}
                  </span>
                  <span className="rb-bind-lane__count tabular-nums">
                    {totalLaneCount} 城
                    {activeSelectedCities.length > 0 && ` · 本次已选 ${selectedInLaneCount} 城`}
                  </span>
                </div>

                <div className={`rb-bind-add-wrap${isAddOpen ? ' is-open' : ''}`}>
                  <button
                    type="button"
                    className="rb-bind-add-btn"
                    aria-haspopup="listbox"
                    aria-expanded={isAddOpen}
                    aria-label={`新增城市到${lane.title}`}
                    disabled={controlsDisabled || candidateCities.length === 0}
                    onClick={() => setAddLane(prev => (prev === lane.key ? null : lane.key))}
                  >
                    <Plus size={12} aria-hidden="true" />
                    <span>新增城市</span>
                  </button>

                  {isAddOpen && (
                    <div
                      className="rb-bind-menu is-align-right is-add-menu"
                      role="listbox"
                      aria-label={`选择城市新增到${lane.title}`}
                    >
                      <div className="rb-bind-menu__head-row">
                        <span>从「{lane.oppositeTitle}」移入</span>
                        <button
                          type="button"
                          className="rb-bind-menu__done"
                          onClick={() => setAddLane(null)}
                        >
                          完成
                        </button>
                      </div>
                      <div className="rb-bind-menu__scroll">
                        {candidateCities.map(city => (
                          <button
                            key={city.id}
                            type="button"
                            role="option"
                            aria-selected={false}
                            className={`rb-bind-menu__item${platformToneClass(lane.key)}`}
                            onClick={() =>
                              handleMoveCity(
                                city.name,
                                lane.key,
                                true,
                                candidateCities.length - 1,
                              )
                            }
                          >
                            <span className="rb-bind-menu__label">{city.name}</span>
                            <span className="rb-bind-menu__action">
                              <Plus size={12} aria-hidden="true" />
                              移入
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="rb-bind-lane__body">
                {laneCities.length > 0 ? (
                  <div className="rb-bind-chip-list">
                    {laneCities.map(city => {
                      const isCityActive =
                        activeSelectedCities.length === 0 ||
                        activeSelectedCities.includes(city.name);
                      return (
                        <span
                          key={city.id}
                          className={`rb-bind-tag is-platform-${lane.tone}${
                            activeSelectedCities.length > 0
                              ? isCityActive
                                ? ' is-selected-city'
                                : ' is-unselected-city'
                              : ''
                          }`}
                          title={
                            activeSelectedCities.length > 0
                              ? isCityActive
                                ? `${city.name}（已纳入本次报表处理范围）`
                                : `${city.name}（未勾选，本次执行不处理）`
                              : `${city.name}（默认归属${lane.title}）`
                          }
                        >
                          <span className="rb-bind-tag__name">{city.name}</span>
                          <button
                            type="button"
                            className="rb-bind-tag__remove"
                            aria-label={`从${lane.title}删除${city.name}`}
                            title={`删除后将自动归入「${lane.oppositeTitle}」`}
                            disabled={controlsDisabled}
                            onClick={() => handleMoveCity(city.name, lane.oppositeKey)}
                          >
                            <X size={12} aria-hidden="true" />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                ) : (
                  <p className="rb-bind-lane__empty">
                    {query.trim()
                      ? `暂无匹配「${query.trim()}」的城市`
                      : `暂无绑定城市，点击右上角「新增城市」从${lane.oppositeTitle}移入`}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
