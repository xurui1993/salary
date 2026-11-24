// @ts-nocheck
import { useEffect, useMemo, useState } from 'react';
import { getWorkspaceId } from '../utils';
import { sortCitiesWithLanorangeFirst } from './workbench';
import { shouldUseDemoData, useDemoDataVisibility, usePlatformAuthSnapshot } from './demoMode';
import { buildDemoStationDirectory } from './showcaseDemoData';

const defaultFetch = (url: string, init?: RequestInit) => {
  const headers = new Headers(init?.headers);
  headers.set('x-workspace-id', encodeURIComponent(getWorkspaceId()));
  return fetch(url, { ...init, headers });
};

export interface StationDirectory {
  cities: Array<{ id: string; name: string; status?: string; station_count?: number | null; [key: string]: any }>;
  stations?: Array<any>;
  status?: string;
  fetched_at?: string;
  message?: string;
  demo?: boolean;
  [key: string]: any;
}

export type DirectoryStation = any;

interface DirectoryCacheEntry {
  data: StationDirectory | null;
  timestamp: number;
  inflight?: Promise<StationDirectory>;
}

const directoryCache = new Map<string, DirectoryCacheEntry>();
const DIRECTORY_CACHE_TTL_MS = 10_000;

export function useStationDirectory(
  platform: any,
  fetcher: any = defaultFetch,
  enabled = true,
): { data: StationDirectory | null; error: string; refresh: () => void; isDemo?: boolean } {
  const [data, setData] = useState<StationDirectory | null>(() => directoryCache.get(String(platform))?.data ?? null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const auth = usePlatformAuthSnapshot();
  const { demoHidden } = useDemoDataVisibility();

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let timer: any;
    let generation = 0;
    const controller = new AbortController();
    const cacheKey = String(platform);

    async function read(refresh = false) {
      const request = ++generation;
      try {
        const now = Date.now();
        const existing = directoryCache.get(cacheKey);
        let nextValue: StationDirectory;

        if (!refresh && existing?.data && now - existing.timestamp < DIRECTORY_CACHE_TTL_MS && fetcher === defaultFetch) {
          nextValue = existing.data;
        } else if (!refresh && existing?.inflight && fetcher === defaultFetch) {
          nextValue = await existing.inflight;
        } else {
          const inflightPromise = (async () => {
            const response = await fetcher(
              `/api/workbench/station-directory?platform=${platform}${refresh ? '&refresh=1' : ''}`,
              { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) },
            );
            const value = await response.json();
            if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '目录暂不可用');
            const normalized =
              platform === 'xiaoxiang' && Array.isArray(value?.cities)
                ? { ...value, cities: sortCitiesWithLanorangeFirst(value.cities) }
                : value;
            if (fetcher === defaultFetch) {
              directoryCache.set(cacheKey, {
                data: normalized,
                timestamp: Date.now(),
              });
            }
            return normalized;
          })();

          if (fetcher === defaultFetch) {
            directoryCache.set(cacheKey, {
              data: existing?.data ?? null,
              timestamp: existing?.timestamp ?? 0,
              inflight: inflightPromise,
            });
          }

          try {
            nextValue = await inflightPromise;
          } finally {
            const latest = directoryCache.get(cacheKey);
            if (latest?.inflight === inflightPromise) {
              delete latest.inflight;
            }
          }
        }

        if (!disposed && request === generation) {
          setData(nextValue);
          setError('');
          const isPendingSync = nextValue?.status === 'loading' || nextValue?.status === 'syncing';
          if (isPendingSync) {
            timer = setTimeout(() => void read(true), 2500);
          }
        }
      } catch (problem) {
        if (!disposed && request === generation) {
          setError(problem instanceof Error ? problem.message : '站点目录暂不可用');
        }
      }
    }

    const changed = (event: any) => {
      const source = event.detail?.source;
      if (source && source !== platform) return;
      clearTimeout(timer);
      directoryCache.delete(cacheKey);
      setData(null);
      void read(true);
    };

    window.addEventListener('workbench:platform-session-changed', changed);
    if (reload > 0) {
      directoryCache.delete(cacheKey);
      setData(null);
    }
    void read(reload > 0);

    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener('workbench:platform-session-changed', changed);
    };
  }, [platform, reload, enabled]);

  const normalizedPlatform: 'fengshen' | 'xiaoxiang' = platform === 'xiaoxiang' ? 'xiaoxiang' : 'fengshen';
  const isLoggedIn = auth.isLoggedIn(normalizedPlatform);
  const hasLiveDirectory = Boolean(
    data &&
      data.status === 'ready' &&
      Array.isArray(data.cities) &&
      data.cities.some(c => typeof c.station_count === 'number'),
  );
  const useDemo =
    typeof window !== 'undefined' &&
    enabled &&
    shouldUseDemoData({
      isLoggedIn,
      hasLiveData: hasLiveDirectory,
      demoHidden,
    });

  const demoData = useMemo(
    () => (useDemo ? buildDemoStationDirectory(normalizedPlatform) : null),
    [useDemo, normalizedPlatform],
  );

  return {
    data: useDemo ? demoData : data,
    error: useDemo ? '' : error,
    refresh: () => setReload(value => value + 1),
    isDemo: useDemo,
  };
}

export function stationCountText(directory: any, city: any) {
  const matching = directory?.cities?.filter((value: any) => value.id === city || value.name === city) || [];
  if (matching.length !== 1 || matching[0].station_count === null || matching[0].station_count === undefined) {
    return '待同步';
  }
  return `${matching[0].station_count}站`;
}
