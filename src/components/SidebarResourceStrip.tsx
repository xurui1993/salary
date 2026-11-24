import React from 'react';
import { formatSystemResourceStats, type SystemResourceStatsInput } from '../lib/workbench';

export interface SidebarResourceStripProps {
  stats: SystemResourceStatsInput | null;
  collapsed?: boolean;
  darkRail?: boolean;
}

/**
 * 侧栏底部常驻展开式本机引擎资源面板（取消折叠弹窗，核心指标一目了然）
 */
export function SidebarResourceStrip({
  stats,
  collapsed = false,
}: SidebarResourceStripProps) {
  const view = formatSystemResourceStats(stats);
  const cpuWidth = Math.max(3, Math.min(100, view.cpuPercent));
  const memWidth = Math.max(3, Math.min(100, view.memPercent));
  const ariaSummary = `本机运算引擎状态：CPU ${view.cpuText}，内存 ${view.memText}，${view.statusText}`;

  if (collapsed) {
    return (
      <section
        className={`wbx-res-panel is-collapsed is-${view.level}`}
        aria-label={ariaSummary}
        title={`${ariaSummary}（进程 ${view.procMemMb} MB）`}
      >
        <div className="wbx-res-panel__compact-row tabular-nums">
          <span className="wbx-res-panel__compact-tag">C</span>
          <strong className="wbx-res-panel__compact-val">{view.cpuText}</strong>
        </div>
        <div className="wbx-res-panel__track" aria-hidden="true">
          <span
            className="wbx-res-panel__bar is-cpu"
            style={{ width: `${cpuWidth}%` }}
          />
        </div>
        <div className="wbx-res-panel__compact-row tabular-nums">
          <span className="wbx-res-panel__compact-tag">M</span>
          <strong className="wbx-res-panel__compact-val">{view.memText}</strong>
        </div>
        <div className="wbx-res-panel__track" aria-hidden="true">
          <span
            className="wbx-res-panel__bar is-mem"
            style={{ width: `${memWidth}%` }}
          />
        </div>
      </section>
    );
  }

  return (
    <section
      className={`wbx-res-panel is-${view.level}`}
      aria-label={ariaSummary}
    >
      <div className="wbx-res-panel__head">
        <span className="wbx-res-panel__title">本机运算引擎</span>
        <span className={`wbx-res-panel__status is-${view.level}`}>
          {view.statusText}
        </span>
      </div>

      <div className="wbx-res-panel__metrics">
        <div className="wbx-res-panel__item">
          <div className="wbx-res-panel__row tabular-nums">
            <span className="wbx-res-panel__label">
              CPU · {view.cpuCores} 核
            </span>
            <strong className="wbx-res-panel__val">{view.cpuText}</strong>
          </div>
          <div className="wbx-res-panel__track" aria-hidden="true">
            <span
              className="wbx-res-panel__bar is-cpu"
              style={{ width: `${cpuWidth}%` }}
            />
          </div>
        </div>

        <div className="wbx-res-panel__item">
          <div className="wbx-res-panel__row tabular-nums">
            <span className="wbx-res-panel__label" title={view.memDetailText}>
              内存 · {view.memDetailText}
            </span>
            <strong className="wbx-res-panel__val">{view.memText}</strong>
          </div>
          <div className="wbx-res-panel__track" aria-hidden="true">
            <span
              className="wbx-res-panel__bar is-mem"
              style={{ width: `${memWidth}%` }}
            />
          </div>
        </div>
      </div>

      <div className="wbx-res-panel__foot tabular-nums">
        <span>引擎进程占用</span>
        <strong>{view.procMemMb} MB</strong>
      </div>
    </section>
  );
}
