import React from 'react';
import {
  BadgeDollarSign,
  Compass,
  CreditCard,
  FileSpreadsheet,
  FolderKanban,
  Layers,
  Radar,
  SlidersHorizontal,
  UserSearch,
  UsersRound,
  WalletCards,
  X,
} from 'lucide-react';
import { BrandLogo } from './BrandLogo';
import { SidebarResourceStrip } from './SidebarResourceStrip';
import type { DownloadPlatform } from '../lib/downloadModules';
import type { PayrollSubView, PlatformStatusMap, SystemResourceStatsInput } from '../lib/workbench';
import {
  getActiveNavGroup,
  getPlatformChannelStatus,
  SPECIAL_REPORT_SUBMODULES,
  type QuickTargetId,
  type ShellCommandAction,
} from '../lib/shellNav';

export interface DualRailSidebarProps {
  workspaceView: 'create' | 'history' | 'approval' | 'price-export';
  taskKind: 'download' | 'generate' | 'payroll';
  downloadPlatform: DownloadPlatform;
  activeReportId?: string;
  payrollSubView: PayrollSubView;
  collapsed?: boolean;
  isDrawerMode: boolean;
  taskFormLocked: boolean;
  platformStatuses: PlatformStatusMap;
  systemStats: SystemResourceStatsInput | null;
  activeDownloadCount: number;
  payrollBadge: { label: string; tone: 'active' | 'warn' | 'ready' | 'done' } | null;
  approvalActiveCount: number;
  approvalPendingCount?: number;
  totalActiveCount: number;
  hasLogErrors?: boolean;
  logDrawerOpen?: boolean;
  pinnedTargets?: QuickTargetId[];
  recentTargets?: QuickTargetId[];
  onExecuteAction: (action: ShellCommandAction) => void;
  onTogglePin?: (targetId: QuickTargetId) => void;
  onToggleCollapse?: () => void;
  onCloseMobile: () => void;
  onOpenCmdk?: () => void;
  onToggleLogs?: () => void;
  onOpenPlatformDock: () => void;
}

interface SidebarNavItem {
  id: QuickTargetId;
  label: string;
  icon: React.ReactNode;
  active: boolean;
  action: ShellCommandAction;
  channel?: { tone: 'ready' | 'busy' | 'warn' | 'idle'; statusText: string };
  badgeText?: string;
  badgeTone?: 'active' | 'warn' | 'ready' | 'done';
}

