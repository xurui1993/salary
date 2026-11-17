import React from 'react';
import { ChevronDown, ChevronRight, Layers } from 'lucide-react';
import { CityDeductionAmounts, DeductionBentoGroups } from './CityDeductionAmounts';
import { ProblemRuleEditor } from './ProblemRuleEditor';
import type { DeductionEntry } from './DeductionAmounts';
import { fillUnconfigured } from '../lib/deductionBulk';
import {
  buildDeductionCategories,
  hasNonZeroDeduction,
  summarizeStationRow,
  type CityCardGroup,
  type DeductionCategoryId,
  type ProblemRuleItem,
} from '../lib/deductionCategories';

interface CityStationAccordionCardProps {
  group: CityCardGroup;
  allEntries: DeductionEntry[];
  columns: string[];
  activeCategory: DeductionCategoryId;
  visibleColumns: string[];
  expanded: boolean;
  expandedStations: Set<string>;
  selectedStations: Set<string>;
  disabled: boolean;
  onToggleCity: (cityId: string) => void;
  onToggleStation: (stationKey: string) => void;
  onToggleAllCityStations: (stationKeys: string[], open: boolean) => void;
  onToggleSelectStation: (stationKey: string, checked: boolean) => void;
  onUpdateCity: (updated: DeductionEntry) => void;
  onApplyCityToStations: (cityEntry: DeductionEntry) => void;
  onUpdateStation: (updated: DeductionEntry) => void;
  onBulkUpdateStations: (updatedEntries: DeductionEntry[]) => void;
}

