import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FolderOpen,
  ListChecks,
  Loader2,
  Pencil,
  RotateCw,
  SlidersHorizontal,
  Square,
  Terminal,
  X,
} from 'lucide-react';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { PayrollReviewSummary } from './PayrollReviewSummary';
import { businessLogEntries } from '../lib/payrollBusinessLogs';
import {
  extractPayrollAmount,
  extractPayrollReviewAlert,
  formatPayrollAmount,
  payrollCycleLabel,
  payrollElapsed,
  payrollModeName,
  payrollPeriodRange,
  payrollQueueRunning,
  payrollQueueStatus,
  payrollTypeTone,
  type PayrollQueueTask,
} from '../lib/payrollQueue';
import { toneClass } from '../lib/statusSemantics';

export type PayrollDetailTab = 'activity' | 'deductions' | 'review';

interface PayrollBatchDetailDrawerProps {
  task: PayrollQueueTask | null;
  tasks: PayrollQueueTask[];
  initialTab?: PayrollDetailTab;
  busy?: boolean;
  onClose: () => void;
  onSelectTask: (id: string) => void;
  onDownload: (task: PayrollQueueTask) => void;
  onOpenDirectory: (task: PayrollQueueTask) => void;
  onStop: (task: PayrollQueueTask) => void;
  onRetry?: (task: PayrollQueueTask) => void;
  onConfirmDeductions?: (task: PayrollQueueTask) => void;
  onSaveApproval?: (task: PayrollQueueTask, code: string) => Promise<void>;
  onCopyApproval?: (code: string) => void;
  onOpenConnections: () => void;
  onOpenFengshenLogin: () => void;
  onOpenDeductions: () => void;
  onNavigateTaskCenter?: () => void;
}

function formatLogClock(value?: string) {
  if (!value) return '';
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
  return value.match(/(?:T|\s)?(\d{2}:\d{2}(?::\d{2})?)/)?.[1] || value;
}

