// @ts-nocheck
import React, { useEffect, useRef, useState } from 'react';
import { Compass, Layers, Radar, RefreshCw, UsersRound } from 'lucide-react';
import {
  AUTH_PREFLIGHT_CANCEL_EVENT as PREFLIGHT_CANCELLED_EVENT,
  AUTH_PREFLIGHT_EVENT as PREFLIGHT_EVENT,
  AUTH_PREFLIGHT_READY_EVENT as PREFLIGHT_RESOLVED_EVENT,
} from '../lib/authPreflight';
import { platformAuthRequest as fetchPlatformAuthJson } from '../lib/platformAuthApi';
import { getPlatformCardBadge, getPlatformStatusCluster } from '../lib/workbench';
import { SourceLoginPanel } from './SourceLoginPanel';
import { WorkbenchDrawer } from './WorkbenchDrawer';

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

const PLATFORM_DEFS = [
  { key: 'fengshen', label: '风神', icon: Compass },
  { key: 'lanorange', label: '蓝橙', icon: Layers },
  { key: 'baize', label: '商翼', icon: UsersRound },
  { key: 'xiaoxiang', label: '灯塔', icon: Radar },
] as const;

export function SystemConnections({
  apiFetch,
  fengshenStatus,
  onOpenFengshen,
  hideTrigger = false,
}: {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  fengshenStatus?: any;
  onOpenFengshen: () => void;
  hideTrigger?: boolean;
}) {
  const fetchRef = useRef(apiFetch);
  fetchRef.current = apiFetch;
  const [statuses, setStatuses] = useState<Record<string, any>>({});
  const [drawerOpen, setDrawerOpen] = useState(false);
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
    setStatuses(prev => ({ ...prev, [source]: nextStatus }));
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
          setStatuses(prev => ({ ...prev, [source]: { ...prev[source], offline: true } }));
        }
      }
      if (!disposed) {
        const delay =
          source === activeSessionKey && ['baize', 'xiaoxiang'].includes(source)
            ? 500
            : drawerOpen || activeSessionKey
              ? 2000
              : 10000;
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
    if (activeSessionKey && statuses[activeSessionKey]?.state === 'ready' && !statuses[activeSessionKey]?.busy) {
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
  const readyCount = PLATFORM_DEFS.filter(item => {
    const st = statuses[item.key] || (item.key === 'fengshen' && fengshenStatus) || {};
    return st.state === 'ready' && !st.offline;
  }).length;

  return (
    <>
      {(!hideTrigger || busyAuthSource) && (
        <button
          className="wb-connection-trigger"
          aria-label="管理系统连接"
          onClick={() => setDrawerOpen(true)}
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
        <WorkbenchDrawer title="平台登录" onClose={handleCloseDrawer}>
          <div className="wb-platform-overview-bar">
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
            <div className="wb-preflight-banner" role="status">
              <strong>本次任务需要先完成认证：</strong>
              {preflightItems.map(item => item.label).join('、')}
              。完成认证后任务将自动继续创建，无需重新提交。
            </div>
          )}

          <div className="wb-platform-card-list">
            {PLATFORM_DEFS.map(({ key, label, icon: Icon }) => {
              const st = statuses[key] || (key === 'fengshen' && fengshenStatus) || {};
              const ready = st.state === 'ready' && !st.offline;
              const canLogout =
                !!st.saved ||
                !!st.busy ||
                ready ||
                ['starting', 'waiting_login'].includes(st.state || '');
              const badge = getPlatformCardBadge(st, pendingActions[key]);
              return (
                <section key={key} className={`wb-platform-login-row is-${key}`}>
                  <div className="wb-platform-login-summary">
                    <div className="wb-platform-identity">
                      <span className="wb-platform-avatar" aria-hidden="true">
                        <Icon size={17} />
                      </span>
                      <h3 className="wb-platform-name">{label}</h3>
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
        </WorkbenchDrawer>
      )}

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
