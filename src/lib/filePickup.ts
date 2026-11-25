export interface PickupFile {
  name: string;
  id?: string;
  run_id?: string;
  available?: boolean;
  size?: number;
}

export interface PickupTaskRecord {
  id: string;
  kind: string;
  title?: string;
  status: string;
  files?: PickupFile[];
  price_id?: string;
  created_at?: string;
  updated_at?: string;
  cities?: string[];
  datasets?: string[];
}

export interface PickupSource {
  id: string;
  name: string;
  unc: string;
  created?: string;
  reachable?: boolean;
}

export interface SharedEntry {
  name: string;
  dir: boolean;
  size: number;
  mtime: number;
}

export interface DownloadTarget {
  url: string;
  name: string;
}

const DELIVERED = new Set(['success', 'partial']);

export function deliverableTasks(records: PickupTaskRecord[]): PickupTaskRecord[] {
  return (records || []).filter(record => {
    if (!record || !DELIVERED.has(record.status)) return false;
    if (record.kind === 'approval' || record.kind === 'price-export') return Boolean(record.price_id);
    return (record.files || []).some(file => file.available !== false);
  });
}

export function taskFileTarget(record: PickupTaskRecord, file?: PickupFile): DownloadTarget | null {
  if (!record) return null;
  if (record.kind === 'approval' && record.price_id) {
    return {
      url: `/api/fengshen-downloads/lanorange-approvals/batches/${record.price_id}/result.csv`,
      name: '蓝橙价格审批回执.csv',
    };
  }
  if (record.kind === 'price-export' && record.price_id) {
    return {
      url: `/api/fengshen-downloads/lanorange-prices/exports/${record.price_id}/result.xlsx`,
      name: '蓝橙待审每日价格.xlsx',
    };
  }
  if (file?.run_id && file?.id) {
    return {
      url: `/api/fengshen-downloads/runs/${file.run_id}/files/${file.id}`,
      name: file.name || '结果文件',
    };
  }
  return null;
}

export function taskBundleTarget(record: PickupTaskRecord): DownloadTarget | null {
  if (!record) return null;
  if (record.kind === 'approval' || record.kind === 'price-export') return taskFileTarget(record);
  return { url: `/api/fengshen-downloads/records/${record.id}/bundle`, name: `结果_${record.id.slice(0, 8)}.zip` };
}

export function taskDownloadableFiles(record: PickupTaskRecord): PickupFile[] {
  if (record.kind === 'approval' || record.kind === 'price-export') return [];
  return (record.files || []).filter(file => file.available !== false);
}

export function joinSharePath(parent: string, name: string): string {
  const base = (parent || '').replace(/^\\+/, '').replace(/\\+$/, '');
  return base ? `${base}\\${name}` : name;
}

export function parentSharePath(path: string): string {
  const index = (path || '').lastIndexOf('\\');
  return index < 0 ? '' : path.slice(0, index);
}

export function formatPickupSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatPickupTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatShareTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  return formatPickupTime(new Date(seconds * 1000).toISOString());
}