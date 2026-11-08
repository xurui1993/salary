import React, { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  Circle,
  Loader2,
  PlayCircle,
  Clock,
  AlertCircle,
  FolderOpen,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  PauseCircle,
} from 'lucide-react';
import { TerminalPanel } from './TerminalPanel';
import { LogEntry } from '../types';
import type { TaskItem } from './CorePage';

interface Stage {
  label: string;
  state: 'done' | 'active' | 'pending';
}

interface ExecutionCockpitProps {
  appTheme?: 'light' | 'dark';
  runKey: number;
  running: boolean;
  paused: boolean;
  title: string;
  subtitle?: string;
  progress: number;
  progressText: string;
  logs: LogEntry[];
  taskQueue: TaskItem[];
  preparationSlot?: React.ReactNode;
  onOpenOutput?: (path: string, title: string) => void;
  onBack?: () => void;
}

function CockpitTimer({ runKey, active }: { runKey: number; active: boolean }) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const startedAt = useRef<number>(Date.now());

  useEffect(() => {
    startedAt.current = Date.now();
    setElapsedMs(0);
  }, [runKey]);

  useEffect(() => {
    if (!active) return;
    setElapsedMs(Date.now() - startedAt.current);
    const timerId = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAt.current);
    }, 1000);
    return () => window.clearInterval(timerId);
  }, [active, runKey]);

  const minutes = Math.floor(elapsedMs / 60000).toString().padStart(2, '0');
  const seconds = Math.floor((elapsedMs % 60000) / 1000).toString().padStart(2, '0');
  return (
    <span className="px-2.5 py-1 rounded-full border border-sky-200 bg-sky-50 text-sky-700 font-mono text-xs tracking-wider tabular-nums">
      {minutes}:{seconds}
    </span>
  );
}

