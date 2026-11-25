import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  Bell,
  BellRing,
  CheckCircle2,
  KeyRound,
  RefreshCw,
  X,
} from 'lucide-react';
import { platformAuthRequest } from '../lib/platformAuthApi';
import {
  shouldUseDemoData,
  useDemoDataVisibility,
  usePlatformAuthSnapshot,
} from '../lib/demoMode';

export interface ApprovalPendingTaskItem {
  id: string;
  business_id?: string;
  businessCode?: string;
  businessTitle?: string;
  cityName?: string;
  siteName?: string;
  nodeName?: string;
  createByName?: string;
  createTime?: string;
  period_start?: string;
  period_end?: string;
  rider_count?: number;
  settle_month?: string;
  reason?: string;
}

export interface HeaderApprovalNotifierProps {
  apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  workspaceId: string;
  isApprovalViewActive?: boolean;
  onNavigateApproval: () => void;
  onOpenLanorangeAuth: () => void;
  onPendingCountChange?: (count: number) => void;
  onShowToast?: (msg: string, type?: 'info' | 'error' | 'warn') => void;
  onDesktopNotify?: (title: string, body: string) => void;
}

const SEEN_STORAGE_PREFIX = 'lanorange-approval-seen-ids:';

function readSeenIds(workspaceId: string): Set<string> | null {
  try {
    const raw = sessionStorage.getItem(`${SEEN_STORAGE_PREFIX}${workspaceId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((id): id is string => typeof id === 'string'));
    }
    return null;
  } catch {
    return null;
  }
}

function writeSeenIds(workspaceId: string, ids: Set<string>): void {
  try {
    sessionStorage.setItem(
      `${SEEN_STORAGE_PREFIX}${workspaceId}`,
      JSON.stringify(Array.from(ids)),
    );
  } catch {
    // Ignore storage quota errors
  }
}

export function HeaderApprovalNotifier({
  apiFetch,
  workspaceId,
  isApprovalViewActive = false,
  onNavigateApproval,
  onOpenLanorangeAuth,
  onPendingCountChange,
  onShowToast,
  onDesktopNotify,
}: HeaderApprovalNotifierProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [actorLabel, setActorLabel] = useState('');
  const [rows, setRows] = useState<ApprovalPendingTaskItem[]>([]);
  const [demoRows, setDemoRows] = useState<ApprovalPendingTaskItem[]>([]);
  const [unreadIds, setUnreadIds] = useState<string[]>([]);
  const [lastCheckedAt, setLastCheckedAt] = useState<string>('');

  const auth = usePlatformAuthSnapshot();
  const { demoHidden } = useDemoDataVisibility();
  const isLanorangeLoggedIn = loggedIn || auth.isLoggedIn('lanorange');
  const demoActive = shouldUseDemoData({
    isLoggedIn: isLanorangeLoggedIn,
    hasLiveData: rows.length > 0,
    demoHidden,
  });

  const wrapRef = useRef<HTMLDivElement>(null);
  const fetchRef = useRef(apiFetch);
  fetchRef.current = apiFetch;
  const onPendingCountChangeRef = useRef(onPendingCountChange);
  onPendingCountChangeRef.current = onPendingCountChange;
  const onShowToastRef = useRef(onShowToast);
  onShowToastRef.current = onShowToast;
  const onDesktopNotifyRef = useRef(onDesktopNotify);
  onDesktopNotifyRef.current = onDesktopNotify;

  const inflightRef = useRef(false);
  const seenIdsRef = useRef<Set<string> | null>(null);
  const snapshotEpochRef = useRef(0);

  useEffect(() => {
    seenIdsRef.current = readSeenIds(workspaceId);
  }, [workspaceId]);

  const applyPendingSnapshot = useCallback(
    (
      nextRows: ApprovalPendingTaskItem[],
      nextActor: string,
      options: { announceNew?: boolean } = { announceNew: true },
    ) => {
      snapshotEpochRef.current += 1;
      setLoggedIn(true);
      setActorLabel(nextActor || '');
      setRows(nextRows);
      setLastCheckedAt(
        new Date().toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }),
      );

      const currentIds = new Set(nextRows.map(item => String(item.id)));
      const previousSeen = seenIdsRef.current;

      if (previousSeen === null) {
        // First snapshot in this workspace session
        seenIdsRef.current = currentIds;
        writeSeenIds(workspaceId, currentIds);
        if (nextRows.length > 0 && options.announceNew) {
          const freshIds = nextRows.map(item => String(item.id));
          setUnreadIds(freshIds);
          onShowToastRef.current?.(
            `价格审批共有 ${nextRows.length} 条待审批提审单，请及时处理`,
            'info',
          );
        }
        return;
      }

      const newlyAdded = nextRows.filter(item => !previousSeen.has(String(item.id)));
      seenIdsRef.current = currentIds;
      writeSeenIds(workspaceId, currentIds);

      if (newlyAdded.length > 0) {
        const addedIds = newlyAdded.map(item => String(item.id));
        setUnreadIds(prev => Array.from(new Set([...addedIds, ...prev])));
        if (options.announceNew) {
          const sampleCity =
            newlyAdded[0]?.cityName || newlyAdded[0]?.siteName || '蓝橙站点';
          const msg = `新增 ${newlyAdded.length} 条价格待审批单（${sampleCity}等，当前共 ${nextRows.length} 条待审）`;
          onShowToastRef.current?.(msg, 'info');
          onDesktopNotifyRef.current?.('价格审批新待办提醒', msg);
        }
      } else {
        // Prune any unreadIds that are no longer pending
        setUnreadIds(prev => prev.filter(id => currentIds.has(id)));
      }
    },
    [workspaceId],
  );

  const pollPendingApprovals = useCallback(
    async (announceNew = true, silent = false) => {
      if (inflightRef.current) return;
      if (silent && document.visibilityState !== 'visible') return;
      inflightRef.current = true;
      const startEpoch = snapshotEpochRef.current;
      if (!silent) setLoading(true);
      try {
        const auth = await platformAuthRequest<{ saved?: boolean; state?: string }>(
          fetchRef.current,
          '/api/fengshen-downloads/platform-auth/lanorange',
        ).catch(() => null);

        if (snapshotEpochRef.current !== startEpoch) {
          return;
        }

        const isAuthed = Boolean(
          auth?.saved && !['signed_out', 'login_required'].includes(auth.state || ''),
        );
        if (!isAuthed) {
          setLoggedIn(prev => (prev ? false : prev));
          setActorLabel(prev => (prev ? '' : prev));
          setRows(prev => (prev.length ? [] : prev));
          return;
        }

        const value = await platformAuthRequest<{
          rows: ApprovalPendingTaskItem[];
          total: number;
          actor_label: string;
        }>(
          fetchRef.current,
          '/api/fengshen-downloads/lanorange-approvals/pending-scope',
        );

        if (snapshotEpochRef.current !== startEpoch) {
          return;
        }

        if (value && Array.isArray(value.rows)) {
          applyPendingSnapshot(value.rows, value.actor_label || '', { announceNew });
        }
      } catch {
        // Keep last known rows on transient error
      } finally {
        inflightRef.current = false;
        if (!silent) setLoading(false);
      }
    },
    [applyPendingSnapshot],
  );

  useEffect(() => {
    void pollPendingApprovals(true, false);
    const timer = setInterval(() => {
      void pollPendingApprovals(true, true);
    }, 25000);
    return () => clearInterval(timer);
  }, [pollPendingApprovals]);

  // 真实蓝橙登录后立即拉取实时待办
  const prevLanorangeRef = useRef(auth.isLoggedIn('lanorange'));
  useEffect(() => {
    const nowAuthed = auth.isLoggedIn('lanorange');
    if (nowAuthed && !prevLanorangeRef.current) {
      void pollPendingApprovals(false);
    }
    prevLanorangeRef.current = nowAuthed;
  }, [auth, pollPendingApprovals]);

  // Stay in sync when LanorangeApprovals page fetches or updates pending rows
  useEffect(() => {
    const onUpdated = (event: Event) => {
      const detail = (event as CustomEvent).detail as
        | { rows?: ApprovalPendingTaskItem[]; actor_label?: string; loggedOut?: boolean; demo?: boolean }
        | undefined;
      if (!detail) return;
      if (detail.demo && Array.isArray(detail.rows)) {
        setDemoRows(detail.rows);
        return;
      }
      if (detail.loggedOut) {
        snapshotEpochRef.current += 1;
        setLoggedIn(false);
        setRows([]);
        return;
      }
      if (Array.isArray(detail.rows)) {
        applyPendingSnapshot(detail.rows, detail.actor_label || '', {
          announceNew: true,
        });
      }
    };
    window.addEventListener('workbench:lanorange-approvals-updated', onUpdated);
    return () => {
      window.removeEventListener('workbench:lanorange-approvals-updated', onUpdated);
    };
  }, [applyPendingSnapshot]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onMouseDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('mousedown', onMouseDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('mousedown', onMouseDown);
    };
  }, [open]);

  const displayRows = demoActive ? demoRows : rows;
  const pendingCount = displayRows.length;
  const eligibleCount = displayRows.filter(item => !item.reason).length;
  const unreadCount = isLanorangeLoggedIn ? unreadIds.length : 0;
  const hasUnread = unreadCount > 0;

  // 统一将顶部待办与侧边栏审批徽标与当前展示列表保持一致（演示态展示示例数，真实登录后只展示后台数）
  useEffect(() => {
    onPendingCountChangeRef.current?.(pendingCount);
  }, [pendingCount]);

  const handleToggleOpen = () => {
    setOpen(prev => {
      const next = !prev;
      if (next) {
        setUnreadIds([]);
        if (rows.length === 0) {
          void pollPendingApprovals(false);
        }
      }
      return next;
    });
  };

  return (
    <div className="wbx-popover-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`wbx-header-tool-btn wbx-approval-bell-btn${open ? ' is-open' : ''}${isApprovalViewActive ? ' is-viewing' : ''}${pendingCount > 0 ? ' has-pending' : ''}${hasUnread ? ' has-unread' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`价格审批待办通知（待审批 ${pendingCount} 条${hasUnread ? `，新增 ${unreadCount} 条` : ''}）`}
        title={
          isLanorangeLoggedIn
            ? `价格审批：当前待审批 ${pendingCount} 条（可同意 ${eligibleCount} 条）`
            : demoActive
              ? `价格审批示例待办 ${pendingCount} 条（登录蓝橙后自动切换真实数据）`
              : '价格审批通知（未登录蓝橙账号）'
        }
        onClick={handleToggleOpen}
      >
        <span className="wbx-approval-bell-btn__icon-wrap">
          {pendingCount > 0 ? (
            <BellRing
              size={13.5}
              className="wbx-header-tool-icon is-active"
              aria-hidden="true"
            />
          ) : (
            <Bell size={13.5} className="wbx-header-tool-icon" aria-hidden="true" />
          )}
          {hasUnread && <span className="wbx-approval-bell-btn__ping" aria-hidden="true" />}
        </span>

        <span className="wbx-approval-bell-btn__label">待办审批</span>

        <span
          className={`wbx-approval-bell-btn__count tabular-nums${
            pendingCount > 0 ? ' is-pending' : ''
          }`}
        >
          {pendingCount > 99 ? '99+' : pendingCount}
        </span>
      </button>

      {open && (
        <div
          className="wbx-popover wbx-approval-popover"
          role="dialog"
          aria-modal="false"
          aria-label="价格审批待办通知"
        >
          <div className="wbx-popover__head">
            <div>
              <div className="flex items-center gap-2">
                <span className="wbx-popover__title">价格审批待办通知</span>
                <span
                  className={`wbx-approval-popover__badge tabular-nums${
                    pendingCount > 0 ? ' is-pending' : ''
                  }`}
                >
                  待审 {pendingCount}
                </span>
                {demoActive && <span className="wbx-demo-badge">示例</span>}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                {isLanorangeLoggedIn
                  ? `${actorLabel ? `账号：${actorLabel} · ` : ''}可同意 ${eligibleCount} 条${
                      lastCheckedAt ? ` · 更新于 ${lastCheckedAt}` : ''
                    }`
                  : demoActive
                    ? `演示数据 · 可同意 ${eligibleCount} 条 · 登录蓝橙后自动切换实时待办`
                    : '连接蓝橙账号后自动实时巡检并推送新增待审提醒'}
              </p>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                className="wbx-btn wbx-btn--ghost wbx-btn--sm"
                aria-label="刷新蓝橙待审批数量"
                title="立即同步蓝橙本人待办"
                disabled={loading}
                onClick={() => void pollPendingApprovals(true)}
              >
                <RefreshCw size={13.5} className={loading ? 'animate-spin' : ''} />
              </button>
              <button
                type="button"
                className="wbx-btn wbx-btn--ghost wbx-btn--sm"
                aria-label="关闭待办审批通知弹窗"
                onClick={() => setOpen(false)}
              >
                <X size={15} />
              </button>
            </div>
          </div>

          <div className="wbx-approval-popover__body">
            {!isLanorangeLoggedIn && !demoActive ? (
              <div className="wbx-approval-popover__empty">
                <span className="wbx-approval-popover__empty-icon">
                  <KeyRound size={18} />
                </span>
                <p className="wbx-approval-popover__empty-title">尚未登录蓝橙平台账号</p>
                <p className="wbx-approval-popover__empty-desc">
                  完成蓝橙扫码或账号授权后，状态栏将实时显示本人待审批数量，并在新增提审单时第一时间通知。
                </p>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--primary wbx-btn--sm mt-1"
                  onClick={() => {
                    setOpen(false);
                    onOpenLanorangeAuth();
                  }}
                >
                  <KeyRound size={12.5} />
                  <span>立即登录蓝橙授权</span>
                </button>
              </div>
            ) : pendingCount === 0 ? (
              <div className="wbx-approval-popover__empty">
                <span className="wbx-approval-popover__empty-icon is-clear">
                  <CheckCircle2 size={18} />
                </span>
                <p className="wbx-approval-popover__empty-title">当前暂无待审批提审单</p>
                <p className="wbx-approval-popover__empty-desc">
                  后台每 25 秒自动同步蓝橙待办队列，有新提审单到达时将自动弹窗提醒。
                </p>
              </div>
            ) : (
              <>
                <ul className="wbx-approval-popover__list" aria-label="待审批价格提审单列表">
                  {displayRows.slice(0, 5).map(task => {
                    const code = task.businessCode || task.id;
                    const periodText = task.period_start
                      ? `${task.period_start.slice(5, 10)} ~ ${task.period_end?.slice(5, 10) || '—'}`
                      : task.settle_month || '—';
                    return (
                      <li key={task.id} className="wbx-approval-popover__item">
                        <button
                          type="button"
                          className="wbx-approval-popover__item-btn"
                          onClick={() => {
                            setOpen(false);
                            onNavigateApproval();
                          }}
                        >
                          <div className="wbx-approval-popover__item-top">
                            <span className="wbx-approval-popover__city">
                              {task.cityName || '未知城市'} · {task.siteName || '未知站点'}
                            </span>
                            <span
                              className={`wbx-approval-popover__tag${
                                task.reason ? ' is-blocked' : ' is-ready'
                              }`}
                            >
                              {task.reason ? '需核实' : task.nodeName || '待审批'}
                            </span>
                          </div>
                          <div className="wbx-approval-popover__item-meta tabular-nums">
                            <span>{code}</span>
                            <span>·</span>
                            <span>{task.rider_count ?? '—'} 人</span>
                            <span>·</span>
                            <span>{periodText}</span>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {pendingCount > 5 && (
                  <p className="wbx-approval-popover__more tabular-nums">
                    还有 {pendingCount - 5} 条待审批记录，点击下方前往全部处理
                  </p>
                )}
              </>
            )}
          </div>

          <div className="wbx-approval-popover__foot flex items-center gap-2">
            {demoActive && (
              <button
                type="button"
                className="wbx-btn wbx-btn--sm shrink-0"
                onClick={() => {
                  setOpen(false);
                  onOpenLanorangeAuth();
                }}
              >
                <KeyRound size={12.5} aria-hidden="true" />
                <span>登录蓝橙</span>
              </button>
            )}
            <button
              type="button"
              className="wbx-btn wbx-btn--primary wbx-btn--sm w-full justify-center"
              onClick={() => {
                setOpen(false);
                onNavigateApproval();
              }}
            >
              <span>
                {pendingCount > 0
                  ? `前往价格审批处理 (${pendingCount})`
                  : '打开价格审批工作台'}
              </span>
              <ArrowRight size={13} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
