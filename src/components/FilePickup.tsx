import React, { useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronRight,
  Copy,
  Download,
  FileSpreadsheet,
  Folder,
  FolderOpen,
  HardDrive,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { downloadErrorMessage, readDownloadResponse, saveDownloadBlob } from '../lib/outputDownload';
import {
  deliverableTasks,
  formatPickupSize,
  formatPickupTime,
  formatShareTime,
  joinSharePath,
  parentSharePath,
  taskBundleTarget,
  taskDownloadableFiles,
  taskFileTarget,
  type DownloadTarget,
  type PickupSource,
  type PickupTaskRecord,
  type SharedEntry,
} from '../lib/filePickup';
import { cleanTaskTitle } from '../lib/taskCenterDisplay';

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

interface TaskCenterResponse {
  records?: PickupTaskRecord[];
  pages?: number;
}

interface SharedListing {
  path: string;
  parent: string | null;
  entries: SharedEntry[];
}

interface ShareInfo {
  local: boolean;
  path: string;
  shared: boolean;
  share_name: string;
  shares: { name: string; path: string }[];
  lan_urls: string[];
  error?: string;
}

const KIND_LABEL: Record<string, string> = {
  download: '资料下载',
  generate: '业务报表',
  approval: '价格审批',
  'price-export': '每日价格',
  payroll: '薪资核算',
  payroll_source: '核算资料',
};

function displayTitle(record: PickupTaskRecord): string {
  const raw = (record.title || '').trim();
  if (raw) return cleanTaskTitle(raw);
  return KIND_LABEL[record.kind] || '后台任务';
}

async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // LAN 页面不是安全上下文时退回 execCommand
  }
  try {
    const area = document.createElement('textarea');
    area.value = value;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const done = document.execCommand('copy');
    area.remove();
    return done;
  } catch {
    return false;
  }
}

