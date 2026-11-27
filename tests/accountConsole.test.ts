import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ALL_PERMISSION_KEYS,
  buildDefaultNewMemberPermissions,
  buildFullPermissions,
  countEnabledPermissions,
  createDraftFromUser,
  filterAuditEvents,
  filterManagedUsers,
  formatAuditAction,
  formatAuditDetail,
  formatAuditTime,
  getEnabledPermissionLabels,
  getPermissionGroups,
  getStatusLabel,
  getVisiblePermissionKeys,
  getWorkspaceDisplayLabel,
  hasDraftChanges,
  resolveAuditTargetLabel,
} from '../src/lib/accountConsole';
import {
  buildShellCommands,
  getActiveNavGroup,
  getBreadcrumbModel,
  getCurrentQuickTargetId,
} from '../src/lib/shellNav';
import {
  DEFAULT_GLOBAL_WORKBENCH_CONFIG,
  normalizeGlobalWorkbenchConfig,
} from '../src/lib/workbenchConfig';
import type { AuditEvent, PermissionKey, WorkspaceUser } from '../src/lib/workspaceAuth';

function makePerms(overrides: Partial<Record<PermissionKey, boolean>> = {}): Record<PermissionKey, boolean> {
  return {
    ...buildFullPermissions(false),
    ...overrides,
  };
}

function makeUser(overrides: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    id: 'u-1',
    username: 'payroll_test',
    display_name: '林晓',
    role: 'member',
    status: 'active',
    enabled: true,
    workspace_id: 'ws_payroll_test',
    effective_workspace: 'ws_payroll_test',
    inspecting: false,
    inspect_target: null,
    permissions: makePerms({
      collection: true,
      reports: true,
      payroll: true,
      approval: false,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: false,
    }),
    note: '负责华东区核算',
    created_at: 1730000000,
    updated_at: 1730000000,
    ...overrides,
  };
}

test('ALL_PERMISSION_KEYS, permission drafts, and dynamic groups work without role templates', () => {
  assert.equal(ALL_PERMISSION_KEYS.length, 11);

  const member = makeUser();
  const draft = createDraftFromUser(member);
  assert.equal(draft.role, 'member');
  assert.equal(hasDraftChanges(member, draft), false);

  const visibleKeys = getVisiblePermissionKeys(DEFAULT_GLOBAL_WORKBENCH_CONFIG);
  // Default config: 4 modules + 2 shared platforms (xiaoxiang, benlai) + shared_auth_manage = 7
  assert.equal(visibleKeys.length, 7);
  assert.equal(countEnabledPermissions(draft.permissions, visibleKeys), 5);

  const toggled = {
    ...draft,
    permissions: { ...draft.permissions, approval: true },
  };
  assert.equal(hasDraftChanges(member, toggled), true);
  assert.equal(countEnabledPermissions(toggled.permissions, visibleKeys), 6);

  const adminUser = makeUser({ id: 'u-admin', username: 'admin', role: 'admin' });
  const adminDraft = createDraftFromUser(adminUser);
  assert.equal(adminDraft.role, 'admin');
  assert.equal(countEnabledPermissions(adminDraft.permissions), ALL_PERMISSION_KEYS.length);
  assert.equal(hasDraftChanges(adminUser, adminDraft), false);

  assert.deepEqual(getEnabledPermissionLabels(draft.permissions, false, DEFAULT_GLOBAL_WORKBENCH_CONFIG), [
    '数据采集',
    '业务报表',
    '薪资核算',
    '共享小象灯塔',
    '共享本来人力',
  ]);
  assert.equal(getEnabledPermissionLabels(undefined, true, DEFAULT_GLOBAL_WORKBENCH_CONFIG).length, 7);
  assert.deepEqual(getEnabledPermissionLabels(makePerms(), false, DEFAULT_GLOBAL_WORKBENCH_CONFIG), []);

  // Dynamically assigning fengshen to shared exposes fengshen_use in permission groups & visible keys
  const sharedFsCfg = normalizeGlobalWorkbenchConfig({
    channel_modes: { ...DEFAULT_GLOBAL_WORKBENCH_CONFIG.channel_modes, fengshen: 'shared' },
  });
  const sharedKeys = getVisiblePermissionKeys(sharedFsCfg);
  assert.ok(sharedKeys.includes('fengshen_use'));
  assert.equal(sharedKeys.length, 8);
  const groups = getPermissionGroups(sharedFsCfg);
  assert.ok(groups[1].items.some(item => item.key === 'fengshen_use' && item.label === '共享风神'));

  const newMemberDefaults = buildDefaultNewMemberPermissions(sharedFsCfg);
  assert.equal(newMemberDefaults.collection, true);
  assert.equal(newMemberDefaults.reports, true);
  assert.equal(newMemberDefaults.xiaoxiang_use, true);
  assert.equal(newMemberDefaults.benlai_use, true);
});

