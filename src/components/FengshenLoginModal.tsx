import React, { useCallback, useEffect, useRef, useState } from 'react';
import { KeyRound, Loader2, ShieldCheck } from 'lucide-react';
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

  const opening = useRef(false);
  const hiddenChallenge = useRef<string | null>(null);
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
    if (next.challenge_id && next.challenge_id !== hiddenChallenge.current && ['login_required', 'sms_sent', 'manual_required', 'sending', 'verifying'].includes(next.stage || '')) {
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
    hiddenChallenge.current = null;
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
  return (
    <WorkbenchDrawer title={exportVerification?'风神导出验证':'风神登录验证'} closeLabel="收起认证，保留任务" bodyClassName="wb-auth-session" onClose={()=>{hiddenChallenge.current=statusRef.current?.challenge_id || null;setOpen(false);}}>
        <div role="status" className="mb-5 flex items-start gap-2 text-sm leading-6 text-slate-700">
          {busy || status?.stage === 'checking' ? <Loader2 size={18} className="mt-1 shrink-0 text-sky-700" /> : <ShieldCheck size={18} className="mt-1 shrink-0 text-emerald-600" />}
          <span className="min-w-0 break-words">{offline ? connectionError || '登录服务已断开，任务状态待确认' : status?.message || (httpMode ? '正在连接风神认证服务' : '正在主机打开风神登录页')}</span>
        </div>
        {releasing && <p role="status" className="wb-notice">{status?.release_message || '正在结束本次认证，请稍候。'}{['timeout','unconfirmed'].includes(status?.release_state || '')?' 可重新读取状态；未结束前不会启动新认证。':''}</p>}
        {message && <div role="alert" className="mb-4 break-words text-sm leading-6 text-amber-700">{message}</div>}
        {status?.state !== 'ready' && waiting && <form onSubmit={event => { event.preventDefault(); if (status?.can_verify && !busy) void command('verify'); }} className="space-y-4">
          <div>
            {phoneRequired ? <label htmlFor="fengshen-phone" className="mb-2 block text-sm font-medium text-slate-700">手机号码</label> : <p className="mb-2 text-sm text-slate-600">验证码由风神发送到当前账号绑定的手机。</p>}
            <div className="flex flex-wrap gap-2">
              {phoneRequired && <input ref={phoneInput} id="fengshen-phone" type="tel" inputMode="tel" autoComplete="off" maxLength={11}
                value={phone} onInput={event => setPhone(event.currentTarget.value.replace(/\D/g, '').slice(0, 11))}
                onChange={event => setPhone(event.target.value.replace(/\D/g, '').slice(0, 11))}
                disabled={busy || !waiting} className="min-w-0 flex-1 basis-40 rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-700" />}
              <button type="button" onClick={() => void command('send')} disabled={busy || offline || !status?.can_send || (phoneRequired && !/^1[3-9]\d{9}$/.test(phone))}
                className="flex min-w-28 items-center justify-center gap-2 rounded-lg bg-sky-700 hover:bg-sky-800 px-3 py-2.5 text-sm font-medium text-white disabled:opacity-40">
                <KeyRound size={15} />{status?.retry_after ? `${status.retry_after} 秒` : '获取验证码'}
              </button>
            </div>
          </div>
          <div>
            <label htmlFor="fengshen-code" className="mb-2 block text-sm font-medium text-slate-700">短信验证码</label>
            <input id="fengshen-code" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
              value={code} onInput={event => setCode(event.currentTarget.value.replace(/\D/g, '').slice(0, 6))}
              onChange={event => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              disabled={busy || !waiting} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-700" />
          </div>
          <button type="submit" disabled={busy || offline || !status?.can_verify || code.length !== 6}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40">
            {busy ? <Loader2 size={16} /> : <ShieldCheck size={16} />}{exportVerification?'验证并继续':'登录'}
          </button>
          <p className="text-xs leading-5 text-slate-500">{httpMode ? (exportVerification ? '这是平台要求的资料导出验证。完成后继续当前下载任务。' : '在此输入短信验证码即可完成认证，任务会自动继续。如平台要求额外验证，系统会暂停并显示原因。') : '当前认证需要平台额外验证，已暂停；不会自动打开外部浏览器。'}</p>
        </form>}
        {!status?.busy && status?.state!=='ready' && <button type="button" className="wb-primary" disabled={busy || offline} onClick={async()=>{setBusy(true);setMessage('');try{const value=await request('start',{});if(value.status)acceptStatus(value.status);}catch(error){setMessage(error instanceof Error?error.message:'登录未完成');}finally{setBusy(false);}}}>登录</button>}
    </WorkbenchDrawer>
  );
}
