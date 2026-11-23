import test from 'node:test';
import assert from 'node:assert/strict';
import {
  hasAnyAuthenticatedPlatform,
  isPlatformAuthenticated,
  isSpecificPlatformAuthenticated,
  shouldUseDemoData,
} from '../src/lib/demoMode.ts';
import {
  buildDemoApprovalPriceTable,
  buildDemoApprovalReceiptBatches,
  buildDemoApprovalReceiptCsv,
  buildDemoEngineLogs,
  buildDemoLanorangeApprovals,
  buildDemoStationDirectory,
} from '../src/lib/showcaseDemoData.ts';

test('isPlatformAuthenticated: 严格区分未登录、离线与真实登录态', () => {
  assert.equal(isPlatformAuthenticated(null), false);
  assert.equal(isPlatformAuthenticated(undefined), false);
  assert.equal(isPlatformAuthenticated({}), false);
  assert.equal(isPlatformAuthenticated({ saved: false, state: 'signed_out' }), false);
  assert.equal(isPlatformAuthenticated({ saved: true, state: 'signed_out' }), false);
  assert.equal(isPlatformAuthenticated({ saved: true, state: 'login_required' }), false);
  assert.equal(isPlatformAuthenticated({ saved: true, state: 'ready', offline: true }), false);

  assert.equal(isPlatformAuthenticated({ saved: true, state: 'ready' }), true);
  assert.equal(isPlatformAuthenticated({ saved: true }), true);
  assert.equal(isPlatformAuthenticated({ state: 'ready' }), true);
  assert.equal(isPlatformAuthenticated({ loggedIn: true }), true);
});

test('hasAnyAuthenticatedPlatform & isSpecificPlatformAuthenticated: 支持 5 平台与风神独立态', () => {
  assert.equal(hasAnyAuthenticatedPlatform({}, null), false);
  assert.equal(
    hasAnyAuthenticatedPlatform(
      {
        fengshen: { saved: false, state: 'login_required' },
        lanorange: { saved: false, state: 'signed_out' },
        baize: { offline: true, state: 'ready' },
      },
      { loggedIn: false, state: 'login_required' },
    ),
    false,
  );

  // 任一真实平台登录即视为已登录
  assert.equal(
    hasAnyAuthenticatedPlatform({
      fengshen: { saved: false, state: 'signed_out' },
      lanorange: { saved: true, state: 'ready' },
    }),
    true,
  );
  assert.equal(
    hasAnyAuthenticatedPlatform({}, { loggedIn: true, state: 'ready' }),
    true,
  );

  // 单平台精准判定（蓝橙登录后不影响小象/风神各自扣款配置独立判断）
  const statuses = {
    fengshen: { saved: false, state: 'signed_out' },
    lanorange: { saved: true, state: 'ready' },
    xiaoxiang: { saved: false, state: 'login_required' },
  };
  assert.equal(isSpecificPlatformAuthenticated('lanorange', statuses), true);
  assert.equal(isSpecificPlatformAuthenticated('fengshen', statuses), false);
  assert.equal(isSpecificPlatformAuthenticated('xiaoxiang', statuses), false);
  assert.equal(
    isSpecificPlatformAuthenticated('fengshen', statuses, { loggedIn: true }),
    true,
  );
});

test('shouldUseDemoData: 未登录无数据时启用示例，真实登录或已有后台数据时强制切回真实数据', () => {
  // 1. 未登录 + 无后台数据 + 未隐藏 => 展示示例数据
  assert.equal(
    shouldUseDemoData({ isLoggedIn: false, hasLiveData: false, demoHidden: false }),
    true,
  );

  // 2. 真实登录后 => 立即关闭示例数据（即使后台暂无记录也绝不用示例遮挡）
  assert.equal(
    shouldUseDemoData({ isLoggedIn: true, hasLiveData: false, demoHidden: false }),
    false,
  );
  assert.equal(
    shouldUseDemoData({ isLoggedIn: true, hasLiveData: true, demoHidden: false }),
    false,
  );

  // 3. 未登录但后台已有真实记录 => 优先展示真实记录，不混入示例
  assert.equal(
    shouldUseDemoData({ isLoggedIn: false, hasLiveData: true, demoHidden: false }),
    false,
  );

  // 4. 用户主动点击「隐藏示例」 => 展示空态/登录引导
  assert.equal(
    shouldUseDemoData({ isLoggedIn: false, hasLiveData: false, demoHidden: true }),
    false,
  );
});

test('新增示例目录、运行日志与回执 CSV 构建器结构完整', () => {
  const fsDir = buildDemoStationDirectory('fengshen');
  assert.equal(fsDir.status, 'ready');
  assert.equal(fsDir.cities.length, 10);
  assert.equal(fsDir.stations.length, 30);
  assert.ok(fsDir.cities.every(c => typeof c.station_count === 'number' && c.station_count > 0));

  const xxDir = buildDemoStationDirectory('xiaoxiang');
  assert.equal(xxDir.platform, 'xiaoxiang');
  assert.equal(xxDir.cities.length, 10);
  assert.equal(xxDir.stations.length, 30);

  const logs = buildDemoEngineLogs();
  assert.ok(logs.length >= 5);
  assert.ok(logs.some(l => l.level === 'SUCCESS'));
  assert.ok(logs.some(l => l.level === 'WARN'));
  assert.ok(logs.every(l => typeof l.time === 'string' && /^\d{2}:\d{2}:\d{2}$/.test(l.time)));

  const approvals = buildDemoLanorangeApprovals();
  const priceTable = buildDemoApprovalPriceTable(approvals[0]);
  assert.equal(priceTable.columns.length, 7);
  assert.ok(priceTable.columns.every(c => Boolean(c.key && c.label)));
  assert.ok(priceTable.rows.length >= 4);
  assert.ok(priceTable.remark.length > 0);

  const history = buildDemoApprovalReceiptBatches();
  assert.equal(history.length, 3);
  assert.ok(history[0].actor_label.length > 0);
  assert.ok(history[0].items.every(i => Boolean(i.task.businessCode && i.status_label)));

  const csv = buildDemoApprovalReceiptCsv(history[0]);
  assert.ok(csv.startsWith('\uFEFF'));
  assert.match(csv, /批次号,流程编号,城市,站点/);
  assert.ok(csv.split('\r\n').length > 2);
});
