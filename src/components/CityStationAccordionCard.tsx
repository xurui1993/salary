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

  const preview = extractCityCardPreview(cityEntry, visibleColumns, 3);
  const fullSummaryTitle = cityEntry
    ? summarizeStationRow(cityEntry, visibleColumns)
    : '暂无城市默认';

  const statusMeta = hasEdits
    ? { text: '有待保存', tone: 'is-edited' }
    : allDone
      ? { text: '已全部配置', tone: 'is-ready' }
      : total === 0
        ? { text: '目录同步中', tone: 'is-muted' }
        : { text: `待配 ${summary.pendingStations} 站`, tone: 'is-pending' };

  const overrideLabel =
    summary.overrideStations > 0 ? `${summary.overrideStations} 站例外` : '全站统一';

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
        {/* 1. 顶部：城市名称 + 站点概况 + 完成状态 */}
        <div className="wbx-city-vcard__head">
          <div className="wbx-city-vcard__title-block">
            <h3 className="wbx-city-vcard__name">{summary.cityName}</h3>
            <p className="wbx-city-vcard__subtitle tabular-nums">
              <span>{total} 个站点</span>
              <span className="wbx-city-vcard__sep" aria-hidden="true">·</span>
              <span className={summary.overrideStations > 0 ? 'is-accent' : ''}>
                {overrideLabel}
              </span>
            </p>
          </div>
          <span className={`wbx-city-vcard__status ${statusMeta.tone}`}>
            {statusMeta.text}
          </span>
        </div>

        {/* 2. 中部：去盒化结构化默认扣款口径预览 */}
        <div className="wbx-city-vcard__body" title={fullSummaryTitle}>
          {preview.state === 'configured' ? (
            <>
              <div className="wbx-city-vcard__section-head tabular-nums">
                <span>默认口径</span>
                <span className="wbx-city-vcard__section-meta">
                  {preview.extraCount > 0
                    ? `共 ${preview.configuredCount} 项`
                    : `${preview.configuredCount} 项已设`}
                </span>
              </div>
              <div
                className="wbx-city-vcard__metrics"
                style={{
                  gridTemplateColumns: `repeat(${preview.metrics.length}, minmax(0, 1fr))`,
                }}
              >
                {preview.metrics.map(item => (
                  <div
                    key={item.column}
                    className="wbx-city-vcard__metric"
                    title={item.unit ? `${item.column}：${item.valueText} ${item.unit}` : `${item.column}：${item.valueText}`}
                  >
                    <span className="wbx-city-vcard__metric-label">{item.shortLabel}</span>
                    <strong className="wbx-city-vcard__metric-value tabular-nums">
                      {item.unit.startsWith('元') && (
                        <span className="wbx-city-vcard__metric-unit" aria-hidden="true">¥</span>
                      )}
                      {item.valueText}
                    </strong>
                  </div>
                ))}
              </div>
            </>
          ) : preview.state === 'zero' ? (
            <div className="wbx-city-vcard__state is-zero">
              <span className="wbx-city-vcard__state-title">
                <CheckCircle2 size={13.5} aria-hidden="true" />
                <span>{preview.zeroConfirmed ? '全项零扣款' : '全 0 待确认'}</span>
              </span>
              <span className="wbx-city-vcard__state-sub tabular-nums">
                {preview.zeroConfirmed
                  ? `已确认 ${preview.totalCount} 项均不扣款`
                  : `共 ${preview.totalCount} 项金额为 0，进入可一键确认`}
              </span>
            </div>
          ) : (
            <div className="wbx-city-vcard__state is-pending">
              <span className="wbx-city-vcard__state-title">
                <AlertCircle size={13.5} aria-hidden="true" />
                <span>默认口径待配置</span>
              </span>
              <span className="wbx-city-vcard__state-sub tabular-nums">
                待填写 {preview.blankCount || preview.totalCount} 项城市默认规则
              </span>
            </div>
          )}
        </div>

        {/* 3. 底部：关键词规则摘要 + 查看扣款入口 */}
        <div className="wbx-city-vcard__foot">
          <span className="wbx-city-vcard__foot-meta tabular-nums">
            {totalKeywordRules > 0 ? (
              <>
                <Tag size={11.5} className="wbx-city-vcard__foot-icon" aria-hidden="true" />
                <span>关键词 {totalKeywordRules} 条</span>
              </>
            ) : (
              <span className={summary.cityDefaultConfigured ? 'is-ok' : 'is-warn'}>
                {summary.cityDefaultEdited
                  ? '默认已调整'
                  : summary.cityDefaultConfigured
                    ? '默认已设'
                    : '待设默认'}
              </span>
            )}
          </span>
          <span className="wbx-city-vcard__cta">
            <span>查看扣款</span>
            <ArrowRight size={13.5} className="wbx-city-vcard__arrow" aria-hidden="true" />
          </span>
        </div>
      </button>
    </article>
  );
}
