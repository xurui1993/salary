import type { GlobalWorkbenchConfig } from './workbenchConfig';

export type PermissionKey =
  | 'collection'
  | 'reports'
  | 'payroll'
  | 'approval'
  | 'fengshen_use'
  | 'lanorange_use'
  | 'lanorange_mdr_use'
  | 'baize_use'
  | 'xiaoxiang_use'
  | 'benlai_use'
  | 'shared_auth_manage';

export interface InspectTargetInfo {
  id: string;
  username: string;
  display_name: string;
  workspace_id: string;
}

export interface WorkspaceUser {
  id: string;
  username: string;
  display_name: string;
  role: 'admin' | 'member';
  status: 'active' | 'disabled';
  enabled: boolean;
  has_password?: boolean;
  workspace_id: string;
  effective_workspace: string;
  inspecting: boolean;
  inspect_target: InspectTargetInfo | null;
  permissions: Record<PermissionKey, boolean>;
  note: string;
  created_at: number;
  updated_at: number;
}

export interface WorkspaceDirectoryEntry {
  workspace_id: string;
  user_id: string;
  username: string;
  display_name: string;
  role: 'admin' | 'member';
  status: string;
  is_primary: boolean;
}

export interface WorkspaceSessionState {
  initialized: boolean;
  authenticated: boolean;
  host_machine: boolean;
  local_loopback: boolean;
  host_auto_login?: boolean;
  can_switch_to_host?: boolean;
  bootstrap_allowed: boolean;
  user: WorkspaceUser | null;
  permission_keys: PermissionKey[];
  permission_labels: Record<PermissionKey, string>;
  workspaces: WorkspaceDirectoryEntry[];
  global_config?: GlobalWorkbenchConfig;
}

export function hasModulePermission(
  user: WorkspaceUser | null | undefined,
  key: PermissionKey,
): boolean {
  if (!user) return false;
  if (user.role === 'admin') return true;
  return Boolean(user.permissions?.[key]);
}

export function syncStoredWorkspaceId(wid: string | undefined | null): void {
  const next = wid || 'download_shared';
  try {
    localStorage.setItem('app_workspace_id', next);
  } catch {
    // ignore storage failures
  }
}

async function authJson<T>(url: string, method = 'GET', body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(url, init);
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail =
      (typeof data?.detail === 'string' && data.detail) ||
      (typeof data?.error === 'string' && data.error) ||
      (typeof data?.message === 'string' && data.message) ||
      `请求失败 (${res.status})`;
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return data as T;
}

export async function fetchWorkspaceSession(): Promise<WorkspaceSessionState> {
  const state = await authJson<WorkspaceSessionState>('/api/auth/session');
  if (state.authenticated && state.user) {
    syncStoredWorkspaceId(state.user.effective_workspace);
  }
  return state;
}

export async function switchToHostAdmin(): Promise<WorkspaceSessionState> {
  const state = await authJson<WorkspaceSessionState>('/api/auth/switch-host', 'POST', {});
  if (state.user) syncStoredWorkspaceId(state.user.effective_workspace);
  return state;
}

export async function loginWorkspaceAccount(payload: {
  username: string;
  password: string;
}): Promise<WorkspaceSessionState> {
  const state = await authJson<WorkspaceSessionState>('/api/auth/login', 'POST', payload);
  if (state.user) syncStoredWorkspaceId(state.user.effective_workspace);
  return state;
}

export async function logoutWorkspaceAccount(): Promise<void> {
  await authJson('/api/auth/logout', 'POST', {});
}

export async function changeOwnPassword(payload: {
  current_password: string;
  new_password: string;
}): Promise<{ ok: boolean; message: string }> {
  return authJson('/api/auth/password', 'POST', payload);
}

export async function switchInspectWorkspace(
  workspace_id: string,
): Promise<WorkspaceSessionState> {
  const state = await authJson<WorkspaceSessionState>('/api/auth/inspect', 'POST', {
    workspace_id,
  });
  if (state.user) syncStoredWorkspaceId(state.user.effective_workspace);
  return state;
}

export interface AdminAccountsResponse {
  users: WorkspaceUser[];
  workspaces: WorkspaceDirectoryEntry[];
  permission_keys: PermissionKey[];
  permission_labels: Record<PermissionKey, string>;
  global_config?: GlobalWorkbenchConfig;
}

export async function fetchAdminAccounts(): Promise<AdminAccountsResponse> {
  return authJson('/api/admin/accounts');
}

export async function adminCreateAccount(payload: {
  username: string;
  display_name: string;
  password: string;
  role?: 'admin' | 'member';
  permissions: Record<string, boolean>;
  note?: string;
}): Promise<{ ok: boolean; user: WorkspaceUser; users: WorkspaceUser[]; workspaces: WorkspaceDirectoryEntry[] }> {
  return authJson('/api/admin/accounts', 'POST', payload);
}

export async function adminUpdateAccount(
  userId: string,
  payload: {
    display_name?: string;
    role?: 'admin' | 'member';
    permissions?: Record<string, boolean>;
    enabled?: boolean;
    note?: string;
  },
): Promise<{
  ok: boolean;
  user: WorkspaceUser;
  users: WorkspaceUser[];
  workspaces: WorkspaceDirectoryEntry[];
}> {
  return authJson(`/api/admin/accounts/${encodeURIComponent(userId)}`, 'PUT', payload);
}

export async function adminResetPassword(
  userId: string,
  new_password: string,
): Promise<{ ok: boolean; message: string }> {
  return authJson(`/api/admin/accounts/${encodeURIComponent(userId)}/reset-password`, 'POST', {
    new_password,
  });
}

export async function adminSyncDefaultConfig(
  userId: string,
): Promise<{ ok: boolean; message: string }> {
  return authJson(
    `/api/admin/accounts/${encodeURIComponent(userId)}/sync-default-config`,
    'POST',
    {},
  );
}

export async function fetchGlobalWorkbenchConfig(): Promise<{ ok: boolean; config: GlobalWorkbenchConfig }> {
  return authJson('/api/workbench/global-config');
}

export async function updateGlobalWorkbenchConfig(
  patch: Partial<GlobalWorkbenchConfig>,
): Promise<{ ok: boolean; config: GlobalWorkbenchConfig }> {
  return authJson('/api/admin/workbench/global-config', 'PUT', patch);
}

export async function resetGlobalWorkbenchConfig(
  section: 'all' | 'channels' | 'module_names' | 'datasets' | 'naming' = 'all',
): Promise<{ ok: boolean; config: GlobalWorkbenchConfig }> {
  return authJson('/api/admin/workbench/global-config/reset', 'POST', { section });
}

export interface AuditEvent {
  id: number;
  time: number;
  user_id: string;
  username: string;
  action: string;
  run_id: string;
  detail: string;
}

export async function fetchAdminAuditLogs(): Promise<{ events: AuditEvent[] }> {
  return authJson('/api/admin/accounts/audit');
}
