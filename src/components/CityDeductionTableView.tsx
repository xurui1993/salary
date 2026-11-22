import React, { useMemo, useState } from 'react';
import {
  ArrowLeft,
  Check,
  Eraser,
  Layers,
  Search,
  Sparkles,
  Tag,
  X,
} from 'lucide-react';
import type { DeductionEntry } from './DeductionAmounts';
import { ProblemRuleEditor } from './ProblemRuleEditor';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { fillUnconfigured } from '../lib/deductionBulk';
import {
  columnDisplayLabel,
  DEDUCTION_COLUMN_UNIT,
  hasNonZeroDeduction,
  type CityCardGroup,
  type CityProgressSummary,
  type DeductionCategoryId,
  type DeductionCategorySpec,
  type ProblemRuleItem,
} from '../lib/deductionCategories';

interface CityDeductionTableViewProps {
  group: CityCardGroup;
  allCitySummaries: CityProgressSummary[];
  allEntries: DeductionEntry[];
  columns: string[];
  categorySpecs: DeductionCategorySpec[];
  activeCategory: DeductionCategoryId;
  visibleColumns: string[];
  selectedStations: Set<string>;
  showProblemRules: boolean;
  disabled: boolean;
  onBack: () => void;
  onSelectCity: (cityId: string) => void;
  onChangeCategory: (category: DeductionCategoryId) => void;
  onToggleSelectStation: (stationKey: string, checked: boolean) => void;
  onToggleSelectAllStations: (stationKeys: string[], checked: boolean) => void;
  onUpdateCity: (updated: DeductionEntry) => void;
  onApplyCityToStations: (cityEntry: DeductionEntry) => void;
  onUpdateStation: (updated: DeductionEntry) => void;
  onBulkUpdateStations: (updatedEntries: DeductionEntry[]) => void;
}

type KeywordDrawerTarget =
  | { kind: 'city'; key: string }
  | { kind: 'station'; key: string };

function shortColumnTitle(column: string): string {
  return columnDisplayLabel(column).replace('天数阈值', '阈值');
}

function getEntryStatusMeta(entry: DeductionEntry, isCityDefault = false): { label: string; tone: string } {
  if (isCityDefault) {
    if (entry.edited) return { label: '已调整待保存', tone: 'is-edited' };
    if (entry.configured) return { label: '已设默认', tone: 'is-ready' };
    return { label: '待配置默认', tone: 'is-pending' };
  }
  if (entry.edited) return { label: '已调整', tone: 'is-edited' };
  if (entry.station_override) return { label: '站点例外', tone: 'is-override' };
  if (entry.inherited_city) return { label: '沿用默认', tone: 'is-ready' };
  if (entry.configured) return { label: '已配置', tone: 'is-ready' };
  if (entry.legacy) return { label: '旧配置待核', tone: 'is-pending' };
  return { label: '待配置', tone: 'is-pending' };
}

function fillBlankColumnsZero(entry: DeductionEntry, columns: string[]): DeductionEntry {
  return {
    ...entry,
    edited: true,
    row: Object.fromEntries(
      Object.entries(entry.row).map(([key, val]) => [
        key,
        columns.includes(key) && !key.endsWith('_maxDays') && (val === null || val === '')
          ? 0
          : val,
      ]),
    ),
  };
}

