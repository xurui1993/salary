import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDown,
  Check,
  Copy,
  Download,
  Loader2,
  Search,
  Terminal,
  Trash2,
  X,
} from 'lucide-react';
import type { LogEntry } from '../types';
import {
  countLogLevels,
  filterLogEntries,
  formatLogsForExport,
  getLogLevelLabel,
  highlightMatchSegments,
  normalizeLogEntries,
  type LogFilterLevel,
} from '../lib/logInspector';

export interface TerminalPanelProps {
  logs: LogEntry[];
  progress: number;
  progressText: string;
  isRunning: boolean;
  showFooterProgress?: boolean;
  onClear?: () => void;
  title?: string;
  embeddedInDrawer?: boolean;
}

const FILTER_TABS: { id: LogFilterLevel; label: string }[] = [
  { id: 'ALL', label: '全部' },
  { id: 'INFO', label: '信息' },
  { id: 'SUCCESS', label: '完成' },
  { id: 'WARN', label: '警告' },
  { id: 'ERROR', label: '异常' },
];

export function TerminalPanel({
  logs,
  progress,
  progressText,
  isRunning,
  showFooterProgress = false,
  onClear,
  title = '引擎运行日志',
  embeddedInDrawer = false,
}: TerminalPanelProps) {
  const [levelFilter, setLevelFilter] = useState<LogFilterLevel>('ALL');
  const [query, setQuery] = useState('');
  const [autoFollow, setAutoFollow] = useState(true);
  const [copied, setCopied] = useState(false);
  const streamRef = useRef<HTMLDivElement>(null);

  const normalized = useMemo(() => normalizeLogEntries(logs || []), [logs]);
  const counts = useMemo(() => countLogLevels(normalized), [normalized]);
  const filtered = useMemo(
    () => filterLogEntries(normalized, { level: levelFilter, query }),
    [normalized, levelFilter, query],
  );

  useEffect(() => {
    if (!autoFollow || !streamRef.current) return;
    streamRef.current.scrollTop = streamRef.current.scrollHeight;
  }, [filtered.length, autoFollow]);

  const handleScroll = () => {
    const el = streamRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoFollow(distanceFromBottom <= 28);
  };

  const scrollToBottom = () => {
    const el = streamRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setAutoFollow(true);
  };

  const handleCopy = async () => {
    const payload = formatLogsForExport(filtered, progressText);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(payload);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = payload;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Ignore clipboard permission errors cleanly
    }
  };

  const handleDownload = () => {
    const payload = formatLogsForExport(filtered, progressText);
    const blob = new Blob([payload], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    link.href = url;
    link.download = `workbench-engine-${stamp}.log`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const clampedProgress = Math.max(0, Math.min(100, Math.round(progress || 0)));

  return (
    <section
      className={`wbx-log-panel${embeddedInDrawer ? ' wbx-log-panel--drawer' : ''}`}
      aria-label={title}
    >
      <div className="wbx-log-panel__head">
        <div className="wbx-log-panel__title-row">
          <span className="wbx-log-panel__icon" aria-hidden="true">
            {isRunning ? <Loader2 size={14} className="wbx-spin" /> : <Terminal size={14} />}
          </span>
          {!embeddedInDrawer && <strong className="wbx-log-panel__title">{title}</strong>}
          <span className="wbx-log-panel__status-text">
            {isRunning ? `实时输出中 · ${clampedProgress}%` : progressText || '就绪'}
          </span>
        </div>

        <div className="wbx-log-panel__actions">
          <button
            type="button"
            className="wbx-log-action-btn"
            onClick={() => void handleCopy()}
            disabled={filtered.length === 0}
            title="复制当前筛选日志"
          >
            {copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />}
            <span>{copied ? '已复制' : '复制'}</span>
          </button>
          <button
            type="button"
            className="wbx-log-action-btn"
            onClick={handleDownload}
            disabled={filtered.length === 0}
            title="导出为 .log 文件"
          >
            <Download size={13} />
            <span>导出</span>
          </button>
          {onClear && (
            <button
              type="button"
              className="wbx-log-action-btn"
              onClick={onClear}
              disabled={normalized.length === 0 || isRunning}
              title="清空当前日志"
            >
              <Trash2 size={13} />
              <span>清空</span>
            </button>
          )}
        </div>
      </div>

      <div className="wbx-log-panel__toolbar">
        <div className="wbx-log-filters" role="tablist" aria-label="日志级别筛选">
          {FILTER_TABS.map(tab => {
            const count = counts[tab.id];
            const active = levelFilter === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                className={`wbx-log-filter-tab is-${tab.id.toLowerCase()}${active ? ' is-active' : ''}`}
                onClick={() => setLevelFilter(tab.id)}
              >
                <span>{tab.label}</span>
                <span className="wbx-log-filter-tab__count tabular-nums">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="wbx-log-search">
          <Search size={13} className="wbx-log-search__icon" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder="检索关键词或时间…"
            className="wbx-log-search__input"
            aria-label="搜索运行日志"
          />
          {query && (
            <button
              type="button"
              className="wbx-log-search__clear"
              onClick={() => setQuery('')}
              aria-label="清除日志搜索"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      <div className="wbx-log-stream-wrap">
        <div
          ref={streamRef}
          className="wbx-log-stream"
          role="log"
          aria-live={isRunning ? 'polite' : 'off'}
          onScroll={handleScroll}
        >
          {filtered.length === 0 ? (
            <div className="wbx-log-empty">
              <span>
                {normalized.length === 0
                  ? '暂无运行日志输出，发起采集或核算任务后将在此实时流式呈现'
                  : '当前筛选条件下无匹配日志记录'}
              </span>
              {(levelFilter !== 'ALL' || query) && (
                <button
                  type="button"
                  className="wbx-log-reset-btn"
                  onClick={() => {
                    setLevelFilter('ALL');
                    setQuery('');
                  }}
                >
                  重置筛选
                </button>
              )}
            </div>
          ) : (
            filtered.map(item => {
              const segments = highlightMatchSegments(item.text, query);
              return (
                <div
                  key={item.id}
                  className={`wbx-log-row is-${item.level.toLowerCase()}`}
                >
                  <span className="wbx-log-row__index tabular-nums" aria-hidden="true">
                    {String(item.rawIndex + 1).padStart(2, '0')}
                  </span>
                  <span className="wbx-log-row__time tabular-nums">{item.time}</span>
                  <span className={`wbx-log-row__level is-${item.level.toLowerCase()}`}>
                    {getLogLevelLabel(item.level)}
                  </span>
                  <span className="wbx-log-row__text">
                    {segments.map((seg, idx) =>
                      seg.match ? (
                        <mark key={idx} className="wbx-log-mark">
                          {seg.text}
                        </mark>
                      ) : (
                        <React.Fragment key={idx}>{seg.text}</React.Fragment>
                      ),
                    )}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {!autoFollow && filtered.length > 0 && (
          <button
            type="button"
            className="wbx-log-follow-btn"
            onClick={scrollToBottom}
          >
            <ArrowDown size={13} />
            <span>回到底部</span>
          </button>
        )}
      </div>

      {showFooterProgress && (
        <div className="wbx-log-panel__foot">
          <div className="wbx-log-panel__foot-meta tabular-nums">
            <span className="truncate">{progressText || (isRunning ? '引擎执行中…' : '等待任务指令')}</span>
            <strong>{clampedProgress}%</strong>
          </div>
          <div className="wbx-progress" aria-hidden="true">
            <span
              className={`wbx-progress__bar${isRunning ? ' is-live' : ''}`}
              style={{ width: `${clampedProgress}%` }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
