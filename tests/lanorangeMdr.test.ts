import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { DualRailSidebar } from '../src/components/DualRailSidebar';
import { datasetGroup, isMdr, isLanorange, selectionKey } from '../src/lib/downloadCenterLogic';
import {
  DOWNLOAD_PLATFORMS,
  computeDynamicScopeRequirements,
  groupDatasetsByPlatform,
  inferDatasetPlatform,
} from '../src/lib/downloadModules';

test('new Lancheng datasets form an independent platform group', () => {
  const ids = ['lcmdr_archive', 'lcmdr_exit', 'lcmdr_batch_exit', 'lcmdr_exit_report',
    'lcmdr_leave', 'lcmdr_type_change', 'lcmdr_commission_proxy', 'lcmdr_part_price'];
  for (const id of ids) {
    assert.equal(isMdr(id), true);
    assert.equal(isLanorange(id), false);
    assert.equal(datasetGroup(id), 'lanorange_mdr');
    assert.equal(inferDatasetPlatform(id), 'lanorange_mdr');
  }
  assert.ok(DOWNLOAD_PLATFORMS.some(item => item.id === 'lanorange_mdr' && item.navLabel === '新蓝橙数据'));
  assert.deepEqual(groupDatasetsByPlatform(['lcmdr_leave', 'lanorange_rider_leave']), {
    fengshen: [],
    lanorange: ['lanorange_rider_leave'],
    lanorange_mdr: ['lcmdr_leave'],
    payout: [],
    xiaoxiang: [],
  });
});

test('new Lancheng scope requires a city and months only for price or commission', () => {
  const plain = computeDynamicScopeRequirements('lanorange_mdr', ['lcmdr_leave', 'lcmdr_exit']);
  assert.equal(plain.needsCity, true);
  assert.equal(plain.cityOptional, false);
  assert.equal(plain.needsDate, false);
  const priced = computeDynamicScopeRequirements('lanorange_mdr', ['lcmdr_part_price']);
  assert.equal(priced.needsDate, true);
  const commission = computeDynamicScopeRequirements('lanorange_mdr', ['lcmdr_leave', 'lcmdr_commission_proxy']);
  assert.equal(commission.needsDate, true);
});

test('selection key keeps new Lancheng city and month scope', () => {
  const key = selectionKey({ cities: ['广州', '深圳'], datasets: ['lcmdr_part_price', 'lcmdr_leave'], start: '2026-11-01', end: '2026-11-30', lanorange_months: ['2026-11'] });
  const parsed = JSON.parse(key);
  assert.deepEqual(parsed.cities, ['广州', '深圳']);
  assert.equal(parsed.scope, 'city');
  assert.deepEqual(parsed.lanorange_months, ['2026-11']);
});

test('left sidebar exposes the new Lancheng data entry', () => {
  const html = renderToStaticMarkup(React.createElement(DualRailSidebar, {
    workspaceView: 'create',
    taskKind: 'download',
    downloadPlatform: 'lanorange',
    payrollSubView: 'batches',
    isDrawerMode: false,
    taskFormLocked: false,
    platformStatuses: {},
    activeDownloadCount: 0,
    payrollBadge: null,
    approvalActiveCount: 0,
    totalActiveCount: 0,
    onExecuteAction: () => {},
    onCloseMobile: () => {},
    onOpenPlatformDock: () => {},
  }));
  assert.match(html, /新蓝橙数据/);
  assert.match(html, /data-nav-key="platform:lanorange_mdr"/);
});