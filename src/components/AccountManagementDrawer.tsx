import React, { useEffect, useState } from 'react';
import {
  Check,
  Eye,
  KeyRound,
  Plus,
  RefreshCw,
  Shield,
  SlidersHorizontal,
  UserCheck,
  UserPlus,
  UserX,
  X,
} from 'lucide-react';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import {
  adminApproveAccount,
  adminCreateAccount,
  adminRejectAccount,
  adminResetPassword,
  adminSyncDefaultConfig,
  adminUpdateAccount,
  fetchAdminAccounts,
  type AdminAccountsResponse,
  type PermissionKey,
  type WorkspaceDirectoryEntry,
  type WorkspaceUser,
} from '../lib/workspaceAuth';

interface AccountManagementDrawerProps {
  open: boolean;
  currentUserId: string;
  onClose: () => void;
  onInspectWorkspace: (workspaceId: string) => void;
  onAccountsChanged: (pendingCount: number, workspaces: WorkspaceDirectoryEntry[]) => void;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export function AccountManagementDrawer({
  open,
  currentUserId,
  onClose,
  onInspectWorkspace,
  onAccountsChanged,
  onToast,
}: AccountManagementDrawerProps) {
  const [data, setData] = useState<AdminAccountsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string>('');
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Draft edits per user id
  const [drafts, setDrafts] = useState<
    Record<string, { role_template: string; permissions: Record<string, boolean>; dirty?: boolean }>
  >({});

  // Create form state
  const [newUsername, setNewUsername] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newNote, setNewNote] = useState('');
  const [newRoleTemplate, setNewRoleTemplate] = useState('payroll_specialist');
  const [newPerms, setNewPerms] = useState<Record<string, boolean>>({});

