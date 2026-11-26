import { getPlatformCardBadge, type PlatformDotTone } from './workbench';
import { systemLabel, type ConnectionChipKey } from './platformCatalog';

export type PlatformAuthScope = 'personal' | 'shared';
export type PlatformScopeFilter = 'all' | PlatformAuthScope;
export type PlatformStateFilter = 'all' | 'ready' | 'attention' | 'idle';

export interface PlatformCapabilityProbeDef {
  id: string;
  label: string;
  description: string;
}

export interface PlatformRegistryEntry {
  key: ConnectionChipKey;
  displayName: string;
  shortName: string;
  businessLine: string;
  scope: PlatformAuthScope;
  scopeLabel: string;
  authMethodLabel: string;
  accent: 'sky' | 'amber' | 'emerald' | 'violet' | 'indigo';
  usedByModules: string[];
  description: string;
  probeDefs: PlatformCapabilityProbeDef[];
}

export interface PlatformCapabilityProbeStatus {
  id: string;
  label: string;
  description: string;
  tone: 'ready' | 'warn' | 'idle';
  statusText: string;
}

export interface PlatformRawAuthStatus {
  state?: string;
  saved?: boolean;
  busy?: boolean;
  offline?: boolean;
  cancelling?: boolean;
  release_state?: string;
  session_id?: string;
  session_version?: string;
  account_label?: string;
  organization?: string;
  can_manage?: boolean;
  credential_saved?: boolean;
  credential_prompt?: boolean;
  credential_account?: string;
  message?: string;
  capabilities?: Record<string, { verified?: boolean; message?: string } | undefined>;
  stages?: Record<string, string | undefined>;
}

export interface BaizeAccountMeta {
  account_type?: 'shanggou' | 'xiaoxiang' | string;
  region_text?: string;
  account_label?: string;
}

export interface PlatformAuthCardViewModel {
  entry: PlatformRegistryEntry;
  raw: PlatformRawAuthStatus;
  badge: { label: string; tone: PlatformDotTone };
  isReady: boolean;
  isBusy: boolean;
  needsAttention: boolean;
  isIdle: boolean;
  canManage: boolean;
  canLogout: boolean;
  canSwitchAccount: boolean;
  canDeepCheck: boolean;
  accountTitle: string;
  accountOrganization: string;
  accountSubtypeLabel: string;
  credentialStatusText: string;
  capabilitySummary: string;
  probes: PlatformCapabilityProbeStatus[];
  errorText: string;
}

export interface PlatformAuthOverviewSummary {
  totalCount: number;
  readyCount: number;
  personalCount: number;
  personalReadyCount: number;
  sharedCount: number;
  sharedReadyCount: number;
  attentionCount: number;
  idleCount: number;
}

