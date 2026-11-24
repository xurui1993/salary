import React from 'react';
import { Activity } from 'lucide-react';
import {
  getPlatformChannelStatus,
  type BreadcrumbModel,
  type QuickTargetId,
  type ShellCommandAction,
} from '../lib/shellNav';
import type { DownloadPlatform } from '../lib/downloadModules';
import type { PlatformStatusMap } from '../lib/workbench';

export interface HeaderBreadcrumbProps {
  model: BreadcrumbModel;
  disabled?: boolean;
  canBack?: boolean;
  canForward?: boolean;
  onStepBack?: () => void;
  onStepForward?: () => void;
  currentTargetId?: QuickTargetId;
  isPinned?: boolean;
  onTogglePin?: (targetId: QuickTargetId) => void;
  platformStatuses?: PlatformStatusMap;
  isRunning?: boolean;
  progress?: number;
  progressText?: string;
  activeDownloadCount?: number;
  errorLogCount?: number;
  onOpenLogDrawer?: () => void;
  onSelect: (action: ShellCommandAction) => void;
  onOpenPlatformAuth?: (platform?: DownloadPlatform) => void;
}

export const HeaderBreadcrumb = React.memo(function HeaderBreadcrumb({
  model,
  platformStatuses,
  isRunning = false,
  progress = 0,
  progressText = '',
  activeDownloadCount = 0,
  onOpenLogDrawer,
  onOpenPlatformAuth,
}: HeaderBreadcrumbProps) {
  const activeSibling = model.siblings.find(item => item.active) || model.siblings[0];
  const activePlatform: DownloadPlatform | undefined =
    activeSibling?.action.type === 'platform'
      ? (activeSibling.action.platform as DownloadPlatform)
      : model.groupId === 'approval'
        ? 'lanorange'
        : undefined;
  const activeChannel =
    activePlatform && activePlatform !== 'payout' && platformStatuses
      ? getPlatformChannelStatus(activePlatform, platformStatuses)
      : null;

  const pct = Math.max(0, Math.min(100, Math.round(progress)));

  return (
    <div className="wbx-topbar-context">
      <div className="wbx-topbar-location" aria-label="当前位置">
        <span className="wbx-topbar-module">{model.moduleLabel}</span>
        <span className="wbx-topbar-sep" aria-hidden="true">/</span>
        <h1 className="wbx-topbar-title">{model.viewLabel}</h1>
      </div>

      {activeChannel && onOpenPlatformAuth && (
        <button
          type="button"
          className={`wbx-topbar-status-tag is-${activeChannel.tone}`}
          onClick={() => onOpenPlatformAuth(activePlatform)}
          title={`当前平台状态：${activeChannel.statusText}（点击管理授权）`}
        >
          <span className={`wbx-channel-dot is-${activeChannel.tone}`} aria-hidden="true" />
          <span>{activeChannel.statusText}</span>
          {activeChannel.tone !== 'ready' && (
            <span className="wbx-topbar-status-tag__action">去登录</span>
          )}
        </button>
      )}

      {isRunning && (
        <button
          type="button"
          className="wbx-topbar-live-pill"
          onClick={onOpenLogDrawer}
          title="点击查看实时执行进度与运行日志"
        >
          <Activity size={12} className="wbx-topbar-live-pill__icon" aria-hidden="true" />
          <span className="wbx-topbar-live-pill__text">
            {`${progressText || '执行中'}${pct > 0 ? ` ${pct}%` : ''}`}
          </span>
        </button>
      )}
    </div>
  );
});
