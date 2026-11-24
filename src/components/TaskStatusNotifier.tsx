import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  FolderOpen,
  KeyRound,
  X,
  XCircle,
} from 'lucide-react';
import type { TaskStatusAlert } from '../lib/taskWorkflow';

interface TaskStatusNotifierProps {
  alerts: TaskStatusAlert[];
  onDismiss: (key: string) => void;
  onOpenTask: (alert: TaskStatusAlert) => void;
  onOpenDirectory: (alert: TaskStatusAlert) => void;
  onOpenAuth: (system: string) => void;
}

function TaskAlertCard({
  alert,
  onDismiss,
  onOpenTask,
  onOpenDirectory,
  onOpenAuth,
}: {
  alert: TaskStatusAlert;
  onDismiss: (key: string) => void;
  onOpenTask: (alert: TaskStatusAlert) => void;
  onOpenDirectory: (alert: TaskStatusAlert) => void;
  onOpenAuth: (system: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  // Auto-dismiss completed cards after 10s unless hovered; keep blocked alerts until acted on or dismissed.
  useEffect(() => {
    if (alert.kind !== 'completed' || hovered) return;
    const timer = setTimeout(() => onDismiss(alert.key), 10000);
    return () => clearTimeout(timer);
  }, [alert.key, alert.kind, hovered, onDismiss]);

  const isCompleted = alert.kind === 'completed';
  const isAuthWait = alert.status === 'waiting_login';
  const isManualOrPartial = alert.status === 'waiting_manual' || alert.status === 'partial';
  const tone = isCompleted ? 'success' : isAuthWait || isManualOrPartial ? 'warn' : 'error';

  const heading = isCompleted
    ? '任务已完成'
    : isAuthWait
      ? '需要登录验证'
      : alert.status === 'waiting_manual'
        ? '任务等待确认'
        : alert.status === 'partial'
          ? '部分完成，存在异常'
          : '任务执行遇阻';

  return (
    <article
      className={`wbx-task-alert is-${tone}`}
      role={isCompleted ? 'status' : 'alert'}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="wbx-task-alert__head">
        <span className="wbx-task-alert__badge">
          {isCompleted ? (
            <CheckCircle2 size={14} aria-hidden="true" />
          ) : tone === 'warn' ? (
            <AlertTriangle size={14} aria-hidden="true" />
          ) : (
            <XCircle size={14} aria-hidden="true" />
          )}
          <span>{heading}</span>
        </span>
        <button
          type="button"
          className="wbx-task-alert__close"
          aria-label="关闭任务通知"
          onClick={() => onDismiss(alert.key)}
        >
          <X size={13} />
        </button>
      </div>

      <p className="wbx-task-alert__title" title={alert.title}>
        {alert.title}
      </p>
      <p className="wbx-task-alert__sub">{alert.subtitle}</p>

      <div className="wbx-task-alert__actions">
        {alert.needsAuth && (
          <button
            type="button"
            className="wbx-task-alert__btn is-primary"
            onClick={() => {
              onDismiss(alert.key);
              onOpenAuth(alert.primarySystem);
            }}
          >
            <KeyRound size={12.5} aria-hidden="true" />
            <span>去验证</span>
          </button>
        )}
        {alert.canOpenDir && (
          <button
            type="button"
            className="wbx-task-alert__btn is-primary"
            onClick={() => {
              onDismiss(alert.key);
              onOpenDirectory(alert);
            }}
          >
            <FolderOpen size={12.5} aria-hidden="true" />
            <span>打开目录</span>
          </button>
        )}
        <button
          type="button"
          className={`wbx-task-alert__btn${!alert.needsAuth && !alert.canOpenDir ? ' is-primary' : ''}`}
          onClick={() => {
            onDismiss(alert.key);
            onOpenTask(alert);
          }}
        >
          <span>{isCompleted ? '查看任务' : '查看处理'}</span>
          <ArrowUpRight size={12.5} aria-hidden="true" />
        </button>
      </div>
    </article>
  );
}

export function TaskStatusNotifier({
  alerts,
  onDismiss,
  onOpenTask,
  onOpenDirectory,
  onOpenAuth,
}: TaskStatusNotifierProps) {
  if (!alerts.length) return null;

  return (
    <aside
      className="wbx-task-notifier"
      aria-label="后台任务完成与异常通知"
      aria-live="polite"
    >
      {alerts.slice(0, 3).map(alert => (
        <TaskAlertCard
          key={alert.key}
          alert={alert}
          onDismiss={onDismiss}
          onOpenTask={onOpenTask}
          onOpenDirectory={onOpenDirectory}
          onOpenAuth={onOpenAuth}
        />
      ))}
    </aside>
  );
}
