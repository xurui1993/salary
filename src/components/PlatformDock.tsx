import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ShieldCheck, X } from 'lucide-react';
import { getPlatformStatusCluster, type PlatformStatusMap } from '../lib/workbench';

export function PlatformDock({
  open: controlledOpen,
  onToggle,
  onClose,
  children,
}: {
  open?: boolean;
  onToggle?: () => void;
  onClose?: () => void;
  onOpenFengshen?: () => void;
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
  const warnCount = cluster.filter(item => item.tone === 'warn').length;
  const summaryTitle = cluster.map(item => `${item.shortLabel}：${item.statusText}`).join(' · ');

  const overallTone =
    warnCount > 0 ? 'warn' : busyCount > 0 ? 'busy' : readyCount > 0 ? 'ready' : 'idle';

  return (
    <div className="wbx-popover-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`wbx-header-tool-btn wbx-plat-btn${isOpen ? ' is-open' : ''}`}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label={`打开平台授权（已就绪 ${readyCount} / ${cluster.length}）`}
        title={summaryTitle}
        onClick={handleToggle}
      >
        <ShieldCheck
          size={13.5}
          className={`wbx-header-tool-icon${readyCount > 0 ? ' is-active' : ''}`}
          aria-hidden="true"
        />
        <span className="wbx-plat-btn__label">平台授权</span>
        <span
          className={`wbx-plat-dock-ratio tabular-nums is-${overallTone}`}
        >
          {readyCount}/{cluster.length}
        </span>
        <ChevronDown
          size={12}
          className={`wbx-plat-dock-chevron${isOpen ? ' is-open' : ''}`}
          aria-hidden="true"
        />
      </button>

      <div
        className="wbx-popover wbx-popover--platforms"
        role="dialog"
        aria-modal="false"
        aria-label="平台登录与连接状态"
        style={isOpen ? undefined : { display: 'none' }}
      >
        <div className="wbx-popover__head">
          <div>
            <span className="wbx-popover__title">五大业务平台连接中心</span>
            <p className="text-xs text-slate-500 mt-0.5">
              支持扫码或账号直连 · 授权状态实时同步
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
