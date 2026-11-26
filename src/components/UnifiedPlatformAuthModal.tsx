import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Building2,
  KeyRound,
  Layers,
  Loader2,
  QrCode,
  Radar,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from 'lucide-react';
export interface PlatformModalStatus {
  state?: string;
  message?: string;
  busy?: boolean;
  offline?: boolean;
  session_id?: string;
  cancelling?: boolean;
  credential_prompt?: boolean;
  credential_account?: string;
  [key: string]: unknown;
}

export interface PlatformAuthModalMeta {
  title: string;
  tag: string;
  subtitle: string;
  channelPill: string;
  footnote: string;
  defaultStatusText: string;
  iconKey: 'qr' | 'layers' | 'users' | 'building' | 'radar' | 'shield';
}

export function getPlatformAuthModalMeta(
  sourceKey: string,
  displayName?: string,
): PlatformAuthModalMeta {
  const label = displayName || sourceKey;
  switch (sourceKey) {
    case 'lanorange':
      return {
        title: '蓝橙登录验证',
        tag: '钉钉扫码授权',
        subtitle: '使用手机钉钉扫描下方安全二维码，确认授权后自动同步企业团队会话。',
        channelPill: '钉钉安全通道',
        footnote:
          '扫码确认后蓝橙站点、审批及账单拉取任务将自动恢复；支持多账户独立会话保存与快速切换。',
        defaultStatusText: '请使用手机钉钉扫描下方二维码，确认后自动连接蓝橙',
        iconKey: 'qr',
      };
    case 'lanorange_mdr':
      return {
        title: '新蓝橙登录验证',
        tag: '钉钉扫码授权',
        subtitle: '使用手机钉钉扫描下方安全二维码，确认授权后自动同步新蓝橙业务会话。',
        channelPill: '钉钉安全通道',
        footnote:
          '扫码确认后新蓝橙排班与业务数据通道将自动就绪；与原蓝橙通道会话隔离、互不干扰。',
        defaultStatusText: '请使用手机钉钉扫描下方二维码，确认后自动连接新蓝橙',
        iconKey: 'layers',
      };
    case 'baize':
      return {
        title: '商翼登录验证',
        tag: '企业账号认证',
        subtitle: '输入白泽商翼企业账号、登录密码与算式答案，认证完成后自动同步会话。',
        channelPill: '本机加密会话',
        footnote:
          '登录成功后可选择保存本机加密凭据，后续切换账户或重启工作台时可自动恢复连接。',
        defaultStatusText: '商翼安全认证通道已就绪，请输入企业账号、密码与算式答案',
        iconKey: 'users',
      };
    case 'benlai':
      return {
        title: '本来人力登录验证',
        tag: '商户账号认证',
        subtitle: '输入本来人力商户号/手机号与登录密码，验证通过后自动同步发薪通道会话。',
        channelPill: '本机加密会话',
        footnote:
          '登录成功后可选择保存本机加密凭据，保障发薪平台签约状态与实名核验任务连续运行。',
        defaultStatusText: '本来人力安全认证通道已就绪，请输入商户号/手机号与登录密码',
        iconKey: 'building',
      };
    case 'xiaoxiang':
      return {
        title: '小象灯塔登录验证',
        tag: '双重扫码 / 短信认证',
        subtitle: '按提示完成美团App或大象扫码（或短信动态码核验），自动连接灯塔与知了看板。',
        channelPill: '双阶段安全通道',
        footnote:
          '若本机仍保留有效知了看板或灯塔登录态，系统将自动复用并跳过已认证阶段。',
        defaultStatusText: '小象灯塔认证通道已就绪，请按下方指引完成扫码或短信核验',
        iconKey: 'radar',
      };
    default:
      return {
        title: `${label}登录验证`,
        tag: '平台安全认证',
        subtitle: `完成${label}平台账号核验后，系统将自动同步并加密保存当前工作台会话。`,
        channelPill: '安全认证通道',
        footnote: '核验完成后关联的数据采集与薪资核算任务将自动恢复运行。',
        defaultStatusText: `请在下方完成${label}平台登录验证`,
        iconKey: 'shield',
      };
  }
}

