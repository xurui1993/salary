import React, { useEffect, useRef, useState } from 'react';
import {
  Building2,
  Calculator,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  QrCode,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  User,
} from 'lucide-react';
import { platformAuthRequest, PlatformAuthError } from '../lib/platformAuthApi';
import { OfficialVerification } from './OfficialVerification';
import { reconcileAuthDraft } from '../lib/authInputDraft';

export interface DesktopField {
  id: string;
  type?: string;
  role?: string;
  label?: string;
  filled?: boolean;
  auto?: boolean;
}

export interface DesktopControl {
  id: string;
  kind: string;
  label?: string;
  enabled?: boolean;
  retry_after?: number;
  issuer?: string;
}

export interface MathCaptchaMeta {
  id?: string;
  state?: 'solved' | 'recognizing' | 'unavailable' | 'manual' | string;
  expression?: string;
  answer?: string;
  image?: string;
}

export interface SourceDesktopState {
  fields?: DesktopField[];
  controls?: DesktopControl[];
  math_captcha?: MathCaptchaMeta;
  has_qr?: boolean;
  qr_stage?: string;
  qr_state?: string;
  qr_version?: string;
  transitioning?: boolean;
  submitted?: { account?: string } | null;
  retry?: boolean;
  sms_retry_after?: number;
  input_completed?: number;
  input_pending?: boolean;
  input_error?: string;
  form_id?: string;
  form_detection?: string;
  has_challenge?: boolean;
  challenge_id?: string;
  challenge_version?: string;
  official_feedback?: string;
  official_feedback_kind?: string;
  official_feedback_detail?: string;
  window_visible?: boolean;
  board_reused?: boolean;
  lighthouse_reused?: boolean;
}

interface SourceLoginPanelProps {
  source: string;
  sessionId: string;
  apiFetch: typeof fetch;
  desktop?: SourceDesktopState;
}

export function fieldLabel(field: DesktopField): string {
  const roleMap: Record<string, string> = {
    phone: '手机号码',
    password: '密码',
    sms_code: '短信验证码',
    voice_code: '语音验证码',
    math: '算式答案',
  };
  if (field.role && roleMap[field.role]) {
    return roleMap[field.role];
  }
  if (field.type === 'checkbox') {
    return field.label || '同意平台登录授权';
  }
  if (field.label && /[\u4e00-\u9fff]/.test(field.label)) {
    return field.label.replace(/^请输入|^请填写/, '').slice(0, 24);
  }
  return '账号';
}

export function fieldHint(
  field: DesktopField,
  source: string,
  captcha?: MathCaptchaMeta,
): string {
  if (field.role === 'phone') return '11 位大陆手机号';
  if (field.role === 'password' || field.type === 'password') return '平台登录密码';
  if (field.role === 'sms_code') return '6 位数字动态码';
  if (field.role === 'voice_code') return '语音电话动态码';
  if (field.role === 'math') {
    if (captcha?.state === 'solved' && captcha.expression && captcha.answer) {
      return `${captcha.expression} = ${captcha.answer}（已自动填入）`;
    }
    if (captcha?.state === 'recognizing') {
      return '正在自动识别算式…';
    }
    return '填写右侧图形算式结果';
  }
  if (source === 'benlai') return '支持商户号或绑定手机号';
  if (source === 'baize') return '白泽商翼企业登录账号';
  return '平台绑定登录账号';
}

export function fieldPlaceholder(field: DesktopField, source: string): string {
  const label = fieldLabel(field);
  if (field.role === 'phone') return '请输入 11 位绑定手机号';
  if (field.role === 'password' || field.type === 'password') return '请输入平台登录密码';
  if (field.role === 'sms_code') return '请输入短信验证码';
  if (field.role === 'voice_code') return '请输入语音电话动态码';
  if (field.role === 'math') return '请输入结果';
  if (source === 'benlai') return '请输入本来人力商户号或手机号';
  if (source === 'baize') return '请输入白泽商翼企业账号';
  return `请输入${label}`;
}