test('filterManagedUsers filters by active/disabled status, role, and query cleanly', () => {
  const users: WorkspaceUser[] = [
    makeUser({ id: '1', username: 'admin', display_name: '系统管理员', role: 'admin', status: 'active', workspace_id: 'download_shared' }),
    makeUser({ id: '2', username: 'payroll_test', display_name: '林晓', role: 'member', status: 'active', note: '薪资核算' }),
    makeUser({ id: '3', username: 'disabled_user', display_name: '张敏', role: 'member', status: 'disabled', enabled: false, note: '离职停用' }),
  ];

  const allManaged = filterManagedUsers(users, { query: '', status: 'all', role: 'all' });
  assert.deepEqual(allManaged.map(u => u.id), ['1', '2', '3']);

  const activeOnly = filterManagedUsers(users, { query: '', status: 'active', role: 'all' });
  assert.deepEqual(activeOnly.map(u => u.id), ['1', '2']);

  const disabledOnly = filterManagedUsers(users, { query: '', status: 'disabled', role: 'all' });
  assert.deepEqual(disabledOnly.map(u => u.id), ['3']);

  const adminOnly = filterManagedUsers(users, { query: '', status: 'all', role: 'admin' });
  assert.deepEqual(adminOnly.map(u => u.id), ['1']);

  const byQuery = filterManagedUsers(users, { query: '薪资', status: 'all', role: 'all' });
  assert.deepEqual(byQuery.map(u => u.id), ['2']);

  assert.equal(resolveAuditTargetLabel('', users), '—');
  assert.equal(resolveAuditTargetLabel('download_shared', users), '管理员主空间');
  assert.equal(resolveAuditTargetLabel('ws_payroll_test', users), '林晓');
  assert.equal(resolveAuditTargetLabel('ws_unknown', users), '独立工作空间');

  assert.equal(getWorkspaceDisplayLabel('download_shared'), '管理员主空间');
  assert.equal(getWorkspaceDisplayLabel('ws_payroll_test'), '独立工作空间');
  assert.equal(getStatusLabel('active'), '正常启用');
  assert.equal(getStatusLabel('disabled'), '已停用');
});

