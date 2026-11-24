const PHASES: Record<string, string> = {
  queued: '排队中',
  preparing: '准备资料',
  downloading: '正在下载',
  validating: '校验文件',
  waiting_login: '等待平台登录，完成后继续',
  waiting_export: '等待平台生成文件',
  waiting_collection: '等待采集资源',
  submitting: '提交导出',
  generating: '生成资料',
  publishing: '保存文件',
  running: '处理中',
  success: '下载完成',
  error: '下载失败',
  cancelled: '已停止',
  interrupted: '已中断',
};

export function payrollLogText(
  text: string,
  jobs: string[] = [],
  scopes: Record<string, string> = {},
): string {
  if (!/^资料下载[：:]/.test(text)) return text;
  return text.replace(/\b([a-f0-9]{6})\s+([a-z_]+)\s+(\d+)%/g, (_all, id: string, phase: string) => {
    const job = jobs.find(key => key.startsWith(id));
    const scope = job ? scopes[job] : undefined;
    const prefix =
      scope === 'normal'
        ? '普通站点资料'
        : scope
          ? '取分离站点资料'
          : '本批次资料';
    return `${prefix}：${PHASES[phase] || '处理中'}`;
  });
}
