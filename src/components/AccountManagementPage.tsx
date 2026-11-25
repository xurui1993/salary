import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft,
  Calculator,
  Check,
  ChevronRight,
  Clock,
  CopyCheck,
  Download,
  Eye,
  EyeOff,
  FileCheck2,
  FileSpreadsheet,
  KeyRound,
  Lock,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  Store,
  User,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import {
  adminApproveAccount,
  adminCreateAccount,
  adminRejectAccount,
  adminResetPassword,
  adminSyncDefaultConfig,
  adminUpdateAccount,
  fetchAdminAccounts,
  fetchAdminAuditLogs,
  type AuditEvent,
  type PermissionKey,
  type RoleTemplateDef,
  type WorkspaceDirectoryEntry,
  type WorkspaceUser,
} from '../lib/workspaceAuth';
import {
  ALL_PERMISSION_KEYS,
  PERMISSION_GROUPS,
  applyTemplateToDraft,
  buildFullPermissions,
  countEnabledPermissions,
  createDraftFromUser,
  filterAuditEvents,
  filterManagedUsers,
  formatAuditAction,
  formatAuditDetail,
  formatAuditTime,
  getEnabledPermissionLabels,
  getStatusLabel,
  getWorkspaceDisplayLabel,
  hasDraftChanges,
  type AuditCategory,
  type UserPermissionDraft,
} from '../lib/accountConsole';

export type AccountConsoleTab = 'members' | 'pending' | 'audit';

