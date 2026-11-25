// @ts-nocheck
import React, { useEffect, useRef, useState } from 'react';
import { Building2, Compass, Layers, Radar, RefreshCw, UsersRound, X } from 'lucide-react';
import {
  AUTH_PREFLIGHT_CANCEL_EVENT as PREFLIGHT_CANCELLED_EVENT,
  AUTH_PREFLIGHT_EVENT as PREFLIGHT_EVENT,
  AUTH_PREFLIGHT_READY_EVENT as PREFLIGHT_RESOLVED_EVENT,
} from '../lib/authPreflight';
import { platformAuthRequest as fetchPlatformAuthJson } from '../lib/platformAuthApi';
import { getPlatformCardBadge, getPlatformStatusCluster } from '../lib/workbench';
import { systemLabel } from '../lib/platformCatalog';
import { SourceLoginPanel } from './SourceLoginPanel';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { isPlatformStatusRecordEqual } from '../lib/perfUtils';

function getActionLabel(_source: string, _status: any) {
  return '登录';
}

function getCapabilitySummary(source: string, status: any) {
  if (status.offline) return '功能状态暂不可读，请重试';
  if (status.busy) return '认证进行中，完成后检测功能';
  if (!status.saved || ['signed_out', 'login_required'].includes(status.state || '')) {
    return '需要登录后检查功能权限';
  }
  if (source === 'xiaoxiang') {
    const stationsVerified = status.capabilities?.stations?.verified === true;
    const boardStage = status.stages?.board;
    return `${stationsVerified ? '站点目录已验证' : '站点目录待查询验证'} · ${
      boardStage === 'ready'
        ? '知了连接已验证，数据权限以具体查询为准'
        : boardStage === 'error'
          ? '知了需要重新认证'
          : '知了尚未确认，日分析权限待验证'
    }`;
  }
  if (
    source === 'fengshen' &&
    (status.capabilities?.cities?.verified || status.capabilities?.stations?.verified)
  ) {
    return `${status.capabilities?.stations?.verified ? '站点目录已验证' : '城市目录已验证'} · 账单权限以具体查询为准`;
  }
  return status.state === 'ready'
    ? '会话已验证，数据权限以具体查询为准'
    : '已保存会话，功能权限尚未验证';
}

// 面板标题统一走 platformCatalog 的全名（xiaoxiang → 小象灯塔），
// 与头部状态灯的短名（灯塔）不同源不重复，满足 V3「无两个灯塔」。
const PLATFORM_DEFS = [
  { key: 'fengshen', label: systemLabel('fengshen'), icon: Compass },
  { key: 'lanorange', label: systemLabel('lanorange'), icon: Layers },
  { key: 'baize', label: systemLabel('baize'), icon: UsersRound },
  { key: 'xiaoxiang', label: systemLabel('xiaoxiang'), icon: Radar },
  { key: 'benlai', label: systemLabel('benlai'), icon: Building2 },
] as const;

