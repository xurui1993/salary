import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArchiveRestore,
  Calculator,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FolderOpen,
  History,
  KeyRound,
  Layers,
  Loader2,
  RotateCw,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import {
  computeTaskElapsedSeconds,
  computeTaskProgressMeta,
  formatTaskDuration,
} from '../lib/downloadCenterLogic';
import { taskGuidance, taskHandoffs } from '../lib/taskGuidance';
import { taskTone, toneClass } from '../lib/statusSemantics';
import {
  buildTaskTimelineSteps,
  cleanTaskTitle,
  formatCitiesCompact,
  formatCompactTimestamp,
  formatFileSize,
  formatPeriodCompact,
  isTaskRetryable,
  platformTone,
  resolveTaskAuthSystem,
  type TaskAuthSystem,
  type TaskDisplayRecord,
} from '../lib/taskCenterDisplay';

export type TaskDetailTab = 'files' | 'sources' | 'history';

export interface TaskDetailItem extends TaskDisplayRecord {
  batch_id?: string;
  output?: string;
  demo?: boolean;
  member_ids: string[];
  attempts: { id: string; status: string }[];
  action_run_id: string;
}

interface TaskDetailDrawerProps {
  task: TaskDetailItem | null;
  tasks: TaskDetailItem[];
  initialTab?: TaskDetailTab;
  archived: boolean;
  busy: boolean;
  nowMs: number;
  syncMs: number;
  selectedRunId: string;
  execution: React.ReactNode;
  error?: string;
  platformName: (task: TaskDetailItem) => string;
  kindLabel: (kind: string) => string;
  rawTitle: (task: TaskDetailItem) => string;
  onClose: () => void;
  onSelectTask: (task: TaskDetailItem) => void;
  onDownloadResult: (task: TaskDetailItem) => void;
  onDownloadFile: (task: TaskDetailItem, file: TaskDetailItem['files'][number]) => void;
  onDownloadSources: (task: TaskDetailItem) => void;
  onShowDirectory: (task: TaskDetailItem) => void;
  onStopTask: (task: TaskDetailItem) => void;
  onArchiveOrRestore: (task: TaskDetailItem) => void;
  onRetryTask?: (task: TaskDetailItem) => void;
  onOpenAuth?: (system: TaskAuthSystem, task: TaskDetailItem) => void;
  onNavigatePayroll?: () => void;
  onOpenPrice?: (task: TaskDetailItem) => void;
  onNavigateGenerate?: (cities: string[], start: string, end: string) => void;
  onOpenAttempt: (runId: string) => void;
  onReloadExecution: (task: TaskDetailItem) => void;
}

const ACTIVE_STATUSES = new Set([
  'queued',
  'running',
  'waiting_login',
  'waiting_manual',
  'cancelling',
  'preparing',
  'stopping',
]);

const ENDED_STATUSES = new Set(['success', 'partial', 'error', 'failed', 'cancelled', 'interrupted', 'empty']);

