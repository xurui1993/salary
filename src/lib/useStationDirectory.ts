// @ts-nocheck
import { useEffect, useMemo, useState } from 'react';
import { getWorkspaceId } from '../utils';
import { sortCitiesWithLanorangeFirst } from './workbench';

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
  [key: string]: any;
}

export type DirectoryStation = any;

export function useStationDirectory(
  platform: any,
  fetcher: any = defaultFetch,
  enabled = true,
): { data: StationDirectory | null; error: string; refresh: () => void } {
  const [data, setData] = useState<StationDirectory | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let timer: any;
    let generation = 0;
    const controller = new AbortController();

    async function read(refresh = false) {
      const request = ++generation;
      try {
        const response = await fetcher(
          `/api/workbench/station-directory?platform=${platform}${refresh ? '&refresh=1' : ''}`,
          { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) },
        );
        const value = await response.json();
        if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '目录暂不可用');
        if (!disposed && request === generation) {
          const nextValue =
            platform === 'xiaoxiang' && Array.isArray(value?.cities)
              ? { ...value, cities: sortCitiesWithLanorangeFirst(value.cities) }
              : value;
          setData(nextValue);
          setError('');
        }
      } catch (problem) {
        if (!disposed && request === generation) {
          setError(problem instanceof Error ? problem.message : '站点目录暂不可用');
        }
      }
      if (!disposed && request === generation) {
        timer = setTimeout(() => void read(), 2000);
      }
    }

    const changed = (event: any) => {
      const source = event.detail?.source;
      if (source && source !== platform) return;
      clearTimeout(timer);
      setData(null);
      void read(true);
    };

    window.addEventListener('workbench:platform-session-changed', changed);
    setData(null);
    void read(reload > 0);

    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener('workbench:platform-session-changed', changed);
    };
  }, [platform, reload, enabled]);

  return {
    data,
    error,
    refresh: () => setReload(value => value + 1),
  };
}

export function stationCountText(directory: any, city: any) {
  const matching = directory?.cities?.filter((value: any) => value.id === city || value.name === city) || [];
  if (matching.length !== 1 || matching[0].station_count === null || matching[0].station_count === undefined) {
    return '待同步';
  }
  return `${matching[0].station_count}站`;
}
