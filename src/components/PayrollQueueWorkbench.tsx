import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArchiveRestore,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Download,
  FileSpreadsheet,
  FolderOpen,
  Loader2,
  Pencil,
  Search,
  ShieldAlert,
  Square,
  UploadCloud,
  X,
} from 'lucide-react';
import type { CorePageProps } from './CorePage';
import { ControlPanel } from './ControlPanel';
import { PayrollBatchDetailDrawer, type PayrollDetailTab } from './PayrollBatchDetailDrawer';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { StatusHoverPopover } from './StatusHoverPopover';
import { WorkbenchConfirmModal, WorkbenchToast, type ToastNotice } from './WorkbenchFeedback';
import { toneClass } from '../lib/statusSemantics';
import { SystemTemplatesPanel } from './SystemTemplatesPanel';
import { readDownloadResponse, saveDownloadBlob } from '../lib/outputDownload';
import { businessLogEntries } from '../lib/payrollBusinessLogs';
import {
  buildPayrollProgressPopoverData,
  detectDuplicateUploadNames,
  extractPayrollAmount,
  extractPayrollReviewAlert,
  formatPayrollAmount,
  legacyPayrollTask,
  payrollCycleLabel,
  payrollElapsed,
  payrollModeName,
  payrollPeriodRange,
  payrollQueueRunning,
  payrollQueueStatus,
  payrollTypeTone,
  resolvePayrollElapsedText,
  sortPayrollTasks,
  summarizePayrollTasks,
  type PayrollQueueTask,
  type PayrollSortKey,
} from '../lib/payrollQueue';
import { paginateEntries } from '../lib/deductionCategories';
import {
  filterPayrollQueueAdvanced,
  filterPayrollQueueTasks,
  type PayrollQueueFilterTab,
} from '../lib/workbenchFilters';
import { buildDemoPayrollTasks } from '../lib/showcaseDemoData';

type Props = Pick<
  CorePageProps,
  | 'config'
  | 'onConfigChange'
  | 'progress'
  | 'progressText'
  | 'logs'
  | 'payrollPreparation'
  | 'apiFetch'
  | 'onPreparationChange'
  | 'onUploadFiles'
  | 'onRun'
  | 'onOpenConnections'
  | 'onOpenFengshenLogin'
  | 'onOpenDeductions'
  | 'onOpenSettings'
  | 'onNavigateTaskCenter'
  | 'uploadExtracted'
> & { isRunning: boolean };

const API = '/api/parttime/queue';

function taskLabel(task: PayrollQueueTask) {
  return (task.approval_code || '').trim() || '未填写审批编号的任务';
}

function ApprovalCell({
  task,
  onSave,
}: {
  task: PayrollQueueTask;
  onSave: (task: PayrollQueueTask, code: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(task.approval_code || '');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!editing) setDraft(task.approval_code || '');
  }, [task.approval_code, editing]);
  const code = (task.approval_code || '').trim();
  const cancel = () => {
    setDraft(task.approval_code || '');
    setEditing(false);
  };
  const commit = async () => {
    const next = draft.trim();
    if (next === code) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(task, next);
      setEditing(false);
    } catch {
      /* Keep editor open so the number can be corrected. */
    } finally {
      setSaving(false);
    }
  };
  if (task.legacy) {
    return (
      <span className={`pq-code-text${code ? ' tabular-nums' : ' is-empty'}`} title="历史批次审批编号请在原批次维护">
        {code || '待填写审批编号'}
      </span>
    );
  }
  if (editing) {
    return (
      <div className="pq-approval-edit" onClick={event => event.stopPropagation()}>
        <input
          autoFocus
          value={draft}
          maxLength={64}
          placeholder="填写审批编号"
          aria-label="核算审批编号"
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') void commit();
            else if (event.key === 'Escape') cancel();
          }}
        />
        <button
          type="button"
          className="pq-icon-button"
          title={saving ? '保存中' : '保存审批编号'}
          aria-label="保存审批编号"
          disabled={saving}
          onClick={() => void commit()}
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Check size={14} />}
        </button>
        <button
          type="button"
          className="pq-icon-button"
          title="取消修改"
          aria-label="取消修改审批编号"
          disabled={saving}
          onClick={cancel}
        >
          <X size={14} />
        </button>
      </div>
    );
  }
  return (
    <div className="pq-approval" onClick={event => event.stopPropagation()}>
      <button
        type="button"
        className={`pq-code-text${code ? ' tabular-nums' : ' is-empty'}`}
        title={code || '点击填写核算审批编号'}
        onClick={() => setEditing(true)}
      >
        {code || '待填写审批编号'}
      </button>
      <button
        type="button"
        className="pq-icon-button pq-approval-edit-btn"
        title={code ? '修改审批编号' : '填写审批编号'}
        aria-label={`${code ? '修改' : '填写'} ${taskLabel(task)}`}
        onClick={() => setEditing(true)}
      >
        <Pencil size={12.5} />
      </button>
    </div>
  );
}

