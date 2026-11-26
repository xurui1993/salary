// @ts-nocheck
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRightLeft,
  Building2,
  CheckCircle2,
  Clock,
  Compass,
  KeyRound,
  Layers,
  LogIn,
  LogOut,
  Radar,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UserCheck,
  UsersRound,
  X,
} from 'lucide-react';
import {
  AUTH_PREFLIGHT_CANCEL_EVENT as PREFLIGHT_CANCELLED_EVENT,
  AUTH_PREFLIGHT_EVENT as PREFLIGHT_EVENT,
  AUTH_PREFLIGHT_READY_EVENT as PREFLIGHT_RESOLVED_EVENT,
} from '../lib/authPreflight';
import { platformAuthRequest as fetchPlatformAuthJson } from '../lib/platformAuthApi';
import {
  PLATFORM_AUTH_REGISTRY,
  buildPlatformAuthCardViewModels,
  filterPlatformAuthCards,
  summarizePlatformAuthOverview,
  type BaizeAccountMeta,
  type PlatformAuthCardViewModel,
  type PlatformRawAuthStatus,
  type PlatformScopeFilter,
  type PlatformStateFilter,
} from '../lib/platformAuthCenter';
import type { ConnectionChipKey } from '../lib/platformCatalog';
import { isPlatformStatusRecordEqual } from '../lib/perfUtils';
import { SourceLoginPanel } from './SourceLoginPanel';
import { WorkbenchDrawer } from './WorkbenchDrawer';

const PLATFORM_ICONS: Record<ConnectionChipKey, React.ComponentType<{ className?: string; size?: number }>> = {
  fengshen: Compass,
  lanorange: Layers,
  baize: UsersRound,
  xiaoxiang: Radar,
  benlai: Building2,
};

const ACCENT_ICON_STYLES: Record<string, string> = {
  sky: 'bg-sky-50 text-[#008EC4] border border-sky-100/80',
  amber: 'bg-amber-50 text-amber-600 border border-amber-100/80',
  emerald: 'bg-emerald-50 text-emerald-600 border border-emerald-100/80',
  violet: 'bg-violet-50 text-violet-600 border border-violet-100/80',
  indigo: 'bg-indigo-50 text-indigo-600 border border-indigo-100/80',
};

export interface PlatformAuthCenterPageProps {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  active: boolean;
  fengshenStatus?: any;
  onOpenFengshen: () => void;
  onNavigateToSelf?: () => void;
  isAdmin?: boolean;
  canManageSharedAuth?: boolean;
  onToast?: (msg: string, type?: 'info' | 'success' | 'error' | 'warn') => void;
}

