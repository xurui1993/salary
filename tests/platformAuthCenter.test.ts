import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PLATFORM_AUTH_REGISTRY,
  buildPlatformAuthCardViewModels,
  filterPlatformAuthCards,
  shouldCancelAuthOnModalClose,
  summarizePlatformAuthOverview,
} from '../src/lib/platformAuthCenter';
import {
  buildShellCommands,
  getActiveNavGroup,
  getBreadcrumbModel,
  getCurrentQuickTargetId,
  type ShellNavState,
} from '../src/lib/shellNav';

test('PLATFORM_AUTH_REGISTRY defines 6 platforms with personal and shared scopes', () => {
  assert.equal(PLATFORM_AUTH_REGISTRY.length, 6);
  const personalKeys = PLATFORM_AUTH_REGISTRY.filter(p => p.scope === 'personal').map(p => p.key);
  const sharedKeys = PLATFORM_AUTH_REGISTRY.filter(p => p.scope === 'shared').map(p => p.key);
  assert.deepEqual(personalKeys, ['fengshen', 'lanorange', 'lanorange_mdr', 'baize']);
  assert.deepEqual(sharedKeys, ['xiaoxiang', 'benlai']);
});

test('buildPlatformAuthCardViewModels & summarizePlatformAuthOverview support multi-account pools and capability probes', () => {
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
        account_label: 'sy_enterprise_01',
        session_version: 'v1',
        active_account_id: 'acct_1',
        accounts: [
          {
            slot_id: 'acct_1',
            account_label: 'sy_enterprise_01',
            alias: '华南闪购主号',
            organization: '深圳商翼',
            account_type: 'shanggou',
            region_text: '华南大区',
            state: 'ready',
            is_active: true,
            credential_saved: true,
            session_version: 'v1',
          },
          {
            slot_id: 'acct_2',
            account_label: 'sy_enterprise_02',
            alias: '华东小象专户',
            organization: '上海商翼',
            account_type: 'xiaoxiang',
            region_text: '华东大区',
            state: 'ready',
            is_active: false,
            credential_saved: true,
            session_version: 'v2',
          },
        ],
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
  assert.equal(summary.totalCount, 6);
  assert.equal(summary.readyCount, 2);
  assert.equal(summary.personalCount, 4);
  assert.equal(summary.personalReadyCount, 2);
  assert.equal(summary.sharedCount, 2);
  assert.equal(summary.sharedReadyCount, 0);
  assert.equal(summary.attentionCount, 2); // lanorange (waiting_login) + xiaoxiang (saved/board error)
  assert.equal(summary.idleCount, 2); // lanorange_mdr + benlai
  // fengshen (1 fallback slot) + baize (2 pool slots) + xiaoxiang (1 fallback slot) = 4 logged accounts
  assert.equal(summary.totalLoggedAccountsCount, 4);

  const fengshenCard = cards.find(c => c.entry.key === 'fengshen')!;
  assert.equal(fengshenCard.isReady, true);
  assert.equal(fengshenCard.canSwitchAccount, true);
  assert.equal(fengshenCard.accountTitle, 'fs_user_01');
  assert.equal(fengshenCard.accountOrganization, '深圳分部');
  assert.equal(fengshenCard.accounts.length, 1);
  assert.equal(fengshenCard.accounts[0].isActive, true);
  assert.equal(fengshenCard.accounts[0].badgeText, '当前使用');
  assert.ok(fengshenCard.credentialStatusText.includes('加密凭据'));
  assert.ok(fengshenCard.probes.every(p => p.tone === 'ready'));

  const baizeCard = cards.find(c => c.entry.key === 'baize')!;
  assert.equal(baizeCard.accountSubtypeLabel, '闪购业务账户（华南大区）');
  assert.equal(baizeCard.accounts.length, 2);
  assert.equal(baizeCard.accounts[0].displayTitle, '华南闪购主号');
  assert.equal(baizeCard.accounts[0].isActive, true);
  assert.equal(baizeCard.accounts[0].badgeText, '当前使用');
  assert.ok(baizeCard.accounts[0].subtitle.includes('sy_enterprise_01'));
  assert.ok(baizeCard.accounts[0].subtitle.includes('闪购业务账户'));
  assert.equal(baizeCard.accounts[1].displayTitle, '华东小象专户');
  assert.equal(baizeCard.accounts[1].isActive, false);
  assert.equal(baizeCard.accounts[1].badgeText, '已驻留');

  // Non-admin without shared_auth_manage cannot manage shared platforms (xiaoxiang / benlai)
  const xiaoxiangCard = cards.find(c => c.entry.key === 'xiaoxiang')!;
  assert.equal(xiaoxiangCard.canManage, false);
  assert.equal(xiaoxiangCard.canLogout, false);
  assert.equal(xiaoxiangCard.canSwitchAccount, false);

  const benlaiCard = cards.find(c => c.entry.key === 'benlai')!;
  assert.equal(benlaiCard.accountTitle, '暂未绑定平台账号');
  assert.equal(benlaiCard.accounts.length, 0);
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
  assert.equal(fs.accounts.length, 0);
  assert.equal(fs.canLogout, false);
  assert.equal(fs.canSwitchAccount, false);
});