export function SystemConnections({
  apiFetch,
  fengshenStatus,
  onOpenFengshen,
  hideTrigger = false,
  open,
  onOpenChange,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  fengshenStatus?: any;
  onOpenFengshen: () => void;
  /** 隐藏自带触发键（改由 `PlatformDock` 做唯一入口），仅保留受控面板。 */
  hideTrigger?: boolean;
  /** 受控展开态；不传则退回内部 state（保持既有调用方零改动）。 */
  open?: boolean;
  /** 受控展开态变更回调。 */
  onOpenChange?: (open: boolean) => void;
}) {
  const fetchRef = useRef(apiFetch);
  fetchRef.current = apiFetch;
  const [statuses, setStatuses] = useState<Record<string, any>>({});
  const [baizeAccount, setBaizeAccount] = useState<any>(null);
  const [internalOpen, setInternalOpen] = useState(false);
  const drawerOpen = typeof open === 'boolean' ? open : internalOpen;
  const setDrawerOpen = (next: boolean) => {
    if (onOpenChange) onOpenChange(next);
    else setInternalOpen(next);
  };
  const [activeSessionKey, setActiveSessionKey] = useState('');
  const [pendingActions, setPendingActions] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [preflightItems, setPreflightItems] = useState<any[]>([]);
  const locksRef = useRef(new Set<string>());
  const checkedVersionsRef = useRef(new Set<string>());
  const lastVersionRef = useRef<Record<string, string>>({});

  function acquireLock(source: string, action: string) {
    if (locksRef.current.has(source)) return false;
    locksRef.current.add(source);
    setPendingActions(prev => ({ ...prev, [source]: action }));
    setErrors(prev => ({ ...prev, [source]: '' }));
    return true;
  }

  function releaseLock(source: string) {
    locksRef.current.delete(source);
    setPendingActions(prev => {
      const next = { ...prev };
      delete next[source];
      return next;
    });
  }

  function updateStatus(source: string, nextStatus: any) {
    const prevVersion = lastVersionRef.current[source];
    if (nextStatus.session_version) {
      lastVersionRef.current[source] = nextStatus.session_version;
    }
    setStatuses(prev => {
      if (isPlatformStatusRecordEqual(prev[source], nextStatus)) {
        return prev;
      }
      return { ...prev, [source]: nextStatus };
    });
    if (
      prevVersion &&
      nextStatus.session_version &&
      prevVersion !== nextStatus.session_version
    ) {
      window.dispatchEvent(
        new CustomEvent('workbench:platform-session-changed', { detail: { source } }),
      );
    }
  }

  function recordError(source: string, err: unknown) {
    setErrors(prev => ({
      ...prev,
      [source]: err instanceof Error ? err.message : '操作未完成，请稍候再试。',
    }));
  }

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('workbench:platform-statuses', { detail: statuses }));
  }, [statuses]);

  useEffect(() => {
    const openHandler = () => setDrawerOpen(true);
    window.addEventListener('workbench:connections', openHandler);
    return () => window.removeEventListener('workbench:connections', openHandler);
  }, []);

  useEffect(() => {
    const preflightHandler = (event: any) => {
      setPreflightItems((event.detail || []).filter((item: any) => item && item.source));
      setDrawerOpen(true);
    };
    window.addEventListener(PREFLIGHT_EVENT, preflightHandler);
    return () => window.removeEventListener(PREFLIGHT_EVENT, preflightHandler);
  }, []);

  const isSourceReady = (source: string) => {
    const item = statuses[source] || (source === 'fengshen' && fengshenStatus) || {};
    return item.state === 'ready' && !item.offline;
  };

  useEffect(() => {
    if (preflightItems.length && !preflightItems.some(item => !isSourceReady(item.source))) {
      setPreflightItems([]);
      window.dispatchEvent(new Event(PREFLIGHT_RESOLVED_EVENT));
    }
  }, [statuses, preflightItems, fengshenStatus]);

  function handleCloseDrawer() {
    if (preflightItems.length) {
      setPreflightItems([]);
      window.dispatchEvent(new Event(PREFLIGHT_CANCELLED_EVENT));
    }
    setDrawerOpen(false);
  }

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    const timers = new Map<string, any>();
    const wrappedFetch = (url: string, init?: RequestInit) =>
      fetchRef.current(url, {
        ...init,
        signal: init?.signal ? AbortSignal.any([controller.signal, init.signal]) : controller.signal,
      });

    async function poll(source: string) {
      if (document.visibilityState === 'visible') {
        try {
          const res = await fetchPlatformAuthJson(
            wrappedFetch,
            `/api/fengshen-downloads/platform-auth/${source}`,
            undefined,
            10000,
          );
          if (!disposed) updateStatus(source, { ...res, offline: false });
        } catch {
          if (!disposed) {
            setStatuses(prev => {
              if (prev[source]?.offline === true) return prev;
              return { ...prev, [source]: { ...prev[source], offline: true } };
            });
          }
        }
      }
      if (!disposed) {
        const delay =
          source === activeSessionKey && ['baize', 'xiaoxiang'].includes(source)
            ? 500
            : drawerOpen || activeSessionKey
              ? 2000
              : 20000;
        timers.set(source, setTimeout(() => void poll(source), delay));
      }
    }

    PLATFORM_DEFS.forEach(({ key }) => void poll(key));
    return () => {
      disposed = true;
      controller.abort();
      timers.forEach(clearTimeout);
    };
  }, [drawerOpen, activeSessionKey]);

  useEffect(() => {
    if (!drawerOpen) return;
    let cancelled = false;
    void fetchPlatformAuthJson(
      apiFetch,
      '/api/fengshen-downloads/platform-auth/baize/accounts',
      undefined,
      15000,
    )
      .then(data => { if (!cancelled) setBaizeAccount(data); })
      .catch(() => { if (!cancelled) setBaizeAccount(null); });
    return () => { cancelled = true; };
  }, [drawerOpen, statuses.baize?.session_version, apiFetch]);

  useEffect(() => {
    for (const { key } of PLATFORM_DEFS) {
      const st = statuses[key];
      const version = st?.session_version;
      if (
        version &&
        st.saved &&
        !st.busy &&
        !st.offline &&
        ['saved', 'partial'].includes(st.state || '') &&
        !locksRef.current.has(key) &&
        !checkedVersionsRef.current.has(key + version) &&
        acquireLock(key, 'verify')
      ) {
        checkedVersionsRef.current.add(key + version);
        fetchPlatformAuthJson(
          fetchRef.current,
          `/api/fengshen-downloads/platform-auth/${key}/check${key === 'xiaoxiang' ? '?deep=true' : ''}`,
          {},
          key === 'xiaoxiang' ? 45000 : 20000,
        )
          .then(res =>
            setStatuses(prev => (prev[key]?.session_version === version ? { ...prev, [key]: res } : prev)),
          )
          .catch(err => recordError(key, err))
          .finally(() => releaseLock(key));
      }
    }
  }, [statuses]);

  useEffect(() => {
    if (
      activeSessionKey &&
      statuses[activeSessionKey]?.state === 'ready' &&
      !statuses[activeSessionKey]?.busy &&
      !statuses[activeSessionKey]?.credential_prompt
    ) {
      setActiveSessionKey('');
    }
  }, [statuses, activeSessionKey]);

  async function handleStartLogin(source: string) {
    if (!acquireLock(source, 'login')) return;
    try {
      const current = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}`,
        undefined,
        10000,
      );
      updateStatus(source, current);
      if (current.state === 'ready') return;
      if ((source === 'xiaoxiang' || source === 'benlai') && current.can_manage === false) {
        recordError(source, new Error('该平台为全局共享连接，请联系管理员或授权维护人完成扫码登录'));
        return;
      }
      setDrawerOpen(false);
      if (source === 'fengshen') {
        onOpenFengshen();
        return;
      }
      setActiveSessionKey(source);
      if (['starting', 'waiting_login', 'refreshing'].includes(current.state || '') || current.busy) {
        return;
      }
      const started = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/source-auth/${source}/start`,
        {},
      );
      updateStatus(source, started);
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  async function handleLogout(source: string) {
    if (!acquireLock(source, 'logout')) return;
    try {
      const current = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}`,
        undefined,
        10000,
      );
      if (!current.session_version) {
        throw new Error('登录状态暂未读到，请稍候再点退出。');
      }
      const loggedOut = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}/logout`,
        { confirm: true, session_version: current.session_version },
        30000,
      );
      updateStatus(source, loggedOut);
      if (activeSessionKey === source) setActiveSessionKey('');
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  const busyAuthSource = PLATFORM_DEFS.find(
    ({ key }) =>
      ['starting', 'waiting_login', 'login_required', 'sms_sent', 'manual_required'].includes(
        statuses[key]?.state || '',
      ) && statuses[key]?.busy,
  );
  const cluster = getPlatformStatusCluster(statuses, fengshenStatus);
  const activeDef = PLATFORM_DEFS.find(item => item.key === activeSessionKey);
  const activeStatus = statuses[activeSessionKey] || {};

  async function handleCredential(action: 'save' | 'skip') {
    const source = activeSessionKey;
    if (!source || !acquireLock(source, 'credential')) return;
    try {
      const next = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/source-auth/${source}/credentials`,
        { action },
        30000,
      );
      updateStatus(source, next);
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }
  const readyCount = PLATFORM_DEFS.filter(item => {
    const st = statuses[item.key] || (item.key === 'fengshen' && fengshenStatus) || {};
    return st.state === 'ready' && !st.offline;
  }).length;

  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        handleCloseDrawer();
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        handleCloseDrawer();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [drawerOpen]);

  return (
    <>
      <div className="wb-connection-dropdown" ref={dropdownRef} data-inert={hideTrigger ? 'true' : undefined}>
        {(!hideTrigger || busyAuthSource) && (
          <button
            className="wb-connection-trigger"
            aria-label="管理系统连接"
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(!drawerOpen)}
          >
            <span className="wb-connection-title">平台登录</span>
            <span className="wb-connection-sep" aria-hidden="true" />
            <span className="wb-connection-cluster" aria-hidden="true">
              {cluster.map(item => (
                <span
                  key={item.key}
                  className={`wb-connection-chip is-${item.tone}`}
                  title={`${item.shortLabel}：${item.statusText}`}
                >
                  <span
                    className={`wb-dot ${
                      item.tone === 'ready'
                        ? 'ready'
                        : item.tone === 'warn'
                          ? 'offline'
                          : item.tone === 'busy'
                            ? 'busy'
                            : ''
                    }`}
                  />
                  <span>{item.shortLabel}</span>
                </span>
              ))}
            </span>
          </button>
        )}

        {drawerOpen && (
          hideTrigger ? (
            <div className="wbx-plat-embed" aria-label="平台登录状态">
              {preflightItems.length > 0 && (
                <div className="wb-preflight-banner mb-2.5" role="status">
                  <strong>本次任务需要先完成认证：</strong>
                  {preflightItems.map(item => item.label).join('、')}
                  。完成认证后任务将自动继续创建，无需重新提交。
                </div>
              )}

              <ul className="wbx-plat-list" role="list" aria-label="业务数据源平台列表">
                {PLATFORM_DEFS.map(({ key, label, icon: Icon }) => {
                  const st = statuses[key] || (key === 'fengshen' && fengshenStatus) || {};
                  const ready = st.state === 'ready' && !st.offline;
                  const canLogout =
                    !!st.saved ||
                    !!st.busy ||
                    ready ||
                    ['starting', 'waiting_login'].includes(st.state || '');
                  const badge = getPlatformCardBadge(st, pendingActions[key]);
                  const accountLine = [st.account_label, st.organization].filter(Boolean).join(' · ');
                  const baizeAccountHint =
                    key === 'baize' && ready && baizeAccount?.account_type
                      ? `${baizeAccount.account_type === 'shanggou' ? '闪购业务账户' : '小象业务账户'}${
                          baizeAccount.region_text ? `（${baizeAccount.region_text}）` : ''
                        }`
                      : '';
                  const baseSubtitle = accountLine || getCapabilitySummary(key, st);
                  const subtitle = baizeAccountHint
                    ? `${baizeAccountHint} · ${baseSubtitle}`
                    : baseSubtitle;
                  const errorMsg = errors[key] || (st.offline ? '连接状态暂不可用，请稍候再试。' : '');

                  return (
                    <li key={key} className={`wbx-plat-row is-${key}`}>
                      <span className={`wbx-plat-row__icon is-${key}`} aria-hidden="true">
                        <Icon size={15} />
                      </span>

                      <div className="wbx-plat-row__main">
                        <div className="wbx-plat-row__top">
                          <span className="wbx-plat-row__name">{label}</span>
                          <span className={`wbx-plat-row__status is-${badge.tone}`}>
                            <span className={`wbx-plat-row__dot is-${badge.tone}`} aria-hidden="true" />
                            <span>{badge.label}</span>
                          </span>
                        </div>
                        <p className="wbx-plat-row__desc" title={subtitle}>
                          {subtitle}
                        </p>
                        {errorMsg && (
                          <p role="alert" className="wbx-plat-row__err">
                            {errorMsg}
                          </p>
                        )}
                      </div>

                      <div className="wbx-plat-row__actions">
                        {!ready && (
                          <button
                            type="button"
                            className="wbx-plat-row__login-btn"
                            disabled={!!pendingActions[key]}
                            onClick={() => void handleStartLogin(key)}
                          >
                            {getActionLabel(key, st)}
                          </button>
                        )}
                        {canLogout && (
                          <button
                            type="button"
                            className="wbx-plat-row__logout-btn"
                            disabled={!!pendingActions[key]}
                            onClick={() => void handleLogout(key)}
                          >
                            退出
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>

              <div className="wbx-plat-foot">
                <span className="wbx-plat-foot__meta tabular-nums">
                  已就绪 <strong>{readyCount}</strong> / {PLATFORM_DEFS.length} 个通道
                </span>
                <button
                  type="button"
                  className="wbx-plat-foot__refresh"
                  title="重新刷新检测平台连接"
                  onClick={() => {
                    for (const { key } of PLATFORM_DEFS) {
                      const st = statuses[key];
                      const version = st?.session_version;
                      if (st?.saved && !st?.busy && !st?.offline && version && acquireLock(key, 'verify')) {
                        fetchPlatformAuthJson(
                          fetchRef.current,
                          `/api/fengshen-downloads/platform-auth/${key}/check${key === 'xiaoxiang' ? '?deep=true' : ''}`,
                          {},
                          key === 'xiaoxiang' ? 45000 : 20000,
                        )
                          .then(res =>
                            setStatuses(prev =>
                              prev[key]?.session_version === version ? { ...prev, [key]: res } : prev,
                            ),
                          )
                          .catch(err => recordError(key, err))
                          .finally(() => releaseLock(key));
                      }
                    }
                  }}
                >
                  <RefreshCw size={12} aria-hidden="true" />
                  <span>检测全部状态</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="wb-connection-popover" role="dialog" aria-label="平台登录状态">
              <div className="wb-popover-header">
                <span className="wb-popover-title">数据源平台通道</span>
                <button
                  type="button"
                  className="wb-popover-close-btn"
                  aria-label="关闭浮窗"
                  onClick={handleCloseDrawer}
                >
                  <X size={15} />
                </button>
              </div>

              <div className="wb-platform-overview-bar mb-2.5">
                <div className="wb-platform-overview-stat">
                  <span className="wb-platform-overview-dot" />
                  <span>
                    数据源通道 · <strong>{readyCount}</strong> / {PLATFORM_DEFS.length} 已就绪
                  </span>
                </div>
                <button
                  type="button"
                  className="wb-platform-refresh-btn"
                  title="重新刷新检测平台连接"
                  onClick={() => {
                    for (const { key } of PLATFORM_DEFS) {
                      const st = statuses[key];
                      const version = st?.session_version;
                      if (st?.saved && !st?.busy && !st?.offline && version && acquireLock(key, 'verify')) {
                        fetchPlatformAuthJson(
                          fetchRef.current,
                          `/api/fengshen-downloads/platform-auth/${key}/check${key === 'xiaoxiang' ? '?deep=true' : ''}`,
                          {},
                          key === 'xiaoxiang' ? 45000 : 20000,
                        )
                          .then(res =>
                            setStatuses(prev =>
                              prev[key]?.session_version === version ? { ...prev, [key]: res } : prev,
                            ),
                          )
                          .catch(err => recordError(key, err))
                          .finally(() => releaseLock(key));
                      }
                    }
                  }}
                >
                  <RefreshCw size={12} />
                  <span>检测状态</span>
                </button>
              </div>

              {preflightItems.length > 0 && (
                <div className="wb-preflight-banner mb-2.5" role="status">
                  <strong>本次任务需要先完成认证：</strong>
                  {preflightItems.map(item => item.label).join('、')}
                  。完成认证后任务将自动继续创建，无需重新提交。
                </div>
              )}

              <div className="wb-platform-card-list">
                {PLATFORM_DEFS.map(({ key, label, icon: Icon }) => {
                  const st = statuses[key] || (key === 'fengshen' && fengshenStatus) || {};
                  const ready = st.state === 'ready' && !st.offline;
                  const isShared = key === 'xiaoxiang' || key === 'benlai';
                  const canManagePlatform = !isShared || st.can_manage !== false;
                  const canLogout =
                    canManagePlatform &&
                    (!!st.saved ||
                      !!st.busy ||
                      ready ||
                      ['starting', 'waiting_login'].includes(st.state || ''));
                  const badge = getPlatformCardBadge(st, pendingActions[key]);
                  return (
                    <section key={key} className={`wb-platform-login-row is-${key}`}>
                      <div className="wb-platform-login-summary">
                        <div className="wb-platform-identity">
                          <span className="wb-platform-avatar" aria-hidden="true">
                            <Icon size={17} />
                          </span>
                          <h3 className="wb-platform-name">{label}</h3>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                              isShared
                                ? 'bg-amber-50 text-amber-700 border border-amber-200/80'
                                : 'bg-sky-50 text-sky-700 border border-sky-200/80'
                            }`}
                          >
                            {isShared ? '全局共享' : '个人独立'}
                          </span>
                        </div>
                        <div className="wb-platform-status-area">
                          <span className={`wb-status-badge is-${badge.tone}`}>
                            <span
                              className={`wb-dot ${
                                badge.tone === 'ready'
                                  ? 'ready'
                                  : badge.tone === 'warn'
                                    ? 'offline'
                                    : badge.tone === 'busy'
                                      ? 'busy'
                                      : ''
                              }`}
                            />
                            <span>{badge.label}</span>
                          </span>
                        </div>
                        <div className="wb-platform-actions">
                          {canManagePlatform ? (
                            <>
                              {!ready && (
                                <button
                                  type="button"
                                  className="wb-button wb-btn-login"
                                  disabled={!!pendingActions[key]}
                                  onClick={() => void handleStartLogin(key)}
                                >
                                  {getActionLabel(key, st)}
                                </button>
                              )}
                              {canLogout && (
                                <button
                                  type="button"
                                  className="wb-button wb-btn-logout"
                                  disabled={!!pendingActions[key]}
                                  onClick={() => void handleLogout(key)}
                                >
                                  退出
                                </button>
                              )}
                            </>
                          ) : (
                            <span className="text-[11px] text-slate-400 select-none">
                              管理员统一维护
                            </span>
                          )}
                        </div>
                      </div>
                      <p className="wb-muted">{getCapabilitySummary(key, st)}</p>
                      {(st.account_label || st.organization) && (
                        <p className="wb-muted">
                          {[st.account_label, st.organization].filter(Boolean).join(' · ')}
                        </p>
                      )}
                      {(errors[key] || st.offline) && (
                        <p role="alert" className="wb-error">
                          {errors[key] || '连接状态暂不可用，请稍候再试。'}
                        </p>
                      )}
                    </section>
                  );
                })}
              </div>
            </div>
          )
        )}
      </div>

      {!!activeDef && (
        <WorkbenchDrawer
          title={activeDef.key === 'lanorange' ? '蓝橙扫码登录' : `${activeDef.label}登录验证`}
          closeLabel="收起登录窗口"
          bodyClassName="wb-auth-session"
          onClose={() => setActiveSessionKey('')}
        >
          {activeStatus.message && (
            <p role="status" className="wb-muted">
              {activeStatus.message}
            </p>
          )}
          {activeStatus.credential_prompt && (
            <section className="wb-auth-credential-prompt">
              <p>
                是否保存 {activeStatus.credential_account || '当前账号'} 的账号密码，以便下次自动登录？
              </p>
              <div className="wb-row">
                <button
                  type="button"
                  className="wb-primary"
                  disabled={!!pendingActions[activeDef.key]}
                  onClick={() => void handleCredential('save')}
                >
                  保存
                </button>
                <button
                  type="button"
                  className="wb-button"
                  disabled={!!pendingActions[activeDef.key]}
                  onClick={() => void handleCredential('skip')}
                >
                  不保存
                </button>
              </div>
              <p className="wb-muted">
                密码仅使用 Windows DPAPI 加密保存在本机；退出登录或切换账号时会同步清除。
              </p>
            </section>
          )}
          {activeStatus.state === 'waiting_login' &&
            activeStatus.session_id &&
            !activeStatus.cancelling && (
              <SourceLoginPanel
                key={activeDef.key + activeStatus.session_id}
                source={activeDef.key}
                sessionId={activeStatus.session_id}
                desktop={activeStatus}
                apiFetch={apiFetch}
              />
            )}
          {!activeStatus.busy &&
            !['starting', 'waiting_login', 'refreshing', 'ready'].includes(
              activeStatus.state || '',
            ) && (
              <button
                className="wb-primary"
                disabled={!!pendingActions[activeDef.key]}
                onClick={() => void handleStartLogin(activeDef.key)}
              >
                {getActionLabel(activeDef.key, activeStatus)}
              </button>
            )}
          {errors[activeDef.key] && (
            <p role="alert" className="wb-error">
              {errors[activeDef.key]}
            </p>
          )}
        </WorkbenchDrawer>
      )}
    </>
  );
}
