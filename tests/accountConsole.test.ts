import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ALL_PERMISSION_KEYS,
  applyTemplateToDraft,
  countEnabledPermissions,
  createDraftFromUser,
  filterAuditEvents,
  filterManagedUsers,
  formatAuditAction,
  formatAuditDetail,
  formatAuditTime,
  getEnabledPermissionLabels,
  getRoleTemplateLabel,
  getStatusLabel,
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
import type { AuditEvent, RoleTemplateDef, WorkspaceUser } from '../src/lib/workspaceAuth';

const SAMPLE_TEMPLATES: Record<string, RoleTemplateDef> = {
  admin: {
    label: '系统管理员',
    description: '全部模块与账户治理权限',
    role: 'admin',
    permissions: {
      collection: true,
      reports: true,
      payroll: true,
      approval: true,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: true,
    },
  },
  payroll_specialist: {
    label: '薪资专员',
    description: '数据采集、业务报表与薪资核算',
    role: 'member',
    permissions: {
      collection: true,
      reports: true,
      payroll: true,
      approval: false,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: false,
    },
  },
  viewer: {
    label: '仅浏览导出',
    description: '只读查看任务记录',
    role: 'member',
    permissions: {
      collection: false,
      reports: false,
      payroll: false,
      approval: false,
      xiaoxiang_use: false,
      benlai_use: false,
      shared_auth_manage: false,
    },
  },
};

function makeUser(overrides: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    id: 'u-1',
    username: 'payroll_test',
    display_name: '林晓（薪资验收）',
    role: 'member',
    status: 'active',
    enabled: true,
    workspace_id: 'ws_payroll_test',
    effective_workspace: 'ws_payroll_test',
    inspecting: false,
    inspect_target: null,
    role_template: 'payroll_specialist',
    permissions: {
      collection: true,
      reports: true,
      payroll: true,
      approval: false,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: false,
    },
    note: '负责华东区核算',
    created_at: 1730000000,
    updated_at: 1730000000,
    ...overrides,
  };
}

test('createDraftFromUser, applyTemplateToDraft, and hasDraftChanges detect unsaved edits accurately', () => {
  const member = makeUser();
  const draft = createDraftFromUser(member);

  assert.equal(draft.role_template, 'payroll_specialist');
  assert.equal(hasDraftChanges(member, draft), false);
  assert.equal(countEnabledPermissions(draft.permissions), 5);

  const toggled = {
    ...draft,
    role_template: 'custom',
    permissions: { ...draft.permissions, approval: true },
  };
  assert.equal(hasDraftChanges(member, toggled), true);
  assert.equal(countEnabledPermissions(toggled.permissions), 6);

  const viewerDraft = applyTemplateToDraft('viewer', SAMPLE_TEMPLATES);
  assert.equal(viewerDraft.role_template, 'viewer');
  assert.equal(countEnabledPermissions(viewerDraft.permissions), 0);
  assert.equal(hasDraftChanges(member, viewerDraft), true);

  const adminUser = makeUser({ id: 'u-admin', username: 'admin', role: 'admin', role_template: 'admin' });
  const adminDraft = createDraftFromUser(adminUser);
  assert.equal(countEnabledPermissions(adminDraft.permissions), ALL_PERMISSION_KEYS.length);
  assert.equal(hasDraftChanges(adminUser, adminDraft), false);

  assert.deepEqual(getEnabledPermissionLabels(draft.permissions, false), [
    '数据采集',
    '业务报表',
    '薪资核算',
    '共享小象',
    '共享本来',
  ]);
  assert.equal(getEnabledPermissionLabels(undefined, true).length, ALL_PERMISSION_KEYS.length);
  assert.deepEqual(getEnabledPermissionLabels(viewerDraft.permissions, false), []);
});

