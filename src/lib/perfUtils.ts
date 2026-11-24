import type { SystemResourceStatsInput } from './workbench';

export interface AdaptivePollInput {
  hasActiveTasks: boolean;
  isDocumentVisible: boolean;
  isViewActive: boolean;
  activeMs?: number;
  backgroundActiveMs?: number;
  idleMs?: number;
  backgroundIdleMs?: number;
}

/**
 * Compute adaptive polling interval (in ms), or `null` when polling should pause.
 * Prevents hammering the backend and JS main thread when the browser tab is hidden,
 * when no tasks are running, or when the consumer view is not currently on screen.
 */
export function computeAdaptivePollDelay({
  hasActiveTasks,
  isDocumentVisible,
  isViewActive,
  activeMs = 3500,
  backgroundActiveMs = 8000,
  idleMs = 12000,
  backgroundIdleMs = 20000,
}: AdaptivePollInput): number | null {
  if (!isDocumentVisible) return null;
  if (hasActiveTasks) {
    return isViewActive ? activeMs : backgroundActiveMs;
  }
  return isViewActive ? idleMs : backgroundIdleMs;
}

export interface FingerprintableTaskRecord {
  id: string;
  status?: string;
  completed_items?: number;
  failed_items?: number;
  total_items?: number;
  available_files?: number;
  current_action?: string;
  phase?: string;
  error?: string;
  updated_at?: string | number;
  finished_at?: string | number;
  files?: ReadonlyArray<{ id?: string; available?: boolean }>;
}

/**
 * Fast O(N) string fingerprint for task-center records & counts so polling hooks
 * skip redundant React state updates and table re-renders when nothing changed.
 */
export function buildTaskListFingerprint(
  records: ReadonlyArray<FingerprintableTaskRecord>,
  counts?: Record<string, number> | null,
  extra?: string,
): string {
  const parts: string[] = [];
  for (let i = 0; i < records.length; i += 1) {
    const r = records[i];
    const availCount = r.available_files ?? r.files?.length ?? 0;
    parts.push(
      `${r.id}|${r.status ?? ''}|${r.completed_items ?? 0}/${r.total_items ?? 0}|f${r.failed_items ?? 0}|a${availCount}|${r.phase ?? ''}|${r.current_action ?? ''}|${r.updated_at ?? ''}|${r.finished_at ?? ''}|${r.error ?? ''}`,
    );
  }
  let countsPart = '';
  if (counts) {
    const keys = Object.keys(counts).sort();
    countsPart = keys.map(k => `${k}:${counts[k]}`).join(',');
  }
  return `${countsPart}#${extra ?? ''}#${parts.join(';')}`;
}

/**
 * Fast equality check on rendered SidebarResourceStrip values so tiny 0.01% jitter
 * or unchanged payloads never cause redundant re-renders.
 */
export function areSystemStatsVisuallyEqual(
  prev: SystemResourceStatsInput | null,
  next: SystemResourceStatsInput | null,
): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  const pCpu = Math.round((prev.sysCpu ?? 0) * 10);
  const nCpu = Math.round((next.sysCpu ?? 0) * 10);
  const pMem = Math.round((prev.sysMemRatio ?? 0) * 10);
  const nMem = Math.round((next.sysMemRatio ?? 0) * 10);
  const pUsed = Math.round((prev.usedMemGb ?? 0) * 10);
  const nUsed = Math.round((next.usedMemGb ?? 0) * 10);
  const pProc = Math.round(prev.procMem ?? 0);
  const nProc = Math.round(next.procMem ?? 0);
  return (
    pCpu === nCpu &&
    pMem === nMem &&
    pUsed === nUsed &&
    pProc === nProc &&
    (prev.cpuCores ?? 0) === (next.cpuCores ?? 0) &&
    (prev.totalMemGb ?? 0) === (next.totalMemGb ?? 0)
  );
}
