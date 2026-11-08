import React, { useEffect } from 'react';
import type { DownloadFetch, DownloadUser } from '../lib/downloadCenterLogic';

const SHARED_USER: DownloadUser = { id: 'shared', username: '小组共享', role: 'admin' };
interface Props { apiFetch: DownloadFetch; onAccountChange?: (accountId?: string) => void; children: (user: DownloadUser, apiFetch: DownloadFetch) => React.ReactNode }

// Shared access for the internal download centre; platform login remains separate.
export function DownloadAccountPanel({ apiFetch, onAccountChange, children }: Props) {
  useEffect(() => {
    onAccountChange?.(SHARED_USER.id);
    return () => onAccountChange?.(undefined);
  }, [onAccountChange]);
  return <>{children(SHARED_USER, apiFetch)}</>;
}
