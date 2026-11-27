import test from 'node:test';
import assert from 'node:assert/strict';

import {
  arePlatformStatusMapsEqual,
  areSystemStatsVisuallyEqual,
  buildApprovalBatchesFingerprint,
  buildPayrollQueueFingerprint,
  buildTaskListFingerprint,
  computeAdaptivePollDelay,
  hasActiveApprovalBatches,
  hasActivePayrollQueueTasks,
  isPlatformStatusRecordEqual,
} from '../src/lib/perfUtils';

test('computeAdaptivePollDelay pauses when hidden and throttles based on view activity and task activity', () => {
  assert.equal(
    computeAdaptivePollDelay({ hasActiveTasks: true, isDocumentVisible: false, isViewActive: true }),
    null,
  );
  assert.equal(
    computeAdaptivePollDelay({ hasActiveTasks: true, isDocumentVisible: true, isViewActive: true }),
    3500,
  );
  assert.equal(
    computeAdaptivePollDelay({ hasActiveTasks: true, isDocumentVisible: true, isViewActive: false }),
    8000,
  );
  assert.equal(
    computeAdaptivePollDelay({ hasActiveTasks: false, isDocumentVisible: true, isViewActive: true }),
    12000,
  );
  assert.equal(
    computeAdaptivePollDelay({ hasActiveTasks: false, isDocumentVisible: true, isViewActive: false }),
    20000,
  );
});

test('buildTaskListFingerprint detects meaningful progress or status changes while staying stable across identical polls', () => {
  const base = [
    { id: 'r1', status: 'running', completed_items: 2, total_items: 6, failed_items: 0, available_files: 1 },
    { id: 'r2', status: 'success', completed_items: 4, total_items: 4, failed_items: 0, available_files: 4 },
  ];
  const counts = { all: 2, active: 1, success: 1 };

  const fp1 = buildTaskListFingerprint(base, counts);
  const fp2 = buildTaskListFingerprint(
    base.map(item => ({ ...item })),
    { success: 1, all: 2, active: 1 },
  );
  assert.equal(fp1, fp2);

  const fpProgress = buildTaskListFingerprint(
    [
      { ...base[0], completed_items: 3 },
      base[1],
    ],
    counts,
  );
  assert.notEqual(fp1, fpProgress);

  const fpStatus = buildTaskListFingerprint(
    [
      { ...base[0], status: 'success', completed_items: 6 },
      base[1],
    ],
    { all: 2, active: 0, success: 2 },
  );
  assert.notEqual(fp1, fpStatus);
});

test('areSystemStatsVisuallyEqual ignores sub-decimal jitter and flags real display changes', () => {
  const a = {
    sysCpu: 14.21,
    cpuCores: 4,
    sysMemRatio: 41.82,
    usedMemGb: 6.71,
    totalMemGb: 16,
    procMem: 136.2,
  };
  const b = {
    sysCpu: 14.24,
    cpuCores: 4,
    sysMemRatio: 41.84,
    usedMemGb: 6.72,
    totalMemGb: 16,
    procMem: 136.4,
  };
  const c = {
    ...a,
    sysCpu: 18.6,
  };

  assert.equal(areSystemStatsVisuallyEqual(a, b), true);
  assert.equal(areSystemStatsVisuallyEqual(a, c), false);
  assert.equal(areSystemStatsVisuallyEqual(null, a), false);
  assert.equal(areSystemStatsVisuallyEqual(null, null), true);
});

test('isPlatformStatusRecordEqual and arePlatformStatusMapsEqual prevent redundant status re-renders', () => {
  const s1 = { state: 'ready', saved: true, offline: false, session_version: 'v1' };
  const s2 = { state: 'ready', saved: true, offline: false, session_version: 'v1' };
  const s3 = { state: 'login_required', saved: false, offline: false, session_version: 'v2' };

  assert.equal(isPlatformStatusRecordEqual(s1, s2), true);
  assert.equal(isPlatformStatusRecordEqual(s1, s3), false);
  assert.equal(
    arePlatformStatusMapsEqual({ lanorange: s1, baize: s1 }, { lanorange: s2, baize: s2 }),
    true,
  );
  assert.equal(
    arePlatformStatusMapsEqual({ lanorange: s1, baize: s1 }, { lanorange: s3, baize: s2 }),
    false,
  );

  const waitingLoading = {
    state: 'waiting_login',
    saved: false,
    offline: false,
    busy: true,
    session_id: 'sid-1',
    message: '请扫码',
    has_qr: false,
    qr_state: 'not_detected',
    form_detection: 'loading',
    fields: [],
  };
  const waitingQrReady = {
    ...waitingLoading,
    has_qr: true,
    qr_state: 'visible',
    qr_version: 'abc123',
    form_detection: 'qr_only',
  };
  const waitingFormReady = {
    ...waitingLoading,
    form_detection: 'fields_detected',
    form_id: 'f1',
    fields: [{ id: 'u', role: 'username', label: '账号' }],
    math_captcha: { id: 'm1', state: 'manual', image: 'data:image/png;base64,AAA' },
  };
  assert.equal(isPlatformStatusRecordEqual(waitingLoading, waitingQrReady), false);
  assert.equal(isPlatformStatusRecordEqual(waitingLoading, waitingFormReady), false);
  assert.equal(isPlatformStatusRecordEqual(waitingFormReady, { ...waitingFormReady }), true);
});

test('buildPayrollQueueFingerprint and buildApprovalBatchesFingerprint stabilize idle polling', () => {
  const tasks = [
    { id: 't1', status: 'calculated', stage: 'done', applicant_count: 42 },
  ];
  assert.equal(hasActivePayrollQueueTasks(tasks), false);
  assert.equal(hasActivePayrollQueueTasks([{ id: 't2', status: 'running' }]), true);
  assert.equal(
    buildPayrollQueueFingerprint(tasks),
    buildPayrollQueueFingerprint(tasks.map(t => ({ ...t }))),
  );

  const batches = [
    { id: 'b1', status: 'completed', approved_count: 10, total_count: 10, failed_count: 0 },
  ];
  assert.equal(hasActiveApprovalBatches(batches), false);
  assert.equal(hasActiveApprovalBatches([{ id: 'b2', status: 'running' }]), true);
  assert.equal(
    buildApprovalBatchesFingerprint(batches),
    buildApprovalBatchesFingerprint(batches.map(b => ({ ...b }))),
  );
});

