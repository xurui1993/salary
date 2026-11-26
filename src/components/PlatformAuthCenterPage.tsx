// @ts-nocheck
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRightLeft,
  Building2,
  Check,
  Compass,
  Edit3,
  KeyRound,
  Layers,
  LogIn,
  LogOut,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Trash2,
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
  type PlatformAccountSlotViewModel,
  type PlatformAuthCardViewModel,
  type PlatformRawAuthStatus,
  type PlatformScopeFilter,
  type PlatformStateFilter,
} from '../lib/platformAuthCenter';
import type { ConnectionChipKey } from '../lib/platformCatalog';
import { isPlatformStatusRecordEqual } from '../lib/perfUtils';
import { SourceLoginPanel } from './SourceLoginPanel';
import { UnifiedPlatformAuthModal } from './UnifiedPlatformAuthModal';

const PLATFORM_ICONS: Record<ConnectionChipKey, React.ComponentType<{ className?: string; size?: number }>> = {
  fengshen: Compass,
  lanorange: Layers,
  lanorange_mdr: Layers,
  baize: UsersRound,
  xiaoxiang: Radar,
  benlai: Building2,
};

const ACCENT_ICON_STYLES: Record<string, string> = {
  sky: 'bg-sky-50 text-[#008EC4] border border-sky-100/80',
  amber: 'bg-amber-50 text-amber-600 border border-amber-100/80',
  cyan: 'bg-cyan-50 text-cyan-700 border border-cyan-100/80',
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
  const [editingSlotKey, setEditingSlotKey] = useState<string>('');
  const [editingAliasValue, setEditingAliasValue] = useState<string>('');

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
      const prevAccountsKey = JSON.stringify(prev[source]?.accounts || []);
      const nextAccountsKey = JSON.stringify(nextStatus.accounts || []);
      if (
        isPlatformStatusRecordEqual(prev[source], nextStatus) &&
        prevAccountsKey === nextAccountsKey &&
        prev[source]?.active_account_id === nextStatus.active_account_id &&
        prev[source]?.pending_new_account === nextStatus.pending_new_account
      ) {
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
          source === activeSessionKey
            ? 450
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
      const cached = statuses[source] || {};
      if ((source === 'xiaoxiang' || source === 'benlai') && cached.can_manage === false) {
        recordError(
          source,
          new Error('该平台为全局共享连接，请联系系统管理员或授权维护人操作'),
        );
        return;
      }
      if (source === 'fengshen') {
        if (!forceRelogin && cached.state === 'ready') {
          onToastRef.current?.('当前账户已处于连接就绪状态', 'info');
          return;
        }
        onOpenFengshen();
        return;
      }
      if (!forceRelogin && cached.state === 'ready') {
        onToastRef.current?.('当前账户已处于连接就绪状态', 'info');
        return;
      }
      // 立即弹出统一认证窗并展示加载反馈，避免点击后先等待状态预检造成卡顿感
      setActiveSessionKey(source);
      if (
        ['starting', 'waiting_login', 'refreshing'].includes(cached.state || '') ||
        cached.busy
      ) {
        return;
      }
      setStatuses(prev => ({
        ...prev,
        [source]: {
          ...prev[source],
          state: 'starting',
          busy: true,
          message:
            source === 'lanorange' || source === 'lanorange_mdr'
              ? '正在准备钉钉扫码环境…'
              : '正在连接官方认证入口…',
        },
      }));
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

  async function handleAddNewAccount(card: PlatformAuthCardViewModel) {
    const source = card.entry.key;
    if (!acquireLock(source, 'add-account')) return;
    setFocusedPlatformKey(source);
    try {
      const prepared = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}/accounts/prepare-add`,
        {},
        15000,
      );
      updateStatus(source, prepared);
      if (source === 'fengshen') {
        onOpenFengshen();
        onToastRef.current?.('已保留现有风神账户，请在登录窗口中登录新账户', 'info');
        return;
      }
      setActiveSessionKey(source);
      const started = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/source-auth/${source}/start`,
        {},
      );
      updateStatus(source, started);
      onToastRef.current?.(`已保留原${card.entry.shortName}账户至账户列表，请继续登录新账户`, 'info');
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  async function handleActivateAccountSlot(
    source: ConnectionChipKey,
    slot: PlatformAccountSlotViewModel,
  ) {
    if (slot.isActive) return;
    if (!acquireLock(source, 'switch-account')) return;
    setFocusedPlatformKey(source);
    try {
      const res = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}/accounts/${encodeURIComponent(slot.slotId)}/activate`,
        {},
        15000,
      );
      updateStatus(source, { ...res, offline: false });
      window.dispatchEvent(
        new CustomEvent('workbench:platform-session-changed', { detail: { source } }),
      );
      onToastRef.current?.(`已切换至「${slot.displayTitle}」作为当前生效账户`, 'success');
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  async function handleSaveAccountAlias(source: ConnectionChipKey, slotId: string) {
    if (!acquireLock(source, 'alias')) return;
    try {
      const res = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}/accounts/${encodeURIComponent(slotId)}/alias`,
        { alias: editingAliasValue.trim() },
        10000,
      );
      updateStatus(source, { ...res, offline: false });
      setEditingSlotKey('');
      setEditingAliasValue('');
      onToastRef.current?.('已更新账户备注名称', 'success');
    } catch (err) {
      recordError(source, err);
    } finally {
      releaseLock(source);
    }
  }

  async function handleRemoveAccountSlot(
    source: ConnectionChipKey,
    slot: PlatformAccountSlotViewModel,
  ) {
    if (slot.slotId === 'active_default') {
      await handleLogout(source);
      return;
    }
    if (!acquireLock(source, 'remove-account')) return;
    setFocusedPlatformKey(source);
    try {
      const res = await fetchPlatformAuthJson(
        apiFetch,
        `/api/fengshen-downloads/platform-auth/${source}/accounts/${encodeURIComponent(slot.slotId)}/remove`,
        {},
        20000,
      );
      updateStatus(source, { ...res, offline: false });
      if (activeSessionKey === source && !res.saved) {
        setActiveSessionKey('');
      }
      onToastRef.current?.(
        res.active_account_id
          ? `已移除「${slot.displayTitle}」，并自动切换至其余在线账户`
          : `已退出并移除账户「${slot.displayTitle}」`,
        'info',
      );
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
        onToastRef.current?.('已安全退出并清除当前平台账户会话', 'info');
      }
      return true;
    } catch (err) {
      recordError(source, err);
      return false;
    } finally {
      releaseLock(source);
    }
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
    onToastRef.current?.('已完成全部平台账户连通性巡检', 'info');
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
        <div className="max-w-[1160px] mx-auto space-y-5 pb-8">
          {/* 1. 极简页头 + 一行式筛选条（无药丸堆叠、单层平面深度） */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1 min-w-0">
                <h2 className="text-[19px] font-bold text-[#18191C] tracking-tight">
                  授权管理
                </h2>
                <p className="text-[12.5px] text-[#61666D] tabular-nums">
                  <span>
                    已就绪{' '}
                    <strong className="font-semibold text-[#18191C]">
                      {overview.readyCount}/{overview.totalCount}
                    </strong>
                  </span>
                  <span className="mx-2 text-slate-300">·</span>
                  <span>
                    已驻留{' '}
                    <strong className="font-semibold text-[#18191C]">
                      {overview.totalLoggedAccountsCount}
                    </strong>{' '}
                    个账户
                  </span>
                  {lastInspectedAt && (
                    <>
                      <span className="mx-2 text-slate-300">·</span>
                      <span className="text-[#9499A0]">巡检 {lastInspectedAt}</span>
                    </>
                  )}
                </p>
              </div>

              <button
                type="button"
                disabled={anyVerifying}
                onClick={() => void handleCheckAllPlatforms()}
                className="h-8.5 inline-flex items-center gap-1.5 rounded-[10px] bg-[#00AEEC] hover:bg-[#009CD6] text-white px-3.5 text-[12.5px] font-semibold shadow-[0_6px_16px_-8px_rgba(0,174,236,0.75)] transition cursor-pointer whitespace-nowrap disabled:opacity-60"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${anyVerifying ? 'animate-spin' : ''}`} />
                <span>一键巡检全部</span>
              </button>
            </div>

            <div className="rounded-xl bg-white border border-slate-200/80 px-3.5 py-2.5 flex flex-wrap items-center justify-between gap-2.5">
              <div className="flex flex-wrap items-center gap-3">
                <div
                  className="inline-flex items-center h-7.5 p-0.5 rounded-lg bg-slate-100/90"
                  role="group"
                  aria-label="按通道归属筛选"
                >
                  {(
                    [
                      ['all', `全部 ${overview.totalCount}`],
                      ['personal', `个人 ${overview.personalCount}`],
                      ['shared', `共享 ${overview.sharedCount}`],
                    ] as [PlatformScopeFilter, string][]
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setScopeFilter(key)}
                      className={`h-6.5 px-2.5 rounded-[6px] text-[12px] transition whitespace-nowrap cursor-pointer tabular-nums ${
                        scopeFilter === key
                          ? 'bg-white text-[#18191C] shadow-2xs font-semibold'
                          : 'text-[#61666D] hover:text-[#18191C]'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                <span className="hidden sm:inline-block w-px h-4 bg-slate-200" aria-hidden="true" />

                <div
                  className="inline-flex items-center gap-1"
                  role="group"
                  aria-label="按连接状态筛选"
                >
                  {(
                    [
                      ['all', '全部状态'],
                      ['ready', '已就绪'],
                      ['attention', '待验证'],
                      ['idle', '未登录'],
                    ] as [PlatformStateFilter, string][]
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setStateFilter(key)}
                      className={`h-7 px-2.5 rounded-lg text-[12px] transition whitespace-nowrap cursor-pointer ${
                        stateFilter === key
                          ? 'bg-sky-50 text-[#008EC4] font-semibold'
                          : 'text-[#61666D] hover:bg-slate-50 hover:text-[#18191C]'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="relative w-full sm:w-[220px]">
                <Search className="w-3.5 h-3.5 text-[#9499A0] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="搜索平台或账号..."
                  aria-label="搜索平台或绑定账号"
                  className="w-full h-7.5 rounded-lg border border-slate-200/85 bg-[#F8FAFC] focus:bg-white pl-8 pr-7 text-[12px] text-[#18191C] placeholder:text-[#9499A0] transition focus:outline-none focus:border-[#00AEEC]"
                />
                {searchQuery && (
                  <button
                    type="button"
                    aria-label="清空搜索"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[#9499A0] hover:text-[#18191C] cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* 预检拦截引导横幅（仅在任务被授权阻塞时显示） */}
          {preflightItems.length > 0 && (
            <div
              role="status"
              className="rounded-xl border border-amber-300/85 bg-amber-50/90 px-4 py-3 flex flex-wrap items-center justify-between gap-3"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                <div className="min-w-0 text-[12.5px] text-amber-950">
                  <span className="font-semibold">
                    当前任务需先完成授权：{preflightItems.map(item => item.label).join('、')}
                  </span>
                  <span className="text-amber-800 ml-2">完成后将自动继续执行</span>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {preflightItems[0]?.source && (
                  <button
                    type="button"
                    onClick={() => void handleStartLogin(preflightItems[0].source)}
                    className="h-7.5 px-3 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[12px] font-semibold transition cursor-pointer"
                  >
                    立即验证
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCancelPreflight}
                  className="h-7.5 px-2.5 rounded-lg border border-amber-300 bg-white/80 hover:bg-white text-amber-900 text-[12px] font-medium transition cursor-pointer"
                >
                  取消等待
                </button>
              </div>
            </div>
          )}

          {/* 2. 清爽通透双列平台卡片网格 */}
          {filteredCards.length === 0 ? (
            <div className="rounded-2xl bg-white border border-slate-200/80 p-10 text-center space-y-2.5">
              <div className="w-9 h-9 rounded-xl bg-slate-100 text-[#61666D] flex items-center justify-center mx-auto">
                <KeyRound className="w-4 h-4" />
              </div>
              <div className="text-[13.5px] font-semibold text-[#18191C]">
                未找到匹配的业务平台或账户
              </div>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setScopeFilter('all');
                  setStateFilter('all');
                }}
                className="h-7.5 px-3 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-[12px] font-medium text-[#18191C] transition cursor-pointer"
              >
                重置筛选
              </button>
            </div>
          ) : (
            <div
              className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start"
              role="list"
              aria-label="业务系统平台账户卡片列表"
            >
              {filteredCards.map(card => {
                const { entry, badge, accounts } = card;
                const Icon = PLATFORM_ICONS[entry.key] || Compass;
                const isFocused = focusedPlatformKey === entry.key;
                const pendingAction = pendingActions[entry.key];
                const warnProbes = card.probes.filter(p => p.tone === 'warn');

                return (
                  <article
                    key={entry.key}
                    role="listitem"
                    data-platform-card={entry.key}
                    className={`rounded-2xl bg-white border transition-colors duration-150 flex flex-col overflow-hidden ${
                      isFocused
                        ? 'border-[#00AEEC]/60 shadow-[0_4px_18px_-8px_rgba(0,174,236,0.2)]'
                        : 'border-slate-200/85 hover:border-slate-300/90'
                    }`}
                  >
                    {/* 卡片顶栏：平台名 + 极简归属/方式 + 状态点 + 轻量操作 */}
                    <div className="px-5 py-3.5 flex items-center justify-between gap-3 border-b border-slate-100/90">
                      <div className="flex items-center gap-3 min-w-0">
                        <span
                          className={`w-9 h-9 rounded-[11px] flex items-center justify-center shrink-0 ${
                            ACCENT_ICON_STYLES[entry.accent] || ACCENT_ICON_STYLES.sky
                          }`}
                          aria-hidden="true"
                        >
                          <Icon size={17} />
                        </span>

                        <div className="min-w-0">
                          <div className="flex items-center gap-2 min-w-0">
                            <h3 className="text-[14.5px] font-bold text-[#18191C] tracking-tight truncate">
                              {entry.displayName}
                            </h3>
                            <span className="text-[11.5px] text-[#9499A0] shrink-0">
                              {entry.scope === 'shared' ? '全局共享' : '个人独立'}
                            </span>
                          </div>
                          <div className="text-[12px] text-[#61666D] mt-0.5 truncate">
                            {entry.authMethodLabel}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`inline-flex items-center gap-1.5 text-[12px] font-medium tabular-nums ${
                            badge.tone === 'ready'
                              ? 'text-emerald-700'
                              : badge.tone === 'warn'
                                ? 'text-amber-700'
                                : badge.tone === 'busy'
                                  ? 'text-[#008EC4]'
                                  : 'text-[#9499A0]'
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
                                    : 'bg-slate-300'
                            }`}
                            aria-hidden="true"
                          />
                          <span>{badge.label}</span>
                        </span>

                        <button
                          type="button"
                          disabled={Boolean(pendingAction)}
                          onClick={() => void handleCheckPlatform(entry.key)}
                          title="检测该平台连通性"
                          aria-label={`检测${entry.displayName}连接`}
                          className="w-7 h-7 rounded-lg text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 inline-flex items-center justify-center transition cursor-pointer disabled:opacity-45"
                        >
                          <RefreshCw
                            className={`w-3.5 h-3.5 ${pendingAction === 'verify' ? 'animate-spin' : ''}`}
                          />
                        </button>

                        {card.canManage && accounts.length > 0 && (
                          <button
                            type="button"
                            disabled={Boolean(pendingAction)}
                            onClick={() => void handleAddNewAccount(card)}
                            title="保留当前账户，继续登录另一个新账户"
                            className="h-7 px-2.5 rounded-lg border border-slate-200/90 bg-white hover:border-[#00AEEC]/60 hover:text-[#008EC4] text-[#4E5969] text-[12px] font-medium inline-flex items-center gap-1 transition cursor-pointer disabled:opacity-50 whitespace-nowrap"
                          >
                            <Plus className="w-3.5 h-3.5" />
                            <span>添加账户</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {/* 卡片主体：单层平面布局（无嵌套虚线盒），多账户切换一目了然 */}
                    <div className="px-5 py-4 flex-1 flex flex-col justify-center gap-2.5">
                      {accounts.length === 0 ? (
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-[12.5px] text-[#9499A0]">
                            {card.canManage ? '暂未登录' : '由管理员统一维护'}
                          </span>

                          {card.canManage && (
                            <button
                              type="button"
                              disabled={Boolean(pendingAction)}
                              onClick={() => void handleStartLogin(entry.key, true)}
                              className="h-8 px-3.5 rounded-[9px] bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12.5px] font-semibold inline-flex items-center gap-1.5 transition cursor-pointer disabled:opacity-55 shrink-0 whitespace-nowrap"
                            >
                              <LogIn className="w-3.5 h-3.5" />
                              <span>立即登录</span>
                            </button>
                          )}
                        </div>
                      ) : (
                        <div
                          className="divide-y divide-slate-100 -mx-5 -my-1"
                          role="list"
                          aria-label={`${entry.displayName}已登录账户列表`}
                        >
                          {accounts.map(slot => {
                            const compositeKey = `${entry.key}:${slot.slotId}`;
                            const isEditingAlias = editingSlotKey === compositeKey;

                            return (
                              <div
                                key={slot.slotId}
                                role="listitem"
                                className={`px-5 py-2.5 transition-colors ${
                                  slot.isActive
                                    ? 'bg-[#F0F9FF]/55'
                                    : 'bg-white hover:bg-slate-50/75'
                                }`}
                              >
                                {isEditingAlias ? (
                                  <div className="flex items-center gap-2">
                                    <input
                                      type="text"
                                      value={editingAliasValue}
                                      onChange={e => setEditingAliasValue(e.target.value)}
                                      placeholder="输入账户备注名（如：闪购主号）"
                                      aria-label="账户备注名称"
                                      autoFocus
                                      onKeyDown={e => {
                                        if (e.key === 'Enter') {
                                          void handleSaveAccountAlias(entry.key, slot.slotId);
                                        } else if (e.key === 'Escape') {
                                          setEditingSlotKey('');
                                        }
                                      }}
                                      className="flex-1 h-7.5 rounded-lg border border-[#00AEEC] bg-white px-2.5 text-[12px] text-[#18191C] focus:outline-none"
                                    />
                                    <button
                                      type="button"
                                      onClick={() => void handleSaveAccountAlias(entry.key, slot.slotId)}
                                      className="h-7.5 px-2.5 rounded-lg bg-[#00AEEC] text-white text-[12px] font-semibold inline-flex items-center gap-1 cursor-pointer"
                                    >
                                      <Check className="w-3.5 h-3.5" />
                                      <span>保存</span>
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setEditingSlotKey('')}
                                      className="h-7.5 px-2 rounded-lg border border-slate-200 bg-white text-[#61666D] text-[12px] cursor-pointer"
                                    >
                                      取消
                                    </button>
                                  </div>
                                ) : (
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                                      <span
                                        className={`w-2 h-2 rounded-full shrink-0 ${
                                          slot.isActive
                                            ? slot.tone === 'ready'
                                              ? 'bg-emerald-500 ring-4 ring-emerald-500/15'
                                              : 'bg-amber-500 ring-4 ring-amber-500/15'
                                            : 'bg-slate-300'
                                        }`}
                                        aria-hidden="true"
                                      />

                                      <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 min-w-0">
                                          <span
                                            className={`text-[13.5px] truncate ${
                                              slot.isActive
                                                ? 'font-semibold text-[#18191C]'
                                                : 'font-medium text-[#3F4652]'
                                            }`}
                                            title={slot.displayTitle}
                                          >
                                            {slot.displayTitle}
                                          </span>
                                          <span
                                            className={`text-[11px] shrink-0 ${
                                              slot.isActive
                                                ? slot.tone === 'ready'
                                                  ? 'text-emerald-700 font-medium'
                                                  : 'text-amber-700 font-medium'
                                                : 'text-[#9499A0]'
                                            }`}
                                          >
                                            {slot.badgeText}
                                          </span>
                                        </div>

                                        {slot.subtitle && (
                                          <div
                                            className="text-[11.5px] text-[#86909C] mt-0.5 truncate"
                                            title={slot.subtitle}
                                          >
                                            {slot.subtitle}
                                          </div>
                                        )}
                                      </div>
                                    </div>

                                    {card.canManage && (
                                      <div className="flex items-center gap-1 shrink-0">
                                        {!slot.isActive ? (
                                          <button
                                            type="button"
                                            disabled={Boolean(pendingAction)}
                                            onClick={() =>
                                              void handleActivateAccountSlot(entry.key, slot)
                                            }
                                            title="切换此账户为当前生效账户"
                                            className="h-7 px-2.5 rounded-lg border border-sky-200 bg-white hover:bg-sky-50 text-[#008EC4] text-[12px] font-semibold inline-flex items-center gap-1 transition cursor-pointer disabled:opacity-50 whitespace-nowrap"
                                          >
                                            <ArrowRightLeft className="w-3 h-3" />
                                            <span>切换</span>
                                          </button>
                                        ) : (
                                          !card.isReady && (
                                            <button
                                              type="button"
                                              disabled={Boolean(pendingAction)}
                                              onClick={() => void handleStartLogin(entry.key, true)}
                                              className="h-7 px-2.5 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[12px] font-semibold inline-flex items-center gap-1 transition cursor-pointer disabled:opacity-50 whitespace-nowrap"
                                            >
                                              <LogIn className="w-3 h-3" />
                                              <span>重新验证</span>
                                            </button>
                                          )
                                        )}

                                        {slot.slotId !== 'active_default' && (
                                          <button
                                            type="button"
                                            disabled={Boolean(pendingAction)}
                                            onClick={() => {
                                              setEditingSlotKey(compositeKey);
                                              setEditingAliasValue(slot.alias || slot.displayTitle);
                                            }}
                                            title="修改备注名"
                                            aria-label={`修改${slot.displayTitle}备注`}
                                            className="w-7 h-7 rounded-lg text-[#9499A0] hover:text-[#18191C] hover:bg-slate-100 inline-flex items-center justify-center transition cursor-pointer disabled:opacity-45"
                                          >
                                            <Edit3 className="w-3.5 h-3.5" />
                                          </button>
                                        )}

                                        <button
                                          type="button"
                                          disabled={Boolean(pendingAction)}
                                          onClick={() =>
                                            void handleRemoveAccountSlot(entry.key, slot)
                                          }
                                          title={
                                            slot.isActive
                                              ? '退出并移除当前账户'
                                              : '移除此驻留账户'
                                          }
                                          aria-label={`移除${slot.displayTitle}`}
                                          className="w-7 h-7 rounded-lg text-[#9499A0] hover:text-rose-600 hover:bg-rose-50 inline-flex items-center justify-center transition cursor-pointer disabled:opacity-45"
                                        >
                                          {slot.isActive ? (
                                            <LogOut className="w-3.5 h-3.5" />
                                          ) : (
                                            <Trash2 className="w-3.5 h-3.5" />
                                          )}
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })}

                          {card.pendingNewAccount && card.canManage && (
                            <div className="px-5 py-2.5 bg-sky-50/45 flex items-center justify-between gap-2">
                              <span className="text-[12px] text-[#008EC4]">
                                等待登录新账户（已有账户已保留）
                              </span>
                              <button
                                type="button"
                                disabled={Boolean(pendingAction)}
                                onClick={() => void handleStartLogin(entry.key, true)}
                                className="h-7 px-2.5 rounded-lg bg-[#00AEEC] hover:bg-[#009CD6] text-white text-[11.5px] font-semibold cursor-pointer"
                              >
                                继续登录
                              </button>
                            </div>
                          )}
                        </div>
                      )}

                      {/* 仅在子通道存在待验证告警时展示精简提示，避免所有卡片重复堆叠底栏 */}
                      {warnProbes.length > 0 && accounts.length > 0 && (
                        <div className="rounded-lg bg-amber-50/80 px-3 py-1.5 text-[11.5px] text-amber-800 flex items-center justify-between gap-2">
                          <span className="truncate">
                            {warnProbes.map(p => `${p.label}${p.statusText}`).join(' · ')}
                          </span>
                          {card.canManage && (
                            <button
                              type="button"
                              disabled={Boolean(pendingAction)}
                              onClick={() => void handleStartLogin(entry.key, true)}
                              className="text-amber-700 hover:text-amber-950 font-semibold shrink-0 cursor-pointer"
                            >
                              去处理
                            </button>
                          )}
                        </div>
                      )}

                      {card.errorText && (
                        <div
                          role="alert"
                          className="rounded-lg bg-rose-50/90 border border-rose-200/70 px-3 py-1.5 text-[11.5px] text-rose-700 flex items-center justify-between gap-2"
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
                  </article>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 统一居中平台认证弹窗（与风神登录验证保持一致的视觉体系与交互体验） */}
      {!!activeDef && (
        <UnifiedPlatformAuthModal
          sourceKey={activeDef.key}
          displayName={activeDef.displayName}
          status={activeStatus}
          pending={!!pendingActions[activeDef.key]}
          errorMessage={errors[activeDef.key] || ''}
          startActionLabel="立即验证并登录"
          onClose={() => setActiveSessionKey('')}
          onStartLogin={() => void handleStartLogin(activeDef.key)}
          onCredentialAction={decision => void handleCredential(decision)}
        >
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
        </UnifiedPlatformAuthModal>
      )}
    </>
  );
}