export function normalizePlatformAuthStatusText(
  sourceKey: string,
  rawMessage: string | undefined,
  state: string | undefined,
  meta: PlatformAuthModalMeta,
): string {
  const trimmed = (rawMessage || '').trim();
  if (!trimmed) {
    if (state === 'starting') {
      return `正在初始化${meta.title.replace(/登录验证$/, '')}安全认证会话，请稍候…`;
    }
    return meta.defaultStatusText;
  }
  if (trimmed.includes('请在内部表单完成白泽登录')) {
    if (sourceKey === 'lanorange' || sourceKey === 'lanorange_mdr') {
      return meta.defaultStatusText;
    }
    return '商翼安全认证通道已就绪，请输入企业账号、密码与算式答案';
  }
  if (trimmed.includes('请在内部表单完成本来人力登录')) {
    return '本来人力安全认证通道已就绪，请输入商户号/手机号与登录密码';
  }
  return trimmed;
}

interface UnifiedPlatformAuthModalProps {
  sourceKey: string;
  displayName: string;
  status: PlatformModalStatus;
  pending?: boolean;
  errorMessage?: string;
  startActionLabel?: string;
  onClose: () => void;
  onStartLogin: () => void;
  onCredentialAction: (decision: 'save' | 'skip') => void;
  children?: React.ReactNode;
}

