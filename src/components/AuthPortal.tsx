import React, { useState } from 'react';
import {
  CheckCircle2,
  KeyRound,
  Lock,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  UserPlus,
  Users,
} from 'lucide-react';
import { BrandLogo } from './BrandLogo';
import {
  bootstrapHostAdmin,
  loginWorkspaceAccount,
  registerWorkspaceAccount,
  type WorkspaceSessionState,
} from '../lib/workspaceAuth';

interface AuthPortalProps {
  session: WorkspaceSessionState;
  onAuthenticated: (nextSession: WorkspaceSessionState) => void;
  onRefreshSession: () => Promise<void>;
}

export function AuthPortal({ session, onAuthenticated, onRefreshSession }: AuthPortalProps) {
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [registerDoneMsg, setRegisterDoneMsg] = useState('');

  const handleBootstrap = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('两次输入的管理员密码不一致');
      return;
    }
    setBusy(true);
    try {
      const next = await bootstrapHostAdmin({
        username: username.trim(),
        display_name: displayName.trim() || username.trim(),
        password,
      });
      onAuthenticated(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : '初始化失败，请重试');
    } finally {
      setBusy(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const next = await loginWorkspaceAccount({
        username: username.trim(),
        password,
      });
      onAuthenticated(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请检查用户名与密码');
    } finally {
      setBusy(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    setBusy(true);
    try {
      const res = await registerWorkspaceAccount({
        username: username.trim(),
        display_name: displayName.trim() || username.trim(),
        password,
        note: note.trim(),
      });
      setRegisterDoneMsg(res.message);
      setPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册提交失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center px-4 py-10 bg-[#F6F7F8] text-[#18191C]">
      <div className="w-full max-w-[440px]">
        {/* Brand Header */}
        <div className="flex flex-col items-center mb-6 text-center">
          <div className="mb-3">
            <BrandLogo collapsed={false} />
          </div>
          <p className="text-xs text-[#61666D]">
            多账号独立工作空间 · 薪酬核算与多平台采集协同平台
          </p>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200/90 shadow-sm p-6 sm:p-7">
          {!session.initialized ? (
            session.bootstrap_allowed ? (
              <form onSubmit={handleBootstrap} className="space-y-4">
                <div className="flex items-start gap-3 p-3.5 rounded-xl bg-sky-50/90 border border-sky-200/70">
                  <ShieldCheck className="w-5 h-5 text-[#00AEEC] shrink-0 mt-0.5" />
                  <div className="text-xs leading-relaxed text-slate-700">
                    <div className="font-semibold text-slate-900 mb-0.5">首次启动：初始化主机管理员</div>
                    本机现有的扣款配置、历史核算记录与平台会话将自动归入管理员主空间。初始化完成后，局域网同事即可访问本机地址注册各自的独立空间。
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    管理员登录账号 <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    minLength={2}
                    maxLength={40}
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="如 admin 或您的拼音工号"
                    className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    管理员显示姓名
                  </label>
                  <input
                    type="text"
                    maxLength={40}
                    value={displayName}
                    onChange={e => setDisplayName(e.target.value)}
                    placeholder="如 张三（主机管理员）"
                    className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      登录密码（至少6位） <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="password"
                      required
                      minLength={6}
                      maxLength={128}
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="设置密码"
                      className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      确认密码 <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="password"
                      required
                      minLength={6}
                      maxLength={128}
                      value={confirmPassword}
                      onChange={e => setConfirmPassword(e.target.value)}
                      placeholder="再次输入密码"
                      className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                    />
                  </div>
                </div>

                {error && (
                  <div
                    role="alert"
                    className="rounded-xl bg-rose-50 border border-rose-200 px-3.5 py-2.5 text-xs text-rose-700"
                  >
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={busy}
                  className="w-full py-2.5 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] disabled:opacity-60 text-white text-sm font-semibold transition cursor-pointer flex items-center justify-center gap-2"
                >
                  <ShieldCheck className="w-4 h-4" />
                  <span>{busy ? '正在初始化主空间…' : '创建主机管理员并进入工作台'}</span>
                </button>
              </form>
            ) : (
              <div className="space-y-4 text-center py-4">
                <div className="w-12 h-12 rounded-2xl bg-amber-50 border border-amber-200 text-amber-600 flex items-center justify-center mx-auto">
                  <Lock className="w-6 h-6" />
                </div>
                <div className="space-y-1.5">
                  <h2 className="text-base font-semibold text-slate-900">等待主机管理员完成初始化</h2>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    系统首次运行需要由管理员在运行服务的主机电脑上创建首个超级管理员账号。完成后您即可在此页面注册并申请专属独立空间。
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void onRefreshSession()}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-300 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>刷新初始化状态</span>
                </button>
              </div>
            )
          ) : (
            <>
              {/* Segmented Tabs */}
              <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-100 mb-5">
                <button
                  type="button"
                  onClick={() => {
                    setTab('login');
                    setError('');
                    setRegisterDoneMsg('');
                  }}
                  className={`py-2 text-xs font-semibold rounded-lg transition cursor-pointer flex items-center justify-center gap-1.5 ${
                    tab === 'login'
                      ? 'bg-white text-slate-900 shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <KeyRound className="w-3.5 h-3.5" />
                  <span>空间登录</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setTab('register');
                    setError('');
                  }}
                  className={`py-2 text-xs font-semibold rounded-lg transition cursor-pointer flex items-center justify-center gap-1.5 ${
                    tab === 'register'
                      ? 'bg-white text-slate-900 shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>同事注册申请</span>
                </button>
              </div>

              {tab === 'login' ? (
                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      登录用户名
                    </label>
                    <input
                      type="text"
                      required
                      autoFocus
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      placeholder="请输入您的用户名"
                      className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      登录密码
                    </label>
                    <input
                      type="password"
                      required
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      placeholder="请输入登录密码"
                      className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#00AEEC] focus:ring-2 focus:ring-[#00AEEC]/15"
                    />
                  </div>

                  {error && (
                    <div
                      role="alert"
                      className="rounded-xl bg-rose-50 border border-rose-200 px-3.5 py-2.5 text-xs text-rose-700 leading-relaxed"
                    >
                      {error}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={busy}
                    className="w-full py-2.5 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] disabled:opacity-60 text-white text-sm font-semibold transition cursor-pointer flex items-center justify-center gap-2"
                  >
                    <UserCheck className="w-4 h-4" />
                    <span>{busy ? '正在验证并进入空间…' : '登录我的独立空间'}</span>
                  </button>

                  <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
                    <span>每位成员拥有独立的配置、批次与平台账号</span>
                    <button
                      type="button"
                      onClick={() => {
                        setTab('register');
                        setError('');
                      }}
                      className="text-[#00AEEC] hover:underline font-medium cursor-pointer"
                    >
                      首次使用？提交申请
                    </button>
                  </div>
                </form>
              ) : registerDoneMsg ? (
                <div className="space-y-4 py-3 text-center">
                  <div className="w-12 h-12 rounded-2xl bg-emerald-50 border border-emerald-200 text-emerald-600 flex items-center justify-center mx-auto">
                    <CheckCircle2 className="w-6 h-6" />
                  </div>
                  <div className="space-y-1.5">
                    <h3 className="text-sm font-semibold text-slate-900">注册申请已提交</h3>
                    <p className="text-xs text-slate-600 leading-relaxed">{registerDoneMsg}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setRegisterDoneMsg('');
                      setTab('login');
                    }}
                    className="w-full py-2.5 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] text-white text-xs font-semibold cursor-pointer"
                  >
                    返回登录页
                  </button>
                </div>
              ) : (
                <form onSubmit={handleRegister} className="space-y-3.5">
                  <div className="rounded-xl bg-slate-50 border border-slate-200/80 px-3.5 py-2.5 text-xs text-slate-600 leading-relaxed flex items-start gap-2">
                    <Users className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                    <span>
                      提交申请后将由管理员审批并分配功能权限；开通后系统自动为您初始化专属工作空间及标准扣款配置。
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        登录用户名 <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="text"
                        required
                        minLength={2}
                        maxLength={40}
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        placeholder="如 zhangsan"
                        className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-[#00AEEC]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        真实姓名 / 花名 <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="text"
                        required
                        maxLength={40}
                        value={displayName}
                        onChange={e => setDisplayName(e.target.value)}
                        placeholder="如 张三"
                        className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-[#00AEEC]"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        设置密码（至少6位） <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="password"
                        required
                        minLength={6}
                        maxLength={128}
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        placeholder="至少6位字符"
                        className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-[#00AEEC]"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        确认密码 <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="password"
                        required
                        minLength={6}
                        maxLength={128}
                        value={confirmPassword}
                        onChange={e => setConfirmPassword(e.target.value)}
                        placeholder="再次输入密码"
                        className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-[#00AEEC]"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      负责城市 / 岗位说明（选填，便于管理员分配权限）
                    </label>
                    <input
                      type="text"
                      maxLength={120}
                      value={note}
                      onChange={e => setNote(e.target.value)}
                      placeholder="如：深圳/广州兼职核算、蓝橙价格审批"
                      className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-[#00AEEC]"
                    />
                  </div>

                  {error && (
                    <div
                      role="alert"
                      className="rounded-xl bg-rose-50 border border-rose-200 px-3.5 py-2.5 text-xs text-rose-700"
                    >
                      {error}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={busy}
                    className="w-full py-2.5 px-4 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] disabled:opacity-60 text-white text-sm font-semibold transition cursor-pointer flex items-center justify-center gap-2"
                  >
                    <UserPlus className="w-4 h-4" />
                    <span>{busy ? '正在提交申请…' : '提交注册并申请独立空间'}</span>
                  </button>
                </form>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
