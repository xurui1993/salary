import React, { useEffect, useState } from 'react';
import { formatSystemResourceStats, type SystemResourceStatsInput } from '../lib/workbench';
import { areSystemStatsVisuallyEqual } from '../lib/perfUtils';

export interface SidebarResourceStripProps {
  stats?: SystemResourceStatsInput | null;
  collapsed?: boolean;
  darkRail?: boolean;
}

/**
 * 侧栏底部常驻展开式本机引擎资源面板（独立轻量轮询 + React.memo 隔离，避免触发整页根组件重渲染）
 */
export const SidebarResourceStrip = React.memo(function SidebarResourceStrip({
  stats,
  collapsed = false,
}: SidebarResourceStripProps) {
  const isControlled = stats !== undefined;
  const [internalStats, setInternalStats] = useState<SystemResourceStatsInput | null>(null);

  useEffect(() => {
    if (isControlled) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const scheduleNext = () => {
      if (disposed || document.visibilityState !== 'visible') return;
      timer = setTimeout(() => void readStats(), 8000);
    };

    const readStats = async () => {
      if (disposed || document.visibilityState !== 'visible') return;
      try {
        const res = await fetch('/api/system/stats', { signal: controller.signal });
        const data = res.ok ? await res.json() : null;
        if (!disposed && data?.success) {
          setInternalStats(prev => (areSystemStatsVisuallyEqual(prev, data) ? prev : data));
        }
      } catch {
        // ignore transient network errors
      } finally {
        scheduleNext();
      }
    };

    const onVisibility = () => {
      clearTimeout(timer);
      if (document.visibilityState === 'visible') {
        void readStats();
      }
    };

    void readStats();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [isControlled]);

  const effectiveStats = isControlled ? stats : internalStats;
  const view = formatSystemResourceStats(effectiveStats ?? null);
  const ariaSummary = `本机运算引擎状态：CPU ${view.cpuText}，内存 ${view.memText}，${view.statusText}`;
  const fullTooltip = `本机运算引擎 · ${view.statusText}\nCPU (${view.cpuCores} 核)：${view.cpuText}\n内存 (${view.memDetailText})：${view.memText}\n引擎进程占用：${view.procMemMb} MB`;

  if (collapsed) {
    return (
      <section
        className={`wbx-res-panel wbx-res-panel--mini is-collapsed is-${view.level}`}
        aria-label={ariaSummary}
        title={fullTooltip}
      >
        <span className={`wbx-res-mini__dot is-${view.level}`} aria-hidden="true" />
        <strong className="wbx-res-mini__val tabular-nums">{view.cpuText}</strong>
      </section>
    );
  }

  return (
    <section
      className={`wbx-res-panel wbx-res-panel--mini is-${view.level}`}
      aria-label={ariaSummary}
      title={fullTooltip}
    >
      <div className="wbx-res-mini__lead">
        <span className={`wbx-res-mini__dot is-${view.level}`} aria-hidden="true" />
        <span className="wbx-res-mini__title">引擎</span>
      </div>
      <div className="wbx-res-mini__metrics tabular-nums">
        <span className="wbx-res-mini__pair">
          <span className="wbx-res-mini__k">CPU</span>
          <strong className="wbx-res-mini__v">{view.cpuText}</strong>
        </span>
        <span className="wbx-res-mini__sep" aria-hidden="true">·</span>
        <span className="wbx-res-mini__pair">
          <span className="wbx-res-mini__k">内存</span>
          <strong className="wbx-res-mini__v">{view.memText}</strong>
        </span>
      </div>
    </section>
  );
});
