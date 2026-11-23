import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { KeyRound, Loader2, ShieldCheck, Smartphone, Sparkles, X } from 'lucide-react';
import { requestFengshenAuth } from '../lib/fengshenAuthApi';

export interface FengshenAuthStatus {
  release_state?: string;
  release_message?: string;
  cancelling?: boolean;
  session_version?: string;
  account_label?: string;
  organization?: string;
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
  autoOpenEnabled?: boolean;
  requestVersion: number;
  eventStatus: FengshenAuthStatus | null;
  onStatus: (status: FengshenAuthStatus) => void;
}

const EXIT_TRANSITION_MS = 240;

export function FengshenLoginModal({
  workspaceId,
  downloadAccountId,
  enabled = true,
  autoOpenEnabled = true,
  requestVersion,
  eventStatus,
  onStatus,
}: Props) {
  const [status, setStatus] = useState<FengshenAuthStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [rendered, setRendered] = useState(false);
  const [animPhase, setAnimPhase] = useState<'entering' | 'entered' | 'exiting'>('entering');
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
  const initialFocusDone = useRef(false);
  const autoOpenEnabledRef = useRef(autoOpenEnabled);
  autoOpenEnabledRef.current = autoOpenEnabled;

  const snooze = useCallback(() => {
    snoozeUntil.current = Date.now() + 30000;
    setOpen(false);
  }, []);

  const httpMode =
    status?.transport === 'http' || (!!downloadAccountId && status?.transport !== 'browser');
  const phoneRequired = status?.phone_required !== false;
  const exportVerification = status?.purpose === 'export';

  useEffect(() => {
    if (!enabled) {
      setRendered(false);
      setAnimPhase('entering');
      return;
    }
    if (open) {
      setRendered(true);
      setAnimPhase('entering');
      let raf2 = 0;
      const raf1 = window.requestAnimationFrame(() => {
        raf2 = window.requestAnimationFrame(() => {
          setAnimPhase('entered');
        });
      });
      return () => {
        window.cancelAnimationFrame(raf1);
        if (raf2) window.cancelAnimationFrame(raf2);
      };
    }
    if (rendered) {
      setAnimPhase('exiting');
      const timer = window.setTimeout(() => {
        setRendered(false);
      }, EXIT_TRANSITION_MS);
      return () => window.clearTimeout(timer);
    }
  }, [open, enabled, rendered]);

  const acceptStatus = useCallback(
    (next: FengshenAuthStatus) => {
      if (!next || typeof next.state !== 'string') return;
      const justSucceeded =
        next.state === 'ready' &&
        !!statusRef.current?.challenge_id &&
        statusRef.current.state !== 'ready';
      if (next.challenge_id !== statusRef.current?.challenge_id) {
        setCode('');
        setMessage('');
      }
      statusRef.current = next;
      setStatus(next);
      onStatus(next);
      if (
        autoOpenEnabledRef.current &&
        next.challenge_id &&
        Date.now() >= snoozeUntil.current &&
        ['login_required', 'sms_sent', 'manual_required', 'sending', 'verifying'].includes(
          next.stage || '',
        )
      ) {
        setOpen(true);
      }
      if (justSucceeded) {
        setOpen(false);
        setPhone('');
        setCode('');
      }
    },
    [onStatus],
  );

  const request = useCallback(
    <T = Record<string, any>,>(path: string, body?: object) =>
      requestFengshenAuth<T>(workspaceId, path, body, fetch, !!downloadAccountId),
    [workspaceId, downloadAccountId],
  );

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
      void refresh().catch(() => {});
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
        if (!disposed) {
          acceptStatus(next);
          setOffline(false);
          setConnectionError('');
        }
      } catch (error) {
        if (!disposed) {
          setOffline(true);
          if (statusRef.current) onStatus({ ...statusRef.current, connection_unknown: true });
          setConnectionError(
            error instanceof Error ? error.message : '无法更新主机登录状态',
          );
        }
      }
      if (!disposed) timer = setTimeout(poll, statusRef.current?.busy ? 1000 : 5000);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [request, acceptStatus, enabled, onStatus]);

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
    void request<FengshenAuthStatus>('status')
      .then(async current => {
        acceptStatus(current);
        return current.state === 'ready' || current.busy
          ? { status: current }
          : request('start', {});
      })
      .then(data => {
        if (data.status) acceptStatus(data.status);
      })
      .catch(error => setMessage(error instanceof Error ? error.message : '无法启动登录'))
      .finally(() => {
        opening.current = false;
        setBusy(false);
      });
  }, [requestVersion, request, acceptStatus, enabled]);

  useEffect(() => {
    if (!open) setCode('');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') snooze();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, snooze]);

  const challengeActive =
    !!status?.challenge_id && status.state !== 'ready' && !status?.cancelling;

  useEffect(() => {
    if (!open) {
      initialFocusDone.current = false;
      return;
    }
    if (initialFocusDone.current) return;
    const timer = window.setTimeout(() => {
      const target =
        phoneRequired && !phone.trim() ? phoneInput.current : codeInput.current;
      if (!target) return;
      target.focus();
      initialFocusDone.current = true;
    }, 60);
    return () => window.clearTimeout(timer);
  }, [open, status?.challenge_id, status?.state, phoneRequired, phone]);

  useEffect(() => {
    if (!challengeActive || !status?.challenge_id) return;
    const original = document.title;
    let flip = false;
    const timer = window.setInterval(() => {
      flip = !flip;
      document.title = flip ? '【等待短信验证】' + original : original;
    }, 1500);
    return () => {
      window.clearInterval(timer);
      document.title = original;
    };
  }, [challengeActive, status?.challenge_id]);

  const startSession = async () => {
    setBusy(true);
    setMessage('');
    try {
      const value = await request('start', {});
      if (value.status) acceptStatus(value.status);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '登录未完成');
    } finally {
      setBusy(false);
    }
  };

  const command = async (action: 'send' | 'verify') => {
    setBusy(true);
    setMessage('');
    try {
      const result = await request(action, {
        challenge_id: statusRef.current?.challenge_id,
        ...(action === 'send'
          ? { phone: phone.trim() }
          : action === 'verify'
            ? { code: code.trim() }
            : {}),
      });
      setMessage(result.message || (result.ok ? '操作已完成' : '操作未完成'));
      if (action === 'verify') setCode('');

      await refresh();
      if (action === 'send' && result.ok && codeInput.current) {
        initialFocusDone.current = true;
        window.setTimeout(() => codeInput.current?.focus(), 50);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '登录服务连接失败');
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  if (!rendered || !enabled) return null;

  const releasing =
    !!status?.cancelling ||
    ['releasing', 'timeout', 'terminated', 'unconfirmed'].includes(
      status?.release_state || '',
    );
  const waiting = !!status?.challenge_id && status.state !== 'ready' && !releasing;
  const showForm = status?.state !== 'ready' && !releasing;
  const validPhone = !phoneRequired || /^1[3-9]\d{9}$/.test(phone);
  const canClickSend =
    !busy &&
    !offline &&
    validPhone &&
    (waiting ? !!status?.can_send : true);
  const canClickVerify =
    !busy &&
    !offline &&
    (waiting ? code.length === 6 && validPhone : validPhone);

  const title = exportVerification ? '风神导出验证' : '风神登录验证';
  const phaseClass =
    animPhase === 'entered'
      ? 'is-entered'
      : animPhase === 'exiting'
        ? 'is-exiting'
        : 'is-entering';

  const statusText = offline
    ? connectionError || '登录服务待连接，可在下方输入手机号与短信验证码准备认证'
    : status?.message ||
      (httpMode
        ? '风神短信安全通道已就绪，请输入绑定手机号与验证码'
        : '正在主机打开风神登录会话');

  const modalNode = (
    <div
      className={`wbx-fs-backdrop ${phaseClass}`}
      onMouseDown={event => {
        if (event.target === event.currentTarget) snooze();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`wbx-fs-modal ${phaseClass}`}
      >
        <header className="wbx-fs-modal__head">
          <div className="wbx-fs-modal__lead">
            <span className="wbx-fs-modal__badge" aria-hidden="true">
              <ShieldCheck size={21} />
            </span>
            <div className="wbx-fs-modal__heading">
              <div className="wbx-fs-modal__title-row">
                <h2 className="wbx-fs-modal__title">{title}</h2>
                <span className="wbx-fs-modal__tag">
                  {exportVerification ? '导出安全校验' : '短信安全认证'}
                </span>
              </div>
              <p className="wbx-fs-modal__subtitle">
                {exportVerification
                  ? '任务已暂停在导出环节，完成验证码核验后自动恢复；关闭将在 30 秒后再次提醒。'
                  : '输入风神平台绑定手机号与 6 位短信验证码，认证完成后自动同步会话。'}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="稍后提醒（30 秒）"
            title="稍后提醒（30 秒）"
            onClick={snooze}
            className="wbx-fs-modal__close"
          >
            <X size={17} />
          </button>
        </header>

        <div className="wbx-fs-modal__body wb-auth-session">
          <div
            role="status"
            className={`wbx-fs-status${offline ? ' is-offline' : ''}`}
          >
            <div className="wbx-fs-status__main">
              {busy || status?.stage === 'checking' ? (
                <Loader2
                  size={16}
                  className="wbx-fs-status__icon wbx-fs-spin"
                />
              ) : (
                <Sparkles size={16} className="wbx-fs-status__icon" />
              )}
              <span className="wbx-fs-status__text">{statusText}</span>
            </div>
            <span className="wbx-fs-status__pill">
              {httpMode ? 'HTTP 直连' : '主机会话'}
            </span>
          </div>

          {releasing && (
            <p role="status" className="wbx-fs-alert">
              {status?.release_message || '正在结束本次认证，请稍候。'}
              {['timeout', 'unconfirmed'].includes(status?.release_state || '')
                ? ' 可重新读取状态；未结束前不会启动新认证。'
                : ''}
            </p>
          )}

          {message && message !== connectionError && (
            <div role="alert" className="wbx-fs-alert">
              {message}
            </div>
          )}

          {showForm && (
            <form
              className="wbx-fs-form"
              onSubmit={event => {
                event.preventDefault();
                if (busy || offline) return;
                if (waiting) {
                  if (code.length === 6 && validPhone) {
                    void command('verify');
                  }
                } else {
                  void startSession();
                }
              }}
            >
              {phoneRequired && (
                <div className="wbx-fs-field">
                  <div className="wbx-fs-field__head">
                    <label
                      htmlFor="fengshen-phone"
                      className="wbx-fs-field__label"
                    >
                      手机号码
                    </label>
                    <span className="wbx-fs-field__hint">
                      {status?.phone_mask
                        ? `已绑定 ${status.phone_mask}`
                        : '11 位大陆手机号'}
                    </span>
                  </div>
                  <div
                    className={`wbx-fs-input-wrap${busy ? ' is-disabled' : ''}${validPhone && phone.length === 11 ? ' is-complete' : ''}`}
                  >
                    <Smartphone
                      size={16}
                      className="wbx-fs-input__icon"
                      aria-hidden="true"
                    />
                    <input
                      ref={phoneInput}
                      id="fengshen-phone"
                      type="tel"
                      inputMode="tel"
                      autoComplete="off"
                      maxLength={11}
                      placeholder="请输入 11 位风神绑定手机号"
                      value={phone}
                      onInput={event =>
                        setPhone(
                          event.currentTarget.value
                            .replace(/\D/g, '')
                            .slice(0, 11),
                        )
                      }
                      onChange={event =>
                        setPhone(
                          event.target.value.replace(/\D/g, '').slice(0, 11),
                        )
                      }
                      disabled={busy}
                      className="wb-fengshen-input wbx-fs-input"
                    />
                    <span className="wbx-fs-input__count">
                      {phone.length}/11
                    </span>
                  </div>
                </div>
              )}

              <div className="wbx-fs-field">
                <div className="wbx-fs-field__head">
                  <label
                    htmlFor="fengshen-code"
                    className="wbx-fs-field__label"
                  >
                    短信验证码
                  </label>
                  <span className="wbx-fs-field__hint">6 位数字动态码</span>
                </div>
                <div className="wbx-fs-input-row">
                  <div
                    className={`wbx-fs-input-wrap${busy ? ' is-disabled' : ''}${code.length === 6 ? ' is-complete' : ''}`}
                  >
                    <KeyRound
                      size={16}
                      className="wbx-fs-input__icon"
                      aria-hidden="true"
                    />
                    <input
                      ref={codeInput}
                      id="fengshen-code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      value={code}
                      placeholder="请输入 6 位短信验证码"
                      onInput={event =>
                        setCode(
                          event.currentTarget.value
                            .replace(/\D/g, '')
                            .slice(0, 6),
                        )
                      }
                      onChange={event =>
                        setCode(
                          event.target.value.replace(/\D/g, '').slice(0, 6),
                        )
                      }
                      disabled={busy}
                      className="wb-fengshen-input wbx-fs-input is-code"
                    />
                    <span className="wbx-fs-input__count">{code.length}/6</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (waiting) {
                        void command('send');
                      } else {
                        void startSession();
                      }
                    }}
                    disabled={!canClickSend}
                    className="wbx-fs-code-btn"
                  >
                    <KeyRound size={14} />
                    <span>
                      {status?.retry_after
                        ? `${status.retry_after} 秒`
                        : '获取验证码'}
                    </span>
                  </button>
                </div>
                <p className="wbx-fs-field__sub">
                  {phoneRequired
                    ? '验证码将发送至上方手机号；'
                    : '验证码将发送至平台账号绑定手机；'}
                  如未收到请稍候重试，系统不会自动重发。
                </p>
              </div>

              <div className="wbx-fs-actions">
                <button
                  type="submit"
                  disabled={!canClickVerify}
                  className="wbx-fs-submit-btn"
                >
                  {busy ? (
                    <Loader2 size={16} className="wbx-fs-spin" />
                  ) : (
                    <ShieldCheck size={16} />
                  )}
                  <span>
                    {exportVerification
                      ? '验证并继续任务'
                      : waiting
                        ? '立即验证并登录'
                        : '启动认证并登录'}
                  </span>
                </button>
                <div className="wbx-fs-foot-note">
                  {httpMode
                    ? exportVerification
                      ? '此为平台要求的资料导出安全验证，核验通过后自动继续当前下载任务。'
                      : '完成短信核验后采集与核算任务将自动恢复；如平台要求额外图形校验，系统会安全暂停并提示原因。'
                    : '当前认证需要主机端完成额外校验，任务已安全暂停；系统不会自动拉起外部浏览器。'}
                </div>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );

  return typeof document === 'undefined'
    ? modalNode
    : createPortal(
        modalNode,
        document.querySelector('.workbench-app') || document.body,
      );
}