export const PLATFORM_AUTH_REGISTRY: PlatformRegistryEntry[] = [
  {
    key: 'fengshen',
    displayName: systemLabel('fengshen'),
    shortName: '风神',
    businessLine: '淘宝闪购自有系统',
    scope: 'personal',
    scopeLabel: '个人独立通道',
    authMethodLabel: '独立窗口 / 账号密码直连',
    accent: 'sky',
    usedByModules: ['风神数据采集', '支付绑定', '异常跟进', '问题单', '兼职薪资核算'],
    description: '配送费、违规扣款、月度 UB 账单、骑手收薪绑定与考勤源表核心通道。',
    probeDefs: [
      { id: 'session', label: '主站登录会话', description: '风神系统基础登录凭证与会话状态' },
      { id: 'cities', label: '城市权限目录', description: '当前账号可访问的城市范围授权校验' },
      { id: 'stations', label: '站点与账单拉取', description: '站点列表读取与结算账单导出接口验证' },
    ],
  },
  {
    key: 'lanorange',
    displayName: systemLabel('lanorange'),
    shortName: '蓝橙',
    businessLine: '原雷神人事与审批系统',
    scope: 'personal',
    scopeLabel: '个人独立通道',
    authMethodLabel: '手机钉钉扫码认证',
    accent: 'amber',
    usedByModules: ['蓝橙数据采集', '异常名单', '支付绑定', '价格审批'],
    description: '骑手人事档案、兼职价格表、离职报备、请假记录及价格审批流转核心通道。',
    probeDefs: [
      { id: 'session', label: '钉钉扫码会话', description: '蓝橙后台钉钉扫码绑定与令牌有效性' },
      { id: 'archive', label: '人事与价格档案', description: '全城骑手档案、离职请假及兼职价格读取权限' },
      { id: 'approval', label: '价格审批协同', description: '本人待审单据同步与跨页批量审批接口' },
    ],
  },
  {
    key: 'baize',
    displayName: systemLabel('baize'),
    shortName: '商翼',
    businessLine: '白泽商翼人力发薪系统',
    scope: 'personal',
    scopeLabel: '个人独立通道',
    authMethodLabel: '企业账号 + 算式验证码',
    accent: 'emerald',
    usedByModules: ['发薪平台采集', '支付绑定', '兼职薪资核算'],
    description: '白泽商翼全量员工档案实时采集，自动识别闪购或小象业务账户归属。',
    probeDefs: [
      { id: 'session', label: '企业账号会话', description: '白泽商翼企业账号登录与算式认证状态' },
      { id: 'account_type', label: '业务线归属识别', description: '自动探测闪购业务账户或小象业务账户及区域' },
      { id: 'export', label: '员工总表直采', description: '商翼全量员工原表导出与收薪绑定匹配' },
    ],
  },
  {
    key: 'xiaoxiang',
    displayName: systemLabel('xiaoxiang'),
    shortName: '灯塔',
    businessLine: '美团小象灯塔与知了看板',
    scope: 'shared',
    scopeLabel: '全局共享通道',
    authMethodLabel: '美团 App + 大象双阶段扫码',
    accent: 'violet',
    usedByModules: ['小象灯塔采集', '小象兼职薪资核算', '站点扣款配置'],
    description: '全局共享采集通道，一次授权全员可用；覆盖灯塔站点目录与知了日维度分析看板。',
    probeDefs: [
      { id: 'lighthouse', label: '美团灯塔主站', description: '美团 App 扫码认证与灯塔基础会话状态' },
      { id: 'stations', label: '站点目录查询', description: '灯塔配送站点目录与城市归属校验' },
      { id: 'board', label: '知了数据看板', description: '大象扫码连接知了看板与日维度骑手分析权限' },
    ],
  },
  {
    key: 'benlai',
    displayName: systemLabel('benlai'),
    shortName: '本来',
    businessLine: '本来人力灵工发薪商户端',
    scope: 'shared',
    scopeLabel: '全局共享通道',
    authMethodLabel: '手机号 + 短信动态验证码',
    accent: 'indigo',
    usedByModules: ['发薪平台采集', '支付绑定', '异常跟进'],
    description: '全局共享发薪档案通道，实时拉取企业全量灵工签约档案与签约城市归属。',
    probeDefs: [
      { id: 'session', label: '商户端登录会话', description: '本来人力商户端手机号与短信验证码登录态' },
      { id: 'roster', label: '灵工签约名册', description: '企业全量灵工档案与签约状态拉取校验' },
      { id: 'city_bind', label: '签约城市映射', description: '发薪平台绑定判定所需的签约城市字段读取' },
    ],
  },
];

export function resolvePlatformCapabilitySummary(
  source: ConnectionChipKey,
  status: PlatformRawAuthStatus,
): string {
  if (status.offline) return '功能状态暂不可读，请点击重新检测';
  if (status.busy) return '认证进行中，完成后将自动校验各项子功能权限';
  if (!status.saved && status.state !== 'ready') {
    return '尚未建立有效会话，请先登录平台账号以启用数据通道';
  }
  if (['signed_out', 'login_required'].includes(status.state || '')) {
    return '登录凭证已过期或需重新验证，请重新登录或切换账号';
  }
  if (source === 'xiaoxiang') {
    const stationsVerified = status.capabilities?.stations?.verified === true;
    const boardStage = status.stages?.board;
    return `${stationsVerified ? '站点目录已验证' : '站点目录待查询验证'} · ${
      boardStage === 'ready'
        ? '知了看板连接已就绪'
        : boardStage === 'error'
          ? '知了看板需重新扫码认证'
          : '知了看板待确认连接'
    }`;
  }
  if (
    source === 'fengshen' &&
    (status.capabilities?.cities?.verified || status.capabilities?.stations?.verified)
  ) {
    return `${status.capabilities?.stations?.verified ? '站点与城市目录已验证' : '城市目录已验证'} · 账单导出权限就绪`;
  }
  return status.state === 'ready'
    ? '主会话已验证通过，各项采集与核算子通道就绪'
    : '已保存本机会话，建议点击「重新检测」确认完整权限';
}