export function SourceLoginPanel({
  source,
  sessionId,
  apiFetch,
  desktop = {},
}: SourceLoginPanelProps) {
  const fetchRef = useRef(apiFetch);
  fetchRef.current = apiFetch;

  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const [lastCommand, setLastCommand] = useState(0);
  const [lastSms, setLastSms] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [qr, setQr] = useState<{ key: string; url: string; error: string }>({
    key: '',
    url: '',
    error: '',
  });
  const [qrRetry, setQrRetry] = useState(0);
  const [editingAccount, setEditingAccount] = useState(false);
  const [visiblePasswords, setVisiblePasswords] = useState<Record<string, boolean>>({});

  const deadline = useRef(0);
  const inflight = useRef(false);
  const issuer = useRef<string | undefined>(undefined);
  const previousDraft = useRef<any>(undefined);

  const fields = desktop.fields || [];
  const controls = desktop.controls || [];
  const fieldShape = JSON.stringify(
    desktop.fields?.map(({ id, type, role }) => ({ id, type, role })),
  );

  const sms = controls.find(c => c.kind === 'sms');
  const submit = controls.find(c => c.kind === 'submit');
  const captchaRefresh = controls.find(c => c.kind === 'captcha_refresh');
  const captcha = desktop.math_captcha;
  const consentField = fields.find(f => f.role === 'consent');
  const voiceField = fields.find(f => f.role === 'voice_code');

  const boardQr =
    source === 'xiaoxiang' && !!desktop.has_qr && desktop.qr_stage === 'board';
  const lighthouseQr =
    source === 'xiaoxiang' && !!desktop.has_qr && !boardQr;
  const isDingtalkQr = source === 'lanorange' || source === 'lanorange_mdr';
  const qrMode = isDingtalkQr || boardQr || lighthouseQr;

  const transitioning = !!desktop.transitioning;
  const submitted = desktop.submitted || null;
  const retry = !!desktop.retry && !transitioning && !editingAccount;
  const mathFields = fields.filter(f => f.role === 'math');
  const shownFields = retry
    ? fields.filter(f => ['password', 'math'].includes(f.role || ''))
    : fields;

  const qrKey =
    qrMode && desktop.has_qr && desktop.qr_version
      ? `${sessionId}:${desktop.qr_version}`
      : '';
  const refresh = controls.find(c => c.kind === 'qr_refresh');

  useEffect(() => {
    setValues({});
    setError('');
    setUncertain(false);
    setLastCommand(0);
    setLastSms(0);
    setEditingAccount(false);
    setVisiblePasswords({});
  }, [source, sessionId]);

  useEffect(() => {
    if (desktop.fields === undefined) return;
    const next = {
      source,
      sessionId,
      fields: desktop.fields as any,
      captchaId: desktop.math_captcha?.id,
    };
    const previous = previousDraft.current;
    setValues(prev => reconcileAuthDraft(prev, previous, next));
    previousDraft.current = next;
  }, [source, sessionId, fieldShape, desktop.math_captcha?.id]);

  useEffect(() => {
    if (issuer.current !== sms?.issuer) {
      deadline.current = 0;
      issuer.current = sms?.issuer;
    }
    deadline.current = Math.max(
      deadline.current,
      Date.now() + 1000 * Math.max(desktop.sms_retry_after || 0, sms?.retry_after || 0),
    );
  }, [desktop.sms_retry_after, sms?.retry_after, sms?.issuer]);

  useEffect(() => {
    const tick = () =>
      setSeconds(Math.max(0, Math.ceil((deadline.current - Date.now()) / 1000)));
    tick();
    const timer = setInterval(tick, 500);
    return () => clearInterval(timer);
  }, []);

  const endpoint = `/api/fengshen-downloads/source-auth/${source}`;

  useEffect(() => {
    if (!qrKey) {
      setQr({ key: '', url: '', error: '' });
      return;
    }
    let disposed = false;
    let objectUrl = '';
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let activeController: AbortController | null = null;

    const loadQr = async (attempt: number) => {
      if (disposed) return;
      const controller = new AbortController();
      activeController = controller;
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetchRef.current(
          `${endpoint}/qr?session_id=${encodeURIComponent(sessionId)}&v=${encodeURIComponent(
            desktop.qr_version || '',
          )}`,
          { cache: 'no-store', signal: controller.signal },
        );
        if (
          !response.ok ||
          !response.headers.get('content-type')?.startsWith('image/png')
        ) {
          throw new Error('二维码暂未就绪，正在等待更新。');
        }
        const blob = await response.blob();
        if (!blob.size || blob.size > 512 * 1024) {
          throw new Error('二维码暂不可用，请重新读取。');
        }
        if (!disposed) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = URL.createObjectURL(blob);
          setQr({ key: qrKey, url: objectUrl, error: '' });
        }
      } catch {
        if (disposed) return;
        if (attempt < 3) {
          retryTimer = setTimeout(() => void loadQr(attempt + 1), 550);
          return;
        }
        setQr({
          key: qrKey,
          url: '',
          error: '二维码读取未完成，请重新读取。',
        });
      } finally {
        clearTimeout(timer);
      }
    };

    void loadQr(0);

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (activeController) activeController.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [endpoint, sessionId, qrKey, qrRetry, desktop.qr_version]);

  const pending = !!lastCommand && (desktop.input_completed || 0) < lastCommand;

  const initialValue = (f: DesktopField) =>
    f.role === 'math' && captcha?.state === 'solved'
      ? captcha.answer ?? ''
      : undefined;

  const inputValues = () =>
    fields.flatMap(f => {
      const text = values[f.id] ?? initialValue(f);
      return text !== undefined ? [{ id: f.id, text }] : [];
    });

  async function send(control?: DesktopControl, inspect = false) {
    if (inflight.current || pending) return;
    inflight.current = true;
    setBusy(true);
    setError('');
    try {
      if (uncertain) {
        const current = await platformAuthRequest(
          fetchRef.current,
          endpoint,
          undefined,
          10000,
        );
        if (current.input_pending) {
          setError('上次操作仍在处理中，请稍候。');
          return;
        }
        setUncertain(false);
        setError('状态已确认，请再次点击所需操作。');
        return;
      }
      const command = inspect
        ? { action: 'inspect' }
        : control
          ? {
              action: 'control',
              id: control.id,
              values: ['captcha_refresh', 'qr_refresh'].includes(control.kind)
                ? []
                : inputValues(),
            }
          : {
              action: 'fill_fields',
              values: inputValues(),
              submit_id: submit?.id,
            };
      const response = await platformAuthRequest(
        fetchRef.current,
        `${endpoint}/interact`,
        {
          ...command,
          session_id: sessionId,
          form_id: desktop.form_id,
        },
      );
      setLastCommand(response.command_id || 0);
      if (control?.kind === 'sms') {
        setLastSms(response.command_id || 0);
        deadline.current = Date.now() + 60000;
        setSeconds(60);
      }
      if (!control) {
        setValues(previous =>
          Object.fromEntries(
            fields
              .filter(
                f =>
                  !['password', 'sms_code', 'voice_code', 'math'].includes(
                    f.role || '',
                  ) &&
                  f.type !== 'password' &&
                  previous[f.id] !== undefined,
              )
              .map(f => [f.id, previous[f.id]]),
          ),
        );
      }
    } catch (err) {
      if (err instanceof PlatformAuthError && err.uncertain) {
        setUncertain(true);
      }
      setError(
        err instanceof Error ? err.message : '操作未完成，请稍候重试。',
      );
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  }

  const disabled = busy || pending || !!desktop.has_challenge;
  const mathReady = fields
    .filter(f => f.role === 'math')
    .every(
      f =>
        !!(
          values[f.id] ?? (captcha?.state === 'solved' ? captcha.answer : '')
        )?.trim(),
    );
  const phoneEntered = fields.some(
    f => f.role === 'phone' && !!values[f.id]?.trim(),
  );

  // IMPORTANT: Keep text directly inside <button> so test regex /<button[^>]*disabled=""[^>]*>获取验证码/ matches
  const smsButton = sms && (
    <button
      type="button"
      className="wb-button wbx-fs-code-btn"
      disabled={disabled || seconds > 0 || (sms.enabled === false && !phoneEntered)}
      onClick={() => void send(sms)}
    >
      {seconds ? `${seconds}秒后可重发` : '获取验证码'}
    </button>
  );

  if (transitioning) {
    return (
      <div className="wb-auth-session wbx-auth-panel">
        <div className="wb-auth-progress wbx-auth-progress-card" role="status">
          <div className="wbx-auth-progress-card__head">
            <Loader2 size={18} className="wbx-fs-spin text-[#00AEEC]" />
            <p className="wb-auth-progress-title">
              {submitted?.account
                ? `企业账号 ${submitted.account} 已提交，正在验证并跳转…`
                : '已提交登录信息，正在验证并跳转…'}
            </p>
          </div>
          <p className="wb-muted">
            请稍候，不要重复点击；若长时间无响应，请按官方页面提示重新操作。
          </p>
        </div>
        {error && (
          <p role="alert" className="wb-error wbx-fs-alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  const renderFieldIcon = (field: DesktopField) => {
    if (field.role === 'phone') {
      return <Smartphone size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
    }
    if (field.role === 'password' || field.type === 'password') {
      return <Lock size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
    }
    if (field.role === 'math') {
      return <Calculator size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
    }
    if (field.role === 'sms_code' || field.role === 'voice_code') {
      return <KeyRound size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
    }
    if (source === 'baize' || source === 'benlai') {
      return <Building2 size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
    }
    return <User size={16} className="wbx-fs-input__icon" aria-hidden="true" />;
  };

  const qrReady = qr.key === qrKey && !!qr.url;
  const qrExpired = desktop.qr_state === 'expired';
  const qrAppBadgeLabel = lighthouseQr
    ? '美团App 扫码认证'
    : boardQr
      ? '大象 / 美团 扫码认证'
      : '钉钉 App 扫码授权';

  return (
    <div className="wb-auth-session wbx-auth-panel">
      {desktop.official_feedback && (
        <p
          role="alert"
          className={
            desktop.official_feedback_kind === 'sms_sent'
              ? 'wb-success'
              : desktop.official_feedback_kind === 'voice_required'
                ? 'wb-muted'
                : 'wb-error'
          }
        >
          {desktop.official_feedback}
        </p>
      )}
      {desktop.official_feedback_detail && (
        <p className="wb-muted">{desktop.official_feedback_detail}</p>
      )}
      {source === 'xiaoxiang' && desktop.window_visible === false && (
        <p className="wb-muted">
          {boardQr
            ? '认证在后台自动进行，请用大象扫描面板中的二维码完成看板登录。'
            : desktop.board_reused
              ? '认证在后台自动进行；本机保留知了看板登录态，本次只需用美团App扫描面板中的二维码，完成后自动连接看板。'
              : '认证在后台自动进行，请用美团App扫描面板中的二维码；如官方页面无法在后台操作，系统会自动打开登录窗口。'}
        </p>
      )}
      {source === 'xiaoxiang' && consentField && (
        <p className="wb-muted">
          {consentField.filled
            ? '用户协议已由系统自动勾选，可取消勾选；取消后本轮不会再次自动勾选。'
            : '用户协议尚未勾选；勾选后系统会继续官方登录流程。'}
        </p>
      )}
      {source === 'xiaoxiang' && voiceField && (
        <p className="wb-muted">
          官方已进入语音二次验证；语音验证码是动态码，请按提示接听语音电话后填入，系统无法预先知道。
        </p>
      )}
      {source === 'xiaoxiang' &&
        desktop.has_challenge &&
        desktop.challenge_id &&
        desktop.challenge_version && (
          <OfficialVerification
            key={sessionId + desktop.challenge_id}
            apiFetch={apiFetch}
            sessionId={sessionId}
            challengeId={desktop.challenge_id}
            version={desktop.challenge_version}
            disabled={busy || pending || !!desktop.input_pending}
            onCommand={setLastCommand}
          />
        )}

      {qrMode ? (
        <div className="wb-dingtalk-qr wbx-auth-qr-card">
          <div className="wbx-auth-qr-card__top">
            <span className="wbx-auth-qr-card__app-pill">
              <QrCode size={13} />
              <span>{qrAppBadgeLabel}</span>
            </span>
            <span
              className={`wbx-auth-qr-card__state-pill ${
                qrExpired
                  ? 'is-expired'
                  : qrReady
                    ? 'is-ready'
                    : 'is-loading'
              }`}
            >
              {qrExpired
                ? '二维码已过期'
                : qrReady
                  ? '安全码已就绪'
                  : '正在同步安全码'}
            </span>
          </div>

          <div
            className={`wb-dingtalk-qr-image wbx-auth-qr-frame ${
              qrReady ? 'is-ready' : 'is-loading'
            } ${qrExpired ? 'is-expired' : ''}`}
          >
            <span className="wbx-auth-qr-corner is-tl" aria-hidden="true" />
            <span className="wbx-auth-qr-corner is-tr" aria-hidden="true" />
            <span className="wbx-auth-qr-corner is-bl" aria-hidden="true" />
            <span className="wbx-auth-qr-corner is-br" aria-hidden="true" />

            {qrReady ? (
              <img
                className={lighthouseQr || boardQr ? 'wb-qr-sharp' : undefined}
                src={qr.url}
                alt={
                  lighthouseQr
                    ? '美团App登录二维码'
                    : boardQr
                      ? '知了看板登录二维码'
                      : '钉钉登录二维码'
                }
              />
            ) : (
              <div className="wbx-auth-qr-placeholder">
                <div className="wbx-auth-qr-placeholder__icon-wrap" aria-hidden="true">
                  <QrCode size={34} className="wbx-auth-qr-placeholder__icon" />
                  {!qrExpired && (
                    <Loader2 size={16} className="wbx-auth-qr-placeholder__spinner wbx-fs-spin" />
                  )}
                </div>
                <p role="status" className="wb-muted wbx-auth-qr-placeholder__text">
                  {qr.key === qrKey && qr.error
                    ? qr.error
                    : lighthouseQr
                      ? qrExpired
                        ? '二维码已过期，请点击刷新重新获取。'
                        : '正在准备美团登录二维码…'
                      : boardQr
                        ? qrExpired
                          ? '二维码已过期，请点击刷新重新获取。'
                          : '正在准备知了看板二维码…'
                        : '正在准备钉钉二维码…'}
                </p>
              </div>
            )}
          </div>

          <p
            role="status"
            className={qrExpired ? 'wb-error' : 'wb-muted'}
          >
            {lighthouseQr
              ? qrExpired
                ? '二维码已过期，请点击刷新后重新扫码。'
                : desktop.board_reused
                  ? '请用美团App扫码完成灯塔登录；本机保留知了看板登录态，完成后自动连接看板，无需再扫大象。'
                  : '请打开美团App，使用扫一扫扫描二维码完成灯塔登录；如官方要求安全验证，可在认证面板或自动打开的官方窗口中完成。'
              : boardQr
                ? qrExpired
                  ? '二维码已过期，请点击刷新后重新扫码，无需重新发送短信。'
                  : desktop.lighthouse_reused
                    ? '灯塔会话仍有效，已跳过美团扫码；请用大象扫码完成知了看板登录。'
                    : desktop.board_reused
                      ? '本机保留的看板登录态已失效；请用大象扫码完成知了看板登录。'
                      : '灯塔登录已完成；请用大象或美团扫码完成知了看板登录，无需再发送短信。'
                : qrExpired
                  ? '二维码已过期，请刷新后重新扫码。'
                  : '使用手机钉钉扫一扫，确认后自动连接。'}
          </p>

          <div className="wbx-auth-qr-steps" aria-hidden="true">
            <span className="wbx-auth-qr-step">
              <b>1</b> 打开手机端扫一扫
            </span>
            <span className="wbx-auth-qr-step-sep">→</span>
            <span className="wbx-auth-qr-step">
              <b>2</b> 扫描上方安全码
            </span>
            <span className="wbx-auth-qr-step-sep">→</span>
            <span className="wbx-auth-qr-step">
              <b>3</b> 手机确认自动连接
            </span>
          </div>

          <div className="wb-row wbx-auth-qr-actions">
            <button
              type="button"
              className="wb-button wbx-fs-code-btn"
              disabled={disabled || refresh?.enabled === false}
              onClick={() =>
                refresh ? void send(refresh) : setQrRetry(value => value + 1)
              }
            >
              <RefreshCw size={14} className={busy || pending ? 'wbx-fs-spin' : ''} />
              <span>{refresh ? '刷新二维码' : '重新读取二维码'}</span>
            </button>
          </div>

          {pending && (
            <p role="status" className="wb-muted">
              操作已提交，正在等待平台确认。
            </p>
          )}
        </div>
      ) : (
        <>
          {retry && (
            <div className="wb-auth-submitted wbx-auth-submitted-bar">
              <span>企业账号 {submitted?.account || ''} 已提交</span>
              <button
                type="button"
                className="wb-link"
                onClick={() => setEditingAccount(true)}
              >
                修改账号
              </button>
            </div>
          )}

          {!fields.length ? (
            <div className="wbx-auth-empty-form" role="status">
              <Loader2 size={18} className="wbx-fs-spin text-[#00AEEC]" />
              <p className="wb-muted">
                {source === 'xiaoxiang' && desktop.form_detection === 'not_detected'
                  ? '正在等待官方登录页面就绪；如窗口已关闭，请重新点击登录（灯塔登录已保留，无需重新发送短信）。'
                  : desktop.form_detection === 'not_detected' ||
                      desktop.form_detection === 'qr_only'
                    ? '暂未识别到可用的内部登录表单；不会自动打开外部页面或发送验证码。'
                    : '正在准备登录表单…'}
              </p>
            </div>
          ) : (
            <form
              className="wb-internal-login-form wbx-fs-form"
              onSubmit={event => {
                event.preventDefault();
                void send();
              }}
            >
              {shownFields.map(field => {
                if (field.type === 'checkbox') {
                  const checked =
                    values[field.id] !== undefined
                      ? values[field.id] === 'true'
                      : initialValue(field) !== undefined
                        ? initialValue(field) === 'true'
                        : !!field.filled;
                  return (
                    <label
                      key={field.id}
                      className="wb-auth-consent wbx-auth-consent-card"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={event =>
                          setValues(v => ({
                            ...v,
                            [field.id]: String(event.target.checked),
                          }))
                        }
                      />
                      <span>{field.label || '同意平台登录授权'}</span>
                    </label>
                  );
                }

                const label = fieldLabel(field);
                const hint = fieldHint(field, source, captcha);
                const placeholder = fieldPlaceholder(field, source);
                const isPassword =
                  field.type === 'password' || field.role === 'password';
                const passwordVisible = !!visiblePasswords[field.id];
                const isCodeLike = ['sms_code', 'voice_code', 'math'].includes(
                  field.role || '',
                );
                const currentValue =
                  values[field.id] ?? initialValue(field) ?? '';
                const hasValidCaptchaImg =
                  field.role === 'math' &&
                  captcha?.image &&
                  /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(
                    captcha.image,
                  ) &&
                  captcha.image.length < 360000;

                return (
                  <div
                    key={field.id}
                    className="wb-auth-field wbx-fs-field"
                  >
                    <div className="wbx-fs-field__head">
                      <label
                        htmlFor={`source-field-${field.id}`}
                        className="wbx-fs-field__label"
                      >
                        {label}
                      </label>
                      <span className="wbx-fs-field__hint">{hint}</span>
                    </div>

                    <div className="wb-auth-input-row wbx-fs-input-row">
                      <div
                        className={`wbx-fs-input-wrap${
                          disabled ? ' is-disabled' : ''
                        }${currentValue.trim() ? ' is-complete' : ''}`}
                      >
                        {renderFieldIcon(field)}
                        <input
                          id={`source-field-${field.id}`}
                          aria-label={label}
                          type={
                            isPassword
                              ? passwordVisible
                                ? 'text'
                                : 'password'
                              : field.role === 'phone'
                                ? 'tel'
                                : 'text'
                          }
                          inputMode={
                            ['phone', 'sms_code', 'voice_code', 'math'].includes(
                              field.role || '',
                            )
                              ? 'numeric'
                              : undefined
                          }
                          value={currentValue}
                          autoComplete="off"
                          maxLength={4096}
                          disabled={disabled}
                          placeholder={placeholder}
                          onChange={event =>
                            setValues(v => ({
                              ...v,
                              [field.id]: event.target.value,
                            }))
                          }
                          className={`wb-fengshen-input wbx-fs-input${
                            isCodeLike ? ' is-code' : ''
                          }`}
                        />
                        {isPassword && (
                          <button
                            type="button"
                            className="wbx-auth-pwd-toggle"
                            aria-label={passwordVisible ? '隐藏密码' : '显示密码'}
                            title={passwordVisible ? '隐藏密码' : '显示密码'}
                            tabIndex={-1}
                            onClick={() =>
                              setVisiblePasswords(prev => ({
                                ...prev,
                                [field.id]: !prev[field.id],
                              }))
                            }
                          >
                            {passwordVisible ? (
                              <EyeOff size={15} />
                            ) : (
                              <Eye size={15} />
                            )}
                          </button>
                        )}
                      </div>

                      {field.role === 'phone' && smsButton}

                      {field.role === 'math' && (
                        <div className="wbx-auth-captcha-inline">
                          {hasValidCaptchaImg && (
                            <div className="wbx-auth-captcha-img-box">
                              <img
                                src={captcha!.image}
                                alt="商翼算式验证码"
                              />
                            </div>
                          )}
                          {captchaRefresh && (
                            <button
                              type="button"
                              className="wb-button wbx-fs-code-btn is-captcha-refresh"
                              disabled={disabled}
                              onClick={() => void send(captchaRefresh)}
                              title="刷新算式验证码"
                            >
                              <RefreshCw size={13} />
                              <span>刷新算式</span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>

                    {field.role === 'math' && (
                      <div className="wb-auth-math wbx-auth-math-caption">
                        {captcha?.state === 'solved' ? (
                          <span className="wb-muted">
                            {captcha.expression} = {captcha.answer}
                            ，已自动计算，可修改。
                          </span>
                        ) : (
                          <span className="wb-muted">
                            {captcha?.state === 'recognizing'
                              ? '正在自动识别，也可直接填写答案。'
                              : captcha?.state === 'unavailable'
                                ? '算式暂未加载，请刷新后填写。'
                                : '未能可靠识别，请填写算式答案。'}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {!fields.some(f => f.role === 'phone') && smsButton}

              {mathFields.length > 0 && captcha?.state === 'unavailable' ? (
                <p className="wb-muted">
                  算式尚未加载；请点击上方“刷新算式”后再登录。
                </p>
              ) : (
                <div className="wbx-fs-actions">
                  <button
                    className="wb-primary wbx-fs-submit-btn"
                    type="submit"
                    disabled={
                      disabled || !mathReady || !submit || submit.enabled === false
                    }
                  >
                    {disabled ? (
                      <Loader2 size={16} className="wbx-fs-spin" />
                    ) : (
                      <ShieldCheck size={16} />
                    )}
                    <span>
                      {disabled
                        ? '正在验证并登录…'
                        : !submit?.label || submit.label === '登录'
                          ? '立即验证并登录'
                          : submit.label}
                    </span>
                  </button>
                </div>
              )}

              {pending && (
                <p role="status" className="wb-muted">
                  操作已提交，正在等待平台确认。
                </p>
              )}
            </form>
          )}

          {!!lastSms && !pending && !desktop.official_feedback && (
            <p role="status" className="wb-muted">
              已操作验证码发送请求，尚未读到官方发送结果。倒计时仅限制重复操作，不代表短信已发送。
            </p>
          )}
        </>
      )}

      {(error || desktop.input_error) && (
        <p role="alert" className="wb-error wbx-fs-alert">
          {error || desktop.input_error}
        </p>
      )}
      {uncertain && (
        <p className="wb-muted">
          操作结果尚未确认；再次操作时会先读取状态，不会自动重发验证码。
        </p>
      )}
    </div>
  );
}
