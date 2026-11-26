import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Calculator,
  Check,
  ChevronDown,
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
  getRoleTemplateLabel,
  getStatusLabel,
  getWorkspaceDisplayLabel,
  hasDraftChanges,
  resolveAuditTargetLabel,
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
  'w-full h-8 rounded-lg border border-slate-200/90 bg-white px-2.5 text-[12.5px] text-[#18191C] placeholder:text-[#9499A0] transition duration-150 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15';

const PERMISSION_ICONS: Record<PermissionKey, React.ComponentType<{ className?: string }>> = {
  collection: Download,
  reports: FileSpreadsheet,
  payroll: Calculator,
  approval: FileCheck2,
  xiaoxiang_use: Store,
  benlai_use: ShoppingBag,
  shared_auth_manage: ShieldCheck,
};

const AUDIT_CATEGORY_OPTIONS: { key: AuditCategory; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'auth', label: '登录' },
  { key: 'permission', label: '权限' },
  { key: 'approval', label: '审批' },
  { key: 'workspace', label: '空间' },
  { key: 'security', label: '安全' },
];

const AUDIT_CATEGORY_TONE: Record<Exclude<AuditCategory, 'all'>, string> = {
  auth: 'text-sky-700',
  permission: 'text-indigo-700',
  approval: 'text-amber-700',
  workspace: 'text-emerald-700',
  security: 'text-rose-700',
};

const MEMBER_STATUS_OPTIONS: {
  key: 'all' | 'active' | 'disabled' | 'rejected';
  label: string;
}[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '启用' },
  { key: 'disabled', label: '停用' },
  { key: 'rejected', label: '驳回' },
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
  disabled?: boolean;
  columns?: 1 | 2;
  onChange: (key: PermissionKey, next: boolean) => void;
}

