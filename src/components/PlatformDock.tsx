import React, {useEffect, useRef, useState} from 'react';
import {connectionChips, type ConnectionChip} from '../lib/platformCatalog';
import {connectionTone, toneClass, type Tone} from '../lib/statusSemantics';

/** `workbench:platform-statuses` 事件的载荷（由 `SystemConnections` 广播）。 */
type PlatformStatusMap = Record<string, {state?: string; offline?: boolean; busy?: boolean} | undefined>;

/**
 * 头部平台入口组件的 props。
 */
export interface PlatformDockProps {
  /** 面板是否展开（受控）。 */
  open: boolean;
  /** 触发键回调（展开 / 收起）。 */
  onToggle: () => void;
  /** 请求收起（点击外部 / Esc）。 */
  onClose?: () => void;
  /** 需要处理的事项数，>0 时在触发键上显示强调点。 */
  attentionCount?: number;
  /** 面板宿主：由调用方注入受控的连接面板（避免出现第二个入口）。 */
  children?: React.ReactNode;
}

/** tone → 状态文案（与架构 §7.2 的 5 个语义一一对应）。 */
const TONE_TEXT: Record<Tone, string> = {
  success: '已连接',
  warn: '需验证',
  danger: '连接异常',
  progress: '连接中',
  neutral: '未连接',
};

/**
 * 头部「平台登录」单一入口：触发键 + 5 个平台状态灯 + 受控面板宿主。
 *
 * 数据来源（禁止在本组件内硬编码平台名）：
 * - 平台集合与短名：`platformCatalog.connectionChips()`（5 项，`dengta` 不进入）
 * - 实时状态：`workbench:platform-statuses` 事件（`SystemConnections` 轮询结果）
 * - 色调归一：`statusSemantics.connectionTone()` / `toneClass()`
 *
 * @param props 见 {@link PlatformDockProps}。
 * @returns 头部平台入口。
 */
export function PlatformDock({open, onToggle, onClose, attentionCount = 0, children}: PlatformDockProps) {
  const [statuses, setStatuses] = useState<PlatformStatusMap>({});
  const containerRef = useRef<HTMLDivElement>(null);
  const chips: ConnectionChip[] = connectionChips();

  useEffect(() => {
    const onStatuses = (event: Event) => {
      const detail = (event as CustomEvent<PlatformStatusMap>).detail;
      setStatuses(detail && typeof detail === 'object' ? detail : {});
    };
    window.addEventListener('workbench:platform-statuses', onStatuses as EventListener);
    return () => window.removeEventListener('workbench:platform-statuses', onStatuses as EventListener);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => (onClose ? onClose() : onToggle());
    const onPointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose, onToggle]);

  const readyCount = chips.filter(chip => connectionTone(statuses[chip.key]) === 'success').length;

  return (
    <div className="wbx-dock" ref={containerRef} data-open={open ? 'true' : 'false'}>
      <button
        type="button"
        className="wbx-dock__trigger"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`平台登录：${readyCount} / ${chips.length} 已就绪${attentionCount > 0 ? `，${attentionCount} 项待处理` : ''}`}
        onClick={onToggle}
      >
        <span className="wbx-dock__title">平台登录</span>
        {attentionCount > 0 && <span className="wbx-dot is-warn" aria-hidden="true" />}
      </button>
      {children}
    </div>
  );
}

export default PlatformDock;
