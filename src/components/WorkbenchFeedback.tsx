import React, { useEffect } from 'react';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

export interface ToastNotice {
  id: number;
  tone: 'success' | 'info' | 'error';
  text: string;
}

/**
 * 悬浮轻提示：渲染于抽屉遮罩之上，确保在右侧详情抽屉内触发的保存/停止/复制/重试反馈清晰可见。
 */
export function WorkbenchToast({
  toast,
  onDismiss,
}: {
  toast: ToastNotice | null;
  onDismiss: () => void;
}) {
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(onDismiss, toast.tone === 'error' ? 5000 : 3400);
    return () => window.clearTimeout(timer);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div
      className={`wbx-toast is-${toast.tone}`}
      role={toast.tone === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      <span className="wbx-toast__icon" aria-hidden="true">
        {toast.tone === 'error' ? (
          <AlertCircle size={15} />
        ) : toast.tone === 'success' ? (
          <CheckCircle2 size={15} />
        ) : (
          <Info size={15} />
        )}
      </span>
      <span className="wbx-toast__text">{toast.text}</span>
      <button
        type="button"
        className="wbx-toast__close"
        aria-label="关闭提示"
        onClick={onDismiss}
      >
        <X size={13.5} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * 统一居中确认弹窗：替代双层抽屉叠加，使用规范化 wbx-btn 按钮体系。
 */
export function WorkbenchConfirmModal({
  title,
  description,
  hint,
  items,
  extraContent,
  confirmLabel,
  confirmTone = 'primary',
  busy = false,
  error,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  hint?: string;
  items?: string[];
  extraContent?: React.ReactNode;
  confirmLabel: string;
  confirmTone?: 'primary' | 'danger';
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [busy, onCancel]);

  return (
    <div
      className="wbx-modal-backdrop"
      role="presentation"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div
        className="wbx-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={event => event.stopPropagation()}
      >
        <header className="wbx-modal__head">
          <h3>{title}</h3>
          <button
            type="button"
            className="wbx-modal__close"
            aria-label="关闭弹窗"
            disabled={busy}
            onClick={onCancel}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="wbx-modal__body">
          <p className="wbx-modal__desc">{description}</p>
          {hint && <p className="wbx-modal__hint">{hint}</p>}
          {!!items?.length && (
            <ul className="wbx-modal__list">
              {items.slice(0, 20).map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
              {items.length > 20 && (
                <li className="wbx-modal__list-more">其余 {items.length - 20} 项已省略…</li>
              )}
            </ul>
          )}
          {extraContent}
          {error && (
            <p className="wb-error" role="alert">
              {error}
            </p>
          )}
        </div>

        <footer className="wbx-modal__foot">
          <button type="button" className="wbx-btn wbx-btn--sm" disabled={busy} onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            className={`wbx-btn wbx-btn--sm ${confirmTone === 'danger' ? 'wbx-btn--danger' : 'wbx-btn--primary'}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? '处理中…' : confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
}
