import type { AuditEvent, PermissionKey, WorkspaceUser } from './workspaceAuth';
import {
  DEFAULT_GLOBAL_WORKBENCH_CONFIG,
  getDynamicPermissionGroups,
  getGlobalWorkbenchConfig,
  type GlobalWorkbenchConfig,
} from './workbenchConfig';

export interface PermissionMetaItem {
  key: PermissionKey;
  label: string;
  description: string;
  globallyPaused?: boolean;
}

export interface PermissionGroupDef {
  id: 'business' | 'shared';
  title: string;
  subtitle: string;
  items: PermissionMetaItem[];
}

export const ALL_PERMISSION_KEYS: PermissionKey[] = [
  'collection',
  'reports',
  'payroll',
  'approval',
  'fengshen_use',
  'lanorange_use',
  'lanorange_mdr_use',
  'baize_use',
  'xiaoxiang_use',
  'benlai_use',
  'shared_auth_manage',
];

export function getPermissionGroups(
  cfg: GlobalWorkbenchConfig = getGlobalWorkbenchConfig(),
): PermissionGroupDef[] {
  const dynamic = getDynamicPermissionGroups(cfg);
  return dynamic.map(group => {
    if (group.id === 'modules') {
      return {
        id: 'business',
        title: group.title,
        subtitle: '控制左侧业务导航入口及对应后台接口操作权',
        items: group.items.map(item => ({
          key: item.key as PermissionKey,
          label: item.label,
          description: item.desc,
          globallyPaused: item.globallyPaused,
        })),
      };
    }
    return {
      id: 'shared',
      title: group.title,
      subtitle: '主机设为共享模式的平台将集中出现在此，按需分配同事使用与维护权',
      items: group.items.map(item => ({
        key: item.key as PermissionKey,
        label: item.label,
        description: item.desc,
      })),
    };
  });
}

export const PERMISSION_GROUPS: PermissionGroupDef[] = getPermissionGroups(
  DEFAULT_GLOBAL_WORKBENCH_CONFIG,
);

export interface UserPermissionDraft {
  role: 'admin' | 'member';
  permissions: Record<PermissionKey, boolean>;
}

export function buildFullPermissions(enabled: boolean): Record<PermissionKey, boolean> {
  return ALL_PERMISSION_KEYS.reduce(
    (acc, key) => {
      acc[key] = enabled;
      return acc;
    },
    {} as Record<PermissionKey, boolean>,
  );
}

export function buildDefaultNewMemberPermissions(
  cfg: GlobalWorkbenchConfig = getGlobalWorkbenchConfig(),
): Record<PermissionKey, boolean> {
  const perms = buildFullPermissions(false);
  perms.collection = true;
  perms.reports = true;
  for (const [plat, mode] of Object.entries(cfg.channel_modes)) {
    if (mode === 'shared') {
      const useKey = `${plat}_use` as PermissionKey;
      if (useKey in perms) {
        perms[useKey] = plat === 'xiaoxiang' || plat === 'benlai';
      }
    }
  }
  return perms;
}

export function createDraftFromUser(user: WorkspaceUser): UserPermissionDraft {
  const perms = buildFullPermissions(false);
  for (const key of ALL_PERMISSION_KEYS) {
    perms[key] = user.role === 'admin' ? true : Boolean(user.permissions?.[key]);
  }
  return {
    role: user.role === 'admin' ? 'admin' : 'member',
    permissions: perms,
  };
}

export function hasDraftChanges(
  user: WorkspaceUser,
  draft: UserPermissionDraft | undefined,
): boolean {
  if (!draft) return false;
  if (draft.role !== user.role) return true;
  for (const key of ALL_PERMISSION_KEYS) {
    const savedVal = user.role === 'admin' ? true : Boolean(user.permissions?.[key]);
    if (Boolean(draft.permissions?.[key]) !== savedVal) {
      return true;
    }
  }
  return false;
}

export function countEnabledPermissions(
  permissions: Record<string, boolean> | undefined,
  keys: PermissionKey[] = ALL_PERMISSION_KEYS,
): number {
  if (!permissions) return 0;
  return keys.reduce((total, key) => total + (permissions[key] ? 1 : 0), 0);
}

export function getVisiblePermissionKeys(
  cfg: GlobalWorkbenchConfig = getGlobalWorkbenchConfig(),
): PermissionKey[] {
  return getPermissionGroups(cfg).flatMap(g => g.items.map(i => i.key));
}

