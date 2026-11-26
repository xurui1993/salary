import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeftRight,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  KeyRound,
  Lock,
  LogOut,
  Search,
  ShieldCheck,
  User,
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
  onSwitchWorkspace: (workspaceId: string) => Promise<void>;
  onLogout: () => Promise<void>;
  onToast: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export function HeaderAccountBar({
  user,
  workspaces,
  onSwitchWorkspace,
  onLogout,
  onToast,
}: HeaderAccountBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [wsFilter, setWsFilter] = useState('');
  const [pwModalOpen, setPwModalOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [switchingWid, setSwitchingWid] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!pwModalOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) setPwModalOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [pwModalOpen, busy]);

  const openPasswordModal = () => {
    setMenuOpen(false);
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setShowCurrentPw(false);
    setShowNewPw(false);
    setPwModalOpen(true);
  };

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

  const handleSelectWorkspace = async (ws: WorkspaceDirectoryEntry) => {
    const activeWid = user.inspecting ? user.effective_workspace : user.workspace_id;
    if (ws.workspace_id === activeWid) {
      setMenuOpen(false);
      return;
    }
    setSwitchingWid(ws.workspace_id);
    try {
      await onSwitchWorkspace(ws.workspace_id === user.workspace_id ? '' : ws.workspace_id);
      setMenuOpen(false);
    } finally {
      setSwitchingWid(null);
    }
  };

  const activeWorkspaceId = user.inspecting ? user.effective_workspace : user.workspace_id;
  const filteredWorkspaces = workspaces.filter(ws => {
    const q = wsFilter.trim().toLowerCase();
    if (!q) return true;
    return `${ws.display_name} ${ws.username} ${ws.workspace_id}`.toLowerCase().includes(q);
  });
  const pwLenOk = newPassword.length >= 6;
  const pwMatchOk = Boolean(newPassword && confirmPassword && newPassword === confirmPassword);
  const pwMismatch = Boolean(confirmPassword && newPassword !== confirmPassword);

  return (
    <>
      <div className="flex items-center shrink-0">
        {/* 个人账户触发器 + 集成跨空间巡检的毛玻璃下拉面板 */}
        <div ref={menuRef} className="relative">
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title={`${user.display_name}${user.inspecting && user.inspect_target ? ` · 正在巡检 ${user.inspect_target.display_name}` : ''}`}
            onClick={() => {
              setWsFilter('');
              setMenuOpen(v => !v);
            }}
            className={`inline-flex items-center gap-2 h-8 rounded-[10px] border px-3 text-xs font-medium transition duration-150 cursor-pointer whitespace-nowrap shrink-0 ${
              user.inspecting
                ? 'border-amber-300/90 bg-amber-50/90 hover:bg-amber-50 text-amber-950'
                : 'border-slate-200/90 bg-white/85 hover:bg-white text-[#18191C]'
            }`}
          >
            <User
              className={`w-3.5 h-3.5 shrink-0 ${
                user.inspecting ? 'text-amber-600' : 'text-[#61666D]'
              }`}
            />
            <span className="max-w-[128px] truncate">{user.display_name}</span>
            {user.inspecting && (
              <span className="hidden md:inline text-[11px] font-semibold text-amber-700">
                巡检中
              </span>
            )}
            <ChevronDown
              className={`w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform duration-150 ${
                menuOpen ? 'rotate-180' : ''
              }`}
            />
          </button>

          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-[264px] rounded-2xl bg-white/96 backdrop-blur-xl border border-slate-200/90 shadow-[0_18px_40px_-14px_rgba(15,23,42,0.18)] p-2 z-50"
            >
              {/* 当前登录身份摘要（点击用户名直接修改个人密码） */}
              <div className="pb-1.5 mb-1 border-b border-slate-100">
                <button
                  type="button"
                  role="menuitem"
                  title="点击修改个人登录密码"
                  onClick={openPasswordModal}
                  className="w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-xl hover:bg-sky-50/75 transition cursor-pointer group"
                >
                  <span className="text-[13px] font-semibold text-[#18191C] group-hover:text-[#008EC4] truncate transition-colors">
                    {user.display_name}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#61666D] group-hover:text-[#008EC4] shrink-0 transition-colors">
                    <KeyRound className="w-3 h-3" />
                    <span>修改密码</span>
                  </span>
                </button>
              </div>

              {/* 管理员专属：跨空间巡检快速切换区 */}
              {user.role === 'admin' && workspaces.length > 1 && (
                <div className="py-2 border-b border-slate-100">
                  <div className="px-2.5 pb-1.5 flex items-center justify-between text-[11px] font-medium text-[#61666D]">
                    <span className="flex items-center gap-1.5">
                      <ArrowLeftRight className="w-3 h-3 text-[#00AEEC]" />
                      <span>切换成员空间</span>
                    </span>
                    <span className="tabular-nums text-slate-400">{workspaces.length}</span>
                  </div>

                  {workspaces.length > 5 && (
                    <div className="px-2 pb-1.5">
                      <div className="relative">
                        <Search className="w-3 h-3 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                        <input
                          type="text"
                          value={wsFilter}
                          onChange={e => setWsFilter(e.target.value)}
                          placeholder="搜索成员姓名…"
                          className="w-full rounded-lg border border-slate-200 bg-slate-50/80 pl-7 pr-2.5 py-1 text-[11px] text-[#18191C] placeholder:text-slate-400 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:bg-white"
                        />
                      </div>
                    </div>
                  )}

                  <div className="max-h-60 overflow-y-auto space-y-0.5 px-0.5">
                    {filteredWorkspaces.map(ws => {
                      const isCurrent = ws.workspace_id === activeWorkspaceId;
                      const isLoading = switchingWid === ws.workspace_id;
                      return (
                        <button
                          key={ws.workspace_id}
                          type="button"
                          disabled={Boolean(switchingWid)}
                          onClick={() => void handleSelectWorkspace(ws)}
                          className={`w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg text-left text-xs transition cursor-pointer ${
                            isCurrent
                              ? 'bg-[#00AEEC]/10 text-[#008EC4] font-semibold'
                              : 'text-[#4E5969] hover:bg-slate-50 hover:text-[#18191C]'
                          }`}
                        >
                          <span className="truncate">
                            {ws.is_primary ? `${ws.display_name}（主空间）` : ws.display_name}
                          </span>
                          {isLoading ? (
                            <span className="text-[10px] text-[#00AEEC] shrink-0">切换中…</span>
                          ) : isCurrent ? (
                            <Check className="w-3.5 h-3.5 text-[#00AEEC] shrink-0" />
                          ) : null}
                        </button>
                      );
                    })}
                    {filteredWorkspaces.length === 0 && (
                      <div className="px-2.5 py-2 text-[11px] text-slate-400 text-center">
                        未找到匹配的成员空间
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 常用账户操作 */}
              <div className="pt-1 space-y-0.5">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    void onLogout();
                  }}
                  className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-rose-50 text-xs text-rose-600 transition cursor-pointer"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>退出当前账号</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 修改个人密码弹窗（通过 Portal 挂载至 body，彻底脱离顶栏 backdrop-filter 裁切） */}
      {pwModalOpen &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            className="fixed inset-0 z-[70] bg-slate-900/30 backdrop-blur-[3px] flex items-center justify-center p-4"
            onMouseDown={e => {
              if (e.target === e.currentTarget && !busy) setPwModalOpen(false);
            }}
          >
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="self-pw-title"
            onSubmit={handlePasswordSubmit}
            className="w-full max-w-[424px] rounded-[22px] bg-white border border-slate-200/85 shadow-[0_24px_64px_-20px_rgba(15,23,42,0.24)] overflow-hidden"
          >
            {/* 顶部品牌化安全标头 */}
            <div className="px-6 py-4 bg-gradient-to-b from-[#FAFBFD] to-white border-b border-slate-100 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-9 h-9 rounded-xl bg-sky-50 border border-[#00AEEC]/15 text-[#008EC4] flex items-center justify-center shrink-0">
                  <KeyRound className="w-4 h-4" />
                </span>
                <div className="min-w-0">
                  <h3 id="self-pw-title" className="text-[15px] font-semibold text-[#18191C]">
                    修改登录密码
                  </h3>
                  <p className="text-[12px] text-[#757A82] mt-0.5 truncate">
                    {user.display_name} · 保存后将立即生效
                  </p>
                </div>
              </div>
              <button
                type="button"
                aria-label="关闭弹窗"
                onClick={() => setPwModalOpen(false)}
                className="w-8 h-8 rounded-xl inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 transition cursor-pointer shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 统一细线分隔表单卡 */}
            <div className="p-5 bg-[#FAFBFD]/55 space-y-3.5">
              <div className="rounded-2xl border border-slate-200/80 bg-white overflow-hidden divide-y divide-slate-100 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
                {/* 当前密码 */}
                <label className="flex items-center gap-3 px-4 py-3 focus-within:bg-sky-50/35 transition-colors cursor-text">
                  <span className="w-8 h-8 rounded-[10px] bg-slate-100/85 text-[#61666D] flex items-center justify-center shrink-0">
                    <Lock className="w-4 h-4" />
                  </span>
                  <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                    原密码
                  </span>
                  <input
                    type={showCurrentPw ? 'text' : 'password'}
                    required
                    autoFocus
                    data-custom-focus="true"
                    autoComplete="current-password"
                    value={currentPassword}
                    onChange={e => setCurrentPassword(e.target.value)}
                    placeholder="输入当前使用的密码"
                    className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPw(v => !v)}
                    aria-label={showCurrentPw ? '隐藏当前密码' : '显示当前密码'}
                    className="w-7 h-7 rounded-lg inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100/80 transition cursor-pointer shrink-0"
                  >
                    {showCurrentPw ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </label>

                {/* 新密码 */}
                <label className="flex items-center gap-3 px-4 py-3 focus-within:bg-sky-50/45 transition-colors cursor-text">
                  <span className="w-8 h-8 rounded-[10px] bg-sky-50 text-[#008EC4] flex items-center justify-center shrink-0">
                    <KeyRound className="w-4 h-4" />
                  </span>
                  <span className="w-16 shrink-0 text-[12.5px] font-medium text-[#4E5969]">
                    新密码
                  </span>
                  <input
                    type={showNewPw ? 'text' : 'password'}
                    required
                    minLength={6}
                    data-custom-focus="true"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    placeholder="至少 6 位字符"
                    className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPw(v => !v)}
                    aria-label={showNewPw ? '隐藏新密码' : '显示新密码'}
                    className="w-7 h-7 rounded-lg inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100/80 transition cursor-pointer shrink-0"
                  >
                    {showNewPw ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </label>

                {/* 确认新密码 */}
                <label className="flex items-center gap-3 px-4 py-3 focus-within:bg-sky-50/45 transition-colors cursor-text">
                  <span
                    className={`w-8 h-8 rounded-[10px] flex items-center justify-center shrink-0 transition-colors ${
                      pwMatchOk
                        ? 'bg-emerald-50 text-emerald-600'
                        : pwMismatch
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
                    type={showNewPw ? 'text' : 'password'}
                    required
                    minLength={6}
                    data-custom-focus="true"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={e => setConfirmPassword(e.target.value)}
                    placeholder="再次输入新密码"
                    className="flex-1 min-w-0 bg-transparent text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] focus:outline-none focus-visible:outline-none"
                  />
                </label>
              </div>

              {/* 实时校验条 */}
              <div className="flex items-center justify-between px-1 text-[11.5px]">
                <span className={pwLenOk ? 'text-emerald-600 font-medium' : 'text-[#9499A0]'}>
                  {pwLenOk ? '✓ 密码长度已达标' : '长度需不少于 6 位字符'}
                </span>
                {pwMismatch ? (
                  <span className="text-rose-600 font-medium">两次输入不一致</span>
                ) : pwMatchOk ? (
                  <span className="text-emerald-600 font-medium">✓ 确认一致</span>
                ) : null}
              </div>
            </div>

            <div className="px-6 py-4 bg-white border-t border-slate-100 flex justify-end gap-2.5">
              <button
                type="button"
                disabled={busy}
                onClick={() => setPwModalOpen(false)}
                className="h-9 px-4 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#4E5969] transition cursor-pointer"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={busy || pwMismatch || !pwLenOk || !currentPassword}
                className="h-9 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] disabled:opacity-50 text-white text-xs font-semibold shadow-[0_8px_18px_-10px_rgba(0,174,236,0.85)] transition cursor-pointer"
              >
                {busy ? '正在保存…' : '保存新密码'}
              </button>
            </div>
          </form>
        </div>,
          document.body,
        )}
    </>
  );
}

export function WorkspaceInspectBanner({
  user,
  workspaces = [],
  onSwitchWorkspace,
  onExitInspect,
}: {
  user: WorkspaceUser;
  workspaces?: WorkspaceDirectoryEntry[];
  onSwitchWorkspace?: (workspaceId: string) => void;
  onExitInspect: () => void;
}) {
  if (!user.inspecting || !user.inspect_target) return null;
  const otherWorkspaces = workspaces.filter(ws => !ws.is_primary);
  const showHandle =
    user.inspect_target.username &&
    user.inspect_target.username !== user.inspect_target.display_name;
  return (
    <div
      role="status"
      className="mb-3 rounded-xl border border-amber-200/90 bg-amber-50/88 backdrop-blur-sm px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs text-amber-950"
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="w-6 h-6 rounded-lg bg-amber-500/15 text-amber-700 flex items-center justify-center shrink-0">
          <Eye className="w-3.5 h-3.5" />
        </span>
        <div className="min-w-0 leading-relaxed">
          <span className="font-semibold">正在跨空间巡检</span>
          <span className="mx-1.5 text-amber-700/60" aria-hidden="true">·</span>
          <span className="font-semibold text-[#18191C]">
            {user.inspect_target.display_name}
          </span>
          {showHandle && (
            <span className="ml-1 text-amber-900/75 font-mono text-[11px]">
              @{user.inspect_target.username}
            </span>
          )}
          <span
            className="hidden md:inline text-amber-900/70 ml-2"
            title={`空间编号：${user.effective_workspace}`}
          >
            （所有任务、配置与文件均作用于该成员独立空间）
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {onSwitchWorkspace && otherWorkspaces.length > 1 && (
          <select
            aria-label="快速切换巡检成员空间"
            value={user.effective_workspace}
            onChange={e => onSwitchWorkspace(e.target.value)}
            className="h-7 rounded-lg border border-amber-300/80 bg-white/90 px-2 text-xs text-[#18191C] focus:outline-none focus-visible:outline-none focus:border-amber-500 cursor-pointer"
          >
            {otherWorkspaces.map(ws => (
              <option key={ws.workspace_id} value={ws.workspace_id}>
                切换：{ws.display_name}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          onClick={onExitInspect}
          className="h-7 px-3 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition cursor-pointer whitespace-nowrap"
        >
          退出巡检 · 返回主空间
        </button>
      </div>
    </div>
  );
}
