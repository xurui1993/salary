import type { LogEntry } from '../types';

export type NormalizedLogLevel = 'INFO' | 'SUCCESS' | 'WARN' | 'ERROR';
export type LogFilterLevel = 'ALL' | NormalizedLogLevel;

export interface NormalizedLogEntry {
  id: string;
  time: string;
  level: NormalizedLogLevel;
  text: string;
  rawIndex: number;
}

export interface LogLevelCounts {
  ALL: number;
  INFO: number;
  SUCCESS: number;
  WARN: number;
  ERROR: number;
}

export interface HighlightSegment {
  text: string;
  match: boolean;
}

export function normalizeLogLevel(level?: string, text?: string): NormalizedLogLevel {
  const upper = (level || '').toUpperCase().trim();
  if (upper === 'ERROR' || upper === 'ERR' || upper === 'FATAL') return 'ERROR';
  if (upper === 'WARN' || upper === 'WARNING') return 'WARN';
  if (upper === 'SUCCESS' || upper === 'OK' || upper === 'DONE') return 'SUCCESS';

  const body = text || '';
  if (/^\[error\]|执行失败|引擎断开|异常:/i.test(body)) return 'ERROR';
  if (/^\[warn\]|等待处理|跳过|警告/i.test(body)) return 'WARN';
  if (/任务完成|圆满完成|已成功生成|已保存至/.test(body)) return 'SUCCESS';
  return 'INFO';
}

export function normalizeLogEntries(logs: ReadonlyArray<Partial<LogEntry>>): NormalizedLogEntry[] {
  return logs.map((entry, idx) => {
    const text = String(entry?.text ?? '');
    return {
      id: entry?.id ? String(entry.id) : `log-${idx}`,
      time: entry?.time ? String(entry.time) : '--:--:--',
      level: normalizeLogLevel(entry?.level, text),
      text,
      rawIndex: idx,
    };
  });
}

export function countLogLevels(entries: ReadonlyArray<NormalizedLogEntry>): LogLevelCounts {
  const counts: LogLevelCounts = {
    ALL: entries.length,
    INFO: 0,
    SUCCESS: 0,
    WARN: 0,
    ERROR: 0,
  };
  for (const item of entries) {
    counts[item.level] += 1;
  }
  return counts;
}

export function filterLogEntries(
  entries: ReadonlyArray<NormalizedLogEntry>,
  options: { level?: LogFilterLevel; query?: string },
): NormalizedLogEntry[] {
  const level = options.level || 'ALL';
  const query = (options.query || '').trim().toLowerCase();

  return entries.filter(item => {
    if (level !== 'ALL' && item.level !== level) return false;
    if (!query) return true;
    return item.text.toLowerCase().includes(query) || item.time.toLowerCase().includes(query);
  });
}

export function highlightMatchSegments(text: string, rawQuery: string): HighlightSegment[] {
  const query = rawQuery.trim();
  if (!query || !text) {
    return [{ text, match: false }];
  }

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const segments: HighlightSegment[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    const idx = lowerText.indexOf(lowerQuery, cursor);
    if (idx === -1) {
      segments.push({ text: text.slice(cursor), match: false });
      break;
    }
    if (idx > cursor) {
      segments.push({ text: text.slice(cursor, idx), match: false });
    }
    segments.push({ text: text.slice(idx, idx + query.length), match: true });
    cursor = idx + query.length;
  }

  return segments.length ? segments : [{ text, match: false }];
}

export function formatLogsForExport(
  entries: ReadonlyArray<NormalizedLogEntry>,
  progressText?: string,
): string {
  const lines: string[] = [];
  if (progressText && progressText.trim()) {
    lines.push(`# 当前状态: ${progressText.trim()}`);
  }
  lines.push(`# 日志条数: ${entries.length}`);
  lines.push('------------------------------------------------------------');
  for (const item of entries) {
    lines.push(`[${item.time}] [${item.level.padEnd(7, ' ')}] ${item.text}`);
  }
  return lines.join('\n');
}

export function getLogLevelLabel(level: NormalizedLogLevel): string {
  switch (level) {
    case 'SUCCESS':
      return '完成';
    case 'WARN':
      return '警告';
    case 'ERROR':
      return '异常';
    default:
      return '信息';
  }
}