export function CityDeductionTableView({
  group,
  allCitySummaries,
  allEntries,
  columns,
  categorySpecs,
  activeCategory,
  visibleColumns,
  selectedStations,
  showProblemRules,
  disabled,
  onBack,
  onSelectCity,
  onChangeCategory,
  onToggleSelectStation,
  onToggleSelectAllStations,
  onUpdateCity,
  onApplyCityToStations,
  onUpdateStation,
  onBulkUpdateStations,
}: CityDeductionTableViewProps) {
  const { summary, cityEntry, stations } = group;
  const [stationSearch, setStationSearch] = useState('');
  const [onlyPendingStations, setOnlyPendingStations] = useState(false);
  const [keywordTarget, setKeywordTarget] = useState<KeywordDrawerTarget | null>(null);

  const filteredStations = useMemo(() => {
    const q = stationSearch.trim().toLowerCase();
    return stations.filter(item => {
      if (onlyPendingStations && item.configured) return false;
      if (!q) return true;
      const hay = `${item.station.name} ${item.station.id} ${item.station.city}`.toLowerCase();
      return hay.includes(q);
    });
  }, [stations, stationSearch, onlyPendingStations]);

  const selectableKeys = useMemo(
    () => filteredStations.filter(s => s.station.id !== '*').map(s => s.key),
    [filteredStations],
  );
  const allFilteredSelected =
    selectableKeys.length > 0 && selectableKeys.every(key => selectedStations.has(key));
  const selectedInCityCount = selectableKeys.filter(key => selectedStations.has(key)).length;

  const pct = summary.totalStations > 0
    ? Math.round((summary.configuredStations / summary.totalStations) * 100)
    : 0;

  const cityReadyToApply = Boolean(
    cityEntry &&
      columns.every(
        c => c.endsWith('_maxDays') || (cityEntry.row[c] !== null && cityEntry.row[c] !== ''),
      ),
  );

  const activeKeywordEntry = useMemo(() => {
    if (!keywordTarget) return null;
    if (keywordTarget.kind === 'city') {
      return cityEntry && cityEntry.key === keywordTarget.key ? cityEntry : null;
    }
    return stations.find(s => s.key === keywordTarget.key) || null;
  }, [keywordTarget, cityEntry, stations]);

  const renderEditableCell = (
    entry: DeductionEntry,
    column: string,
    onUpdate: (next: DeductionEntry) => void,
    rowTitle: string,
  ) => {
    const value = entry.row[column];
    const isThreshold = column.endsWith('_maxDays');
    const isText =
      column === '招聘来源' ||
      (typeof value === 'string' && value !== '' && !Number.isFinite(Number(value)));

    if (typeof value === 'boolean') {
      return (
        <td key={column} className="wbx-ded-sheet__cell is-center">
          <input
            type="checkbox"
            checked={value}
            disabled={disabled}
            aria-label={`${rowTitle} ${columnDisplayLabel(column)}`}
            onChange={e =>
              onUpdate({
                ...entry,
                edited: true,
                zero_confirmed: false,
                row: { ...entry.row, [column]: e.target.checked },
              })
            }
          />
        </td>
      );
    }

    const isEmpty = value === null || value === undefined || value === '';
    return (
      <td
        key={column}
        className={`wbx-ded-sheet__cell${isEmpty && !isThreshold ? ' is-empty' : ''}${isThreshold ? ' is-threshold' : ''}`}
      >
        <input
          className="wbx-ded-sheet__input tabular-nums"
          type={isText ? 'text' : 'number'}
          step="any"
          disabled={disabled}
          aria-label={`${rowTitle} ${columnDisplayLabel(column)}`}
          placeholder={isThreshold ? '留空' : '—'}
          value={value ?? ''}
          onChange={e => {
            const raw = e.target.value;
            let nextValue: string | number | null;
            if (isThreshold) {
              const num = raw === '' ? NaN : Number(raw);
              nextValue = Number.isFinite(num) && num > 0 ? num : null;
            } else {
              nextValue = isText ? raw : raw === '' ? null : Number(raw);
            }
            onUpdate({
              ...entry,
              edited: true,
              zero_confirmed: false,
              row: { ...entry.row, [column]: nextValue },
            });
          }}
        />
      </td>
    );
  };

  return (
    <div className="wbx-ded-tableview" aria-label={`${summary.cityName} 扣款明细表格视图`}>
      {/* 1. 城市表格顶栏：返回卡片墙 + 城市快切 + 进度摘要 + 站内过滤 */}
      <div className="wbx-ded-tableview__bar">
        <div className="wbx-ded-tableview__nav">
          <button
            type="button"
            className="wbx-ded-back-btn"
            onClick={onBack}
          >
            <ArrowLeft size={14} aria-hidden="true" />
            <span>返回城市卡片</span>
          </button>

          <span className="wbx-ded-tableview__sep" aria-hidden="true" />

          <div className="wbx-ded-tableview__city-picker">
            <select
              className="wb-select wbx-ded-tableview__select"
              aria-label="切换当前编辑城市"
              value={summary.cityId}
              onChange={e => {
                setStationSearch('');
                setOnlyPendingStations(false);
                setKeywordTarget(null);
                onSelectCity(e.target.value);
              }}
            >
              {allCitySummaries.map(item => (
                <option key={item.cityId} value={item.cityId}>
                  {item.cityName}（{item.configuredStations}/{item.totalStations} 站）
                </option>
              ))}
            </select>
          </div>

          <div className="wbx-ded-tableview__meta tabular-nums">
            <span className={summary.pendingStations === 0 && summary.totalStations > 0 ? 'is-ready' : 'is-pending'}>
              已配 {summary.configuredStations}/{summary.totalStations} 站（{pct}%）
            </span>
            <span aria-hidden="true">·</span>
            <span>
              {summary.overrideStations > 0 ? `${summary.overrideStations} 站例外` : '全站统一口径'}
            </span>
          </div>
        </div>

        <div className="wbx-ded-tableview__controls">
          <div className="wbx-ded-search is-compact">
            <Search size={13} className="wbx-ded-search__icon" aria-hidden="true" />
            <input
              className="wbx-ded-search__input"
              aria-label={`搜索 ${summary.cityName} 下属站点`}
              placeholder="筛选本市站点名称或编号…"
              value={stationSearch}
              onChange={e => setStationSearch(e.target.value)}
            />
            {stationSearch.trim() && (
              <button
                type="button"
                className="wbx-ded-search__clear"
                aria-label="清空站点筛选"
                onClick={() => setStationSearch('')}
              >
                <X size={12} />
              </button>
            )}
          </div>

          <button
            type="button"
            className={`wbx-ded-filter-chip${onlyPendingStations ? ' is-active' : ''}`}
            aria-pressed={onlyPendingStations}
            onClick={() => setOnlyPendingStations(v => !v)}
          >
            <span className="tabular-nums">仅看未配 ({summary.pendingStations})</span>
          </button>

          {cityEntry && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-btn--secondary"
              disabled={disabled || !cityReadyToApply}
              title={
                cityReadyToApply
                  ? '将城市统一默认金额下发到本市全部沿用或尚未配置的站点'
                  : '请先将首行「城市统一默认」填写完整（或先点击首行填零）'
              }
              onClick={() => onApplyCityToStations(cityEntry)}
            >
              <Sparkles size={13} aria-hidden="true" />
              <span>下发默认至待配站点</span>
            </button>
          )}
        </div>
      </div>

      {/* 2. 类目列组切换条 */}
      <div className="wbx-ded-tableview__cats">
        <div className="wbx-ded-catbar" role="group" aria-label="切换表格展示扣款类目">
          <button
            type="button"
            className={`wbx-ded-cat${activeCategory === 'all' ? ' is-active' : ''}`}
            aria-pressed={activeCategory === 'all'}
            onClick={() => onChangeCategory('all')}
          >
            <span>全部列</span>
            <span className="wbx-ded-cat__count tabular-nums">{columns.length}</span>
          </button>
          {categorySpecs.map(cat => (
            <button
              key={cat.id}
              type="button"
              className={`wbx-ded-cat${activeCategory === cat.id ? ' is-active' : ''}`}
              aria-pressed={activeCategory === cat.id}
              onClick={() => onChangeCategory(activeCategory === cat.id ? 'all' : cat.id)}
            >
              <span>{cat.label}</span>
              <span className="wbx-ded-cat__count tabular-nums">{cat.columns.length}</span>
            </button>
          ))}
        </div>

        <span className="wbx-ded-tableview__hint tabular-nums">
          {selectedInCityCount > 0
            ? `已勾选 ${selectedInCityCount} 个站点用于定向同步`
            : `首行固定「${summary.cityName} · 城市默认」，下方共 ${filteredStations.length} 个站点支持单元格直接填写`}
        </span>
      </div>

      {/* 3. 全宽可编辑表格主区域 */}
      <div className="wbx-ded-sheet-wrap" role="region" aria-label={`${summary.cityName} 站点扣款填写表格`}>
        <table className="wbx-ded-sheet">
          <thead>
            <tr>
              <th className="wbx-ded-sheet__th-check">
                <input
                  type="checkbox"
                  aria-label={`全选 ${summary.cityName} 站点`}
                  checked={allFilteredSelected}
                  disabled={disabled || selectableKeys.length === 0}
                  onChange={e => onToggleSelectAllStations(selectableKeys, e.target.checked)}
                />
              </th>
              <th className="wbx-ded-sheet__th-station">站点 / 规则对象</th>
              {visibleColumns.map(col => (
                <th key={col} className="wbx-ded-sheet__th-col" title={`${columnDisplayLabel(col)}${DEDUCTION_COLUMN_UNIT[col] ? `（${DEDUCTION_COLUMN_UNIT[col]}）` : ''}`}>
                  <div className="wbx-ded-sheet__th-inner">
                    <span className="wbx-ded-sheet__th-name">{shortColumnTitle(col)}</span>
                    {DEDUCTION_COLUMN_UNIT[col] && (
                      <small className="wbx-ded-sheet__th-unit">{DEDUCTION_COLUMN_UNIT[col]}</small>
                    )}
                  </div>
                </th>
              ))}
              {showProblemRules && (
                <th className="wbx-ded-sheet__th-kw">关键词</th>
              )}
              <th className="wbx-ded-sheet__th-ops">行操作</th>
            </tr>
          </thead>

          <tbody>
            {/* 首行固定：城市统一默认 */}
            {cityEntry && (() => {
              const status = getEntryStatusMeta(cityEntry, true);
              const charged = hasNonZeroDeduction(cityEntry.row, columns);
              const kwCount = ((cityEntry as any).problem_rules || []).length;

              return (
                <tr className={`wbx-ded-sheet__row is-city-default${cityEntry.edited ? ' is-edited' : ''}`}>
                  <td className="wbx-ded-sheet__td-check">
                    <span className="wbx-ded-sheet__city-badge" title="城市统一默认规则" aria-label="城市默认">
                      <Layers size={13} aria-hidden="true" />
                    </span>
                  </td>
                  <td className="wbx-ded-sheet__td-station">
                    <div className="wbx-ded-sheet__station-cell">
                      <div className="wbx-ded-sheet__station-main">
                        <strong>{summary.cityName} · 城市默认</strong>
                        <span className={`wbx-ded-sheet__status ${status.tone}`}>{status.label}</span>
                      </div>
                      <span className="wbx-ded-sheet__sub">全城未设例外的站点自动沿用此口径</span>
                    </div>
                  </td>
                  {visibleColumns.map(col =>
                    renderEditableCell(cityEntry, col, onUpdateCity, `${summary.cityName} 城市默认`),
                  )}
                  {showProblemRules && (
                    <td className="wbx-ded-sheet__td-kw">
                      <button
                        type="button"
                        className={`wbx-ded-sheet__kw-btn${kwCount > 0 ? ' has-rules' : ''}`}
                        onClick={() => setKeywordTarget({ kind: 'city', key: cityEntry.key })}
                      >
                        <Tag size={12} aria-hidden="true" />
                        <span className="tabular-nums">{kwCount > 0 ? `${kwCount} 条` : '设置'}</span>
                      </button>
                    </td>
                  )}
                  <td className="wbx-ded-sheet__td-ops">
                    <div className="wbx-ded-sheet__ops">
                      <button
                        type="button"
                        className="wbx-ded-sheet__op-btn"
                        disabled={disabled}
                        title="将本行空白扣款项填入 0"
                        onClick={() => onUpdateCity(fillBlankColumnsZero(cityEntry, columns))}
                      >
                        <Eraser size={12} aria-hidden="true" />
                        <span>填零</span>
                      </button>
                      <label
                        className={`wbx-ded-sheet__zero-toggle${cityEntry.zero_confirmed ? ' is-checked' : ''}${charged ? ' is-disabled' : ''}`}
                        title={charged ? '已填写非零金额，无需确认零扣款' : '勾选确认本市默认零扣款'}
                      >
                        <input
                          type="checkbox"
                          disabled={disabled || charged}
                          checked={cityEntry.zero_confirmed}
                          onChange={e =>
                            onUpdateCity({
                              ...(e.target.checked ? fillBlankColumnsZero(cityEntry, columns) : cityEntry),
                              edited: true,
                              zero_confirmed: e.target.checked,
                            })
                          }
                        />
                        <span>零扣</span>
                      </label>
                    </div>
                  </td>
                </tr>
              );
            })()}

            {/* 下属站点明细行 */}
            {filteredStations.length === 0 ? (
              <tr>
                <td
                  colSpan={visibleColumns.length + (showProblemRules ? 4 : 3)}
                  className="wbx-ded-sheet__empty"
                >
                  当前筛选条件下该城市暂无匹配站点。
                </td>
              </tr>
            ) : (
              filteredStations.map(entry => {
                const status = getEntryStatusMeta(entry, false);
                const charged = hasNonZeroDeduction(entry.row, columns);
                const readyToSync = !columns.some(
                  c => !c.endsWith('_maxDays') && (entry.row[c] === null || entry.row[c] === ''),
                );
                const kwCount = ((entry as any).problem_rules || []).length;
                const isSelected = selectedStations.has(entry.key);

                return (
                  <tr
                    key={entry.key}
                    className={`wbx-ded-sheet__row${entry.edited ? ' is-edited' : ''}${isSelected ? ' is-selected' : ''}`}
                  >
                    <td className="wbx-ded-sheet__td-check">
                      {entry.station.id !== '*' && (
                        <input
                          type="checkbox"
                          aria-label={`选择同步站点 ${entry.station.name}`}
                          checked={isSelected}
                          disabled={disabled}
                          onChange={e => onToggleSelectStation(entry.key, e.target.checked)}
                        />
                      )}
                    </td>
                    <td className="wbx-ded-sheet__td-station">
                      <div className="wbx-ded-sheet__station-cell">
                        <div className="wbx-ded-sheet__station-main">
                          <strong title={entry.station.name}>{entry.station.name}</strong>
                          <span className={`wbx-ded-sheet__status ${status.tone}`}>{status.label}</span>
                        </div>
                        <span className="wbx-ded-sheet__sub tabular-nums">编号 {entry.station.id}</span>
                      </div>
                    </td>
                    {visibleColumns.map(col =>
                      renderEditableCell(entry, col, onUpdateStation, entry.station.name),
                    )}
                    {showProblemRules && (
                      <td className="wbx-ded-sheet__td-kw">
                        <button
                          type="button"
                          className={`wbx-ded-sheet__kw-btn${kwCount > 0 ? ' has-rules' : ''}`}
                          onClick={() => setKeywordTarget({ kind: 'station', key: entry.key })}
                        >
                          <Tag size={12} aria-hidden="true" />
                          <span className="tabular-nums">{kwCount > 0 ? `${kwCount} 条` : '设置'}</span>
                        </button>
                      </td>
                    )}
                    <td className="wbx-ded-sheet__td-ops">
                      <div className="wbx-ded-sheet__ops">
                        <button
                          type="button"
                          className="wbx-ded-sheet__op-btn"
                          disabled={disabled}
                          title="将本站空白扣款项填入 0"
                          onClick={() => onUpdateStation(fillBlankColumnsZero(entry, columns))}
                        >
                          <span>填零</span>
                        </button>
                        {entry.station.id !== '*' && (
                          <button
                            type="button"
                            className="wbx-ded-sheet__op-btn is-sync"
                            disabled={disabled || !readyToSync}
                            title={
                              readyToSync
                                ? selectedStations.size
                                  ? '将本站金额同步至已勾选的未配置站点'
                                  : '将本站金额同步至同城未配置站点'
                                : '请先将本站所有扣款项填写完整'
                            }
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
                            <span>{selectedStations.size ? '同步已选' : '同步同城'}</span>
                          </button>
                        )}
                        <label
                          className={`wbx-ded-sheet__zero-toggle${entry.zero_confirmed ? ' is-checked' : ''}${charged ? ' is-disabled' : ''}`}
                          title={charged ? '已填写非零金额，无需确认零扣款' : '勾选确认本站零扣款'}
                        >
                          <input
                            type="checkbox"
                            disabled={disabled || charged}
                            checked={entry.zero_confirmed}
                            onChange={e =>
                              onUpdateStation({
                                ...(e.target.checked ? fillBlankColumnsZero(entry, columns) : entry),
                                edited: true,
                                zero_confirmed: e.target.checked,
                              })
                            }
                          />
                          <span>零扣</span>
                        </label>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* 4. 问题单关键词规则侧栏抽屉 */}
      {showProblemRules && keywordTarget && activeKeywordEntry && (
        <WorkbenchDrawer
          title={
            keywordTarget.kind === 'city'
              ? `${summary.cityName} · 城市默认问题单关键词`
              : `${summary.cityName} · ${activeKeywordEntry.station.name} 关键词规则`
          }
          onClose={() => setKeywordTarget(null)}
        >
          <p className="wb-muted mb-3">
            {keywordTarget.kind === 'city'
              ? '城市问题单关键词适用于本市所有未单独设例外的站点；编辑后记得在主页面点击“保存后续默认扣款”。'
              : '站点级关键词规则优先级高于城市默认规则；留空关键词则对该问题单类型整类生效。'}
          </p>
          <ProblemRuleEditor
            scopeLabel={keywordTarget.kind === 'city' ? '城市问题单关键词' : '站点问题单关键词'}
            rules={((activeKeywordEntry as any).problem_rules || []) as ProblemRuleItem[]}
            disabled={disabled}
            onChange={nextRules => {
              const updated = {
                ...activeKeywordEntry,
                edited: true,
                problem_rules: nextRules,
              } as DeductionEntry;
              if (keywordTarget.kind === 'city') onUpdateCity(updated);
              else onUpdateStation(updated);
            }}
          />
          <div className="wb-row justify-end mt-4">
            <button
              type="button"
              className="wbx-btn wbx-btn--primary wbx-btn--sm"
              onClick={() => setKeywordTarget(null)}
            >
              <Check size={13.5} aria-hidden="true" />
              <span>完成返回表格</span>
            </button>
          </div>
        </WorkbenchDrawer>
      )}
    </div>
  );
}
