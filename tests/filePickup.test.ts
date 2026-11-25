import test from 'node:test';
import assert from 'node:assert/strict';
import {
  deliverableTasks,
  formatPickupSize,
  formatShareTime,
  joinSharePath,
  parentSharePath,
  taskBundleTarget,
  taskDownloadableFiles,
  taskFileTarget,
} from '../src/lib/filePickup';

const files = [
  { name: '汇总.xlsx', id: 'f1', run_id: 'run-1' },
  { name: '已删除.xlsx', id: 'f2', run_id: 'run-1', available: false },
];

test('deliverableTasks keeps finished tasks with claimable files only', () => {
  const rows = deliverableTasks([
    { id: 'a', kind: 'download', status: 'success', files },
    { id: 'b', kind: 'download', status: 'running', files },
    { id: 'c', kind: 'download', status: 'success', files: [{ name: 'x', available: false }] },
    { id: 'd', kind: 'approval', status: 'partial', price_id: 'p1', files: [] },
    { id: 'e', kind: 'price-export', status: 'success', price_id: 'p2' },
    { id: 'f', kind: 'approval', status: 'success', files: [] },
  ]);
  assert.deepEqual(rows.map(row => row.id), ['a', 'd', 'e']);
});

test('taskFileTarget maps run files and special approval/price exports', () => {
  assert.deepEqual(taskFileTarget({ id: 'a', kind: 'download', status: 'success' }, files[0]), {
    url: '/api/fengshen-downloads/runs/run-1/files/f1',
    name: '汇总.xlsx',
  });
  assert.deepEqual(taskFileTarget({ id: 'd', kind: 'approval', status: 'partial', price_id: 'p1' }), {
    url: '/api/fengshen-downloads/lanorange-approvals/batches/p1/result.csv',
    name: '蓝橙价格审批回执.csv',
  });
  assert.deepEqual(taskFileTarget({ id: 'e', kind: 'price-export', status: 'success', price_id: 'p2' }), {
    url: '/api/fengshen-downloads/lanorange-prices/exports/p2/result.xlsx',
    name: '蓝橙待审每日价格.xlsx',
  });
  assert.equal(taskFileTarget({ id: 'a', kind: 'download', status: 'success' }, { name: '缺字段.xlsx' }), null);
});

test('taskBundleTarget packages regular tasks and reuses special files', () => {
  assert.deepEqual(taskBundleTarget({ id: 'abcdef123456', kind: 'generate', status: 'success' }), {
    url: '/api/fengshen-downloads/records/abcdef123456/bundle',
    name: '结果_abcdef12.zip',
  });
  assert.equal(taskBundleTarget({ id: 'd', kind: 'approval', status: 'success', price_id: 'p1' })?.name, '蓝橙价格审批回执.csv');
});

test('taskDownloadableFiles hides unavailable files', () => {
  assert.deepEqual(taskDownloadableFiles({ id: 'a', kind: 'download', status: 'success', files }).map(file => file.name), ['汇总.xlsx']);
  assert.deepEqual(taskDownloadableFiles({ id: 'd', kind: 'approval', status: 'success', files }), []);
});

test('share path helpers stay relative to the share root', () => {
  assert.equal(joinSharePath('', '结果.xlsx'), '结果.xlsx');
  assert.equal(joinSharePath('2026\\11', '结果.xlsx'), '2026\\11\\结果.xlsx');
  assert.equal(parentSharePath('2026\\11\\结果.xlsx'), '2026\\11');
  assert.equal(parentSharePath('结果.xlsx'), '');
});

test('size and share time formatting are stable', () => {
  assert.equal(formatPickupSize(0), '0 B');
  assert.equal(formatPickupSize(2048), '2 KB');
  assert.equal(formatPickupSize(5 * 1024 * 1024), '5.0 MB');
  assert.equal(formatShareTime(0), '');
  assert.match(formatShareTime(1764000000), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});