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
  progress?: number | null;
  error?: string;
  updated_at?: string | number;
  last_activity_at?: string | number;
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
      `${r.id}|${r.status ?? ''}|${r.completed_items ?? 0}/${r.total_items ?? 0}|f${r.failed_items ?? 0}|a${availCount}|p${r.progress ?? ''}|${r.phase ?? ''}|${r.current_action ?? ''}|${r.last_activity_at ?? r.updated_at ?? ''}|${r.finished_at ?? ''}|${r.error ?? ''}`,
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

/**
 * Compare two single-platform status snapshots so background polling in SystemConnections
 * skips state updates and CustomEvent broadcasts when nothing changed.
 */
export function isPlatformStatusRecordEqual(
  prev: Record<string, any> | undefined | null,
  next: Record<string, any> | undefined | null,
): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  if (
    (prev.state ?? '') !== (next.state ?? '') ||
    Boolean(prev.saved) !== Boolean(next.saved) ||
    Boolean(prev.offline) !== Boolean(next.offline) ||
    Boolean(prev.busy) !== Boolean(next.busy) ||
    Boolean(prev.cancelling) !== Boolean(next.cancelling) ||
    (prev.session_version ?? '') !== (next.session_version ?? '') ||
    (prev.session_id ?? '') !== (next.session_id ?? '') ||
    (prev.phase ?? '') !== (next.phase ?? '') ||
    (prev.account_label ?? '') !== (next.account_label ?? '') ||
    (prev.message ?? '') !== (next.message ?? '') ||
    (prev.updated_at ?? '') !== (next.updated_at ?? '')
  ) {
    return false;
  }
  // Compare interactive desktop login / QR / form / captcha fields so live auth modals update immediately.
  if (
    Boolean(prev.has_qr) !== Boolean(next.has_qr) ||
    (prev.qr_state ?? '') !== (next.qr_state ?? '') ||
    (prev.qr_stage ?? '') !== (next.qr_stage ?? '') ||
    (prev.qr_version ?? '') !== (next.qr_version ?? '') ||
    (prev.form_id ?? '') !== (next.form_id ?? '') ||
    (prev.form_detection ?? '') !== (next.form_detection ?? '') ||
    Boolean(prev.transitioning) !== Boolean(next.transitioning) ||
    Boolean(prev.retry) !== Boolean(next.retry) ||
    Boolean(prev.credential_prompt) !== Boolean(next.credential_prompt) ||
    Boolean(prev.input_pending) !== Boolean(next.input_pending) ||
    (prev.input_completed ?? 0) !== (next.input_completed ?? 0) ||
    (prev.input_error ?? '') !== (next.input_error ?? '') ||
    (prev.sms_retry_after ?? 0) !== (next.sms_retry_after ?? 0) ||
    Boolean(prev.has_challenge) !== Boolean(next.has_challenge) ||
    (prev.challenge_id ?? '') !== (next.challenge_id ?? '') ||
    (prev.challenge_version ?? '') !== (next.challenge_version ?? '') ||
    (prev.official_feedback ?? '') !== (next.official_feedback ?? '') ||
    (prev.official_feedback_kind ?? '') !== (next.official_feedback_kind ?? '') ||
    (prev.official_feedback_detail ?? '') !== (next.official_feedback_detail ?? '')
  ) {
    return false;
  }
  const prevMath = prev.math_captcha;
  const nextMath = next.math_captcha;
  if (Boolean(prevMath) !== Boolean(nextMath)) return false;
  if (
    prevMath &&
    nextMath &&
    ((prevMath.id ?? '') !== (nextMath.id ?? '') ||
      (prevMath.state ?? '') !== (nextMath.state ?? '') ||
      (prevMath.answer ?? '') !== (nextMath.answer ?? '') ||
      (prevMath.expression ?? '') !== (nextMath.expression ?? '') ||
      (prevMath.image ?? '') !== (nextMath.image ?? ''))
  ) {
    return false;
  }
  const prevFields = Array.isArray(prev.fields) ? prev.fields : null;
  const nextFields = Array.isArray(next.fields) ? next.fields : null;
  if ((prevFields?.length ?? 0) !== (nextFields?.length ?? 0)) return false;
  if (prevFields && nextFields && prevFields.length > 0) {
    if (JSON.stringify(prevFields) !== JSON.stringify(nextFields)) return false;
  }
  const prevControls = Array.isArray(prev.controls) ? prev.controls : null;
  const nextControls = Array.isArray(next.controls) ? next.controls : null;
  if ((prevControls?.length ?? 0) !== (nextControls?.length ?? 0)) return false;
  if (prevControls && nextControls && prevControls.length > 0) {
    if (JSON.stringify(prevControls) !== JSON.stringify(nextControls)) return false;
  }
  return true;
}

