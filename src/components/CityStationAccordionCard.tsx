import React from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, Tag } from 'lucide-react';
import type { DeductionEntry } from './DeductionAmounts';
import {
  extractCityCardPreview,
  summarizeStationRow,
  type CityCardGroup,
  type DeductionCategoryId,
  type ProblemRuleItem,
} from '../lib/deductionCategories';

interface CityStationAccordionCardProps {
  group: CityCardGroup;
  allEntries?: DeductionEntry[];
  columns?: string[];
  activeCategory?: DeductionCategoryId;
  visibleColumns: string[];
  expanded?: boolean;
  expandedStations?: Set<string>;
  selectedStations?: Set<string>;
  disabled?: boolean;
  onOpenCity?: (cityId: string) => void;
  onToggleCity: (cityId: string) => void;
  onToggleStation?: (stationKey: string) => void;
  onToggleAllCityStations?: (stationKeys: string[], open: boolean) => void;
  onToggleSelectStation?: (stationKey: string, checked: boolean) => void;
  onUpdateCity?: (updated: DeductionEntry) => void;
  onApplyCityToStations?: (cityEntry: DeductionEntry) => void;
  onUpdateStation?: (updated: DeductionEntry) => void;
  onBulkUpdateStations?: (updatedEntries: DeductionEntry[]) => void;
}

export function CityStationAccordionCard({
  group,
  visibleColumns,
  onOpenCity,
  onToggleCity,
}: CityStationAccordionCardProps) {
  const { summary, cityEntry, stations } = group;
  const total = summary.totalStations;
  const allDone = total > 0 && summary.pendingStations === 0;
  const hasEdits = summary.cityDefaultEdited || summary.editedStations > 0;

  const cityProblemRules: ProblemRuleItem[] = ((cityEntry as any)?.problem_rules || []) as ProblemRuleItem[];
  const stationProblemTotal = stations.reduce(
    (sum, s) => sum + (((s as any)?.problem_rules || []).length || 0),
    0,
  );
  const totalKeywordRules = cityProblemRules.length + stationProblemTotal;

  const preview = extractCityCardPreview(cityEntry, visibleColumns, 2);
  const fullSummaryTitle = cityEntry
    ? summarizeStationRow(cityEntry, visibleColumns)
    : '暂无城市默认';

  const statusMeta = hasEdits
    ? { text: '有待保存', tone: 'is-edited' }
    : allDone
      ? { text: '已配齐', tone: 'is-ready' }
      : total === 0
        ? { text: '同步中', tone: 'is-muted' }
        : { text: `待配 ${summary.pendingStations} 站`, tone: 'is-pending' };

  const overrideLabel =
    summary.overrideStations > 0 ? `${summary.overrideStations} 例外` : '统一';

  const handleOpen = () => {
    if (onOpenCity) onOpenCity(summary.cityId);
    else onToggleCity(summary.cityId);
  };

  return (
    <article
      className={`wbx-city-vcard${allDone ? ' is-complete' : ''}${hasEdits ? ' is-edited' : ''}`}
      aria-label={`${summary.cityName} 扣款配置卡片`}
    >
      <button
        type="button"
        className="wbx-city-vcard__trigger"
        onClick={handleOpen}
      >
        {/* 1. 顶部行：城市名 + 站点概况 + 轻量状态标签 */}
        <div className="wbx-city-vcard__head">
          <div className="wbx-city-vcard__head-left">
            <h3 className="wbx-city-vcard__name">{summary.cityName}</h3>
            <span className="wbx-city-vcard__subtitle tabular-nums">
              <span>{total} 个站点</span>
              <span className="wbx-city-vcard__sep" aria-hidden="true">·</span>
              <span className={summary.overrideStations > 0 ? 'is-accent' : ''}>
                {overrideLabel}
              </span>
            </span>
          </div>
          <span className={`wbx-city-vcard__status ${statusMeta.tone}`}>
            {statusMeta.text}
          </span>
        </div>

        {/* 2. 紧凑单行默认口径摘要（2 项核心指标 + 总项数，永不截断数字） */}
        <div className="wbx-city-vcard__compact-body" title={fullSummaryTitle}>
          {preview.state === 'configured' ? (
            <div className="wbx-city-vcard__inline-metrics tabular-nums">
              <span className="wbx-city-vcard__inline-group">
                {preview.metrics.map(item => (
                  <span key={item.column} className="wbx-city-vcard__inline-item">
                    <span className="wbx-city-vcard__inline-label">{item.shortLabel}</span>
                    <strong>
                      {item.unit.startsWith('元') ? '¥' : ''}
                      {item.valueText}
                    </strong>
                  </span>
                ))}
              </span>
              {preview.configuredCount > preview.metrics.length && (
                <span className="wbx-city-vcard__inline-count">
                  共 {preview.configuredCount} 项
                </span>
              )}
            </div>
          ) : preview.state === 'zero' ? (
            <span className="wbx-city-vcard__inline-state is-zero">
              <CheckCircle2 size={13} aria-hidden="true" />
              <span>{preview.zeroConfirmed ? '全项零扣款' : '全 0 待确认'}</span>
            </span>
          ) : (
            <span className="wbx-city-vcard__inline-state is-pending">
              <AlertCircle size={13} aria-hidden="true" />
              <span>待设默认（{preview.blankCount || preview.totalCount} 项）</span>
            </span>
          )}
        </div>

        {/* 3. 轻量化底行：关键词计数 + 进入箭头 */}
        <div className="wbx-city-vcard__foot">
          <span className="wbx-city-vcard__foot-meta tabular-nums">
            {totalKeywordRules > 0 ? (
              <>
                <Tag size={11} className="wbx-city-vcard__foot-icon" aria-hidden="true" />
                <span>关键词 {totalKeywordRules} 条</span>
              </>
            ) : (
              <span className={summary.cityDefaultConfigured ? 'is-ok' : 'is-warn'}>
                {summary.cityDefaultEdited
                  ? '默认已调整'
                  : summary.cityDefaultConfigured
                    ? `共 ${preview.configuredCount} 项默认`
                    : '待设默认'}
              </span>
            )}
          </span>
          <span className="wbx-city-vcard__cta">
            <span>查看扣款</span>
            <ArrowRight size={12.5} className="wbx-city-vcard__arrow" aria-hidden="true" />
          </span>
        </div>
      </button>
    </article>
  );
}
