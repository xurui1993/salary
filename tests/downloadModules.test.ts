import test from 'node:test';
import assert from 'node:assert/strict';
import {
  moduleAcceptsDataset,
  matchesRecordModule,
  inferDatasetPlatform,
  toggleCrossPlatformDataset,
  groupDatasetsByPlatform,
  computeDynamicScopeRequirements,
} from '../src/lib/downloadModules';

test('platform downloads integrate generated reports into fengshen while excluding them from other platforms', () => {
  assert(moduleAcceptsDataset('invitation_records', 'fengshen'));
  assert(moduleAcceptsDataset('attendance_detail', 'fengshen'));
  assert(moduleAcceptsDataset('payment_binding', 'fengshen'));
  assert(moduleAcceptsDataset('abnormal_followup', 'fengshen'));
  assert(moduleAcceptsDataset('abnormal_riders', 'fengshen'));
  assert(moduleAcceptsDataset('lanorange_part_price', 'lanorange'));
  assert(moduleAcceptsDataset('baize_employees', 'payout'));
  assert(moduleAcceptsDataset('benlai_employees', 'payout'));
  assert(moduleAcceptsDataset('rider_daily', 'xiaoxiang'));
  assert(!moduleAcceptsDataset('payment_binding', 'lanorange'));
  assert(!moduleAcceptsDataset('abnormal_riders', 'lanorange'));
  assert(!moduleAcceptsDataset('payment_binding', 'payout'));
  assert(!moduleAcceptsDataset('payment_binding', 'xiaoxiang'));
  assert(!moduleAcceptsDataset('rider_daily', 'fengshen'));
  assert(!moduleAcceptsDataset('delivery_fee', 'payout'));
});

test('local history matches generated reports under fengshen and preserves legacy filters', () => {
  const report = { kind: 'generate', datasets: ['abnormal_followup', 'lanorange_part_price'] };
  assert(matchesRecordModule(report, 'generate'));
  assert(matchesRecordModule(report, 'fengshen'));
  assert(!matchesRecordModule(report, 'lanorange'));
  const legacy = { datasets: ['delivery_fee', 'lanorange_part_price'] };
  assert(matchesRecordModule(legacy, 'fengshen'));
  assert(matchesRecordModule(legacy, 'lanorange'));
  assert(!matchesRecordModule(legacy, 'payout'));
  assert(matchesRecordModule({ datasets: ['benlai_employees'] }, 'payout'));
  assert(matchesRecordModule({ datasets: ['baize_employees'] }, 'payout'));
  assert(!matchesRecordModule({ kind: 'payroll', datasets: ['delivery_fee'] }, 'fengshen'));
  assert(matchesRecordModule(report));
});

test('cross-platform cart preserves datasets across all 4 platforms and computes dynamic scope requirements', () => {
  assert.equal(inferDatasetPlatform('delivery_fee'), 'fengshen');
  assert.equal(inferDatasetPlatform('lanorange_rider_profile'), 'lanorange');
  assert.equal(inferDatasetPlatform('baize_employees'), 'payout');
  assert.equal(inferDatasetPlatform('rider_daily'), 'xiaoxiang');

  let selected: string[] = [];
  selected = toggleCrossPlatformDataset(selected, 'delivery_fee');
  selected = toggleCrossPlatformDataset(selected, 'baize_employees');
  selected = toggleCrossPlatformDataset(selected, 'lanorange_rider_archive');
  selected = toggleCrossPlatformDataset(selected, 'rider_daily');
  assert.deepEqual(selected, ['delivery_fee', 'baize_employees', 'lanorange_rider_archive', 'rider_daily']);

  const grouped = groupDatasetsByPlatform(selected);
  assert.deepEqual(grouped, {
    fengshen: ['delivery_fee'],
    lanorange: ['lanorange_rider_archive'],
    payout: ['baize_employees'],
    xiaoxiang: ['rider_daily'],
  });

  // Dynamic scope requirements adapt to platform & selected datasets
  const payoutScope = computeDynamicScopeRequirements('payout', ['baize_employees']);
  assert.equal(payoutScope.needsCity, false);
  assert.equal(payoutScope.needsDate, false);

  const archiveScope = computeDynamicScopeRequirements('lanorange', ['lanorange_rider_archive']);
  assert.equal(archiveScope.needsCity, true);
  assert.equal(archiveScope.cityOptional, true);
  assert.equal(archiveScope.needsDate, false);

  const fengshenDatedScope = computeDynamicScopeRequirements('fengshen', ['delivery_fee']);
  assert.equal(fengshenDatedScope.needsCity, true);
  assert.equal(fengshenDatedScope.needsDate, true);
  assert.equal(fengshenDatedScope.needsSeparationRule, true);

  const abnormalRidersScope = computeDynamicScopeRequirements('fengshen', ['abnormal_riders']);
  assert.equal(abnormalRidersScope.needsCity, false);
  assert.equal(abnormalRidersScope.needsDate, false);
  assert.equal(abnormalRidersScope.needsSeparationRule, false);
});

