import React from 'react';
import type { LogEntry } from '../types';

export interface TerminalPanelProps {
  logs: LogEntry[];
  progress: number;
  progressText: string;
  isRunning: boolean;
  showFooterProgress?: boolean;
}

export function TerminalPanel({ logs, progressText }: TerminalPanelProps) {
  return (
    <div className="p-3 text-xs font-mono space-y-1 max-h-64 overflow-y-auto">
      {progressText ? <div className="text-slate-500 mb-2">{progressText}</div> : null}
      {logs.map(item => (
        <div key={item.id} className="flex gap-2">
          <span className="text-slate-400">{item.time}</span>
          <span>{item.text}</span>
        </div>
      ))}
    </div>
  );
}
