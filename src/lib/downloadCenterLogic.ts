export interface DownloadUser { id: string; username: string; role: string; enabled?: boolean }
export type DownloadFetch = (url: string, init?: RequestInit) => Promise<Response>;
export interface ItemSelection { city: string; dataset: string; start: string; end: string }
export interface Recovery { mode: 'resume_existing' | 'retry_unsubmitted' | 'blocked'; reason: string }
export interface CreateSelection { cities: string[]; datasets: string[]; start: string; end: string; refresh_history?: boolean; waybill_all_city_send?: boolean; lanorange_months?: string[]; include_separation?: boolean; exclude_separation?: boolean; merchant_by_city?: boolean; lanorange_by_city?: boolean; lanorange_full_delivery?: boolean; task_kind?: 'download' | 'generate'; generation_target?: string }
export interface RequestAttempt<T> { request_id: string; payload: T }
// abnormal_riders（异常骑手整理生成表）只依赖蓝橙成品，交付口径与蓝橙一致。
export const isBaize = (id: string) => id === 'baize_employees';
export const XIAOXIANG_DETAIL_DATASETS = ['detail_orders', 'detail_kesu', 'detail_reviews'];
export const XIAOXIANG_NOTICE_DATASETS = ['rider_order_detail', 'xiaoxiang_attendance_detail'];
export const RIDER_ARCHIVE_DATASET = 'rider_archive';
export const isRiderArchive = (id: string) => id === RIDER_ARCHIVE_DATASET;
export const isXiaoxiang = (id: string) => id === 'rider_daily' || XIAOXIANG_DETAIL_DATASETS.includes(id) || XIAOXIANG_NOTICE_DATASETS.includes(id) || isRiderArchive(id);
export const isMerchant = (id:string)=>id==='invitation_records'||id==='attendance_detail';
export const isMerchantSnapshot = (id:string)=>id==='invitation_records';
export function toggleDownloadDataset(values:string[],id:string){
  if(values.includes(id))return values.filter(value=>value!==id);
  if(isBaize(id))return [id];
  if(isXiaoxiang(id))return [...values.filter(isXiaoxiang), id];
  return [...values.filter(value=>!isBaize(value)&&!isXiaoxiang(value)),id];
}
export const isGlobalDataset = (id: string) => isBaize(id) || isLanorange(id);
export const datasetGroup = (id: string) => isBaize(id) ? 'baize' : isXiaoxiang(id) ? 'xiaoxiang' : isLanorange(id) ? 'lanorange' : 'fengshen';
export const isLanorange = (id: string) => id.startsWith('lanorange_') || id === 'abnormal_riders';

export const PHASE_LABELS: Record<string, string> = {
  queued: '排队中', waiting_collection: '等待主机采集会话', waiting_login: '等待来源登录认证',
  waiting_manual: '等待平台验证', preparing: '准备资料', submitting: '提交平台导出',
  waiting_export: '等待平台生成文件', downloading: '下载文件', validating: '校验文件',
  generating: '生成业务表', publishing: '归档成品', summarizing: '汇总合并',
  completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断',
};
export function phaseLabel(phase?: string) { return phase ? PHASE_LABELS[phase] || '正在处理' : ''; }
export function itemKey(item: ItemSelection) { return JSON.stringify([item.city, item.dataset, item.start, item.end]); }
export function selectionKey(value: CreateSelection) {
  if(value.datasets.length&&value.datasets.every(isMerchant))return JSON.stringify({datasets:[...value.datasets].sort(),scope:value.merchant_by_city?'city_merchants':'current_merchant',...(value.merchant_by_city?{cities:[...value.cities].sort()}:{}),...(value.datasets.includes('attendance_detail')?{start:value.start,end:value.end}:{})});
  if (value.datasets.length === 1 && isRiderArchive(value.datasets[0])) return JSON.stringify({datasets: ['rider_archive'], scope: 'snapshot'});
  if (value.datasets.length === 1 && isBaize(value.datasets[0])) return JSON.stringify({datasets: ['baize_employees'], scope: 'all'});
  if (value.datasets.length && value.datasets.every(isXiaoxiang)) return JSON.stringify({datasets: [...value.datasets].sort(), scope: 'all', start: value.start, end: value.end});
  if (value.datasets.length && value.datasets.every(isLanorange)) {
    if (value.lanorange_full_delivery) {
      return JSON.stringify({
        datasets: [...value.datasets].sort(),
        scope: 'full_delivery',
        lanorange_full_delivery: true,
        ...(value.lanorange_months?.length ? {lanorange_months: [...value.lanorange_months].sort()} : {})
      });
    }
    const scopedCities = (value.cities || []).filter(city => city !== '全部城市');
    const hasCityScope = scopedCities.length > 0 && value.lanorange_by_city !== false;
    return JSON.stringify({
      datasets: [...value.datasets].sort(),
      scope: hasCityScope ? 'city' : 'all',
      ...(hasCityScope ? {cities: [...scopedCities].sort()} : {}),
      ...(value.lanorange_by_city ? {lanorange_by_city: true} : {}),
      ...(value.lanorange_months?.length ? {lanorange_months: [...value.lanorange_months].sort()} : {})
    });
  }
  return JSON.stringify({ cities: [...value.cities].sort(), datasets: [...value.datasets].sort(), start: value.start, end: value.end,
    ...(value.refresh_history ? { refresh_history: true } : {}), ...(value.waybill_all_city_send ? { waybill_all_city_send: true } : {}),
    ...(value.lanorange_months?.length ? {lanorange_months: [...value.lanorange_months].sort()} : {}),
    ...(value.include_separation ? { include_separation: true } : {}),
    ...(value.exclude_separation !== undefined ? { exclude_separation: value.exclude_separation } : {}),
    ...(value.lanorange_by_city ? {lanorange_by_city: true} : {}), ...(value.lanorange_full_delivery ? {lanorange_full_delivery:true} : {}) });
}
export function newRequestId() {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID();
  // HTTP LAN pages may lack randomUUID; getRandomValues is still available.
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export function retainAttempt<T>(current: RequestAttempt<T> | null, payload: T): RequestAttempt<T> {
  if (current) return current;
  return { request_id: newRequestId(), payload: JSON.parse(JSON.stringify(payload)) };
}
export function recoverable(item: { status: string; submission_state?: string; recovery?: Recovery }) {
  return ['error', 'failed', 'cancelled', 'interrupted'].includes(item.status.toLowerCase())
    && !!item.recovery && (item.recovery.mode === 'resume_existing' || (item.recovery.mode === 'retry_unsubmitted' && !['unknown', 'submitted'].includes(item.submission_state || '')));
}

export function recoverySummary(items: {status: string; submission_state?: string; recovery?: Recovery}[]) {
  return { retained: items.filter(i => i.status === 'success').length,
    continuing: items.filter(i => recoverable(i) && i.recovery?.mode === 'resume_existing').length,
    unsubmitted: items.filter(i => recoverable(i) && i.recovery?.mode === 'retry_unsubmitted').length,
    blocked: items.filter(i => ['error','failed','cancelled','interrupted'].includes(i.status.toLowerCase()) && !recoverable(i)).length };
}
