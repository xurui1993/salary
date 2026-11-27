import React from 'react';
import {
  BadgeDollarSign,
  Building2,
  Compass,
  CreditCard,
  FileSpreadsheet,
  FileWarning,
  FolderCheck,
  FolderDown,
  FolderKanban,
  KeyRound,
  Layers,
  Radar,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  UserSearch,
  UsersRound,
  WalletCards,
  X,
} from 'lucide-react';
import { BrandLogo } from './BrandLogo';
import { SidebarResourceStrip } from './SidebarResourceStrip';
import type { DownloadPlatform } from '../lib/downloadModules';
import {
  getPlatformStatusCluster,
  type PayrollSubView,
  type PlatformStatusMap,
  type SystemResourceStatsInput,
} from '../lib/workbench';
import {
  canMemberAccessDownloadPlatform,
  getActiveNavGroup,
  getPlatformChannelStatus,
  SPECIAL_REPORT_SUBMODULES,
  type QuickTargetId,
  type ShellCommandAction,
} from '../lib/shellNav';
import {
  isBusinessModuleEnabled,
  resolveModuleGroupLabel,
  resolveSubmoduleLabel,
  useGlobalWorkbenchConfig,
} from '../lib/workbenchConfig';

export interface DualRailSidebarProps {
  workspaceView:
    | 'create'
    | 'history'
    | 'approval'
    | 'price-export'
    | 'pickup'
    | 'accounts'
    | 'platform-auth'
    | 'global-config';
  taskKind: 'download' | 'generate' | 'payroll';
  downloadPlatform: DownloadPlatform;
  activeReportId?: string;
  payrollSubView: PayrollSubView;
  collapsed?: boolean;
  isDrawerMode: boolean;
  taskFormLocked: boolean;
  platformStatuses: PlatformStatusMap;
  systemStats?: SystemResourceStatsInput | null;
  activeDownloadCount: number;
  payrollBadge: { label: string; tone: 'active' | 'warn' | 'ready' | 'done' } | null;
  approvalActiveCount: number;
  approvalPendingCount?: number;
  totalActiveCount: number;
  taskAttentionCount?: number;
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
  onOpenPlatformDock?: () => void;
  permissions?: Record<string, boolean>;
  isAdmin?: boolean;
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

export const DualRailSidebar = React.memo(function DualRailSidebar({
  workspaceView,
  taskKind,
  downloadPlatform,
  activeReportId = SPECIAL_REPORT_SUBMODULES[0].id,
  payrollSubView,
  collapsed = false,
  isDrawerMode,
  taskFormLocked,
  platformStatuses,
  systemStats,
  activeDownloadCount,
  payrollBadge,
  approvalActiveCount,
  approvalPendingCount = 0,
  totalActiveCount,
  taskAttentionCount = 0,
  onExecuteAction,
  onCloseMobile,
  permissions,
  isAdmin = true,
}: DualRailSidebarProps) {
  const globalConfig = useGlobalWorkbenchConfig();
  const activeGroup = getActiveNavGroup({ workspaceView, taskKind });
  const isCollapsedRail = Boolean(collapsed && !isDrawerMode);
  const canUse = (key: string) => isAdmin || !permissions || permissions[key] !== false;

  const collectionGroupLabel = resolveModuleGroupLabel('collection', globalConfig);
  const reportsGroupLabel = resolveModuleGroupLabel('reports', globalConfig);
  const payrollGroupLabel = resolveModuleGroupLabel('payroll', globalConfig);
  const adminGroupLabel = resolveModuleGroupLabel('admin', globalConfig);

  const collectionItems: SidebarNavItem[] = [
    {
      id: 'platform:fengshen',
      label: resolveSubmoduleLabel('platform:fengshen', '风神数据', globalConfig),
      icon: <Compass size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'collection' && downloadPlatform === 'fengshen',
      action: { type: 'platform', platform: 'fengshen' },
      channel: getPlatformChannelStatus('fengshen', platformStatuses),
    },
    {
      id: 'platform:lanorange',
      label: resolveSubmoduleLabel('platform:lanorange', '蓝橙数据', globalConfig),
      icon: <Layers size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'collection' && downloadPlatform === 'lanorange',
      action: { type: 'platform', platform: 'lanorange' },
      channel: getPlatformChannelStatus('lanorange', platformStatuses),
    },
    {
      id: 'platform:lanorange_mdr',
      label: resolveSubmoduleLabel('platform:lanorange_mdr', '新蓝橙数据', globalConfig),
      icon: <Building2 size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'collection' && downloadPlatform === 'lanorange_mdr',
      action: { type: 'platform', platform: 'lanorange_mdr' },
      channel: getPlatformChannelStatus('lanorange_mdr', platformStatuses),
    },
    {
      id: 'platform:payout',
      label: resolveSubmoduleLabel('platform:payout', '发薪平台', globalConfig),
      icon: <UsersRound size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'collection' && downloadPlatform === 'payout',
      action: { type: 'platform', platform: 'payout' },
      channel: getPlatformChannelStatus('payout', platformStatuses),
    },
    {
      id: 'platform:xiaoxiang',
      label: resolveSubmoduleLabel('platform:xiaoxiang', '小象灯塔', globalConfig),
      icon: <Radar size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'collection' && downloadPlatform === 'xiaoxiang',
      action: { type: 'platform', platform: 'xiaoxiang' },
      channel: getPlatformChannelStatus('xiaoxiang', platformStatuses),
    },
    {
      id: 'workspace:history',
      label: resolveSubmoduleLabel('workspace:history', '任务下载', globalConfig),
      icon: <FolderCheck size={15.5} />,
      active: workspaceView === 'history',
      action: { type: 'workspace', view: 'history' },
      badgeText: totalActiveCount > 0 ? String(totalActiveCount) : taskAttentionCount > 0 ? String(taskAttentionCount) : undefined,
      badgeTone: totalActiveCount > 0 ? 'active' : taskAttentionCount > 0 ? 'warn' : undefined,
    },
  ];

  const reportIconFor = (id: string) => {
    if (id === 'payment_binding') return <CreditCard size={15.5} />;
    if (id === 'abnormal_followup') return <UserSearch size={15.5} />;
    if (id === 'problem') return <FileWarning size={15.5} />;
    return <FolderKanban size={15.5} />;
  };

  const reportItems: SidebarNavItem[] = SPECIAL_REPORT_SUBMODULES.map(report => ({
    id: `report:${report.id}` as QuickTargetId,
    label: resolveSubmoduleLabel(`report:${report.id}`, report.label, globalConfig),
    icon: reportIconFor(report.id),
    active: workspaceView === 'create' && activeGroup === 'reports' && activeReportId === report.id,
    action: { type: 'report', reportId: report.id },
  }));

  const payrollItems: SidebarNavItem[] = [
    {
      id: 'payroll:batches',
      label: resolveSubmoduleLabel('payroll:batches', '兼职核算', globalConfig),
      icon: <WalletCards size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'batches',
      action: { type: 'payroll', subView: 'batches' },
    },
    {
      id: 'payroll:deductions',
      label: resolveSubmoduleLabel('payroll:deductions', '扣款配置', globalConfig),
      icon: <SlidersHorizontal size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'deductions',
      action: { type: 'payroll', subView: 'deductions' },
    },
    {
      id: 'payroll:templates',
      label: resolveSubmoduleLabel('payroll:templates', '模板中心', globalConfig),
      icon: <FileSpreadsheet size={15.5} />,
      active: workspaceView === 'create' && activeGroup === 'payroll' && payrollSubView === 'templates',
      action: { type: 'payroll', subView: 'templates' },
    },
    {
      id: 'workspace:approval',
      label: resolveSubmoduleLabel('workspace:approval', '价格审批', globalConfig),
      icon: <BadgeDollarSign size={15.5} />,
      active: workspaceView === 'approval' || workspaceView === 'price-export',
      action: { type: 'workspace', view: 'approval' },
    },
  ];

  const collectionAllowed =
    (isAdmin || isBusinessModuleEnabled('collection', globalConfig)) && canUse('collection');
  const visibleCollectionItems = collectionAllowed
    ? collectionItems.filter(item => {
        if (item.id === 'workspace:history') return true;
        const platId = item.id.replace('platform:', '') as DownloadPlatform;
        return canMemberAccessDownloadPlatform(platId, {
          isAdmin,
          permissions,
          globalConfig,
        });
      })
    : [];
  const visibleReportItems =
    (isAdmin || isBusinessModuleEnabled('reports', globalConfig)) && canUse('reports')
      ? reportItems
      : [];
  const visiblePayrollItems = payrollItems.filter(item => {
    if (item.id === 'workspace:approval') {
      return (isAdmin || isBusinessModuleEnabled('approval', globalConfig)) && canUse('approval');
    }
    return (isAdmin || isBusinessModuleEnabled('payroll', globalConfig)) && canUse('payroll');
  });

  const platformCluster = getPlatformStatusCluster(platformStatuses);
  const platformReadyCount = platformCluster.filter(item => item.tone === 'ready').length;
  const platformWarnCount = platformCluster.filter(item => item.tone === 'warn').length;

  const platformManagementItems: SidebarNavItem[] = [
    {
      id: 'workspace:pickup',
      label: resolveSubmoduleLabel('workspace:pickup', '组内共享', globalConfig),
      icon: <FolderDown size={15.5} />,
      active: workspaceView === 'pickup',
      action: { type: 'workspace', view: 'pickup' },
    },
    {
      id: 'workspace:platform-auth',
      label: resolveSubmoduleLabel('workspace:platform-auth', '授权管理', globalConfig),
      icon: <KeyRound size={15.5} />,
      active: workspaceView === 'platform-auth',
      action: { type: 'workspace', view: 'platform-auth' },
      badgeText: `${platformReadyCount}/${platformCluster.length}`,
      badgeTone:
        platformWarnCount > 0
          ? 'warn'
          : platformReadyCount === platformCluster.length
            ? 'ready'
            : undefined,
    },
    ...(isAdmin
      ? [
          {
            id: 'workspace:accounts' as const,
            label: resolveSubmoduleLabel('workspace:accounts', '用户权限分配', globalConfig),
            icon: <ShieldCheck size={15.5} />,
            active: workspaceView === 'accounts',
            action: { type: 'workspace' as const, view: 'accounts' as const },
          },
          {
            id: 'workspace:global-config' as const,
            label: resolveSubmoduleLabel('workspace:global-config', '全局配置', globalConfig),
            icon: <Settings2 size={15.5} />,
            active: workspaceView === 'global-config',
            action: { type: 'workspace' as const, view: 'global-config' as const },
          },
        ]
      : []),
  ];

  const renderNavItem = (item: SidebarNavItem) => (
    <button
      key={item.id}
      type="button"
      data-nav-key={item.id}
      disabled={taskFormLocked}
      title={isCollapsedRail ? item.label : undefined}
      aria-label={isCollapsedRail ? item.label : undefined}
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
    </button>
  );

  return (
    <aside
      className={`wb-sidebar wbx-sidebar wbx-flat-sidebar${isCollapsedRail ? ' is-collapsed' : ''}`}
      aria-label="工作台主导航"
    >
      {/* 顶部品牌区：与右侧 56px 顶栏精确对齐 */}
      <div className="wbx-flat-sidebar__brand">
        <BrandLogo
          collapsed={isCollapsedRail}
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

      {/* 全展开核心业务导航：数据采集 / 业务报表 / 薪资核算 / 平台管理 */}
      <nav className="wbx-flat-sidebar__nav" aria-label="业务功能导航">
        {visibleCollectionItems.length > 0 && (
          <section className="wbx-snav-group" aria-label={collectionGroupLabel}>
            <div className="wbx-snav-group__head">
              <span className="wbx-snav-group__title">{collectionGroupLabel}</span>
            </div>
            <div className="wbx-snav-group__list">
              {visibleCollectionItems.map(renderNavItem)}
            </div>
          </section>
        )}

        {visibleReportItems.length > 0 && (
          <section className="wbx-snav-group" aria-label={reportsGroupLabel}>
            <div className="wbx-snav-group__head">
              <span className="wbx-snav-group__title">{reportsGroupLabel}</span>
            </div>
            <div className="wbx-snav-group__list">
              {visibleReportItems.map(renderNavItem)}
            </div>
          </section>
        )}

        {visiblePayrollItems.length > 0 && (
          <section className="wbx-snav-group" aria-label={payrollGroupLabel}>
            <div className="wbx-snav-group__head">
              <span className="wbx-snav-group__title">{payrollGroupLabel}</span>
            </div>
            <div className="wbx-snav-group__list">
              {visiblePayrollItems.map(renderNavItem)}
            </div>
          </section>
        )}

        <section className="wbx-snav-group wbx-snav-group--delivery" aria-label={adminGroupLabel}>
          <div className="wbx-snav-group__head">
            <span className="wbx-snav-group__title">{adminGroupLabel}</span>
          </div>
          <div className="wbx-snav-group__list">
            {platformManagementItems.map(renderNavItem)}
          </div>
        </section>
      </nav>

      {/* 底部引擎资源状态条 */}
      <div className="wbx-flat-sidebar__footer">
        <SidebarResourceStrip stats={systemStats} collapsed={isCollapsedRail} />
      </div>
    </aside>
  );
});
