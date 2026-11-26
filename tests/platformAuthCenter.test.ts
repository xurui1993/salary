import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PLATFORM_AUTH_REGISTRY,
  buildPlatformAuthCardViewModels,
  filterPlatformAuthCards,
  summarizePlatformAuthOverview,
} from '../src/lib/platformAuthCenter';
import {
  buildShellCommands,
  getActiveNavGroup,
  getBreadcrumbModel,
  getCurrentQuickTargetId,
  type ShellNavState,
} from '../src/lib/shellNav';

test('PLATFORM_AUTH_REGISTRY defines 5 platforms with personal and shared scopes', () => {
  assert.equal(PLATFORM_AUTH_REGISTRY.length, 5);
  const personalKeys = PLATFORM_AUTH_REGISTRY.filter(p => p.scope === 'personal').map(p => p.key);
  const sharedKeys = PLATFORM_AUTH_REGISTRY.filter(p => p.scope === 'shared').map(p => p.key);
  assert.deepEqual(personalKeys, ['fengshen', 'lanorange', 'baize']);
  assert.deepEqual(sharedKeys, ['xiaoxiang', 'benlai']);
});

test('buildPlatformAuthCardViewModels & summarizePlatformAuthOverview compute accurate counts and probes', () => {
  const cards = buildPlatformAuthCardViewModels({
    statuses: {
      fengshen: {
        state: 'ready',
        saved: true,
        account_label: 'fs_user_01',
        organization: '深圳分部',
        credential_saved: true,
        capabilities: { cities: { verified: true }, stations: { verified: true } },
      },
      lanorange: {
        state: 'waiting_login',
        saved: false,
        busy: false,
      },
      baize: {
        state: 'ready',
        saved: true,
        account_label: 'sy_enterprise',
        session_version: 'v1',
      },
      xiaoxiang: {
        state: 'saved',
        saved: true,
        session_version: 'v2',
        capabilities: { stations: { verified: true } },
        stages: { board: 'error' },
      },
      benlai: {
        state: 'signed_out',
        saved: false,
      },
    },
    baizeAccount: {
      account_type: 'shanggou',
      region_text: '华南大区',
    },
    isAdmin: false,
    canManageSharedAuth: false,
  });

  const summary = summarizePlatformAuthOverview(cards);
  assert.equal(summary.totalCount, 5);
  assert.equal(summary.readyCount, 2);
  assert.equal(summary.personalCount, 3);
  assert.equal(summary.personalReadyCount, 2);
  assert.equal(summary.sharedCount, 2);
  assert.equal(summary.sharedReadyCount, 0);
  assert.equal(summary.attentionCount, 2); // lanorange (waiting_login) + xiaoxiang (saved/board error)
  assert.equal(summary.idleCount, 1); // benlai

  const fengshenCard = cards.find(c => c.entry.key === 'fengshen')!;
  assert.equal(fengshenCard.isReady, true);
  assert.equal(fengshenCard.canSwitchAccount, true);
  assert.equal(fengshenCard.accountTitle, 'fs_user_01');
  assert.equal(fengshenCard.accountOrganization, '深圳分部');
  assert.ok(fengshenCard.credentialStatusText.includes('加密凭据'));
  assert.ok(fengshenCard.probes.every(p => p.tone === 'ready'));

  const baizeCard = cards.find(c => c.entry.key === 'baize')!;
  assert.equal(baizeCard.accountSubtypeLabel, '闪购业务账户（华南大区）');

  // Non-admin without shared_auth_manage cannot manage shared platforms (xiaoxiang / benlai)
  const xiaoxiangCard = cards.find(c => c.entry.key === 'xiaoxiang')!;
  assert.equal(xiaoxiangCard.canManage, false);
  assert.equal(xiaoxiangCard.canLogout, false);
  assert.equal(xiaoxiangCard.canSwitchAccount, false);

  const benlaiCard = cards.find(c => c.entry.key === 'benlai')!;
  assert.equal(benlaiCard.accountTitle, '暂未绑定平台账号');
  assert.equal(benlaiCard.canLogout, false);
});

test('un-saved platform with non-empty session_version hash shows as unlinked and hides logout button', () => {
  const cards = buildPlatformAuthCardViewModels({
    statuses: {
      fengshen: {
        state: 'signed_out',
        saved: false,
        session_version: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      },
    },
    isAdmin: true,
  });
  const fs = cards.find(c => c.entry.key === 'fengshen')!;
  assert.equal(fs.accountTitle, '暂未绑定平台账号');
  assert.equal(fs.canLogout, false);
  assert.equal(fs.canSwitchAccount, false);
});

test('filterPlatformAuthCards filters by scope, state, and search query', () => {
  const cards = buildPlatformAuthCardViewModels({
    statuses: {
      fengshen: { state: 'ready', saved: true, account_label: '13800138000' },
      lanorange: { state: 'waiting_login' },
    },
    isAdmin: true,
  });

  assert.equal(filterPlatformAuthCards(cards, { scope: 'personal' }).length, 3);
  assert.equal(filterPlatformAuthCards(cards, { scope: 'shared' }).length, 2);
  assert.equal(filterPlatformAuthCards(cards, { state: 'ready' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { state: 'attention' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { state: 'idle' }).length, 3);
  assert.equal(filterPlatformAuthCards(cards, { query: '13800138000' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { query: '钉钉' }).length, 1);
});

test('shellNav places workspace:platform-auth under 平台管理 for all users', () => {
  const state: ShellNavState = {
    workspaceView: 'platform-auth',
    taskKind: 'download',
    downloadPlatform: 'fengshen',
    payrollSubView: 'batches',
  };

  assert.equal(getActiveNavGroup(state), 'admin');
  assert.equal(getCurrentQuickTargetId(state), 'workspace:platform-auth');

  const breadcrumb = getBreadcrumbModel(state);
  assert.equal(breadcrumb.moduleLabel, '平台管理');
  assert.equal(breadcrumb.viewLabel, '授权管理');
  assert.equal(breadcrumb.siblings.length, 4);

  const memberCommands = buildShellCommands(state, { isAdmin: false });
  assert.ok(memberCommands.some(c => c.id === 'nav-platform-auth' && c.group === '平台管理' && c.label === '授权管理'));
  assert.ok(!memberCommands.some(c => c.id === 'nav-accounts'));
});
