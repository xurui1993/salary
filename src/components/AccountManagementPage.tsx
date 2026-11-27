import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  Building2,
  Calculator,
  ChevronRight,
  Clock,
  Compass,
  CopyCheck,
  Download,
  Eye,
  EyeOff,
  FileCheck2,
  FileSpreadsheet,
  KeyRound,
  Layers,
  Lock,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  ShoppingBag,
  Store,
  UserPlus,
  Users,
  UsersRound,
  X,
} from 'lucide-react';
import {
  adminCreateAccount,
  adminResetPassword,
  adminSyncDefaultConfig,
  adminUpdateAccount,
  fetchAdminAccounts,
  fetchAdminAuditLogs,
  resetGlobalWorkbenchConfig,
  updateGlobalWorkbenchConfig,
  type AuditEvent,
  type PermissionKey,
  type WorkspaceDirectoryEntry,
  type WorkspaceUser,
} from '../lib/workspaceAuth';
import {
  ALL_PERMISSION_KEYS,
  buildDefaultNewMemberPermissions,
  buildFullPermissions,
  countEnabledPermissions,
  createDraftFromUser,
  filterAuditEvents,
  filterManagedUsers,
  formatAuditAction,
  formatAuditDetail,
  formatAuditTime,
  getEnabledPermissionLabels,
  getPermissionGroups,
  getStatusLabel,
  getVisiblePermissionKeys,
  getWorkspaceDisplayLabel,
  hasDraftChanges,
  resolveAuditTargetLabel,
  type AuditCategory,
  type UserPermissionDraft,
} from '../lib/accountConsole';
import {
  PLATFORM_CHANNEL_CATALOG,
  applyBusinessModuleEnabled,
  applyPlatformChannelMode,
  countGlobalConfigCustomizations,
  resolveModuleGroupLabel,
  resolveSubmoduleLabel,
  setGlobalWorkbenchConfig,
  useGlobalWorkbenchConfig,
  type BusinessModuleKey,
  type ChannelMode,
  type GlobalWorkbenchConfig,
  type PlatformChannelKey,
} from '../lib/workbenchConfig';
import { ChannelModuleAllocationPanel } from './ChannelModuleAllocationPanel';

export type AccountConsoleTab = 'members' | 'allocations' | 'audit';

interface AccountManagementPageProps {
  currentUserId: string;
  requestedTab?: AccountConsoleTab | null;
  requestedTabVersion?: number;
  onAccountsChanged: (workspaces: WorkspaceDirectoryEntry[]) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

const INPUT_BASE =
  'w-full h-8 rounded-lg border border-slate-200/90 bg-white px-2.5 text-[12.5px] text-[#18191C] placeholder:text-[#9499A0] transition duration-150 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15';

const PERMISSION_ICONS: Record<PermissionKey, React.ComponentType<{ className?: string }>> = {
  collection: Download,
  reports: FileSpreadsheet,
  payroll: Calculator,
  approval: FileCheck2,
  fengshen_use: Compass,
  lanorange_use: Layers,
  lanorange_mdr_use: Building2,
  baize_use: UsersRound,
  xiaoxiang_use: Store,
  benlai_use: ShoppingBag,
  shared_auth_manage: ShieldCheck,
};

const AUDIT_CATEGORY_OPTIONS: { key: AuditCategory; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'auth', label: '登录' },
  { key: 'permission', label: '权限' },
  { key: 'workspace', label: '空间' },
  { key: 'security', label: '安全' },
];

const AUDIT_CATEGORY_TONE: Record<Exclude<AuditCategory, 'all'>, string> = {
  auth: 'text-sky-700',
  permission: 'text-indigo-700',
  workspace: 'text-emerald-700',
  security: 'text-rose-700',
};

const MEMBER_STATUS_OPTIONS: {
  key: 'all' | 'active' | 'disabled';
  label: string;
}[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '启用' },
  { key: 'disabled', label: '停用' },
];