export function PayrollQueueTable({
  tasks,
  selectedId,
  activeDetailId,
  checked,
  onSelect,
  onOpenDetail,
  onCheck,
  onCheckAll,
  onStop,
  onRemove,
  onDownload,
  onOpenDirectory,
  onRestore,
  onApproval,
  busy = false,
  hidden = false,
}: {
  tasks: PayrollQueueTask[];
  selectedId?: string;
  activeDetailId?: string;
  expandedId?: string;
  checked: string[];
  onSelect: (id: string) => void;
  onOpenDetail?: (id: string, tab?: PayrollDetailTab) => void;
  onToggleExpand?: (id: string) => void;
  onCheck: (id: string) => void;
  onCheckAll: () => void;
  onStop: (task: PayrollQueueTask) => void;
  onRemove: (tasks: PayrollQueueTask[]) => void;
  onDownload: (task: PayrollQueueTask) => void;
  onOpenDirectory?: (task: PayrollQueueTask) => void;
  onRestore: (tasks: PayrollQueueTask[]) => void;
  onApproval: (task: PayrollQueueTask, code: string) => Promise<void>;
  renderDetail?: (task: PayrollQueueTask) => React.ReactNode;
  busy?: boolean;
  hidden?: boolean;
}) {
  const allChecked = tasks.length > 0 && tasks.every(task => checked.includes(task.id));
  return (
    <div className="pq-table-scroll wbx-table-scroll wbx-payroll__scroll">
      <table className="pq-table wbx-table wbx-payroll__table">
        <thead>
          <tr>
            <th className="pq-check">
              <input
                type="checkbox"
                aria-label="选择全部任务"
                checked={allChecked}
                disabled={!tasks.length || busy}
                onChange={onCheckAll}
              />
            </th>
            <th className="pq-col-approval">审批编号</th>
            <th className="pq-col-city">城市</th>
            <th className="pq-col-period">周期</th>
            <th className="pq-col-type">类型</th>
            <th className="pq-col-applicants">人数</th>
            <th className="pq-col-amount">金额</th>
            <th className="pq-col-progress">核算进度</th>
            <th className="pq-col-ops">操作</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map(task => {
            const state = payrollQueueStatus(task.status);
            const running = payrollQueueRunning(task);
            const done = task.status === 'completed';
            const isWaiting = task.status === 'waiting_confirmation' || task.status === 'waiting_materials';
            const isError = task.status === 'error' || task.status === 'interrupted';
            const isDetailOpen = activeDetailId === task.id;
            const errorHint =
              task.status === 'error' && !task.current_action
                ? businessLogEntries(task.logs?.length ? task.logs : task.preparation?.execution_logs)
                    .business.filter(entry => /ERROR|WARN/.test(entry.level || ''))
                    .pop()?.text || ''
                : '';
            const progressDesc = task.current_action || errorHint;
            const cycleLabel = payrollCycleLabel(task.plan);
            const periodRange = payrollPeriodRange(task.plan);
            const typeTone = payrollTypeTone(task.mode);
            const amount = extractPayrollAmount(task);
            const reviewAlert = extractPayrollReviewAlert(task);
            const pct = Number.isFinite(task.progress) ? Math.max(0, Math.min(100, Math.round(task.progress))) : 0;
            const showProgressBar = running && task.status !== 'queued' && pct > 0;
            const popoverModel = buildPayrollProgressPopoverData(task, {
              fallbackAction: progressDesc,
            });

            return (
              <tr
                key={task.id}
                className={`pq-row${task.id === selectedId ? ' is-selected' : ''}${isDetailOpen ? ' is-detail-open' : ''}`}
                onClick={() => {
                  onSelect(task.id);
                  onOpenDetail?.(task.id);
                }}
              >
                <td className="pq-check">
                  <input
                    type="checkbox"
                    aria-label={`选择任务 ${taskLabel(task)}`}
                    checked={checked.includes(task.id)}
                    disabled={busy}
                    onClick={event => event.stopPropagation()}
                    onChange={() => onCheck(task.id)}
                  />
                </td>
                <td className="pq-col-approval">
                  <ApprovalCell task={task} onSave={onApproval} />
                </td>
                <td className="pq-col-city">
                  <span className={`pq-city-text${task.plan?.city ? '' : ' is-muted'}`}>
                    {task.plan?.city || (task.status === 'queued' ? '待识别' : '识别中')}
                  </span>
                </td>
                <td className="pq-col-period">
                  <span className="pq-period-inline tabular-nums">
                    {periodRange || (task.plan ? '—' : '按上传顺序')}
                  </span>
                </td>
                <td className="pq-col-type">
                  <span className={`pq-type-text is-${typeTone}`}>{payrollModeName(task)}</span>
                  {task.legacy && <small className="pq-type-legacy">历史</small>}
                </td>
                <td className="pq-col-applicants tabular-nums">
                  {task.plan?.applicants != null ? (
                    <span className="pq-num-text">{task.plan.applicants}</span>
                  ) : (
                    <span className="pq-empty-val">—</span>
                  )}
                </td>
                <td className="pq-col-amount tabular-nums">
                  {amount !== null ? (
                    <span className="pq-amount-text">
                      <span className="pq-currency-sign">¥</span>
                      {formatPayrollAmount(amount)}
                    </span>
                  ) : (
                    <span className="pq-empty-val">—</span>
                  )}
                </td>
                <td className="pq-col-progress">
                  <div className="pq-progress-top">
                    <StatusHoverPopover model={popoverModel}>
                      <span
                        className={`wbx-pill ${toneClass(state.tone)}${showProgressBar ? ' wbx-pill--has-progress' : ''}`}
                        aria-label={showProgressBar ? `${state.label} ${pct}%` : state.label}
                      >
                        {showProgressBar && (
                          <span
                            className="wbx-pill__fill"
                            style={{ width: `${pct}%` }}
                            aria-hidden="true"
                          />
                        )}
                        <span className="wbx-pill__content">
                          <span className="wbx-pill__lead">
                            {running && task.status !== 'stopping' && task.status !== 'queued' ? (
                              <Loader2 size={11.5} className="animate-spin wbx-pill__icon" aria-hidden="true" />
                            ) : (
                              <span className="wbx-pill__dot" aria-hidden="true" />
                            )}
                            <span className="wbx-pill__label">{state.label}</span>
                          </span>
                          {showProgressBar && (
                            <span className="wbx-pill__pct tabular-nums">{pct}%</span>
                          )}
                        </span>
                      </span>
                    </StatusHoverPopover>
                    {reviewAlert ? (
                      <button
                        type="button"
                        className="pq-review-alert-btn tabular-nums"
                        title="存在复核风险提示，点击直接查看复核摘要"
                        onClick={event => {
                          event.stopPropagation();
                          onSelect(task.id);
                          onOpenDetail?.(task.id, 'review');
                        }}
                      >
                        <span>· {reviewAlert.label}</span>
                      </button>
                    ) : null}
                  </div>
                </td>
                {/* 精简操作列：仅保留场景主操作、停止与移出，点击整行直接展开详情抽屉 */}
                <td className="pq-col-ops">
                  <div className="pq-row-actions" onClick={event => event.stopPropagation()}>
                    {hidden ? (
                      <button
                        type="button"
                        className="pq-op-cta is-primary"
                        disabled={busy}
                        onClick={() => onRestore([task])}
                      >
                        <span>恢复</span>
                      </button>
                    ) : (
                      <>
                        {done && task.batch_id && (
                          <>
                            <button
                              type="button"
                              className="pq-op-cta is-primary"
                              title="下载核算成品包"
                              aria-label={`下载 ${taskLabel(task)} 核算成品包`}
                              disabled={busy}
                              onClick={() => onDownload(task)}
                            >
                              <span>下载</span>
                            </button>
                            <button
                              type="button"
                              className="pq-icon-btn"
                              title="打开本地结果目录"
                              aria-label={`打开 ${taskLabel(task)} 结果目录`}
                              disabled={busy}
                              onClick={() => onOpenDirectory?.(task)}
                            >
                              <FolderOpen size={13.5} aria-hidden="true" />
                            </button>
                          </>
                        )}
                        {isWaiting && (
                          <button
                            type="button"
                            className="pq-op-cta is-warn"
                            onClick={() => {
                              onSelect(task.id);
                              onOpenDetail?.(
                                task.id,
                                task.status === 'waiting_confirmation' ? 'deductions' : 'activity',
                              );
                            }}
                          >
                            <span>{task.status === 'waiting_confirmation' ? '确认扣款' : '去处理'}</span>
                          </button>
                        )}
                        {isError && (
                          <button
                            type="button"
                            className="pq-op-cta is-danger"
                            onClick={() => {
                              onSelect(task.id);
                              onOpenDetail?.(task.id, 'activity');
                            }}
                          >
                            <span>查看原因</span>
                          </button>
                        )}
                        {running && (
                          <button
                            type="button"
                            className="pq-stop-btn"
                            title={
                              task.status === 'stopping'
                                ? '停止中'
                                : task.status === 'queued'
                                  ? '取消排队'
                                  : '停止任务'
                            }
                            aria-label={`${task.status === 'queued' ? '取消排队' : '停止'} ${taskLabel(task)}`}
                            disabled={busy || task.status === 'stopping'}
                            onClick={() => onStop(task)}
                          >
                            {task.status === 'stopping' ? '停止中' : task.status === 'queued' ? '取消' : '停止'}
                          </button>
                        )}
                        {((done && task.batch_id) || isWaiting || isError || running) && (
                          <span className="pq-op-sep" aria-hidden="true" />
                        )}
                        <button
                          type="button"
                          className="pq-icon-btn pq-remove-btn"
                          title={running ? '停止并移出' : '移出任务'}
                          aria-label={`${running ? '停止并移出' : '移出'} ${taskLabel(task)}`}
                          disabled={busy || task.status === 'stopping'}
                          onClick={() => onRemove([task])}
                        >
                          <X size={13.5} aria-hidden="true" />
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!tasks.length && (
        <div className="pq-empty">
          <FileSpreadsheet size={28} />
          <strong>{hidden ? '没有已移出的任务' : '还没有核算任务'}</strong>
          <p>{hidden ? '移出只隐藏记录，原文件始终保留。' : '上传多个模板后，每份模板会建立一个独立任务。'}</p>
        </div>
      )}
    </div>
  );
}

export function PayrollTaskActivity({ logs }: { logs: PayrollQueueTask['logs'] }) {
  const { business, technical } = businessLogEntries(logs || []);
  const recent = business.slice(-5);
  return (
    <div className="pq-activity">
      <h4>任务动态</h4>
      {recent.length ? (
        <ol className="pq-log-list">{recent.map((entry, index) => logLine(entry, index))}</ol>
      ) : (
        <p className="wbx-hint">任务开始后在这里显示关键进展。</p>
      )}
      {business.length > 5 && (
        <details className="pq-disclosure">
          <summary>全部业务记录（{business.length}）</summary>
          <ol className="pq-log-list pq-log-history">{business.map((entry, index) => logLine(entry, index))}</ol>
        </details>
      )}
      {!!technical.length && (
        <details className="pq-disclosure pq-technical">
          <summary>详细诊断（{technical.length}）</summary>
          <pre>{technical.map(entry => entry.text).join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

function logLine(entry: { time?: string; text: string; level?: string }, index: number) {
  return (
    <li key={index} className={/ERROR|WARN/.test(entry.level || '') ? 'is-attention' : ''}>
      {entry.time && <time>{formatLogTime(entry.time)}</time>}
      <span>{entry.text}</span>
    </li>
  );
}

function formatLogTime(value: string) {
  const date = new Date(value);
  if (Number.isFinite(date.getTime())) {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date);
  }
  return value.match(/(?:T|\s)(\d{2}:\d{2}(?::\d{2})?)/)?.[1] || value;
}

export function FlashPayrollWorkbench({
  config,
  onConfigChange,
  progress,
  progressText,
  logs,
  payrollPreparation: value,
  apiFetch,
  onPreparationChange,
  onUploadFiles,
  onOpenConnections,
  onOpenFengshenLogin,
  onOpenDeductions,
  onNavigateTaskCenter,
}: Props) {
  const [tasks, setTasks] = useState<PayrollQueueTask[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [checked, setChecked] = useState<string[]>([]);
  const [detailTaskId, setDetailTaskId] = useState('');
  const [detailTab, setDetailTab] = useState<PayrollDetailTab | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [toast, setToast] = useState<ToastNotice | null>(null);
  const [templates, setTemplates] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [removeTargets, setRemoveTargets] = useState<PayrollQueueTask[]>([]);
  const [skipLegacy, setSkipLegacy] = useState(false);
  const [intakeCollapsed, setIntakeCollapsed] = useState(false);

  // 多维筛选与排序状态
  const [queueFilterTab, setQueueFilterTab] = useState<PayrollQueueFilterTab>('all');
  const [queueSearch, setQueueSearch] = useState('');
  const [cityFilter, setCityFilter] = useState('');
  const [modeFilter, setModeFilter] = useState('');
  const [missingApprovalOnly, setMissingApprovalOnly] = useState(false);
  const [sortKey, setSortKey] = useState<PayrollSortKey>('default');
  const [queuePage, setQueuePage] = useState(1);
  const [queuePageSize, setQueuePageSize] = useState(20);

  const [demoEnabled, setDemoEnabled] = useState(true);
  const [demoTasks, setDemoTasks] = useState<PayrollQueueTask[]>(() => buildDemoPayrollTasks());
  const [demoHiddenIds, setDemoHiddenIds] = useState<string[]>([]);

  const api = useRef(apiFetch);
  api.current = apiFetch;
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const guard = useRef(false);
  const fetching = useRef(false);
  const readController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const excludeSeparation = config.payrollExcludeSeparation ?? true;

  const pushToast = useCallback((text: string, tone: ToastNotice['tone'] = 'success') => {
    setToast({ id: Date.now() + Math.random(), tone, text });
  }, []);

  const request = useCallback(async (url: string, body?: unknown) => {
    const response = await api.current(
      url,
      body === undefined
        ? { cache: 'no-store', signal: AbortSignal.timeout(120000) }
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(120000),
          },
    );
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw Error(
        typeof result.detail === 'string'
          ? result.detail
          : typeof result.error === 'string'
            ? result.error
            : `操作未完成（${response.status}），请检查连接后再操作。`,
      );
    }
    return response;
  }, []);

  const refreshSeq = useRef(0);
  const refresh = useCallback(
    async (force = false) => {
      if (fetching.current && !force) return null;
      if (fetching.current && force) {
        const deadline = Date.now() + 4000;
        while (fetching.current && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 50));
        }
      }
      fetching.current = true;
      const seq = ++refreshSeq.current;
      const controller = new AbortController();
      readController.current = controller;
      try {
        const parameters = new URLSearchParams();
        if (hidden) parameters.set('hidden', 'true');
        if (selectedRef.current) parameters.set('detail_id', selectedRef.current);
        const response = await api.current(API + (parameters.size ? '?' + parameters.toString() : ''), {
          cache: 'no-store',
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
        });
        const result = await response.json();
        if (!response.ok || !Array.isArray(result.tasks)) {
          throw Error(typeof result.detail === 'string' ? result.detail : '任务队列暂时无法更新');
        }
        if (mounted.current && !controller.signal.aborted && seq === refreshSeq.current) {
          setTasks(result.tasks);
          setLoadError('');
        }
        return result.tasks as PayrollQueueTask[];
      } catch (e) {
        if (mounted.current && !controller.signal.aborted && seq === refreshSeq.current) {
          setLoadError(e instanceof Error ? e.message : '任务队列暂时无法更新');
        }
        return null;
      } finally {
        if (seq === refreshSeq.current) fetching.current = false;
        if (mounted.current && seq === refreshSeq.current) setLoading(false);
      }
    },
    [hidden],
  );

  useEffect(() => {
    mounted.current = true;
    void refresh();
    let timer = 0;
    const interval = () => (document.visibilityState === 'visible' ? 2500 : 10000);
    const schedule = () => {
      window.clearInterval(timer);
      timer = window.setInterval(() => void refresh(), interval());
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void refresh();
      schedule();
    };
    schedule();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
      readController.current?.abort();
    };
  }, [refresh]);

  useEffect(() => {
    void refresh();
  }, [selectedId, refresh]);

  useEffect(() => {
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{ tasks?: PayrollQueueTask[] }>).detail;
      const incoming = Array.isArray(detail?.tasks) ? detail.tasks : [];
      if (incoming.length) {
        setTasks(previous => {
          const merged = new Map(previous.map(task => [task.id, task]));
          for (const task of incoming) merged.set(task.id, task);
          return Array.from(merged.values());
        });
        setLoading(false);
        setSelectedId(previous => previous || incoming[0].id);
        pushToast(`已提交 ${incoming.length} 个核算任务，正在同步队列…`, 'info');
      }
      void refresh(true);
    };
    window.addEventListener('payroll-queue:changed', changed);
    return () => window.removeEventListener('payroll-queue:changed', changed);
  }, [refresh, pushToast]);

  useEffect(() => {
    setChecked([]);
    setSelectedId('');
    setDetailTaskId('');
    setTasks([]);
    setLoading(true);
  }, [hidden]);

  useEffect(() => {
    setSkipLegacy(false);
  }, [value?.id]);

  const legacy =
    value && !hidden && !skipLegacy && !tasks.some(task => task.batch_id === value.id)
      ? legacyPayrollTask(value, logs, progress, progressText)
      : null;
  const liveVisible = legacy ? [legacy, ...tasks] : tasks;
  const hasLiveData = liveVisible.length > 0;
  const usingDemo = !hasLiveData && demoEnabled;

  const visible = useMemo(() => {
    if (hasLiveData) return liveVisible;
    if (!demoEnabled) return [];
    return hidden
      ? demoTasks.filter(task => demoHiddenIds.includes(task.id))
      : demoTasks.filter(task => !demoHiddenIds.includes(task.id));
  }, [hasLiveData, liveVisible, demoEnabled, hidden, demoTasks, demoHiddenIds]);

  const availableCities = useMemo(() => {
    const set = new Set<string>();
    for (const t of visible) {
      if (t.plan?.city) set.add(t.plan.city);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [visible]);

  const filteredVisible = useMemo(() => {
    const filtered = filterPayrollQueueAdvanced(visible, {
      tab: queueFilterTab,
      keyword: queueSearch,
      city: cityFilter,
      mode: modeFilter,
      missingApprovalOnly,
    });
    return sortPayrollTasks(filtered, sortKey);
  }, [visible, queueFilterTab, queueSearch, cityFilter, modeFilter, missingApprovalOnly, sortKey]);

  const summary = useMemo(() => summarizePayrollTasks(filteredVisible), [filteredVisible]);
  const pagedQueue = useMemo(
    () => paginateEntries(filteredVisible, queuePage, queuePageSize),
    [filteredVisible, queuePage, queuePageSize],
  );
  const pagedTasks = pagedQueue.items;

  const tabCounts = useMemo(
    () => ({
      all: visible.length,
      active: filterPayrollQueueTasks(visible, 'active', '').length,
      waiting: filterPayrollQueueTasks(visible, 'waiting', '').length,
      completed: filterPayrollQueueTasks(visible, 'completed', '').length,
      issue: filterPayrollQueueTasks(visible, 'issue', '').length,
    }),
    [visible],
  );

  const selected =
    filteredVisible.find(task => task.id === selectedId) ||
    visible.find(task => task.id === selectedId) ||
    visible.find(task => task.batch_id === value?.id) ||
    visible.find(payrollQueueRunning) ||
    visible[0];
  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected?.id, selectedId]);

  const chosen = visible.filter(task => checked.includes(task.id));
  const downloadable = (chosen.length ? chosen : filteredVisible).filter(
    task => task.status === 'completed' && task.batch_id,
  );
  const stoppableChosen = chosen.filter(task => payrollQueueRunning(task) && task.status !== 'stopping');

  const act = async (work: () => Promise<void>) => {
    if (guard.current) return;
    guard.current = true;
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '操作未完成';
      setError(msg);
      pushToast(msg, 'error');
    } finally {
      guard.current = false;
      setBusy(false);
    }
  };

  const upload = async (files: { file: File; relativePath: string }[]) => {
    if (uploading) return;
    setUploading(true);
    setError('');
    try {
      const duplicates = detectDuplicateUploadNames(
        files.map(f => f.relativePath || f.file.name),
        visible,
      );
      if (duplicates.length) {
        pushToast(`提醒：队列中已存在同名模板（${duplicates.slice(0, 2).join('、')}），请注意核对避免重复结算。`, 'info');
      }
      const previous = new Set(tasks.map(task => task.id));
      await onUploadFiles(files);
      if (hidden) {
        setHidden(false);
        return;
      }
      const next = await refresh(true);
      const added = next?.filter(task => !previous.has(task.id)) || [];
      if (added.length) {
        setSelectedId(added[0].id);
        setQueueFilterTab('all');
        setQueueSearch('');
        setCityFilter('');
        setModeFilter('');
        setMissingApprovalOnly(false);
        // 队列按提交时间倒序，新提交批次始终位于第 1 页顶部
        setQueuePage(1);
        pushToast(`已加入 ${added.length} 个核算任务，请逐行填写审批编号。`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '资料上传未完成';
      setError(msg);
      pushToast(msg, 'error');
    } finally {
      setUploading(false);
    }
  };

  const updateApproval = async (task: PayrollQueueTask, code: string) => {
    setError('');
    if (task.demo) {
      setDemoTasks(prev => prev.map(item => (item.id === task.id ? { ...item, approval_code: code } : item)));
      pushToast(code ? `审批编号已更新为 ${code}` : '审批编号已清空');
      return;
    }
    try {
      const response = await request(`${API}/${task.id}/approval`, { approval_code: code });
      await response.json().catch(() => ({}));
      pushToast('审批编号已保存');
      await refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '审批编号保存失败';
      setError(msg);
      pushToast(msg, 'error');
      throw e;
    }
  };

  const copyApproval = (code: string) => {
    void navigator.clipboard
      .writeText(code)
      .then(() => pushToast(`已复制审批编号「${code}」`))
      .catch(() => pushToast('复制失败，请手动选中复制', 'error'));
  };

  const stop = (task: PayrollQueueTask) =>
    void act(async () => {
      if (task.demo) {
        const wasQueued = task.status === 'queued';
        setDemoTasks(prev =>
          prev.map(item =>
            item.id === task.id
              ? {
                  ...item,
                  status: 'cancelled',
                  current_action: wasQueued ? '已取消排队（示例预览）' : '已手动停止（示例预览）',
                }
              : item,
          ),
        );
        pushToast(wasQueued ? '已取消排队任务' : '已停止示例核算任务');
        return;
      }
      if (task.legacy) {
        await request('/api/workbench/task-center/stop', { id: 'payroll_' + task.batch_id });
        onPreparationChange(await (await request(`/api/parttime/preparations/${task.batch_id}`)).json());
      } else {
        await request(`${API}/${task.id}/stop`, {});
      }
      pushToast('已提交停止指令', 'info');
      await refresh();
    });

  const batchStop = (targets: PayrollQueueTask[]) =>
    void act(async () => {
      if (!targets.length) return;
      if (targets.every(t => t.demo)) {
        const stopIds = new Set(targets.map(t => t.id));
        setDemoTasks(prev =>
          prev.map(item =>
            stopIds.has(item.id)
              ? { ...item, status: 'cancelled', current_action: '已批量手动停止（示例预览）' }
              : item,
          ),
        );
        setChecked([]);
        pushToast(`已批量停止 ${targets.length} 条在途/排队批次`);
        return;
      }
      for (const task of targets) {
        if (task.legacy) {
          await request('/api/workbench/task-center/stop', { id: 'payroll_' + task.batch_id });
        } else {
          await request(`${API}/${task.id}/stop`, {});
        }
      }
      setChecked([]);
      pushToast(`已批量提交 ${targets.length} 条批次的停止请求`, 'info');
      await refresh();
    });

  const retryTask = (task: PayrollQueueTask) =>
    void act(async () => {
      if (task.demo) {
        const nowStr = new Intl.DateTimeFormat('zh-CN', {
          timeZone: 'Asia/Shanghai',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }).format(new Date());
        setDemoTasks(prev =>
          prev.map(item =>
            item.id === task.id
              ? {
                  ...item,
                  status: 'preparing',
                  progress: 18,
                  current_action: '已重新发起核算，正在重新校验资料与扣款口径',
                  logs: [
                    ...(item.logs || []),
                    { time: nowStr, level: 'INFO', message: '人工触发重新核算，重新进入资料与规则校验流程' },
                  ],
                }
              : item,
          ),
        );
        pushToast(`批次「${taskLabel(task)}」已重新发起核算`);
        return;
      }
      await request(`${API}/${task.id}/retry`, {});
      pushToast('已重新提交核算请求');
      await refresh();
    });

  const confirmDeductions = (task: PayrollQueueTask) =>
    void act(async () => {
      if (task.demo) {
        const nowStr = new Intl.DateTimeFormat('zh-CN', {
          timeZone: 'Asia/Shanghai',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }).format(new Date());
        setDemoTasks(prev =>
          prev.map(item =>
            item.id === task.id
              ? {
                  ...item,
                  status: 'calculating',
                  progress: 82,
                  current_action: '站点扣款口径已确认，正在执行最终实发薪资汇总',
                  logs: [
                    ...(item.logs || []),
                    { time: nowStr, level: 'INFO', message: '已确认本批次站点扣款口径，恢复自动核算流程' },
                  ],
                }
              : item,
          ),
        );
        pushToast(`已确认「${task.plan?.city || taskLabel(task)}」扣款口径，继续核算中`);
        return;
      }
      await request(`${API}/${task.id}/confirm-deductions`, {});
      pushToast('已确认扣款口径，核算继续推进');
      await refresh();
    });

  const download = (task: PayrollQueueTask) =>
    void act(async () => {
      if (task.demo) {
        pushToast(`示例批次「${task.approval_code || task.plan?.city}」仅用于界面预览，上传真实模板后可下载成品包。`, 'info');
        return;
      }
      const response = await request(
        `/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(task.batch_id!)}`,
      );
      saveDownloadBlob(
        await readDownloadResponse(response, '薪资核算结果.zip'),
        task.template_name.replace(/\.xlsx?$/i, '') + '_核算结果.zip',
      );
      pushToast('已发起成品包下载');
    });

  const directory = (task: PayrollQueueTask) =>
    void act(async () => {
      if (task.demo) {
        pushToast(`示例批次「${task.approval_code || task.plan?.city}」未写入本地磁盘目录。`, 'info');
        return;
      }
      await request('/api/workbench/task-center/directory/open', { record_id: 'payroll_' + task.batch_id });
      pushToast('已打开本地结果目录');
    });

  const restore = (entries: PayrollQueueTask[]) =>
    void act(async () => {
      if (entries.every(t => t.demo)) {
        const restoreSet = new Set(entries.map(t => t.id));
        setDemoHiddenIds(prev => prev.filter(id => !restoreSet.has(id)));
        setChecked([]);
        pushToast(`已恢复 ${entries.length} 条示例核算批次`);
        return;
      }
      await request(API + '/visibility', { ids: entries.map(task => task.id), restore: true });
      setChecked([]);
      pushToast(`已恢复 ${entries.length} 条核算批次`);
      await refresh();
    });

  const detailTask = detailTaskId
    ? filteredVisible.find(task => task.id === detailTaskId) || visible.find(task => task.id === detailTaskId) || null
    : null;

  const hasActiveFilters =
    queueFilterTab !== 'all' || !!queueSearch || !!cityFilter || !!modeFilter || missingApprovalOnly;

  return (
    <div className="pq-workbench wbx-payroll">
      {/* 1. 可折叠的一站式上传工作台（高频核对时一键收起释放首屏空间） */}
      <section className={`pq-intake${intakeCollapsed ? ' is-collapsed' : ''}`} aria-label="添加核算任务">
        {intakeCollapsed ? (
          <div className="pq-intake-compact">
            <div className="pq-intake-compact__left">
              <UploadCloud size={15} aria-hidden="true" />
              <span>新增核算批次</span>
              <small>支持拖入或点选 .xlsx 模板与手动资料文件夹</small>
            </div>
            <div className="pq-intake-compact__right">
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                onClick={() => setTemplates(true)}
              >
                <FileSpreadsheet size={13} aria-hidden="true" />
                <span>标准模板</span>
              </button>
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                onClick={() => setIntakeCollapsed(false)}
              >
                <ChevronDown size={13.5} aria-hidden="true" />
                <span>展开上传区</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="pq-intake-expanded">
            <ControlPanel
              onUploadFiles={upload}
              onOpenTemplates={() => setTemplates(true)}
              isRunning={uploading}
              separationOption={
                <label
                  className="pq-intake-option"
                  title="仅对自动风神核算生效；取消勾选则下载全部站点，范围在任务建立时固定。"
                >
                  <input
                    type="checkbox"
                    aria-label="排除取分离站点"
                    checked={excludeSeparation}
                    disabled={uploading}
                    onChange={event => onConfigChange({ payrollExcludeSeparation: event.target.checked })}
                  />
                  <span>排除取分离站点</span>
                </label>
              }
              collapseAction={
                visible.length > 0 ? (
                  <button
                    type="button"
                    className="pq-intake-toggle"
                    title="收起上传区以释放列表首屏空间"
                    aria-label="收起上传区"
                    onClick={() => setIntakeCollapsed(true)}
                  >
                    <ChevronUp size={13.5} aria-hidden="true" />
                    <span>收起</span>
                  </button>
                ) : undefined
              }
            />
          </div>
        )}
      </section>

      {error && (
        <p className="pq-message is-error" role="alert">
          {error}
        </p>
      )}
      {loadError && !usingDemo && (
        <p className="pq-message" role="status">
          {loadError}；现有记录保留，系统会继续更新。
        </p>
      )}

      {/* 2. 常驻兼职核算队列 */}
      <section className="pq-queue" aria-label="兼职核算队列" aria-busy={loading && !usingDemo}>
        <header className="pq-queue-heading">
          <div className="pq-queue-title-group">
            <h3>
              {hidden ? '已移出批次' : '兼职核算队列'}
              <span className="tabular-nums">{visible.length}</span>
            </h3>
            {visible.length > 0 && (
              <div className="pq-inline-summary tabular-nums" aria-label="当前筛选批次财务汇总">
                <span>
                  共 <strong>{summary.count}</strong> 批
                </span>
                <span className="pq-summary-strip__dot" aria-hidden="true">·</span>
                <span>
                  <strong>{summary.applicants.toLocaleString('zh-CN')}</strong> 人
                </span>
                <span className="pq-summary-strip__dot" aria-hidden="true">·</span>
                <span>
                  合计 <strong>¥{formatPayrollAmount(summary.amount)}</strong>
                </span>
                {summary.reviewAlertCount > 0 && (
                  <>
                    <span className="pq-summary-strip__dot" aria-hidden="true">·</span>
                    <span>
                      预警 <strong>{summary.reviewAlertCount}</strong>
                    </span>
                  </>
                )}
                <button
                  type="button"
                  className={`pq-summary-toggle${missingApprovalOnly ? ' is-active' : ''}`}
                  onClick={() => {
                    setMissingApprovalOnly(prev => !prev);
                    setQueuePage(1);
                  }}
                >
                  <span>未填编号</span>
                  <strong className="tabular-nums">{summary.missingApprovalCount}</strong>
                </button>
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="wb-link pq-reset-filter-link"
                    onClick={() => {
                      setQueueFilterTab('all');
                      setQueueSearch('');
                      setCityFilter('');
                      setModeFilter('');
                      setMissingApprovalOnly(false);
                      setQueuePage(1);
                    }}
                  >
                    重置筛选
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="pq-queue-actions">
            {chosen.length > 0 && <span className="pq-selection tabular-nums">已选 {chosen.length} 项</span>}
            {!hasLiveData && (
              <span className="wbx-demo-group">
                {usingDemo && <span className="wbx-demo-badge">示例数据</span>}
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  onClick={() => {
                    setDemoEnabled(prev => !prev);
                    setQueuePage(1);
                    setChecked([]);
                    setDetailTaskId('');
                  }}
                >
                  {demoEnabled ? '隐藏示例' : '加载 30 条示例'}
                </button>
              </span>
            )}
            {hidden ? (
              chosen.length > 0 && (
                <button className="wbx-btn wbx-btn--sm wbx-btn--primary" disabled={busy} onClick={() => restore(chosen)}>
                  恢复已选
                </button>
              )
            ) : (
              <>
                {stoppableChosen.length > 0 && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--danger wbx-btn--sm"
                    disabled={busy}
                    onClick={() => batchStop(stoppableChosen)}
                  >
                    <Square size={11.5} aria-hidden="true" />
                    <span>批量停止 ({stoppableChosen.length})</span>
                  </button>
                )}
                {!!downloadable.length && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--primary wbx-btn--sm"
                    disabled={busy}
                    onClick={() =>
                      void act(async () => {
                        if (downloadable.every(t => t.demo)) {
                          pushToast(
                            `示例模式共 ${downloadable.length} 条已完成批次，上传真实模板后可批量下载成品包。`,
                            'info',
                          );
                          return;
                        }
                        if (downloadable.length === 1) {
                          const response = await request(
                            `/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(downloadable[0].batch_id!)}`,
                          );
                          saveDownloadBlob(await readDownloadResponse(response, '薪资核算结果.zip'), '薪资核算结果.zip');
                        } else {
                          const queueEntries = downloadable.filter(task => !task.legacy);
                          if (queueEntries.length !== downloadable.length) {
                            throw Error('历史批次请在对应行单独下载；其余任务可勾选后批量下载。');
                          }
                          const response = await request(API + '/bundle', {
                            ids: queueEntries.map(task => task.id),
                          });
                          saveDownloadBlob(
                            await readDownloadResponse(response, '批量薪资核算结果.zip'),
                            '批量薪资核算结果.zip',
                          );
                        }
                        pushToast('已发起成品包下载');
                      })
                    }
                  >
                    <Download size={13.5} />
                    <span>{chosen.length ? '下载已选结果' : '下载已完成'}</span>
                    <span className="pq-action-count tabular-nums">{downloadable.length}</span>
                  </button>
                )}
                {chosen.length > 0 && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                    disabled={busy}
                    onClick={() => setRemoveTargets(chosen)}
                  >
                    移出已选
                  </button>
                )}
              </>
            )}
            <button
              type="button"
              className={`wbx-btn wbx-btn--sm${hidden ? ' wbx-btn--secondary' : ''}`}
              onClick={() => {
                setHidden(previous => !previous);
                setQueuePage(1);
                setDetailTaskId('');
              }}
            >
              <ArchiveRestore size={13} aria-hidden="true" />
              <span>{hidden ? '返回队列' : '已移出'}</span>
            </button>
          </div>
        </header>

        {(() => {
          const waiting = visible.find(task => task.preparation?.execution?.waiting_verification);
          if (!waiting) return null;
          return (
            <div className="wbx-payroll__verify-banner" role="status">
              <div className="wbx-payroll__verify-banner-copy">
                <ShieldAlert size={15} />
                <span>等待骑手信息导出验证，完成后自动继续。</span>
                <span className="wbx-hint">收起验证窗口会保留等待。</span>
              </div>
              <button
                type="button"
                className="wbx-btn wbx-btn--sm wbx-payroll__verify-btn"
                onClick={onOpenFengshenLogin}
              >
                打开验证码窗口
              </button>
            </div>
          );
        })()}

        {/* 3. 单行多维筛选栏（状态页签 + 搜索 + 城市 / 类型 / 排序） */}
        {visible.length > 0 && (
          <div className="wbx-payroll__filter-bar">
            <div className="wbx-payroll__tabs" role="tablist" aria-label="按队列状态筛选">
              {(
                [
                  ['all', '全部', tabCounts.all],
                  ['active', '执行中', tabCounts.active],
                  ['waiting', '待处理', tabCounts.waiting],
                  ['completed', '已完成', tabCounts.completed],
                  ['issue', '异常/已结束', tabCounts.issue],
                ] as const
              ).map(([key, label, count]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={queueFilterTab === key}
                  className={`wbx-payroll__tab ${queueFilterTab === key ? 'is-active' : ''}`}
                  onClick={() => {
                    setQueueFilterTab(key);
                    setQueuePage(1);
                    setChecked([]);
                  }}
                >
                  <span>{label}</span>
                  <span className="wbx-payroll__tab-count tabular-nums">{count}</span>
                </button>
              ))}
            </div>

            <div className="wbx-payroll__filter-controls">
              <label className="wbx-payroll__search">
                <Search size={13.5} />
                <input
                  type="search"
                  value={queueSearch}
                  onChange={e => {
                    setQueueSearch(e.target.value);
                    setQueuePage(1);
                  }}
                  placeholder="搜索审批编号、城市或模板…"
                  aria-label="筛选核算批次"
                />
              </label>

              <select
                className="wb-select wbx-payroll__select"
                aria-label="按城市筛选"
                value={cityFilter}
                onChange={e => {
                  setCityFilter(e.target.value);
                  setQueuePage(1);
                  setChecked([]);
                }}
              >
                <option value="">全部城市</option>
                {availableCities.map(city => (
                  <option key={city} value={city}>
                    {city}
                  </option>
                ))}
              </select>

              <select
                className="wb-select wbx-payroll__select"
                aria-label="按核算类型筛选"
                value={modeFilter}
                onChange={e => {
                  setModeFilter(e.target.value);
                  setQueuePage(1);
                  setChecked([]);
                }}
              >
                <option value="">全部类型</option>
                <option value="周结">周结</option>
                <option value="半月结">半月结</option>
                <option value="月结">月结</option>
                <option value="全职">全职</option>
                <option value="日结">日结</option>
              </select>

              <select
                className="wb-select wbx-payroll__select"
                aria-label="核算批次排序"
                value={sortKey}
                onChange={e => setSortKey(e.target.value as PayrollSortKey)}
              >
                <option value="default">按提交时间</option>
                <option value="amount_desc">按金额降序</option>
                <option value="applicants_desc">按人数降序</option>
                <option value="elapsed_desc">按用时降序</option>
              </select>
            </div>
          </div>
        )}

        {loading && !visible.length ? (
          <div className="pq-empty">
            <Loader2 size={23} className="animate-spin" />
            <p>正在读取任务队列…</p>
          </div>
        ) : filteredVisible.length > 0 ? (
          <>
            <PayrollQueueTable
              tasks={pagedTasks}
              selectedId={selected?.id}
              activeDetailId={detailTaskId}
              onSelect={(id: string) => setSelectedId(id)}
              onOpenDetail={(id: string, tab?: PayrollDetailTab) => {
                setDetailTab(tab);
                setDetailTaskId(id);
              }}
              checked={checked}
              onCheck={id =>
                setChecked(previous =>
                  previous.includes(id) ? previous.filter(item => item !== id) : [...previous, id],
                )
              }
              onCheckAll={() => {
                const pageIds = pagedTasks.map(task => task.id);
                const allPageChecked = pageIds.length > 0 && pageIds.every(id => checked.includes(id));
                setChecked(previous =>
                  allPageChecked
                    ? previous.filter(id => !pageIds.includes(id))
                    : Array.from(new Set([...previous, ...pageIds])),
                );
              }}
              onStop={stop}
              onRemove={setRemoveTargets}
              onDownload={download}
              onOpenDirectory={directory}
              onRestore={restore}
              onApproval={updateApproval}
              busy={busy}
              hidden={hidden}
            />
            <footer className="wbx-payroll__pagination" aria-label="兼职核算队列分页">
              <div className="wbx-payroll__pagination-meta tabular-nums">
                <span>
                  共 {pagedQueue.total} 条 · 当前第 {pagedQueue.startIndex + 1}-{pagedQueue.endIndex} 条
                </span>
                <label className="wbx-payroll__page-size">
                  <span>每页</span>
                  <select
                    className="wb-select"
                    aria-label="核算队列每页条数"
                    value={queuePageSize}
                    onChange={e => {
                      setQueuePageSize(Number(e.target.value));
                      setQueuePage(1);
                    }}
                  >
                    <option value={10}>10 条</option>
                    <option value={20}>20 条</option>
                    <option value={50}>50 条</option>
                  </select>
                </label>
              </div>
              <div className="wbx-payroll__pagination-controls">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={pagedQueue.page <= 1}
                  onClick={() => setQueuePage(Math.max(1, pagedQueue.page - 1))}
                >
                  上一页
                </button>
                <span className="tabular-nums wbx-payroll__page-indicator">
                  第 {pagedQueue.page} / {pagedQueue.totalPages} 页
                </span>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={pagedQueue.page >= pagedQueue.totalPages}
                  onClick={() => setQueuePage(Math.min(pagedQueue.totalPages, pagedQueue.page + 1))}
                >
                  下一页
                </button>
              </div>
            </footer>
          </>
        ) : visible.length > 0 ? (
          <div className="pq-empty">
            <FileSpreadsheet size={26} />
            <strong>当前筛选下没有匹配的核算批次</strong>
            <p>可切换状态分类、城市或清空筛选条件，恢复查看全部 {visible.length} 个批次。</p>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm"
              onClick={() => {
                setQueueFilterTab('all');
                setQueueSearch('');
                setCityFilter('');
                setModeFilter('');
                setMissingApprovalOnly(false);
              }}
            >
              重置队列筛选
            </button>
          </div>
        ) : (
          <div className="pq-empty">
            <FileSpreadsheet size={28} />
            <strong>{hidden ? '暂无已移出批次' : '暂无核算批次'}</strong>
            <p>
              {hidden
                ? '移出的任务会保留在此，可随时恢复。'
                : '上传 .xlsx 模板文件将自动核算，上传含模板及补充资料的文件夹将按手动核算处理；支持多模板和在执行中继续添加。'}
            </p>
          </div>
        )}
      </section>

      <PayrollBatchDetailDrawer
        task={detailTask}
        tasks={filteredVisible}
        initialTab={detailTab}
        busy={busy}
        onClose={() => {
          setDetailTaskId('');
          setDetailTab(undefined);
        }}
        onSelectTask={(id: string) => {
          setSelectedId(id);
          setDetailTab(undefined);
          setDetailTaskId(id);
        }}
        onDownload={download}
        onOpenDirectory={directory}
        onStop={stop}
        onRetry={retryTask}
        onConfirmDeductions={confirmDeductions}
        onSaveApproval={updateApproval}
        onCopyApproval={copyApproval}
        onOpenConnections={onOpenConnections}
        onOpenFengshenLogin={onOpenFengshenLogin}
        onOpenDeductions={onOpenDeductions}
        onNavigateTaskCenter={onNavigateTaskCenter}
      />

      {templates && (
        <WorkbenchDrawer title="系统模板" wide onClose={() => setTemplates(false)}>
          <SystemTemplatesPanel onNavigatePayroll={() => setTemplates(false)} />
        </WorkbenchDrawer>
      )}

      {!!removeTargets.length && (
        <WorkbenchConfirmModal
          title={removeTargets.some(payrollQueueRunning) ? '停止并移出任务' : '移出任务列表'}
          description={`${removeTargets.length} 项核算批次将从共享列表移出；成品文件与处理记录均完整保留，可在「已移出」随时恢复。`}
          hint={removeTargets.some(payrollQueueRunning) ? '执行中或排队中的任务会先安全停止。' : undefined}
          items={removeTargets.map(t => `${t.approval_code || '待填编号'} · ${t.plan?.city || t.template_name || t.id}`)}
          confirmLabel="确认移出，保留文件"
          confirmTone="danger"
          busy={busy}
          error={error}
          onCancel={() => setRemoveTargets([])}
          onConfirm={() =>
            void act(async () => {
              if (removeTargets.every(t => t.demo)) {
                const removedSet = new Set(removeTargets.map(t => t.id));
                setDemoHiddenIds(prev => Array.from(new Set([...prev, ...removedSet])));
                if (detailTaskId && removedSet.has(detailTaskId)) setDetailTaskId('');
                setRemoveTargets([]);
                setChecked([]);
                pushToast(`已移出 ${removeTargets.length} 条示例任务，可在「已移出」中恢复。`);
                return;
              }
              const current = removeTargets.filter(task => !task.legacy);
              const old = removeTargets.filter(task => task.legacy);
              if (current.length) {
                await request(API + '/visibility', {
                  ids: current.map(task => task.id),
                  restore: false,
                  stop_first: true,
                });
              }
              if (old.length) {
                await request('/api/workbench/task-center/visibility', {
                  ids: old.map(task => 'payroll_' + task.batch_id),
                  restore: false,
                  stop_first: true,
                });
                setSkipLegacy(true);
              }
              if (detailTaskId && removeTargets.some(task => task.id === detailTaskId)) setDetailTaskId('');
              setRemoveTargets([]);
              setChecked([]);
              pushToast(`已移出 ${removeTargets.length} 条核算批次`);
              await refresh();
            })
          }
        />
      )}

      <WorkbenchToast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