  // Password reset modal state
  const [resetTarget, setResetTarget] = useState<WorkspaceUser | null>(null);
  const [resetPasswordValue, setResetPasswordValue] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetchAdminAccounts();
      setData(res);
      const nextDrafts: Record<
        string,
        { role_template: string; permissions: Record<string, boolean>; dirty?: boolean }
      > = {};
      for (const u of res.users) {
        nextDrafts[u.id] = {
          role_template: u.role_template || (u.role === 'admin' ? 'admin' : 'payroll_specialist'),
          permissions: { ...(u.permissions || {}) },
          dirty: false,
        };
      }
      setDrafts(nextDrafts);
      if (res.role_templates?.payroll_specialist && Object.keys(newPerms).length === 0) {
        setNewPerms({ ...res.role_templates.payroll_specialist.permissions });
      }
      onAccountsChanged(res.pending_count, res.workspaces);
    } catch (err) {
      onToast(err instanceof Error ? err.message : '加载账户列表失败', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void loadData();
    }
  }, [open]);

  if (!open) return null;

  const templates = data?.role_templates || {};
  const permKeys: PermissionKey[] = data?.permission_keys || [
    'collection',
    'reports',
    'payroll',
    'approval',
    'xiaoxiang_use',
    'benlai_use',
    'shared_auth_manage',
  ];
  const permLabels = data?.permission_labels || ({} as Record<PermissionKey, string>);

  const pendingUsers = (data?.users || []).filter(u => u.status === 'pending');
  const managedUsers = (data?.users || []).filter(u => u.status !== 'pending');

  const updateUserTemplate = (userId: string, tmpl: string) => {
    const preset = templates[tmpl]?.permissions || {};
    setDrafts(prev => ({
      ...prev,
      [userId]: {
        role_template: tmpl,
        permissions: { ...preset },
        dirty: true,
      },
    }));
  };

  const toggleUserPerm = (userId: string, key: PermissionKey) => {
    setDrafts(prev => {
      const current = prev[userId];
      if (!current || current.role_template === 'admin') return prev;
      const nextPerms = { ...current.permissions, [key]: !current.permissions[key] };
      return {
        ...prev,
        [userId]: {
          role_template: 'custom',
          permissions: nextPerms,
          dirty: true,
        },
      };
    });
  };

  const handleApprove = async (u: WorkspaceUser) => {
    const draft = drafts[u.id] || {
      role_template: 'payroll_specialist',
      permissions: templates.payroll_specialist?.permissions || {},
    };
    setBusyId(u.id);
    try {
      const res = await adminApproveAccount(u.id, {
        role_template: draft.role_template,
        permissions: draft.permissions,
      });
      onToast(`已批准 ${u.display_name}，独立空间 ${res.user.workspace_id} 已初始化`, 'success');
      await loadData();
    } catch (err) {
      onToast(err instanceof Error ? err.message : '审批操作失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleReject = async (u: WorkspaceUser) => {
    setBusyId(u.id);
    try {
      await adminRejectAccount(u.id);
      onToast(`已驳回 ${u.display_name} 的申请`, 'info');
      await loadData();
    } catch (err) {
      onToast(err instanceof Error ? err.message : '驳回失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleSavePermissions = async (u: WorkspaceUser) => {
    const draft = drafts[u.id];
    if (!draft) return;
    setBusyId(u.id);
    try {
      await adminUpdateAccount(u.id, {
        role_template: draft.role_template,
        permissions: draft.permissions,
      });
      onToast(`已保存 ${u.display_name} 的角色与模块权限`, 'success');
      await loadData();
    } catch (err) {
      onToast(err instanceof Error ? err.message : '保存权限失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleToggleEnabled = async (u: WorkspaceUser) => {
    setBusyId(u.id);
    try {
      const nextEnabled = !u.enabled;
      await adminUpdateAccount(u.id, { enabled: nextEnabled });
      onToast(nextEnabled ? `已恢复启用 ${u.display_name}` : `已停用 ${u.display_name}`, 'success');
      await loadData();
    } catch (err) {
      onToast(err instanceof Error ? err.message : '更新状态失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusyId('create');
    try {
      const res = await adminCreateAccount({
        username: newUsername.trim(),
        display_name: newDisplayName.trim() || newUsername.trim(),
        password: newPassword,
        role_template: newRoleTemplate,
        permissions: newPerms,
        note: newNote.trim(),
      });
      onToast(`已创建成员 ${res.user.display_name} 并开通独立空间`, 'success');
      setNewUsername('');
      setNewDisplayName('');
      setNewPassword('');
      setNewNote('');
      setShowCreateForm(false);
      await loadData();
    } catch (err) {
      onToast(err instanceof Error ? err.message : '创建账号失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTarget) return;
    setBusyId(resetTarget.id);
    try {
      const res = await adminResetPassword(resetTarget.id, resetPasswordValue);
      onToast(res.message, 'success');
      setResetTarget(null);
      setResetPasswordValue('');
    } catch (err) {
      onToast(err instanceof Error ? err.message : '重置密码失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  const handleSyncConfig = async (u: WorkspaceUser) => {
    setBusyId(u.id);
    try {
      const res = await adminSyncDefaultConfig(u.id);
      onToast(res.message, 'success');
    } catch (err) {
      onToast(err instanceof Error ? err.message : '同步默认配置失败', 'error');
    } finally {
      setBusyId('');
    }
  };

  return (
    <WorkbenchDrawer
      title="账户审批、独立空间与权限管理"
      closeLabel="关闭账户管理"
      onClose={onClose}
    >
      <div className="space-y-5 text-slate-800">
        {/* Top toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200">
          <div className="text-xs text-slate-600">
            小象灯塔、本来人力采用<strong>全局共享连接</strong>；风神、蓝橙、白泽按<strong>个人空间独立登录</strong>。
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowCreateForm(v => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>直接新建成员</span>
            </button>
            <button
              type="button"
              onClick={() => void loadData()}
              disabled={loading}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-xs text-slate-700 cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>刷新</span>
            </button>
          </div>
        </div>

        {/* Direct Create User Form */}
        {showCreateForm && (
          <form
            onSubmit={handleCreateUser}
            className="rounded-xl border border-sky-200 bg-sky-50/50 p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                <UserPlus className="w-4 h-4 text-[#00AEEC]" />
                <span>新建同事账户并立即开通独立空间</span>
              </h3>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <input
                type="text"
                required
                minLength={2}
                placeholder="登录用户名 *"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
              <input
                type="text"
                required
                placeholder="真实姓名/花名 *"
                value={newDisplayName}
                onChange={e => setNewDisplayName(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
              <input
                type="password"
                required
                minLength={6}
                placeholder="初始密码(至少6位) *"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <select
                value={newRoleTemplate}
                onChange={e => {
                  const tmpl = e.target.value;
                  setNewRoleTemplate(tmpl);
                  if (templates[tmpl]) {
                    setNewPerms({ ...templates[tmpl].permissions });
                  }
                }}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              >
                {Object.entries(templates).map(([key, def]) => (
                  <option key={key} value={key}>
                    预设角色：{def.label}
                  </option>
                ))}
              </select>
              <input
                type="text"
                placeholder="备注（如负责城市/岗位，选填）"
                value={newNote}
                onChange={e => setNewNote(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              {permKeys.map(key => {
                const checked = newRoleTemplate === 'admin' ? true : Boolean(newPerms[key]);
                return (
                  <label
                    key={key}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs cursor-pointer select-none ${
                      checked
                        ? 'bg-sky-100/80 border-sky-300 text-sky-900 font-medium'
                        : 'bg-white border-slate-200 text-slate-600'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={newRoleTemplate === 'admin'}
                      onChange={() => {
                        setNewRoleTemplate('custom');
                        setNewPerms(prev => ({ ...prev, [key]: !prev[key] }));
                      }}
                      className="accent-[#00AEEC]"
                    />
                    <span>{permLabels[key] || key}</span>
                  </label>
                );
              })}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="submit"
                disabled={busyId === 'create'}
                className="px-3.5 py-1.5 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold cursor-pointer"
              >
                {busyId === 'create' ? '创建中…' : '确认创建并开通空间'}
              </button>
            </div>
          </form>
        )}

        {/* Password Reset Modal Box */}
        {resetTarget && (
          <form
            onSubmit={handleResetPassword}
            className="rounded-xl border border-amber-300 bg-amber-50/90 p-3.5 space-y-2.5"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-900">
                重置【{resetTarget.display_name} ({resetTarget.username})】的登录密码
              </span>
              <button
                type="button"
                onClick={() => {
                  setResetTarget(null);
                  setResetPasswordValue('');
                }}
                className="text-slate-500 hover:text-slate-800 text-xs cursor-pointer"
              >
                取消
              </button>
            </div>
            <div className="flex gap-2">
              <input
                type="password"
                required
                minLength={6}
                value={resetPasswordValue}
                onChange={e => setResetPasswordValue(e.target.value)}
                placeholder="输入新密码（至少6位）"
                className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
              />
              <button
                type="submit"
                disabled={busyId === resetTarget.id}
                className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold cursor-pointer"
              >
                确认重置
              </button>
            </div>
          </form>
        )}

        {/* Pending Approvals Section */}
        {pendingUsers.length > 0 && (
          <section className="space-y-2.5">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs font-bold">
                待审批 ({pendingUsers.length})
              </span>
              <span className="text-xs text-slate-500">
                勾选授权模块后点击批准，系统将自动为其创建独立工作空间并复制标准默认扣款表
              </span>
            </div>

            <div className="space-y-3">
              {pendingUsers.map(u => {
                const draft = drafts[u.id] || {
                  role_template: 'payroll_specialist',
                  permissions: templates.payroll_specialist?.permissions || {},
                };
                return (
                  <div
                    key={u.id}
                    className="rounded-xl border border-amber-300 bg-amber-50/40 p-3.5 space-y-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">
                          {u.display_name}{' '}
                          <span className="text-xs font-normal text-slate-500">@{u.username}</span>
                        </div>
                        {u.note && (
                          <div className="text-xs text-slate-600 mt-0.5">申请说明：{u.note}</div>
                        )}
                      </div>

                      <div className="flex items-center gap-2">
                        <select
                          value={draft.role_template}
                          onChange={e => updateUserTemplate(u.id, e.target.value)}
                          className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs"
                        >
                          {Object.entries(templates).map(([key, def]) => (
                            <option key={key} value={key}>
                              {def.label}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void handleApprove(u)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold cursor-pointer"
                        >
                          <UserCheck className="w-3.5 h-3.5" />
                          <span>批准并开通空间</span>
                        </button>
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void handleReject(u)}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-rose-200 bg-white hover:bg-rose-50 text-rose-600 text-xs cursor-pointer"
                        >
                          <UserX className="w-3.5 h-3.5" />
                          <span>驳回</span>
                        </button>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {permKeys.map(key => {
                        const checked =
                          draft.role_template === 'admin' ? true : Boolean(draft.permissions[key]);
                        return (
                          <label
                            key={key}
                            className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] cursor-pointer select-none ${
                              checked
                                ? 'bg-emerald-50 border-emerald-300 text-emerald-900 font-medium'
                                : 'bg-white border-slate-200 text-slate-500'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={draft.role_template === 'admin'}
                              onChange={() => toggleUserPerm(u.id, key)}
                              className="accent-emerald-600"
                            />
                            <span>{permLabels[key] || key}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Active & Managed Accounts Section */}
        <section className="space-y-2.5">
          <div className="text-xs font-semibold text-slate-700">
            已开通与历史成员 ({managedUsers.length})
          </div>

          <div className="space-y-3">
            {managedUsers.map(u => {
              const draft = drafts[u.id] || {
                role_template: u.role_template,
                permissions: u.permissions || {},
                dirty: false,
              };
              const isSelf = u.id === currentUserId;
              const isPrimarySpace = u.workspace_id === 'download_shared';

              return (
                <div
                  key={u.id}
                  className={`rounded-xl border p-3.5 space-y-2.5 ${
                    u.enabled
                      ? 'border-slate-200 bg-white'
                      : 'border-slate-200 bg-slate-50/80 opacity-80'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-slate-900">{u.display_name}</span>
                      <span className="text-xs text-slate-500">@{u.username}</span>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          u.role === 'admin'
                            ? 'bg-sky-100 text-sky-800'
                            : 'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {u.role === 'admin'
                          ? '管理员'
                          : templates[u.role_template]?.label || '成员'}
                      </span>
                      <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 text-[11px] font-mono">
                        {isPrimarySpace ? '主空间 (download_shared)' : `独立空间 (${u.workspace_id})`}
                      </span>
                      {!u.enabled && (
                        <span className="px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 text-[11px]">
                          {u.status === 'rejected' ? '已驳回' : '已停用'}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      {u.status !== 'rejected' && (
                        <button
                          type="button"
                          onClick={() => {
                            onInspectWorkspace(isPrimarySpace ? '' : u.workspace_id);
                            onClose();
                          }}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-sky-200 bg-sky-50 hover:bg-sky-100 text-sky-800 text-xs font-medium cursor-pointer"
                          title="切换到该成员的工作空间协助查看任务与配置"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>{isPrimarySpace ? '进入主空间' : '巡检空间'}</span>
                        </button>
                      )}

                      {!isPrimarySpace && u.enabled && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void handleSyncConfig(u)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs cursor-pointer"
                          title="将管理员主空间最新的标准扣款配置表覆盖同步到该成员空间（原配置自动备份）"
                        >
                          <SlidersHorizontal className="w-3 h-3" />
                          <span>同步标准扣款表</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => {
                          setResetTarget(u);
                          setResetPasswordValue('');
                        }}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs cursor-pointer"
                      >
                        <KeyRound className="w-3 h-3" />
                        <span>改密</span>
                      </button>

                      {!isSelf && (
                        <button
                          type="button"
                          disabled={busyId === u.id}
                          onClick={() => void handleToggleEnabled(u)}
                          className={`px-2.5 py-1 rounded-lg border text-xs cursor-pointer ${
                            u.enabled
                              ? 'border-rose-200 text-rose-600 hover:bg-rose-50'
                              : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50'
                          }`}
                        >
                          {u.enabled ? '停用' : '启用'}
                        </button>
                      )}
                    </div>
                  </div>

                  {u.note && <div className="text-xs text-slate-500">备注：{u.note}</div>}

                  {/* Role & Permissions Editor */}
                  <div className="pt-1.5 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <select
                        value={draft.role_template}
                        disabled={isSelf && u.role === 'admin'}
                        onChange={e => updateUserTemplate(u.id, e.target.value)}
                        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs mr-1"
                      >
                        {Object.entries(templates).map(([key, def]) => (
                          <option key={key} value={key}>
                            {def.label}
                          </option>
                        ))}
                      </select>

                      {permKeys.map(key => {
                        const checked =
                          draft.role_template === 'admin' ? true : Boolean(draft.permissions[key]);
                        return (
                          <label
                            key={key}
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] cursor-pointer select-none ${
                              checked
                                ? 'bg-sky-50 border-sky-200 text-sky-900 font-medium'
                                : 'bg-white border-slate-200 text-slate-400'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={draft.role_template === 'admin'}
                              onChange={() => toggleUserPerm(u.id, key)}
                              className="accent-[#00AEEC]"
                            />
                            <span>{permLabels[key] || key}</span>
                          </label>
                        );
                      })}
                    </div>

                    {draft.dirty && (
                      <button
                        type="button"
                        disabled={busyId === u.id}
                        onClick={() => void handleSavePermissions(u)}
                        className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold cursor-pointer"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>保存权限修改</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </WorkbenchDrawer>
  );
}
