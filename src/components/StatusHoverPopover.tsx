import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clock, Activity } from 'lucide-react';

export type StatusPopoverTone = 'active' | 'waiting' | 'success' | 'error' | 'muted';

export interface StatusPopoverMetric {
  label: string;
  value: string;
  tone?: 'default' | 'accent' | 'warn' | 'danger' | 'success';
}

export interface StatusPopoverModel {
  badgeLabel: string;
  tone: StatusPopoverTone;
  percent?: number | null;
  elapsedLabel: string;
  elapsedValue: string;
  currentNode: string;
  metrics: StatusPopoverMetric[];
  footnote?: string;
}

interface PopoverCoords {
  top: number;
  left: number;
  arrowLeft: number;
  placement: 'top' | 'bottom';
}

const POPOVER_WIDTH = 280;
const VIEWPORT_MARGIN = 12;
const GAP = 9;

export function StatusHoverPopover({
  model,
  children,
}: {
  model: StatusPopoverModel;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<PopoverCoords | null>(null);
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const popoverId = useId();

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger || typeof window === 'undefined') return;
    const rect = trigger.getBoundingClientRect();
    const popHeight = popoverRef.current?.offsetHeight || 168;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    const canBottom = vh - rect.bottom >= popHeight + GAP + VIEWPORT_MARGIN;
    const canTop = rect.top >= popHeight + GAP + VIEWPORT_MARGIN;
    const placement: 'top' | 'bottom' = canBottom || !canTop ? 'bottom' : 'top';

    const centerX = rect.left + rect.width / 2;
    const rawLeft = centerX - POPOVER_WIDTH / 2;
    const clampedLeft = Math.max(
      VIEWPORT_MARGIN,
      Math.min(vw - POPOVER_WIDTH - VIEWPORT_MARGIN, rawLeft),
    );
    const arrowLeft = Math.max(18, Math.min(POPOVER_WIDTH - 18, centerX - clampedLeft));

    const top =
      placement === 'top'
        ? Math.max(VIEWPORT_MARGIN, rect.top - popHeight - GAP)
        : Math.min(vh - popHeight - VIEWPORT_MARGIN, rect.bottom + GAP);

    setCoords({ top, left: clampedLeft, arrowLeft, placement });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const raf = window.requestAnimationFrame(updatePosition);
    return () => window.cancelAnimationFrame(raf);
  }, [open, updatePosition, model.currentNode, model.elapsedValue, model.percent]);

  useEffect(() => {
    if (!open) return;
    const onScrollOrResize = () => updatePosition();
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize);
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true);
      window.removeEventListener('resize', onScrollOrResize);
    };
  }, [open, updatePosition]);

  const hasPct = typeof model.percent === 'number' && Number.isFinite(model.percent);
  const clampedPct = hasPct ? Math.max(0, Math.min(100, Math.round(model.percent!))) : 0;

  return (
    <span
      ref={triggerRef}
      className="wbx-status-hover-trigger"
      tabIndex={0}
      aria-describedby={open ? popoverId : undefined}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            ref={popoverRef}
            id={popoverId}
            role="tooltip"
            className={`wbx-status-popover is-${model.tone} is-place-${coords?.placement || 'top'}`}
            style={{
              top: coords ? `${coords.top}px` : '-9999px',
              left: coords ? `${coords.left}px` : '-9999px',
              width: `${POPOVER_WIDTH}px`,
              opacity: coords ? 1 : 0,
            }}
          >
            <span
              className="wbx-status-popover__arrow"
              style={{ left: `${coords?.arrowLeft ?? POPOVER_WIDTH / 2}px` }}
              aria-hidden="true"
            />
            <div className="wbx-status-popover__head">
              <span className="wbx-status-popover__title">
                <span className="wbx-status-popover__dot" aria-hidden="true" />
                <strong>{model.badgeLabel}</strong>
              </span>
              <span className="wbx-status-popover__elapsed tabular-nums">
                <Clock size={11.5} aria-hidden="true" />
                <span>{model.elapsedLabel}</span>
                <strong>{model.elapsedValue || '—'}</strong>
              </span>
            </div>

            {hasPct && (
              <div className="wbx-status-popover__progress">
                <div className="wbx-status-popover__track" aria-hidden="true">
                  <span
                    className="wbx-status-popover__bar"
                    style={{ width: `${clampedPct}%` }}
                  />
                </div>
                <span className="wbx-status-popover__pct tabular-nums">{clampedPct}%</span>
              </div>
            )}

            <div className="wbx-status-popover__node">
              <span className="wbx-status-popover__node-label">
                <Activity size={11} aria-hidden="true" />
                <span>当前处理节点</span>
              </span>
              <p className="wbx-status-popover__node-text">{model.currentNode}</p>
            </div>

            {model.metrics.length > 0 && (
              <dl className="wbx-status-popover__metrics">
                {model.metrics.map(item => (
                  <div key={item.label} className="wbx-status-popover__metric">
                    <dt>{item.label}</dt>
                    <dd className={`tabular-nums${item.tone ? ` is-${item.tone}` : ''}`}>
                      {item.value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}

            {model.footnote && (
              <p className="wbx-status-popover__footnote">{model.footnote}</p>
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