export function getEnabledPermissionLabels(
  permissions: Record<string, boolean> | undefined,
  isAdmin = false,
  cfg: GlobalWorkbenchConfig = getGlobalWorkbenchConfig(),
): string[] {
  const allItems = getPermissionGroups(cfg).flatMap(g => g.items);
  if (isAdmin) {
    return allItems.map(item => item.label);
  }
  if (!permissions) return [];
  return allItems.filter(item => Boolean(permissions[item.key])).map(item => item.label);
}

export function getWorkspaceDisplayLabel(workspaceId: string): string {
  return workspaceId === 'download_shared' ? '管理员主空间' : '独立工作空间';
}

export function resolveAuditTargetLabel(
  runId: string,
  users: Pick<WorkspaceUser, 'id' | 'username' | 'display_name' | 'workspace_id'>[],
): string {
  const clean = (runId || '').trim();
  if (!clean) return '—';
  if (clean === 'download_shared') return '管理员主空间';
  const matched = users.find(
    u => u.workspace_id === clean || u.username === clean || u.id === clean,
  );
  if (matched) {
    return matched.display_name || matched.username;
  }
  return getWorkspaceDisplayLabel(clean);
}

export function getStatusLabel(status: WorkspaceUser['status']): string {
  if (status === 'active') return '正常启用';
  return '已停用';
}

export interface ManagedUserFilterOptions {
  query: string;
  status: 'all' | 'active' | 'disabled';
  role: 'all' | 'admin' | 'member';
}

export function filterManagedUsers(
  users: WorkspaceUser[],
  options: ManagedUserFilterOptions,
): WorkspaceUser[] {
  const q = options.query.trim().toLowerCase();
  return users.filter(user => {
    if (options.status !== 'all' && user.status !== options.status) {
      return false;
    }
    if (options.role !== 'all' && user.role !== options.role) return false;
    if (!q) return true;
    const haystack = `${user.display_name} ${user.username} ${user.note || ''} ${user.workspace_id}`.toLowerCase();
    return haystack.includes(q);
  });
}

export type AuditCategory = 'all' | 'auth' | 'permission' | 'workspace' | 'security';

export interface AuditActionMeta {
  label: string;
  category: Exclude<AuditCategory, 'all'>;
}

const AUDIT_ACTION_MAP: Record<string, AuditActionMeta> = {
  'account.bootstrap': { label: '初始化主机管理员', category: 'auth' },
  'account.switch_host': { label: '一键切回主机管理员', category: 'auth' },
  'account.login': { label: '成员登录工作空间', category: 'auth' },
  'account.logout': { label: '成员退出登录', category: 'auth' },
  'account.create': { label: '管理员新建成员', category: 'permission' },
  'account.update': { label: '调整成员权限或状态', category: 'permission' },
  'account.password.change': { label: '修改个人密码', category: 'security' },
  'account.password.reset': { label: '管理员重置成员密码', category: 'security' },
  'account.inspect': { label: '切换跨空间巡检', category: 'workspace' },
  'account.config.sync': { label: '同步标准默认扣款表', category: 'workspace' },
  'workbench.global_config': { label: '更新全局名称与通道配置', category: 'workspace' },
};

export function formatAuditAction(action: string): AuditActionMeta {
  return AUDIT_ACTION_MAP[action] || { label: action || '系统操作', category: 'security' };
}

const AUDIT_DETAIL_MAP: Record<string, string> = {
  success: '执行成功',
  failed: '执行失败',
  enabled: '启用状态',
  disabled: '停用状态',
  admin: '管理员',
  member: '团队成员',
  inspect: '巡检进入',
  cancelled: '已取消',
  partial: '部分完成',
};

export function formatAuditDetail(detail: string): string {
  if (!detail) return '—';
  return AUDIT_DETAIL_MAP[detail] || detail;
}

export function formatAuditTime(epochSeconds: number): string {
  if (!epochSeconds || !Number.isFinite(epochSeconds)) return '—';
  const d = new Date(epochSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function filterAuditEvents(
  events: AuditEvent[],
  options: {
    query: string;
    category: AuditCategory;
    users?: Pick<WorkspaceUser, 'id' | 'username' | 'display_name' | 'workspace_id'>[];
  },
): AuditEvent[] {
  const q = options.query.trim().toLowerCase();
  const users = options.users || [];
  return events.filter(evt => {
    const meta = formatAuditAction(evt.action);
    if (options.category !== 'all' && meta.category !== options.category) return false;
    if (!q) return true;
    const resolvedTarget = evt.run_id && users.length ? resolveAuditTargetLabel(evt.run_id, users) : '';
    const haystack = `${evt.username} ${meta.label} ${evt.action} ${evt.run_id || ''} ${resolvedTarget} ${formatAuditDetail(evt.detail)}`.toLowerCase();
    return haystack.includes(q);
  });
}