interface AccountManagementPageProps {
  currentUserId: string;
  requestedTab?: AccountConsoleTab | null;
  requestedTabVersion?: number;
  onAccountsChanged: (pendingCount: number, workspaces: WorkspaceDirectoryEntry[]) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

const INPUT_BASE =
  'w-full h-9 rounded-[11px] border border-slate-200/90 bg-white px-3 text-[13px] text-[#18191C] placeholder:text-[#9499A0] transition duration-150 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:ring-3 focus:ring-[#00AEEC]/15';

const PERMISSION_ICONS: Record<PermissionKey, React.ComponentType<{ className?: string }>> = {
  collection: Download,
  reports: FileSpreadsheet,
  payroll: Calculator,
  approval: FileCheck2,
  xiaoxiang_use: Store,
  benlai_use: ShoppingBag,
  shared_auth_manage: ShieldCheck,
};

interface PermissionConfigListProps {
  permissions: Record<PermissionKey, boolean>;
  disabled?: boolean;
  compact?: boolean;
  onChange: (key: PermissionKey, next: boolean) => void;
  onBatchChange?: (nextPermissions: Record<PermissionKey, boolean>) => void;
}

function PermissionConfigList({
  permissions,
  disabled,
  compact = false,
  onChange,
  onBatchChange,
}: PermissionConfigListProps) {
  const totalEnabled = countEnabledPermissions(permissions);
  const allEnabled = totalEnabled === ALL_PERMISSION_KEYS.length;

  return (
    <div className={compact ? 'space-y-3.5' : 'space-y-4'}>
      {/* 顶部权限进度汇总与快捷全选/清空 */}
      <div className="flex items-center justify-between gap-3 px-0.5">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1 shrink-0" aria-hidden="true">
            {ALL_PERMISSION_KEYS.map((permKey, idx) => {
              const active = idx < totalEnabled;
              return (
                <span
                  key={permKey}
                  className={`h-1.5 w-3 rounded-full transition-colors duration-150 ${
                    active
                      ? allEnabled
                        ? 'bg-emerald-500'
                        : 'bg-[#00AEEC]'
                      : 'bg-slate-200/90'
                  }`}
                />
              );
            })}
          </div>
          <span className="text-[12px] font-medium text-[#4E5969] tabular-nums">
            已开通{' '}
            <span className="font-semibold text-[#18191C]">{totalEnabled}</span>
            <span className="text-[#9499A0]"> / {ALL_PERMISSION_KEYS.length}</span>
          </span>
        </div>

        {!disabled && onBatchChange && (
          <div className="flex items-center gap-2.5 text-[12px]">
            <button
              type="button"
              disabled={allEnabled}
              onClick={() => onBatchChange(buildFullPermissions(true))}
              className="font-medium text-[#008EC4] hover:text-[#006F9B] disabled:text-[#C9CDD4] disabled:cursor-not-allowed transition cursor-pointer"
            >
              全选
            </button>
            <span className="text-slate-200 select-none" aria-hidden="true">
              |
            </span>
            <button
              type="button"
              disabled={totalEnabled === 0}
              onClick={() => onBatchChange(buildFullPermissions(false))}
              className="font-medium text-[#61666D] hover:text-[#18191C] disabled:text-[#C9CDD4] disabled:cursor-not-allowed transition cursor-pointer"
            >
              清空
            </button>
          </div>
        )}
      </div>

      {/* 分组列表（细线分隔、图标柔和着墨、悬停展示说明） */}
      {PERMISSION_GROUPS.map(group => {
        const enabledInGroup = countEnabledPermissions(
          permissions,
          group.items.map(i => i.key),
        );
        return (
          <div key={group.id} className="space-y-1.5">
            <div className="flex items-center justify-between px-1" title={group.subtitle}>
              <span className="text-[12px] font-semibold text-[#4E5969] tracking-wide">
                {group.title}
              </span>
              <span className="text-[11.5px] text-[#9499A0] tabular-nums">
                {enabledInGroup} / {group.items.length}
              </span>
            </div>

            <div className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden divide-y divide-slate-100/90 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
              {group.items.map(item => {
                const checked = Boolean(permissions[item.key]);
                const Icon = PERMISSION_ICONS[item.key];
                return (
                  <button
                    key={item.key}
                    type="button"
                    role="switch"
                    aria-checked={checked}
                    disabled={disabled}
                    title={item.description}
                    onClick={() => onChange(item.key, !checked)}
                    className={`w-full px-4 ${compact ? 'py-2.5' : 'py-3'} flex items-center justify-between gap-3.5 text-left transition-colors duration-150 ${
                      disabled
                        ? 'opacity-70 cursor-not-allowed'
                        : 'hover:bg-[#F7FAFC] cursor-pointer'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`w-7.5 h-7.5 rounded-[9px] flex items-center justify-center shrink-0 transition-colors duration-150 ${
                          checked
                            ? 'bg-sky-50 text-[#008EC4]'
                            : 'bg-slate-100/85 text-[#9499A0]'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                      </span>
                      <span
                        className={`text-[13px] font-medium truncate transition-colors ${
                          checked ? 'text-[#18191C]' : 'text-[#61666D]'
                        }`}
                      >
                        {item.label}
                      </span>
                    </div>

                    <span
                      aria-hidden="true"
                      className={`relative inline-flex h-[20px] w-[36px] shrink-0 items-center rounded-full transition-colors duration-150 ${
                        checked ? 'bg-[#00AEEC]' : 'bg-slate-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-[16px] w-[16px] rounded-full bg-white shadow-xs transition-transform duration-150 ${
                          checked ? 'translate-x-[18px]' : 'translate-x-[2px]'
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
  const [activeTab, setActiveTab] = useState<AccountConsoleTab>('members');
  const tabInitializedRef = useRef(false);
  const requestedTabRef = useRef(requestedTab);
  const onAccountsChangedRef = useRef(onAccountsChanged);
  const onToastRef = useRef(onToast);

  requestedTabRef.current = requestedTab;
  onAccountsChangedRef.current = onAccountsChanged;
  onToastRef.current = onToast;

  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState('');
  const [users, setUsers] = useState<WorkspaceUser[]>([]);
  const [templates, setTemplates] = useState<Record<string, RoleTemplateDef>>({});
  const [drafts, setDrafts] = useState<Record<string, UserPermissionDraft>>({});

  // Slide-over drawer state: permissions view vs seamless inline password view
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [drawerMode, setDrawerMode] = useState<'permissions' | 'password'>('permissions');
  const [syncConfirming, setSyncConfirming] = useState(false);

  // Drawer inline password form state
  const [resetPasswordVal, setResetPasswordVal] = useState('');
  const [resetConfirmVal, setResetConfirmVal] = useState('');
  const [resetShowPw, setResetShowPw] = useState(false);

  // Member search & filters
  const [memberQuery, setMemberQuery] = useState('');
  const [memberStatusFilter, setMemberStatusFilter] = useState<
    'all' | 'active' | 'disabled' | 'rejected'
  >('all');

  // Audit logs state
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditLoaded, setAuditLoaded] = useState(false);
  const [auditQuery, setAuditQuery] = useState('');
  const [auditCategory, setAuditCategory] = useState<AuditCategory>('all');

  // Create member modal state
  const [createOpen, setCreateOpen] = useState(false);
  const [createUsername, setCreateUsername] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createShowPw, setCreateShowPw] = useState(false);
  const [createDraft, setCreateDraft] = useState<UserPermissionDraft>({
    role_template: 'custom',
    permissions: {
      collection: true,
      reports: true,
      payroll: true,
      approval: false,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: false,
    },
  });

  // Legacy pending reject confirm
  const [rejectConfirmUser, setRejectConfirmUser] = useState<WorkspaceUser | null>(null);

  const openMemberDrawer = (userId: string) => {
    setSelectedUserId(userId);
    setDrawerMode('permissions');
    setSyncConfirming(false);
    setResetPasswordVal('');
    setResetConfirmVal('');
    setResetShowPw(false);
  };

  const closeMemberDrawer = () => {
    setSelectedUserId(null);
    setDrawerMode('permissions');
    setSyncConfirming(false);
    setResetPasswordVal('');
    setResetConfirmVal('');
  };

  const openDrawerPasswordMode = () => {
    setSyncConfirming(false);
    setResetPasswordVal('');
    setResetConfirmVal('');
    setResetShowPw(false);
    setDrawerMode('password');
  };

  const syncDraftsFromUsers = useCallback(
    (nextUsers: WorkspaceUser[], nextTemplates: Record<string, RoleTemplateDef>) => {
      const nextDrafts: Record<string, UserPermissionDraft> = {};
      for (const u of nextUsers) {
        if (u.status === 'pending') {
          nextDrafts[u.id] = applyTemplateToDraft('payroll_specialist', nextTemplates);
        } else {
          nextDrafts[u.id] = createDraftFromUser(u);
        }
      }
      setDrafts(nextDrafts);
    },
    [],
  );

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchAdminAccounts();
      setUsers(data.users);
      setTemplates(data.role_templates);
      syncDraftsFromUsers(data.users, data.role_templates);
      onAccountsChangedRef.current(data.pending_count, data.workspaces);

      if (!tabInitializedRef.current) {
        const req = requestedTabRef.current;
        setActiveTab(req || (data.pending_count > 0 ? 'pending' : 'members'));
        tabInitializedRef.current = true;
      }

      setSelectedUserId(prev =>
        prev && data.users.some(u => u.id === prev) ? prev : null,
      );
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '加载成员列表失败', 'error');
    } finally {
      setLoading(false);
    }
  }, [syncDraftsFromUsers]);

  const loadAuditLogs = useCallback(async () => {
    setAuditLoading(true);
    try {
      const res = await fetchAdminAuditLogs();
      setAuditEvents(res.events || []);
      setAuditLoaded(true);
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '加载审计日志失败', 'error');
    } finally {
      setAuditLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
    void loadAuditLogs();
  }, [loadAccounts, loadAuditLogs]);

  useEffect(() => {
    if (requestedTab && requestedTabVersion > 0) {
      setActiveTab(requestedTab);
    }
  }, [requestedTab, requestedTabVersion]);

  useEffect(() => {
    if (activeTab === 'audit' && !auditLoaded) {
      void loadAuditLogs();
    }
  }, [activeTab, auditLoaded, loadAuditLogs]);

  // Escape dismisses topmost overlay cleanly
  useEffect(() => {
    const hasOverlay = Boolean(createOpen || rejectConfirmUser || selectedUserId);
    if (!hasOverlay) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || busyKey) return;
      if (rejectConfirmUser) setRejectConfirmUser(null);
      else if (createOpen) setCreateOpen(false);
      else if (selectedUserId && drawerMode === 'password') setDrawerMode('permissions');
      else if (selectedUserId) closeMemberDrawer();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [createOpen, rejectConfirmUser, selectedUserId, drawerMode, busyKey]);

  const pendingUsers = useMemo(() => users.filter(u => u.status === 'pending'), [users]);
  const formalMemberCount = useMemo(
    () => users.filter(u => u.status !== 'pending').length,
    [users],
  );
  const activeCount = useMemo(() => users.filter(u => u.status === 'active').length, [users]);

  const filteredMembers = useMemo(
    () =>
      filterManagedUsers(users, {
        query: memberQuery,
        status: memberStatusFilter,
        role: 'all',
      }),
    [users, memberQuery, memberStatusFilter],
  );

  const filteredAudits = useMemo(
    () => filterAuditEvents(auditEvents, { query: auditQuery, category: auditCategory }),
    [auditEvents, auditQuery, auditCategory],
  );

  const selectedUser = useMemo(
    () => (selectedUserId ? users.find(u => u.id === selectedUserId) || null : null),
    [users, selectedUserId],
  );

  const updateUserDraftPermission = (userId: string, key: PermissionKey, next: boolean) => {
    setDrafts(prev => {
      const current = prev[userId];
      if (!current) return prev;
      return {
        ...prev,
        [userId]: {
          role_template: 'custom',
          permissions: { ...current.permissions, [key]: next },
        },
      };
    });
  };

  const replaceUserDraftPermissions = (
    userId: string,
    nextPermissions: Record<PermissionKey, boolean>,
  ) => {
    setDrafts(prev => ({
      ...prev,
      [userId]: {
        role_template: 'custom',
        permissions: nextPermissions,
      },
    }));
  };

  const resetUserDraft = (user: WorkspaceUser) => {
    setDrafts(prev => ({
      ...prev,
      [user.id]:
        user.status === 'pending'
          ? applyTemplateToDraft('payroll_specialist', templates)
          : createDraftFromUser(user),
    }));
  };

  const handleSavePermissions = async (user: WorkspaceUser) => {
    const draft = drafts[user.id];
    if (!draft) return;
    setBusyKey(`save:${user.id}`);
    try {
      const res = await adminUpdateAccount(user.id, {
        role_template: draft.role_template,
        permissions: draft.permissions,
      });
      setUsers(res.users);
      syncDraftsFromUsers(res.users, templates);
      onAccountsChangedRef.current(res.pending_count, res.workspaces);
      setAuditLoaded(false);
      onToastRef.current(`已保存「${user.display_name}」的权限配置`, 'success');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '保存权限失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleApprove = async (user: WorkspaceUser) => {
    const draft = drafts[user.id] || applyTemplateToDraft('payroll_specialist', templates);
    setBusyKey(`approve:${user.id}`);
    try {
      const res = await adminApproveAccount(user.id, {
        role_template: draft.role_template,
        permissions: draft.permissions,
      });
      setUsers(res.users);
      syncDraftsFromUsers(res.users, templates);
      onAccountsChangedRef.current(res.pending_count, res.workspaces);
      setAuditLoaded(false);
      closeMemberDrawer();
      onToastRef.current(`已批准「${user.display_name}」并开通独立空间`, 'success');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '审批失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleConfirmReject = async () => {
    if (!rejectConfirmUser) return;
    const target = rejectConfirmUser;
    setBusyKey(`reject:${target.id}`);
    try {
      const res = await adminRejectAccount(target.id);
      setUsers(res.users);
      syncDraftsFromUsers(res.users, templates);
      onAccountsChangedRef.current(
        res.pending_count,
        res.users
          .filter(u => u.status === 'active')
          .map(u => ({
            workspace_id: u.workspace_id,
            user_id: u.id,
            username: u.username,
            display_name: u.display_name,
            role: u.role,
            status: u.status,
            is_primary: u.workspace_id === 'download_shared',
          })),
      );
      setAuditLoaded(false);
      setRejectConfirmUser(null);
      closeMemberDrawer();
      onToastRef.current(`已驳回「${target.display_name}」的注册申请`, 'info');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '驳回失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleToggleEnabled = async (user: WorkspaceUser) => {
    setBusyKey(`toggle:${user.id}`);
    try {
      const nextEnabled = !user.enabled;
      const res = await adminUpdateAccount(user.id, { enabled: nextEnabled });
      setUsers(res.users);
      syncDraftsFromUsers(res.users, templates);
      onAccountsChangedRef.current(res.pending_count, res.workspaces);
      setAuditLoaded(false);
      onToastRef.current(
        nextEnabled ? `已恢复启用「${user.display_name}」` : `已停用「${user.display_name}」`,
        'info',
      );
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '状态切换失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleSyncDefaultConfig = async (user: WorkspaceUser) => {
    setBusyKey(`sync:${user.id}`);
    try {
      const res = await adminSyncDefaultConfig(user.id);
      setSyncConfirming(false);
      setAuditLoaded(false);
      onToastRef.current(res.message || `已同步默认扣款配置至「${user.display_name}」`, 'success');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '同步默认扣款配置失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanUsername = createUsername.trim();
    if (!cleanUsername) return;
    setBusyKey('create');
    try {
      const res = await adminCreateAccount({
        username: cleanUsername,
        display_name: cleanUsername,
        password: createPassword,
        role_template: 'custom',
        permissions: createDraft.permissions,
        note: '',
      });
      setUsers(res.users);
      syncDraftsFromUsers(res.users, templates);
      onAccountsChangedRef.current(
        res.users.filter(u => u.status === 'pending').length,
        res.workspaces,
      );
      setAuditLoaded(false);
      setCreateUsername('');
      setCreatePassword('');
      setCreateOpen(false);
      setActiveTab('members');
      onToastRef.current(`已创建成员「${res.user.display_name}」`, 'success');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '创建成员失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    if (resetPasswordVal !== resetConfirmVal) {
      onToastRef.current('两次输入的新密码不一致', 'error');
      return;
    }
    setBusyKey(`reset:${selectedUser.id}`);
    try {
      await adminResetPassword(selectedUser.id, resetPasswordVal);
      setAuditLoaded(false);
      onToastRef.current(`已修改「${selectedUser.display_name}」的登录密码`, 'success');
      setResetPasswordVal('');
      setResetConfirmVal('');
      setDrawerMode('permissions');
    } catch (err) {
      onToastRef.current(err instanceof Error ? err.message : '修改密码失败', 'error');
    } finally {
      setBusyKey('');
    }
  };

  const selectedDraft = selectedUser
    ? drafts[selectedUser.id] ||
      (selectedUser.status === 'pending'
        ? applyTemplateToDraft('payroll_specialist', templates)
        : createDraftFromUser(selectedUser))
    : null;
  const selectedIsDirty =
    selectedUser && selectedUser.status !== 'pending' && selectedUser.role !== 'admin'
      ? hasDraftChanges(selectedUser, selectedDraft || undefined)
      : false;

  const resetPwLenOk = resetPasswordVal.length >= 6;
  const resetPwMatchOk = Boolean(
    resetPasswordVal && resetConfirmVal && resetPasswordVal === resetConfirmVal,
  );
  const resetPwMismatch = Boolean(resetConfirmVal && resetPasswordVal !== resetConfirmVal);

  const auditCategoryOptions = useMemo<[AuditCategory, string][]>(
    () => [
      ['all', '全部'],
      ['auth', '登录'],
      ['approval', '审批'],
      ['permission', '权限'],
      ['workspace', '空间'],
      ['security', '密码'],
    ],
    [],
  );

  return (
    <div className="max-w-[1160px] mx-auto space-y-5 pb-6">
      {/* 精致页头区 */}
      <div className="flex flex-wrap items-end justify-between gap-4 pt-1">
        <div>
          <h2 className="text-[20px] font-bold text-[#18191C] tracking-tight leading-tight">
            团队成员与权限
          </h2>
          <p className="text-[13px] text-[#61666D] mt-1">
            集中管理团队账号、模块访问权限与安全审计轨迹
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <button
            type="button"
            disabled={loading || auditLoading}
            onClick={() => {
              void loadAccounts();
              void loadAuditLogs();
            }}
            className="h-9 inline-flex items-center gap-1.5 rounded-[11px] border border-slate-200/90 bg-white hover:bg-slate-50 px-3.5 text-[12.5px] font-medium text-[#4E5969] shadow-[var(--wbx-shadow-xs)] transition cursor-pointer whitespace-nowrap disabled:opacity-55"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${loading || auditLoading ? 'animate-spin' : ''}`}
            />
            <span>刷新</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setCreateUsername('');
              setCreatePassword('');
              setCreateShowPw(false);
              setCreateDraft({
                role_template: 'custom',
                permissions: applyTemplateToDraft('payroll_specialist', templates).permissions,
              });
              setCreateOpen(true);
            }}
            className="h-9 inline-flex items-center gap-1.5 rounded-[11px] bg-[#00AEEC] hover:bg-[#009CD6] text-white px-4 text-[12.5px] font-semibold shadow-[0_8px_20px_-10px_rgba(0,174,236,0.85)] transition cursor-pointer whitespace-nowrap"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>新建成员</span>
          </button>
        </div>
      </div>

      {/* 单层横向概览条 */}
      <div className="rounded-2xl bg-white border border-slate-200/80 shadow-[var(--wbx-shadow-xs)] grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-slate-100 overflow-hidden">
        <button
          type="button"
          onClick={() => {
            setActiveTab('members');
            setMemberStatusFilter('all');
          }}
          className={`px-5 py-4 text-left transition-colors cursor-pointer ${
            activeTab === 'members' && memberStatusFilter === 'all'
              ? 'bg-sky-50/35'
              : 'hover:bg-slate-50/75'
          }`}
        >
          <div className="text-[12px] font-medium text-[#61666D]">全部成员</div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-[22px] font-semibold tracking-tight text-[#18191C] tabular-nums leading-none">
              {loading ? '—' : formalMemberCount}
            </span>
            <span className="text-[11.5px] text-[#9499A0]">已开通账号</span>
          </div>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('members');
            setMemberStatusFilter('active');
          }}
          className={`px-5 py-4 text-left transition-colors cursor-pointer ${
            activeTab === 'members' && memberStatusFilter === 'active'
              ? 'bg-sky-50/35'
              : 'hover:bg-slate-50/75'
          }`}
        >
          <div className="text-[12px] font-medium text-[#61666D]">正常启用</div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-[22px] font-semibold tracking-tight text-emerald-600 tabular-nums leading-none">
              {loading ? '—' : activeCount}
            </span>
            <span className="text-[11.5px] text-[#9499A0]">可登录使用</span>
          </div>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('pending')}
          className={`px-5 py-4 text-left transition-colors cursor-pointer ${
            activeTab === 'pending' ? 'bg-amber-50/45' : 'hover:bg-slate-50/75'
          }`}
        >
          <div className="text-[12px] font-medium text-[#61666D]">待审批</div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span
              className={`text-[22px] font-semibold tracking-tight tabular-nums leading-none ${
                pendingUsers.length > 0 ? 'text-amber-600' : 'text-[#18191C]'
              }`}
            >
              {loading ? '—' : pendingUsers.length}
            </span>
            <span className="text-[11.5px] text-[#9499A0]">
              {pendingUsers.length > 0 ? '待审核开通' : '暂无待审'}
            </span>
          </div>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('audit')}
          className={`px-5 py-4 text-left transition-colors cursor-pointer ${
            activeTab === 'audit' ? 'bg-sky-50/35' : 'hover:bg-slate-50/75'
          }`}
        >
          <div className="text-[12px] font-medium text-[#61666D]">安全审计</div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-[22px] font-semibold tracking-tight text-[#18191C] tabular-nums leading-none">
              {auditLoaded ? auditEvents.length : '—'}
            </span>
            <span className="text-[11.5px] text-[#9499A0]">操作轨迹</span>
          </div>
        </button>
      </div>

      {/* 主数据面板 */}
      <div className="rounded-2xl bg-white border border-slate-200/80 shadow-[var(--wbx-shadow-sm)] overflow-hidden">
        {/* 顶部页签栏 */}
        <div
          className="px-6 border-b border-slate-100 flex items-center justify-between gap-4 overflow-x-auto"
          role="tablist"
          aria-label="账户与权限视图切换"
        >
          <div className="flex items-center gap-7">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'members'}
              onClick={() => setActiveTab('members')}
              className={`relative py-3.5 text-[13.5px] font-semibold whitespace-nowrap transition cursor-pointer flex items-center gap-2 ${
                activeTab === 'members'
                  ? 'text-[#008EC4]'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              <span>成员与权限</span>
              <span className="text-[12px] font-normal text-[#9499A0] tabular-nums">
                {formalMemberCount}
              </span>
              {activeTab === 'members' && (
                <span className="absolute left-0 right-0 bottom-0 h-[2px] rounded-full bg-[#00AEEC]" />
              )}
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'pending'}
              onClick={() => setActiveTab('pending')}
              className={`relative py-3.5 text-[13.5px] font-semibold whitespace-nowrap transition cursor-pointer flex items-center gap-2 ${
                activeTab === 'pending'
                  ? 'text-[#008EC4]'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              <span>待审批</span>
              <span
                className={`text-[12px] tabular-nums ${
                  pendingUsers.length > 0
                    ? 'font-semibold text-amber-600'
                    : 'font-normal text-[#9499A0]'
                }`}
              >
                {pendingUsers.length}
              </span>
              {activeTab === 'pending' && (
                <span className="absolute left-0 right-0 bottom-0 h-[2px] rounded-full bg-[#00AEEC]" />
              )}
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'audit'}
              onClick={() => setActiveTab('audit')}
              className={`relative py-3.5 text-[13.5px] font-semibold whitespace-nowrap transition cursor-pointer flex items-center gap-2 ${
                activeTab === 'audit'
                  ? 'text-[#008EC4]'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              <span>审计日志</span>
              {auditLoaded && (
                <span className="text-[12px] font-normal text-[#9499A0] tabular-nums">
                  {auditEvents.length}
                </span>
              )}
              {activeTab === 'audit' && (
                <span className="absolute left-0 right-0 bottom-0 h-[2px] rounded-full bg-[#00AEEC]" />
              )}
            </button>
          </div>

          <span className="hidden md:inline text-[12px] text-[#9499A0] whitespace-nowrap tabular-nums">
            {activeTab === 'members'
              ? `显示 ${filteredMembers.length} / ${formalMemberCount} 位成员`
              : activeTab === 'pending'
                ? `${pendingUsers.length} 条待审批申请`
                : `共 ${filteredAudits.length} 条记录`}
          </span>
        </div>

        {/* 1. 成员与权限表格 */}
        {activeTab === 'members' && (
          <div>
            <div className="px-6 py-3.5 bg-[#FAFBFD] border-b border-slate-100 flex flex-wrap items-center justify-between gap-3">
              <div className="relative flex-1 min-w-[220px] max-w-[300px]">
                <Search className="w-3.5 h-3.5 text-[#9499A0] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  data-custom-focus="true"
                  value={memberQuery}
                  onChange={e => setMemberQuery(e.target.value)}
                  placeholder="搜索用户姓名或账号…"
                  className={`${INPUT_BASE} pl-8.5 ${memberQuery ? 'pr-8' : ''}`}
                />
                {memberQuery && (
                  <button
                    type="button"
                    onClick={() => setMemberQuery('')}
                    aria-label="清空搜索"
                    className="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-md inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>

              <div className="inline-flex items-center p-1 rounded-[11px] bg-slate-100/85 border border-slate-200/50">
                {(
                  [
                    ['all', '全部'],
                    ['active', '启用'],
                    ['disabled', '停用'],
                  ] as const
                ).map(([val, label]) => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setMemberStatusFilter(val)}
                    className={`h-7 px-3 rounded-[8px] text-[12px] font-medium transition cursor-pointer whitespace-nowrap ${
                      memberStatusFilter === val
                        ? 'bg-white text-[#18191C] shadow-[0_1px_3px_rgba(15,23,42,0.08)]'
                        : 'text-[#61666D] hover:text-[#18191C]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {loading ? (
              <div className="px-6 py-5 space-y-3">
                {[0, 1, 2, 3].map(idx => (
                  <div key={idx} className="h-14 rounded-xl bg-slate-50 animate-pulse" />
                ))}
              </div>
            ) : filteredMembers.length === 0 ? (
              <div className="py-16 text-center space-y-2.5">
                <div className="w-11 h-11 rounded-2xl bg-slate-50 border border-slate-100 text-slate-300 flex items-center justify-center mx-auto">
                  <Users className="w-5 h-5" />
                </div>
                <p className="text-[13px] font-medium text-[#4E5969]">未找到匹配的成员账号</p>
                {(memberQuery || memberStatusFilter !== 'all') && (
                  <button
                    type="button"
                    onClick={() => {
                      setMemberQuery('');
                      setMemberStatusFilter('all');
                    }}
                    className="text-[12px] font-medium text-[#008EC4] hover:text-[#006F9B] cursor-pointer"
                  >
                    重置筛选条件
                  </button>
                )}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[740px] table-fixed text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-100 text-[12px] font-medium text-[#61666D] bg-[#FAFBFD]/60">
                      <th className="py-3 pl-6 pr-4 w-[24%]">成员</th>
                      <th className="py-3 px-4 w-[46%]">模块权限</th>
                      <th className="py-3 px-4 w-[16%]">状态</th>
                      <th className="py-3 pl-4 pr-6 text-right w-[14%]">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100/90">
                    {filteredMembers.map(user => {
                      const draft = drafts[user.id] || createDraftFromUser(user);
                      const isDirty = user.role !== 'admin' && hasDraftChanges(user, draft);
                      const enabledCount =
                        user.role === 'admin'
                          ? ALL_PERMISSION_KEYS.length
                          : countEnabledPermissions(draft.permissions);
                      const enabledLabels = getEnabledPermissionLabels(
                        draft.permissions,
                        user.role === 'admin',
                      );
                      const isSelected = selectedUserId === user.id;
                      const isToggleLocked = user.id === currentUserId || user.role === 'admin';
                      const isToggling = busyKey === `toggle:${user.id}`;

                      return (
                        <tr
                          key={user.id}
                          onClick={() => openMemberDrawer(user.id)}
                          className={`group transition-colors duration-150 cursor-pointer ${
                            isSelected ? 'bg-sky-50/55' : 'hover:bg-[#F7FAFC]'
                          }`}
                        >
                          <td className="py-4 pl-6 pr-4" title={`账号：${user.username}`}>
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span className="text-[14px] font-semibold text-[#18191C] truncate">
                                {user.display_name}
                              </span>
                              {user.id === currentUserId && (
                                <span className="text-[11.5px] font-medium text-[#008EC4] shrink-0">
                                  · 我
                                </span>
                              )}
                            </div>
                          </td>

                          <td className="py-4 px-4">
                            <div className="space-y-1.5 min-w-0">
                              <div className="flex items-center gap-2.5">
                                <div
                                  className="flex items-center gap-1 shrink-0"
                                  aria-hidden="true"
                                >
                                  {ALL_PERMISSION_KEYS.map((permKey, idx) => {
                                    const active = idx < enabledCount;
                                    return (
                                      <span
                                        key={permKey}
                                        className={`h-1.5 w-3 rounded-full transition-colors duration-150 ${
                                          active
                                            ? enabledCount === ALL_PERMISSION_KEYS.length
                                              ? 'bg-emerald-500'
                                              : 'bg-[#00AEEC]'
                                            : 'bg-slate-200/80'
                                        }`}
                                      />
                                    );
                                  })}
                                </div>
                                <span className="text-[12px] font-semibold tabular-nums text-[#18191C] shrink-0">
                                  {enabledCount}
                                  <span className="font-normal text-[#9499A0]">
                                    {' '}
                                    / {ALL_PERMISSION_KEYS.length}
                                  </span>
                                </span>
                                {isDirty && (
                                  <span className="text-[11.5px] font-medium text-[#008EC4] shrink-0">
                                    · 未保存
                                  </span>
                                )}
                              </div>
                              <div
                                className={`text-[12px] truncate ${
                                  enabledLabels.length > 0 ? 'text-[#61666D]' : 'text-[#9499A0]'
                                }`}
                                title={
                                  enabledLabels.length > 0
                                    ? enabledLabels.join(' · ')
                                    : '暂未开通任何模块权限'
                                }
                              >
                                {user.role === 'admin'
                                  ? '全部业务与共享通道权限'
                                  : enabledLabels.length > 0
                                    ? enabledLabels.join(' · ')
                                    : '暂未开通模块权限'}
                              </div>
                            </div>
                          </td>

                          <td
                            className="py-4 px-4 whitespace-nowrap"
                            onClick={e => e.stopPropagation()}
                          >
                            {user.status === 'rejected' ? (
                              <span className="text-[12.5px] font-medium text-rose-600">
                                已驳回
                              </span>
                            ) : (
                              <button
                                type="button"
                                role="switch"
                                aria-checked={user.enabled}
                                aria-label={`${user.enabled ? '停用' : '启用'} ${user.display_name}`}
                                disabled={isToggleLocked || Boolean(busyKey)}
                                title={
                                  isToggleLocked
                                    ? '系统管理员账号不可停用'
                                    : user.enabled
                                      ? '点击停用该账号'
                                      : '点击恢复启用该账号'
                                }
                                onClick={e => {
                                  e.stopPropagation();
                                  void handleToggleEnabled(user);
                                }}
                                className={`inline-flex items-center gap-2 rounded-lg py-1 transition ${
                                  isToggleLocked
                                    ? 'opacity-65 cursor-not-allowed'
                                    : 'cursor-pointer'
                                }`}
                              >
                                <span
                                  aria-hidden="true"
                                  className={`relative inline-flex h-[20px] w-[36px] shrink-0 items-center rounded-full transition-colors duration-150 ${
                                    user.enabled ? 'bg-emerald-500' : 'bg-slate-200'
                                  }`}
                                >
                                  <span
                                    className={`inline-block h-[16px] w-[16px] rounded-full bg-white shadow-xs transition-transform duration-150 ${
                                      user.enabled ? 'translate-x-[18px]' : 'translate-x-[2px]'
                                    }`}
                                  />
                                </span>
                                <span
                                  className={`text-[12.5px] font-medium ${
                                    user.enabled ? 'text-emerald-700' : 'text-[#61666D]'
                                  }`}
                                >
                                  {isToggling ? '切换中…' : user.enabled ? '启用' : '停用'}
                                </span>
                              </button>
                            )}
                          </td>

                          <td className="py-4 pl-4 pr-6 text-right whitespace-nowrap">
                            <button
                              type="button"
                              onClick={e => {
                                e.stopPropagation();
                                openMemberDrawer(user.id);
                              }}
                              aria-label={`配置 ${user.display_name}`}
                              className={`h-8 px-3 rounded-[10px] border text-[12px] font-medium inline-flex items-center gap-1 transition cursor-pointer ${
                                isSelected
                                  ? 'border-[#00AEEC]/40 bg-sky-50 text-[#008EC4]'
                                  : 'border-slate-200/90 bg-white text-[#4E5969] group-hover:border-[#00AEEC]/40 group-hover:text-[#008EC4] group-hover:bg-sky-50/50'
                              }`}
                            >
                              <span>配置</span>
                              <ChevronRight className="w-3.5 h-3.5 transition-transform duration-150 group-hover:translate-x-0.5" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* 2. 待审批注册申请队列 */}
        {activeTab === 'pending' && (
          <div>
            {loading ? (
              <div className="px-6 py-5 space-y-3">
                {[0, 1, 2].map(idx => (
                  <div key={idx} className="h-14 rounded-xl bg-slate-50 animate-pulse" />
                ))}
              </div>
            ) : pendingUsers.length === 0 ? (
              <div className="py-16 px-6 text-center space-y-2.5">
                <div className="w-11 h-11 rounded-2xl bg-slate-50 border border-slate-100 text-slate-300 flex items-center justify-center mx-auto">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <p className="text-[13.5px] font-medium text-[#4E5969]">暂无待审批的注册申请</p>
                <p className="text-[12px] text-[#9499A0] max-w-md mx-auto">
                  通过后台公开注册接口提交的新成员申请将自动汇入此列表，等待管理员分配权限后开通
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] table-fixed text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-100 text-[12px] font-medium text-[#61666D] bg-[#FAFBFD]/60">
                      <th className="py-3 pl-6 pr-4 w-[32%]">申请人</th>
                      <th className="py-3 px-4 w-[28%]">申请说明</th>
                      <th className="py-3 px-4 w-[18%]">提交时间</th>
                      <th className="py-3 pl-4 pr-6 text-right w-[22%]">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100/90 text-[13px]">
                    {pendingUsers.map(user => {
                      const isSelected = selectedUserId === user.id;
                      const showDistinctAccount =
                        user.username && user.username !== user.display_name;
                      return (
                        <tr
                          key={user.id}
                          onClick={() => openMemberDrawer(user.id)}
                          className={`group transition-colors duration-150 cursor-pointer ${
                            isSelected ? 'bg-amber-50/55' : 'hover:bg-[#F7FAFC]'
                          }`}
                        >
                          <td className="py-4 pl-6 pr-4" title={`账号：${user.username}`}>
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-[14px] font-semibold text-[#18191C] truncate">
                                {user.display_name}
                              </span>
                              {showDistinctAccount && (
                                <span className="text-[12px] text-[#9499A0] truncate">
                                  · {user.username}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="py-4 px-4 text-[12.5px] text-[#61666D] truncate">
                            {user.note || '—'}
                          </td>
                          <td className="py-4 px-4 text-[#61666D] font-mono text-[12px] tabular-nums whitespace-nowrap">
                            {formatAuditTime(user.created_at)}
                          </td>
                          <td
                            className="py-4 pl-4 pr-6 text-right whitespace-nowrap"
                            onClick={e => e.stopPropagation()}
                          >
                            <div className="inline-flex items-center justify-end gap-2">
                              <button
                                type="button"
                                disabled={Boolean(busyKey)}
                                onClick={() => setRejectConfirmUser(user)}
                                className="h-8 px-3 rounded-[10px] border border-slate-200/90 bg-white hover:border-rose-200 hover:bg-rose-50/70 hover:text-rose-600 text-[12px] font-medium text-[#61666D] transition cursor-pointer disabled:opacity-50"
                              >
                                驳回
                              </button>
                              <button
                                type="button"
                                disabled={Boolean(busyKey)}
                                onClick={() => openMemberDrawer(user.id)}
                                aria-label={`审核 ${user.display_name}`}
                                className="h-8 px-3 rounded-[10px] border border-[#00AEEC]/35 bg-sky-50/70 hover:bg-sky-50 text-[12px] font-medium text-[#008EC4] inline-flex items-center gap-1 transition cursor-pointer disabled:opacity-50"
                              >
                                <span>审批配置</span>
                                <ChevronRight className="w-3.5 h-3.5 transition-transform duration-150 group-hover:translate-x-0.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* 3. 安全审计日志简洁表格 */}
        {activeTab === 'audit' && (
          <div>
            <div className="px-6 py-3.5 bg-[#FAFBFD] border-b border-slate-100 flex flex-wrap items-center justify-between gap-3">
              <div className="relative flex-1 min-w-[220px] max-w-[300px]">
                <Search className="w-3.5 h-3.5 text-[#9499A0] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  data-custom-focus="true"
                  value={auditQuery}
                  onChange={e => setAuditQuery(e.target.value)}
                  placeholder="搜索账号或事件…"
                  className={`${INPUT_BASE} pl-8.5 ${auditQuery ? 'pr-8' : ''}`}
                />
                {auditQuery && (
                  <button
                    type="button"
                    onClick={() => setAuditQuery('')}
                    aria-label="清空审计搜索"
                    className="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-md inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>

              <div className="inline-flex flex-wrap items-center p-1 rounded-[11px] bg-slate-100/85 border border-slate-200/50">
                {auditCategoryOptions.map(([cat, label]) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setAuditCategory(cat)}
                    className={`h-7 px-3 rounded-[8px] text-[12px] font-medium transition cursor-pointer whitespace-nowrap ${
                      auditCategory === cat
                        ? 'bg-white text-[#18191C] shadow-[0_1px_3px_rgba(15,23,42,0.08)]'
                        : 'text-[#61666D] hover:text-[#18191C]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {auditLoading ? (
              <div className="px-6 py-5 space-y-2.5">
                {[0, 1, 2, 3, 4].map(idx => (
                  <div key={idx} className="h-11 rounded-xl bg-slate-50 animate-pulse" />
                ))}
              </div>
            ) : filteredAudits.length === 0 ? (
              <div className="py-16 text-center space-y-2.5">
                <div className="w-11 h-11 rounded-2xl bg-slate-50 border border-slate-100 text-slate-300 flex items-center justify-center mx-auto">
                  <Clock className="w-5 h-5" />
                </div>
                <p className="text-[13px] font-medium text-[#4E5969]">暂无匹配的审计记录</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-100 text-[12px] font-medium text-[#61666D] bg-[#FAFBFD]/60">
                      <th className="py-3 pl-6 pr-4">时间</th>
                      <th className="py-3 px-4">操作账号</th>
                      <th className="py-3 px-4">事件</th>
                      <th className="py-3 px-4">目标对象</th>
                      <th className="py-3 pl-4 pr-6 text-right">结果</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100/90 text-[13px]">
                    {filteredAudits.map(evt => {
                      const meta = formatAuditAction(evt.action);
                      const detailLabel = formatAuditDetail(evt.detail);
                      const isPositive =
                        evt.detail === 'success' ||
                        evt.detail === 'approved' ||
                        evt.detail === 'enabled';
                      const isWarning = evt.detail === 'rejected' || evt.detail === 'disabled';
                      return (
                        <tr key={evt.id} className="hover:bg-[#F7FAFC] transition-colors">
                          <td className="py-3 pl-6 pr-4 font-mono text-[12px] text-[#61666D] tabular-nums whitespace-nowrap">
                            {formatAuditTime(evt.time)}
                          </td>
                          <td className="py-3 px-4 text-[12.5px] font-medium text-[#18191C] whitespace-nowrap">
                            {evt.username || 'system'}
                          </td>
                          <td className="py-3 px-4 text-[#18191C] whitespace-nowrap">
                            {meta.label}
                          </td>
                          <td
                            className="py-3 px-4 text-[12px] text-[#61666D] whitespace-nowrap"
                            title={evt.run_id || undefined}
                          >
                            {evt.run_id ? getWorkspaceDisplayLabel(evt.run_id) : '—'}
                          </td>
                          <td className="py-3 pl-4 pr-6 text-right whitespace-nowrap">
                            <span
                              className={`text-[12px] font-medium ${
                                isPositive
                                  ? 'text-emerald-600'
                                  : isWarning
                                    ? 'text-rose-600'
                                    : 'text-[#61666D]'
                              }`}
                            >
                              {detailLabel}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 右侧滑出精致配置抽屉（通过 Portal 挂载至 body，确保全屏视口对齐） */}
      {selectedUser &&
        selectedDraft &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            className="fixed inset-0 z-[70] flex justify-end bg-slate-900/25 backdrop-blur-[3px]"
            onClick={() => {
              if (!busyKey) closeMemberDrawer();
            }}
          >
            <aside
              role="dialog"
              aria-modal="true"
              aria-label={`${selectedUser.display_name} 权限配置`}
              onClick={e => e.stopPropagation()}
              className="w-full max-w-[448px] h-full bg-white border-l border-slate-200/90 shadow-[-24px_0_64px_-24px_rgba(15,23,42,0.22)] flex flex-col"
            >
              {drawerMode === 'password' ? (
                /* 无缝内嵌：修改成员登录密码子视图（避免双层弹窗叠压，100%适配主界面风格） */
                <form
                  onSubmit={handleResetPasswordSubmit}
                  className="flex-1 min-h-0 flex flex-col"
                >
                {/* 顶部返回栏 */}
                <div className="px-6 py-4 bg-gradient-to-b from-[#FAFBFD] to-white border-b border-slate-100 flex items-center justify-between gap-3 shrink-0">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <button
                      type="button"
                      disabled={Boolean(busyKey)}
                      onClick={() => setDrawerMode('permissions')}
                      aria-label="返回权限配置"
                      className="w-8 h-8 -ml-1.5 rounded-xl inline-flex items-center justify-center text-[#61666D] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer shrink-0"
                    >
                      <ArrowLeft className="w-4 h-4" />
                    </button>
                    <div className="min-w-0">
                      <h3
                        id="reset-pw-title"
                        className="text-[15px] font-semibold text-[#18191C] truncate"
                      >
                        修改登录密码
                      </h3>
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={Boolean(busyKey)}
                    onClick={closeMemberDrawer}
                    aria-label="关闭配置抽屉"
                    className="w-8 h-8 rounded-xl inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer shrink-0"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* 主体：身份卡 + 细线分隔密码输入卡 */}
                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 bg-[#FAFBFD]/50">
                  <div className="rounded-2xl border border-[#00AEEC]/20 bg-sky-50/55 px-4 py-3.5 flex items-center gap-3">
                    <span className="w-9 h-9 rounded-xl bg-white border border-[#00AEEC]/20 text-[#008EC4] flex items-center justify-center shrink-0 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
                      <KeyRound className="w-4 h-4" />
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13.5px] font-semibold text-[#18191C] truncate">
                        {selectedUser.display_name}
                      </div>
                      <p className="text-[11.5px] text-[#61666D] mt-0.5">
                        修改保存后，该成员原有的登录会话将立即失效
                      </p>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="px-1 text-[12px] font-semibold text-[#4E5969] tracking-wide">
                      设置新密码
                    </div>
                    <div className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden divide-y divide-slate-100 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
                      <label className="flex items-center gap-3 px-4 py-3.5 focus-within:bg-sky-50/45 transition-colors cursor-text">
                        <span className="w-8 h-8 rounded-[10px] bg-sky-50 text-[#008EC4] flex items-center justify-center shrink-0">
                          <Lock className="w-4 h-4" />
                        </span>
                        <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                          新密码
                        </span>
                        <input
                          id="rp-new"
                          type={resetShowPw ? 'text' : 'password'}
                          required
                          minLength={6}
                          autoFocus
                          data-custom-focus="true"
                          autoComplete="new-password"
                          value={resetPasswordVal}
                          onChange={e => setResetPasswordVal(e.target.value)}
                          placeholder="至少 6 位字符"
                          className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setResetShowPw(v => !v)}
                          aria-label={resetShowPw ? '隐藏密码' : '显示密码'}
                          className="w-7 h-7 rounded-lg inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100/80 transition cursor-pointer shrink-0"
                        >
                          {resetShowPw ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </label>

                      <label className="flex items-center gap-3 px-4 py-3.5 focus-within:bg-sky-50/45 transition-colors cursor-text">
                        <span
                          className={`w-8 h-8 rounded-[10px] flex items-center justify-center shrink-0 transition-colors ${
                            resetPwMatchOk
                              ? 'bg-emerald-50 text-emerald-600'
                              : resetPwMismatch
                                ? 'bg-rose-50 text-rose-500'
                                : 'bg-slate-100/85 text-[#9499A0]'
                          }`}
                        >
                          <ShieldCheck className="w-4 h-4" />
                        </span>
                        <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                          确认密码
                        </span>
                        <input
                          id="rp-confirm"
                          type={resetShowPw ? 'text' : 'password'}
                          required
                          minLength={6}
                          data-custom-focus="true"
                          autoComplete="new-password"
                          value={resetConfirmVal}
                          onChange={e => setResetConfirmVal(e.target.value)}
                          placeholder="再次输入新密码"
                          className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                        />
                      </label>
                    </div>

                    <div className="flex items-center justify-between px-1 pt-1 text-[11.5px]">
                      <span
                        className={
                          resetPwLenOk ? 'text-emerald-600 font-medium' : 'text-[#9499A0]'
                        }
                      >
                        {resetPwLenOk ? '✓ 密码长度已达标' : '密码长度需不少于 6 位字符'}
                      </span>
                      {resetPwMismatch ? (
                        <span className="text-rose-600 font-medium">两次输入不一致</span>
                      ) : resetPwMatchOk ? (
                        <span className="text-emerald-600 font-medium">✓ 确认一致</span>
                      ) : null}
                    </div>
                  </div>
                </div>

                {/* 底部提交栏 */}
                <div className="px-6 py-4 border-t border-slate-100 bg-white flex items-center justify-end gap-2.5 shrink-0">
                  <button
                    type="button"
                    disabled={Boolean(busyKey)}
                    onClick={() => setDrawerMode('permissions')}
                    className="h-9 px-4 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] transition cursor-pointer"
                  >
                    返回配置
                  </button>
                  <button
                    type="submit"
                    disabled={
                      busyKey === `reset:${selectedUser.id}` ||
                      !resetPwLenOk ||
                      resetPwMismatch ||
                      !resetConfirmVal
                    }
                    className="h-9 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold shadow-[0_8px_18px_-10px_rgba(0,174,236,0.85)] transition cursor-pointer disabled:opacity-50"
                  >
                    {busyKey === `reset:${selectedUser.id}` ? '保存中…' : '确认修改'}
                  </button>
                </div>
              </form>
            ) : (
              /* 默认视图：模块权限与扣款配置同步 */
              <>
                {/* 顶部状态栏：点击用户名无缝切换至修改密码 */}
                <div className="px-6 py-4 bg-gradient-to-b from-[#FAFBFD] to-white border-b border-slate-100 flex items-center justify-between gap-3 shrink-0">
                  <div className="flex items-center gap-2.5 min-w-0">
                    {selectedUser.status !== 'pending' ? (
                      <button
                        type="button"
                        disabled={Boolean(busyKey)}
                        onClick={openDrawerPasswordMode}
                        title="点击修改该成员登录密码"
                        className="group inline-flex items-center gap-2 -ml-2 px-2.5 py-1.5 rounded-xl hover:bg-sky-50/85 transition cursor-pointer min-w-0 disabled:opacity-55"
                      >
                        <span className="text-[15px] font-semibold text-[#18191C] group-hover:text-[#008EC4] truncate transition-colors">
                          {selectedUser.display_name}
                        </span>
                        <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#757A82] group-hover:text-[#008EC4] shrink-0 transition-colors">
                          <KeyRound className="w-3.5 h-3.5" />
                          <span>修改密码</span>
                        </span>
                      </button>
                    ) : (
                      <h3 className="text-[15px] font-semibold text-[#18191C] truncate">
                        {selectedUser.display_name}
                      </h3>
                    )}

                    <span
                      className={`text-[12px] font-medium shrink-0 ${
                        selectedUser.status === 'active'
                          ? 'text-emerald-600'
                          : selectedUser.status === 'pending'
                            ? 'text-amber-600'
                            : 'text-[#61666D]'
                      }`}
                    >
                      {getStatusLabel(selectedUser.status)}
                    </span>
                  </div>

                  <button
                    type="button"
                    disabled={Boolean(busyKey)}
                    onClick={closeMemberDrawer}
                    aria-label="关闭配置抽屉"
                    className="w-8 h-8 rounded-xl inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer shrink-0"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* 抽屉主内容 */}
                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 bg-[#FAFBFD]/50">
                  {selectedUser.role === 'admin' && (
                    <div className="rounded-2xl bg-sky-50/65 border border-[#00AEEC]/20 px-4 py-3 text-[12.5px] text-[#0073A0] flex items-center gap-2.5">
                      <ShieldCheck className="w-4 h-4 text-[#00AEEC] shrink-0" />
                      <span>系统管理员默认拥有全部业务与共享通道权限</span>
                    </div>
                  )}

                  <PermissionConfigList
                    permissions={selectedDraft.permissions}
                    disabled={selectedUser.role === 'admin'}
                    onChange={(key, next) =>
                      updateUserDraftPermission(selectedUser.id, key, next)
                    }
                    onBatchChange={
                      selectedUser.role === 'admin'
                        ? undefined
                        : nextPerms => replaceUserDraftPermissions(selectedUser.id, nextPerms)
                    }
                  />

                  {/* 扣款配置同步入口（融入操作配置抽屉，内联确认无叠层弹窗） */}
                  {selectedUser.status === 'active' && selectedUser.role !== 'admin' && (
                    <div className="space-y-1.5">
                      <div className="px-1 text-[12px] font-semibold text-[#4E5969] tracking-wide">
                        扣款配置
                      </div>
                      <div className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
                        <div className="px-4 py-3 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="w-7.5 h-7.5 rounded-[9px] bg-sky-50 text-[#008EC4] flex items-center justify-center shrink-0">
                              <CopyCheck className="w-3.5 h-3.5" />
                            </span>
                            <div className="min-w-0">
                              <div className="text-[13px] font-medium text-[#18191C]">
                                同步默认扣款表
                              </div>
                              <div className="text-[11.5px] text-[#9499A0] truncate">
                                将主空间标准扣款配置同步至该成员空间
                              </div>
                            </div>
                          </div>

                          {!syncConfirming && (
                            <button
                              type="button"
                              disabled={Boolean(busyKey)}
                              onClick={() => setSyncConfirming(true)}
                              className="h-8 px-3 rounded-[10px] border border-slate-200/90 bg-white hover:border-[#00AEEC]/40 hover:bg-sky-50/50 hover:text-[#008EC4] text-[12px] font-medium text-[#4E5969] transition cursor-pointer shrink-0 disabled:opacity-50"
                            >
                              同步
                            </button>
                          )}
                        </div>

                        {syncConfirming && (
                          <div className="px-4 py-3 bg-sky-50/55 border-t border-[#00AEEC]/15 flex items-center justify-between gap-3">
                            <span className="text-[12px] text-[#0073A0]">
                              覆盖该成员扣款表？历史任务不受影响
                            </span>
                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                type="button"
                                disabled={Boolean(busyKey)}
                                onClick={() => setSyncConfirming(false)}
                                className="h-7.5 px-2.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-[11.5px] font-medium text-[#4E5969] transition cursor-pointer"
                              >
                                取消
                              </button>
                              <button
                                type="button"
                                disabled={busyKey === `sync:${selectedUser.id}`}
                                onClick={() => void handleSyncDefaultConfig(selectedUser)}
                                className="h-7.5 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[11.5px] font-semibold transition cursor-pointer disabled:opacity-55"
                              >
                                {busyKey === `sync:${selectedUser.id}` ? '同步中…' : '确认同步'}
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* 抽屉底部操作栏 */}
                {selectedUser.status === 'pending' ? (
                  <div className="px-6 py-4 border-t border-slate-100 bg-white flex items-center justify-end gap-2.5 shrink-0">
                    <button
                      type="button"
                      disabled={Boolean(busyKey)}
                      onClick={() => setRejectConfirmUser(selectedUser)}
                      className="h-9 px-4 rounded-xl border border-rose-200 bg-white hover:bg-rose-50 text-xs font-medium text-rose-600 transition cursor-pointer disabled:opacity-55"
                    >
                      驳回
                    </button>
                    <button
                      type="button"
                      disabled={busyKey === `approve:${selectedUser.id}`}
                      onClick={() => void handleApprove(selectedUser)}
                      className="h-9 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-55"
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>
                        {busyKey === `approve:${selectedUser.id}` ? '开通中…' : '批准并开通空间'}
                      </span>
                    </button>
                  </div>
                ) : selectedIsDirty ? (
                  <div className="px-6 py-4 border-t border-slate-200/80 bg-white flex items-center justify-between gap-3 shrink-0">
                    <span className="text-[12.5px] font-medium text-[#008EC4]">
                      有未保存的权限修改
                    </span>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        type="button"
                        disabled={busyKey === `save:${selectedUser.id}`}
                        onClick={() => resetUserDraft(selectedUser)}
                        className="h-9 px-3.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] inline-flex items-center gap-1.5 transition cursor-pointer"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>还原</span>
                      </button>
                      <button
                        type="button"
                        disabled={busyKey === `save:${selectedUser.id}`}
                        onClick={() => void handleSavePermissions(selectedUser)}
                        className="h-9 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold shadow-[0_8px_18px_-10px_rgba(0,174,236,0.85)] inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-55"
                      >
                        <Save className="w-3.5 h-3.5" />
                        <span>
                          {busyKey === `save:${selectedUser.id}` ? '保存中…' : '保存配置'}
                        </span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="px-6 py-3.5 border-t border-slate-100 bg-white flex items-center justify-between gap-2 text-[11.5px] text-[#9499A0] shrink-0">
                    <span>权限配置已同步</span>
                    <span>点击上方用户名可修改密码</span>
                  </div>
                )}
              </>
            )}
            </aside>
          </div>,
          document.body,
        )}

      {/* 弹窗 1：新建成员（通过 Portal 挂载至 body，统一细线图标行卡） */}
      {createOpen &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            className="fixed inset-0 z-[70] bg-slate-900/28 backdrop-blur-[3px] flex items-center justify-center p-4"
            onClick={() => !busyKey && setCreateOpen(false)}
          >
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-member-title"
            onSubmit={handleCreateSubmit}
            className="w-full max-w-[464px] max-h-[92vh] rounded-[22px] bg-white border border-slate-200/85 shadow-[0_24px_64px_-20px_rgba(15,23,42,0.24)] overflow-hidden flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            {/* 弹窗顶部 */}
            <div className="px-6 py-4 bg-gradient-to-b from-[#FAFBFD] to-white border-b border-slate-100 flex items-center justify-between gap-3 shrink-0">
              <div>
                <h2
                  id="create-member-title"
                  className="text-[15.5px] font-semibold text-[#18191C]"
                >
                  新建成员
                </h2>
                <p className="text-[12px] text-[#757A82] mt-0.5">
                  创建账号并分配初始模块访问权限
                </p>
              </div>
              <button
                type="button"
                disabled={Boolean(busyKey)}
                onClick={() => setCreateOpen(false)}
                aria-label="关闭弹窗"
                className="w-8 h-8 rounded-xl inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 弹窗主表单区 */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 bg-[#FAFBFD]/50">
              {/* 账号信息（与下方模块权限采用统一细线图标行卡，消除拥挤与双层框感） */}
              <div className="space-y-1.5">
                <div className="px-1 text-[12px] font-semibold text-[#4E5969] tracking-wide">
                  账号信息
                </div>
                <div className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden divide-y divide-slate-100 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
                  <label className="flex items-center gap-3 px-4 py-2.5 focus-within:bg-sky-50/45 transition-colors cursor-text">
                    <span className="w-7.5 h-7.5 rounded-[9px] bg-sky-50 text-[#008EC4] flex items-center justify-center shrink-0">
                      <User className="w-3.5 h-3.5" />
                    </span>
                    <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                      用户姓名
                    </span>
                    <input
                      id="cm-username"
                      type="text"
                      required
                      minLength={2}
                      maxLength={40}
                      autoFocus
                      data-custom-focus="true"
                      value={createUsername}
                      onChange={e => setCreateUsername(e.target.value)}
                      placeholder="请输入用户姓名"
                      className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                    />
                  </label>

                  <label className="flex items-center gap-3 px-4 py-2.5 focus-within:bg-sky-50/45 transition-colors cursor-text">
                    <span className="w-7.5 h-7.5 rounded-[9px] bg-slate-100/85 text-[#61666D] flex items-center justify-center shrink-0">
                      <Lock className="w-3.5 h-3.5" />
                    </span>
                    <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                      初始密码
                    </span>
                    <input
                      id="cm-password"
                      type={createShowPw ? 'text' : 'password'}
                      required
                      minLength={6}
                      data-custom-focus="true"
                      value={createPassword}
                      onChange={e => setCreatePassword(e.target.value)}
                      placeholder="设置至少 6 位密码"
                      className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setCreateShowPw(v => !v)}
                      aria-label={createShowPw ? '隐藏密码' : '显示密码'}
                      className="w-7 h-7 rounded-lg inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100/80 transition cursor-pointer shrink-0"
                    >
                      {createShowPw ? (
                        <EyeOff className="w-3.5 h-3.5" />
                      ) : (
                        <Eye className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </label>
                </div>
              </div>

              {/* 模块权限配置列表 */}
              <PermissionConfigList
                compact
                permissions={createDraft.permissions}
                onChange={(key, next) =>
                  setCreateDraft(prev => ({
                    role_template: 'custom',
                    permissions: { ...prev.permissions, [key]: next },
                  }))
                }
                onBatchChange={nextPerms =>
                  setCreateDraft({
                    role_template: 'custom',
                    permissions: nextPerms,
                  })
                }
              />
            </div>

            {/* 弹窗底部操作栏 */}
            <div className="px-6 py-3.5 bg-white border-t border-slate-100 flex items-center justify-end gap-2.5 shrink-0">
              <button
                type="button"
                disabled={busyKey === 'create'}
                onClick={() => setCreateOpen(false)}
                className="h-9 px-4 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] transition cursor-pointer"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={busyKey === 'create'}
                className="h-9 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold shadow-[0_8px_18px_-10px_rgba(0,174,236,0.85)] transition cursor-pointer disabled:opacity-55"
              >
                {busyKey === 'create' ? '创建中…' : '创建并开通'}
              </button>
            </div>
          </form>
        </div>,
          document.body,
        )}

      {/* 弹窗 2：历史待审批驳回确认（兼容旧库兜底） */}
      {rejectConfirmUser &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            className="fixed inset-0 z-[75] bg-slate-900/28 backdrop-blur-[3px] flex items-center justify-center p-4"
            onClick={() => !busyKey && setRejectConfirmUser(null)}
          >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="reject-confirm-title"
            className="w-full max-w-sm rounded-[22px] bg-white border border-slate-200/85 shadow-[0_24px_64px_-20px_rgba(15,23,42,0.24)] p-6 space-y-4"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <span className="w-9 h-9 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center shrink-0">
                <ShieldAlert className="w-4 h-4" />
              </span>
              <div>
                <h2 id="reject-confirm-title" className="text-sm font-semibold text-[#18191C]">
                  驳回注册申请
                </h2>
                <p className="text-xs text-[#61666D] mt-1 leading-relaxed">
                  确认驳回「{rejectConfirmUser.display_name}」的注册申请吗？驳回后该账号无法登录。
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                disabled={Boolean(busyKey)}
                onClick={() => setRejectConfirmUser(null)}
                className="h-9 px-3.5 rounded-xl border border-slate-200 text-xs font-medium text-[#4E5969] hover:bg-slate-50 cursor-pointer"
              >
                取消
              </button>
              <button
                type="button"
                disabled={busyKey === `reject:${rejectConfirmUser.id}`}
                onClick={() => void handleConfirmReject()}
                className="h-9 px-4 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold transition cursor-pointer disabled:opacity-55"
              >
                {busyKey === `reject:${rejectConfirmUser.id}` ? '处理中…' : '确认驳回'}
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
      <div className="w-full max-w-md rounded-2xl bg-white border border-slate-200/85 shadow-[0_8px_28px_-20px_rgba(15,23,42,0.12)] px-8 py-9 text-center space-y-5">
        <div className="w-11 h-11 rounded-2xl bg-sky-50 border border-[#00AEEC]/20 text-[#008EC4] flex items-center justify-center mx-auto">
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-sm font-bold text-[#18191C]">当前账号尚未开通此模块权限</h2>
          <p className="text-xs text-[#61666D] leading-relaxed">
            {displayName}，请联系管理员开启对应模块权限，或先前往任务中心与文件领取查看记录。
          </p>
        </div>
        <div className="flex items-center justify-center gap-2.5">
          <button
            type="button"
            onClick={onOpenHistory}
            className="h-9 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold transition cursor-pointer"
          >
            进入任务中心
          </button>
          <button
            type="button"
            onClick={onOpenPickup}
            className="h-9 px-4 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] transition cursor-pointer"
          >
            前往文件领取
          </button>
        </div>
      </div>
    </div>
  );
}
