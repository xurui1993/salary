import React from 'react';
import { ArrowRight } from 'lucide-react';
import type { DeductionEntry } from './DeductionAmounts';
import {
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
  const pct = total > 0 ? Math.round((summary.configuredStations / total) * 100) : 0;
  const allDone = total > 0 && summary.pendingStations === 0;
  const hasEdits = summary.cityDefaultEdited || summary.editedStations > 0;

  const cityProblemRules: ProblemRuleItem[] = ((cityEntry as any)?.problem_rules || []) as ProblemRuleItem[];
  const stationProblemTotal = stations.reduce(
    (sum, s) => sum + (((s as any)?.problem_rules || []).length || 0),
    0,
  );
  const totalKeywordRules = cityProblemRules.length + stationProblemTotal;

  const citySummaryText = cityEntry
    ? summarizeStationRow(cityEntry, visibleColumns)
    : '暂无城市默认';

  const statusMeta = hasEdits
    ? { text: '有待保存修改', tone: 'is-edited' }
    : allDone
      ? { text: '已全部配置', tone: 'is-ready' }
      : total === 0
        ? { text: '目录同步中', tone: 'is-muted' }
        : { text: `待配 ${summary.pendingStations} 站`, tone: 'is-pending' };

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
        {/* 1. 顶部城市标题与状态 */}
        <div className="wbx-city-vcard__head">
          <div className="wbx-city-vcard__title-block">
            <h3 className="wbx-city-vcard__name">{summary.cityName}</h3>
            <p className="wbx-city-vcard__subtitle tabular-nums">
              <span>{total} 个站点</span>
              <span aria-hidden="true">·</span>
              <span className={summary.cityDefaultConfigured ? 'is-ok' : 'is-warn'}>
                {summary.cityDefaultEdited
                  ? '默认已调整'
                  : summary.cityDefaultConfigured
                    ? '默认已设'
                    : '待设默认'}
              </span>
            </p>
          </div>
          <span className={`wbx-city-vcard__status ${statusMeta.tone}`}>
            {statusMeta.text}
          </span>
        </div>

        {/* 2. 纵向完成度指标区 */}
        <div className="wbx-city-vcard__progress">
          <div className="wbx-city-vcard__progress-row tabular-nums">
            <span className="wbx-city-vcard__progress-label">配置进度</span>
            <strong className="wbx-city-vcard__pct">{pct}%</strong>
          </div>
          <div className="wbx-city-vcard__bar" aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </div>
          <div className="wbx-city-vcard__progress-sub tabular-nums">
            <span>已配 {summary.configuredStations} / {total} 站</span>
            <span>{summary.overrideStations > 0 ? `${summary.overrideStations} 站例外` : '全站统一'}</span>
          </div>
        </div>

        {/* 3. 默认口径摘要区 */}
        <div className="wbx-city-vcard__policy">
          <div className="wbx-city-vcard__policy-head">
            <span>默认扣款口径</span>
            <span className="tabular-nums">
              {totalKeywordRules > 0 ? `关键词 ${totalKeywordRules} 条` : '无关键词规则'}
            </span>
          </div>
          <p className="wbx-city-vcard__policy-text tabular-nums" title={citySummaryText}>
            {citySummaryText}
          </p>
        </div>

        {/* 4. 底部行动栏 */}
        <div className="wbx-city-vcard__foot">
          <span className="wbx-city-vcard__cta">
            <span>查看扣款</span>
            <ArrowRight size={14} className="wbx-city-vcard__arrow" aria-hidden="true" />
          </span>
        </div>
      </button>
    </article>
  );
}
