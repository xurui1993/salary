import { useEffect, useState } from 'react';

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

export function isSpecificPlatformAuthenticated(
  platform: PlatformKey,
  platformStatuses?: PlatformAuthMap | null,
  fengshenAuthStatus?: PlatformAuthLike | null,
): boolean {
  if (platform === 'fengshen' && isPlatformAuthenticated(fengshenAuthStatus)) return true;
  return isPlatformAuthenticated(platformStatuses?.[platform]);
}

interface GlobalAuthStore {
  statuses: PlatformAuthMap;
  fengshen: PlatformAuthLike | null;
}

const globalAuthStore: GlobalAuthStore = {
  statuses: {},
  fengshen: null,
};

const AUTH_SYNC_EVENT = 'workbench:platform-auth-sync';
let windowListenerAttached = false;

function ensureGlobalAuthListener(): void {
  if (windowListenerAttached || typeof window === 'undefined') return;
  windowListenerAttached = true;
  window.addEventListener('workbench:platform-statuses', (event: Event) => {
    const detail = (event as CustomEvent).detail;
    if (detail && typeof detail === 'object') {
      globalAuthStore.statuses = detail as PlatformAuthMap;
      window.dispatchEvent(new CustomEvent(AUTH_SYNC_EVENT));
    }
  });
}

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
    window.dispatchEvent(new CustomEvent(AUTH_SYNC_EVENT));
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
    window.addEventListener(AUTH_SYNC_EVENT, onChange);
    window.addEventListener('workbench:platform-statuses', onChange);
    return () => {
      window.removeEventListener(AUTH_SYNC_EVENT, onChange);
      window.removeEventListener('workbench:platform-statuses', onChange);
    };
  }, []);

  void tick;
  return getGlobalPlatformAuthSnapshot();
}