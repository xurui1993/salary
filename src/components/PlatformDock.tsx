import React, { useEffect, useRef, useState } from 'react';
import { ShieldCheck, ChevronDown, X } from 'lucide-react';
import { getPlatformStatusCluster, type PlatformStatusMap } from '../lib/workbench';

const dotClass = (tone: 'ready' | 'busy' | 'warn' | 'idle') =>
  tone === 'ready'
    ? 'wb-dot ready'
    : tone === 'busy'
      ? 'wb-dot busy'
      : tone === 'warn'
        ? 'wb-dot offline'
        : 'wb-dot';

export function PlatformDock({
  open: controlledOpen,
  onToggle,
  onClose,
  children,
}: {
  open?: boolean;
  onToggle?: () => void;
  onClose?: () => void;
  children?: React.ReactNode;
}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [statuses, setStatuses] = useState<PlatformStatusMap>({});
  const wrapRef = useRef<HTMLDivElement>(null);

  const isOpen = typeof controlledOpen === 'boolean' ? controlledOpen : internalOpen;
  const handleToggle = () => {
    if (onToggle) onToggle();
    else setInternalOpen(v => !v);
  };
  const handleClose = () => {
    if (onClose) onClose();
    else setInternalOpen(false);
  };

  useEffect(() => {
    const onStatuses = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail && typeof detail === 'object') {
        setStatuses(detail as PlatformStatusMap);
      }
    };
    window.addEventListener('workbench:platform-statuses', onStatuses);
    return () => window.removeEventListener('workbench:platform-statuses', onStatuses);
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') handleClose();
    };
    const onMouseDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        handleClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('mousedown', onMouseDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('mousedown', onMouseDown);
    };
  }, [isOpen]);

  const cluster = getPlatformStatusCluster(statuses);
  const readyCount = cluster.filter(item => item.tone === 'ready').length;
  const busyCount = cluster.filter(item => item.tone === 'busy').length;

  return (
    <div className="wbx-popover-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`wbx-plat-dock-trigger${isOpen ? ' is-open' : ''}`}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label="打开平台登录状态与连接管理"
        onClick={handleToggle}
      >
        <ShieldCheck size={15} className="text-sky-600 shrink-0" />
        <span>平台登录</span>
        <span className="wbx-plat-dock-dots" aria-hidden="true">
          {cluster.map(item => (
            <span key={item.key} className="wbx-plat-mini-item" title={`${item.shortLabel}：${item.statusText}`}>
              <span className={dotClass(item.tone)} />
              <span className="hidden xl:inline">{item.shortLabel}</span>
            </span>
          ))}
        </span>
        <span
          className={`wbx-pill ${
            readyCount === cluster.length
              ? 'wbx-pill--success'
              : busyCount > 0
                ? 'wbx-pill--progress'
                : readyCount > 0
                  ? 'wbx-pill--neutral'
                  : 'wbx-pill--warn'
          } tabular-nums`}
        >
          {readyCount}/{cluster.length} 就绪
        </span>
        <ChevronDown size={13} className={`text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      <div
        className="wbx-popover"
        role="dialog"
        aria-modal="false"
        aria-label="平台登录与连接状态"
        style={isOpen ? undefined : { display: 'none' }}
      >
          <div className="wbx-popover__head">
            <div>
              <span className="wbx-popover__title">五大业务平台连接中心</span>
              <p className="text-xs text-slate-500 mt-0.5">
                已就绪 {readyCount} / {cluster.length} 个数据源通道 · 支持扫码或账号直连
              </p>
            </div>
            <button
              type="button"
              className="wbx-btn wbx-btn--ghost wbx-btn--sm"
              aria-label="关闭平台登录弹窗"
              onClick={handleClose}
            >
              <X size={15} />
            </button>
          </div>
          {children}
        </div>
    </div>
  );
}
