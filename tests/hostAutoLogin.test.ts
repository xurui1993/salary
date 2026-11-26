import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AuthPortal } from '../src/components/AuthPortal';
import { HeaderAccountBar } from '../src/components/HeaderAccountBar';
import type { WorkspaceSessionState, WorkspaceUser } from '../src/lib/workspaceAuth';

function makeSession(overrides: Partial<WorkspaceSessionState> = {}): WorkspaceSessionState {
  return {
    initialized: true,
    authenticated: false,
    host_machine: false,
    local_loopback: false,
    host_auto_login: false,
    can_switch_to_host: false,
    bootstrap_allowed: false,
    user: null,
    role_templates: {},
    permission_keys: [],
    permission_labels: {} as any,
    workspaces: [],
    pending_count: 0,
    ...overrides,
  };
}

function makeUser(overrides: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    id: 'host-id',
    username: 'host_admin',
    display_name: '主机管理员',
    role: 'admin',
    role_template: 'admin',
    status: 'active',
    enabled: true,
    has_password: false,
    workspace_id: 'download_shared',
    effective_workspace: 'download_shared',
    inspecting: false,
    inspect_target: null,
    permissions: {
      collection: true,
      reports: true,
      payroll: true,
      approval: true,
      xiaoxiang_use: true,
      benlai_use: true,
      shared_auth_manage: true,
    },
    note: '',
    created_at: 0,
    updated_at: 0,
    ...overrides,
  };
}

test('AuthPortal always renders direct login form and never renders host admin bootstrap wizard', () => {
  const html = renderToStaticMarkup(
    React.createElement(AuthPortal, {
      session: makeSession({ initialized: false, bootstrap_allowed: true }),
      onAuthenticated: () => {},
    }),
  );

  assert.doesNotMatch(html, /初始化主机管理员/);
  assert.doesNotMatch(html, /创建并进入/);
  assert.doesNotMatch(html, /等待管理员初始化/);
  assert.match(html, /账号/);
  assert.match(html, /密码/);
  assert.match(html, /登录/);
  assert.match(html, /账号由系统管理员统一创建开通/);
});

test('HeaderAccountBar displays host auto-login trigger and switched indicator correctly', () => {
  const hostHtml = renderToStaticMarkup(
    React.createElement(HeaderAccountBar, {
      user: makeUser(),
      workspaces: [],
      hostMachine: true,
      hostAutoLogin: true,
      canSwitchToHost: false,
      onSwitchWorkspace: async () => {},
      onSwitchAccount: async () => {},
      onSwitchToHost: async () => {},
      onLogout: async () => {},
      onToast: () => {},
    }),
  );
  assert.match(hostHtml, /主机管理员/);
  assert.match(hostHtml, /本机免登超级管理员/);
  assert.doesNotMatch(hostHtml, /已切换/);

  const switchedHtml = renderToStaticMarkup(
    React.createElement(HeaderAccountBar, {
      user: makeUser({
        id: 'member-1',
        username: 'alice',
        display_name: '爱丽丝',
        role: 'member',
        has_password: true,
        workspace_id: 'ws_alice',
        effective_workspace: 'ws_alice',
      }),
      workspaces: [],
      hostMachine: true,
      hostAutoLogin: false,
      canSwitchToHost: true,
      onSwitchWorkspace: async () => {},
      onSwitchAccount: async () => {},
      onSwitchToHost: async () => {},
      onLogout: async () => {},
      onToast: () => {},
    }),
  );
  assert.match(switchedHtml, /爱丽丝/);
  assert.match(switchedHtml, /已切换/);
});