test('audit log formatters and filterAuditEvents support workbench.global_config and standard actions', () => {
  assert.deepEqual(formatAuditAction('workbench.global_config'), {
    label: '更新全局名称与通道配置',
    category: 'workspace',
  });
  assert.deepEqual(formatAuditAction('custom.unknown'), {
    label: 'custom.unknown',
    category: 'security',
  });
  assert.equal(formatAuditDetail('success'), '执行成功');
  assert.equal(formatAuditDetail(''), '—');
  assert.equal(formatAuditTime(0), '—');
  assert.match(formatAuditTime(1730000000), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

  const events: AuditEvent[] = [
    {
      id: 1,
      time: 1730000001,
      user_id: 'u-admin',
      username: 'admin',
      action: 'account.login',
      run_id: '',
      detail: 'success',
    },
    {
      id: 2,
      time: 1730000010,
      user_id: 'u-admin',
      username: 'admin',
      action: 'account.inspect',
      run_id: 'ws_payroll_test',
      detail: 'inspect',
    },
    {
      id: 3,
      time: 1730000020,
      user_id: 'u-admin',
      username: 'admin',
      action: 'account.password.reset',
      run_id: 'payroll_test',
      detail: 'success',
    },
    {
      id: 4,
      time: 1730000030,
      user_id: 'u-admin',
      username: 'admin',
      action: 'workbench.global_config',
      run_id: 'download_shared',
      detail: 'success',
    },
  ];

  const workspaceOnly = filterAuditEvents(events, { query: '', category: 'workspace' });
  assert.deepEqual(workspaceOnly.map(e => e.id), [2, 4]);

  const byKeyword = filterAuditEvents(events, { query: '重置成员密码', category: 'all' });
  assert.deepEqual(byKeyword.map(e => e.id), [3]);

  const byTargetDisplayName = filterAuditEvents(events, {
    query: '林晓',
    category: 'all',
    users: [makeUser({ id: 'u-payroll', username: 'payroll_test', display_name: '林晓', workspace_id: 'ws_payroll_test' })],
  });
  assert.deepEqual(byTargetDisplayName.map(e => e.id), [2, 3]);
});

test('buildShellCommands and shellNav helpers enforce admin, module pause, and shared platform permissions', () => {
  const baseState = {
    workspaceView: 'accounts' as const,
    taskKind: 'download' as const,
    downloadPlatform: 'fengshen' as const,
    payrollSubView: 'batches' as const,
  };

  assert.equal(getActiveNavGroup(baseState), 'admin');
  assert.equal(getCurrentQuickTargetId(baseState), 'workspace:accounts');
  const crumb = getBreadcrumbModel(baseState);
  assert.equal(crumb.moduleLabel, '平台管理');
  assert.equal(crumb.viewLabel, '用户权限分配');

  const adminCommands = buildShellCommands(baseState, {
    isAdmin: true,
    permissions: buildFullPermissions(true),
  });
  assert.ok(adminCommands.some(c => c.id === 'nav-accounts' && c.active));
  assert.ok(adminCommands.some(c => c.id === 'nav-global-config'));
  assert.ok(adminCommands.some(c => c.id === 'nav-approval'));
  assert.ok(adminCommands.some(c => c.id === 'nav-xiaoxiang'));

  const memberCommands = buildShellCommands(
    { ...baseState, workspaceView: 'create' },
    {
      isAdmin: false,
      permissions: makePerms({
        collection: true,
        reports: true,
        payroll: true,
        approval: false,
        xiaoxiang_use: true,
        benlai_use: true,
      }),
    },
  );
  assert.equal(memberCommands.some(c => c.id === 'nav-accounts'), false);
  assert.equal(memberCommands.some(c => c.id === 'nav-global-config'), false);
  assert.equal(memberCommands.some(c => c.id === 'nav-approval'), false);
  assert.equal(memberCommands.some(c => c.id === 'nav-payroll-batches'), true);
  assert.equal(memberCommands.some(c => c.id === 'nav-xiaoxiang'), true);

  // Global module pause hides payroll from non-admin even if user has payroll=true
  const pausedPayrollCfg = normalizeGlobalWorkbenchConfig({
    module_permissions: { ...DEFAULT_GLOBAL_WORKBENCH_CONFIG.module_permissions, payroll: false },
  });
  const pausedMemberCommands = buildShellCommands(
    { ...baseState, workspaceView: 'create' },
    {
      isAdmin: false,
      permissions: buildFullPermissions(true),
      globalConfig: pausedPayrollCfg,
    },
  );
  assert.equal(pausedMemberCommands.some(c => c.id === 'nav-payroll-batches'), false);
  assert.equal(pausedMemberCommands.some(c => c.id === 'nav-approval'), true);

  // Shared fengshen with fengshen_use=false hides nav-fengshen from member
  const sharedFsDeniedCfg = normalizeGlobalWorkbenchConfig({
    channel_modes: { ...DEFAULT_GLOBAL_WORKBENCH_CONFIG.channel_modes, fengshen: 'shared' },
  });
  const deniedMemberCommands = buildShellCommands(
    { ...baseState, workspaceView: 'create' },
    {
      isAdmin: false,
      permissions: makePerms({ collection: true, fengshen_use: false }),
      globalConfig: sharedFsDeniedCfg,
    },
  );
  assert.equal(deniedMemberCommands.some(c => c.id === 'nav-fengshen'), false);
  assert.equal(deniedMemberCommands.some(c => c.id === 'nav-lanorange'), true);

  const viewerCommands = buildShellCommands(
    { ...baseState, workspaceView: 'history' },
    {
      isAdmin: false,
      permissions: makePerms(),
    },
  );
  assert.equal(viewerCommands.some(c => c.id === 'nav-fengshen'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-xiaoxiang'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-payroll-batches'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-accounts'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-history'), true);
  assert.equal(viewerCommands.some(c => c.id === 'nav-pickup'), true);
});
