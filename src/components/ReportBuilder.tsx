import React, { useEffect, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  FileSpreadsheet,
  Layers,
  MapPin,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import {
  buildGenerateBatchPayloads,
  buildRecentReportMonths,
  buildReportMonthChunks,
  deriveSelectedMonthsFromRange,
  summarizeSelectedReportsScope,
  toggleReportMonthSelection,
  toggleReportSelection,
  type ReportDefinition,
} from '../lib/reportBuilder';
import { useStationDirectory } from '../lib/useStationDirectory';
import { CityStationCount } from './CityStationCount';
import { BindingPlatformConfig } from './BindingPlatformConfig';

interface CityItem {
  id: string;
  name: string;
  disabled?: boolean;
  note?: string;
}

export interface ReportBuilderProps {
  reports: ReportDefinition[];
  selectedIds?: string[];
  onSelectIds?: (ids: string[]) => void;
  selectedId?: string;
  onSelect?: (id: string) => void;
  cities: CityItem[];
  selectedCities: string[];
  onCities: (cities: string[]) => void;
  start: string;
  end: string;
  today: string;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
  selectedMonths?: string[];
  onSelectedMonths?: (months: string[]) => void;
  excludeSeparation?: boolean;
  onExcludeSeparation?: (value: boolean) => void;
  includeSeparation?: boolean;
  onSeparation?: (value: boolean) => void;
  locked: boolean;
  creating: boolean;
  disabled: boolean;
  submitLabel: string;
  onSubmit: () => void;
  uncertain: boolean;
  duplicate: boolean;
  recollect: boolean;
  onRecollect: (value: boolean) => void;
  refreshing: boolean;
  onRefreshCities: () => void;
  singleReportMode?: boolean;
  bindingPlatforms?: Record<string, string>;
  onBindingPlatformsChange?: (next: Record<string, string>) => void;
  bindingPlatformsSaving?: boolean;
}

function reportScopeLabel(scope: ReportDefinition['scope']): string {
  if (scope === 'city_month') return '按城市 · 近3月';
  if (scope === 'city_range') return '按城市 · 按日期';
  return '全部城市 · 全量';
}

export function ReportBuilder(props: ReportBuilderProps) {
  const stationDirectory = useStationDirectory('fengshen');
  const { reports, cities, selectedCities, locked } = props;

  const activeSelectedIds = (
    props.selectedIds ?? (props.selectedId ? [props.selectedId] : [])
  ).filter(id => reports.some(report => report.id === id));

  const recentMonths = buildRecentReportMonths(props.today, 3);
  const allowedMonthCodes = recentMonths.map(item => item.month);
  const activeMonths = (
    props.selectedMonths !== undefined
      ? props.selectedMonths.filter(m => allowedMonthCodes.includes(m))
      : deriveSelectedMonthsFromRange(props.start, props.end, allowedMonthCodes)
  ).sort();

  const selectedReports = reports.filter(report => activeSelectedIds.includes(report.id));
  const showBindingPlatforms = selectedReports.some(
    report => report.id === 'payment_binding' || report.id === 'abnormal_followup',
  );
  const scopeSummary = summarizeSelectedReportsScope(
    selectedReports,
    props.start,
    props.end,
    props.today,
    activeMonths,
  );
  const range = scopeSummary.range;
  const monthChunks =
    activeMonths.length > 0 ? buildReportMonthChunks(activeMonths, props.today) : [];

  const effectiveExcludeSeparation =
    props.excludeSeparation !== undefined
      ? props.excludeSeparation
      : !(props.includeSeparation ?? false);

  const handleExcludeSeparationChange = (checked: boolean) => {
    if (locked) return;
    props.onExcludeSeparation?.(checked);
    props.onSeparation?.(!checked);
  };

  const updateSelectedIds = (nextIds: string[]) => {
    if (props.onSelectIds) {
      props.onSelectIds(nextIds);
      return;
    }
    if (props.onSelect) {
      props.onSelect(nextIds[nextIds.length - 1] || '');
    }
  };

  const handleToggleReport = (id: string) => {
    if (locked) return;
    if (props.onSelectIds) {
      updateSelectedIds(
        toggleReportSelection(
          activeSelectedIds,
          id,
          reports.map(r => r.id),
        ),
      );
      return;
    }
    if (props.onSelect) {
      props.onSelect(id);
    }
  };

  const [reportDropdownOpen, setReportDropdownOpen] = useState(false);
  const [reportSearch, setReportSearch] = useState('');
  const [citySearch, setCitySearch] = useState('');
  const reportDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (locked) {
      setReportDropdownOpen(false);
    }
  }, [locked]);

  useEffect(() => {
    const outside = (event: MouseEvent) => {
      if (!reportDropdownRef.current?.contains(event.target as Node)) {
        setReportDropdownOpen(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setReportDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, []);

  const selectable = cities.filter(city => !city.disabled);
  const filteredCities = citySearch.trim()
    ? cities.filter(city => city.name.includes(citySearch.trim()))
    : cities;
  const filteredReports = reportSearch.trim()
    ? reports.filter(
        report =>
          report.label.includes(reportSearch.trim()) ||
          (report.description || '').includes(reportSearch.trim()),
      )
    : reports;

  const chooseCity = (name: string) => {
    if (locked) return;
    props.onCities(
      selectedCities.includes(name)
        ? selectedCities.filter(value => value !== name)
        : [...selectedCities, name],
    );
  };

  const applyMonths = (nextMonths: string[]) => {
    if (locked) return;
    const valid = [...new Set(nextMonths.filter(m => allowedMonthCodes.includes(m)))].sort();
    if (!valid.length) return;
    const nextChunks = buildReportMonthChunks(valid, props.today);
    props.onSelectedMonths?.(valid);
    if (nextChunks.length > 0) {
      props.onStart(nextChunks[0].start);
      props.onEnd(nextChunks[nextChunks.length - 1].end);
    }
  };

  const handleToggleMonth = (monthCode: string) => {
    if (locked) return;
    const nextMonths = toggleReportMonthSelection(activeMonths, monthCode, allowedMonthCodes);
    applyMonths(nextMonths);
  };

  const blockerText = !selectedReports.length
    ? '请先在左侧「01 报表类型」选择至少 1 份报表'
    : scopeSummary.needsCity && !selectedCities.length
      ? '请至少选择 1 个处理城市'
      : scopeSummary.needsDate && !range
        ? '请选择有效的业务月份'
        : '';

  const plannedBatches = buildGenerateBatchPayloads(
    selectedReports,
    selectedCities,
    props.start,
    props.end,
    props.today,
    {
      excludeSeparation: effectiveExcludeSeparation,
      selectedMonths: activeMonths,
    },
  );
  const plannedBatchCount = plannedBatches.length;

  const effectiveSubmitLabel =
    props.submitLabel === '生成报表'
      ? selectedReports.length > 1
        ? `批量生成 ${selectedReports.length} 份报表`
        : plannedBatchCount > 1
          ? `批量生成 ${plannedBatchCount} 批报表`
          : '生成报表'
      : props.submitLabel;

  const allReportsSelected =
    reports.length > 0 && reports.every(report => activeSelectedIds.includes(report.id));
  const allMonthsSelected =
    allowedMonthCodes.length > 0 &&
    allowedMonthCodes.every(monthCode => activeMonths.includes(monthCode));

  const singleMode = Boolean(props.singleReportMode);
  const singleReport = singleMode ? selectedReports[0] : undefined;
  const cityStepNumber = singleMode ? '01' : '02';
  const monthStepNumber = singleMode ? '02' : '03';

  return (
    <section className={`rb-workbench${singleMode ? ' is-single-module' : ''}`} aria-label="专项报表生成">
      <div className="rb-main">
        {singleMode && singleReport ? (
          !scopeSummary.allGlobal && scopeSummary.sources.length > 0 ? (
            <section className="wbx-card rb-compact-note" aria-label={`${singleReport.label}说明与来源`}>
              <details className="rb-explanation" key={singleReport.id}>
                <summary>
                  <span className="rb-compact-note__summary">
                    <strong>报表说明与来源（{scopeSummary.sources.length}）</strong>
                    {singleReport.description && (
                      <span className="rb-compact-note__desc">{singleReport.description}</span>
                    )}
                  </span>
                  <ChevronDown size={15} className="rb-compact-note__chevron" aria-hidden="true" />
                </summary>
                <ul>
                  {scopeSummary.sources.map(source => (
                    <li key={source}>{source.replaceAll('白泽', '商翼')}</li>
                  ))}
                </ul>
                <p>资料不足时暂停生成，已取得的资料保留。</p>
              </details>
            </section>
          ) : null
        ) : (
        /* Step 01: Left Report Type Multi-Select Dropdown */
        <section className="wb-step-card rb-step-card" aria-labelledby="report-type-label">
          <div className="wb-step-card-header">
            <div className="wb-step-badge">
              <span className="wb-step-number">01</span>
              <span id="report-type-label" className="wb-step-title">
                报表类型
              </span>
              <span className="wb-step-count-pill tabular-nums">
                已选 {selectedReports.length} / {reports.length} 项
              </span>
            </div>

            {reports.length > 0 && props.onSelectIds && (
              <div className="wb-inline-city-toolbar">
                <button
                  type="button"
                  className="wb-city-preset-btn"
                  disabled={locked}
                  onClick={() =>
                    updateSelectedIds(
                      allReportsSelected ? [] : reports.map(report => report.id),
                    )
                  }
                >
                  {allReportsSelected ? '清空报表' : '全选报表'}
                </button>
              </div>
            )}
          </div>

          <div className="rb-report-dropdown" ref={reportDropdownRef}>
            <button
              type="button"
              className={`rb-report-dropdown-trigger ${selectedReports.length > 0 ? 'has-value' : ''} ${reportDropdownOpen ? 'is-open' : ''}`}
              aria-haspopup="listbox"
              aria-expanded={reportDropdownOpen}
              aria-label="选择业务报表"
              disabled={locked || !reports.length}
              onClick={() => setReportDropdownOpen(open => !open)}
            >
              <div className="rb-dropdown-trigger-main">
                <span className="rb-dropdown-icon" aria-hidden="true">
                  <FileSpreadsheet size={16} />
                </span>
                {selectedReports.length === 0 ? (
                  <span className="rb-dropdown-placeholder">
                    请选择需要生成的专项报表（支持多选）
                  </span>
                ) : (
                  <div className="rb-dropdown-chips">
                    {selectedReports.map(report => (
                      <span key={report.id} className="rb-selected-chip">
                        <span>{report.label}</span>
                        <small>{reportScopeLabel(report.scope)}</small>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="rb-dropdown-trigger-end">
                <span className="rb-dropdown-action-hint">
                  {reportDropdownOpen ? '收起列表' : '点击选择（支持多选）'}
                </span>
                <ChevronDown
                  size={16}
                  className={`rb-dropdown-chevron ${reportDropdownOpen ? 'is-rotated' : ''}`}
                />
              </div>
            </button>

            {reportDropdownOpen && (
              <div
                className="rb-report-dropdown-menu"
                role="listbox"
                aria-multiselectable={!!props.onSelectIds}
                aria-label="专项报表下拉列表"
              >
                {reports.length > 4 && (
                  <label className="rb-dropdown-search">
                    <Search size={14} />
                    <input
                      autoFocus
                      aria-label="搜索报表"
                      placeholder="搜索报表名称或说明…"
                      value={reportSearch}
                      onChange={e => setReportSearch(e.target.value)}
                    />
                  </label>
                )}

                <div className="rb-dropdown-options">
                  {filteredReports.map(item => {
                    const isSelected = activeSelectedIds.includes(item.id);
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        disabled={locked}
                        onClick={() => handleToggleReport(item.id)}
                        className={`rb-dropdown-option ${isSelected ? 'is-selected' : ''}`}
                      >
                        <span
                          className={`rb-option-check ${isSelected ? 'is-checked' : ''}`}
                          aria-hidden="true"
                        >
                          {isSelected && <Check size={12} strokeWidth={2.75} />}
                        </span>
                        <div className="rb-option-content">
                          <div className="rb-option-top">
                            <strong>{item.label}</strong>
                            <span className="rb-option-scope">{reportScopeLabel(item.scope)}</span>
                          </div>
                          {item.description && (
                            <p className="rb-option-desc">{item.description}</p>
                          )}
                          {item.systems && item.systems.length > 0 && (
                            <span className="rb-option-systems">
                              关联系统：{item.systems.join(' / ')}
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                  {!filteredReports.length && (
                    <p className="rb-dropdown-empty">未找到匹配的报表</p>
                  )}
                </div>

                <div className="rb-dropdown-footer">
                  <span className="rb-dropdown-footer-count tabular-nums">
                    已选 {selectedReports.length} / {reports.length} 项
                  </span>
                  <div className="rb-dropdown-footer-actions">
                    {props.onSelectIds && (
                      <>
                        <button
                          type="button"
                          className="rb-text-action"
                          disabled={locked || allReportsSelected}
                          onClick={() => updateSelectedIds(reports.map(r => r.id))}
                        >
                          全选
                        </button>
                        <button
                          type="button"
                          className="rb-text-action"
                          disabled={locked || !selectedReports.length}
                          onClick={() => updateSelectedIds([])}
                        >
                          清空
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      className="rb-dropdown-done-btn"
                      onClick={() => setReportDropdownOpen(false)}
                    >
                      完成
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {!reports.length && <p className="rb-muted">暂无可用报表。</p>}

          {selectedReports.length > 0 && (
            <div className="rb-selected-summary-block">
              <div className="rb-selected-meta-bar">
                {scopeSummary.systems.length > 0 && (
                  <div className="rb-systems">
                    <Layers size={13} aria-hidden="true" />
                    <span>关联系统：{scopeSummary.systems.join(' / ')}</span>
                  </div>
                )}
                <span className="rb-selected-desc-line">
                  {selectedReports.length === 1
                    ? selectedReports[0].description || '确认下方范围后点击右侧「生成报表」。'
                    : `已选 ${selectedReports.length} 份报表，提交后将自动拆分为 ${selectedReports.length} 批独立生成任务。`}
                </span>
              </div>

              {scopeSummary.sources.length > 0 && (
                <details
                  className="rb-explanation"
                  key={selectedReports.map(r => r.id).join(',')}
                >
                  <summary>报表说明与来源（{scopeSummary.sources.length}）</summary>
                  <ul>
                    {scopeSummary.sources.map(source => (
                      <li key={source}>{source.replaceAll('白泽', '商翼')}</li>
                    ))}
                  </ul>
                  <p>资料不足时暂停生成，已取得的资料保留。</p>
                </details>
              )}
            </div>
          )}
        </section>
        )}

        {/* 处理城市与站点范围（全部取消下拉框，平铺展示） */}
        {selectedReports.length > 0 && (
          scopeSummary.allGlobal ? (
            <>
            <section className={`${singleMode ? 'wbx-card wbx-step' : 'wb-step-card'} rb-step-card`} aria-label="全局报表固定范围">
              <div className="wb-step-card-header">
                <div className="wb-step-badge">
                  <span className="wb-step-number">{cityStepNumber}</span>
                  <span className="wb-step-title">处理范围</span>
                  <span className="wb-step-count-pill">固定全局口径</span>
                </div>
              </div>
              <div className="rb-fixed-scope">
                <div className="rb-fixed-scope-item">
                  <span className="rb-fixed-scope-label">城市范围</span>
                  <strong>全部授权城市</strong>
                  <small>自动整合全部城市站点，无需单独勾选</small>
                </div>
                <div className="rb-fixed-scope-item">
                  <span className="rb-fixed-scope-label">资料周期</span>
                  <strong>当前全量 · 不按日期筛选</strong>
                  <small>直接汇总蓝橙 5 类在职/离职与请假最新档案</small>
                </div>
              </div>
              {scopeSummary.sources.length > 0 && (
                <div className="rb-fixed-sources">
                  <div className="rb-fixed-sources__head">
                    <span>纳入的 {scopeSummary.sources.length} 类数据来源</span>
                    <small>资料不足时暂停生成，已取得资料自动保留</small>
                  </div>
                  <ul className="rb-fixed-sources__list">
                    {scopeSummary.sources.map((source, idx) => (
                      <li key={source}>
                        <span className="rb-fixed-sources__idx tabular-nums">{String(idx + 1).padStart(2, '0')}</span>
                        <span>{source.replaceAll('白泽', '商翼')}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            <section className={`${singleMode ? 'wbx-card wbx-step' : 'wb-step-card'} rb-step-card`} aria-label="输出内容与归档说明">
              <div className="wb-step-card-header">
                <div className="wb-step-badge">
                  <span className="wb-step-number">{monthStepNumber}</span>
                  <span className="wb-step-title">输出内容与归档说明</span>
                  <span className="wb-step-count-pill">标准 Excel 工作簿</span>
                </div>
              </div>
              <div className="rb-delivery-grid">
                <div className="rb-delivery-item">
                  <span className="rb-delivery-item__label">工作簿结构</span>
                  <strong>异常汇总 + 5 类明细底表</strong>
                  <small>自动按正常离职、离职报备、批量离职、请假及总档案分 Sheet 整理，方便财务复核</small>
                </div>
                <div className="rb-delivery-item">
                  <span className="rb-delivery-item__label">去重与聚合口径</span>
                  <strong>按证件号归并最新状态</strong>
                  <small>同一骑手存在多条审批记录时保留最新生效时间，并自动标注所属城市与站点</small>
                </div>
                <div className="rb-delivery-item">
                  <span className="rb-delivery-item__label">归档与文件领取</span>
                  <strong>任务中心一键下载</strong>
                  <small>生成完毕后自动写入本机归档目录，可在任务中心直接领取成品 .xlsx 或原始来源包</small>
                </div>
              </div>
            </section>
            </>
          ) : (
            <section className={`${singleMode ? 'wbx-card wbx-step' : 'wb-step-card'} rb-step-card`} aria-labelledby="report-city-label">
              <div className="wb-step-card-header">
                <div className="wb-step-badge">
                  <span className="wb-step-number">{cityStepNumber}</span>
                  <span id="report-city-label" className="wb-step-title">
                    处理城市
                  </span>
                  <span className="wb-step-count-pill tabular-nums">
                    已选 {selectedCities.length} / {selectable.length}
                  </span>
                </div>

                <div className="wb-inline-city-toolbar flex-wrap">
                  <button
                    type="button"
                    className="wb-city-preset-btn"
                    disabled={locked || !selectable.length}
                    onClick={() =>
                      props.onCities(
                        selectedCities.length === selectable.length
                          ? []
                          : selectable.map(city => city.name),
                      )
                    }
                  >
                    {selectedCities.length === selectable.length && selectedCities.length
                      ? '清空城市'
                      : '全选城市'}
                  </button>
                  <button
                    type="button"
                    className="wb-city-preset-btn"
                    disabled={locked || props.refreshing}
                    onClick={props.onRefreshCities}
                  >
                    <RefreshCw size={12} className={props.refreshing ? 'animate-spin' : ''} />
                    <span>{props.refreshing ? '刷新中…' : '刷新城市'}</span>
                  </button>
                  <button
                    type="button"
                    className="wb-city-preset-btn"
                    disabled={locked || stationDirectory.data?.status === 'loading'}
                    onClick={stationDirectory.refresh}
                  >
                    {stationDirectory.data?.status === 'loading' ? '站点同步中…' : '刷新站点数'}
                  </button>
                </div>
              </div>

              {cities.length > 18 && (
                <div className="rb-inline-city-filter">
                  <Search size={14} />
                  <input
                    aria-label="筛选处理城市"
                    placeholder="输入城市名称快速定位…"
                    value={citySearch}
                    onChange={e => setCitySearch(e.target.value)}
                  />
                  {citySearch && (
                    <button
                      type="button"
                      className="rb-filter-clear"
                      aria-label="清除城市筛选"
                      onClick={() => setCitySearch('')}
                    >
                      <X size={13} />
                    </button>
                  )}
                </div>
              )}

              <div
                className="wb-inline-city-grid rb-inline-city-grid"
                role="group"
                aria-labelledby="report-city-label"
              >
                {filteredCities.map(city => {
                  const selected = !city.disabled && selectedCities.includes(city.name);
                  return (
                    <button
                      key={city.id}
                      type="button"
                      disabled={locked || city.disabled}
                      title={city.disabled ? city.note : undefined}
                      aria-pressed={selected}
                      onClick={() => chooseCity(city.name)}
                      className={`wb-inline-city-chip ${selected ? 'is-selected' : ''} ${
                        city.disabled ? 'is-disabled' : ''
                      }`}
                    >
                      <span className="wb-city-check-box" aria-hidden="true">
                        {selected && '✓'}
                      </span>
                      <span className="wb-city-chip-name">{city.name}</span>
                      <span className="wb-city-status">
                        <CityStationCount directory={stationDirectory.data} city={city.id} />
                        {city.disabled && (
                          <span className="wb-city-disabled-badge">{city.note || '下架'}</span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>

              {!selectable.length && (
                <p className="wb-notice mt-3">暂无可用城市，请刷新城市或检查平台连接。</p>
              )}

              {showBindingPlatforms && (
                <BindingPlatformConfig
                  cities={cities}
                  selectedCities={selectedCities}
                  bindingPlatforms={props.bindingPlatforms}
                  onChange={props.onBindingPlatformsChange}
                  saving={props.bindingPlatformsSaving}
                  disabled={locked}
                />
              )}

              {!scopeSummary.needsDate && scopeSummary.needsSeparation && (
                <div className="wb-date-rule-bar" role="group" aria-label="报表站点范围">
                  <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                    <input
                      type="checkbox"
                      aria-label="排除取分离站点"
                      checked={effectiveExcludeSeparation}
                      disabled={locked}
                      onChange={event => handleExcludeSeparationChange(event.target.checked)}
                      className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                    />
                    <span>
                      排除取分离站点{' '}
                      <span className="font-normal text-slate-400">
                        （不勾选则下载全部站点）
                      </span>
                    </span>
                  </label>
                </div>
              )}
            </section>
          )
        )}

        {/* 业务月份（近3个月多选 + 风神样式排除取分离站点开关） */}
        {selectedReports.length > 0 && scopeSummary.needsDate && (
          <section className={`${singleMode ? 'wbx-card wbx-step' : 'wb-step-card'} rb-step-card`} aria-labelledby="report-month-label">
            <div className="wb-step-card-header">
              <div className="wb-step-badge">
                <span className="wb-step-number">{monthStepNumber}</span>
                <span id="report-month-label" className="wb-step-title">
                  业务月份
                </span>
                {activeMonths.length > 1 ? (
                  <span className="wb-step-count-pill tabular-nums">
                    已选 {activeMonths.length} 个月（{activeMonths.join('、')}）
                  </span>
                ) : activeMonths.length === 1 ? (
                  <span className="wb-step-count-pill tabular-nums">
                    已选 {activeMonths[0]}
                  </span>
                ) : (
                  <span className="wb-step-count-pill">仅开放近 3 个月选择</span>
                )}
              </div>

              {allowedMonthCodes.length > 1 && (
                <div className="wb-city-preset-group">
                  <button
                    type="button"
                    className={`wb-city-preset-btn ${allMonthsSelected ? 'is-active' : ''}`}
                    disabled={locked}
                    onClick={() =>
                      applyMonths(
                        allMonthsSelected ? [allowedMonthCodes[0]] : [...allowedMonthCodes],
                      )
                    }
                  >
                    {allMonthsSelected ? '仅选最新月' : `全选近${allowedMonthCodes.length}月`}
                  </button>
                </div>
              )}
            </div>

            <div
              className="wb-month-grid-3"
              role="group"
              aria-labelledby="report-month-label"
            >
              {recentMonths.map(item => {
                const selected = activeMonths.includes(item.month);
                return (
                  <button
                    key={item.month}
                    type="button"
                    disabled={locked}
                    aria-pressed={selected}
                    title={`${item.start} 至 ${item.end}（支持多选）`}
                    onClick={() => handleToggleMonth(item.month)}
                    className={`wb-month-card-3 tabular-nums ${selected ? 'is-selected' : ''}`}
                  >
                    <span className="wb-month-chip-left">
                      <span className="wb-month-check-box" aria-hidden="true">
                        {selected && '✓'}
                      </span>
                      <span className="wb-month-card-title">{item.label}</span>
                    </span>
                    <span className="wb-month-chip-range">
                      {item.start.slice(5)} ~ {item.end.slice(5)}
                    </span>
                  </button>
                );
              })}
            </div>

            {monthChunks.length > 1 && (
              <p className="mt-2.5 text-xs leading-relaxed text-sky-700">
                已多选非连续月份（{activeMonths.join('、')}），提交后将自动拆分为 {monthChunks.length}{' '}
                个月度批次依次生成。
              </p>
            )}

            {!range && (
              <small role="alert" className="rb-invalid">
                请在上方选择近 3 个月内的有效业务月份。
              </small>
            )}

            {scopeSummary.needsSeparation && (
              <div className="wb-date-rule-bar" role="group" aria-label="报表站点范围">
                <label className="flex items-center gap-2 cursor-pointer font-medium text-slate-700">
                  <input
                    type="checkbox"
                    aria-label="排除取分离站点"
                    checked={effectiveExcludeSeparation}
                    disabled={locked}
                    onChange={event => handleExcludeSeparationChange(event.target.checked)}
                    className="accent-sky-700 h-3.5 w-3.5 rounded border-slate-300"
                  />
                  <span>
                    排除取分离站点{' '}
                    <span className="font-normal text-slate-400">
                      （不勾选则下载全部站点）
                    </span>
                  </span>
                </label>
              </div>
            )}
          </section>
        )}
      </div>

      {/* Right Sticky Execution & Summary Rail */}
      <aside className="wb-task-preview wb-preview-compact rb-rail" aria-label="已选报表与执行核对">
        <div className="wb-compact-rail-top">
          <div className="wb-compact-rail-header">
            <div className="wb-compact-rail-title">
              <h4>{singleMode ? '当前报表' : '已选报表'}</h4>
              {!singleMode && (
                <span className="wb-compact-count-pill tabular-nums">
                  {selectedReports.length > 0 ? `已选 ${selectedReports.length} 项` : '0 项'}
                </span>
              )}
            </div>
            {!singleMode && selectedReports.length > 0 && props.onSelectIds && (
              <button
                type="button"
                className="wb-compact-clear-btn"
                disabled={locked}
                onClick={() => updateSelectedIds([])}
              >
                清空
              </button>
            )}
          </div>

          <div className="wb-compact-list-wrap">
            {selectedReports.length > 0 ? (
              <div className="wb-compact-list-surface">
                <ul className="wb-compact-dataset-list is-dense">
                  {selectedReports.map((report, index) => (
                    <li key={report.id} className="wb-compact-dataset-item">
                      <span className="wb-compact-item-index tabular-nums" aria-hidden="true">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <div className="wb-compact-item-body">
                        <div className="wb-compact-item-row">
                          <span className="wb-compact-item-name" title={report.label}>
                            {report.label}
                          </span>
                          <span className="wb-dataset-tag wb-compact-item-tag is-amber">
                            {reportScopeLabel(report.scope)}
                          </span>
                        </div>
                      </div>
                      {!singleMode && props.onSelectIds && (
                        <button
                          type="button"
                          className="wb-compact-item-remove"
                          disabled={locked}
                          title={`移除 ${report.label}`}
                          aria-label={`移除 ${report.label}`}
                          onClick={() => handleToggleReport(report.id)}
                        >
                          ×
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="wb-compact-list-footer">
                  <span className="wb-compact-footer-text">
                    {selectedReports.length > 1
                      ? `已选多份报表 · 自动拆分为 ${selectedReports.length} 批独立生成`
                      : scopeSummary.allGlobal
                        ? '全城全量整理 · 独立归档'
                        : '确认范围后即可生成业务表'}
                  </span>
                  {!blockerText && (
                    <span className="wb-compact-ready-badge is-ready">
                      配置就绪
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="wb-compact-empty">
                <span className="wb-compact-empty-dot" />
                <p>尚未选择报表类型</p>
                <small>请在左侧「01 报表类型」下拉框中勾选 1 项或多项业务报表</small>
              </div>
            )}
          </div>
        </div>

        <div className="wb-compact-rail-bottom">
          <div className="wb-compact-scope-box">
            <div className="wb-compact-scope-header">
              <span>执行范围核对</span>
            </div>
            <div className="wb-compact-scope-row">
              <span className="wb-compact-scope-k">关联系统</span>
              <span className="wb-compact-scope-v">
                {scopeSummary.systems.length ? scopeSummary.systems.join('、') : '未选择'}
              </span>
            </div>
            <div className="wb-compact-scope-row">
              <span className="wb-compact-scope-k">处理城市</span>
              <span className="wb-compact-scope-v tabular-nums" title={selectedCities.join('、')}>
                {!selectedReports.length
                  ? '待选择报表'
                  : scopeSummary.allGlobal
                    ? '全部授权城市'
                    : selectedCities.length > 0
                      ? `已选 ${selectedCities.length} 城${
                          selectedCities.length <= 2 ? `（${selectedCities.join('、')}）` : ''
                        }`
                      : '未选择城市'}
              </span>
            </div>
            {scopeSummary.needsSeparation && (
              <div className="wb-compact-scope-row">
                <span className="wb-compact-scope-k">站点范围</span>
                <span className="wb-compact-scope-v">
                  {effectiveExcludeSeparation ? '排除取分离' : '全部站点（含取分离）'}
                </span>
              </div>
            )}
            <div className="wb-compact-scope-row">
              <span className="wb-compact-scope-k">业务账期</span>
              <span className="wb-compact-scope-v wb-compact-scope-period tabular-nums">
                {!selectedReports.length
                  ? '待选择'
                  : scopeSummary.allGlobal
                    ? '当前全量（不限账期）'
                    : monthChunks.length > 1
                      ? (
                        <>
                          <span className="font-mono">{activeMonths.join('、')}</span>
                          <span className="wb-compact-period-badge">
                            共 {activeMonths.length} 个月
                          </span>
                        </>
                      )
                      : range
                        ? (
                          <>
                            <span className="font-mono">
                              {range.start.slice(5)} ~ {range.end.slice(5)}
                            </span>
                            {range.months > 0 && (
                              <span className="wb-compact-period-badge">共 {range.months} 个月</span>
                            )}
                          </>
                        )
                        : '无效月份'}
              </span>
            </div>
            <div className="wb-compact-scope-row">
              <span className="wb-compact-scope-k">交付规格</span>
              <span className="wb-compact-scope-v tabular-nums">
                {plannedBatchCount > 1
                  ? `${selectedReports.length} 份报表（分 ${plannedBatchCount} 批）`
                  : selectedReports.length === 1
                    ? '1 份业务报表'
                    : '—'}
              </span>
            </div>
          </div>

          {props.uncertain && (
            <p className="rb-rail-notice" role="status">
              上次提交结果尚未确认，范围已锁定。请确认原请求，避免重复创建。
            </p>
          )}

          {props.duplicate && !props.uncertain && selectedReports.length === 1 && (
            <div className="rb-rail-notice">
              <p>相同范围已有结果，可直接查看。</p>
              <label className="rb-rail-recollect">
                <input
                  type="checkbox"
                  checked={props.recollect}
                  disabled={locked}
                  onChange={e => props.onRecollect(e.target.checked)}
                />
                <span>重新采集，生成新版本</span>
              </label>
            </div>
          )}

          <div className="wb-compact-action-area">
            <button
              type="button"
              className="wb-compact-submit-btn wb-rail-submit-btn"
              disabled={props.disabled || !selectedReports.length || (scopeSummary.needsDate && !range)}
              onClick={props.onSubmit}
            >
              <FileSpreadsheet size={16} />
              <span>{props.creating ? '提交中…' : effectiveSubmitLabel}</span>
            </button>

            {blockerText && (
              <div className="rb-rail-blocker" role="status">
                <MapPin size={13} className="shrink-0" />
                <span>{blockerText}</span>
              </div>
            )}
          </div>
        </div>
      </aside>
    </section>
  );
}
