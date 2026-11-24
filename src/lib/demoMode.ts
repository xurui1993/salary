import { useCallback, useEffect, useState } from 'react';

export type PlatformKey = 'fengshen' | 'lanorange' | 'baize' | 'xiaoxiang' | 'benlai';

export const PLATFORM_KEYS: readonly PlatformKey[] = [
  'fengshen',
  'lanorange',
  'baize',
  'xiaoxiang',
  'benlai',
] as const;

export interface PlatformAuthLike {
  saved?: boolean;
  state?: string;
  offline?: boolean;
  loggedIn?: boolean;
}

export type PlatformAuthMap = Partial<Record<string, PlatformAuthLike | null | undefined>>;

export interface DemoDataDecisionInput {
  /** Whether the relevant platform (or any platform) has a real authenticated session */
  isLoggedIn: boolean;
  /** Whether real backend data is already present (live records always win over demo) */
  hasLiveData: boolean;
  /** Whether the user explicitly toggled demo data off while logged out */
  demoHidden: boolean;
}

/**
 * Determine whether a single platform status represents a real authenticated session.
 * Offline, signed_out, login_required, or unsaved sessions return false.
 */
export function isPlatformAuthenticated(status?: PlatformAuthLike | null): boolean {
  if (!status || status.offline) return false;
  if (status.loggedIn === true) return true;
  if (status.state === 'ready') return true;
  if (status.saved === true) {
    const state = status.state || '';
    return state !== 'signed_out' && state !== 'login_required' && state !== 'offline';
  }
  return false;
}

/**
 * Determine whether ANY platform in the workbench is genuinely logged in.
 */
export function hasAnyAuthenticatedPlatform(
  platformStatuses?: PlatformAuthMap | null,
  fengshenAuthStatus?: PlatformAuthLike | null,
): boolean {
  if (isPlatformAuthenticated(fengshenAuthStatus)) return true;
  if (!platformStatuses) return false;
  for (const key of PLATFORM_KEYS) {
    if (isPlatformAuthenticated(platformStatuses[key])) return true;
  }
  return false;
}

/**
 * Determine whether a specific platform is genuinely logged in.
 */
export function isSpecificPlatformAuthenticated(
  platform: PlatformKey,
  platformStatuses?: PlatformAuthMap | null,
  fengshenAuthStatus?: PlatformAuthLike | null,
): boolean {
  if (platform === 'fengshen' && isPlatformAuthenticated(fengshenAuthStatus)) return true;
  return isPlatformAuthenticated(platformStatuses?.[platform]);
}

/**
 * Pure decision rule for whether frontend showcase/demo data should be displayed.
 *
 * Core guarantee:
 * - As soon as a real login succeeds (`isLoggedIn === true`), returns `false`
 *   so the view switches immediately and exclusively to real backend data.
 * - If real backend records already exist (`hasLiveData === true`), returns `false`
 *   so live data is never hidden or mixed with demo records.
 * - While unauthenticated with no live records, respects the user's hide/show toggle.
 */
export function shouldUseDemoData(input: DemoDataDecisionInput): boolean {
  if (input.isLoggedIn) return false;
  if (input.hasLiveData) return false;
  if (input.demoHidden) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Global reactive snapshot (bridges SystemConnections, FengshenLoginModal & views)
// ---------------------------------------------------------------------------

const DEMO_HIDDEN_STORAGE_KEY = 'workbench_demo_data_hidden';
const DEMO_VISIBILITY_EVENT = 'workbench:demo-visibility-changed';
const DEMO_AUTH_SYNC_EVENT = 'workbench:demo-auth-sync';

interface GlobalAuthStore {
  statuses: PlatformAuthMap;
  fengshen: PlatformAuthLike | null;
}

const globalAuthStore: GlobalAuthStore = {
  statuses: {},
  fengshen: null,
};

let windowListenerAttached = false;

function ensureGlobalAuthListener(): void {
  if (windowListenerAttached || typeof window === 'undefined') return;
  windowListenerAttached = true;
  window.addEventListener('workbench:platform-statuses', (event: Event) => {
    const detail = (event as CustomEvent).detail;
    if (detail && typeof detail === 'object') {
      globalAuthStore.statuses = detail as PlatformAuthMap;
      window.dispatchEvent(new CustomEvent(DEMO_AUTH_SYNC_EVENT));
    }
  });
}

/**
 * Called by App.tsx whenever platformStatuses or fengshenAuthStatus updates,
 * keeping lazily mounted pages immediately aware of real login state.
 */
export function syncGlobalPlatformAuth(
  platformStatuses?: PlatformAuthMap | null,
  fengshenAuthStatus?: PlatformAuthLike | null,
): void {
  if (platformStatuses && typeof platformStatuses === 'object') {
    globalAuthStore.statuses = platformStatuses;
  }
  if (fengshenAuthStatus !== undefined) {
    globalAuthStore.fengshen = fengshenAuthStatus;
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(DEMO_AUTH_SYNC_EVENT));
  }
}

export function getGlobalPlatformAuthSnapshot(): {
  statuses: PlatformAuthMap;
  fengshen: PlatformAuthLike | null;
  anyLoggedIn: boolean;
  isLoggedIn: (platform: PlatformKey) => boolean;
} {
  ensureGlobalAuthListener();
  const statuses = globalAuthStore.statuses;
  const fengshen = globalAuthStore.fengshen;
  return {
    statuses,
    fengshen,
    anyLoggedIn: hasAnyAuthenticatedPlatform(statuses, fengshen),
    isLoggedIn: (platform: PlatformKey) =>
      isSpecificPlatformAuthenticated(platform, statuses, fengshen),
  };
}

export function usePlatformAuthSnapshot() {
  ensureGlobalAuthListener();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onChange = () => setTick(v => v + 1);
    window.addEventListener(DEMO_AUTH_SYNC_EVENT, onChange);
    window.addEventListener('workbench:platform-statuses', onChange);
    return () => {
      window.removeEventListener(DEMO_AUTH_SYNC_EVENT, onChange);
      window.removeEventListener('workbench:platform-statuses', onChange);
    };
  }, []);

  void tick;
  return getGlobalPlatformAuthSnapshot();
}

export function readDemoHiddenPreference(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return sessionStorage.getItem(DEMO_HIDDEN_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeDemoHiddenPreference(hidden: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    if (hidden) sessionStorage.setItem(DEMO_HIDDEN_STORAGE_KEY, '1');
    else sessionStorage.removeItem(DEMO_HIDDEN_STORAGE_KEY);
  } catch {
    // Ignore storage quota / sandbox restrictions
  }
  window.dispatchEvent(new CustomEvent(DEMO_VISIBILITY_EVENT, { detail: { hidden } }));
}

export function useDemoDataVisibility(): {
  demoHidden: boolean;
  setDemoHidden: (hidden: boolean) => void;
  toggleDemoHidden: () => void;
} {
  const setDemoHidden = useCallback((_hidden: boolean) => {
    // 示例数据已全局关闭，界面全部绑定真实数据
  }, []);

  const toggleDemoHidden = useCallback(() => {
    // 示例数据已全局关闭，界面全部绑定真实数据
  }, []);

  return { demoHidden: true, setDemoHidden, toggleDemoHidden };
}