export function buildPlatformCapabilityProbes(
  entry: PlatformRegistryEntry,
  status: PlatformRawAuthStatus,
  baizeAccount?: BaizeAccountMeta | null,
): PlatformCapabilityProbeStatus[] {
  const isOffline = Boolean(status.offline);
  const isReady = status.state === 'ready' && !isOffline;
  const isSavedOrPartial =
    !isOffline && (Boolean(status.saved) || ['saved', 'partial'].includes(status.state || ''));

  return entry.probeDefs.map((probe, index) => {
    if (isOffline) {
      return {
        ...probe,
        tone: 'idle',
        statusText: '离线待检',
      };
    }

    if (entry.key === 'xiaoxiang') {
      if (probe.id === 'lighthouse') {
        if (isReady || isSavedOrPartial || status.stages?.lighthouse === 'ready') {
          return { ...probe, tone: 'ready', statusText: '已连接' };
        }
        return { ...probe, tone: 'idle', statusText: '未登录' };
      }
      if (probe.id === 'stations') {
        if (status.capabilities?.stations?.verified === true) {
          return { ...probe, tone: 'ready', statusText: '已验证' };
        }
        if (isReady || isSavedOrPartial) {
          return { ...probe, tone: 'warn', statusText: '待查询验证' };
        }
        return { ...probe, tone: 'idle', statusText: '未验证' };
      }
      if (probe.id === 'board') {
        const boardStage = status.stages?.board;
        if (boardStage === 'ready' || (isReady && boardStage !== 'error')) {
          return { ...probe, tone: 'ready', statusText: '已就绪' };
        }
        if (boardStage === 'error') {
          return { ...probe, tone: 'warn', statusText: '需重认证' };
        }
        if (isSavedOrPartial) {
          return { ...probe, tone: 'warn', statusText: '待确认' };
        }
        return { ...probe, tone: 'idle', statusText: '未连接' };
      }
    }

    if (entry.key === 'fengshen') {
      if (probe.id === 'session') {
        if (isReady) return { ...probe, tone: 'ready', statusText: '已验证' };
        if (isSavedOrPartial) return { ...probe, tone: 'warn', statusText: '待校验' };
        return { ...probe, tone: 'idle', statusText: '未登录' };
      }
      if (probe.id === 'cities') {
        if (status.capabilities?.cities?.verified || isReady) {
          return { ...probe, tone: 'ready', statusText: '已验证' };
        }
        if (isSavedOrPartial) return { ...probe, tone: 'warn', statusText: '待检测' };
        return { ...probe, tone: 'idle', statusText: '未验证' };
      }
      if (probe.id === 'stations') {
        if (status.capabilities?.stations?.verified || isReady) {
          return { ...probe, tone: 'ready', statusText: '已就绪' };
        }
        if (isSavedOrPartial) return { ...probe, tone: 'warn', statusText: '待检测' };
        return { ...probe, tone: 'idle', statusText: '未验证' };
      }
    }

    if (entry.key === 'baize' && probe.id === 'account_type') {
      if (isReady && baizeAccount?.account_type) {
        const typeText =
          baizeAccount.account_type === 'shanggou' ? '闪购业务线' : '小象业务线';
        return { ...probe, tone: 'ready', statusText: typeText };
      }
      if (isReady) {
        return { ...probe, tone: 'ready', statusText: '已识别' };
      }
      if (isSavedOrPartial) {
        return { ...probe, tone: 'warn', statusText: '待识别' };
      }
      return { ...probe, tone: 'idle', statusText: '未识别' };
    }

    if (isReady) {
      return {
        ...probe,
        tone: 'ready',
        statusText: index === 0 ? '已连接' : '已就绪',
      };
    }
    if (isSavedOrPartial) {
      return {
        ...probe,
        tone: 'warn',
        statusText: index === 0 ? '已存会话' : '待验证',
      };
    }
    return {
      ...probe,
      tone: 'idle',
      statusText: index === 0 ? '未登录' : '待授权',
    };
  });
}