export function TaskDetailDrawer({
  task,
  tasks,
  initialTab,
  archived,
  busy,
  nowMs,
  syncMs,
  selectedRunId,
  execution,
  error,
  platformName,
  kindLabel,
  rawTitle,
  onClose,
  onSelectTask,
  onDownloadResult,
  onDownloadFile,
  onDownloadSources,
  onShowDirectory,
  onStopTask,
  onArchiveOrRestore,
  onRetryTask,
  onOpenAuth,
  onNavigatePayroll,
  onOpenPrice,
  onNavigateGenerate,
  onOpenAttempt,
  onReloadExecution,
}: TaskDetailDrawerProps) {
  const [tab, setTab] = useState<TaskDetailTab>('files');

  useEffect(() => {
    if (!task) return;
    if (initialTab) {
      setTab(initialTab);
      return;
    }
    if (task.files.length > 0 && ['success', 'partial'].includes(task.status)) {
      setTab('files');
    } else {
      setTab('history');
    }
  }, [task?.id, initialTab]);

  const currentIndex = task ? tasks.findIndex(item => item.id === task.id) : -1;
  const prevTask = currentIndex > 0 ? tasks[currentIndex - 1] : null;
  const nextTask = currentIndex >= 0 && currentIndex < tasks.length - 1 ? tasks[currentIndex + 1] : null;

  // 支持 ← / → 方向键快速切换上一条 / 下一条任务
  useEffect(() => {
    if (!task) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.key === 'ArrowLeft' && prevTask) {
        event.preventDefault();
        onSelectTask(prevTask);
      } else if (event.key === 'ArrowRight' && nextTask) {
        event.preventDefault();
        onSelectTask(nextTask);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [task?.id, prevTask, nextTask, onSelectTask]);

  if (!task) return null;

  const pName = platformName(task);
  const kLabel = kindLabel(task.kind);
  const displayTitle = cleanTaskTitle(rawTitle(task), pName, kLabel);
  const guidance = taskGuidance({
    status: task.status,
    kind: task.kind,
    availableFiles: task.available_files,
    failedItems: task.failed_items,
    summaryIssue: task.summary_issue,
  });
  const isActive = ACTIVE_STATUSES.has(task.status);
  const isEnded = ENDED_STATUSES.has(task.status);
  const isWaitingAuth = task.status === 'waiting_login' || task.status === 'waiting_manual';
  const authSystem = resolveTaskAuthSystem(task);
  const retryable = !archived && isTaskRetryable(task) && !!onRetryTask;
  const progressMeta = computeTaskProgressMeta(task);
  const elapsedSec = computeTaskElapsedSeconds(task, nowMs, syncMs);
  const elapsedText = formatTaskDuration(elapsedSec);
  const citiesMeta = formatCitiesCompact(task.cities);
  const periodMeta = formatPeriodCompact(task.start, task.end, task.datasets);
  const createdMeta = formatCompactTimestamp(task.created_at, nowMs);
  const pTone = platformTone(pName);

  const canDownloadSources = ['download', 'generate', 'payroll_source'].includes(task.kind) && isEnded;
  const sourceFiles = task.source_files || [];
  const handoffs = taskHandoffs(task.kind, task.datasets, task.cities);
  const timelineSteps = buildTaskTimelineSteps(task, pName);

  const showCallout = !!task.error || isWaitingAuth || (guidance.needsAction && !isActive);
  const calloutTone = ['error', 'failed', 'interrupted'].includes(task.status) ? 'danger' : 'warn';

  return (
    <WorkbenchDrawer
      title={`任务详情 · ${displayTitle}`}
      wide
      onClose={onClose}
      bodyClassName="tc-drawer-body"
    >
      <div className="tc-drawer">
        {/* 1. 顶部状态栏 + 主操作 + 上/下一条快速切换（支持 ←/→ 快捷键） */}
        <div className="tc-drawer__toolbar">
          <div className="tc-drawer__status-group">
            <span className={`wbx-pill ${toneClass(taskTone(task.status))}`}>
              {isActive && !['stopping', 'cancelling', 'waiting_login', 'waiting_manual', 'queued'].includes(task.status) ? (
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              ) : (
                <span className="wbx-pill__dot" aria-hidden="true" />
              )}
              {guidance.label}
            </span>
            {elapsedSec !== null && (
              <span className="tc-drawer__elapsed tabular-nums">
                <Clock size={12} aria-hidden="true" />
                {isActive ? `已耗时 ${elapsedText}` : `耗时 ${elapsedText}`}
              </span>
            )}
          </div>

          <div className="tc-drawer__actions">
            {task.available_files > 0 && (
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                disabled={busy}
                onClick={() => onDownloadResult(task)}
              >
                <Download size={13} aria-hidden="true" />
                <span>{task.available_files > 1 ? `打包下载 (${task.available_files})` : '下载结果'}</span>
              </button>
            )}
            {retryable && (
              <button
                type="button"
                className={`wbx-btn wbx-btn--sm${task.available_files === 0 ? ' wbx-btn--primary' : ''}`}
                disabled={busy}
                onClick={() => onRetryTask?.(task)}
              >
                <RotateCw size={12.5} aria-hidden="true" />
                <span>{task.status === 'partial' ? '重试失败项' : '重新发起'}</span>
              </button>
            )}
            {task.price_id && onOpenPrice && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                onClick={() => onOpenPrice(task)}
              >
                <ExternalLink size={13} aria-hidden="true" />
                <span>查看{task.kind === 'approval' ? '审批' : '价格'}记录</span>
              </button>
            )}
            {!archived && isActive && (
              <button
                type="button"
                className="wbx-btn wbx-btn--danger wbx-btn--sm"
                disabled={busy || ['stopping', 'cancelling'].includes(task.status)}
                onClick={() => onStopTask(task)}
              >
                <Square size={11.5} aria-hidden="true" />
                <span>{['stopping', 'cancelling'].includes(task.status) ? '停止中' : task.status === 'queued' ? '取消排队' : '停止任务'}</span>
              </button>
            )}
            {tasks.length > 1 && currentIndex >= 0 && (
              <div className="tc-drawer__pager" aria-label="切换相邻任务" title="支持键盘 ← / → 切换">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  disabled={!prevTask}
                  aria-label="上一条任务"
                  onClick={() => prevTask && onSelectTask(prevTask)}
                >
                  <ChevronLeft size={14} aria-hidden="true" />
                  <span>上一条</span>
                </button>
                <span className="tc-drawer__pager-pos tabular-nums">
                  {currentIndex + 1} / {tasks.length}
                </span>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  disabled={!nextTask}
                  aria-label="下一条任务"
                  onClick={() => nextTask && onSelectTask(nextTask)}
                >
                  <span>下一条</span>
                  <ChevronRight size={14} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 2. 实时进度条（执行中蓝色 / 等待验证琥珀色） */}
        {progressMeta.isActive && (() => {
          const pct = Math.max(0, Math.min(100, progressMeta.pct ?? 0));
          return (
            <div className={`tc-drawer__livebar${isWaitingAuth ? ' is-paused' : ''}`}>
              <div className="tc-drawer__livebar-head">
                <span className="tabular-nums">
                  {progressMeta.hasTotal
                    ? `${isWaitingAuth ? '执行已暂停' : '执行进度'}：已完成 ${task.completed_items} / ${task.total_items} 项（${pct}%）`
                    : task.status === 'queued'
                      ? '排队等待采集通道中…'
                      : isWaitingAuth
                        ? '等待完成认证或人工验证后继续…'
                        : '后台持续处理中…'}
                </span>
                <span className="tc-drawer__livebar-clock tabular-nums">已运行 {elapsedText}</span>
              </div>
              <div className="tc-drawer__track" aria-hidden="true">
                <span style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })()}

        {/* 3. 异常 / 等待认证直达提示条 */}
        {showCallout && (
          <div className={`tc-drawer__callout is-${calloutTone}`} role="status">
            <div className="tc-drawer__callout-copy">
              <AlertTriangle size={15} aria-hidden="true" />
              <span>{task.error || guidance.hint}</span>
            </div>
            <div className="tc-drawer__callout-actions">
              {isWaitingAuth && onOpenAuth && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--primary"
                  onClick={() => onOpenAuth(authSystem, task)}
                >
                  <KeyRound size={12.5} aria-hidden="true" />
                  <span>
                    {authSystem === 'fengshen'
                      ? task.status === 'waiting_manual'
                        ? '打开风神验证窗口'
                        : '打开风神登录'
                      : `前往${pName}授权`}
                  </span>
                </button>
              )}
              {task.failed_items > 0 && task.available_files > 0 && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={busy}
                  onClick={() => onDownloadResult(task)}
                >
                  先领取已有 {task.available_files} 个文件
                </button>
              )}
            </div>
          </div>
        )}

        {error && (
          <p role="alert" className="wb-error">
            {error}
          </p>
        )}

        {/* 4. 6 字段结构化业务概览 */}
        <dl className="tc-drawer__facts">
          <div>
            <dt>来源平台</dt>
            <dd>
              <span className={`tc-platform-text is-${pTone}`}>{pName}</span>
            </dd>
          </div>
          <div>
            <dt>任务类型</dt>
            <dd>{kLabel}</dd>
          </div>
          <div>
            <dt>城市范围</dt>
            <dd title={citiesMeta.full}>{citiesMeta.short}</dd>
          </div>
          <div>
            <dt>业务周期</dt>
            <dd className="tabular-nums" title={periodMeta.full}>
              {periodMeta.short}
            </dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd className="tabular-nums" title={createdMeta.full}>
              {createdMeta.short}
            </dd>
          </div>
          <div>
            <dt>任务编号</dt>
            <dd className="tabular-nums" title={task.id}>
              {task.id}
            </dd>
          </div>
        </dl>

        {/* 5. 次级快捷操作条（目录 / 复核包 / 专项报表 / 核算联动 / 移出） */}
        <div className="tc-drawer__subactions">
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            disabled={busy}
            onClick={() => onShowDirectory(task)}
          >
            <FolderOpen size={13} aria-hidden="true" />
            <span>任务目录</span>
          </button>
          {canDownloadSources && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              disabled={busy}
              onClick={() => onDownloadSources(task)}
            >
              <Download size={13} aria-hidden="true" />
              <span>下载复核资料包</span>
            </button>
          )}
          {task.status === 'success' && handoffs?.generate && onNavigateGenerate && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              onClick={() => {
                onClose();
                onNavigateGenerate(handoffs.cities, task.start, task.end);
              }}
            >
              <Sparkles size={13} aria-hidden="true" />
              <span>生成专项报表</span>
            </button>
          )}
          {task.status === 'success' && task.kind === 'download' && onNavigatePayroll && (
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              onClick={() => {
                onClose();
                onNavigatePayroll();
              }}
            >
              <Calculator size={13} aria-hidden="true" />
              <span>前往核算批次</span>
            </button>
          )}
          <button
            type="button"
            className="wbx-btn wbx-btn--sm wbx-btn--ghost tc-drawer__subactions-end"
            disabled={busy}
            onClick={() => onArchiveOrRestore(task)}
          >
            {archived ? <ArchiveRestore size={13} aria-hidden="true" /> : <Trash2 size={13} aria-hidden="true" />}
            <span>{archived ? '恢复到列表' : isActive ? '停止并移出' : '移出列表'}</span>
          </button>
        </div>

        {/* 6. 扁平化分段页签 */}
        <div className="tc-drawer__tabs" role="tablist" aria-label="任务详情分区">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'files'}
            className={`tc-drawer__tab${tab === 'files' ? ' is-active' : ''}`}
            onClick={() => setTab('files')}
          >
            <FileSpreadsheet size={13.5} aria-hidden="true" />
            <span>结果文件</span>
            <span className="tc-drawer__tab-count tabular-nums">{task.files.length}</span>
          </button>
          {(sourceFiles.length > 0 || canDownloadSources) && (
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'sources'}
              className={`tc-drawer__tab${tab === 'sources' ? ' is-active' : ''}`}
              onClick={() => setTab('sources')}
            >
              <Layers size={13.5} aria-hidden="true" />
              <span>来源原件</span>
              <span className="tc-drawer__tab-count tabular-nums">{sourceFiles.length}</span>
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'history'}
            className={`tc-drawer__tab${tab === 'history' ? ' is-active' : ''}`}
            onClick={() => setTab('history')}
          >
            <History size={13.5} aria-hidden="true" />
            <span>执行记录</span>
          </button>
        </div>

        <div className="tc-drawer__panel" role="tabpanel">
          {tab === 'files' && (
            <div className="tc-drawer__section">
              {task.files.length > 0 ? (
                <>
                  <div className="tc-drawer__section-head">
                    <span className="tc-drawer__section-title">
                      共 {task.files.length} 个结果文件 · {task.available_files} 个可直接下载
                    </span>
                  </div>
                  <ul className="tc-drawer__file-list">
                    {task.files.map(file => (
                      <li key={`${file.run_id || task.id}:${file.id}`} className="tc-drawer__file-item">
                        <div className="tc-drawer__file-info">
                          <strong title={file.name}>{file.name}</strong>
                          <small className="tabular-nums">
                            {file.city || '全量'} · {file.available !== false ? formatFileSize(file.bytes) : file.unavailable_reason || '文件不可用'}
                          </small>
                        </div>
                        <button
                          type="button"
                          className="wbx-btn wbx-btn--sm"
                          disabled={busy || file.available === false}
                          onClick={() => onDownloadFile(task, file)}
                        >
                          <Download size={13} aria-hidden="true" />
                          <span>下载</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="tc-drawer__empty">
                  {isActive
                    ? '任务正在采集中，生成结果文件后将自动展示在此处。'
                    : task.status === 'empty'
                      ? '所选业务区间内无有效数据，未生成空文件。'
                      : '当前任务暂无可下载的结果文件，请切换「执行记录」查看详情。'}
                </p>
              )}
            </div>
          )}

          {tab === 'sources' && (
            <div className="tc-drawer__section">
              {sourceFiles.length > 0 ? (
                <>
                  <div className="tc-drawer__section-head">
                    <span className="tc-drawer__section-title">关联来源原件（{sourceFiles.length} 个）</span>
                    <button
                      type="button"
                      className="wb-link"
                      disabled={busy}
                      onClick={() => onDownloadSources(task)}
                    >
                      下载复核资料包
                    </button>
                  </div>
                  <ul className="tc-drawer__file-list">
                    {sourceFiles.map(file => (
                      <li key={`${file.run_id || task.id}:${file.id}`} className="tc-drawer__file-item">
                        <div className="tc-drawer__file-info">
                          <strong title={file.name}>{file.name}</strong>
                          <small className="tabular-nums">
                            {file.city || '全量'} · {file.available !== false ? formatFileSize(file.bytes) : file.unavailable_reason || '文件不可用'}
                          </small>
                        </div>
                        <button
                          type="button"
                          className="wbx-btn wbx-btn--sm"
                          disabled={busy || file.available === false}
                          onClick={() => onDownloadFile(task, file)}
                        >
                          <Download size={13} aria-hidden="true" />
                          <span>下载</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <div className="tc-drawer__empty">
                  <p className="tc-drawer__empty-text">来源原件已归档在服务端，可用于结果口径核对与复算。</p>
                  {canDownloadSources && (
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--sm"
                      disabled={busy}
                      onClick={() => onDownloadSources(task)}
                    >
                      <Download size={13} aria-hidden="true" />
                      <span>打包领取来源资料</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {tab === 'history' && (
            <div className="tc-drawer__section">
              {task.action_run_id ? (
                <div className="tc-drawer__exec">
                  {task.attempts.length > 1 && (
                    <div className="tc-attempts">
                      {task.attempts.map((attempt, index) => (
                        <button
                          key={attempt.id}
                          type="button"
                          className="wbx-btn wbx-btn--sm"
                          aria-pressed={selectedRunId === attempt.id}
                          onClick={() => onOpenAttempt(attempt.id)}
                        >
                          {index ? `第 ${index + 1} 次执行` : '首次执行'} · {taskGuidance({ status: attempt.status }).label}
                        </button>
                      ))}
                    </div>
                  )}
                  {task.member_ids.includes(selectedRunId) ? (
                    execution
                  ) : (
                    <button type="button" className="wb-link" onClick={() => onReloadExecution(task)}>
                      加载实时处理记录
                    </button>
                  )}
                </div>
              ) : (
                <>
                  <div className="tc-drawer__section-head">
                    <span className="tc-drawer__section-title">执行时间线</span>
                  </div>
                  <ol className="tc-timeline">
                    {timelineSteps.map((step, index) => (
                      <li key={index} className={`tc-timeline__item${step.tone ? ` is-${step.tone}` : ''}`}>
                        <time className="tabular-nums">{step.time}</time>
                        <p>{step.text}</p>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </WorkbenchDrawer>
  );
}
