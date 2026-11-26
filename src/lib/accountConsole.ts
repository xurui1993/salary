import type {
  AuditEvent,
  PermissionKey,
  RoleTemplateDef,
  WorkspaceUser,
} from './workspaceAuth';

export interface PermissionMetaItem {
  key: PermissionKey;
  label: string;
  description: string;
}

export interface PermissionGroupDef {
  id: 'business' | 'shared';
  title: string;
  subtitle: string;
  items: PermissionMetaItem[];
}

export const PERMISSION_GROUPS: PermissionGroupDef[] = [
  {
    id: 'business',
    title: '业务模块',
    subtitle: '控制左侧业务导航入口及对应后台接口操作权',
    items: [
      { key: 'collection', label: '数据采集', description: '风神、蓝橙、发薪等原始资料采集' },
      { key: 'reports', label: '业务报表', description: '支付绑定、异常跟进、异常名单与问题单' },
      { key: 'payroll', label: '薪资核算', description: '兼职核算队列、扣款配置与模板中心' },
      { key: 'approval', label: '价格审批', description: '蓝橙待办审批列表与每日价格导出' },
    ],
  },
  {
    id: 'shared',
    title: '共享通道',
    subtitle: '小象灯塔与本来人力采用全局共享登录态，按需分配使用与维护权',
    items: [
      { key: 'xiaoxiang_use', label: '共享小象', description: '复用主机小象灯塔连接执行数据采集' },
      { key: 'benlai_use', label: '共享本来', description: '复用主机本来人力连接拉取灵工档案' },
      { key: 'shared_auth_manage', label: '维护共享连接', description: '允许扫码登录或断开小象灯塔与本来人力' },
    ],
  },
];

export const ALL_PERMISSION_KEYS: PermissionKey[] = PERMISSION_GROUPS.flatMap(g =>
  g.items.map(i => i.key),
);

export interface UserPermissionDraft {
  role_template: string;
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

export function createDraftFromUser(user: WorkspaceUser): UserPermissionDraft {
  const perms = buildFullPermissions(false);
  for (const key of ALL_PERMISSION_KEYS) {
    perms[key] = user.role === 'admin' ? true : Boolean(user.permissions?.[key]);
  }
  return {
    role_template: user.role === 'admin' ? 'admin' : user.role_template || 'custom',
    permissions: perms,
  };
}

export function applyTemplateToDraft(
  templateKey: string,
  templates: Record<string, RoleTemplateDef>,
): UserPermissionDraft {
  const tpl = templates[templateKey];
  const perms = buildFullPermissions(templateKey === 'admin');
  if (tpl?.permissions) {
    for (const key of ALL_PERMISSION_KEYS) {
      perms[key] = templateKey === 'admin' ? true : Boolean(tpl.permissions[key]);
    }
  }
  return {
    role_template: templateKey,
    permissions: perms,
  };
}

export function hasDraftChanges(
  user: WorkspaceUser,
  draft: UserPermissionDraft | undefined,
): boolean {
  if (!draft) return false;
  const savedTemplate = user.role === 'admin' ? 'admin' : user.role_template || 'custom';
  if (draft.role_template !== savedTemplate) return true;
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

export function getEnabledPermissionLabels(
  permissions: Record<string, boolean> | undefined,
  isAdmin = false,
): string[] {
  const allItems = PERMISSION_GROUPS.flatMap(g => g.items);
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

export function getRoleTemplateLabel(
  role: 'admin' | 'member',
  roleTemplate: string,
  templates: Record<string, RoleTemplateDef>,
): string {
  if (role === 'admin') return '系统管理员';
  return templates[roleTemplate]?.label || '自定义权限';
}

export function getStatusLabel(status: WorkspaceUser['status']): string {
  if (status === 'active') return '正常启用';
  if (status === 'pending') return '待审批';
  if (status === 'disabled') return '已停用';
  return '已驳回';
}

export interface ManagedUserFilterOptions {
  query: string;
  status: 'all' | 'active' | 'disabled' | 'rejected';
  role: 'all' | 'admin' | 'member';
}

export function filterManagedUsers(
  users: WorkspaceUser[],
  options: ManagedUserFilterOptions,
): WorkspaceUser[] {
  const q = options.query.trim().toLowerCase();
  return users.filter(user => {
    if (user.status === 'pending') return false;
    if (options.status === 'all') {
      if (user.status === 'rejected') return false;
    } else if (user.status !== options.status) {
      return false;
    }
    if (options.role !== 'all' && user.role !== options.role) return false;
    if (!q) return true;
    const haystack = `${user.display_name} ${user.username} ${user.note || ''} ${user.workspace_id}`.toLowerCase();
    return haystack.includes(q);
  });
}

export type AuditCategory = 'all' | 'auth' | 'approval' | 'permission' | 'workspace' | 'security';

export interface AuditActionMeta {
  label: string;
  category: Exclude<AuditCategory, 'all'>;
}

const AUDIT_ACTION_MAP: Record<string, AuditActionMeta> = {
  'account.bootstrap': { label: '初始化主机管理员', category: 'auth' },
  'account.login': { label: '成员登录工作空间', category: 'auth' },
  'account.logout': { label: '成员退出登录', category: 'auth' },
  'account.register': { label: '提交注册申请', category: 'approval' },
  'account.approve': { label: '批准注册并开通空间', category: 'approval' },
  'account.reject': { label: '驳回注册申请', category: 'approval' },
  'account.create': { label: '管理员新建成员', category: 'permission' },
  'account.update': { label: '调整成员权限或状态', category: 'permission' },
  'account.password.change': { label: '修改个人密码', category: 'security' },
  'account.password.reset': { label: '管理员重置成员密码', category: 'security' },
  'account.inspect': { label: '切换跨空间巡检', category: 'workspace' },
  'account.config.sync': { label: '同步标准默认扣款表', category: 'workspace' },
};

export function formatAuditAction(action: string): AuditActionMeta {
  return AUDIT_ACTION_MAP[action] || { label: action || '系统操作', category: 'security' };
}

const AUDIT_DETAIL_MAP: Record<string, string> = {
  success: '执行成功',
  failed: '执行失败',
  enabled: '启用状态',
  disabled: '停用状态',
  admin: '管理员角色',
  member: '普通成员',
  approved: '已批准开通',
  rejected: '已驳回申请',
  registered: '等待审批',
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