export function ExecutionCockpit({
  runKey,
  running,
  paused,
  title,
  subtitle,
  progress,
  progressText,
  logs,
  taskQueue,
  preparationSlot,
  onOpenOutput,
  onBack,
}: ExecutionCockpitProps) {
  const [logExpanded, setLogExpanded] = useState(false);
  useEffect(() => { setLogExpanded(false); }, [runKey]);

  const subStarted = taskQueue.some(t => t.status !== 'pending');
  const allSubDone =
    taskQueue.length > 0 && taskQueue.every(t => t.status === 'completed' || t.status === 'error');
  const finished = progress >= 100 && !running;

  const stages: Stage[] = taskQueue.length
    ? [
        {
          label: '资料准备',
          state: subStarted || allSubDone || finished ? 'done' : 'active',
        },
        {
          label: '分任务核算',
          state: allSubDone || finished ? 'done' : subStarted ? 'active' : 'pending',
        },
        {
          label: '汇总与输出',
          state: finished ? 'done' : allSubDone ? 'active' : 'pending',
        },
      ]
    : [];

  const doneCount = taskQueue.filter(t => t.status === 'completed').length;
  const errorCount = taskQueue.filter(t => t.status === 'error').length;


  const statusBadge = paused ? (
    <span className="flex items-center gap-1.5 px-3 py-1 rounded-full border border-amber-200 bg-amber-50 text-amber-700 text-xs font-bold">
      <PauseCircle className="w-3.5 h-3.5" />
      已暂停 · 等待处理资料
    </span>
  ) : (
    <span className="flex items-center gap-2 px-3 py-1 rounded-full border border-sky-200 bg-sky-50 text-sky-700 text-xs font-bold">
      <span className="inline-flex rounded-full h-2 w-2 bg-sky-700" />
      {running ? '执行中' : '处理中'}
    </span>
  );

  return (
    <section
      className="flex-1 min-h-0 flex flex-col gap-4"
      aria-label="任务执行驾驶舱"
    >
      {/* 头部：状态 + 标题 + 计时 */}
      <header className="shrink-0 flex flex-wrap items-center gap-3 px-5 py-4 rounded-xl border border-slate-200 bg-white">
        {statusBadge}
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-slate-900 truncate flex items-center gap-2">
            {title}
          </h2>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-0.5 truncate font-mono">
              {subtitle}
            </p>
          )}
        </div>
        <CockpitTimer runKey={runKey} active={running || paused} />
        {paused && onBack && (
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold border border-slate-300 text-slate-700 bg-white hover:bg-slate-100"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            返回准备台
          </button>
        )}
      </header>

      {/* 实时进度条与当前步骤 */}
      <div className="wb-cockpit-progress-wrap shrink-0">
        <div className="wb-cockpit-progress-header">
          <div className="flex items-center gap-2">
            <span className="text-slate-700 font-semibold text-xs">执行进度</span>
            <span className="font-mono text-xs text-sky-700 font-bold">{Math.round(progress || 0)}%</span>
          </div>
          <span className="text-xs text-slate-500 font-medium truncate max-w-md">
            {progressText || (running ? '正在处理数据与核算...' : paused ? '资料待处理' : '任务准备中')}
          </span>
        </div>
        <div className="wb-cockpit-progress-track">
          <div
            className="wb-cockpit-progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, progress || 0))}%` }}
          />
        </div>
      </div>

      {/* 主体：阶段 + 子任务 */}
      <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-4">
        {/* 左：阶段步骤 */}
        <div className="lg:w-64 shrink-0 flex flex-col gap-2.5 p-5 rounded-xl border border-slate-200 bg-white overflow-y-auto">
          <div className="text-[11px] font-bold text-slate-500 border-b border-slate-200 pb-2">
            执行阶段
          </div>
          {stages.length > 0 ? (
            stages.map(stage => (
              <div
                key={stage.label}
                className={`flex items-center gap-2.5 text-sm ${
                  stage.state === 'done'
                    ? 'text-emerald-600'
                    : stage.state === 'active'
                      ? 'text-sky-700 font-bold'
                      : 'text-slate-400'
                }`}
              >
                {stage.state === 'done' ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                ) : stage.state === 'active' ? (
                  <Loader2 className="w-4 h-4 shrink-0" />
                ) : (
                  <Circle className="w-4 h-4 shrink-0" />
                )}
                {stage.label}
              </div>
            ))
          ) : (
            <div className="flex items-center gap-2.5 text-sm text-sky-700 font-bold">
              <Loader2 className="w-4 h-4 shrink-0" />
              {paused ? '等待处理' : '资料处理中'}
            </div>
          )}
          <div className="mt-auto pt-3 border-t border-slate-200 text-[11px] leading-relaxed text-slate-500">
            {taskQueue.length > 0
              ? `子任务 ${doneCount + errorCount}/${taskQueue.length} 处理完毕${errorCount > 0 ? `，${errorCount} 个失败` : ''}`
              : '本任务不拆分子任务'}
          </div>
        </div>

        {/* 右：子任务列表 */}
        <div className="flex-1 min-w-0 flex flex-col rounded-xl border border-slate-200 bg-white overflow-hidden">
          <div className="shrink-0 px-5 py-3 border-b border-slate-200 flex items-center justify-between">
            <span className="text-sm font-bold text-slate-800">子任务</span>
            <span className="text-[11px] font-mono text-slate-500">
              {taskQueue.length > 0 ? `${doneCount}/${taskQueue.length} 完成` : '—'}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-2 min-h-0">
            {taskQueue.length === 0 ? (
              <div className="h-full min-h-[120px] flex flex-col items-center justify-center gap-2 text-slate-400">
                <Loader2 className="w-5 h-5 opacity-50" />
                <p className="text-xs">
                  {paused ? '资料尚未就绪，处理上方待办后继续' : '正在准备资料，子任务清单生成后显示'}
                </p>
              </div>
            ) : (
              taskQueue.map((task, idx) => (
                <div
                  key={task.id}
                  className={`flex items-center justify-between gap-3 px-4 py-3 rounded-lg border ${
                    task.status === 'running'
                      ? 'bg-sky-50 border-sky-600'
                      : task.status === 'completed'
                        ? 'bg-emerald-50/50 border-emerald-200 hover:border-emerald-300'
                        : task.status === 'error'
                          ? 'bg-rose-50/70 border-rose-200'
                          : 'bg-slate-50 border-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-5 flex justify-center shrink-0">
                      {task.status === 'running' && (
                        <PlayCircle className="w-4 h-4 text-sky-700" />
                      )}
                      {task.status === 'completed' && (
                        <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      )}
                      {task.status === 'error' && <AlertCircle className="w-4 h-4 text-rose-600" />}
                      {task.status === 'pending' && <Clock className="w-4 h-4 text-slate-400" />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate text-slate-800">
                        {task.status === 'pending' ? `排队 ${idx + 1} · ` : ''}
                        {task.name}
                      </p>
                      {task.fileCount !== undefined && (
                        <p className="text-[11px] text-slate-500 mt-0.5 font-mono">
                          {task.fileCount} 个文件 ·{' '}
                          {task.totalSize ? `${(task.totalSize / 1024 / 1024).toFixed(2)} MB` : ''}
                        </p>
                      )}
                    </div>
                  </div>
                  {task.outPath && (
                    <button
                      onClick={() => onOpenOutput?.(task.outPath!, `输出目录: ${task.name}`)}
                      className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-bold border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      输出目录
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 暂停待处理资料 */}
      {preparationSlot}

      {/* 底部：进度条 + 日志开关 */}
      <div className="shrink-0 rounded-xl border border-slate-200 bg-white px-5 py-4 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            {running && (
              <Loader2 className="w-3.5 h-3.5 text-sky-700 shrink-0" />
            )}
            <p className="text-xs font-mono text-slate-700 truncate">
              {progressText}
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <span className="font-mono text-sm font-bold text-sky-700 tabular-nums">
              {progress}%
            </span>
            <button
              onClick={() => setLogExpanded(v => !v)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-bold border border-slate-300 text-slate-700 bg-white hover:bg-slate-100"
            >
              {logExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              {logExpanded ? '收起技术日志' : `技术日志${errorCount ? ` · ${errorCount} 项异常` : ''}`}
            </button>
          </div>
        </div>
        <div className="h-2 rounded-full bg-slate-100 border border-slate-200 overflow-hidden">
          <div
            className="h-full rounded-full bg-sky-700"
            style={{ width: `${progress}%` }}
          />
        </div>

      </div>

      {logExpanded && (
        <div className="shrink-0 h-[280px] rounded-xl overflow-hidden border border-slate-200">
          <TerminalPanel
            logs={logs}
            progress={progress}
            progressText={progressText}
            isRunning={running}
            showFooterProgress={false}
          />
        </div>
      )}
    </section>
  );
}