function CompactSwitch({
  checked,
  disabled,
  ariaLabel,
  onToggle,
}: {
  checked: boolean;
  disabled?: boolean;
  ariaLabel: string;
  onToggle: (e: React.MouseEvent) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onToggle}
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full transition-colors duration-150 ${
        checked ? 'bg-[#00AEEC]' : 'bg-slate-200'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-xs transition-transform duration-150 ${
          checked ? 'translate-x-[16px]' : 'translate-x-[2px]'
        }`}
      />
    </button>
  );
}

interface PermissionMatrixProps {
  permissions: Record<PermissionKey, boolean>;
  globalConfig: GlobalWorkbenchConfig;
  disabled?: boolean;
  columns?: 1 | 2;
  onChange: (key: PermissionKey, next: boolean) => void;
}

function PermissionMatrix({
  permissions,
  globalConfig,
  disabled = false,
  columns = 1,
  onChange,
}: PermissionMatrixProps) {
  const groups = useMemo(() => getPermissionGroups(globalConfig), [globalConfig]);

  return (
    <div className="space-y-3">
      {groups.map(group => {
        const groupKeys = group.items.map(i => i.key);
        const groupEnabled = countEnabledPermissions(permissions, groupKeys);
        return (
          <div key={group.id} className="space-y-1.5">
            <div className="flex items-center justify-between px-0.5">
              <span className="text-[11px] font-semibold tracking-wide text-slate-500">
                {group.title}
              </span>
              <span className="text-[11px] font-medium tabular-nums text-slate-400">
                {groupEnabled}/{group.items.length}
              </span>
            </div>
            <div
              className={
                columns === 2
                  ? 'grid grid-cols-1 sm:grid-cols-2 gap-1.5'
                  : 'space-y-1.5'
              }
            >
              {group.items.map(item => {
                const enabled = Boolean(permissions[item.key]);
                const Icon = PERMISSION_ICONS[item.key] || ShieldCheck;
                return (
                  <button
                    key={item.key}
                    type="button"
                    role="switch"
                    aria-checked={enabled}
                    aria-label={`${item.label}权限`}
                    disabled={disabled}
                    onClick={() => {
                      if (!disabled) onChange(item.key, !enabled);
                    }}
                    className={`w-full flex items-center justify-between gap-2.5 px-2.5 py-2 rounded-lg border text-left transition duration-150 ${
                      enabled
                        ? 'bg-white border-sky-200/85 hover:border-sky-300'
                        : 'bg-slate-50/60 border-slate-200/70 hover:bg-white hover:border-slate-300/80'
                    } ${disabled ? 'opacity-70 cursor-default' : 'cursor-pointer'}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span
                        className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 transition-colors ${
                          enabled
                            ? 'bg-sky-50 text-[#008EC4]'
                            : 'bg-slate-100 text-slate-400'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span
                            className={`text-[12.5px] font-semibold leading-tight truncate ${
                              enabled ? 'text-[#18191C]' : 'text-slate-600'
                            }`}
                          >
                            {item.label}
                          </span>
                          {item.globallyPaused && (
                            <span className="text-[10px] font-medium text-amber-600 shrink-0">
                              全局已暂停
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-400 leading-tight truncate mt-0.5">
                          {item.description}
                        </div>
                      </div>
                    </div>
                    <span
                      aria-hidden="true"
                      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full transition-colors duration-150 ${
                        enabled ? 'bg-[#00AEEC]' : 'bg-slate-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-xs transition-transform duration-150 ${
                          enabled ? 'translate-x-[16px]' : 'translate-x-[2px]'
                        }`}
                      />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AccountManagementPage({
  currentUserId,
  requestedTab,
  requestedTabVersion = 0,
  onAccountsChanged,
  onToast,
}: AccountManagementPageProps) {
  const globalConfig = useGlobalWorkbenchConfig();
  const [users, setUsers] = useState<WorkspaceUser[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyKey, setBusyKey] = useState('');

  const [activeTab, setActiveTab] = useState<AccountConsoleTab>('members');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'disabled'>('all');
  const [allocationQuery, setAllocationQuery] = useState('');
  const [allocationSaving, setAllocationSaving] = useState(false);
  const [confirmResetAllocations, setConfirmResetAllocations] = useState(false);
  const [auditQuery, setAuditQuery] = useState('');
  const [auditCategory, setAuditCategory] = useState<AuditCategory>('all');

  const [selectedUserId, setSelectedUserId] = useState<string>('');
  const [drafts, setDrafts] = useState<Record<string, UserPermissionDraft>>({});

  // Inline password reset inside right inspector
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [resetPwdValue, setResetPwdValue] = useState('');
  const [resetPwdVisible, setResetPwdVisible] = useState(false);

  // Create member modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createUsername, setCreateUsername] = useState('');
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createPasswordVisible, setCreatePasswordVisible] = useState(false);
  const [createNote, setCreateNote] = useState('');
  const [createPermissions, setCreatePermissions] = useState<Record<PermissionKey, boolean>>(() =>
    buildDefaultNewMemberPermissions(),
  );
  const [createError, setCreateError] = useState('');

  const onAccountsChangedRef = useRef(onAccountsChanged);
  onAccountsChangedRef.current = onAccountsChanged;
  const onToastRef = useRef(onToast);
  onToastRef.current = onToast;

  const visiblePermissionKeys = useMemo(
    () => getVisiblePermissionKeys(globalConfig),
    [globalConfig],
  );

  const syncDraftsFromUsers = useCallback((list: WorkspaceUser[]) => {
    setDrafts(() => {
      const next: Record<string, UserPermissionDraft> = {};
      for (const u of list) {
        next[u.id] = createDraftFromUser(u);
      }
      return next;
    });
  }, []);

  const loadData = useCallback(
    async (silent = false) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const [acctRes, auditRes] = await Promise.all([
          fetchAdminAccounts(),
          fetchAdminAuditLogs().catch(() => ({ events: [] as AuditEvent[] })),
        ]);
        const nextUsers = acctRes.users || [];
        if (acctRes.global_config) {
          setGlobalWorkbenchConfig(acctRes.global_config);
        }
        setUsers(nextUsers);
        setAuditEvents(auditRes.events || []);
        syncDraftsFromUsers(nextUsers);
        onAccountsChangedRef.current(acctRes.workspaces || []);
      } catch (err) {
        onToastRef.current(
          err instanceof Error ? err.message : '加载用户权限数据失败',
          'error',
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [syncDraftsFromUsers],
  );

  useEffect(() => {
    void loadData(false);
  }, [loadData]);

  useEffect(() => {
    if (requestedTab && requestedTabVersion > 0) {
      setActiveTab(requestedTab);
    }
  }, [requestedTab, requestedTabVersion]);

  const activeMemberCount = useMemo(
    () => users.filter(u => u.status === 'active').length,
    [users],
  );

  const disabledMemberCount = useMemo(
    () => users.filter(u => u.status === 'disabled').length,
    [users],
  );

  const sharedPlatformCount = useMemo(
    () =>
      PLATFORM_CHANNEL_CATALOG.filter(
        p => globalConfig.channel_modes[p.key] === 'shared',
      ).length,
    [globalConfig.channel_modes],
  );

  const allocCustomStats = useMemo(
    () => countGlobalConfigCustomizations(globalConfig),
    [globalConfig],
  );
  const hasCustomAllocations =
    allocCustomStats.channels > 0 || allocCustomStats.modules > 0;

  const filteredMembers = useMemo(
    () =>
      filterManagedUsers(users, {
        query: searchQuery,
        status: statusFilter,
        role: 'all',
      }),
    [users, searchQuery, statusFilter],
  );

  const filteredAuditEvents = useMemo(
    () =>
      filterAuditEvents(auditEvents, {
        query: auditQuery,
        category: auditCategory,
        users,
      }),
    [auditEvents, auditQuery, auditCategory, users],
  );

  useEffect(() => {
    if (filteredMembers.length === 0) {
      return;
    }
    const stillVisible = filteredMembers.some(u => u.id === selectedUserId);
    if (!selectedUserId || !stillVisible) {
      setSelectedUserId(filteredMembers[0].id);
      setShowResetPassword(false);
      setResetPwdValue('');
    }
  }, [filteredMembers, selectedUserId]);

  const selectedUser = useMemo(
    () => users.find(u => u.id === selectedUserId) || filteredMembers[0] || null,
    [users, selectedUserId, filteredMembers],
  );

  const selectedDraft = selectedUser
    ? drafts[selectedUser.id] || createDraftFromUser(selectedUser)
    : null;

  const selectedDirty = Boolean(
    selectedUser && selectedDraft && hasDraftChanges(selectedUser, selectedDraft),
  );

  const openCreateModal = () => {
    setCreateUsername('');
    setCreateDisplayName('');
    setCreatePassword('');
    setCreatePasswordVisible(false);
    setCreateNote('');
    setCreatePermissions(buildDefaultNewMemberPermissions(globalConfig));
    setCreateError('');
    setCreateOpen(true);
  };

  const handleSelectMember = (userId: string) => {
    setSelectedUserId(userId);
    setShowResetPassword(false);
    setResetPwdValue('');
  };

  const updateUserDraftPermission = (userId: string, key: PermissionKey, nextVal: boolean) => {
    const targetUser = users.find(u => u.id === userId);
    if (!targetUser) return;
    setDrafts(prev => {
      const base = prev[userId] || createDraftFromUser(targetUser);
      return {
        ...prev,
        [userId]: {
          ...base,
          permissions: {
            ...base.permissions,
            [key]: nextVal,
          },
        },
      };
    });
  };

  const batchSetUserPermissions = (userId: string, enabled: boolean) => {
    const targetUser = users.find(u => u.id === userId);
    if (!targetUser) return;
    setDrafts(prev => {
      const base = prev[userId] || createDraftFromUser(targetUser);
      const nextPerms = { ...base.permissions };
      for (const key of ALL_PERMISSION_KEYS) {
        if (visiblePermissionKeys.includes(key)) {
          nextPerms[key] = enabled;
        }
      }
      return {
        ...prev,
        [userId]: {
          ...base,
          permissions: nextPerms,
        },
      };
    });
  };

  const resetUserDraft = (user: WorkspaceUser) => {
    setDrafts(prev => ({
      ...prev,
      [user.id]: createDraftFromUser(user),
    }));
  };

  const handleSavePermissions = async (user: WorkspaceUser) => {
    const draft = drafts[user.id] || createDraftFromUser(user);
    setBusyKey(`save:${user.id}`);
    try {
      const res = await adminUpdateAccount(user.id, {
        role: draft.role,
        permissions: draft.permissions,
      });
      setUsers(res.users);
      setDrafts(prev => ({
        ...prev,
        [user.id]: createDraftFromUser(res.user),
      }));
      onAccountsChanged(res.workspaces);
      onToast(`已保存 ${user.display_name} 的模块权限`, 'success');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToast(err instanceof Error ? err.message : '保存权限失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleToggleEnabled = async (user: WorkspaceUser, nextEnabled: boolean) => {
    setBusyKey(`toggle:${user.id}`);
    try {
      const res = await adminUpdateAccount(user.id, { enabled: nextEnabled });
      setUsers(res.users);
      onAccountsChanged(res.workspaces);
      onToast(
        nextEnabled ? `已启用账号：${user.display_name}` : `已停用账号：${user.display_name}`,
        'success',
      );
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToast(err instanceof Error ? err.message : '更新账号状态失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    if (resetPwdValue.trim().length < 6) {
      onToast('新密码长度至少为 6 位', 'error');
      return;
    }
    setBusyKey(`pwd:${selectedUser.id}`);
    try {
      const res = await adminResetPassword(selectedUser.id, resetPwdValue.trim());
      onToast(res.message || `已重置 ${selectedUser.display_name} 的登录密码`, 'success');
      setShowResetPassword(false);
      setResetPwdValue('');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToast(err instanceof Error ? err.message : '重置密码失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleSyncDefaultConfig = async (user: WorkspaceUser) => {
    setBusyKey(`sync:${user.id}`);
    try {
      const res = await adminSyncDefaultConfig(user.id);
      onToast(res.message || `已向 ${user.display_name} 同步标准扣款表`, 'success');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToast(err instanceof Error ? err.message : '同步默认扣款表失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const uname = createUsername.trim();
    const dname = createDisplayName.trim() || uname;
    const pwd = createPassword;
    if (uname.length < 2) {
      setCreateError('登录账号至少需要 2 个字符');
      return;
    }
    if (pwd.length < 6) {
      setCreateError('初始密码长度至少为 6 位');
      return;
    }
    setCreateError('');
    setBusyKey('create');
    try {
      const res = await adminCreateAccount({
        username: uname,
        display_name: dname,
        password: pwd,
        role: 'member',
        permissions: createPermissions,
        note: createNote.trim(),
      });
      setUsers(res.users);
      setDrafts(prev => ({
        ...prev,
        [res.user.id]: createDraftFromUser(res.user),
      }));
      setSelectedUserId(res.user.id);
      setActiveTab('members');
      setStatusFilter('all');
      setSearchQuery('');
      setCreateOpen(false);
      onAccountsChanged(res.workspaces);
      onToast(`已新建成员：${res.user.display_name}`, 'success');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : '新建成员失败');
    } finally {
      setBusyKey('');
    }
  };

  const handleMovePlatform = useCallback(
    async (key: PlatformChannelKey, nextMode: ChannelMode) => {
      if (allocationSaving) return;
      const prev = globalConfig;
      if (prev.channel_modes[key] === nextMode) return;
      const nextModes = applyPlatformChannelMode(prev, key, nextMode);
      const platformLabel =
        PLATFORM_CHANNEL_CATALOG.find(item => item.key === key)?.defaultLabel || key;
      setGlobalWorkbenchConfig({
        ...prev,
        channel_modes: nextModes,
      });
      setAllocationSaving(true);
      try {
        const res = await updateGlobalWorkbenchConfig({
          channel_modes: nextModes,
        });
        setGlobalWorkbenchConfig(res.config);
        onToastRef.current(
          `已将「${platformLabel}」设为${nextMode === 'shared' ? '全局共享通道' : '个人独立通道'}并全局同步`,
          'success',
        );
        fetchAdminAuditLogs()
          .then(r => setAuditEvents(r.events || []))
          .catch(() => {});
      } catch (err) {
        setGlobalWorkbenchConfig(prev);
        onToastRef.current(
          err instanceof Error ? err.message : '更新平台通道归属失败',
          'error',
        );
      } finally {
        setAllocationSaving(false);
      }
    },
    [allocationSaving, globalConfig],
  );

  const handleMoveModule = useCallback(
    async (key: BusinessModuleKey, nextEnabled: boolean) => {
      if (allocationSaving) return;
      const prev = globalConfig;
      if (Boolean(prev.module_permissions[key]) === nextEnabled) return;
      const nextModules = applyBusinessModuleEnabled(prev, key, nextEnabled);
      const moduleLabel =
        key === 'approval'
          ? resolveSubmoduleLabel('workspace:approval', '价格审批', prev)
          : resolveModuleGroupLabel(key, prev);
      setGlobalWorkbenchConfig({
        ...prev,
        module_permissions: nextModules,
      });
      setAllocationSaving(true);
      try {
        const res = await updateGlobalWorkbenchConfig({
          module_permissions: nextModules,
        });
        setGlobalWorkbenchConfig(res.config);
        onToastRef.current(
          `已将「${moduleLabel}」设为${nextEnabled ? '全局开放' : '全局暂停'}并全局同步`,
          'success',
        );
        fetchAdminAuditLogs()
          .then(r => setAuditEvents(r.events || []))
          .catch(() => {});
      } catch (err) {
        setGlobalWorkbenchConfig(prev);
        onToastRef.current(
          err instanceof Error ? err.message : '更新业务模块状态失败',
          'error',
        );
      } finally {
        setAllocationSaving(false);
      }
    },
    [allocationSaving, globalConfig],
  );

  const handleConfirmResetAllocations = useCallback(async () => {
    if (allocationSaving) return;
    setAllocationSaving(true);
    try {
      const res = await resetGlobalWorkbenchConfig('channels');
      setGlobalWorkbenchConfig(res.config);
      setConfirmResetAllocations(false);
      onToastRef.current('已恢复默认通道与模块分配', 'success');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToastRef.current(
        err instanceof Error ? err.message : '恢复默认分配失败',
        'error',
      );
    } finally {
      setAllocationSaving(false);
    }
  }, [allocationSaving]);

  const canResetSelectedPwd = Boolean(
    selectedUser &&
      selectedUser.id !== currentUserId &&
      selectedUser.username !== 'host_admin',
  );

  const isSelectedEditable = Boolean(selectedUser && selectedUser.role !== 'admin');

  return (
    <div
      className="w-full space-y-3 pb-4"
      data-testid="account-management-page"
    >
      {/* 紧凑单行顶栏：标题 + 内联指标 + 刷新 / 新建成员 */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-0.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0">
          <h1 className="text-[17px] font-semibold tracking-tight text-[#18191C] leading-none">
            用户权限分配
          </h1>
          <span className="hidden sm:inline-block h-3.5 w-px bg-slate-200 self-center" aria-hidden="true" />
          <p className="text-[12px] text-[#61666D] tabular-nums flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span>
              成员 <strong className="font-semibold text-[#18191C]">{users.length}</strong>
            </span>
            <span className="text-slate-300" aria-hidden="true">·</span>
            <span>
              启用 <strong className="font-semibold text-emerald-700">{activeMemberCount}</strong>
            </span>
            {disabledMemberCount > 0 && (
              <>
                <span className="text-slate-300" aria-hidden="true">·</span>
                <span>
                  停用 <strong className="font-semibold text-slate-600">{disabledMemberCount}</strong>
                </span>
              </>
            )}
            <span className="text-slate-300" aria-hidden="true">·</span>
            <span>
              共享通道{' '}
              <strong className="font-semibold text-[#0086C4]">
                {sharedPlatformCount}/{PLATFORM_CHANNEL_CATALOG.length}
              </strong>
            </span>
            <span className="text-slate-300" aria-hidden="true">·</span>
            <span>
              审计 <strong className="font-semibold text-[#18191C]">{auditEvents.length}</strong>
            </span>
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            disabled={refreshing || loading}
            onClick={() => void loadData(true)}
            aria-label="刷新用户权限数据"
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#4E5969] transition cursor-pointer disabled:opacity-55 whitespace-nowrap shrink-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            type="button"
            onClick={openCreateModal}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer shadow-xs whitespace-nowrap shrink-0"
          >
            <UserPlus className="w-3.5 h-3.5" />
            新建成员
          </button>
        </div>
      </div>

      {/* 单层高纯净白主容器 */}
      <div
        className={`rounded-xl border border-slate-200/85 bg-white ${
          activeTab === 'allocations' ? 'overflow-visible' : 'overflow-hidden'
        }`}
      >
        {/* 合并工具栏：成员权限 / 通道与模块分配 / 审计日志 + 搜索筛选 */}
        <div className="px-3.5 py-2 border-b border-slate-100 bg-slate-50/45 rounded-t-xl flex flex-wrap items-center justify-between gap-2.5">
          <div
            className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-slate-100/85 border border-slate-200/60"
            role="tablist"
            aria-label="权限分配视图"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'members'}
              onClick={() => setActiveTab('members')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer whitespace-nowrap shrink-0 ${
                activeTab === 'members'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              成员权限
              <span className="text-[11px] tabular-nums text-slate-400">
                {users.length}
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'allocations'}
              onClick={() => setActiveTab('allocations')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer whitespace-nowrap shrink-0 ${
                activeTab === 'allocations'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              通道与模块分配
              <span className="text-[11px] tabular-nums text-slate-400">
                {sharedPlatformCount}/{PLATFORM_CHANNEL_CATALOG.length}
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'audit'}
              onClick={() => setActiveTab('audit')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer whitespace-nowrap shrink-0 ${
                activeTab === 'audit'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              审计日志
              <span className="text-[11px] tabular-nums text-slate-400">
                {auditEvents.length}
              </span>
            </button>
          </div>

          {activeTab === 'members' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-48 sm:w-56">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="搜索姓名、账号或备注..."
                  aria-label="搜索成员"
                  className={`${INPUT_BASE} pl-8 pr-7`}
                />
                {searchQuery && (
                  <button
                    type="button"
                    aria-label="清空成员搜索"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-slate-100/80 border border-slate-200/60">
                {MEMBER_STATUS_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setStatusFilter(opt.key)}
                    className={`h-7 px-2.5 rounded-md text-[11.5px] font-medium transition cursor-pointer ${
                      statusFilter === opt.key
                        ? 'bg-white text-[#0086C4] font-semibold shadow-xs'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'allocations' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-48 sm:w-56">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={allocationQuery}
                  onChange={e => setAllocationQuery(e.target.value)}
                  placeholder="搜索平台或业务模块..."
                  aria-label="搜索通道与业务模块"
                  className={`${INPUT_BASE} pl-8 pr-7`}
                />
                {allocationQuery && (
                  <button
                    type="button"
                    aria-label="清空通道搜索"
                    onClick={() => setAllocationQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <button
                type="button"
                disabled={allocationSaving || !hasCustomAllocations}
                onClick={() => setConfirmResetAllocations(true)}
                className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#4E5969] transition cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                恢复默认分配
              </button>
            </div>
          )}

          {activeTab === 'audit' && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-48 sm:w-56">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={auditQuery}
                  onChange={e => setAuditQuery(e.target.value)}
                  placeholder="筛选操作人、事件或对象..."
                  aria-label="搜索审计日志"
                  className={`${INPUT_BASE} pl-8 pr-7`}
                />
                {auditQuery && (
                  <button
                    type="button"
                    aria-label="清空日志搜索"
                    onClick={() => setAuditQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <div className="inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-slate-100/80 border border-slate-200/60">
                {AUDIT_CATEGORY_OPTIONS.map(opt => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setAuditCategory(opt.key)}
                    className={`h-7 px-2 rounded-md text-[11.5px] font-medium transition cursor-pointer ${
                      auditCategory === opt.key
                        ? 'bg-white text-[#0086C4] font-semibold shadow-xs'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 加载态 */}
        {loading ? (
          <div className="py-16 text-center text-[13px] text-slate-400">
            正在加载成员与权限配置…
          </div>
        ) : activeTab === 'members' ? (
          /* ===================== 视图一：左右分栏紧致权限分配工作区 ===================== */
          filteredMembers.length === 0 ? (
            <div className="py-14 px-6 text-center space-y-2.5">
              <div className="w-9 h-9 rounded-lg bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
                <Users className="w-4.5 h-4.5" />
              </div>
              <div className="text-[13px] font-medium text-[#18191C]">
                未找到匹配的成员账号
              </div>
              <p className="text-[12px] text-slate-400">
                可调整筛选条件或点击右上角「新建成员」直接开通账号。
              </p>
              {(searchQuery || statusFilter !== 'all') && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setStatusFilter('all');
                  }}
                  className="inline-flex items-center h-7 px-3 rounded-lg border border-slate-200 text-[12px] text-[#0086C4] hover:bg-sky-50 cursor-pointer"
                >
                  重置筛选
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1.18fr)_430px] divide-y lg:divide-y-0 lg:divide-x divide-slate-100">
              {/* 左侧：紧致高密度成员列表 */}
              <div className="min-w-0 overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50/55 text-[11px] font-semibold text-slate-500">
                      <th className="py-2 pl-4 pr-2 font-semibold">成员账号</th>
                      <th className="py-2 px-2.5 font-semibold">权限概览</th>
                      <th className="py-2 px-2.5 font-semibold w-[76px] text-center">状态</th>
                      <th className="py-2 pl-2 pr-3.5 font-semibold w-[56px] text-right">分配</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100/90">
                    {filteredMembers.map(user => {
                      const isSelf = user.id === currentUserId;
                      const isAdmin = user.role === 'admin';
                      const isSelected = selectedUser?.id === user.id;
                      const draft = drafts[user.id] || createDraftFromUser(user);
                      const dirty = hasDraftChanges(user, draft);
                      const enabledCount = isAdmin
                        ? visiblePermissionKeys.length
                        : countEnabledPermissions(draft.permissions, visiblePermissionKeys);
                      const enabledLabels = getEnabledPermissionLabels(
                        draft.permissions,
                        isAdmin,
                        globalConfig,
                      );
                      const canToggle = !isSelf && user.username !== 'host_admin';
                      const toggling = busyKey === `toggle:${user.id}`;

                      return (
                        <tr
                          key={user.id}
                          onClick={() => handleSelectMember(user.id)}
                          className={`group transition-colors cursor-pointer ${
                            isSelected
                              ? 'bg-[#00AEEC]/[0.06]'
                              : 'hover:bg-slate-50/75'
                          }`}
                        >
                          {/* 成员账号（无角色预设标签） */}
                          <td className="py-2.5 pl-4 pr-2 align-middle">
                            <div className="flex items-center gap-2.5 min-w-0">
                              <div
                                className={`w-7 h-7 rounded-lg flex items-center justify-center text-[12px] font-semibold shrink-0 ${
                                  isAdmin
                                    ? 'bg-sky-50 text-[#008EC4] border border-sky-200/70'
                                    : user.enabled
                                      ? 'bg-slate-100 text-slate-700'
                                      : 'bg-slate-100 text-slate-400'
                                }`}
                              >
                                {(user.display_name || user.username).slice(0, 1).toUpperCase()}
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5 min-w-0">
                                  <button
                                    type="button"
                                    onClick={e => {
                                      e.stopPropagation();
                                      handleSelectMember(user.id);
                                    }}
                                    className={`text-[13px] font-semibold truncate text-left cursor-pointer ${
                                      isSelected ? 'text-[#007BB5]' : 'text-[#18191C]'
                                    }`}
                                  >
                                    {user.display_name}
                                  </button>
                                  {isSelf && (
                                    <span className="text-[10.5px] font-medium text-emerald-600 shrink-0">
                                      当前
                                    </span>
                                  )}
                                </div>
                                <div className="flex items-center gap-1.5 text-[11.5px] text-slate-400 mt-0.5 min-w-0">
                                  <span className="font-mono truncate">@{user.username}</span>
                                  {user.note && (
                                    <>
                                      <span className="text-slate-300">·</span>
                                      <span className="truncate max-w-[140px]">{user.note}</span>
                                    </>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* 权限概览 */}
                          <td className="py-2.5 px-2.5 align-middle">
                            <div className="space-y-1 min-w-[140px]">
                              <div className="flex items-center gap-2">
                                <div className="flex items-center gap-0.5 shrink-0" aria-hidden="true">
                                  {visiblePermissionKeys.map((k, idx) => (
                                    <span
                                      key={k}
                                      className={`h-1.5 w-2 rounded-[2px] ${
                                        idx < enabledCount
                                          ? enabledCount === visiblePermissionKeys.length
                                            ? 'bg-emerald-500'
                                            : 'bg-[#00AEEC]'
                                          : 'bg-slate-200/90'
                                      }`}
                                    />
                                  ))}
                                </div>
                                <span className="text-[11.5px] font-semibold tabular-nums text-slate-600">
                                  {enabledCount}/{visiblePermissionKeys.length}
                                </span>
                                {dirty && (
                                  <span className="text-[10.5px] font-medium text-amber-600">
                                    未保存
                                  </span>
                                )}
                              </div>
                              <div className="text-[11px] text-slate-400 truncate max-w-[260px]">
                                {isAdmin
                                  ? '全模块与共享通道权限'
                                  : enabledLabels.length > 0
                                    ? enabledLabels.join(' · ')
                                    : '未分配业务权限'}
                              </div>
                            </div>
                          </td>

                          {/* 启停状态 */}
                          <td className="py-2.5 px-2.5 align-middle text-center">
                            {canToggle ? (
                              <div className="inline-flex items-center justify-center">
                                <CompactSwitch
                                  checked={user.enabled}
                                  disabled={toggling}
                                  ariaLabel={`切换 ${user.display_name} 启用状态`}
                                  onToggle={e => {
                                    e.stopPropagation();
                                    void handleToggleEnabled(user, !user.enabled);
                                  }}
                                />
                              </div>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                                <span
                                  className={`w-1.5 h-1.5 rounded-full ${
                                    user.status === 'active'
                                      ? 'bg-emerald-500'
                                      : 'bg-slate-300'
                                  }`}
                                />
                                {user.status === 'active' ? '常驻' : getStatusLabel(user.status)}
                              </span>
                            )}
                          </td>

                          {/* 右侧选中箭头 */}
                          <td className="py-2.5 pl-2 pr-3.5 align-middle text-right">
                            <span
                              className={`inline-flex items-center justify-end gap-0.5 text-[11.5px] font-medium ${
                                isSelected
                                  ? 'text-[#0086C4]'
                                  : 'text-slate-300 group-hover:text-slate-500'
                              }`}
                            >
                              <ChevronRight className="w-4 h-4" />
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* 右侧：常驻一体化权限分配面板 */}
              {selectedUser && selectedDraft && (
                <div
                  className="flex flex-col bg-slate-50/25 min-w-0"
                  data-testid="permission-inspector"
                >
                  {/* 面板身份头 */}
                  <div className="px-4 py-3 bg-white border-b border-slate-100 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <h2 className="text-[14px] font-semibold text-[#18191C] truncate">
                          {selectedUser.display_name}
                        </h2>
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 shrink-0">
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              selectedUser.status === 'active'
                                ? 'bg-emerald-500'
                                : 'bg-slate-400'
                            }`}
                          />
                          {getStatusLabel(selectedUser.status)}
                        </span>
                      </div>
                      <p className="text-[11.5px] text-slate-400 mt-0.5 truncate">
                        <span className="font-mono">@{selectedUser.username}</span>
                        <span className="mx-1.5 text-slate-300">·</span>
                        <span>{getWorkspaceDisplayLabel(selectedUser.workspace_id)}</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {canResetSelectedPwd && (
                        <button
                          type="button"
                          onClick={() => {
                            setShowResetPassword(prev => !prev);
                            setResetPwdValue('');
                          }}
                          className={`inline-flex items-center gap-1 h-7 px-2 rounded-md border text-[11.5px] font-medium transition cursor-pointer ${
                            showResetPassword
                              ? 'border-sky-200 bg-sky-50 text-[#0086C4]'
                              : 'border-slate-200/85 bg-white text-slate-600 hover:bg-slate-50'
                          }`}
                        >
                          <KeyRound className="w-3 h-3" />
                          改密码
                        </button>
                      )}
                      {isSelectedEditable && (
                        <button
                          type="button"
                          disabled={busyKey === `sync:${selectedUser.id}`}
                          onClick={() => void handleSyncDefaultConfig(selectedUser)}
                          title="将管理员主空间的站点默认扣款配置同步给该成员"
                          className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-slate-200/85 bg-white hover:bg-slate-50 text-[11.5px] font-medium text-slate-600 transition cursor-pointer disabled:opacity-50"
                        >
                          <CopyCheck className="w-3 h-3" />
                          {busyKey === `sync:${selectedUser.id}` ? '同步中' : '同步扣款'}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* 内联重置密码折叠条 */}
                  {showResetPassword && canResetSelectedPwd && (
                    <form
                      onSubmit={e => void handleResetPasswordSubmit(e)}
                      className="px-4 py-2.5 bg-sky-50/45 border-b border-sky-100/80 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-[11.5px] font-semibold text-[#18191C]">
                          重置 {selectedUser.display_name} 的登录密码
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setShowResetPassword(false);
                            setResetPwdValue('');
                          }}
                          className="text-slate-400 hover:text-slate-600 cursor-pointer"
                          aria-label="取消重置密码"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="relative flex-1">
                          <input
                            type={resetPwdVisible ? 'text' : 'password'}
                            value={resetPwdValue}
                            onChange={e => setResetPwdValue(e.target.value)}
                            placeholder="输入新密码（至少 6 位）"
                            aria-label="新密码"
                            className={`${INPUT_BASE} pr-8`}
                          />
                          <button
                            type="button"
                            onClick={() => setResetPwdVisible(v => !v)}
                            aria-label={resetPwdVisible ? '隐藏密码' : '显示密码'}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                          >
                            {resetPwdVisible ? (
                              <EyeOff className="w-3.5 h-3.5" />
                            ) : (
                              <Eye className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                        <button
                          type="submit"
                          disabled={busyKey === `pwd:${selectedUser.id}` || resetPwdValue.trim().length < 6}
                          className="h-8 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-50 shrink-0"
                        >
                          {busyKey === `pwd:${selectedUser.id}` ? '保存中' : '确认'}
                        </button>
                      </div>
                    </form>
                  )}

                  {/* 纯权限开关快捷栏：全选 / 清空（已移除角色预设标签） */}
                  {isSelectedEditable ? (
                    <div className="px-4 py-2 bg-slate-50/60 border-b border-slate-100 flex items-center justify-between gap-2">
                      <span className="text-[11.5px] font-medium text-slate-500">
                        自由勾选该成员可访问的模块与共享通道
                      </span>
                      <div className="flex items-center gap-2 text-[11px] shrink-0">
                        <button
                          type="button"
                          onClick={() => batchSetUserPermissions(selectedUser.id, true)}
                          className="text-[#0086C4] hover:underline font-medium cursor-pointer"
                        >
                          全选
                        </button>
                        <span className="text-slate-300">/</span>
                        <button
                          type="button"
                          onClick={() => batchSetUserPermissions(selectedUser.id, false)}
                          className="text-slate-500 hover:text-slate-800 hover:underline font-medium cursor-pointer"
                        >
                          清空
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="px-4 py-2 bg-sky-50/40 border-b border-sky-100/70 flex items-center gap-2 text-[11.5px] text-[#007BB5]">
                      <Lock className="w-3.5 h-3.5 shrink-0" />
                      <span>
                        主机管理员默认拥有全部 {visiblePermissionKeys.length} 项模块与共享通道权限
                      </span>
                    </div>
                  )}

                  {/* 权限开关矩阵 */}
                  <div className="px-4 py-3 flex-1">
                    <PermissionMatrix
                      permissions={
                        isSelectedEditable
                          ? selectedDraft.permissions
                          : buildFullPermissions(true)
                      }
                      globalConfig={globalConfig}
                      disabled={!isSelectedEditable}
                      columns={1}
                      onChange={(key, nextVal) =>
                        updateUserDraftPermission(selectedUser.id, key, nextVal)
                      }
                    />
                  </div>

                  {/* 底部操作栏 */}
                  <div className="px-4 py-2.5 bg-white border-t border-slate-100 flex items-center justify-between gap-2">
                    <div className="text-[11.5px] text-slate-500 tabular-nums">
                      已开通{' '}
                      <strong className="font-semibold text-[#18191C]">
                        {isSelectedEditable
                          ? countEnabledPermissions(
                              selectedDraft.permissions,
                              visiblePermissionKeys,
                            )
                          : visiblePermissionKeys.length}
                      </strong>
                      /{visiblePermissionKeys.length} 项
                      {selectedDirty && (
                        <span className="ml-2 text-amber-600 font-medium">· 待保存</span>
                      )}
                    </div>

                    {isSelectedEditable ? (
                      <div className="flex items-center gap-1.5">
                        {selectedDirty && (
                          <button
                            type="button"
                            onClick={() => resetUserDraft(selectedUser)}
                            className="inline-flex items-center gap-1 h-7.5 px-2.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-[12px] font-medium text-slate-600 transition cursor-pointer"
                          >
                            <RotateCcw className="w-3 h-3" />
                            还原
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={!selectedDirty || busyKey === `save:${selectedUser.id}`}
                          onClick={() => void handleSavePermissions(selectedUser)}
                          className="inline-flex items-center gap-1 h-7.5 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed"
                        >
                          <Save className="w-3.5 h-3.5" />
                          {busyKey === `save:${selectedUser.id}` ? '保存中…' : '保存权限'}
                        </button>
                      </div>
                    ) : (
                      <span className="text-[11.5px] text-slate-400">全权限账号</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        ) : activeTab === 'allocations' ? (
          /* ===================== 视图二：通道与模块双泳道分配（类支付绑定） ===================== */
          <ChannelModuleAllocationPanel
            globalConfig={globalConfig}
            searchQuery={allocationQuery}
            saving={allocationSaving}
            onMovePlatform={(key, nextMode) => {
              void handleMovePlatform(key, nextMode);
            }}
            onMoveModule={(key, nextEnabled) => {
              void handleMoveModule(key, nextEnabled);
            }}
          />
        ) : (
          /* ===================== 视图三：紧凑安全审计日志表 ===================== */
          filteredAuditEvents.length === 0 ? (
            <div className="py-14 px-6 text-center space-y-2">
              <div className="w-9 h-9 rounded-lg bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
                <Clock className="w-4.5 h-4.5" />
              </div>
              <div className="text-[13px] font-medium text-[#18191C]">暂无匹配的审计记录</div>
              <p className="text-[12px] text-slate-400">
                账号登录、权限调整与密码重置等操作会自动记录在此。
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/55 text-[11px] font-semibold text-slate-500">
                    <th className="py-2 pl-4 pr-3 w-[165px]">时间</th>
                    <th className="py-2 px-3 w-[140px]">操作人</th>
                    <th className="py-2 px-3 w-[200px]">操作事件</th>
                    <th className="py-2 pl-3 pr-4">目标与结果</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100/90 text-[12.5px]">
                  {filteredAuditEvents.slice(0, 120).map(evt => {
                    const meta = formatAuditAction(evt.action);
                    const targetLabel = resolveAuditTargetLabel(evt.run_id, users);
                    const detailLabel = formatAuditDetail(evt.detail);
                    return (
                      <tr key={evt.id} className="hover:bg-slate-50/65 transition-colors">
                        <td className="py-2 pl-4 pr-3 font-mono text-[11.5px] text-slate-400 tabular-nums whitespace-nowrap">
                          {formatAuditTime(evt.time)}
                        </td>
                        <td className="py-2 px-3 font-medium text-[#18191C] whitespace-nowrap">
                          {evt.username || 'system'}
                        </td>
                        <td className="py-2 px-3 whitespace-nowrap">
                          <span className={`font-medium ${AUDIT_CATEGORY_TONE[meta.category]}`}>
                            {meta.label}
                          </span>
                        </td>
                        <td className="py-2 pl-3 pr-4 text-slate-600">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                            {targetLabel !== '—' && (
                              <span className="font-medium text-[#18191C]">{targetLabel}</span>
                            )}
                            {targetLabel !== '—' && detailLabel !== '—' && (
                              <span className="text-slate-300">·</span>
                            )}
                            <span className="text-slate-500">{detailLabel}</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>

      {/* ===================== 新建成员弹窗（仅设账号密码与权限开关） ===================== */}
      {createOpen &&
        createPortal(
          <div
            className="fixed inset-0 z-[1000] flex items-center justify-center bg-slate-900/40 backdrop-blur-[2px] p-4"
            role="dialog"
            aria-modal="true"
            aria-label="新建成员账号"
          >
            <div className="w-full max-w-[540px] max-h-[90vh] flex flex-col rounded-2xl bg-white border border-slate-200/90 shadow-xl overflow-hidden">
              <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between">
                <div>
                  <h3 className="text-[14.5px] font-semibold text-[#18191C]">新建成员账号</h3>
                  <p className="text-[11.5px] text-slate-400 mt-0.5">
                    设置登录账号与初始密码，并直接勾选开放的业务模块与共享通道权限
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="关闭新建成员弹窗"
                  onClick={() => setCreateOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <form
                onSubmit={e => void handleCreateSubmit(e)}
                className="flex flex-col min-h-0 flex-1"
              >
                <div className="px-5 py-4 space-y-3.5 overflow-y-auto">
                  {createError && (
                    <div className="px-3 py-2 rounded-lg bg-rose-50 border border-rose-200/80 text-[12px] text-rose-700">
                      {createError}
                    </div>
                  )}

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <label className="space-y-1 block">
                      <span className="text-[11.5px] font-medium text-slate-600">
                        登录账号 <span className="text-rose-500">*</span>
                      </span>
                      <input
                        type="text"
                        required
                        value={createUsername}
                        onChange={e => setCreateUsername(e.target.value)}
                        placeholder="如 zhangsan"
                        className={INPUT_BASE}
                      />
                    </label>
                    <label className="space-y-1 block">
                      <span className="text-[11.5px] font-medium text-slate-600">显示名称</span>
                      <input
                        type="text"
                        value={createDisplayName}
                        onChange={e => setCreateDisplayName(e.target.value)}
                        placeholder="如 张三（华南薪资）"
                        className={INPUT_BASE}
                      />
                    </label>
                    <label className="space-y-1 block">
                      <span className="text-[11.5px] font-medium text-slate-600">
                        初始密码 <span className="text-rose-500">*</span>
                      </span>
                      <div className="relative">
                        <input
                          type={createPasswordVisible ? 'text' : 'password'}
                          required
                          value={createPassword}
                          onChange={e => setCreatePassword(e.target.value)}
                          placeholder="至少 6 位字符"
                          className={`${INPUT_BASE} pr-8`}
                        />
                        <button
                          type="button"
                          aria-label={createPasswordVisible ? '隐藏密码' : '显示密码'}
                          onClick={() => setCreatePasswordVisible(v => !v)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                        >
                          {createPasswordVisible ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </label>
                    <label className="space-y-1 block">
                      <span className="text-[11.5px] font-medium text-slate-600">岗位备注（可选）</span>
                      <input
                        type="text"
                        value={createNote}
                        onChange={e => setCreateNote(e.target.value)}
                        placeholder="例如：负责华南区资料采集"
                        className={INPUT_BASE}
                      />
                    </label>
                  </div>

                  <div className="pt-2 border-t border-slate-100">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[12px] font-semibold text-[#18191C]">初始模块权限</span>
                      <div className="flex items-center gap-2 text-[11px]">
                        <button
                          type="button"
                          onClick={() => setCreatePermissions(buildFullPermissions(true))}
                          className="text-[#0086C4] hover:underline font-medium cursor-pointer"
                        >
                          全选
                        </button>
                        <span className="text-slate-300">/</span>
                        <button
                          type="button"
                          onClick={() => setCreatePermissions(buildFullPermissions(false))}
                          className="text-slate-500 hover:text-slate-800 hover:underline font-medium cursor-pointer"
                        >
                          清空
                        </button>
                      </div>
                    </div>
                    <PermissionMatrix
                      permissions={createPermissions}
                      globalConfig={globalConfig}
                      columns={2}
                      onChange={(key, nextVal) => {
                        setCreatePermissions(prev => ({ ...prev, [key]: nextVal }));
                      }}
                    />
                  </div>
                </div>

                <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    disabled={busyKey === 'create'}
                    onClick={() => setCreateOpen(false)}
                    className="h-8 px-3.5 rounded-lg border border-slate-200 bg-white text-[12px] font-medium text-slate-600 hover:bg-slate-50 cursor-pointer"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    disabled={busyKey === 'create'}
                    className="h-8 px-4 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-55"
                  >
                    {busyKey === 'create' ? '创建中…' : '创建并开通'}
                  </button>
                </div>
              </form>
            </div>
          </div>,
          document.body,
        )}

      {/* ===================== 恢复默认通道与模块分配确认弹窗 ===================== */}
      {confirmResetAllocations &&
        createPortal(
          <div
            className="fixed inset-0 z-[1000] flex items-center justify-center bg-slate-900/40 backdrop-blur-[2px] p-4"
            role="dialog"
            aria-modal="true"
            aria-label="确认恢复默认通道与模块分配"
            onClick={() => {
              if (!allocationSaving) setConfirmResetAllocations(false);
            }}
          >
            <div
              className="w-full max-w-[400px] rounded-2xl bg-white border border-slate-200/90 shadow-xl overflow-hidden"
              onClick={e => e.stopPropagation()}
            >
              <div className="px-5 pt-5 pb-4 flex items-start gap-3">
                <div className="w-9 h-9 rounded-xl bg-amber-50 border border-amber-200/80 text-amber-600 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-4.5 h-4.5" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-[14.5px] font-semibold text-[#18191C]">
                    恢复默认通道与模块分配？
                  </h3>
                  <p className="text-[12px] text-slate-500 leading-relaxed mt-1">
                    将把 6 个数据源恢复为默认通道归属（仅小象灯塔、本来人力为共享通道），并将全部 4 个业务模块恢复为全局开放状态，同时全局同步。不会影响「全局配置」中的自定义名称。
                  </p>
                </div>
              </div>
              <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50 flex items-center justify-end gap-2">
                <button
                  type="button"
                  disabled={allocationSaving}
                  onClick={() => setConfirmResetAllocations(false)}
                  className="h-8 px-3.5 rounded-lg border border-slate-200 bg-white text-[12px] font-medium text-slate-600 hover:bg-slate-50 cursor-pointer disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={allocationSaving}
                  onClick={() => void handleConfirmResetAllocations()}
                  className="h-8 px-4 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-55"
                >
                  {allocationSaving ? '恢复中…' : '确认恢复'}
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

interface NoModuleAccessNoticeProps {
  displayName: string;
  onOpenHistory: () => void;
  onOpenPickup: () => void;
}

export function NoModuleAccessNotice({
  displayName,
  onOpenHistory,
  onOpenPickup,
}: NoModuleAccessNoticeProps) {
  return (
    <div className="min-h-[420px] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md rounded-2xl bg-white border border-slate-200/85 px-8 py-9 text-center space-y-5">
        <div className="w-11 h-11 rounded-xl bg-sky-50 border border-[#00AEEC]/20 text-[#008EC4] flex items-center justify-center mx-auto">
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-sm font-bold text-[#18191C]">当前账号尚未开通此模块权限</h2>
          <p className="text-xs text-[#61666D] leading-relaxed">
            {displayName}，请联系管理员开启对应模块权限，或先前往任务下载与组内共享查看记录。
          </p>
        </div>
        <div className="flex items-center justify-center gap-2.5">
          <button
            type="button"
            onClick={onOpenHistory}
            className="h-9 px-4 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold transition cursor-pointer"
          >
            进入任务下载
          </button>
          <button
            type="button"
            onClick={onOpenPickup}
            className="h-9 px-4 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] transition cursor-pointer"
          >
            前往组内共享
          </button>
        </div>
      </div>
    </div>
  );
}