function PermissionMatrix({
  permissions,
  disabled = false,
  columns = 1,
  onChange,
}: PermissionMatrixProps) {
  return (
    <div className="space-y-3">
      {PERMISSION_GROUPS.map(group => {
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
                const Icon = PERMISSION_ICONS[item.key];
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
                        <div
                          className={`text-[12.5px] font-semibold leading-tight truncate ${
                            enabled ? 'text-[#18191C]' : 'text-slate-600'
                          }`}
                        >
                          {item.label}
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
  const [users, setUsers] = useState<WorkspaceUser[]>([]);
  const [roleTemplates, setRoleTemplates] = useState<Record<string, RoleTemplateDef>>({});
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyKey, setBusyKey] = useState('');

  const [activeTab, setActiveTab] = useState<AccountConsoleTab>('members');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'disabled' | 'rejected'>('all');
  const [auditQuery, setAuditQuery] = useState('');
  const [auditCategory, setAuditCategory] = useState<AuditCategory>('all');

  const [selectedUserId, setSelectedUserId] = useState<string>('');
  const [drafts, setDrafts] = useState<Record<string, UserPermissionDraft>>({});

  // Inline password reset inside right inspector
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [resetPwdValue, setResetPwdValue] = useState('');
  const [resetPwdVisible, setResetPwdVisible] = useState(false);

  // Pending approval expanded row
  const [expandedPendingId, setExpandedPendingId] = useState<string>('');
  const [rejectConfirmUser, setRejectConfirmUser] = useState<WorkspaceUser | null>(null);

  // Create member modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createUsername, setCreateUsername] = useState('');
  const [createDisplayName, setCreateDisplayName] = useState('');
  const [createPassword, setCreatePassword] = useState('');
  const [createPasswordVisible, setCreatePasswordVisible] = useState(false);
  const [createNote, setCreateNote] = useState('');
  const [createTemplate, setCreateTemplate] = useState('payroll_specialist');
  const [createPermissions, setCreatePermissions] = useState<Record<PermissionKey, boolean>>(() =>
    buildFullPermissions(false),
  );
  const [createError, setCreateError] = useState('');

  const onAccountsChangedRef = useRef(onAccountsChanged);
  onAccountsChangedRef.current = onAccountsChanged;
  const onToastRef = useRef(onToast);
  onToastRef.current = onToast;

  const syncDraftsFromUsers = useCallback((list: WorkspaceUser[]) => {
    setDrafts(prev => {
      const next: Record<string, UserPermissionDraft> = {};
      for (const u of list) {
        next[u.id] = createDraftFromUser(u);
      }
      // Preserve unsaved edits only if user still exists and isn't being freshly synced after save
      void prev;
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
        const nextTemplates = acctRes.role_templates || {};
        setUsers(nextUsers);
        setRoleTemplates(nextTemplates);
        setAuditEvents(auditRes.events || []);
        syncDraftsFromUsers(nextUsers);
        onAccountsChangedRef.current(acctRes.pending_count || 0, acctRes.workspaces || []);
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

  const pendingUsers = useMemo(
    () => users.filter(u => u.status === 'pending'),
    [users],
  );

  const managedUsers = useMemo(
    () => users.filter(u => u.status !== 'pending' && u.status !== 'rejected'),
    [users],
  );

  const activeMemberCount = useMemo(
    () => managedUsers.filter(u => u.status === 'active').length,
    [managedUsers],
  );

  const disabledMemberCount = useMemo(
    () => managedUsers.filter(u => u.status === 'disabled').length,
    [managedUsers],
  );

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

  // Keep right inspector always populated with a valid selected member
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

  const editableTemplates = useMemo(
    () =>
      Object.entries(roleTemplates).filter(
        ([key, tpl]) => key !== 'admin' && tpl.role !== 'admin',
      ),
    [roleTemplates],
  );

  const allTemplateEntries = useMemo(
    () => Object.entries(roleTemplates),
    [roleTemplates],
  );

  // Initialize default create modal permissions once templates arrive
  const openCreateModal = () => {
    const defaultKey =
      roleTemplates.payroll_specialist
        ? 'payroll_specialist'
        : editableTemplates[0]?.[0] || 'custom';
    const nextDraft =
      defaultKey !== 'custom' && roleTemplates[defaultKey]
        ? applyTemplateToDraft(defaultKey, roleTemplates)
        : { role_template: 'custom', permissions: buildFullPermissions(false) };
    setCreateUsername('');
    setCreateDisplayName('');
    setCreatePassword('');
    setCreatePasswordVisible(false);
    setCreateNote('');
    setCreateTemplate(nextDraft.role_template);
    setCreatePermissions(nextDraft.permissions);
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
          role_template: 'custom',
          permissions: {
            ...base.permissions,
            [key]: nextVal,
          },
        },
      };
    });
  };

  const applyTemplateToUser = (userId: string, templateKey: string) => {
    const applied = applyTemplateToDraft(templateKey, roleTemplates);
    setDrafts(prev => ({
      ...prev,
      [userId]: applied,
    }));
  };

  const batchSetUserPermissions = (userId: string, enabled: boolean) => {
    setDrafts(prev => ({
      ...prev,
      [userId]: {
        role_template: 'custom',
        permissions: buildFullPermissions(enabled),
      },
    }));
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
        role_template: draft.role_template,
        permissions: draft.permissions,
      });
      setUsers(res.users);
      setDrafts(prev => ({
        ...prev,
        [user.id]: createDraftFromUser(res.user),
      }));
      onAccountsChanged(res.pending_count, res.workspaces);
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
      onAccountsChanged(res.pending_count, res.workspaces);
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

  const handleApprovePending = async (user: WorkspaceUser) => {
    const draft = drafts[user.id] || createDraftFromUser(user);
    setBusyKey(`approve:${user.id}`);
    try {
      const res = await adminApproveAccount(user.id, {
        role_template: draft.role_template,
        permissions: draft.permissions,
        display_name: user.display_name,
        note: user.note,
      });
      setUsers(res.users);
      setDrafts(prev => ({
        ...prev,
        [user.id]: createDraftFromUser(res.user),
      }));
      onAccountsChanged(res.pending_count, res.workspaces);
      onToast(`已批准开通 ${user.display_name}`, 'success');
      fetchAdminAuditLogs()
        .then(r => setAuditEvents(r.events || []))
        .catch(() => {});
    } catch (err) {
      onToast(err instanceof Error ? err.message : '批准开通失败', 'error');
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
      setRejectConfirmUser(null);
      onAccountsChanged(
        res.pending_count,
        users
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
      onToast(`已驳回 ${target.display_name} 的申请`, 'info');
      void loadData(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : '驳回失败', 'error');
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
        role_template: createTemplate,
        permissions: createTemplate === 'admin' ? buildFullPermissions(true) : createPermissions,
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
      onAccountsChanged(
        res.users.filter(u => u.status === 'pending').length,
        res.workspaces,
      );
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
              成员 <strong className="font-semibold text-[#18191C]">{managedUsers.length}</strong>
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
            {pendingUsers.length > 0 && (
              <>
                <span className="text-slate-300" aria-hidden="true">·</span>
                <button
                  type="button"
                  onClick={() => setActiveTab('pending')}
                  className="text-amber-700 hover:underline font-medium cursor-pointer"
                >
                  待审 <strong className="font-semibold">{pendingUsers.length}</strong>
                </button>
              </>
            )}
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
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#4E5969] transition cursor-pointer disabled:opacity-55"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            type="button"
            onClick={openCreateModal}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer shadow-xs"
          >
            <UserPlus className="w-3.5 h-3.5" />
            新建成员
          </button>
        </div>
      </div>

      {/* 单层高纯净白主容器（发丝线分区，零嵌套卡片堆叠） */}
      <div className="rounded-xl border border-slate-200/85 bg-white overflow-hidden">
        {/* 合并工具栏：左侧视图切换 + 右侧情境搜索/筛选 */}
        <div className="px-3.5 py-2 border-b border-slate-100 bg-slate-50/45 flex flex-wrap items-center justify-between gap-2.5">
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
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer ${
                activeTab === 'members'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              成员权限
              <span className="text-[11px] tabular-nums text-slate-400">
                {managedUsers.length}
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'pending'}
              onClick={() => setActiveTab('pending')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer ${
                activeTab === 'pending'
                  ? 'bg-white text-[#18191C] shadow-xs font-semibold'
                  : 'text-[#61666D] hover:text-[#18191C]'
              }`}
            >
              待审批
              {pendingUsers.length > 0 ? (
                <span className="text-[11px] tabular-nums font-semibold text-amber-600">
                  {pendingUsers.length}
                </span>
              ) : (
                <span className="text-[11px] tabular-nums text-slate-400">0</span>
              )}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'audit'}
              onClick={() => setActiveTab('audit')}
              className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[12px] font-medium transition cursor-pointer ${
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

          {activeTab === 'pending' && (
            <span className="text-[12px] text-slate-500">
              {pendingUsers.length > 0
                ? `共 ${pendingUsers.length} 条待审批注册申请`
                : '当前无待处理申请'}
            </span>
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
                        ? ALL_PERMISSION_KEYS.length
                        : countEnabledPermissions(draft.permissions);
                      const enabledLabels = getEnabledPermissionLabels(draft.permissions, isAdmin);
                      const roleLabel = getRoleTemplateLabel(
                        user.role,
                        draft.role_template,
                        roleTemplates,
                      );
                      const canToggle = !isSelf && user.username !== 'host_admin' && user.status !== 'rejected';
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
                          {/* 成员账号 */}
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
                                  {user.display_name.trim() !== roleLabel.trim() && (
                                    <span
                                      className={`text-[11px] font-medium shrink-0 ${
                                        isAdmin ? 'text-[#008EC4]' : 'text-slate-400'
                                      }`}
                                    >
                                      · {roleLabel}
                                    </span>
                                  )}
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
                                  {ALL_PERMISSION_KEYS.map((k, idx) => (
                                    <span
                                      key={k}
                                      className={`h-1.5 w-2 rounded-[2px] ${
                                        idx < enabledCount
                                          ? enabledCount === ALL_PERMISSION_KEYS.length
                                            ? 'bg-emerald-500'
                                            : 'bg-[#00AEEC]'
                                          : 'bg-slate-200/90'
                                      }`}
                                    />
                                  ))}
                                </div>
                                <span className="text-[11.5px] font-semibold tabular-nums text-slate-600">
                                  {enabledCount}/{ALL_PERMISSION_KEYS.length}
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
                                : selectedUser.status === 'disabled'
                                  ? 'bg-slate-400'
                                  : 'bg-rose-400'
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

                  {/* 快捷角色模板与全选/清空条（普通成员可见） */}
                  {isSelectedEditable ? (
                    <div className="px-4 py-2 bg-slate-50/60 border-b border-slate-100 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1">
                        {editableTemplates.map(([tplKey, tpl]) => {
                          const active = selectedDraft.role_template === tplKey;
                          return (
                            <button
                              key={tplKey}
                              type="button"
                              onClick={() => applyTemplateToUser(selectedUser.id, tplKey)}
                              title={tpl.description}
                              className={`h-6 px-2 rounded-md text-[11px] font-medium border transition cursor-pointer ${
                                active
                                  ? 'bg-sky-50 border-sky-200 text-[#0086C4] font-semibold'
                                  : 'bg-white border-slate-200/80 text-slate-600 hover:border-slate-300'
                              }`}
                            >
                              {tpl.label}
                            </button>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-2 text-[11px]">
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
                      <span>系统管理员默认拥有全部 7 项模块与共享通道权限</span>
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
                          ? countEnabledPermissions(selectedDraft.permissions)
                          : ALL_PERMISSION_KEYS.length}
                      </strong>
                      /{ALL_PERMISSION_KEYS.length} 项
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
        ) : activeTab === 'pending' ? (
          /* ===================== 视图二：待审批申请列表 ===================== */
          pendingUsers.length === 0 ? (
            <div className="py-14 px-6 text-center space-y-2">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center mx-auto">
                <Check className="w-4.5 h-4.5" />
              </div>
              <div className="text-[13px] font-medium text-[#18191C]">暂无待审批申请</div>
              <p className="text-[12px] text-slate-400">
                如需为同事直接开通账号，可点击右上角「新建成员」统一建号并分配权限。
              </p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {pendingUsers.map(applicant => {
                const draft = drafts[applicant.id] || createDraftFromUser(applicant);
                const expanded = expandedPendingId === applicant.id;
                const enabledCount = countEnabledPermissions(draft.permissions);
                const approving = busyKey === `approve:${applicant.id}`;

                return (
                  <div key={applicant.id} className="px-4 py-3 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[13.5px] font-semibold text-[#18191C]">
                            {applicant.display_name}
                          </span>
                          <span className="font-mono text-[11.5px] text-slate-400">
                            @{applicant.username}
                          </span>
                          <span className="text-[11px] text-slate-400 tabular-nums">
                            · {formatAuditTime(applicant.created_at)}
                          </span>
                        </div>
                        {applicant.note && (
                          <p className="text-[12px] text-slate-500 mt-0.5">{applicant.note}</p>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <select
                          aria-label={`为 ${applicant.display_name} 选择初始角色模板`}
                          value={draft.role_template}
                          onChange={e => applyTemplateToUser(applicant.id, e.target.value)}
                          className="h-8 rounded-lg border border-slate-200 bg-white px-2.5 text-[12px] text-[#18191C] focus:outline-none focus:border-[#00AEEC]"
                        >
                          {editableTemplates.map(([key, tpl]) => (
                            <option key={key} value={key}>
                              {tpl.label}
                            </option>
                          ))}
                          <option value="custom">自定义权限（{enabledCount}/7）</option>
                        </select>

                        <button
                          type="button"
                          onClick={() =>
                            setExpandedPendingId(prev =>
                              prev === applicant.id ? '' : applicant.id,
                            )
                          }
                          className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-[12px] text-slate-600 cursor-pointer"
                        >
                          微调权限
                          <ChevronDown
                            className={`w-3.5 h-3.5 transition-transform ${
                              expanded ? 'rotate-180' : ''
                            }`}
                          />
                        </button>

                        <button
                          type="button"
                          disabled={Boolean(busyKey)}
                          onClick={() => setRejectConfirmUser(applicant)}
                          className="h-8 px-3 rounded-lg border border-rose-200 bg-white hover:bg-rose-50 text-[12px] font-medium text-rose-600 transition cursor-pointer disabled:opacity-50"
                        >
                          驳回
                        </button>
                        <button
                          type="button"
                          disabled={approving}
                          onClick={() => void handleApprovePending(applicant)}
                          className="h-8 px-3 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-50"
                        >
                          {approving ? '开通中…' : '批准开通'}
                        </button>
                      </div>
                    </div>

                    {expanded && (
                      <div className="pt-2.5 border-t border-slate-100">
                        <PermissionMatrix
                          permissions={draft.permissions}
                          columns={2}
                          onChange={(key, nextVal) =>
                            updateUserDraftPermission(applicant.id, key, nextVal)
                          }
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )
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

      {/* ===================== 新建成员弹窗（紧凑双栏表单） ===================== */}
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
                    创建后自动开通独立工作空间，并按所选权限生效
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
                      <span className="text-[11.5px] font-medium text-slate-600">角色模板</span>
                      <select
                        value={createTemplate}
                        onChange={e => {
                          const tplKey = e.target.value;
                          setCreateTemplate(tplKey);
                          if (tplKey === 'admin') {
                            setCreatePermissions(buildFullPermissions(true));
                          } else if (roleTemplates[tplKey]) {
                            setCreatePermissions(
                              applyTemplateToDraft(tplKey, roleTemplates).permissions,
                            );
                          }
                        }}
                        className={INPUT_BASE}
                      >
                        {allTemplateEntries.map(([key, tpl]) => (
                          <option key={key} value={key}>
                            {tpl.label}
                          </option>
                        ))}
                        <option value="custom">自定义权限</option>
                      </select>
                    </label>
                  </div>

                  <label className="space-y-1 block">
                    <span className="text-[11.5px] font-medium text-slate-600">岗位备注（可选）</span>
                    <input
                      type="text"
                      value={createNote}
                      onChange={e => setCreateNote(e.target.value)}
                      placeholder="例如：负责华南区薪资核算与蓝橙审批"
                      className={INPUT_BASE}
                    />
                  </label>

                  <div className="pt-2 border-t border-slate-100">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[12px] font-semibold text-[#18191C]">初始模块权限</span>
                      {createTemplate !== 'admin' && (
                        <div className="flex items-center gap-2 text-[11px]">
                          <button
                            type="button"
                            onClick={() => {
                              setCreateTemplate('custom');
                              setCreatePermissions(buildFullPermissions(true));
                            }}
                            className="text-[#0086C4] hover:underline font-medium cursor-pointer"
                          >
                            全选
                          </button>
                          <span className="text-slate-300">/</span>
                          <button
                            type="button"
                            onClick={() => {
                              setCreateTemplate('custom');
                              setCreatePermissions(buildFullPermissions(false));
                            }}
                            className="text-slate-500 hover:text-slate-800 hover:underline font-medium cursor-pointer"
                          >
                            清空
                          </button>
                        </div>
                      )}
                    </div>
                    <PermissionMatrix
                      permissions={
                        createTemplate === 'admin'
                          ? buildFullPermissions(true)
                          : createPermissions
                      }
                      disabled={createTemplate === 'admin'}
                      columns={2}
                      onChange={(key, nextVal) => {
                        setCreateTemplate('custom');
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

      {/* ===================== 驳回注册申请确认弹窗 ===================== */}
      {rejectConfirmUser &&
        createPortal(
          <div
            className="fixed inset-0 z-[1000] flex items-center justify-center bg-slate-900/40 backdrop-blur-[2px] p-4"
            role="dialog"
            aria-modal="true"
            aria-label="确认驳回注册申请"
          >
            <div className="w-full max-w-sm rounded-2xl bg-white border border-slate-200/90 shadow-xl p-5 space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-rose-50 border border-rose-200/80 text-rose-600 flex items-center justify-center shrink-0">
                  <ShieldAlert className="w-4.5 h-4.5" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-[14px] font-semibold text-[#18191C]">确认驳回此注册申请？</h3>
                  <p className="text-[12px] text-slate-500 leading-relaxed">
                    驳回后，{rejectConfirmUser.display_name}（@{rejectConfirmUser.username}）将无法登录系统。
                  </p>
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  disabled={Boolean(busyKey)}
                  onClick={() => setRejectConfirmUser(null)}
                  className="h-8 px-3.5 rounded-lg border border-slate-200 text-[12px] font-medium text-slate-600 hover:bg-slate-50 cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={busyKey === `reject:${rejectConfirmUser.id}`}
                  onClick={() => void handleConfirmReject()}
                  className="h-8 px-4 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-[12px] font-semibold transition cursor-pointer disabled:opacity-55"
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