export function PayrollBatchDetailDrawer({
  task,
  tasks,
  initialTab,
  busy = false,
  onClose,
  onSelectTask,
  onDownload,
  onOpenDirectory,
  onStop,
  onRetry,
  onConfirmDeductions,
  onSaveApproval,
  onCopyApproval,
  onOpenConnections,
  onOpenFengshenLogin,
  onOpenDeductions,
  onNavigateTaskCenter,
}: PayrollBatchDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<PayrollDetailTab>('activity');
  const [showTechnical, setShowTechnical] = useState(false);
  const [editingCode, setEditingCode] = useState(false);
  const [codeDraft, setCodeDraft] = useState('');
  const [savingCode, setSavingCode] = useState(false);

  useEffect(() => {
    setShowTechnical(false);
    setEditingCode(false);
    if (!task) return;
    setCodeDraft(task.approval_code || '');
    if (initialTab) {
      setActiveTab(initialTab);
      return;
    }
    if (task.status === 'completed' && task.preparation?.result?.review_summary) {
      setActiveTab('review');
    } else if (task.status === 'waiting_confirmation' && task.preparation?.automatic_deductions?.sources?.length) {
      setActiveTab('deductions');
    } else {
      setActiveTab('activity');
    }
  }, [task?.id, task?.status, initialTab]);

  const currentIndex = task ? tasks.findIndex(item => item.id === task.id) : -1;
  const prevTask = currentIndex > 0 ? tasks[currentIndex - 1] : null;
  const nextTask = currentIndex >= 0 && currentIndex < tasks.length - 1 ? tasks[currentIndex + 1] : null;

  // 支持 ← / → 方向键快速切换上一条 / 下一条批次（编辑输入框时自动让位）
  useEffect(() => {
    if (!task) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.key === 'ArrowLeft' && prevTask) {
        event.preventDefault();
        onSelectTask(prevTask.id);
      } else if (event.key === 'ArrowRight' && nextTask) {
        event.preventDefault();
        onSelectTask(nextTask.id);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [task?.id, prevTask, nextTask, onSelectTask]);

  if (!task) return null;

  const state = payrollQueueStatus(task.status);
  const running = payrollQueueRunning(task);
  const isPaused = task.status === 'waiting_confirmation' || task.status === 'waiting_materials';
  const done = task.status === 'completed';
  const retryable = ['error', 'cancelled', 'interrupted'].includes(task.status) && !!onRetry;
  const amount = extractPayrollAmount(task);
  const reviewAlert = extractPayrollReviewAlert(task);
  const periodRange = payrollPeriodRange(task.plan);
  const cycleLabel = payrollCycleLabel(task.plan);
  const typeTone = payrollTypeTone(task.mode);
  const rawLogs = task.logs?.length ? task.logs : task.preparation?.execution_logs || [];
  const { business, technical } = businessLogEntries(rawLogs);
  const deductionSources = task.preparation?.automatic_deductions?.sources || [];
  const reviewSummary = task.preparation?.result?.review_summary;
  const trimmedCode = (task.approval_code || '').trim();
  const displayCode = trimmedCode || '待填写审批编号';
  const pct = Number.isFinite(task.progress) ? Math.max(0, Math.min(100, Math.round(task.progress))) : 0;

  const commitCode = async () => {
    if (!onSaveApproval) {
      setEditingCode(false);
      return;
    }
    const next = codeDraft.trim();
    if (next === trimmedCode) {
      setEditingCode(false);
      return;
    }
    setSavingCode(true);
    try {
      await onSaveApproval(task, next);
      setEditingCode(false);
    } catch {
      // 保留编辑态以便用户修正
    } finally {
      setSavingCode(false);
    }
  };

  return (
    <WorkbenchDrawer
      title={`批次详情 · ${displayCode}`}
      wide
      bodyClassName="pq-drawer-body"
      onClose={onClose}
    >
      <div className="pq-drawer">
        {/* 1. 顶部快捷操作与上下批次切换条（支持 ←/→ 快捷键） */}
        <div className="pq-drawer__toolbar">
          <div className="pq-drawer__status-row">
            <span className={`wbx-pill ${toneClass(state.tone)}`}>
              {running && task.status !== 'stopping' && task.status !== 'queued' ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <span className="wbx-pill__dot" aria-hidden="true" />
              )}
              {state.label}
            </span>
            {reviewAlert && (
              <span className="pq-review-alert-chip tabular-nums">{reviewAlert.label}</span>
            )}
            {!!task.elapsed_seconds && (
              <span className="pq-drawer__meta-text tabular-nums">用时 {payrollElapsed(task.elapsed_seconds)}</span>
            )}
          </div>

          <div className="pq-drawer__nav-actions">
            {done && task.batch_id && (
              <>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--primary wbx-btn--sm"
                  disabled={busy}
                  onClick={() => onDownload(task)}
                >
                  <Download size={13} aria-hidden="true" />
                  <span>下载成品包</span>
                </button>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={busy}
                  onClick={() => onOpenDirectory(task)}
                >
                  <FolderOpen size={13} aria-hidden="true" />
                  <span>结果目录</span>
                </button>
              </>
            )}
            {retryable && (
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                disabled={busy}
                onClick={() => onRetry?.(task)}
              >
                <RotateCw size={12.5} aria-hidden="true" />
                <span>重新核算</span>
              </button>
            )}
            {running && (
              <button
                type="button"
                className="wbx-btn wbx-btn--danger wbx-btn--sm"
                disabled={busy || task.status === 'stopping'}
                onClick={() => onStop(task)}
              >
                <Square size={11.5} aria-hidden="true" />
                <span>
                  {task.status === 'stopping' ? '停止中' : task.status === 'queued' ? '取消排队' : '停止任务'}
                </span>
              </button>
            )}
            {tasks.length > 1 && currentIndex >= 0 && (
              <div className="pq-drawer__pager" aria-label="切换相邻批次" title="支持键盘 ← / → 切换">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  disabled={!prevTask}
                  aria-label="上一条批次"
                  onClick={() => prevTask && onSelectTask(prevTask.id)}
                >
                  <ChevronLeft size={14} aria-hidden="true" />
                  <span>上一条</span>
                </button>
                <span className="pq-drawer__pager-pos tabular-nums">
                  {currentIndex + 1} / {tasks.length}
                </span>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  disabled={!nextTask}
                  aria-label="下一条批次"
                  onClick={() => nextTask && onSelectTask(nextTask.id)}
                >
                  <span>下一条</span>
                  <ChevronRight size={14} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 2. 实时进度条（执行中蓝色 / 暂停等待琥珀色，0% 无伪进度占位） */}
        {(running || isPaused) && (
          <div className={`pq-drawer__livebar${isPaused ? ' is-paused' : ''}`}>
            <div className="pq-drawer__livebar-head">
              <span className="tabular-nums">
                {task.status === 'queued'
                  ? '排队等待采集/核算通道释放…'
                  : isPaused
                    ? `核算已暂停（当前进度 ${pct}%）`
                    : `核算进度：${pct}%`}
              </span>
              {task.current_action && (
                <span className="pq-drawer__livebar-note" title={task.current_action}>
                  {task.current_action}
                </span>
              )}
            </div>
            <div className="pq-drawer__track" aria-hidden="true">
              <span style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        {/* 3. 状态指引条（待确认扣款支持就地一键确认继续；失败支持查看关联采集任务） */}
        {task.status === 'waiting_materials' && (task.preparation?.pause_reason || task.current_action) && (
          <div className="pq-drawer__callout is-warn" role="status">
            <div className="pq-drawer__callout-copy">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{task.preparation?.pause_reason || task.current_action}</span>
            </div>
            <div className="pq-drawer__callout-actions">
              <button type="button" className="wbx-btn wbx-btn--sm wbx-btn--primary" onClick={onOpenConnections}>
                检查平台授权
              </button>
              {onNavigateTaskCenter && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  onClick={() => {
                    onClose();
                    onNavigateTaskCenter();
                  }}
                >
                  <ExternalLink size={12.5} aria-hidden="true" />
                  <span>任务中心</span>
                </button>
              )}
            </div>
          </div>
        )}
        {task.preparation?.execution?.waiting_login && (
          <div className="pq-drawer__callout is-warn" role="status">
            <div className="pq-drawer__callout-copy">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>
                {task.preparation.execution.waiting_verification
                  ? '正在等待骑手信息导出验证，完成后自动继续。'
                  : '正在等待平台登录授权，完成后自动继续。'}
              </span>
            </div>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-btn--primary"
              onClick={task.mode === 'fengshen' ? onOpenFengshenLogin : onOpenConnections}
            >
              {task.preparation.execution.waiting_verification ? '打开验证码窗口' : '完成平台登录'}
            </button>
          </div>
        )}
        {task.status === 'waiting_confirmation' && (
          <div className="pq-drawer__callout is-warn" role="status">
            <div className="pq-drawer__callout-copy">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{task.current_action || '当前批次存在待确认的站点扣款配置。'}</span>
            </div>
            <div className="pq-drawer__callout-actions">
              {onConfirmDeductions && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--primary"
                  disabled={busy}
                  onClick={() => onConfirmDeductions(task)}
                >
                  <Check size={13} aria-hidden="true" />
                  <span>确认口径并继续</span>
                </button>
              )}
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                onClick={() => {
                  onClose();
                  onOpenDeductions();
                }}
              >
                <SlidersHorizontal size={13} aria-hidden="true" />
                <span>扣款配置</span>
              </button>
            </div>
          </div>
        )}
        {task.status === 'error' && (
          <div className="pq-drawer__callout is-danger" role="alert">
            <div className="pq-drawer__callout-copy">
              <AlertTriangle size={14} aria-hidden="true" />
              <span>{task.current_action || '核算异常终止，请查看下方执行动态定位具体原因。'}</span>
            </div>
            <div className="pq-drawer__callout-actions">
              {onNavigateTaskCenter && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  onClick={() => {
                    onClose();
                    onNavigateTaskCenter();
                  }}
                >
                  <ExternalLink size={12.5} aria-hidden="true" />
                  <span>查采集任务</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* 4. 抽屉内审批编号直编栏 + 6 字段结构化业务摘要 */}
        <div className="pq-drawer__approval-bar">
          <span className="pq-drawer__approval-label">审批编号</span>
          {editingCode && !task.legacy ? (
            <div className="pq-drawer__approval-editor">
              <input
                autoFocus
                value={codeDraft}
                maxLength={64}
                placeholder="输入核算审批编号（如 SP-20261121-005）"
                aria-label="编辑批次审批编号"
                onChange={e => setCodeDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') void commitCode();
                  else if (e.key === 'Escape') {
                    setCodeDraft(task.approval_code || '');
                    setEditingCode(false);
                  }
                }}
              />
              <button
                type="button"
                className="wbx-btn wbx-btn--primary wbx-btn--sm"
                disabled={savingCode}
                onClick={() => void commitCode()}
              >
                {savingCode ? '保存中…' : '保存'}
              </button>
              <button
                type="button"
                className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                disabled={savingCode}
                onClick={() => {
                  setCodeDraft(task.approval_code || '');
                  setEditingCode(false);
                }}
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>
          ) : (
            <div className="pq-drawer__approval-display">
              <strong className={`tabular-nums${trimmedCode ? '' : ' is-empty'}`}>{displayCode}</strong>
              {trimmedCode && onCopyApproval && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  title="复制审批编号"
                  aria-label="复制审批编号"
                  onClick={() => onCopyApproval(trimmedCode)}
                >
                  <Copy size={12.5} aria-hidden="true" />
                  <span>复制</span>
                </button>
              )}
              {!task.legacy && onSaveApproval && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                  aria-label={trimmedCode ? '修改审批编号' : '填写审批编号'}
                  onClick={() => {
                    setCodeDraft(task.approval_code || '');
                    setEditingCode(true);
                  }}
                >
                  <Pencil size={12.5} aria-hidden="true" />
                  <span>{trimmedCode ? '修改' : '立即填写'}</span>
                </button>
              )}
              {onNavigateTaskCenter && (
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--ghost pq-drawer__approval-link"
                  onClick={() => {
                    onClose();
                    onNavigateTaskCenter();
                  }}
                >
                  <ExternalLink size={12.5} aria-hidden="true" />
                  <span>关联任务中心</span>
                </button>
              )}
            </div>
          )}
        </div>

        <dl className="pq-drawer__facts">
          <div>
            <dt>城市</dt>
            <dd>{task.plan?.city || '待识别'}</dd>
          </div>
          <div>
            <dt>结算周期</dt>
            <dd className="tabular-nums">
              {periodRange || '—'}
            </dd>
          </div>
          <div>
            <dt>核算类型</dt>
            <dd>
              <span className={`pq-type-text is-${typeTone}`}>
                {payrollModeName(task)}
                {task.legacy ? ' · 历史' : ''}
              </span>
            </dd>
          </div>
          <div>
            <dt>申请人数</dt>
            <dd className="tabular-nums">{task.plan?.applicants != null ? `${task.plan.applicants} 人` : '—'}</dd>
          </div>
          <div>
            <dt>核算金额</dt>
            <dd className="pq-drawer__amount tabular-nums">
              {amount !== null ? (
                <>
                  <span className="pq-currency-sign">¥</span>
                  {formatPayrollAmount(amount)}
                </>
              ) : (
                <span className="pq-empty-val">待核算</span>
              )}
            </dd>
          </div>
          <div>
            <dt>申请模板</dt>
            <dd className="pq-drawer__template" title={task.template_name}>
              <FileSpreadsheet size={13} aria-hidden="true" />
              <span>{task.template_name || '—'}</span>
            </dd>
          </div>
        </dl>

        {/* 5. 平铺分段切换页签 */}
        <div className="pq-drawer__tabs" role="tablist" aria-label="批次详情分段">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'activity'}
            className={`pq-drawer__tab${activeTab === 'activity' ? ' is-active' : ''}`}
            onClick={() => setActiveTab('activity')}
          >
            <Terminal size={13.5} aria-hidden="true" />
            <span>执行动态</span>
            <span className="pq-drawer__tab-count tabular-nums">{business.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'deductions'}
            className={`pq-drawer__tab${activeTab === 'deductions' ? ' is-active' : ''}`}
            onClick={() => setActiveTab('deductions')}
          >
            <SlidersHorizontal size={13.5} aria-hidden="true" />
            <span>扣款口径</span>
            <span className="pq-drawer__tab-count tabular-nums">{deductionSources.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'review'}
            className={`pq-drawer__tab${activeTab === 'review' ? ' is-active' : ''}`}
            onClick={() => setActiveTab('review')}
          >
            <ListChecks size={13.5} aria-hidden="true" />
            <span>复核摘要</span>
            {done && !reviewAlert && <CheckCircle2 size={12.5} className="pq-drawer__tab-done" aria-hidden="true" />}
            {reviewAlert && <span className="pq-drawer__tab-warn tabular-nums">{reviewAlert.count}</span>}
          </button>
        </div>

        {/* 6. 分段内容面板 */}
        <div className="pq-drawer__panel" role="tabpanel">
          {activeTab === 'activity' && (
            <div className="pq-drawer__section">
              <div className="pq-drawer__section-head">
                <span className="pq-drawer__section-title">
                  业务执行时间线（{business.length} 条）
                </span>
                {technical.length > 0 && (
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                    onClick={() => setShowTechnical(prev => !prev)}
                  >
                    {showTechnical ? '隐藏诊断日志' : `查看诊断日志（${technical.length}）`}
                  </button>
                )}
              </div>

              {business.length > 0 ? (
                <ol className="pq-timeline">
                  {business.map((entry, index) => {
                    const isError = /ERROR/.test(entry.level || '');
                    const isWarn = /WARN/.test(entry.level || '');
                    return (
                      <li
                        key={index}
                        className={`pq-timeline__item${isError ? ' is-error' : isWarn ? ' is-warn' : ''}`}
                      >
                        <time className="tabular-nums">{formatLogClock(entry.time) || '--:--:--'}</time>
                        <p>{entry.text}</p>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className="pq-drawer__empty">任务启动后，此处将实时记录资料拉取、扣款匹配与核算节点。</p>
              )}

              {showTechnical && technical.length > 0 && (
                <pre className="pq-drawer__tech-log">{technical.map(entry => entry.text).join('\n')}</pre>
              )}
            </div>
          )}

          {activeTab === 'deductions' && (
            <div className="pq-drawer__section">
              <div className="pq-drawer__section-head">
                <span className="pq-drawer__section-title">本批次站点扣款口径来源</span>
                <div className="pq-drawer__section-head-ops">
                  {task.status === 'waiting_confirmation' && onConfirmDeductions && (
                    <button
                      type="button"
                      className="wbx-btn wbx-btn--sm wbx-btn--primary"
                      disabled={busy}
                      onClick={() => onConfirmDeductions(task)}
                    >
                      <Check size={12.5} aria-hidden="true" />
                      <span>确认口径并继续</span>
                    </button>
                  )}
                  <button
                    type="button"
                    className="wbx-btn wbx-btn--sm wbx-btn--ghost"
                    onClick={() => {
                      onClose();
                      onOpenDeductions();
                    }}
                  >
                    管理扣款配置
                  </button>
                </div>
              </div>
              {deductionSources.length > 0 ? (
                <>
                  <p className="pq-drawer__hint">
                    沿用已有站点例外或城市默认配置，未配置站点默认按零扣款处理，不会改写全局默认规则。
                  </p>
                  <ul className="pq-drawer__rule-list">
                    {deductionSources.map((entry: any, index: number) => (
                      <li key={index}>
                        <strong>{entry.station?.name || `站点 ${index + 1}`}</strong>
                        <span>{entry.source}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="pq-drawer__empty">当前批次尚未进入扣款规则匹配阶段，待资料准备完成后自动生成站点口径清单。</p>
              )}
            </div>
          )}

          {activeTab === 'review' && (
            <div className="pq-drawer__section">
              {done ? (
                <>
                  <p className="pq-drawer__hint">下载核算成品包后，请在 Excel / WPS 中重新计算并核对最终实发金额。</p>
                  <PayrollReviewSummary review={reviewSummary} />
                </>
              ) : (
                <p className="pq-drawer__empty">当前批次尚未完成核算，完成后将在此自动汇总人数、单价缺失与风控复核明细。</p>
              )}
            </div>
          )}
        </div>
      </div>
    </WorkbenchDrawer>
  );
}