/**
 * Compare two full PlatformStatusMap objects so App root never re-renders on redundant broadcasts.
 */
export function arePlatformStatusMapsEqual(
  prev: Record<string, any> | undefined | null,
  next: Record<string, any> | undefined | null,
): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  const prevKeys = Object.keys(prev);
  const nextKeys = Object.keys(next);
  if (prevKeys.length !== nextKeys.length) return false;
  for (let i = 0; i < prevKeys.length; i += 1) {
    const k = prevKeys[i];
    if (!isPlatformStatusRecordEqual(prev[k], next[k])) {
      return false;
    }
  }
  return true;
}

export interface FingerprintablePayrollTask {
  id?: string;
  status?: string;
  stage?: string;
  updated_at?: string | number;
  error?: string;
  applicant_count?: number;
  output_name?: string;
  approval_code?: string;
  hidden?: boolean;
  [key: string]: any;
}

const ACTIVE_PAYROLL_STATUSES = new Set([
  'queued',
  'running',
  'preparing',
  'calculating',
  'stopping',
]);

export function hasActivePayrollQueueTasks(
  tasks: ReadonlyArray<FingerprintablePayrollTask>,
): boolean {
  for (let i = 0; i < tasks.length; i += 1) {
    const status = String(tasks[i]?.status || '').toLowerCase();
    if (ACTIVE_PAYROLL_STATUSES.has(status)) return true;
  }
  return false;
}

export function buildPayrollQueueFingerprint(
  tasks: ReadonlyArray<FingerprintablePayrollTask>,
): string {
  const parts: string[] = [];
  for (let i = 0; i < tasks.length; i += 1) {
    const t = tasks[i];
    parts.push(
      `${t.id ?? ''}|${t.status ?? ''}|${t.stage ?? ''}|${t.updated_at ?? ''}|${t.applicant_count ?? 0}|${t.output_name ?? ''}|${t.approval_code ?? ''}|${t.hidden ? 1 : 0}|${t.error ?? ''}`,
    );
  }
  return parts.join(';');
}

export interface FingerprintableApprovalBatch {
  id?: string;
  status?: string;
  updated_at?: string;
  approved_count?: number;
  failed_count?: number;
  total_count?: number;
  receipts?: ReadonlyArray<unknown>;
  [key: string]: any;
}

const ACTIVE_APPROVAL_STATUSES = new Set(['queued', 'running', 'stopping']);

export function hasActiveApprovalBatches(
  batches: ReadonlyArray<FingerprintableApprovalBatch>,
): boolean {
  for (let i = 0; i < batches.length; i += 1) {
    if (ACTIVE_APPROVAL_STATUSES.has(String(batches[i]?.status || '').toLowerCase())) {
      return true;
    }
  }
  return false;
}

export function buildApprovalBatchesFingerprint(
  batches: ReadonlyArray<FingerprintableApprovalBatch>,
): string {
  const parts: string[] = [];
  for (let i = 0; i < batches.length; i += 1) {
    const b = batches[i];
    parts.push(
      `${b.id ?? ''}|${b.status ?? ''}|${b.updated_at ?? ''}|${b.approved_count ?? 0}/${b.total_count ?? 0}|f${b.failed_count ?? 0}|r${b.receipts?.length ?? 0}`,
    );
  }
  return parts.join(';');
}