export function PlatformAuthCenterPage({
  apiFetch,
  active,
  fengshenStatus,
  onOpenFengshen,
  onNavigateToSelf,
  isAdmin = false,
  canManageSharedAuth = false,
  onToast,
}: PlatformAuthCenterPageProps) {
  const fetchRef = useRef(apiFetch);
  fetchRef.current = apiFetch;
  const onNavigateRef = useRef(onNavigateToSelf);
  onNavigateRef.current = onNavigateToSelf;
  const onToastRef = useRef(onToast);
  onToastRef.current = onToast;

  const [statuses, setStatuses] = useState<Record<string, PlatformRawAuthStatus>>({});
  const [baizeAccount, setBaizeAccount] = useState<BaizeAccountMeta | null>(null);
  const [activeSessionKey, setActiveSessionKey] = useState<string>('');
  const [focusedPlatformKey, setFocusedPlatformKey] = useState<string>('');
  const [pendingActions, setPendingActions] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [preflightItems, setPreflightItems] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [scopeFilter, setScopeFilter] = useState<PlatformScopeFilter>('all');
  const [stateFilter, setStateFilter] = useState<PlatformStateFilter>('all');
  const [lastInspectedAt, setLastInspectedAt] = useState<string>('');

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
    if (!nextStatus || typeof nextStatus !== 'object') return;
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
    const msg = err instanceof Error ? err.message : '操作未完成，请稍候再试。';
    setErrors(prev => ({
      ...prev,
      [source]: msg,
    }));
  }

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('workbench:platform-statuses', { detail: statuses }));
  }, [statuses]);

  const extractRequestedSource = (detail: unknown): string => {
    if (!detail) return '';
    if (typeof detail === 'string') {
      return detail === 'dengta' ? 'xiaoxiang' : detail;
    }
    if (typeof detail === 'object' && detail !== null) {
      const src = (detail as any).source || (detail as any).platform || (detail as any).id;
      if (typeof src === 'string') {
        return src === 'dengta' ? 'xiaoxiang' : src;
      }
    }
    return '';
  };

  useEffect(() => {
    const openHandler = (event: Event) => {
      const requestedSource = extractRequestedSource((event as CustomEvent).detail);
      setScopeFilter('all');
      setStateFilter('all');
      setSearchQuery('');
      if (requestedSource) {
        setFocusedPlatformKey(requestedSource);
      }
      onNavigateRef.current?.();
      if (
        requestedSource &&
        PLATFORM_AUTH_REGISTRY.some(item => item.key === requestedSource)
      ) {
        const current =
          statuses[requestedSource] ||
          (requestedSource === 'fengshen' ? fengshenStatus : undefined) ||
          {};
        if (current.state !== 'ready') {
          void handleStartLogin(requestedSource);
        }
      }
    };
    window.addEventListener('workbench:connections', openHandler);
    return () => window.removeEventListener('workbench:connections', openHandler);
  }, [statuses, fengshenStatus]);

  useEffect(() => {
    const preflightHandler = (event: any) => {
      const items = (event.detail || []).filter((item: any) => item && item.source);
      setPreflightItems(items);
      setScopeFilter('all');
      setStateFilter('all');
      setSearchQuery('');
      if (items[0]?.source) {
        setFocusedPlatformKey(items[0].source);
      }
      onNavigateRef.current?.();
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
      onToastRef.current?.('所需平台认证已完成，正在自动继续任务', 'success');
    }
  }, [statuses, preflightItems, fengshenStatus]);

  function handleCancelPreflight() {
    if (preflightItems.length) {
      setPreflightItems([]);
      window.dispatchEvent(new Event(PREFLIGHT_CANCELLED_EVENT));
    }
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
            : active || activeSessionKey
              ? 2500
              : 20000;
        timers.set(source, setTimeout(() => void poll(source), delay));
      }
    }

    PLATFORM_AUTH_REGISTRY.forEach(({ key }) => void poll(key));
    return () => {
      disposed = true;
      controller.abort();
      timers.forEach(clearTimeout);
    };
  }, [active, activeSessionKey]);

  useEffect(() => {
    if (!active && !statuses.baize?.session_version) return;
    let cancelled = false;
    void fetchPlatformAuthJson(
      apiFetch,
      '/api/fengshen-downloads/platform-auth/baize/accounts',
      undefined,
      15000,
    )
      .then(data => {
        if (!cancelled) setBaizeAccount(data);
      })
      .catch(() => {
        if (!cancelled) setBaizeAccount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [active, statuses.baize?.session_version, apiFetch]);

  useEffect(() => {
    for (const { key } of PLATFORM_AUTH_REGISTRY) {
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
            setStatuses(prev =>
              prev[key]?.session_version === version ? { ...prev, [key]: res } : prev,
            ),
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

  async function handleStartLogin(source: string, forceRelogin = false) {
    if (!acquireLock(source, 'login')) return;
    setFocusedPlatformKey(source);
    try {
      const current = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}`,
        undefined,
        10000,
      );
      updateStatus(source, current);
      if (current.state === 'ready' && !forceRelogin) {
        onToastRef.current?.('当前平台已处于连接就绪状态', 'info');
        return;
      }
      if ((source === 'xiaoxiang' || source === 'benlai') && current.can_manage === false) {
        recordError(
          source,
          new Error('该平台为全局共享连接，请联系系统管理员或授权维护人完成扫码登录'),
        );
        return;
      }
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

  async function handleLogout(source: string, silentForSwitch = false): Promise<boolean> {
    if (!acquireLock(source, 'logout')) return false;
    setFocusedPlatformKey(source);
    try {
      const current = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}`,
        undefined,
        10000,
      );
      if (!current.session_version) {
        if (silentForSwitch) return true;
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
      if (!silentForSwitch) {
        onToastRef.current?.('已安全退出并清除平台会话', 'info');
      }
      return true;
    } catch (err) {
      recordError(source, err);
      return false;
    } finally {
      releaseLock(source);
    }
  }

  async function handleSwitchAccount(card: PlatformAuthCardViewModel) {
    const source = card.entry.key;
    setFocusedPlatformKey(source);
    if (card.canLogout && card.raw.session_version) {
      const ok = await handleLogout(source, true);
      if (!ok) return;
    }
    await handleStartLogin(source, true);
  }

  async function handleCheckPlatform(source: ConnectionChipKey) {
    setFocusedPlatformKey(source);
    const st = statuses[source] || (source === 'fengshen' ? fengshenStatus : undefined) || {};
    const version = st?.session_version;
    if (!acquireLock(source, 'verify')) return;
    try {
      if (st?.saved && !st?.busy && !st?.offline && version) {
        const res = await fetchPlatformAuthJson(
          fetchRef.current,
          `/api/fengshen-downloads/platform-auth/${source}/check${source === 'xiaoxiang' ? '?deep=true' : ''}`,
          {},
          source === 'xiaoxiang' ? 45000 : 20000,
        );
        updateStatus(source, { ...res, offline: false });
      } else {
        const res = await fetchPlatformAuthJson(
          fetchRef.current,
          `/api/fengshen-downloads/platform-auth/${source}`,
          undefined,
          10000,
        );
        updateStatus(source, { ...res, offline: false });
      }
      const now = new Date();
      setLastInspectedAt(
        `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`,
      );
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  async function handleCheckAllPlatforms() {
    const promises = PLATFORM_AUTH_REGISTRY.map(item => handleCheckPlatform(item.key));
    await Promise.allSettled(promises);
    onToastRef.current?.('已完成五大业务平台连通性与权限状态巡检', 'info');
  }

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
      onToastRef.current?.(
        action === 'save' ? '已保存本机加密登录凭据' : '已设为仅当前会话有效',
        'info',
      );
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  const allCards = useMemo(
    () =>
      buildPlatformAuthCardViewModels({
        statuses,
        fengshenFallback: fengshenStatus,
        baizeAccount,
        pendingActions,
        errors,
        isAdmin,
        canManageSharedAuth,
      }),
    [statuses, fengshenStatus, baizeAccount, pendingActions, errors, isAdmin, canManageSharedAuth],
  );

  const overview = useMemo(() => summarizePlatformAuthOverview(allCards), [allCards]);

  const filteredCards = useMemo(
    () =>
      filterPlatformAuthCards(allCards, {
        query: searchQuery,
        scope: scopeFilter,
        state: stateFilter,
      }),
    [allCards, searchQuery, scopeFilter, stateFilter],
  );

  const anyVerifying = Object.keys(pendingActions).length > 0;
  const activeDef = PLATFORM_AUTH_REGISTRY.find(item => item.key === activeSessionKey);
  const activeStatus = statuses[activeSessionKey] || {};

  return (
    <>
      {active && (
        <div className="max-w-[1160px] mx-auto space-y-5 pb-6">
          {/* 顶部页面标题与全局操作栏 */}
          <div className="flex flex-wrap items-end justify-between gap-4 pt-1">
            <div>
              <h2 className="text-[20px] font-bold text-[#18191C] tracking-tight leading-tight">
                平台授权与系统账户中心
              </h2>
              <p className="text-[13px] text-[#61666D] mt-1">
                集中管理各大业务平台登录会话、切换绑定账户、维护本机加密凭据与子功能权限探针
                {lastInspectedAt ? ` · 最近巡检 ${lastInspectedAt}` : ''}
              </p>
            </div>

            <div className="flex items-center gap-2.5 shrink-0">
              <button
                type="button"
                disabled={anyVerifying}
                onClick={() => void handleCheckAllPlatforms()}
                className="h-9 inline-flex items-center gap-1.5 rounded-[11px] bg-[#00AEEC] hover:bg-[#009CD6] text-white px-4 text-[12.5px] font-semibold shadow-[0_8px_20px_-10px_rgba(0,174,236,0.85)] transition cursor-pointer whitespace-nowrap disabled:opacity-60"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${anyVerifying ? 'animate-spin' : ''}`} />
                <span>一键巡检全部通道</span>
              </button>
            </div>
          </div>

          {/* 预检拦截引导横幅（当发起采集/核算任务触发认证需求时显示） */}
          {preflightItems.length > 0 && (
            <div
              role="status"
              className="rounded-2xl border border-amber-300/90 bg-amber-50/90 px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 shadow-xs"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-8 h-8 rounded-[10px] bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-4 h-4" />
                </span>
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-amber-950">
                    当前任务需要先完成平台授权：
                    {preflightItems.map(item => item.label).join('、')}
                  </div>
                  <div className="text-[12px] text-amber-800 mt-0.5">
                    完成下方对应平台的登录验证后，原任务将自动继续执行，无需重新提交。
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {preflightItems[0]?.source && (
                  <button
                    type="button"
                    onClick={() => void handleStartLogin(preflightItems[0].source)}
                    className="h-8 px-3 rounded-[9px] bg-amber-600 hover:bg-amber-700 text-white text-[12px] font-semibold transition cursor-pointer"
                  >
                    立即前往验证
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCancelPreflight}
                  className="h-8 px-2.5 rounded-[9px] border border-amber-300 bg-white/80 hover:bg-white text-amber-900 text-[12px] font-medium transition cursor-pointer"
                >
                  取消等待
                </button>
              </div>
            </div>
          )}

          {/* 顶部 4 卡片连通性健康概览条 */}
          <div className="rounded-2xl bg-white border border-slate-200/80 shadow-[var(--wbx-shadow-xs)] grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-slate-100 overflow-hidden">
            <button
              type="button"
              onClick={() => {
                setScopeFilter('all');
                setStateFilter('all');
              }}
              className={`relative px-5 py-4 text-left transition-colors cursor-pointer ${
                scopeFilter === 'all' && stateFilter === 'all'
                  ? 'bg-sky-50/35'
                  : 'hover:bg-slate-50/75'
              }`}
            >
              <div className="text-[12px] font-medium text-[#61666D]">全部接入平台</div>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="text-[22px] font-semibold tracking-tight text-[#18191C] tabular-nums leading-none">
                  {overview.readyCount}
                  <span className="text-[15px] font-normal text-[#9499A0]">
                    {' '}
                    / {overview.totalCount}
                  </span>
                </span>
                <span className="text-[11.5px] text-[#9499A0]">通道已连接就绪</span>
              </div>
              {scopeFilter === 'all' && stateFilter === 'all' && (
                <span
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-[#00AEEC]"
                  aria-hidden="true"
                />
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                setScopeFilter('personal');
                setStateFilter('all');
              }}
              className={`relative px-5 py-4 text-left transition-colors cursor-pointer ${
                scopeFilter === 'personal' ? 'bg-sky-50/35' : 'hover:bg-slate-50/75'
              }`}
            >
              <div className="text-[12px] font-medium text-[#61666D]">个人独立通道</div>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="text-[22px] font-semibold tracking-tight text-[#008EC4] tabular-nums leading-none">
                  {overview.personalReadyCount}
                  <span className="text-[15px] font-normal text-[#9499A0]">
                    {' '}
                    / {overview.personalCount}
                  </span>
                </span>
                <span className="text-[11.5px] text-[#9499A0]">空间隔离 · 独立换号</span>
              </div>
              {scopeFilter === 'personal' && (
                <span
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-[#00AEEC]"
                  aria-hidden="true"
                />
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                setScopeFilter('shared');
                setStateFilter('all');
              }}
              className={`relative px-5 py-4 text-left transition-colors cursor-pointer ${
                scopeFilter === 'shared' ? 'bg-emerald-50/35' : 'hover:bg-slate-50/75'
              }`}
            >
              <div className="text-[12px] font-medium text-[#61666D]">全局共享通道</div>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="text-[22px] font-semibold tracking-tight text-emerald-600 tabular-nums leading-none">
                  {overview.sharedReadyCount}
                  <span className="text-[15px] font-normal text-[#9499A0]">
                    {' '}
                    / {overview.sharedCount}
                  </span>
                </span>
                <span className="text-[11.5px] text-[#9499A0]">一次授权 · 全员共享</span>
              </div>
              {scopeFilter === 'shared' && (
                <span
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-emerald-500"
                  aria-hidden="true"
                />
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                setScopeFilter('all');
                setStateFilter(overview.attentionCount > 0 ? 'attention' : 'idle');
              }}
              className={`relative px-5 py-4 text-left transition-colors cursor-pointer ${
                stateFilter === 'attention' || stateFilter === 'idle'
                  ? 'bg-amber-50/40'
                  : 'hover:bg-slate-50/75'
              }`}
            >
              <div className="text-[12px] font-medium text-[#61666D]">待认证 / 需关注</div>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span
                  className={`text-[22px] font-semibold tracking-tight tabular-nums leading-none ${
                    overview.attentionCount > 0 ? 'text-amber-600' : 'text-[#18191C]'
                  }`}
                >
                  {overview.attentionCount + overview.idleCount}
                </span>
                <span className="text-[11.5px] text-[#9499A0]">
                  {overview.attentionCount > 0
                    ? `${overview.attentionCount} 个需验证`
                    : overview.idleCount > 0
                      ? `${overview.idleCount} 个未登录`
                      : '全部连接正常'}
                </span>
              </div>
              {(stateFilter === 'attention' || stateFilter === 'idle') && (
                <span
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-amber-500"
                  aria-hidden="true"
                />
              )}
            </button>
          </div>

          {/* 筛选与检索工具栏 */}
          <div className="rounded-2xl bg-white border border-slate-200/80 shadow-[var(--wbx-shadow-xs)] px-5 py-3.5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3 flex-1 min-w-[240px]">
              <div className="relative flex-1 max-w-[300px] min-w-[200px]">
                <Search className="w-3.5 h-3.5 text-[#9499A0] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="搜索平台名称、绑定账号或关联模块..."
                  aria-label="搜索平台或绑定账号"
                  className="w-full h-9 rounded-[11px] border border-slate-200/90 bg-[#F8FAFC] focus:bg-white pl-8.5 pr-7 text-[12.5px] text-[#18191C] placeholder:text-[#9499A0] transition focus:outline-none focus:border-[#00AEEC] focus:ring-3 focus:ring-[#00AEEC]/15"
                />
                {searchQuery && (
                  <button
                    type="button"
                    aria-label="清空搜索"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#9499A0] hover:text-[#18191C] cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              {/* 通道归属分段控件 */}
              <div
                className="inline-flex items-center h-9 p-1 rounded-[11px] bg-slate-100/90 border border-slate-200/60"
                role="group"
                aria-label="按通道归属筛选"
              >
                {(
                  [
                    ['all', `全部 (${overview.totalCount})`],
                    ['personal', `个人独立 (${overview.personalCount})`],
                    ['shared', `全局共享 (${overview.sharedCount})`],
                  ] as [PlatformScopeFilter, string][]
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setScopeFilter(key)}
                    className={`h-7 px-3 rounded-[8px] text-[12px] font-medium transition whitespace-nowrap cursor-pointer tabular-nums ${
                      scopeFilter === key
                        ? 'bg-white text-[#18191C] shadow-2xs font-semibold'
                        : 'text-[#61666D] hover:text-[#18191C]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* 连接状态分段控件 */}
            <div className="flex items-center gap-2.5">
              <div
                className="inline-flex items-center h-9 p-1 rounded-[11px] bg-slate-100/90 border border-slate-200/60"
                role="group"
                aria-label="按连接状态筛选"
              >
                {(
                  [
                    ['all', '全部状态'],
                    ['ready', '已就绪'],
                    ['attention', '需验证'],
                    ['idle', '未登录'],
                  ] as [PlatformStateFilter, string][]
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setStateFilter(key)}
                    className={`h-7 px-2.5 rounded-[8px] text-[12px] font-medium transition whitespace-nowrap cursor-pointer ${
                      stateFilter === key
                        ? 'bg-white text-[#18191C] shadow-2xs font-semibold'
                        : 'text-[#61666D] hover:text-[#18191C]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* 平台账户卡片响应式网格（可扩展架构） */}
          {filteredCards.length === 0 ? (
            <div className="rounded-2xl bg-white border border-slate-200/80 p-12 text-center space-y-3">
              <div className="w-10 h-10 rounded-2xl bg-slate-100 text-[#61666D] flex items-center justify-center mx-auto">
                <KeyRound className="w-5 h-5" />
              </div>
              <div className="text-[14px] font-semibold text-[#18191C]">
                未找到符合筛选条件的业务平台
              </div>
              <p className="text-[12.5px] text-[#61666D] max-w-md mx-auto">
                您可以尝试清空搜索关键词或切换至「全部」分类查看所有已接入的平台系统通道。
              </p>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setScopeFilter('all');
                  setStateFilter('all');
                }}
                className="h-8 px-3.5 rounded-[9px] border border-slate-200 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#18191C] transition cursor-pointer"
              >
                重置筛选条件
              </button>
            </div>
          ) : (
            <div
              className="grid grid-cols-1 lg:grid-cols-2 gap-4"
              role="list"
              aria-label="业务系统平台账户卡片列表"
            >
              {filteredCards.map(card => {
                const { entry, badge } = card;
                const Icon = PLATFORM_ICONS[entry.key] || Compass;
                const isFocused = focusedPlatformKey === entry.key;
                const pendingAction = pendingActions[entry.key];

                return (
                  <article
                    key={entry.key}
                    role="listitem"
                    data-platform-card={entry.key}
                    className={`rounded-2xl bg-white border transition-colors duration-150 flex flex-col justify-between overflow-hidden ${
                      isFocused
                        ? 'border-[#00AEEC]/65 shadow-[0_4px_20px_-6px_rgba(0,174,236,0.2)]'
                        : 'border-slate-200/85 shadow-[var(--wbx-shadow-xs)] hover:border-slate-300/90'
                    }`}
                  >
                    <div className="p-5 space-y-4">
                      {/* 1. 头部：平台身份、业务线与唯一实时连接状态 */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3.5 min-w-0">
                          <span
                            className={`w-10 h-10 rounded-[12px] flex items-center justify-center shrink-0 ${
                              ACCENT_ICON_STYLES[entry.accent] || ACCENT_ICON_STYLES.sky
                            }`}
                            aria-hidden="true"
                          >
                            <Icon size={19} />
                          </span>

                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h3 className="text-[15.5px] font-bold text-[#18191C] tracking-tight">
                                {entry.displayName}
                              </h3>
                              <span className="text-[12px] text-[#9499A0]" aria-hidden="true">
                                ·
                              </span>
                              <span
                                className={`text-[12px] font-medium ${
                                  entry.scope === 'shared' ? 'text-emerald-700' : 'text-[#008EC4]'
                                }`}
                              >
                                {entry.scopeLabel}
                              </span>
                            </div>

                            <div className="text-[12px] text-[#61666D] mt-0.5 flex items-center gap-1.5 flex-wrap">
                              <span>{entry.businessLine}</span>
                              <span className="text-[#C9CDD4]" aria-hidden="true">
                                ·
                              </span>
                              <span>{entry.authMethodLabel}</span>
                            </div>
                          </div>
                        </div>

                        {/* 右上角实时连接状态指示 */}
                        <div
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[9px] text-[12px] font-semibold shrink-0 tabular-nums ${
                            badge.tone === 'ready'
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/70'
                              : badge.tone === 'warn'
                                ? 'bg-amber-50 text-amber-700 border border-amber-200/70'
                                : badge.tone === 'busy'
                                  ? 'bg-sky-50 text-[#008EC4] border border-sky-200/70'
                                  : 'bg-slate-100 text-[#61666D] border border-slate-200/70'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              badge.tone === 'ready'
                                ? 'bg-emerald-500'
                                : badge.tone === 'warn'
                                  ? 'bg-amber-500'
                                  : badge.tone === 'busy'
                                    ? 'bg-[#00AEEC]'
                                    : 'bg-slate-400'
                            }`}
                            aria-hidden="true"
                          />
                          <span>{badge.label}</span>
                        </div>
                      </div>

                      {/* 2. 当前绑定账户与组织归属区（无嵌套卡片阴影，采用细腻发丝线分割） */}
                      <div className="pt-3.5 border-t border-slate-100 grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div className="min-w-0">
                          <div className="text-[11.5px] font-medium text-[#9499A0]">
                            当前绑定系统账户
                          </div>
                          <div className="mt-1 flex items-center gap-1.5 min-w-0">
                            <UserCheck
                              className={`w-3.5 h-3.5 shrink-0 ${
                                card.isReady
                                  ? 'text-emerald-600'
                                  : card.raw.account_label
                                    ? 'text-[#008EC4]'
                                    : 'text-[#9499A0]'
                              }`}
                            />
                            <span
                              className={`text-[13px] font-semibold truncate ${
                                card.isReady || card.raw.account_label
                                  ? 'text-[#18191C]'
                                  : 'text-[#61666D]'
                              }`}
                              title={card.accountTitle}
                            >
                              {card.accountTitle}
                            </span>
                          </div>
                          {(card.accountOrganization || card.accountSubtypeLabel) && (
                            <div
                              className="text-[11.5px] text-[#61666D] mt-0.5 truncate"
                              title={
                                [card.accountSubtypeLabel, card.accountOrganization]
                                  .filter(Boolean)
                                  .join(' · ')
                              }
                            >
                              {[card.accountSubtypeLabel, card.accountOrganization]
                                .filter(Boolean)
                                .join(' · ')}
                            </div>
                          )}
                        </div>

                        <div className="min-w-0">
                          <div className="text-[11.5px] font-medium text-[#9499A0]">
                            会话与本机凭据策略
                          </div>
                          <div className="mt-1 text-[12.5px] font-medium text-[#18191C] truncate">
                            {card.credentialStatusText}
                          </div>
                          <div
                            className="text-[11.5px] text-[#61666D] mt-0.5 truncate"
                            title={card.capabilitySummary}
                          >
                            {card.capabilitySummary}
                          </div>
                        </div>
                      </div>

                      {/* 3. 细分能力验证探针矩阵 */}
                      <div className="pt-3 border-t border-slate-100 space-y-2">
                        <div className="flex items-center justify-between text-[11.5px]">
                          <span className="font-medium text-[#61666D]">子通道与权限探针校验</span>
                          <span className="text-[#9499A0] truncate max-w-[260px]">
                            关联：{entry.usedByModules.join(' / ')}
                          </span>
                        </div>

                        <div className="grid grid-cols-3 gap-2 pt-0.5">
                          {card.probes.map(probe => (
                            <div
                              key={probe.id}
                              title={probe.description}
                              className="px-2.5 py-2 rounded-[10px] bg-[#F8FAFC] border border-slate-200/65 flex flex-col justify-between gap-1"
                            >
                              <span className="text-[11.5px] text-[#61666D] truncate">
                                {probe.label}
                              </span>
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                    probe.tone === 'ready'
                                      ? 'bg-emerald-500'
                                      : probe.tone === 'warn'
                                        ? 'bg-amber-500'
                                        : 'bg-slate-300'
                                  }`}
                                  aria-hidden="true"
                                />
                                <span
                                  className={`text-[12px] font-semibold truncate ${
                                    probe.tone === 'ready'
                                      ? 'text-emerald-700'
                                      : probe.tone === 'warn'
                                        ? 'text-amber-700'
                                        : 'text-[#61666D]'
                                  }`}
                                >
                                  {probe.statusText}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* 错误提示（如有） */}
                      {card.errorText && (
                        <div
                          role="alert"
                          className="rounded-[10px] bg-rose-50/90 border border-rose-200/80 px-3 py-2 text-[12px] text-rose-700 flex items-center justify-between gap-2"
                        >
                          <span>{card.errorText}</span>
                          <button
                            type="button"
                            onClick={() =>
                              setErrors(prev => {
                                const next = { ...prev };
                                delete next[entry.key];
                                return next;
                              })
                            }
                            className="text-rose-500 hover:text-rose-800 shrink-0 cursor-pointer"
                            aria-label="忽略错误提示"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </div>

                    {/* 4. 底部操作栏：登录 / 切换账号 / 重新检测 / 退出登录 */}
                    <div className="px-5 py-3 bg-[#F8FAFC] border-t border-slate-100 flex flex-wrap items-center justify-between gap-2">
                      <div className="text-[11.5px] text-[#61666D] truncate max-w-[240px]">
                        {card.canManage
                          ? entry.scope === 'shared'
                            ? '您拥有此全局共享通道的维护权限'
                            : '个人工作空间独立隔离保存'
                          : '全局共享通道 · 由管理员或授权人统一维护'}
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          type="button"
                          disabled={Boolean(pendingAction)}
                          onClick={() => void handleCheckPlatform(entry.key)}
                          title="重新检测该平台连接与子功能权限"
                          className="h-8 px-2.5 rounded-[9px] border border-slate-200/90 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#4E5969] inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-55 whitespace-nowrap"
                        >
                          <RefreshCw
                            className={`w-3.5 h-3.5 ${pendingAction === 'verify' ? 'animate-spin' : ''}`}
                          />
                          <span>重新检测</span>
                        </button>

                        {card.canManage && (
                          <>
                            {!card.isReady && (
                              <button
                                type="button"
                                disabled={Boolean(pendingAction)}
                                onClick={() => void handleStartLogin(entry.key)}
                                className="h-8 px-3.5 rounded-[9px] bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold inline-flex items-center gap-1.5 shadow-2xs transition cursor-pointer disabled:opacity-55 whitespace-nowrap"
                              >
                                <LogIn className="w-3.5 h-3.5" />
                                <span>{card.raw.saved ? '继续验证' : '立即登录'}</span>
                              </button>
                            )}

                            {card.canSwitchAccount && (
                              <button
                                type="button"
                                disabled={Boolean(pendingAction)}
                                onClick={() => void handleSwitchAccount(card)}
                                title="退出当前绑定账户并立即登录新账号"
                                className="h-8 px-3 rounded-[9px] border border-sky-200/90 bg-sky-50/70 hover:bg-sky-100/80 text-[#008EC4] text-[12px] font-semibold inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-55 whitespace-nowrap"
                              >
                                <ArrowRightLeft className="w-3.5 h-3.5" />
                                <span>切换账号</span>
                              </button>
                            )}

                            {card.canLogout && (
                              <button
                                type="button"
                                disabled={Boolean(pendingAction)}
                                onClick={() => void handleLogout(entry.key)}
                                title="退出当前平台登录并清除会话与本机凭据"
                                className="h-8 px-2.5 rounded-[9px] border border-slate-200/90 bg-white hover:bg-rose-50 hover:text-rose-600 hover:border-rose-200 text-[#61666D] text-[12px] font-medium inline-flex items-center gap-1 transition cursor-pointer disabled:opacity-55 whitespace-nowrap"
                              >
                                <LogOut className="w-3.5 h-3.5" />
                                <span>退出</span>
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 右侧统一平台认证与凭据管理抽屉（支持从全站任意位置唤起） */}
      {!!activeDef && (
        <WorkbenchDrawer
          title={
            activeDef.key === 'lanorange'
              ? '蓝橙扫码登录'
              : `${activeDef.displayName} · 账号登录验证`
          }
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
                密码仅使用本机加密保存；退出登录或点击「切换账号」时会同步清除。
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
                立即登录
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
