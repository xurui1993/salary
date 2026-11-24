export interface FunctionAvailabilityValue {
  offline?: boolean;
  busy?: boolean;
  saved?: boolean;
  state?: string;
  capabilities?: {
    cities?: { verified?: boolean };
    stations?: { verified?: boolean };
  };
  stages?: {
    board?: string;
  };
}

export function functionAvailability(source: string, value: FunctionAvailabilityValue): string {
  if (value.offline) return '功能状态暂不可读，请重试';
  if (value.busy) return '认证进行中，完成后检测功能';
  if (!value.saved || ['signed_out', 'login_required'].includes(value.state || '')) {
    return '需要登录后检查功能权限';
  }
  if (source === 'xiaoxiang') {
    const stations = value.capabilities?.stations?.verified === true;
    const board = value.stages?.board;
    const stationText = stations ? '站点目录已验证' : '站点目录待查询验证';
    const boardText =
      board === 'ready'
        ? '知了连接已验证，数据权限以具体查询为准'
        : board === 'error'
          ? '知了需要重新认证'
          : '知了尚未确认，日分析权限待验证';
    return `${stationText} · ${boardText}`;
  }
  if (
    source === 'fengshen' &&
    (value.capabilities?.cities?.verified || value.capabilities?.stations?.verified)
  ) {
    return `${value.capabilities?.stations?.verified ? '站点目录已验证' : '城市目录已验证'} · 账单权限以具体查询为准`;
  }
  if (value.state === 'ready') return '会话已验证，数据权限以具体查询为准';
  return '已保存会话，功能权限尚未验证';
}
