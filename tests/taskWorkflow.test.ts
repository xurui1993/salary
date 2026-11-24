import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTO_JUMP_STORAGE_KEY,
  buildTaskReturnTarget,
  computeTaskHeaderCounts,
  detectTaskNotifications,
  readAutoJumpPreference,
  writeAutoJumpPreference,
  type StorageLike,
} from '../src/lib/taskWorkflow';

function createMemoryStorage(initial: Record<string, string> = {}): StorageLike {
  const store = new Map<string, string>(Object.entries(initial));
  return {
    getItem(key) {
      return store.has(key) ? store.get(key)! : null;
    },
    setItem(key, value) {
      store.set(key, value);
    },
  };
}

test('auto-jump preference defaults to true and persists toggle changes', () => {
  const storage = createMemoryStorage();
  assert.equal(readAutoJumpPreference(storage), true);

  writeAutoJumpPreference(false, storage);
  assert.equal(storage.getItem(AUTO_JUMP_STORAGE_KEY), '0');
  assert.equal(readAutoJumpPreference(storage), false);

  writeAutoJumpPreference(true, storage);
  assert.equal(storage.getItem(AUTO_JUMP_STORAGE_KEY), '1');
  assert.equal(readAutoJumpPreference(storage), true);
});

test('buildTaskReturnTarget maps collection, report, payroll, and approval views cleanly', () => {
  const fromFengshen = buildTaskReturnTarget({
    workspaceView: 'create',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.deepEqual(fromFengshen, {
    label: '返回风神数据',
    action: { type: 'platform', platform: 'fengshen' },
  });

  const fromProblemReport = buildTaskReturnTarget({
    workspaceView: 'create',
    taskKind: 'generate',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
    reportId: 'problem',
  });
  assert.deepEqual(fromProblemReport, {
    label: '返回问题单',
    action: { type: 'report', reportId: 'problem' },
  });

  const fromPayroll = buildTaskReturnTarget({
    workspaceView: 'create',
    taskKind: 'payroll',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.deepEqual(fromPayroll, {
    label: '返回兼职核算',
    action: { type: 'payroll', subView: 'batches' },
  });

  const fromHistory = buildTaskReturnTarget({
    workspaceView: 'history',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  });
  assert.equal(fromHistory, null);
});

test('detectTaskNotifications suppresses initial hydration and emits completed / blocked alerts once per transition', () => {
  const seen = new Set<string>();
  const initialRecords = [
    { id: 't1', status: 'running', title: '配送费、违规扣款', datasets: ['delivery_waybill'], available_files: 0 },
    { id: 't2', status: 'running', title: '蓝橙在职人员', datasets: ['lanorange_staff'], available_files: 0 },
    { id: 't3', status: 'running', title: '问题单', kind: 'generate', datasets: ['problem'], available_files: 0 },
    { id: 't4', status: 'success', title: '旧已完成任务', datasets: ['rider_info'], available_files: 2 },
  ];

  // Initial hydration must not fire notifications
  const first = detectTaskNotifications(null, initialRecords, seen, { now: 1000 });
  assert.equal(first.alerts.length, 0);
  assert.equal(first.nextSnapshot.get('t1'), 'running');

  // Second poll: t1 succeeds, t2 waits for login, t3 fails partially, t4 stays success
  const second = detectTaskNotifications(
    first.nextSnapshot,
    [
      { id: 't1', status: 'success', title: '配送费、违规扣款', datasets: ['delivery_waybill'], available_files: 3 },
      { id: 't2', status: 'waiting_login', title: '蓝橙在职人员', datasets: ['lanorange_staff'], available_files: 0 },
      { id: 't3', status: 'partial', title: '问题单', kind: 'generate', datasets: ['problem'], available_files: 1, failed_items: 2 },
      { id: 't4', status: 'success', title: '旧已完成任务', datasets: ['rider_info'], available_files: 2 },
    ],
    seen,
    { now: 2000 },
  );

  assert.equal(second.alerts.length, 3);
  const byTask = new Map(second.alerts.map(a => [a.taskId, a]));

  assert.equal(byTask.get('t1')?.kind, 'completed');
  assert.equal(byTask.get('t1')?.canOpenDir, true);
  assert.equal(byTask.get('t1')?.needsAuth, false);

  assert.equal(byTask.get('t2')?.kind, 'blocked');
  assert.equal(byTask.get('t2')?.needsAuth, true);
  assert.equal(byTask.get('t2')?.primarySystem, 'lanorange');

  assert.equal(byTask.get('t3')?.kind, 'blocked');
  assert.equal(byTask.get('t3')?.canOpenDir, true);
  assert.match(byTask.get('t3')?.subtitle || '', /2 项/);

  // Deduplication prevents re-firing the same transition
  for (const alert of second.alerts) seen.add(alert.key);
  const third = detectTaskNotifications(
    first.nextSnapshot,
    [
      { id: 't1', status: 'success', title: '配送费、违规扣款', datasets: ['delivery_waybill'], available_files: 3 },
    ],
    seen,
    { now: 3000 },
  );
  assert.equal(third.alerts.length, 0);
});

test('computeTaskHeaderCounts separates running, attention, and ready counts cleanly', () => {
  const counts = computeTaskHeaderCounts([
    { status: 'running' },
    { status: 'queued' },
    { status: 'waiting_login' },
    { status: 'partial' },
    { status: 'error' },
    { status: 'success' },
    { status: 'success' },
    { status: 'cancelled' },
  ]);
  assert.deepEqual(counts, {
    activeCount: 2,
    attentionCount: 3,
    readyCount: 2,
  });
});