test('filterPlatformAuthCards filters by scope, state, and search query including standby account aliases', () => {
  const cards = buildPlatformAuthCardViewModels({
    statuses: {
      fengshen: { state: 'ready', saved: true, account_label: '13800138000' },
      lanorange: { state: 'waiting_login' },
      baize: {
        state: 'ready',
        saved: true,
        accounts: [
          { slot_id: 'a1', account_label: 'bz_01', alias: '闪购华南专户', is_active: true, state: 'ready' },
          { slot_id: 'a2', account_label: 'bz_02', alias: '小象华东备用号', is_active: false, state: 'ready' },
        ],
      },
    },
    isAdmin: true,
  });

  assert.equal(filterPlatformAuthCards(cards, { scope: 'personal' }).length, 4);
  assert.equal(filterPlatformAuthCards(cards, { scope: 'shared' }).length, 2);
  assert.equal(filterPlatformAuthCards(cards, { state: 'ready' }).length, 2);
  assert.equal(filterPlatformAuthCards(cards, { state: 'attention' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { state: 'idle' }).length, 3);
  assert.equal(filterPlatformAuthCards(cards, { query: '13800138000' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { query: '小象华东备用号' }).length, 1);
  assert.equal(filterPlatformAuthCards(cards, { query: '钉钉' }).length, 2);
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
  assert.equal(breadcrumb.siblings.length, 3);

  const memberCommands = buildShellCommands(state, { isAdmin: false });
  assert.ok(memberCommands.some(c => c.id === 'nav-platform-auth' && c.group === '平台管理' && c.label === '授权管理'));
  assert.ok(!memberCommands.some(c => c.id === 'nav-accounts'));
});

test('shouldCancelAuthOnModalClose cancels only active non-fengshen auth sessions', () => {
  assert.equal(shouldCancelAuthOnModalClose('lanorange', { state: 'waiting_login', busy: true }), true);
  assert.equal(shouldCancelAuthOnModalClose('baize', { state: 'starting', busy: true }), true);
  assert.equal(shouldCancelAuthOnModalClose('xiaoxiang', { state: 'waiting_login', busy: false }), true);
  assert.equal(shouldCancelAuthOnModalClose('benlai', { state: 'signed_out', busy: true }), true);
  assert.equal(shouldCancelAuthOnModalClose('lanorange', { state: 'waiting_login', busy: true, cancelling: true }), false);
  assert.equal(shouldCancelAuthOnModalClose('baize', { state: 'ready', busy: false }), false);
  assert.equal(shouldCancelAuthOnModalClose('baize', { state: 'signed_out', busy: false }), false);
  assert.equal(shouldCancelAuthOnModalClose('baize', { state: 'error', busy: false }), false);
  assert.equal(shouldCancelAuthOnModalClose('fengshen', { state: 'waiting_login', busy: true }), false);
  assert.equal(shouldCancelAuthOnModalClose('', { state: 'waiting_login', busy: true }), false);
  assert.equal(shouldCancelAuthOnModalClose('lanorange', undefined), false);
});

