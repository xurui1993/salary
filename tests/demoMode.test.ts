import test from 'node:test';
import assert from 'node:assert/strict';
import {
  hasAnyAuthenticatedPlatform,
  isPlatformAuthenticated,
  isSpecificPlatformAuthenticated,
} from '../src/lib/demoMode.ts';

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
