import test from 'node:test';
import assert from 'node:assert/strict';

import {
  areSystemStatsVisuallyEqual,
  buildTaskListFingerprint,
  computeAdaptivePollDelay,
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