export function CityStationAccordionCard({
  group,
  allEntries,
  columns,
  activeCategory,
  visibleColumns,
  expanded,
  expandedStations,
  selectedStations,
  disabled,
  onToggleCity,
  onToggleStation,
  onToggleAllCityStations,
  onToggleSelectStation,
  onUpdateCity,
  onApplyCityToStations,
  onUpdateStation,
  onBulkUpdateStations,
}: CityStationAccordionCardProps) {
  const { summary, cityEntry, stations } = group;
  const total = summary.totalStations;
  const pct = total > 0 ? Math.round((summary.configuredStations / total) * 100) : 0;
  const allDone = total > 0 && summary.pendingStations === 0;
  const anyStationOpen = stations.some(s => expandedStations.has(s.key));
  const categories = buildDeductionCategories(columns).filter(
    cat => activeCategory === 'all' || cat.id === activeCategory,
  );

  const cityProblemRules: ProblemRuleItem[] = ((cityEntry as any)?.problem_rules || []) as ProblemRuleItem[];
  const stationProblemTotal = stations.reduce(
    (sum, s) => sum + (((s as any)?.problem_rules || []).length || 0),
    0,
  );
  const totalKeywordRules = cityProblemRules.length + stationProblemTotal;

  const citySummaryText = cityEntry
    ? summarizeStationRow(cityEntry, visibleColumns)
    : '暂无城市默认';

  const statusLabel = (entry: DeductionEntry) => {
    if (entry.edited) return { text: '已调整待保存', cls: 'is-edited' };
    if (entry.station_override) return { text: '站点独立规则', cls: 'is-override' };
    if (entry.inherited_city) return { text: '沿用城市默认', cls: 'is-ready' };
    if (entry.configured) return { text: '已配置', cls: 'is-ready' };
    if (entry.legacy) return { text: '旧配置待核对', cls: 'is-pending' };
    return { text: '待配置', cls: 'is-pending' };
  };

  return (
    <section
      className={`wbx-city-accordion ${expanded ? 'is-open' : ''} ${allDone ? 'is-complete' : ''}`}
      aria-label={`${summary.cityName} 扣款规则折叠卡片`}
    >
      <button
        type="button"
        className="wbx-city-accordion__head"
        aria-expanded={expanded}
        onClick={() => onToggleCity(summary.cityId)}
      >
        <div className="wbx-city-card__top">
          <div className="wbx-city-card__identity">
            <strong>{summary.cityName}</strong>
            <span className="wbx-city-accordion__count tabular-nums">
              {summary.totalStations} 个站点
            </span>
          </div>
          <span className="wbx-city-accordion__action-hint">
            <span>{expanded ? '收起明细' : '查看扣款'}</span>
            <span className="wbx-city-accordion__chevron" aria-hidden="true">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          </span>
        </div>

        <div className="wbx-city-accordion__title-row">
          <span
            className={`wbx-city-accordion__default-tag ${
              summary.cityDefaultEdited
                ? 'is-edited'
                : summary.cityDefaultConfigured
                  ? 'is-ready'
                  : 'is-pending'
            }`}
          >
            {summary.cityDefaultEdited
              ? '城市默认已调整'
              : summary.cityDefaultConfigured
                ? '城市默认已设'
                : '待设城市默认'}
          </span>
          <span className="wbx-deduction-meta-sep" aria-hidden="true">·</span>
          {summary.overrideStations > 0 ? (
            <span className="wbx-city-accordion__override tabular-nums">
              {summary.overrideStations} 站例外
            </span>
          ) : (
            <span className="wbx-city-accordion__count">全站统一口径</span>
          )}
          <span className="wbx-deduction-meta-sep" aria-hidden="true">·</span>
          {totalKeywordRules > 0 ? (
            <span className="wbx-city-accordion__kw-tag tabular-nums">
              关键词规则 {totalKeywordRules} 条
            </span>
          ) : (
            <span className="wbx-city-accordion__count">无关键词规则</span>
          )}
        </div>

        <div className="wbx-city-card__summary-box">
          <span className="wbx-city-card__summary-label">默认扣款口径</span>
          <p className="wbx-city-accordion__preview tabular-nums">
            {citySummaryText}
          </p>
        </div>

        <div className="wbx-city-accordion__progress-wrap">
          <div className="wbx-city-card__progress-row tabular-nums">
            <div className="wbx-city-accordion__progress-meta">
              <span className={allDone ? 'is-ready' : 'is-pending'}>
                {total === 0
                  ? '目录同步中'
                  : allDone
                    ? `全部已配 (${summary.configuredStations}/${total})`
                    : `已配 ${summary.configuredStations}/${total} · 待配 ${summary.pendingStations}`}
              </span>
            </div>
            <span className="wbx-city-card__pct">{pct}%</span>
          </div>
          <div className="wbx-city-accordion__bar" aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </div>
        </div>
      </button>

      {expanded && (
        <div className="wbx-city-accordion__body">
          {cityEntry && (
            <div className="wbx-city-accordion__default">
              <CityDeductionAmounts
                entries={[cityEntry]}
                columns={columns}
                activeCategory={activeCategory}
                disabled={disabled}
                onChange={updated => {
                  if (updated[0]) onUpdateCity(updated[0]);
                }}
                onApplyToStations={onApplyCityToStations}
                onUpdateProblemRules={(targetCity, nextRules) =>
                  onUpdateCity({
                    ...targetCity,
                    edited: true,
                    problem_rules: nextRules,
                  } as DeductionEntry)
                }
              />
            </div>
          )}

          <div className="wbx-city-accordion__stations">
            <div className="wbx-city-stations-bar">
              <div className="wbx-city-stations-bar__title">
                <Layers size={14} />
                <strong>下属站点分组明细</strong>
                <span className="wbx-deduction-meta-sep" aria-hidden="true">·</span>
                <span className="tabular-nums">
                  当前显示 {stations.length} 站（已展开 {stations.filter(s => expandedStations.has(s.key)).length} 站）
                </span>
              </div>
              {stations.length > 0 && (
                <div className="wbx-city-stations-bar__actions">
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm"
                    onClick={() =>
                      onToggleAllCityStations(
                        stations.map(s => s.key),
                        !anyStationOpen,
                      )
                    }
                  >
                    {anyStationOpen ? '收起本市站点' : '展开本市全部站点'}
                  </button>
                </div>
              )}
            </div>

            {stations.length === 0 ? (
              <div className="wbx-city-stations-empty">
                当前筛选条件下该城市暂无匹配站点。
              </div>
            ) : (
              <div className="wbx-station-card-grid">
                {stations.map(entry => {
                  const isOpen = expandedStations.has(entry.key);
                  const stateInfo = statusLabel(entry);
                  const charged = hasNonZeroDeduction(entry.row, columns);
                  const readyToSync = !columns.some(
                    c => !c.endsWith('_maxDays') && (entry.row[c] === null || entry.row[c] === ''),
                  );

                  return (
                    <article
                      key={entry.key}
                      className={`wbx-station-card ${isOpen ? 'is-open' : ''} ${entry.edited ? 'is-edited' : ''}`}
                    >
                      <div className="wbx-station-card__head">
                        {entry.station.id !== '*' && (
                          <input
                            type="checkbox"
                            className="wbx-station-card__check"
                            aria-label={`选择同步站点 ${entry.station.name}`}
                            disabled={disabled}
                            checked={selectedStations.has(entry.key)}
                            onChange={e => onToggleSelectStation(entry.key, e.target.checked)}
                          />
                        )}
                        <button
                          type="button"
                          className="wbx-station-card__toggle"
                          aria-expanded={isOpen}
                          onClick={() => onToggleStation(entry.key)}
                        >
                          <div className="wbx-station-card__main">
                            <div className="wbx-station-card__top">
                              <strong>{entry.station.name}</strong>
                              <span className="wbx-station-card__id tabular-nums">
                                编号 {entry.station.id}
                              </span>
                              <span className={`wbx-station-card__state ${stateInfo.cls}`}>
                                {stateInfo.text}
                              </span>
                              {(((entry as any).problem_rules || []).length > 0) && (
                                <span className="wbx-station-card__kw-badge tabular-nums">
                                  关键词 {(entry as any).problem_rules.length}
                                </span>
                              )}
                            </div>
                            <p className="wbx-station-card__summary tabular-nums">
                              {summarizeStationRow(entry, visibleColumns)}
                            </p>
                          </div>
                          <span className="wbx-station-card__chevron" aria-hidden="true">
                            {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                          </span>
                        </button>
                      </div>

                      {isOpen && (
                        <div className="wbx-station-card__body">
                          <DeductionBentoGroups
                            groups={categories}
                            entry={entry}
                            disabled={disabled}
                            onUpdateEntry={onUpdateStation}
                          />

                          <ProblemRuleEditor
                            scopeLabel="站点问题单关键词"
                            rules={((entry as any).problem_rules || []) as ProblemRuleItem[]}
                            disabled={disabled}
                            onChange={nextRules =>
                              onUpdateStation({
                                ...entry,
                                edited: true,
                                problem_rules: nextRules,
                              } as DeductionEntry)
                            }
                          />

                          <div className="wbx-station-card__foot">
                            <div className="wbx-station-card__foot-btns">
                              {entry.station.id !== '*' && (
                                <button
                                  type="button"
                                  className="wb-button"
                                  disabled={disabled || !readyToSync}
                                  onClick={() =>
                                    onBulkUpdateStations(
                                      fillUnconfigured(
                                        allEntries,
                                        entry,
                                        columns,
                                        selectedStations.size ? selectedStations : undefined,
                                      ),
                                    )
                                  }
                                >
                                  {selectedStations.size ? '同步已选未配置' : '同步同城未配置'}
                                </button>
                              )}
                              <button
                                type="button"
                                className="wb-button"
                                disabled={disabled}
                                onClick={() =>
                                  onUpdateStation({
                                    ...entry,
                                    edited: true,
                                    row: Object.fromEntries(
                                      Object.entries(entry.row).map(([key, val]) => [
                                        key,
                                        columns.includes(key) &&
                                        (val === null || val === '') &&
                                        !key.endsWith('_maxDays')
                                          ? 0
                                          : val,
                                      ]),
                                    ),
                                  })
                                }
                              >
                                空白项填零
                              </button>
                            </div>
                            <label className="wb-zero-confirm">
                              <input
                                type="checkbox"
                                disabled={disabled || charged}
                                checked={entry.zero_confirmed}
                                onChange={e =>
                                  onUpdateStation({
                                    ...entry,
                                    edited: true,
                                    zero_confirmed: e.target.checked,
                                    row: Object.fromEntries(
                                      Object.entries(entry.row).map(([key, val]) => [
                                        key,
                                        e.target.checked &&
                                        columns.includes(key) &&
                                        (val === null || val === '') &&
                                        !key.endsWith('_maxDays')
                                          ? 0
                                          : val,
                                      ]),
                                    ),
                                  })
                                }
                              />
                              确认本站零扣款
                            </label>
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
