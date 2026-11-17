import React from 'react';
import type { DeductionEntry } from './DeductionAmounts';
import { ProblemRuleEditor } from './ProblemRuleEditor';
import {
  buildDeductionCategories,
  DEDUCTION_COLUMN_UNIT,
  hasNonZeroDeduction,
  type DeductionCategoryId,
  type DeductionCategorySpec,
  type ProblemRuleItem,
} from '../lib/deductionCategories';

interface DeductionSubcardProps {
  group: DeductionCategorySpec;
  entry: DeductionEntry;
  disabled: boolean;
  isSevenGrid?: boolean;
  isPairSplit?: boolean;
  onUpdateEntry: (updated: DeductionEntry) => void;
}

function DeductionSubcard({
  group,
  entry,
  disabled,
  isSevenGrid = false,
  isPairSplit = false,
  onUpdateEntry,
}: DeductionSubcardProps) {
  const gridClass = isSevenGrid
    ? 'wbx-deduction-bento__grid is-seven'
    : isPairSplit
      ? `wbx-deduction-bento__grid is-cols-${group.columns.length}`
      : 'wbx-deduction-bento__grid is-auto';

  return (
    <div className="wbx-deduction-subcard">
      <div className="wbx-deduction-subcard__head">
        <span>{group.label}</span>
        <small>
          {group.columns.length} 项 · {group.unitHint}
        </small>
      </div>
      <div className={gridClass}>
        {group.columns.map(column => {
          const value = entry.row[column];
          const isText =
            column === '招聘来源' ||
            (typeof value === 'string' &&
              value !== '' &&
              !Number.isFinite(Number(value)));
          const unit = DEDUCTION_COLUMN_UNIT[column];
          const fieldLabel = column.replace('_maxDays', '天数阈值');

          return (
            <label key={column} className="wbx-deduction-field">
              <span className="wbx-deduction-field__label">
                <span>{fieldLabel}</span>
                {unit && <small>{unit}</small>}
              </span>
              {typeof value === 'boolean' ? (
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={value}
                  onChange={e =>
                    onUpdateEntry({
                      ...entry,
                      edited: true,
                      zero_confirmed: false,
                      row: {
                        ...entry.row,
                        [column]: e.target.checked,
                      },
                    })
                  }
                />
              ) : (
                <input
                  className="wb-input tabular-nums"
                  type={isText ? 'text' : 'number'}
                  step="any"
                  disabled={disabled}
                  aria-label={`${entry.station.name} ${column}`}
                  placeholder={column.endsWith('_maxDays') ? '沿用空白' : '待填写'}
                  value={value ?? ''}
                  onChange={e =>
                    onUpdateEntry({
                      ...entry,
                      edited: true,
                      zero_confirmed: false,
                      row: {
                        ...entry.row,
                        [column]: isText
                          ? e.target.value
                          : e.target.value === ''
                            ? null
                            : Number(e.target.value),
                      },
                    })
                  }
                />
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
}

export function DeductionBentoGroups({
  groups,
  entry,
  disabled,
  onUpdateEntry,
}: {
  groups: DeductionCategorySpec[];
  entry: DeductionEntry;
  disabled: boolean;
  onUpdateEntry: (updated: DeductionEntry) => void;
}) {
  const violationGroup = groups.find(g => g.id === 'violation');
  const toolsGroup = groups.find(g => g.id === 'tools');
  const fundGroup = groups.find(g => g.id === 'fund_monthly');
  const useSplitPair = groups.length >= 2 && Boolean(toolsGroup && fundGroup);
  const handledIds = new Set<string>();

  if (violationGroup) handledIds.add(violationGroup.id);
  if (useSplitPair && toolsGroup && fundGroup) {
    handledIds.add(toolsGroup.id);
    handledIds.add(fundGroup.id);
  }
  const restGroups = groups.filter(g => !handledIds.has(g.id));

  return (
    <div className="wbx-deduction-bento">
      {violationGroup && (
        <DeductionSubcard
          group={violationGroup}
          entry={entry}
          disabled={disabled}
          isSevenGrid={violationGroup.columns.length === 7}
          onUpdateEntry={onUpdateEntry}
        />
      )}

      {useSplitPair && toolsGroup && fundGroup && (
        <div className="wbx-deduction-bento__split">
          <DeductionSubcard
            group={toolsGroup}
            entry={entry}
            disabled={disabled}
            isPairSplit={toolsGroup.columns.length <= 4}
            onUpdateEntry={onUpdateEntry}
          />
          <DeductionSubcard
            group={fundGroup}
            entry={entry}
            disabled={disabled}
            isPairSplit={fundGroup.columns.length <= 4}
            onUpdateEntry={onUpdateEntry}
          />
        </div>
      )}

      {restGroups.map(group => (
        <DeductionSubcard
          key={group.id}
          group={group}
          entry={entry}
          disabled={disabled}
          onUpdateEntry={onUpdateEntry}
        />
      ))}
    </div>
  );
}

export function CityDeductionAmounts({
  entries,
  columns,
  disabled,
  onChange,
  activeCategory = 'all',
  onApplyToStations,
  onUpdateProblemRules,
}: {
  entries: DeductionEntry[];
  columns: string[];
  disabled: boolean;
  onChange: (entries: DeductionEntry[]) => void;
  activeCategory?: DeductionCategoryId;
  onApplyToStations?: (cityEntry: DeductionEntry) => void;
  onUpdateProblemRules?: (cityEntry: DeductionEntry, nextRules: ProblemRuleItem[]) => void;
}) {
  const update = (index: number, entry: DeductionEntry) =>
    onChange(entries.map((old, i) => (i === index ? entry : old)));

  const groups = buildDeductionCategories(columns).filter(
    group => activeCategory === 'all' || group.id === activeCategory,
  );

  return (
    <div className="city-fee-editors">
      {entries.map((entry, index) => {
        const zero = () => ({
          ...entry.row,
          ...Object.fromEntries(
            columns
              .filter(
                c =>
                  !c.endsWith('_maxDays') &&
                  (entry.row[c] === null || entry.row[c] === ''),
              )
              .map(c => [c, 0]),
          ),
        });
        const charged = hasNonZeroDeduction(entry.row, columns);
        const readyToApply = columns.every(
          c =>
            c.endsWith('_maxDays') ||
            (entry.row[c] !== null && entry.row[c] !== ''),
        );
        const cityRules = ((entry as any).problem_rules || []) as ProblemRuleItem[];

        return (
          <div key={entry.key} className="wbx-city-fee-card">
            <div className="wbx-city-fee-card__head">
              <div className="wbx-city-fee-card__title-wrap">
                <h4>{entry.station.city}</h4>
                <span
                  className={`wbx-pill ${
                    entry.edited
                      ? 'wbx-pill--progress'
                      : entry.configured
                        ? 'wbx-pill--success'
                        : 'wbx-pill--warn'
                  }`}
                >
                  <span className="wbx-pill__dot" aria-hidden="true" />
                  {entry.edited
                    ? '已调整 · 待保存'
                    : entry.configured
                      ? '已保存城市默认金额'
                      : '待配置默认金额'}
                </span>
              </div>

              <div className="wbx-city-fee-card__actions">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={disabled}
                  onClick={() =>
                    update(index, { ...entry, edited: true, row: zero() })
                  }
                >
                  空白项填零
                </button>
                {onApplyToStations && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--secondary wbx-btn--sm"
                    disabled={disabled || !readyToApply}
                    title={
                      readyToApply
                        ? '将本市统一金额批量写入当前城市所有尚未配置的站点'
                        : '请先将本市全部扣款项填写完整（或先点击空白项填零）'
                    }
                    onClick={() => onApplyToStations(entry)}
                  >
                    填充同城待配站点
                  </button>
                )}
                <label className="wbx-zero-confirm-inline">
                  <input
                    type="checkbox"
                    disabled={disabled || charged}
                    checked={entry.zero_confirmed}
                    onChange={e =>
                      update(index, {
                        ...entry,
                        edited: true,
                        zero_confirmed: e.target.checked,
                        row: e.target.checked ? zero() : entry.row,
                      })
                    }
                  />
                  确认本市默认零扣款
                </label>
              </div>
            </div>

            <DeductionBentoGroups
              groups={groups}
              entry={entry}
              disabled={disabled}
              onUpdateEntry={updated => update(index, updated)}
            />

            {onUpdateProblemRules && (
              <ProblemRuleEditor
                scopeLabel="城市问题单关键词"
                rules={cityRules}
                disabled={disabled}
                onChange={nextRules => onUpdateProblemRules(entry, nextRules)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