export function UnifiedPlatformAuthModal({
  sourceKey,
  displayName,
  status,
  pending = false,
  errorMessage = '',
  startActionLabel = '立即启动安全认证',
  onClose,
  onStartLogin,
  onCredentialAction,
  children,
}: UnifiedPlatformAuthModalProps) {
  const [animPhase, setAnimPhase] = useState<'entering' | 'entered'>('entering');
  const [waitSeconds, setWaitSeconds] = useState<number>(0);

  const isPreparingSession =
    !status.session_id &&
    (status.state === 'starting' ||
      status.state === 'refreshing' ||
      (pending && status.state !== 'ready' && status.state !== 'error'));

  useEffect(() => {
    if (!isPreparingSession) {
      setWaitSeconds(0);
      return;
    }
    setWaitSeconds(0);
    const timer = window.setInterval(() => {
      setWaitSeconds(prev => prev + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isPreparingSession, sourceKey]);

  useEffect(() => {
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
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const meta = getPlatformAuthModalMeta(sourceKey, displayName);
  const statusText = normalizePlatformAuthStatusText(
    sourceKey,
    status.message,
    status.state,
    meta,
  );
  const isBusy =
    pending ||
    !!status.busy ||
    status.state === 'starting' ||
    status.state === 'refreshing';
  const isWarningState =
    !!status.offline || status.state === 'error' || status.state === 'unknown';

  const renderBadgeIcon = () => {
    switch (meta.iconKey) {
      case 'qr':
        return <QrCode size={20} />;
      case 'layers':
        return <Layers size={20} />;
      case 'users':
        return <Users size={20} />;
      case 'building':
        return <Building2 size={20} />;
      case 'radar':
        return <Radar size={20} />;
      default:
        return <ShieldCheck size={21} />;
    }
  };

  const phaseClass = animPhase === 'entered' ? 'is-entered' : 'is-entering';
  const showStartTrigger =
    !pending &&
    !status.busy &&
    !['starting', 'waiting_login', 'refreshing', 'ready'].includes(status.state || '');

  const modalNode = (
    <div
      className={`wbx-fs-backdrop ${phaseClass}`}
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={meta.title}
        className={`wbx-fs-modal wbx-unified-auth-modal ${phaseClass}`}
      >
        <header className="wbx-fs-modal__head">
          <div className="wbx-fs-modal__lead">
            <span
              className={`wbx-fs-modal__badge is-${sourceKey}`}
              aria-hidden="true"
            >
              {renderBadgeIcon()}
            </span>
            <div className="wbx-fs-modal__heading">
              <div className="wbx-fs-modal__title-row">
                <h2 className="wbx-fs-modal__title">{meta.title}</h2>
                <span className="wbx-fs-modal__tag">{meta.tag}</span>
              </div>
              <p className="wbx-fs-modal__subtitle">{meta.subtitle}</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="收起登录窗口"
            title="收起登录窗口"
            onClick={onClose}
            className="wbx-fs-modal__close"
          >
            <X size={17} />
          </button>
        </header>

        <div className="wbx-fs-modal__body wb-auth-session">
          <div
            role="status"
            className={`wbx-fs-status${isWarningState ? ' is-offline' : ''}`}
          >
            <div className="wbx-fs-status__main">
              {isBusy ? (
                <Loader2
                  size={16}
                  className="wbx-fs-status__icon wbx-fs-spin"
                />
              ) : (
                <Sparkles size={16} className="wbx-fs-status__icon" />
              )}
              <span className="wbx-fs-status__text">{statusText}</span>
            </div>
            <span className="wbx-fs-status__pill">{meta.channelPill}</span>
          </div>

          {status.credential_prompt && (
            <section className="wb-auth-credential-prompt wbx-auth-cred-card">
              <div className="wbx-auth-cred-card__head">
                <span className="wbx-auth-cred-card__icon" aria-hidden="true">
                  <KeyRound size={15} />
                </span>
                <div className="wbx-auth-cred-card__titles">
                  <p className="wbx-auth-cred-card__title">
                    是否保存 {status.credential_account || '当前账号'} 的加密登录凭据？
                  </p>
                  <p className="wb-muted wbx-auth-cred-card__desc">
                    密码仅使用本机加密隔离保存；该账户驻留在多账户列表中时可一键自动重连与切换。
                  </p>
                </div>
              </div>
              <div className="wb-row wbx-auth-cred-card__actions">
                <button
                  type="button"
                  className="wb-primary wbx-fs-submit-btn is-compact"
                  disabled={pending}
                  onClick={() => onCredentialAction('save')}
                >
                  <ShieldCheck size={15} />
                  <span>保存加密凭据</span>
                </button>
                <button
                  type="button"
                  className="wb-button wbx-fs-code-btn is-compact"
                  disabled={pending}
                  onClick={() => onCredentialAction('skip')}
                >
                  仅本次登录
                </button>
              </div>
            </section>
          )}

          {isPreparingSession && (
            <div className="wbx-auth-starting-card" role="status">
              <Loader2 size={22} className="wbx-fs-spin text-[#00AEEC]" />
              <div className="wbx-auth-starting-card__text">
                <p className="wbx-auth-starting-card__title">
                  正在安全沙箱中准备{displayName}登录环境…
                </p>
                <p className="wb-muted">
                  {waitSeconds >= 3
                    ? `正在建立官方安全通道（已用时 ${waitSeconds} 秒），马上就好…`
                    : '系统正在自动加载认证组件，无需在外部浏览器中操作。'}
                </p>
              </div>
            </div>
          )}

          {children}

          {showStartTrigger && (
            <div className="wbx-fs-actions">
              <button
                type="button"
                className="wb-primary wbx-fs-submit-btn"
                disabled={pending}
                onClick={onStartLogin}
              >
                {pending ? (
                  <Loader2 size={16} className="wbx-fs-spin" />
                ) : (
                  <ShieldCheck size={16} />
                )}
                <span>{startActionLabel}</span>
              </button>
            </div>
          )}

          {errorMessage && (
            <p role="alert" className="wb-error wbx-fs-alert">
              {errorMessage}
            </p>
          )}

          <div className="wbx-fs-foot-note">{meta.footnote}</div>
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
