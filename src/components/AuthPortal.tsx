import React, { useState } from 'react';
import {
  Eye,
  EyeOff,
  Lock,
  RefreshCw,
  User,
} from 'lucide-react';
import { BrandLogo } from './BrandLogo';
import {
  bootstrapHostAdmin,
  loginWorkspaceAccount,
  type WorkspaceSessionState,
} from '../lib/workspaceAuth';

interface AuthPortalProps {
  session: WorkspaceSessionState;
  onAuthenticated: (nextSession: WorkspaceSessionState) => void;
  onRefreshSession: () => Promise<void>;
}

const INPUT_CLASS =
  'w-full h-11 rounded-xl border border-slate-200/90 bg-white px-3.5 text-[13.5px] text-[#18191C] placeholder:text-[#9499A0] transition duration-150 focus:outline-none focus-visible:outline-none focus:border-[#00AEEC] focus:ring-3 focus:ring-[#00AEEC]/15';

export function AuthLoadingSplash() {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-[340px] rounded-[22px] bg-white/90 backdrop-blur-xl border border-white/90 shadow-[0_18px_46px_-22px_rgba(15,23,42,0.14)] px-7 py-8 flex flex-col items-center text-center gap-4">
        <BrandLogo collapsed={false} />
        <div className="w-36 h-1.5 rounded-full bg-slate-100 overflow-hidden" aria-hidden="true">
          <div className="h-full w-1/2 rounded-full bg-[#00AEEC]/70 animate-pulse" />
        </div>
        <p className="text-xs text-[#61666D]">正在连接工作空间…</p>
      </div>
    </div>
  );
}

interface PasswordFieldProps {
  id: string;
  label: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  autoComplete?: string;
  withIcon?: boolean;
}