test('filterManagedUsers excludes pending applicants and filters by status, role, and query', () => {
  const users: WorkspaceUser[] = [
    makeUser({ id: '1', username: 'admin', display_name: '系统管理员', role: 'admin', status: 'active', workspace_id: 'download_shared' }),
    makeUser({ id: '2', username: 'payroll_test', display_name: '林晓', role: 'member', status: 'active', note: '薪资核算' }),
    makeUser({ id: '3', username: 'disabled_user', display_name: '张敏', role: 'member', status: 'disabled', enabled: false, note: '离职停用' }),
    makeUser({ id: '4', username: 'pending_test', display_name: '王磊', role: 'member', status: 'pending', enabled: false, note: '待审批' }),
    makeUser({ id: '5', username: 'rejected_test', display_name: '赵阳', role: 'member', status: 'rejected', enabled: false, note: '已驳回' }),
  ];

  const allManaged = filterManagedUsers(users, { query: '', status: 'all', role: 'all' });
  assert.deepEqual(allManaged.map(u => u.id), ['1', '2', '3']);

  const rejectedOnly = filterManagedUsers(users, { query: '', status: 'rejected', role: 'all' });
  assert.deepEqual(rejectedOnly.map(u => u.id), ['5']);

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
  assert.equal(getRoleTemplateLabel('admin', 'custom', SAMPLE_TEMPLATES), '系统管理员');
  assert.equal(getRoleTemplateLabel('member', 'payroll_specialist', SAMPLE_TEMPLATES), '薪资专员');
  assert.equal(getRoleTemplateLabel('member', 'unknown_tpl', SAMPLE_TEMPLATES), '自定义权限');
  assert.equal(getStatusLabel('active'), '正常启用');
  assert.equal(getStatusLabel('pending'), '待审批');
  assert.equal(getStatusLabel('disabled'), '已停用');
  assert.equal(getStatusLabel('rejected'), '已驳回');
});

test('audit log formatters and filterAuditEvents map actions, details, timestamps, and categories', () => {
  assert.deepEqual(formatAuditAction('account.approve'), {
    label: '批准注册并开通空间',
    category: 'approval',
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
  ];

  const workspaceOnly = filterAuditEvents(events, { query: '', category: 'workspace' });
  assert.deepEqual(workspaceOnly.map(e => e.id), [2]);

  const byKeyword = filterAuditEvents(events, { query: '重置成员密码', category: 'all' });
  assert.deepEqual(byKeyword.map(e => e.id), [3]);

  const byTargetDisplayName = filterAuditEvents(events, {
    query: '林晓',
    category: 'all',
    users: [makeUser({ id: 'u-payroll', username: 'payroll_test', display_name: '林晓（薪资验收）', workspace_id: 'ws_payroll_test' })],
  });
  assert.deepEqual(byTargetDisplayName.map(e => e.id), [2, 3]);
});

test('buildShellCommands and shellNav helpers enforce admin & module permissions cleanly', () => {
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
  assert.equal(crumb.viewLabel, '权限管理');

  const adminCommands = buildShellCommands(baseState, {
    isAdmin: true,
    permissions: SAMPLE_TEMPLATES.admin.permissions,
  });
  assert.ok(adminCommands.some(c => c.id === 'nav-accounts' && c.active));
  assert.ok(adminCommands.some(c => c.id === 'nav-approval'));
  assert.ok(adminCommands.some(c => c.id === 'nav-xiaoxiang'));

  const payrollCommands = buildShellCommands(
    { ...baseState, workspaceView: 'create' },
    {
      isAdmin: false,
      permissions: SAMPLE_TEMPLATES.payroll_specialist.permissions,
    },
  );
  assert.equal(payrollCommands.some(c => c.id === 'nav-accounts'), false);
  assert.equal(payrollCommands.some(c => c.id === 'nav-approval'), false);
  assert.equal(payrollCommands.some(c => c.id === 'nav-payroll-batches'), true);
  assert.equal(payrollCommands.some(c => c.id === 'nav-xiaoxiang'), true);

  const viewerCommands = buildShellCommands(
    { ...baseState, workspaceView: 'history' },
    {
      isAdmin: false,
      permissions: SAMPLE_TEMPLATES.viewer.permissions,
    },
  );
  assert.equal(viewerCommands.some(c => c.id === 'nav-fengshen'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-xiaoxiang'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-payroll-batches'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-accounts'), false);
  assert.equal(viewerCommands.some(c => c.id === 'nav-history'), true);
  assert.equal(viewerCommands.some(c => c.id === 'nav-pickup'), true);
});
