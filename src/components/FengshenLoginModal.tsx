import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { KeyRound, Loader2, ShieldCheck, X } from 'lucide-react';
import { requestFengshenAuth } from '../lib/fengshenAuthApi';
import { WorkbenchDrawer } from './WorkbenchDrawer';

export interface FengshenAuthStatus {
  release_state?:string; release_message?:string; cancelling?:boolean; session_version?: string; account_label?: string; organization?: string;
  state: string;
  message: string;
  saved: boolean;
  busy: boolean;
  challenge_id: string | null;
  stage: string | null;
  phone_mask: string;
  retry_after: number;
  can_send: boolean;
  can_verify: boolean;
  can_recheck: boolean;
  transport?: 'http' | 'browser';
  purpose?: string;
  phone_required?: boolean;
  connection_unknown?: boolean;
}

interface Props {
  workspaceId: string;
  downloadAccountId?: string;
  enabled?: boolean;
  requestVersion: number;
  eventStatus: FengshenAuthStatus | null;
  onStatus: (status: FengshenAuthStatus) => void;
}

export function FengshenLoginModal({ workspaceId, downloadAccountId, enabled = true, requestVersion, eventStatus, onStatus }: Props) {
  const [status, setStatus] = useState<FengshenAuthStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);


  const [offline, setOffline] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const statusRef = useRef<FengshenAuthStatus | null>(null);
  const phoneInput = useRef<HTMLInputElement>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  const opening = useRef(false);
  const snoozeUntil = useRef(0);
  const notifiedChallenge = useRef<string | null>(null);
  const httpMode = status?.transport === 'http' || (!!downloadAccountId && status?.transport !== 'browser');
  const phoneRequired = status?.phone_required !== false;
  const exportVerification = status?.purpose === 'export';

  const acceptStatus = useCallback((next: FengshenAuthStatus) => {
    if (!next || typeof next.state !== 'string') return;
    const justSucceeded = next.state === 'ready' && !!statusRef.current?.challenge_id && statusRef.current.state !== 'ready';
    if (next.challenge_id !== statusRef.current?.challenge_id) {
      setCode('');
      setMessage('');

    }
    statusRef.current = next;
    setStatus(next);
    onStatus(next);
    if (next.challenge_id && Date.now() >= snoozeUntil.current && ['login_required', 'sms_sent', 'manual_required', 'sending', 'verifying'].includes(next.stage || '')) {
      setOpen(true);
    }
    if (justSucceeded) {
      setOpen(false);
      setPhone('');
      setCode('');
    }
  }, [onStatus]);

  const request = useCallback(<T = Record<string, any>,>(path: string, body?: object) => requestFengshenAuth<T>(workspaceId, path, body, fetch, !!downloadAccountId), [workspaceId, downloadAccountId]);

  const refresh = useCallback(async () => {
    const next = await request<FengshenAuthStatus>('status');
    acceptStatus(next);
    setOffline(false);
    setConnectionError('');
    return next as FengshenAuthStatus;
  }, [request, acceptStatus]);

  useEffect(() => {
    if (!enabled) return;
    const openVerification = () => {
      snoozeUntil.current = 0;
      setOpen(true);
      void refresh();
    };
    window.addEventListener('workbench:fengshen-verification', openVerification);
    return () => window.removeEventListener('workbench:fengshen-verification', openVerification);
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await request<FengshenAuthStatus>('status');
        if (!disposed) { acceptStatus(next); setOffline(false); setConnectionError(''); }
      } catch (error) {
        if (!disposed) {
          setOffline(true);
          if (statusRef.current) onStatus({ ...statusRef.current, connection_unknown: true });
          setConnectionError(error instanceof Error ? error.message : '无法更新主机登录状态');
        }
      }
      if (!disposed) timer = setTimeout(poll, statusRef.current?.busy ? 1000 : 5000);
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [request, acceptStatus, enabled]);

  useEffect(() => {
    if (!enabled || downloadAccountId) return;
    if (eventStatus) acceptStatus(eventStatus);
  }, [eventStatus, acceptStatus, downloadAccountId, enabled]);

  useEffect(() => {
    if (!requestVersion || !enabled) return;
    snoozeUntil.current = 0;
    setOpen(true);
    setMessage('');
    if (opening.current) return;
    opening.current = true;
    setBusy(true);
    void request<FengshenAuthStatus>('status').then(async current => {
      acceptStatus(current);
      return current.state === 'ready' || current.busy ? { status: current } : request('start', {});
    }).then(data => {
      if (data.status) acceptStatus(data.status);
    }).catch(error => setMessage(error instanceof Error ? error.message : '无法启动登录'))
      .finally(() => { opening.current = false; setBusy(false); });
  }, [requestVersion, request, acceptStatus, enabled]);

  useEffect(() => { if (!open) setCode(''); }, [open]);

  const challengeActive = !!status?.challenge_id && status.state !== 'ready' && !status?.cancelling;
  useEffect(() => {
    if (!open || !status?.challenge_id) return;
    const timer = window.setTimeout(() => codeInput.current?.focus(), 50);
    return () => window.clearTimeout(timer);
  }, [open, status?.challenge_id, status?.state]);
  useEffect(() => {
    if (!challengeActive || !status?.challenge_id) return;
    const original = document.title;
    let flip = false;
    const timer = window.setInterval(() => {
      flip = !flip;
      document.title = flip ? '【等待短信验证】' + original : original;
    }, 1500);
    if (notifiedChallenge.current !== status.challenge_id && typeof Notification !== 'undefined') {
      notifiedChallenge.current = status.challenge_id;
      const notify = () => new Notification(exportVerification ? '风神导出验证' : '风神登录验证', {
        body: status.phone_mask ? `验证码将发送到 ${status.phone_mask}` : '请在系统页面输入短信验证码',
        tag: status.challenge_id || undefined,
      });
      try {
        if (Notification.permission === 'granted') notify();
        else if (Notification.permission === 'default') {
          void Notification.requestPermission().then(permission => { if (permission === 'granted') notify(); });
        }
      } catch { /* 浏览器不支持桌面通知时保留页面内提醒 */ }
    }
    return () => { window.clearInterval(timer); document.title = original; };
  }, [challengeActive, status?.challenge_id, status?.phone_mask, exportVerification]);

  const command = async (action: 'send' | 'verify') => {
    setBusy(true);
    setMessage('');
    try {
      const result = await request(action, {
        challenge_id: statusRef.current?.challenge_id,
        ...(action === 'send' ? { phone: phone.trim() } : action === 'verify' ? { code: code.trim() } : {}),
      });
      setMessage(result.message || (result.ok ? '操作已完成' : '操作未完成'));
      if (action === 'verify') setCode('');

      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '登录服务连接失败');
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  if (!open || !enabled) return null;
  const releasing=!!status?.cancelling || ['releasing','timeout','terminated','unconfirmed'].includes(status?.release_state || '');
  const waiting = !!status?.challenge_id && status.state !== 'ready' && !releasing;
  const snooze = () => { snoozeUntil.current = Date.now() + 30000; setOpen(false); };
  const content = (
    <>
        <div role="status" className="mb-5 flex items-start gap-2 text-sm leading-6 text-slate-700">
          {busy || status?.stage === 'checking' ? <Loader2 size={18} className="mt-1 shrink-0 text-sky-700" /> : <ShieldCheck size={18} className="mt-1 shrink-0 text-emerald-600" />}
          <span className="min-w-0 break-words">{offline ? connectionError || '登录服务已断开，任务状态待确认' : status?.message || (httpMode ? '正在连接风神认证服务' : '正在主机打开风神登录页')}</span>
        </div>
        {releasing && <p role="status" className="wb-notice">{status?.release_message || '正在结束本次认证，请稍候。'}{['timeout','unconfirmed'].includes(status?.release_state || '')?' 可重新读取状态；未结束前不会启动新认证。':''}</p>}
        {message && <div role="alert" className="mb-4 break-words text-sm leading-6 text-amber-700">{message}</div>}
        {status?.state !== 'ready' && waiting && <form onSubmit={event => { event.preventDefault(); if (status?.can_verify && !busy) void command('verify'); }} className="space-y-4">
          {phoneRequired && <div>
            <label htmlFor="fengshen-phone" className="mb-2 block text-sm font-medium text-slate-700">手机号码</label>
            <input ref={phoneInput} id="fengshen-phone" type="tel" inputMode="tel" autoComplete="off" maxLength={11}
              value={phone} onInput={event => setPhone(event.currentTarget.value.replace(/\D/g, '').slice(0, 11))}
              onChange={event => setPhone(event.target.value.replace(/\D/g, '').slice(0, 11))}
              disabled={busy || !waiting} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-700" />
          </div>}
          <div className="rounded-xl border-2 border-emerald-300 bg-emerald-50/60 p-4">
            <label htmlFor="fengshen-code" className="mb-2 block text-sm font-semibold text-slate-800">请输入短信验证码</label>
            <div className="flex flex-wrap gap-2">
              <input ref={codeInput} id="fengshen-code" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                value={code} placeholder="6 位数字验证码"
                onInput={event => setCode(event.currentTarget.value.replace(/\D/g, '').slice(0, 6))}
                onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                disabled={busy || !waiting} className="min-w-0 flex-1 basis-40 rounded-lg border-2 border-emerald-500 bg-white px-3 py-2.5 text-center text-lg tracking-[0.3em] text-slate-900 focus:outline-none focus:ring-2 focus:ring-emerald-600" />
              <button type="button" onClick={() => void command('send')} disabled={busy || offline || !status?.can_send || (phoneRequired && !/^1[3-9]\d{9}$/.test(phone))}
                className="flex min-w-28 items-center justify-center gap-2 rounded-lg bg-sky-700 hover:bg-sky-800 px-3 py-2.5 text-sm font-medium text-white disabled:opacity-40">
                <KeyRound size={15} />{status?.retry_after ? `${status.retry_after} 秒` : '获取验证码'}
              </button>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">
              {phoneRequired ? '验证码将发送到上方手机号。' : '验证码将发送到平台账号绑定的手机。'}收不到可稍后重试，系统不会自动重发。
            </p>
          </div>
          <button type="submit" disabled={busy || offline || !status?.can_verify || code.length !== 6}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 px-4 py-3 text-base font-semibold text-white disabled:opacity-40">
            {busy ? <Loader2 size={18} /> : <ShieldCheck size={18} />}{exportVerification?'验证并继续任务':'登录'}
          </button>
          <p className="text-xs leading-5 text-slate-500">{httpMode ? (exportVerification ? '这是平台要求的资料导出验证。完成后继续当前下载任务。' : '在此输入短信验证码即可完成认证，任务会自动继续。如平台要求额外验证，系统会暂停并显示原因。') : '当前认证需要平台额外验证，已暂停；不会自动打开外部浏览器。'}</p>
        </form>}
        {!status?.busy && status?.state!=='ready' && <button type="button" className="wb-primary" disabled={busy || offline} onClick={async()=>{setBusy(true);setMessage('');try{const value=await request('start',{});if(value.status)acceptStatus(value.status);}catch(error){setMessage(error instanceof Error?error.message:'登录未完成');}finally{setBusy(false);}}}>登录</button>}
    </>
  );
  if (exportVerification && waiting) {
    return createPortal(
      <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-900/50 p-4"
        onMouseDown={event => { if (event.target === event.currentTarget) snooze(); }}>
        <div role="dialog" aria-modal="true" aria-label="风神导出验证"
          className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-900">风神导出验证</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                任务已暂停在导出环节，输入验证码后自动继续；关闭会在 30 秒后再次提醒。
              </p>
            </div>
            <button type="button" aria-label="稍后提醒" onClick={snooze}
              className="rounded p-1 text-slate-500 hover:bg-slate-100">
              <X size={18} />
            </button>
          </div>
          {content}
        </div>
      </div>,
      document.querySelector('.workbench-app') || document.body);
  }
  return (
    <WorkbenchDrawer title={exportVerification?'风神导出验证':'风神登录验证'} closeLabel="稍后提醒（30 秒）" bodyClassName="wb-auth-session" onClose={snooze}>
      {content}
    </WorkbenchDrawer>
  );
}