function PasswordField({
  id,
  label,
  required,
  minLength,
  maxLength = 128,
  value,
  onChange,
  placeholder,
  autoComplete,
  withIcon = false,
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="block text-[12px] font-medium text-[#4E5969] mb-1.5">
        {label}
      </label>
      <div className="relative">
        {withIcon && (
          <Lock className="w-4 h-4 text-[#9499A0] absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        )}
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          required={required}
          minLength={minLength}
          maxLength={maxLength}
          data-custom-focus="true"
          value={value}
          autoComplete={autoComplete}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`${INPUT_CLASS} ${withIcon ? 'pl-10' : ''} pr-10`}
        />
        <button
          type="button"
          onClick={() => setVisible(v => !v)}
          aria-label={visible ? '隐藏密码' : '显示密码'}
          className="absolute right-2 top-1/2 -translate-y-1/2 w-7 h-7 rounded-lg inline-flex items-center justify-center text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100/80 transition cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#00AEEC]/40"
        >
          {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}

export function AuthPortal({ session, onAuthenticated, onRefreshSession }: AuthPortalProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const handleBootstrap = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
    setBusy(true);
    try {
      const cleanName = username.trim();
      const next = await bootstrapHostAdmin({
        username: cleanName,
        display_name: cleanName,
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
      setError(err instanceof Error ? err.message : '登录失败，请检查账号与密码');
    } finally {
      setBusy(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefreshSession();
    } finally {
      setRefreshing(false);
    }
  };

  const passwordMismatch = Boolean(confirmPassword && password !== confirmPassword);

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10 text-[#18191C]">
      <main className="w-full max-w-[404px]">
        <div className="rounded-[24px] bg-white/94 backdrop-blur-xl border border-white/95 shadow-[0_24px_60px_-24px_rgba(15,23,42,0.18)] px-7 py-8 sm:px-8 sm:py-9">
          {/* 居中精致品牌标头 */}
          <div className="flex flex-col items-center text-center mb-7">
            <BrandLogo collapsed={false} />
          </div>

          {!session.initialized ? (
            session.bootstrap_allowed ? (
              <form onSubmit={handleBootstrap} className="space-y-4">
                <div className="text-center pb-1">
                  <h1 className="text-[15.5px] font-semibold text-[#18191C]">初始化主机管理员</h1>
                  <p className="text-xs text-[#61666D] mt-1">首次在本机运行需创建首位系统管理员</p>
                </div>

                <div>
                  <label htmlFor="boot-username" className="block text-[12px] font-medium text-[#4E5969] mb-1.5">
                    用户姓名或账号
                  </label>
                  <div className="relative">
                    <User className="w-4 h-4 text-[#9499A0] absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="boot-username"
                      type="text"
                      required
                      minLength={2}
                      maxLength={40}
                      autoFocus
                      data-custom-focus="true"
                      autoComplete="username"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      placeholder="请输入管理员姓名或账号"
                      className={`${INPUT_CLASS} pl-10`}
                    />
                  </div>
                </div>

                <PasswordField
                  id="boot-password"
                  label="登录密码"
                  required
                  minLength={6}
                  value={password}
                  onChange={setPassword}
                  placeholder="至少 6 位字符"
                  autoComplete="new-password"
                  withIcon
                />

                <PasswordField
                  id="boot-confirm"
                  label="确认密码"
                  required
                  minLength={6}
                  value={confirmPassword}
                  onChange={setConfirmPassword}
                  placeholder="再次输入密码"
                  autoComplete="new-password"
                  withIcon
                />

                {passwordMismatch && (
                  <p className="text-xs text-rose-600">两次输入的密码不一致</p>
                )}

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
                  disabled={busy || passwordMismatch}
                  className="w-full h-11 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] active:scale-[0.99] disabled:opacity-55 text-white text-[14px] font-semibold shadow-[0_10px_24px_-10px_rgba(0,174,236,0.75)] transition duration-150 cursor-pointer"
                >
                  {busy ? '正在创建…' : '创建并进入'}
                </button>
              </form>
            ) : (
              <div className="py-4 text-center space-y-5">
                <div className="w-11 h-11 rounded-2xl bg-amber-50 border border-amber-200/80 text-amber-600 flex items-center justify-center mx-auto">
                  <Lock className="w-5 h-5" />
                </div>
                <div className="space-y-1.5">
                  <h1 className="text-base font-semibold text-[#18191C]">等待管理员初始化</h1>
                  <p className="text-xs text-[#61666D] leading-relaxed">
                    请管理员先在主机完成首次建号，随后刷新本页登录使用。
                  </p>
                </div>
                <button
                  type="button"
                  disabled={refreshing}
                  onClick={() => void handleRefresh()}
                  className="inline-flex items-center justify-center gap-1.5 h-9 px-4 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-[#18191C] transition cursor-pointer disabled:opacity-60"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
                  <span>{refreshing ? '检查中…' : '刷新状态'}</span>
                </button>
              </div>
            )
          ) : (
            <div>
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label htmlFor="login-username" className="block text-[12px] font-medium text-[#4E5969] mb-1.5">
                    账号
                  </label>
                  <div className="relative">
                    <User className="w-4 h-4 text-[#9499A0] absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      id="login-username"
                      type="text"
                      required
                      autoFocus
                      data-custom-focus="true"
                      autoComplete="username"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      placeholder="请输入用户姓名或账号"
                      className={`${INPUT_CLASS} pl-10`}
                    />
                  </div>
                </div>

                <PasswordField
                  id="login-password"
                  label="密码"
                  required
                  value={password}
                  onChange={setPassword}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  withIcon
                />

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
                  className="w-full h-11 mt-1 rounded-xl bg-[#00AEEC] hover:bg-[#009CD6] active:scale-[0.99] disabled:opacity-55 text-white text-[14px] font-semibold shadow-[0_10px_24px_-10px_rgba(0,174,236,0.75)] transition duration-150 cursor-pointer"
                >
                  {busy ? '登录中…' : '登录'}
                </button>
              </form>

              <p className="mt-6 pt-4 border-t border-slate-100 text-center text-[11.5px] text-[#9499A0]">
                账号由系统管理员统一创建开通
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