export function buildPlatformAuthCardViewModels(options: {
  statuses: Record<string, PlatformRawAuthStatus | undefined>;
  fengshenFallback?: PlatformRawAuthStatus | null;
  baizeAccount?: BaizeAccountMeta | null;
  pendingActions?: Record<string, string | undefined>;
  errors?: Record<string, string | undefined>;
  isAdmin?: boolean;
  canManageSharedAuth?: boolean;
}): PlatformAuthCardViewModel[] {
  const {
    statuses,
    fengshenFallback,
    baizeAccount,
    pendingActions = {},
    errors = {},
    isAdmin = false,
    canManageSharedAuth = false,
  } = options;

  return PLATFORM_AUTH_REGISTRY.map(entry => {
    const raw: PlatformRawAuthStatus =
      statuses[entry.key] || (entry.key === 'fengshen' && fengshenFallback ? fengshenFallback : {}) || {};
    const pendingAction = pendingActions[entry.key];
    const badge = getPlatformCardBadge(raw, pendingAction);
    const isReady = raw.state === 'ready' && !raw.offline;
    const isBusy =
      Boolean(pendingAction) ||
      Boolean(raw.busy) ||
      ['starting', 'refreshing', 'sending', 'verifying', 'checking'].includes(raw.state || '');
    const needsAttention =
      !isReady &&
      !isBusy &&
      (badge.tone === 'warn' ||
        Boolean(errors[entry.key]) ||
        ['waiting_login', 'login_required', 'sms_sent', 'manual_required', 'partial', 'error', 'saved'].includes(
          raw.state || '',
        ));
    const isIdle = !isReady && !isBusy && !needsAttention;

    const isShared = entry.scope === 'shared';
    const canManage = isShared
      ? Boolean(isAdmin || canManageSharedAuth) && raw.can_manage !== false
      : true;

    const hasSessionOrSaved =
      Boolean(raw.saved) ||
      Boolean(raw.busy) ||
      isReady ||
      ['starting', 'waiting_login', 'saved', 'partial'].includes(raw.state || '');

    const canLogout = canManage && hasSessionOrSaved;
    const canSwitchAccount =
      canManage && (isReady || Boolean(raw.saved) || ['saved', 'partial'].includes(raw.state || ''));
    const canDeepCheck = Boolean(raw.saved || isReady) && !raw.offline;

    const accountTitle =
      (raw.account_label || '').trim() ||
      (isReady ? '已授权平台账户' : hasSessionOrSaved ? '本机已存会话账户' : '暂未绑定平台账号');
    const accountOrganization = (raw.organization || '').trim();

    let accountSubtypeLabel = '';
    if (entry.key === 'baize' && isReady && baizeAccount?.account_type) {
      const baseType = baizeAccount.account_type === 'shanggou' ? '闪购业务账户' : '小象业务账户';
      accountSubtypeLabel = baizeAccount.region_text
        ? `${baseType}（${baizeAccount.region_text}）`
        : baseType;
    }

    const credentialStatusText = raw.credential_saved
      ? '已保存本机加密凭据（支持自动重连）'
      : isReady || raw.saved
        ? '仅保留当前会话令牌'
        : '登录时可选择保存本机加密凭据';

    const capabilitySummary = resolvePlatformCapabilitySummary(entry.key, raw);
    const probes = buildPlatformCapabilityProbes(entry, raw, baizeAccount);
    const errorText =
      errors[entry.key] || (raw.offline ? '连接状态暂不可读，请点击重新检测或稍候再试。' : '');

    return {
      entry,
      raw,
      badge,
      isReady,
      isBusy,
      needsAttention,
      isIdle,
      canManage,
      canLogout,
      canSwitchAccount,
      canDeepCheck,
      accountTitle,
      accountOrganization,
      accountSubtypeLabel,
      credentialStatusText,
      capabilitySummary,
      probes,
      errorText,
    };
  });
}

export function summarizePlatformAuthOverview(
  cards: ReadonlyArray<PlatformAuthCardViewModel>,
): PlatformAuthOverviewSummary {
  const totalCount = cards.length;
  const readyCount = cards.filter(c => c.isReady).length;
  const personalCards = cards.filter(c => c.entry.scope === 'personal');
  const sharedCards = cards.filter(c => c.entry.scope === 'shared');
  const attentionCount = cards.filter(c => c.needsAttention || c.isBusy).length;
  const idleCount = cards.filter(c => c.isIdle).length;

  return {
    totalCount,
    readyCount,
    personalCount: personalCards.length,
    personalReadyCount: personalCards.filter(c => c.isReady).length,
    sharedCount: sharedCards.length,
    sharedReadyCount: sharedCards.filter(c => c.isReady).length,
    attentionCount,
    idleCount,
  };
}

export function filterPlatformAuthCards(
  cards: ReadonlyArray<PlatformAuthCardViewModel>,
  filter: {
    query?: string;
    scope?: PlatformScopeFilter;
    state?: PlatformStateFilter;
  },
): PlatformAuthCardViewModel[] {
  const q = (filter.query || '').trim().toLowerCase();
  const scope = filter.scope || 'all';
  const state = filter.state || 'all';

  return cards.filter(card => {
    if (scope !== 'all' && card.entry.scope !== scope) {
      return false;
    }
    if (state === 'ready' && !card.isReady) {
      return false;
    }
    if (state === 'attention' && !(card.needsAttention || card.isBusy)) {
      return false;
    }
    if (state === 'idle' && !card.isIdle) {
      return false;
    }
    if (!q) return true;

    const haystack = [
      card.entry.key,
      card.entry.displayName,
      card.entry.shortName,
      card.entry.businessLine,
      card.entry.scopeLabel,
      card.entry.authMethodLabel,
      card.entry.description,
      ...card.entry.usedByModules,
      card.accountTitle,
      card.accountOrganization,
      card.accountSubtypeLabel,
      card.badge.label,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase();

    return haystack.includes(q);
  });
}
