import React, { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import {
  Calendar as CalendarIcon,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import {
  advanceCalendarRangeSelection,
  buildCalendarMonthGrid,
  buildCalendarYearMonths,
  computeDateRangeSpanDays,
  formatDateTriggerMeta,
  type CalendarDayCell,
  type CalendarMonthCell,
} from '../lib/workbench';

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function daysInMonthUTC(year: number, month1Based: number): number {
  return new Date(Date.UTC(year, month1Based, 0)).getUTCDate();
}

function getShanghaiTodayStr(): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const pick = (t: string) => parts.find(p => p.type === t)?.value || '';
  return `${pick('year')}-${pick('month')}-${pick('day')}`;
}

export interface WorkbenchDatePickerProps {
  value: string;
  onChange: (value: string) => void;
  onRangeChange?: (start: string, end: string) => void;
  mode?: 'date' | 'month' | 'range';
  min?: string;
  max?: string;
  disabled?: boolean;
  ariaLabel?: string;
  placeholder?: string;
  rangeRole?: 'start' | 'end';
  rangeStart?: string;
  rangeEnd?: string;
  today?: string;
  allowClear?: boolean;
  align?: 'left' | 'right';
  compact?: boolean;
  prefixLabel?: string;
  activeHighlight?: boolean;
  className?: string;
}

export function WorkbenchDatePicker({
  value,
  onChange,
  onRangeChange,
  mode = 'date',
  min,
  max,
  disabled = false,
  ariaLabel,
  placeholder,
  rangeRole,
  rangeStart,
  rangeEnd,
  today: todayProp,
  allowClear = false,
  align = 'left',
  compact = false,
  prefixLabel,
  activeHighlight = false,
  className = '',
}: WorkbenchDatePickerProps) {
  const todayDate = useMemo(() => todayProp || getShanghaiTodayStr(), [todayProp]);
  const todayMonth = todayDate.slice(0, 7);
  const [open, setOpen] = useState(false);
  const [pickingMonthView, setPickingMonthView] = useState(false);
  const [pickingStep, setPickingStep] = useState<'start' | 'end'>('start');
  const [hoverDate, setHoverDate] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);

  const parseInitialYearMonth = () => {
    const source = (
      (mode === 'range' ? rangeStart || rangeEnd : value) ||
      rangeStart ||
      max ||
      todayDate ||
      '2026-01-01'
    ).trim();
    const match = /^(\d{4})-(\d{2})/.exec(source);
    if (match) {
      return { year: Number(match[1]), month: Number(match[2]) };
    }
    return { year: 2026, month: 1 };
  };

  const [viewYear, setViewYear] = useState(() => parseInitialYearMonth().year);
  const [viewMonth, setViewMonth] = useState(() => parseInitialYearMonth().month);

  useEffect(() => {
    if (open) {
      const parsed = parseInitialYearMonth();
      setViewYear(parsed.year);
      setViewMonth(parsed.month);
      setPickingMonthView(false);
      setPickingStep('start');
      setHoverDate('');
    }
  }, [open]);

  useEffect(() => {
    if (disabled && open) {
      setOpen(false);
    }
  }, [disabled, open]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const shiftMonth = (deltaMonths: number) => {
    const d = new Date(Date.UTC(viewYear, viewMonth - 1 + deltaMonths, 1));
    setViewYear(d.getUTCFullYear());
    setViewMonth(d.getUTCMonth() + 1);
  };

  const shiftYear = (deltaYears: number) => {
    setViewYear(prev => prev + deltaYears);
  };

  const effectiveRangeStart = useMemo(() => {
    if (mode === 'range' && pickingStep === 'end' && hoverDate && rangeStart) {
      return hoverDate < rangeStart ? hoverDate : rangeStart;
    }
    return rangeStart;
  }, [mode, pickingStep, hoverDate, rangeStart]);

  const effectiveRangeEnd = useMemo(() => {
    if (mode === 'range' && pickingStep === 'end' && hoverDate && rangeStart) {
      return hoverDate < rangeStart ? rangeStart : hoverDate;
    }
    return rangeEnd;
  }, [mode, pickingStep, hoverDate, rangeStart, rangeEnd]);

  const dayCells = useMemo(
    () =>
      buildCalendarMonthGrid(viewYear, viewMonth, {
        selectedDate: mode === 'range' ? effectiveRangeStart : value,
        todayDate,
        rangeStart: effectiveRangeStart,
        rangeEnd: effectiveRangeEnd,
        minDate: min,
        maxDate: max,
      }),
    [viewYear, viewMonth, mode, value, todayDate, effectiveRangeStart, effectiveRangeEnd, min, max],
  );

  const monthCells = useMemo(
    () =>
      buildCalendarYearMonths(viewYear, {
        selectedMonth: mode === 'month' ? value.slice(0, 7) : `${viewYear}-${pad2(viewMonth)}`,
        todayMonth,
        rangeStartMonth: effectiveRangeStart ? effectiveRangeStart.slice(0, 7) : undefined,
        rangeEndMonth: effectiveRangeEnd ? effectiveRangeEnd.slice(0, 7) : undefined,
        minMonth: min ? min.slice(0, 7) : undefined,
        maxMonth: max ? max.slice(0, 7) : undefined,
      }),
    [viewYear, viewMonth, mode, value, todayMonth, effectiveRangeStart, effectiveRangeEnd, min, max],
  );

  const triggerMeta = useMemo(
    () => formatDateTriggerMeta(value, mode, placeholder, rangeStart, rangeEnd),
    [value, mode, placeholder, rangeStart, rangeEnd],
  );

  const compactRangeText = useMemo(() => {
    if (mode === 'range' && rangeStart && rangeEnd) {
      if (rangeStart === rangeEnd) return rangeStart;
      if (rangeStart.slice(0, 4) === rangeEnd.slice(0, 4)) {
        return `${rangeStart} ~ ${rangeEnd.slice(5)}`;
      }
      return `${rangeStart} ~ ${rangeEnd}`;
    }
    return triggerMeta.primaryText;
  }, [mode, rangeStart, rangeEnd, triggerMeta.primaryText]);

  const spanDays = useMemo(
    () =>
      mode === 'date' || mode === 'range'
        ? computeDateRangeSpanDays(effectiveRangeStart, effectiveRangeEnd)
        : null,
    [mode, effectiveRangeStart, effectiveRangeEnd],
  );

  const clampDate = (candidate: string): string => {
    let res = candidate;
    if (min && res < min) res = min;
    if (max && res > max) res = max;
    return res;
  };

  const applyRangeValues = (nextStart: string, nextEnd: string) => {
    if (onRangeChange) {
      onRangeChange(nextStart, nextEnd);
    } else {
      onChange(nextStart);
    }
  };

  const handleSelectDay = (cell: CalendarDayCell) => {
    if (cell.isDisabled || disabled) return;
    if (mode === 'range') {
      const next = advanceCalendarRangeSelection(
        rangeStart || '',
        rangeEnd || '',
        cell.dateStr,
        pickingStep,
      );
      applyRangeValues(next.start, next.end);
      setPickingStep(next.nextStep);
      setHoverDate('');
      if (next.completed) {
        setOpen(false);
      }
      return;
    }
    onChange(cell.dateStr);
    setOpen(false);
  };

  const handleSelectMonth = (cell: CalendarMonthCell) => {
    if (cell.isDisabled || disabled) return;
    if (mode === 'month') {
      onChange(cell.monthStr);
      setOpen(false);
    } else {
      setViewMonth(cell.month);
      setPickingMonthView(false);
    }
  };

  const handleQuickToday = () => {
    if (disabled) return;
    if (mode === 'month') {
      const target2 = max && todayMonth > max.slice(0, 7) ? max.slice(0, 7) : todayMonth;
      onChange(target2);
      setOpen(false);
      return;
    }
    const target = clampDate(todayDate);
    if (mode === 'range') {
      applyRangeValues(target, target);
      setPickingStep('start');
      setHoverDate('');
      setOpen(false);
      return;
    }
    onChange(target);
    setOpen(false);
  };

  const handleQuickMonthEdge = (edge: 'first' | 'last') => {
    if (disabled) return;
    const totalDays = daysInMonthUTC(viewYear, viewMonth);
    const firstStr = clampDate(`${viewYear}-${pad2(viewMonth)}-01`);
    const lastStr = clampDate(`${viewYear}-${pad2(viewMonth)}-${pad2(totalDays)}`);
    if (mode === 'range') {
      if (edge === 'first') {
        const endTarget = clampDate(todayDate) < firstStr ? firstStr : clampDate(todayDate);
        applyRangeValues(firstStr, endTarget > lastStr ? lastStr : endTarget);
      } else {
        if (firstStr > lastStr) return;
        applyRangeValues(firstStr, lastStr);
      }
      setPickingStep('start');
      setHoverDate('');
      setOpen(false);
      return;
    }
    const raw = edge === 'first' ? firstStr : lastStr;
    if ((min && raw < min) || (max && raw > max)) return;
    onChange(raw);
    setOpen(false);
  };

  const quickTodayLabel =
    mode === 'month' ? '本月' : max && max < todayDate ? '最新可选' : '今天';
  const showMonthGrid = mode === 'month' || pickingMonthView;
  const canToggleMonthView = mode === 'date' || mode === 'range';

  return (
    <div
      ref={rootRef}
      className={`wb-datepicker ${compact ? '!w-auto inline-flex relative' : ''} ${open ? 'is-open' : ''} ${disabled ? 'is-disabled' : ''} ${className}`}
    >
      {compact ? (
        <button
          type="button"
          aria-label={ariaLabel}
          aria-haspopup="dialog"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => !disabled && setOpen(prev => !prev)}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-all cursor-pointer select-none whitespace-nowrap ${
            open || activeHighlight
              ? 'border-sky-500 bg-sky-50/90 text-sky-900 font-semibold shadow-2xs'
              : 'border-slate-200 bg-slate-50/70 text-slate-700 font-medium hover:border-sky-300 hover:bg-sky-50/40 hover:text-sky-800'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <CalendarIcon
            size={13}
            aria-hidden="true"
            className={open || activeHighlight ? 'text-sky-600 shrink-0' : 'text-slate-500 shrink-0'}
          />
          {prefixLabel && (
            <>
              <span className={open || activeHighlight ? 'text-sky-800' : 'text-slate-600'}>
                {prefixLabel}
              </span>
              <span className="text-slate-300" aria-hidden="true">
                ·
              </span>
            </>
          )}
          <span className="tabular-nums tracking-tight">{compactRangeText}</span>
          {triggerMeta.badgeText && (
            <span
              className={`rounded px-1.5 py-0.2 text-[11px] font-medium tabular-nums ${
                open || activeHighlight
                  ? 'bg-sky-600 text-white'
                  : 'bg-slate-200/80 text-slate-600'
              }`}
            >
              {triggerMeta.badgeText}
            </span>
          )}
          <ChevronDown
            size={13}
            aria-hidden="true"
            className={`transition-transform duration-150 ${
              open ? 'rotate-180 text-sky-600' : 'text-slate-400'
            }`}
          />
        </button>
      ) : (
        <button
          type="button"
          aria-label={ariaLabel}
          aria-haspopup="dialog"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => !disabled && setOpen(prev => !prev)}
          className={`wb-datepicker-trigger ${open ? 'is-open' : ''} ${triggerMeta.isEmpty ? 'is-empty' : ''}`}
        >
          <span className="wb-dp-trigger-icon" aria-hidden="true">
            <CalendarIcon size={14} />
          </span>
          <span className="wb-dp-trigger-value">{triggerMeta.primaryText}</span>
          {triggerMeta.badgeText && (
            <span className="wb-dp-trigger-badge">{triggerMeta.badgeText}</span>
          )}
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={`wb-dp-trigger-chevron ${open ? 'is-rotated' : ''}`}
          />
        </button>
      )}

      {open && (
        <div
          role="dialog"
          aria-modal="false"
          aria-label={`${ariaLabel || '日期'}选择面板`}
          className={`wb-datepicker-popover ${align === 'right' ? 'is-align-right !right-0 !left-auto' : ''}`}
        >
          <div className="wb-dp-header">
            <div className="wb-dp-nav-group">
              <button
                type="button"
                aria-label="上一年"
                onClick={() => shiftYear(-1)}
                className="wb-dp-nav-btn"
              >
                <ChevronsLeft size={14} />
              </button>
              {!showMonthGrid && (
                <button
                  type="button"
                  aria-label="上一月"
                  onClick={() => shiftMonth(-1)}
                  className="wb-dp-nav-btn"
                >
                  <ChevronLeft size={14} />
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={() => {
                if (canToggleMonthView) setPickingMonthView(prev => !prev);
              }}
              className={`wb-dp-header-title ${canToggleMonthView ? 'is-interactive' : ''}`}
              title={
                canToggleMonthView
                  ? pickingMonthView
                    ? '返回日期视图'
                    : '点击快速切换月份'
                  : undefined
              }
            >
              <span>
                {viewYear}年 {!showMonthGrid && `${pad2(viewMonth)}月`}
              </span>
              {canToggleMonthView && (
                <ChevronDown
                  size={13}
                  className={`wb-dp-title-chevron ${pickingMonthView ? 'is-rotated' : ''}`}
                />
              )}
            </button>

            <div className="wb-dp-nav-group">
              {!showMonthGrid && (
                <button
                  type="button"
                  aria-label="下一月"
                  onClick={() => shiftMonth(1)}
                  className="wb-dp-nav-btn"
                >
                  <ChevronRight size={14} />
                </button>
              )}
              <button
                type="button"
                aria-label="下一年"
                onClick={() => shiftYear(1)}
                className="wb-dp-nav-btn"
              >
                <ChevronsRight size={14} />
              </button>
            </div>
          </div>

          {((mode === 'date' && (rangeStart || rangeEnd)) || mode === 'range') && (
            <div className="wb-dp-range-banner">
              <div className="wb-dp-range-info">
                <span
                  className={`wb-dp-role-pill ${
                    mode === 'range'
                      ? pickingStep === 'end'
                        ? 'is-end'
                        : 'is-start'
                      : rangeRole === 'end'
                        ? 'is-end'
                        : 'is-start'
                  }`}
                >
                  {mode === 'range'
                    ? pickingStep === 'end'
                      ? '请点选结束日'
                      : '请点选开始日'
                    : rangeRole === 'end'
                      ? '结束'
                      : '开始'}
                </span>
                <span className="wb-dp-range-text">
                  {effectiveRangeStart || '—'}{' '}
                  <span className="wb-dp-range-arrow">→</span>{' '}
                  {effectiveRangeEnd || '—'}
                </span>
              </div>
              {spanDays !== null && <span className="wb-dp-span-badge">共 {spanDays} 天</span>}
            </div>
          )}

          {showMonthGrid ? (
            <div className="wb-dp-month-grid" role="grid" aria-label="月份选择网格">
              {monthCells.map(cell => (
                <button
                  key={cell.monthStr}
                  type="button"
                  disabled={cell.isDisabled}
                  aria-selected={cell.isSelected}
                  onClick={() => handleSelectMonth(cell)}
                  className={[
                    'wb-dp-month-cell',
                    cell.isSelected ? 'is-selected' : '',
                    !cell.isSelected && (cell.isRangeStart || cell.isRangeEnd) ? 'is-range-edge' : '',
                    cell.isInRange && !cell.isSelected ? 'is-in-range' : '',
                    cell.isCurrentMonth ? 'is-today' : '',
                    cell.isDisabled ? 'is-disabled' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  <span>{cell.label}</span>
                  {cell.isCurrentMonth && <i className="wb-dp-today-dot" aria-hidden="true" />}
                </button>
              ))}
            </div>
          ) : (
            <Fragment>
              <div className="wb-dp-weekdays" aria-hidden="true">
                {WEEKDAYS.map((dayLabel, idx) => (
                  <span
                    key={dayLabel}
                    className={`wb-dp-weekday ${idx >= 5 ? 'is-weekend' : ''}`}
                  >
                    {dayLabel}
                  </span>
                ))}
              </div>
              <div
                className="wb-dp-grid"
                role="grid"
                aria-label="日期选择网格"
                onMouseLeave={() => {
                  if (mode === 'range' && hoverDate) setHoverDate('');
                }}
              >
                {dayCells.map(cell => {
                  const isSelectedCell =
                    mode === 'range'
                      ? cell.isRangeStart || cell.isRangeEnd
                      : cell.isSelected;
                  return (
                    <button
                      key={cell.dateStr}
                      type="button"
                      disabled={cell.isDisabled}
                      aria-label={`${cell.year}年${cell.month}月${cell.day}日`}
                      aria-selected={isSelectedCell}
                      onMouseEnter={() => {
                        if (mode === 'range' && pickingStep === 'end' && !cell.isDisabled) {
                          setHoverDate(cell.dateStr);
                        }
                      }}
                      onClick={() => handleSelectDay(cell)}
                      className={[
                        'wb-dp-day',
                        cell.inCurrentMonth ? 'is-current-month' : 'is-outside-month',
                        cell.isWeekend && cell.inCurrentMonth ? 'is-weekend' : '',
                        cell.isToday ? 'is-today' : '',
                        isSelectedCell ? 'is-selected' : '',
                        !isSelectedCell && (cell.isRangeStart || cell.isRangeEnd)
                          ? 'is-range-edge'
                          : '',
                        cell.isInRange && !isSelectedCell ? 'is-in-range' : '',
                        cell.isDisabled ? 'is-disabled' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      <span className="wb-dp-day-num">{cell.day}</span>
                      {cell.isToday && <i className="wb-dp-today-dot" aria-hidden="true" />}
                    </button>
                  );
                })}
              </div>
            </Fragment>
          )}

          <div className="wb-dp-footer">
            <div className="wb-dp-quick-actions">
              <button
                type="button"
                onClick={handleQuickToday}
                className="wb-dp-quick-btn is-accent"
              >
                {quickTodayLabel}
              </button>
              {canToggleMonthView && !pickingMonthView && (
                <Fragment>
                  <button
                    type="button"
                    onClick={() => handleQuickMonthEdge('first')}
                    className="wb-dp-quick-btn"
                  >
                    {mode === 'range' ? '月初至今' : '月初'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleQuickMonthEdge('last')}
                    className="wb-dp-quick-btn"
                  >
                    {mode === 'range' ? '当月整月' : '月末'}
                  </button>
                </Fragment>
              )}
              {allowClear && value && (
                <button
                  type="button"
                  onClick={() => {
                    onChange('');
                    setOpen(false);
                  }}
                  className="wb-dp-quick-btn is-muted"
                >
                  清除
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="wb-dp-confirm-btn"
            >
              确定
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

