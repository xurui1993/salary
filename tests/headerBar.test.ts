import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canStepBack,
  canStepForward,
  createNavHistory,
  PLATFORM_MATRIX_GLYPHS,
  pushNavHistory,
  resolveDispatchIslandState,
  stepNavHistory,
} from '../src/lib/headerBar';

test('navigation history stack tracks back/forward transitions, deduplicates consecutive hits, and truncates forward branch on new push', () => {
  let state = createNavHistory('platform:fengshen');
  assert.equal(canStepBack(state), false);
  assert.equal(canStepForward(state), false);

  // Pushing identical target is a no-op
  state = pushNavHistory(state, 'platform:fengshen');
  assert.deepEqual(state.entries, ['platform:fengshen']);

  state = pushNavHistory(state, 'payroll:batches');
  state = pushNavHistory(state, 'payroll:deductions');
  assert.equal(canStepBack(state), true);
  assert.equal(canStepForward(state), false);

  const back1 = stepNavHistory(state, 'back');
  assert.equal(back1.target, 'payroll:batches');
  assert.equal(canStepBack(back1.nextState), true);
  assert.equal(canStepForward(back1.nextState), true);

  const back2 = stepNavHistory(back1.nextState, 'back');
  assert.equal(back2.target, 'platform:fengshen');
  assert.equal(canStepBack(back2.nextState), false);

  const fwd = stepNavHistory(back2.nextState, 'forward');
  assert.equal(fwd.target, 'payroll:batches');

  // Navigating to a new destination clears forward branch
  const branched = pushNavHistory(fwd.nextState, 'workspace:approval');
  assert.deepEqual(branched.entries, ['platform:fengshen', 'payroll:batches', 'workspace:approval']);
  assert.equal(canStepForward(branched), false);
});

test('resolveDispatchIslandState selects running, error, and idle modes with accurate metrics and actions', () => {
  const runningDeterminate = resolveDispatchIslandState({
    runningTask: 'core',
    progress: 64.6,
    progressText: '正在核算宁波站点账单',
    activeDownloadCount: 0,
    approvalActiveCount: 0,
    errorLogCount: 2,
    readyChannelCount: 3,
    totalChannelCount: 5,
  });
  assert.equal(runningDeterminate.mode, 'running');
  assert.equal(runningDeterminate.primaryText, '正在核算宁波站点账单');
  assert.equal(runningDeterminate.secondaryText, '65%');
  assert.equal(runningDeterminate.progressPct, 65);
  assert.equal(runningDeterminate.indeterminate, false);
  assert.equal(runningDeterminate.action, 'open-logs');

  const runningDownload = resolveDispatchIslandState({
    runningTask: null,
    progress: 0,
    progressText: '',
    activeDownloadCount: 2,
    approvalActiveCount: 0,
    errorLogCount: 0,
    readyChannelCount: 5,
    totalChannelCount: 5,
  });
  assert.equal(runningDownload.mode, 'running');
  assert.equal(runningDownload.primaryText, '2 项资料采集中');
  assert.equal(runningDownload.indeterminate, true);
  assert.equal(runningDownload.action, 'open-history');

  const errorMode = resolveDispatchIslandState({
    runningTask: null,
    progress: 0,
    progressText: '',
    activeDownloadCount: 0,
    approvalActiveCount: 0,
    errorLogCount: 3,
    readyChannelCount: 4,
    totalChannelCount: 5,
  });
  assert.equal(errorMode.mode, 'error');
  assert.equal(errorMode.primaryText, '检测到 3 条运行异常');
  assert.equal(errorMode.action, 'open-logs');

  const idleMode = resolveDispatchIslandState({
    runningTask: null,
    progress: 0,
    progressText: '',
    activeDownloadCount: 0,
    approvalActiveCount: 0,
    errorLogCount: 0,
    readyChannelCount: 2,
    totalChannelCount: 5,
  });
  assert.equal(idleMode.mode, 'idle');
  assert.equal(idleMode.secondaryText, '2/5 通道在线');
  assert.equal(idleMode.action, 'open-cmdk');
});

test('PLATFORM_MATRIX_GLYPHS covers all 5 integrated channels with crisp single-character badges', () => {
  assert.equal(PLATFORM_MATRIX_GLYPHS.fengshen.glyph, '风');
  assert.equal(PLATFORM_MATRIX_GLYPHS.lanorange.glyph, '蓝');
  assert.equal(PLATFORM_MATRIX_GLYPHS.baize.glyph, '商');
  assert.equal(PLATFORM_MATRIX_GLYPHS.benlai.glyph, '本');
  assert.equal(PLATFORM_MATRIX_GLYPHS.xiaoxiang.glyph, '象');
});
