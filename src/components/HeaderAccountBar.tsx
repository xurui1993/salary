import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowLeftRight,
  ChevronDown,
  Eye,
  KeyRound,
  LogOut,
  Shield,
  Users,
  X,
} from 'lucide-react';
import {
  changeOwnPassword,
  type WorkspaceDirectoryEntry,
  type WorkspaceUser,
} from '../lib/workspaceAuth';

interface HeaderAccountBarProps {
  user: WorkspaceUser;
  workspaces: WorkspaceDirectoryEntry[];
  pendingCount: number;
  onSwitchWorkspace: (workspaceId: string) => Promise<void>;
  onOpenAdminAccounts: () => void;
  onLogout: () => Promise<void>;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export function HeaderAccountBar({
  user,
  workspaces,
  pendingCount,
  onSwitchWorkspace,
  onOpenAdminAccounts,
  onLogout,
  onToast,
}: HeaderAccountBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [pwModalOpen, setPwModalOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [menuOpen]);

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      onToast('两次输入的新密码不一致', 'error');
      return;
    }
    setBusy(true);
    try {
      await changeOwnPassword({ current_password: currentPassword, new_password: newPassword });
      onToast('个人登录密码修改成功', 'success');
      setPwModalOpen(false);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      onToast(err instanceof Error ? err.message : '修改密码失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="flex items-center gap-2">
        {/* Admin Cross-Workspace Switcher */}
        {user.role === 'admin' && workspaces.length > 1 && (
          <div className="hidden md:flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50/90 px-2.5 py-1 text-xs">
            <ArrowLeftRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
            <select
              aria-label="跨空间巡检切换"
              value={user.inspecting ? user.effective_workspace : user.workspace_id}
              onChange={e => {
                const target = e.target.value;
                void onSwitchWorkspace(target === user.workspace_id ? '' : target);
              }}
              className="bg-transparent text-xs font-medium text-slate-800 focus:outline-none cursor-pointer max-w-[170px]"
            >
              {workspaces.map(ws => (
                <option key={ws.workspace_id} value={ws.workspace_id}>
                  {ws.is_primary
                    ? `主空间 · ${ws.display_name}`
                    : `空间 · ${ws.display_name} (@${ws.username})`}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Admin Account & Permission Management Button */}
        {user.role === 'admin' && (
          <button
            type="button"
            onClick={onOpenAdminAccounts}
            className="relative inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-700 transition cursor-pointer"
            title="管理成员账号、审批注册申请与分配模块权限"
          >
            <Users className="w-3.5 h-3.5 text-[#00AEEC]" />
            <span className="hidden sm:inline">账户权限</span>
            {pendingCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold">
                {pendingCount}
              </span>
            )}
          </button>
        )}

        {/* Current User Identity Menu */}
        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen(v => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-800 transition cursor-pointer"
          >
            <span className="w-5 h-5 rounded-full bg-[#00AEEC]/15 text-[#00AEEC] font-bold flex items-center justify-center text-[11px]">
              {(user.display_name || user.username).slice(0, 1).toUpperCase()}
            </span>
            <span className="max-w-[96px] truncate">{user.display_name}</span>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 mt-1.5 w-56 rounded-xl bg-white border border-slate-200 shadow-lg p-2 z-50 space-y-1">
              <div className="px-2.5 py-2 border-b border-slate-100">
                <div className="text-xs font-semibold text-slate-900 truncate">
                  {user.display_name}{' '}
                  <span className="text-slate-400 font-normal">@{user.username}</span>
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-1">
                  <Shield className="w-3 h-3 text-[#00AEEC]" />
                  <span>
                    {user.role === 'admin' ? '系统管理员' : '独立空间成员'} ·{' '}
                    {user.workspace_id === 'download_shared' ? '主空间' : user.workspace_id}
                  </span>
                </div>
              </div>

              {user.role === 'admin' && (
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    onOpenAdminAccounts();
                  }}
                  className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg hover:bg-slate-50 text-xs text-slate-700 cursor-pointer"
                >
                  <span className="flex items-center gap-2">
                    <Users className="w-3.5 h-3.5 text-slate-500" />
                    <span>账户审批与权限分配</span>
                  </span>
                  {pendingCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-bold">
                      {pendingCount}
                    </span>
                  )}
                </button>
              )}

              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  setPwModalOpen(true);
                }}
                className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-slate-50 text-xs text-slate-700 cursor-pointer"
              >
                <KeyRound className="w-3.5 h-3.5 text-slate-500" />
                <span>修改我的密码</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  void onLogout();
                }}
                className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-rose-50 text-xs text-rose-600 cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>退出登录</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Self Password Change Modal */}
      {pwModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/35 flex items-center justify-center p-4">
          <form
            onSubmit={handlePasswordSubmit}
            className="w-full max-w-sm rounded-2xl bg-white border border-slate-200 shadow-xl p-5 space-y-3.5"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">修改个人登录密码</h3>
              <button
                type="button"
                onClick={() => setPwModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div>
              <label className="block text-xs text-slate-600 mb-1">当前原密码</label>
              <input
                type="password"
                required
                value={currentPassword}
                onChange={e => setCurrentPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-600 mb-1">新密码（至少6位）</label>
              <input
                type="password"
                required
                minLength={6}
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-600 mb-1">确认新密码</label>
              <input
                type="password"
                required
                minLength={6}
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setPwModalOpen(false)}
                className="px-3.5 py-1.5 rounded-xl border border-slate-300 text-xs text-slate-700 cursor-pointer"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={busy}
                className="px-4 py-1.5 rounded-xl bg-[#00AEEC] text-white text-xs font-semibold cursor-pointer"
              >
                {busy ? '保存中…' : '保存新密码'}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}

export function WorkspaceInspectBanner({
  user,
  onExitInspect,
}: {
  user: WorkspaceUser;
  onExitInspect: () => void;
}) {
  if (!user.inspecting || !user.inspect_target) return null;
  return (
    <div
      role="status"
      className="mb-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-950"
    >
      <div className="flex items-center gap-2">
        <Eye className="w-4 h-4 text-amber-600 shrink-0" />
        <span>
          <strong>跨空间巡检模式：</strong>当前正在查看并协助成员
          <strong className="mx-1">
            {user.inspect_target.display_name} (@{user.inspect_target.username})
          </strong>
          的独立工作空间（空间编号：<code className="font-mono">{user.effective_workspace}</code>）
        </span>
      </div>
      <button
        type="button"
        onClick={onExitInspect}
        className="px-3 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold cursor-pointer"
      >
        退出巡检 · 返回我的主空间
      </button>
    </div>
  );
}
