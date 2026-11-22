import React from 'react';
import { AlertTriangle, Loader2, Search, Sparkles, Terminal } from 'lucide-react';
import type { DispatchIslandModel } from '../lib/headerBar';

export interface DynamicDispatchIslandProps {
  model: DispatchIslandModel;
  onOpenCmdk: () => void;
  onOpenLogs: () => void;
  onOpenHistory: () => void;
}

export function DynamicDispatchIsland({
  model,
  onOpenCmdk,
  onOpenLogs,
  onOpenHistory,
}: DynamicDispatchIslandProps) {
  const handleStatusClick = () => {
    if (model.action === 'open-logs') {
      onOpenLogs();
      return;
    }
    if (model.action === 'open-history') {
      onOpenHistory();
      return;
    }
    onOpenCmdk();
  };

  if (model.mode === 'running') {
    return (
      <div className="wbx-island wbx-island--running" role="status" aria-live="polite">
        <button
          type="button"
          className="wbx-island__main"
          title="点击查看实时任务进度与日志"
          onClick={handleStatusClick}
        >
          <span className="wbx-island__pulse-icon" aria-hidden="true">
            <Loader2 size={13} className="animate-spin" />
          </span>
          <span className="wbx-island__text truncate">{model.primaryText}</span>
          <span className="wbx-island__metric tabular-nums">{model.secondaryText}</span>
        </button>
        <span className="wbx-island__sep" aria-hidden="true" />
        <button
          type="button"
          className="wbx-island__cmd-btn"
          aria-label="打开全局命令面板（快捷键 Command+K）"
          title="快速跳转 (⌘K)"
          onClick={onOpenCmdk}
        >
          <Search size={12} aria-hidden="true" />
          <kbd className="wbx-island__kbd">⌘K</kbd>
        </button>
        <span className="wbx-island__progress-track" aria-hidden="true">
          <span
            className={`wbx-island__progress-fill${model.indeterminate ? ' is-indeterminate' : ''}`}
            style={
              model.progressPct !== null
                ? { width: `${model.progressPct}%` }
                : undefined
            }
          />
        </span>
      </div>
    );
  }

  if (model.mode === 'error') {
    return (
      <div className="wbx-island wbx-island--error" role="status" aria-live="polite">
        <button
          type="button"
          className="wbx-island__main"
          title="打开运行日志终端排查异常"
          onClick={onOpenLogs}
        >
          <span className="wbx-island__alert-icon" aria-hidden="true">
            <AlertTriangle size={13} />
          </span>
          <span className="wbx-island__text truncate">{model.primaryText}</span>
          <span className="wbx-island__action-cue">
            <Terminal size={11} aria-hidden="true" />
            <span>{model.secondaryText}</span>
          </span>
        </button>
        <span className="wbx-island__sep" aria-hidden="true" />
        <button
          type="button"
          className="wbx-island__cmd-btn"
          aria-label="打开全局命令面板（快捷键 Command+K）"
          title="快速跳转 (⌘K)"
          onClick={onOpenCmdk}
        >
          <Search size={12} aria-hidden="true" />
          <kbd className="wbx-island__kbd">⌘K</kbd>
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      className="wbx-island wbx-island--idle"
      aria-label="打开全局快捷跳转面板（快捷键 Command+K 或 Ctrl+K）"
      onClick={onOpenCmdk}
    >
      <span className="wbx-island__lead">
        <span className="wbx-island__search-badge" aria-hidden="true">
          <Search size={12.5} />
        </span>
        <span className="wbx-island__placeholder">{model.primaryText}</span>
      </span>
      <span className="wbx-island__trail">
        <span className="wbx-island__hint-chip" aria-hidden="true">
          <Sparkles size={10.5} />
          <span>指令直达</span>
        </span>
        <kbd className="wbx-island__kbd">⌘K</kbd>
      </span>
    </button>
  );
}