export function FilePickup({ apiFetch }: { apiFetch: Fetcher }) {
  const [sources, setSources] = useState<PickupSource[]>([]);
  const [maxSources, setMaxSources] = useState(20);
  const [active, setActive] = useState('local');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: '', unc: '' });
  const [savingSource, setSavingSource] = useState(false);
  const [checking, setChecking] = useState('');
  const [sourceState, setSourceState] = useState<Record<string, boolean>>({});
  const [records, setRecords] = useState<PickupTaskRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState('');
  const [query, setQuery] = useState('');
  const [reload, setReload] = useState(0);
  const [sharePath, setSharePath] = useState('');
  const [entries, setEntries] = useState<SharedEntry[]>([]);
  const [listingLoading, setListingLoading] = useState(false);
  const [listingError, setListingError] = useState('');
  const [busy, setBusy] = useState('');
  const [shareInfo, setShareInfo] = useState<ShareInfo | null>(null);
  const [copied, setCopied] = useState('');

  const activeSource = sources.find(item => item.id === active) || null;

  const readJson = async <T,>(url: string, init?: RequestInit): Promise<T> => {
    const response = await apiFetch(url, init);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = (data as { detail?: unknown })?.detail;
      throw new Error(typeof detail === 'string' ? detail : '请求未完成，请稍后重试');
    }
    return data as T;
  };

  useEffect(() => {
    let disposed = false;
    readJson<{ sources: PickupSource[]; max: number }>('/api/workbench/file-pickup/sources')
      .then(value => {
        if (disposed) return;
        setSources(value.sources || []);
        setMaxSources(value.max || 20);
      })
      .catch(err => {
        if (!disposed) setError(err instanceof Error ? err.message : '共享电脑列表读取失败');
      });
    readJson<ShareInfo>('/api/workbench/file-pickup/share-info')
      .then(value => {
        if (!disposed) setShareInfo(value);
      })
      .catch(() => {
        if (!disposed) setShareInfo(null);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (active !== 'local') return;
    let disposed = false;
    setRecordsLoading(true);
    setRecordsError('');
    (async () => {
      const collected: PickupTaskRecord[] = [];
      let page = 1;
      let pages = 1;
      do {
        const data = await readJson<TaskCenterResponse>(`/api/workbench/task-center?page=${page}&page_size=100`);
        collected.push(...(data.records || []));
        pages = data.pages || 1;
        page += 1;
      } while (page <= pages && page <= 10);
      if (!disposed) setRecords(deliverableTasks(collected));
    })()
      .catch(err => {
        if (!disposed) setRecordsError(err instanceof Error ? err.message : '任务列表读取失败');
      })
      .finally(() => {
        if (!disposed) setRecordsLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [active, reload]);

  useEffect(() => {
    if (active === 'local') return;
    let disposed = false;
    setListingLoading(true);
    setListingError('');
    readJson<SharedListing>(
      `/api/workbench/file-pickup/sources/${encodeURIComponent(active)}/list?path=${encodeURIComponent(sharePath)}`,
    )
      .then(value => {
        if (disposed) return;
        setEntries(Array.isArray(value.entries) ? value.entries : []);
        setSourceState(prev => ({ ...prev, [active]: true }));
      })
      .catch(err => {
        if (disposed) return;
        setEntries([]);
        setSourceState(prev => ({ ...prev, [active]: false }));
        setListingError(err instanceof Error ? err.message : '共享文件夹读取失败');
      })
      .finally(() => {
        if (!disposed) setListingLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [active, sharePath, reload]);

  const visibleRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return records;
    return records.filter(record => {
      const text = [displayTitle(record), ...(record.cities || []), ...(record.files || []).map(file => file.name)]
        .join(' ')
        .toLowerCase();
      return text.includes(keyword);
    });
  }, [records, query]);

  const switchSource = (key: string) => {
    setError('');
    setNotice('');
    setActive(key);
    setSharePath('');
    setEntries([]);
  };

  const addSource = async (event: React.FormEvent) => {
    event.preventDefault();
    if (savingSource) return;
    setSavingSource(true);
    setError('');
    try {
      const value = await readJson<{ source: PickupSource }>('/api/workbench/file-pickup/sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: form.name.trim(), unc: form.unc.trim() }),
      });
      setSources(prev => [...prev, value.source]);
      setSourceState(prev => ({ ...prev, [value.source.id]: Boolean(value.source.reachable) }));
      setActive(value.source.id);
      setSharePath('');
      setAddOpen(false);
      setForm({ name: '', unc: '' });
      setNotice(value.source.reachable
        ? `已添加「${value.source.name}」并连接成功`
        : `已添加「${value.source.name}」，当前无法访问；请确认对方电脑在线且共享权限可用`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加共享电脑未完成');
    } finally {
      setSavingSource(false);
    }
  };

  const removeSource = async (source: PickupSource) => {
    if (!window.confirm(`移除共享电脑「${source.name}」？仅移除本系统记录，不影响对方电脑上的文件。`)) return;
    setError('');
    try {
      await readJson(`/api/workbench/file-pickup/sources/${encodeURIComponent(source.id)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      });
      setSources(prev => prev.filter(item => item.id !== source.id));
      if (active === source.id) switchSource('local');
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除未完成');
    }
  };

  const checkSource = async (source: PickupSource) => {
    setChecking(source.id);
    setError('');
    try {
      const value = await readJson<{ reachable: boolean }>(
        `/api/workbench/file-pickup/sources/${encodeURIComponent(source.id)}/check`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
      );
      setSourceState(prev => ({ ...prev, [source.id]: value.reachable }));
      setNotice(value.reachable ? `「${source.name}」连接正常` : `「${source.name}」当前无法访问，请确认对方在线与共享权限`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '连接检查未完成');
    } finally {
      setChecking('');
    }
  };

  const download = async (target: DownloadTarget | null, key: string) => {
    if (!target || busy) return;
    setBusy(key);
    setError('');
    try {
      const response = await apiFetch(target.url, { signal: AbortSignal.timeout(180000) });
      let filename = target.name;
      const disposition = response.headers.get('content-disposition') || '';
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
      if (encoded) {
        try {
          const actual = decodeURIComponent(encoded);
          if (actual && !/[\\/\x00-\x1f]/.test(actual)) filename = actual;
        } catch {
          // 保留默认文件名
        }
      }
      saveDownloadBlob(await readDownloadResponse(response, filename), filename);
      setNotice(`已开始保存：${filename}`);
    } catch (err) {
      setError(downloadErrorMessage(err));
    } finally {
      setBusy('');
    }
  };

  const copy = async (value: string, key: string) => {
    if (!value) return;
    const done = await copyText(value);
    if (done) {
      setCopied(key);
      setTimeout(() => setCopied(current => (current === key ? '' : current)), 1500);
    } else {
      setError('复制失败，请手动选择文本复制');
    }
  };

  const openEntry = (entry: SharedEntry) => {
    if (entry.dir) {
      setSharePath(current => joinSharePath(current, entry.name));
      return;
    }
    const target = {
      url: `/api/workbench/file-pickup/sources/${encodeURIComponent(active)}/download?path=${encodeURIComponent(joinSharePath(sharePath, entry.name))}`,
      name: entry.name,
    };
    void download(target, `${active}:${joinSharePath(sharePath, entry.name)}`);
  };

  const breadcrumb = useMemo(() => {
    const segments = sharePath ? sharePath.split('\\') : [];
    const items = [{ label: '共享根目录', path: '' }];
    segments.forEach((segment, index) => {
      items.push({ label: segment, path: segments.slice(0, index + 1).join('\\') });
    });
    return items;
  }, [sharePath]);

  return (
    <div className="w-full max-w-full min-w-0 text-slate-900">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-3">
        <div>
          <h2 className="text-lg font-semibold">组内共享</h2>
          <p className="mt-1 text-xs text-slate-500">
            仅列出已完成任务的成品文件；局域网同事可直接下载或打包，也可切换到已添加的组内共享电脑。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-lg bg-slate-100 p-1">
            <button
              type="button"
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ${active === 'local' ? 'bg-white text-sky-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}
              onClick={() => switchSource('local')}
            >
              <HardDrive size={14} />
              本机成品
            </button>
            {sources.map(source => (
              <button
                key={source.id}
                type="button"
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ${active === source.id ? 'bg-white text-sky-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}
                title={source.unc}
                onClick={() => switchSource(source.id)}
              >
                <Network size={14} />
                {source.name}
                <span className={`h-1.5 w-1.5 rounded-full ${sourceState[source.id] === false ? 'bg-rose-500' : sourceState[source.id] ? 'bg-emerald-500' : 'bg-slate-300'}`} />
              </button>
            ))}
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900"
              onClick={() => {
                setAddOpen(value => !value);
                setError('');
              }}
            >
              <Plus size={14} />
              添加共享电脑
            </button>
          </div>
          <button
            type="button"
            className="wbx-btn wbx-btn--sm"
            onClick={() => setReload(value => value + 1)}
          >
            <RefreshCw size={13} />
            刷新
          </button>
        </div>
      </header>

      {addOpen && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3"
          onSubmit={addSource}
        >
          <label className="flex min-w-[140px] flex-1 flex-col gap-1 text-xs text-slate-600">
            电脑名称
            <input
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm"
              placeholder="例如：同事老王"
              value={form.name}
              maxLength={30}
              onChange={event => setForm(prev => ({ ...prev, name: event.target.value }))}
            />
          </label>
          <label className="flex min-w-[280px] flex-[2] flex-col gap-1 text-xs text-slate-600">
            共享路径（UNC）
            <input
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm"
              placeholder="\\\\192.168.1.20\\薪酬成品"
              value={form.unc}
              maxLength={400}
              onChange={event => setForm(prev => ({ ...prev, unc: event.target.value }))}
            />
          </label>
          <button type="submit" className="wbx-btn wbx-btn--primary wbx-btn--sm" disabled={savingSource || !form.name.trim() || !form.unc.trim()}>
            {savingSource ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            保存
          </button>
          <button type="button" className="wbx-btn wbx-btn--sm" onClick={() => setAddOpen(false)} disabled={savingSource}>
            <X size={13} />
            取消
          </button>
          <p className="basis-full text-[11px] leading-relaxed text-slate-500">
            请先在这台电脑的资源管理器访问一次该共享并勾选「记住我的凭据」，系统使用本机 Windows 账号读取；当前共 {sources.length}/{maxSources} 台。
          </p>
        </form>
      )}

      {(error || notice) && (
        <div className="mt-3 space-y-2">
          {error && <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
          {notice && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div>}
        </div>
      )}

      {active === 'local' ? (
        <section className="mt-4" aria-label="本机成品文件">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="relative flex w-full max-w-sm items-center">
              <Search size={14} className="pointer-events-none absolute left-2.5 text-slate-400" />
              <input
                className="w-full rounded-lg border border-slate-300 bg-white py-1.5 pl-8 pr-2.5 text-sm"
                placeholder="搜索任务、城市或文件名"
                value={query}
                onChange={event => setQuery(event.target.value)}
              />
            </label>
            <span className="text-xs text-slate-500 tabular-nums">
              {recordsLoading ? '加载中…' : `${visibleRecords.length} 个已完成任务`}
            </span>
          </div>

          {recordsError && <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{recordsError}</p>}

          {recordsLoading && (
            <div className="mt-3 space-y-2">
              {[0, 1, 2].map(index => (
                <div key={index} className="h-20 animate-pulse rounded-xl border border-slate-200 bg-slate-50" />
              ))}
            </div>
          )}

          {!recordsLoading && !recordsError && visibleRecords.length === 0 && (
            <div className="mt-6 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center">
              <FolderOpen size={22} className="mx-auto text-slate-400" />
              <p className="mt-2 text-sm font-medium text-slate-700">{query ? '没有匹配的成品文件' : '暂无已完成任务的成品文件'}</p>
              <p className="mt-1 text-xs text-slate-500">数据采集或核算任务完成后，成品会出现在这里，可直接下载或打包。</p>
            </div>
          )}

          <div className="mt-3 space-y-2.5">
            {visibleRecords.map(record => {
              const files = taskDownloadableFiles(record);
              const special = record.kind === 'approval' || record.kind === 'price-export';
              const bundle = taskBundleTarget(record);
              const meta = [
                formatPickupTime(record.updated_at || record.created_at),
                (record.cities || []).join('、') || '全量范围',
                KIND_LABEL[record.kind] || '后台任务',
              ].filter(Boolean).join(' · ');
              return (
                <article key={record.id} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold text-slate-900" title={displayTitle(record)}>{displayTitle(record)}</h3>
                      <p className="mt-0.5 text-xs text-slate-500 tabular-nums">{meta}</p>
                    </div>
                    {!special && files.length > 1 && bundle && (
                      <button
                        type="button"
                        className="wbx-btn wbx-btn--sm"
                        disabled={!!busy}
                        onClick={() => void download(bundle, `bundle:${record.id}`)}
                      >
                        {busy === `bundle:${record.id}` ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                        打包下载
                      </button>
                    )}
                  </div>

                  <ul className="mt-2 divide-y divide-slate-100 rounded-lg bg-slate-50/70">
                    {special && (
                      <FileRow
                        name={taskFileTarget(record)?.name || '审批结果'}
                        busy={busy === `file:${record.id}`}
                        onDownload={() => void download(taskFileTarget(record), `file:${record.id}`)}
                      />
                    )}
                    {!special && files.map((file, index) => {
                      const target = taskFileTarget(record, file);
                      const key = `file:${record.id}:${file.id || index}`;
                      return (
                        <FileRow
                          key={key}
                          name={file.name}
                          busy={busy === key}
                          onDownload={() => (target ? void download(target, key) : void download(bundle, key))}
                        />
                      );
                    })}
                    {!special && files.length === 0 && (
                      <li className="px-3 py-2 text-xs text-slate-500">该任务暂无可单独下载的成品，请使用打包下载。</li>
                    )}
                  </ul>
                </article>
              );
            })}
          </div>
        </section>
      ) : (
        <section className="mt-4" aria-label="共享电脑文件">
          {activeSource && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">{activeSource.name}</p>
                <p className="truncate text-xs text-slate-500" title={activeSource.unc}>{activeSource.unc}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm"
                  disabled={checking === activeSource.id}
                  onClick={() => void checkSource(activeSource)}
                >
                  {checking === activeSource.id ? <Loader2 size={13} className="animate-spin" /> : <Network size={13} />}
                  检查连接
                </button>
                <button
                  type="button"
                  className="wbx-btn wbx-btn--sm wbx-btn--danger"
                  onClick={() => void removeSource(activeSource)}
                >
                  <Trash2 size={13} />
                  移除
                </button>
              </div>
            </div>
          )}

          <nav className="mt-3 flex flex-wrap items-center gap-1 text-xs text-slate-600" aria-label="共享目录路径">
            {breadcrumb.map((item, index) => (
              <React.Fragment key={item.path || 'root'}>
                {index > 0 && <ChevronRight size={12} className="text-slate-400" />}
                <button
                  type="button"
                  className={`rounded px-1.5 py-0.5 ${index === breadcrumb.length - 1 ? 'font-medium text-slate-900' : 'hover:bg-slate-100'}`}
                  onClick={() => setSharePath(item.path)}
                >
                  {item.label}
                </button>
              </React.Fragment>
            ))}
          </nav>

          {listingLoading && (
            <div className="mt-3 space-y-2">
              {[0, 1, 2].map(index => (
                <div key={index} className="h-10 animate-pulse rounded-lg bg-slate-100" />
              ))}
            </div>
          )}

          {!listingLoading && listingError && (
            <div role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {listingError}
              <button type="button" className="ml-2 underline" onClick={() => setReload(value => value + 1)}>重试</button>
            </div>
          )}

          {!listingLoading && !listingError && entries.length === 0 && (
            <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center">
              <FolderOpen size={22} className="mx-auto text-slate-400" />
              <p className="mt-2 text-sm font-medium text-slate-700">这个文件夹是空的</p>
            </div>
          )}

          {!listingLoading && !listingError && entries.length > 0 && (
            <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">名称</th>
                    <th className="w-24 px-3 py-2 text-right font-medium">大小</th>
                    <th className="w-40 px-3 py-2 text-right font-medium">修改时间</th>
                    <th className="w-24 px-3 py-2 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {entries.map(entry => (
                    <tr key={entry.name} className="hover:bg-slate-50/70">
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          className="flex max-w-full items-center gap-2 text-left"
                          onClick={() => openEntry(entry)}
                          title={entry.name}
                        >
                          {entry.dir ? <Folder size={15} className="shrink-0 text-amber-500" /> : <FileSpreadsheet size={15} className="shrink-0 text-sky-600" />}
                          <span className="truncate">{entry.name}</span>
                        </button>
                      </td>
                      <td className="px-3 py-2 text-right text-xs text-slate-500 tabular-nums">{entry.dir ? '—' : formatPickupSize(entry.size)}</td>
                      <td className="px-3 py-2 text-right text-xs text-slate-500 tabular-nums">{formatShareTime(entry.mtime)}</td>
                      <td className="px-3 py-2 text-right">
                        {entry.dir ? (
                          <button type="button" className="text-xs text-sky-700 hover:underline" onClick={() => openEntry(entry)}>进入</button>
                        ) : (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:underline disabled:opacity-50"
                            disabled={!!busy}
                            onClick={() => openEntry(entry)}
                          >
                            {busy === `${active}:${joinSharePath(sharePath, entry.name)}`
                              ? <Loader2 size={12} className="animate-spin" />
                              : <Download size={12} />}
                            获取
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sharePath && (
            <button
              type="button"
              className="mt-2 text-xs text-sky-700 hover:underline"
              onClick={() => setSharePath(parentSharePath(sharePath))}
            >
              返回上一级
            </button>
          )}
        </section>
      )}

      {shareInfo && (
        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-3" aria-label="共享给同事">
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <HardDrive size={15} className="text-slate-500" />
              共享给同事（本机）
            </h3>
            {shareInfo.local && (
              <span className={`rounded-full px-2 py-0.5 text-[11px] ${shareInfo.shared ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                {shareInfo.shared ? `已共享为「${shareInfo.share_name}」` : '尚未检测到共享'}
              </span>
            )}
          </div>

          {!shareInfo.local ? (
            <p className="mt-2 text-xs text-slate-500">当前为远程访问；共享路径只在运行本系统的电脑上显示。</p>
          ) : (
            <>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="max-w-full truncate rounded bg-slate-50 px-2 py-1 text-xs text-slate-700" title={shareInfo.path}>
                  {shareInfo.path || '成品目录不可用'}
                </code>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"
                  onClick={() => void copy(shareInfo.path, 'path')}
                >
                  {copied === 'path' ? <Check size={12} /> : <Copy size={12} />}
                  {copied === 'path' ? '已复制' : '复制路径'}
                </button>
              </div>
              {!shareInfo.shared && (
                <p className="mt-2 text-xs leading-relaxed text-slate-500">
                  在 Windows 中右键该目录 → 属性 → 共享，设置共享名与读取权限；同事即可在资源管理器输入 <code className="rounded bg-slate-50 px-1">{`\\\\本机IP\\共享名`}</code> 访问。
                </p>
              )}
              {shareInfo.lan_urls.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                  <span>同事也可通过网页领取：</span>
                  {shareInfo.lan_urls.map(url => (
                    <button
                      key={url}
                      type="button"
                      className="inline-flex items-center gap-1 rounded bg-slate-50 px-2 py-0.5 text-sky-700 hover:underline"
                      onClick={() => void copy(url, url)}
                    >
                      {copied === url ? <Check size={11} /> : <Copy size={11} />}
                      {url}
                    </button>
                  ))}
                </div>
              )}
              {shareInfo.error && <p className="mt-2 text-xs text-amber-700">{shareInfo.error}</p>}
            </>
          )}
        </section>
      )}
    </div>
  );
}

function FileRow({ name, busy, onDownload }: { name: string; busy: boolean; onDownload: () => void }) {
  return (
    <li className="flex items-center justify-between gap-2 px-3 py-2">
      <span className="flex min-w-0 items-center gap-2 text-xs text-slate-700">
        <FileSpreadsheet size={14} className="shrink-0 text-sky-600" />
        <span className="truncate" title={name}>{name}</span>
      </span>
      <button
        type="button"
        className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-sky-700 hover:underline disabled:opacity-50"
        disabled={busy}
        onClick={onDownload}
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
        下载
      </button>
    </li>
  );
}