export function DualRailSidebar({
  workspaceView,
  taskKind,
  downloadPlatform,
  activeReportId = SPECIAL_REPORT_SUBMODULES[0].id,
  payrollSubView,
  isDrawerMode,
  taskFormLocked,
  platformStatuses,
  systemStats,
  activeDownloadCount,
  payrollBadge,
  approvalActiveCount,
  approvalPendingCount = 0,
  onExecuteAction,
  onCloseMobile,
  onOpenPlatformDock,
}: DualRailSidebarProps) {
  const activeGroup = getActiveNavGroup({ workspaceView, taskKind });

  const collectionItems: SidebarNavItem[] = [
    {
      id: 'platform:fengshen',
      label: '风神数据',
      icon: <Compass size={15.5} />,
      active: activeGroup === 'collection' && downloadPlatform === 'fengshen',
      action: { type: 'platform', platform: 'fengshen' },
      channel: getPlatformChannelStatus('fengshen', platformStatuses),
    },
    {
      id: 'platform:lanorange',
      label: '蓝橙数据',
      icon: <Layers size={15.5} />,
      active: activeGroup === 'collection' && downloadPlatform === 'lanorange',
      action: { type: 'platform', platform: 'lanorange' },
      channel: getPlatformChannelStatus('lanorange', platformStatuses),
    },
    {
      id: 'platform:payout',
      label: '发薪平台',
      icon: <UsersRound size={15.5} />,
      active: activeGroup === 'collection' && downloadPlatform === 'payout',
      action: { type: 'platform', platform: 'payout' },
      channel: getPlatformChannelStatus('payout', platformStatuses),
    },
    {
      id: 'platform:xiaoxiang',
      label: '小象灯塔',
      icon: <Radar size={15.5} />,
      active: activeGroup === 'collection' && downloadPlatform === 'xiaoxiang',
      action: { type: 'platform', platform: 'xiaoxiang' },
      channel: getPlatformChannelStatus('xiaoxiang', platformStatuses),
    },
  ];

  const reportIconFor = (id: string) => {
    if (id === 'payment_binding') return <CreditCard size={15.5} />;
    if (id === 'abnormal_followup') return <UserSearch size={15.5} />;
    return <FolderKanban size={15.5} />;
  };

  const reportItems: SidebarNavItem[] = SPECIAL_REPORT_SUBMODULES.map(report => ({
    id: `report:${report.id}` as QuickTargetId,
    label: report.label,
    icon: reportIconFor(report.id),
    active: workspaceView === 'create' && activeGroup === 'reports' && activeReportId === report.id,
    action: { type: 'report', reportId: report.id },
  }));

  const payrollItems: SidebarNavItem[] = [
    {
      id: 'payroll:batches',
      label: '兼职核算',
      icon: <WalletCards size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'batches',
      action: { type: 'payroll', subView: 'batches' },
      badgeText: payrollBadge?.label,
      badgeTone: payrollBadge?.tone,
    },
    {
      id: 'payroll:deductions',
      label: '扣款配置',
      icon: <SlidersHorizontal size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'deductions',
      action: { type: 'payroll', subView: 'deductions' },
    },
    {
      id: 'payroll:templates',
      label: '模板中心',
      icon: <FileSpreadsheet size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'templates',
      action: { type: 'payroll', subView: 'templates' },
    },
    {
      id: 'workspace:approval',
      label: '价格审批',
      icon: <BadgeDollarSign size={15.5} />,
      active: workspaceView === 'approval',
      action: { type: 'workspace', view: 'approval' },
      badgeText:
        approvalActiveCount > 0
          ? '运行中'
          : approvalPendingCount > 0
            ? `${approvalPendingCount}`
            : undefined,
      badgeTone: approvalActiveCount > 0 ? 'active' : 'warn',
    },
  ];

  const renderNavItem = (item: SidebarNavItem) => (
    <button
      key={item.id}
      type="button"
      data-nav-key={item.id}
      disabled={taskFormLocked}
      aria-current={item.active ? 'page' : undefined}
      className={`wbx-snav-item${item.active ? ' is-active' : ''}`}
      onClick={() => onExecuteAction(item.action)}
    >
      <span className="wbx-snav-icon" aria-hidden="true">
        {item.icon}
      </span>
      <span className="wbx-snav-label">{item.label}</span>
      {item.badgeText && (
        <span className={`wbx-snav-badge${item.badgeTone ? ` is-${item.badgeTone}` : ''}`}>
          {item.badgeText}
        </span>
      )}
      {item.channel && item.channel.tone !== 'idle' && (
        <span
          className={`wbx-channel-dot is-${item.channel.tone}`}
          title={`${item.label} · ${item.channel.statusText}`}
          aria-label={item.channel.statusText}
        />
      )}
    </button>
  );

  return (
    <aside
      className="wb-sidebar wbx-sidebar wbx-flat-sidebar"
      aria-label="工作台主导航"
    >
      {/* 顶部品牌区：与右侧 56px 顶栏精确对齐 */}
      <div className="wbx-flat-sidebar__brand">
        <BrandLogo
          collapsed={false}
          onClick={() => {
            onExecuteAction({ type: 'platform', platform: 'fengshen' });
          }}
        />
        {isDrawerMode && (
          <button
            type="button"
            className="wbx-flat-sidebar__mobile-close"
            aria-label="关闭导航菜单"
            onClick={onCloseMobile}
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* 全展开三分栏核心业务导航：数据采集 / 专项报表 / 薪资核算 */}
      <nav className="wbx-flat-sidebar__nav" aria-label="业务功能导航">
        <section className="wbx-snav-group" aria-label="数据采集">
          <div className="wbx-snav-group__head">
            <span className="wbx-snav-group__title">数据采集</span>
            {activeDownloadCount > 0 && (
              <span className="wbx-snav-group__meta tabular-nums">
                {activeDownloadCount} 采集中
              </span>
            )}
          </div>
          <div className="wbx-snav-group__list">
            {collectionItems.map(renderNavItem)}
          </div>
        </section>

        <section className="wbx-snav-group" aria-label="专项报表">
          <div className="wbx-snav-group__head">
            <span className="wbx-snav-group__title">专项报表</span>
          </div>
          <div className="wbx-snav-group__list">
            {reportItems.map(renderNavItem)}
          </div>
        </section>

        <section className="wbx-snav-group" aria-label="薪资核算">
          <div className="wbx-snav-group__head">
            <span className="wbx-snav-group__title">薪资核算</span>
          </div>
          <div className="wbx-snav-group__list">
            {payrollItems.map(renderNavItem)}
          </div>
        </section>
      </nav>

      {/* 底部引擎资源状态条 */}
      <div className="wbx-flat-sidebar__footer">
        <SidebarResourceStrip stats={systemStats} collapsed={false} />
      </div>
    </aside>
  );
}
