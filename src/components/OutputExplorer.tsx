import React, { useState, useEffect } from 'react';
import { Folder, Download, ChevronRight, Package, Loader2, FileSpreadsheet, FileText, CheckCircle, X, Clock } from 'lucide-react';
import { downloadOutput } from '../lib/outputDownload';
import { getWorkspaceId } from '../utils';

const formatSize = (bytes: number) => {
  if (!bytes) return '';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

const FileTreeItem = ({ item, level = 0 }: { item: any; level?: number; appTheme?: 'light' | 'dark' }) => {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [isDownloaded, setIsDownloaded] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState('');

  const toggleDir = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!item.is_dir) return;

    if (!expanded && children.length === 0) {
      setLoading(true);
      try {
        const res = await fetch('/api/files', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-workspace-id': encodeURIComponent(getWorkspaceId()) },
          body: JSON.stringify({ path: item.path }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || '目录读取失败，请重试');
        setChildren(data.files || []);
      } catch (e) {
        setDownloadError(e instanceof Error ? e.message : '目录读取失败，请重试');
        setLoading(false); return;
      }
      setLoading(false);
    }
    setExpanded(!expanded);
  };

  const downloadItem = async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (item.is_dir) { await toggleDir(e as React.MouseEvent); return; }
    if (downloading) return;
    setDownloading(true); setDownloadError('');
    try {
      const wid = getWorkspaceId();
      await downloadOutput(`/api/download?path=${encodeURIComponent(item.path)}&workspace_id=${encodeURIComponent(wid)}`, wid, item.name || 'download');
      setIsDownloaded(true); setTimeout(() => setIsDownloaded(false), 2000);
    } catch (error) { setDownloadError(error instanceof Error ? error.message : '文件下载失败'); }
    finally { setDownloading(false); }
  };

  const isExcel = item.name.endsWith('.xlsx') || item.name.endsWith('.xls');
  const isCsv = item.name.endsWith('.csv');

  return (
    <div className="flex flex-col">
      <div
        onClick={() => (item.is_dir ? toggleDir({ stopPropagation: () => {} } as any) : downloadItem())}
        className={`flex items-center justify-between py-3 px-4 rounded-xl border cursor-pointer mb-2 relative group overflow-hidden ${
          item.is_dir
            ? 'bg-sky-50 hover:bg-sky-100/70 border-sky-200'
            : isExcel || isCsv
              ? 'bg-emerald-50/40 hover:bg-emerald-50 border-emerald-100 hover:border-emerald-300'
              : 'bg-white hover:bg-slate-50 border-slate-200'
        }`}
      >
        <div className="flex items-center gap-3 overflow-hidden flex-1">
          {item.is_dir ? (
            <div className={`shrink-0 ${expanded ? 'rotate-90' : ''}`}>
              <ChevronRight className="w-4 h-4 text-slate-500" />
            </div>
          ) : (
            <div className="w-4 h-4 shrink-0" />
          )}

          <div
            className={`p-2 rounded-lg shrink-0 border ${
              item.is_dir
                ? 'bg-sky-100/80 border-sky-200 text-sky-700'
                : isExcel || isCsv
                  ? 'bg-emerald-100/80 border-emerald-200 text-emerald-600'
                  : 'bg-slate-100 border-slate-200 text-slate-600'
            }`}
          >
            {item.is_dir ? (
              <Folder className="w-4 h-4" />
            ) : isExcel || isCsv ? (
              <FileSpreadsheet className="w-4 h-4" />
            ) : (
              <FileText className="w-4 h-4" />
            )}
          </div>

          <div className="flex flex-col min-w-0 flex-1">
            <span
              className={`text-[13px] font-medium truncate ${
                item.is_dir
                  ? 'text-sky-950 font-semibold'
                  : isExcel || isCsv
                    ? 'text-emerald-950 font-bold'
                    : 'text-slate-800'
              }`}
            >
              {item.name}
            </span>
            <div className="flex items-center gap-3 mt-0.5">
              {!item.is_dir && item.size && (
                <span className="text-[11px] font-mono text-slate-500 flex items-center gap-2">
                  <span>{formatSize(item.size)}</span>
                  {item.mtime && (
                    <>
                      <span className="opacity-40">|</span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(item.mtime).toLocaleString()}
                      </span>
                    </>
                  )}
                </span>
              )}
              {item.is_dir && (
                <span className="text-[11px] font-mono text-sky-700 flex items-center gap-2">
                  <span>目录文件夹</span>
                  {item.mtime && (
                    <>
                      <span className="opacity-40">|</span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(item.mtime).toLocaleString()}
                      </span>
                    </>
                  )}
                </span>
              )}
            </div>
          </div>
          {loading && <Loader2 className="w-4 h-4 text-sky-700 shrink-0" />}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] font-mono opacity-0 group-hover:opacity-100 mr-2 text-slate-500">
            {item.is_dir ? (expanded ? '点击收起' : '点击展开') : isDownloaded ? '已发起下载' : '点击下载'}
          </span>

          <button
            onClick={event => void downloadItem(event)} disabled={downloading}
            aria-label={item.is_dir ? `展开 ${item.name}` : `下载 ${item.name}`} 
            className={`p-2 rounded-lg border shrink-0 ${
              isDownloaded
                ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
                : item.is_dir
                  ? 'bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100'
                  : 'bg-emerald-50 text-emerald-600 border-emerald-100 hover:bg-emerald-100'
            }`}
          >
            {isDownloaded ? <CheckCircle className="w-4 h-4" /> : <Download className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {downloadError && <p role="alert" className="wb-error">{downloadError}</p>}
      {expanded && children.length > 0 && (
        <div className="overflow-hidden pl-4 ml-3 border-l border-slate-200 mt-1">
          {children.map((child, idx) => (
            <FileTreeItem key={idx} item={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

export function OutputExplorer({
  path,
  onClose,
  title,
}: {
  path: string;
  appTheme?: 'light' | 'dark';
  onClose?: () => void;
  title?: string;
}) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [zipDownloading, setZipDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState('');

  useEffect(() => {
    if (path) {
      setLoading(true);
      fetch('/api/files', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-workspace-id': encodeURIComponent(getWorkspaceId()) },
        body: JSON.stringify({ path }),
      })
        .then(res => { if (!res.ok) throw new Error(`文件列表读取失败（${res.status}）`); return res.json(); })
        .then(data => {
          setItems(data.files || []);
          setLoading(false);
        })
        .catch(error => { setDownloadError(error.message || '文件列表读取失败'); setLoading(false); });
    }
  }, [path]);

  const [filterQuery, setFilterQuery] = useState('');

  const downloadAll = async () => {
    if (zipDownloading) return;
    setZipDownloading(true); setDownloadError('');
    try {
      const wid = getWorkspaceId();
      await downloadOutput(`/api/download?path=${encodeURIComponent(path)}&workspace_id=${encodeURIComponent(wid)}`, wid, `${folderName}.zip`);
    } catch (error) { setDownloadError(error instanceof Error ? error.message : '打包下载失败'); }
    finally { setZipDownloading(false); }
  };

  const folderName = path.split(/[/\\]/).pop() || '任务输出';

  const filteredItems = items.filter(item =>
    !filterQuery.trim() || item.name.toLowerCase().includes(filterQuery.trim().toLowerCase())
  );

  return (
    <div className="h-full w-full flex flex-col relative z-20 bg-slate-50 text-slate-800 border border-slate-200 rounded-xl overflow-hidden">
      <div className="h-[3px] w-full bg-sky-600 shrink-0" />

      <div className="flex items-center justify-between p-4 border-b shrink-0 bg-white border-slate-200">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl shrink-0 bg-sky-50 text-sky-700">
            <Package className="w-5 h-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-[14px] font-bold tracking-wide text-slate-900">
              {title || '任务输出结果'}
            </span>
            <span className="text-[11px] font-mono text-slate-500 truncate max-w-[200px]" title={folderName}>
              目录: {folderName}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {items.length > 2 && (
            <input
              type="text"
              placeholder="搜索产出表名..."
              value={filterQuery}
              onChange={e => setFilterQuery(e.target.value)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-sky-600 w-36"
            />
          )}
          <button
            onClick={downloadAll}
            disabled={zipDownloading || items.length === 0}
            className={`flex items-center gap-2 px-4 py-2 font-bold tracking-wider rounded-xl text-xs ${
              zipDownloading
                ? 'bg-sky-100 text-sky-700 cursor-not-allowed border border-sky-200'
                : 'bg-sky-700 hover:bg-sky-800 text-white shadow-sm'
            }`}
          >
            {zipDownloading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 打包中...
              </>
            ) : (
              <>
                <Download className="w-3.5 h-3.5" /> 打包下载全部
              </>
            )}
          </button>

          {onClose && (
            <button
              onClick={onClose}
              className="p-2 rounded-xl border bg-slate-100 hover:bg-slate-200 border-slate-200 text-slate-500 hover:text-slate-800"
              title="收起结果面板"
            >
              <X className="w-4.5 h-4.5" />
            </button>
          )}
        </div>
      </div>

      {downloadError && <div role="alert" className="wb-error"><p>{downloadError}</p><p>可直接使用下方每个文件的下载按钮，逐个领取；无需重新核算或重新采集。</p></div>}
      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        {loading ? (
          <div className="flex flex-col justify-center items-center h-full gap-3 text-slate-500 text-sm">
            <Loader2 className="w-7 h-7 text-sky-700 animate-spin" />
            <span className="font-mono text-xs">正在提取服务器数据源...</span>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="flex flex-col justify-center items-center h-full gap-4 text-slate-500 text-sm py-12">
            <div className="p-4 rounded-full bg-slate-100">
              <Package className="w-8 h-8 opacity-40 text-slate-400" strokeWidth={1.5} />
            </div>
            <div className="text-center">
              <p className="text-[13px] font-medium tracking-wide">
                {filterQuery ? '未找到匹配的文件' : '任务中暂无输出文件'}
              </p>
              <p className="text-[11px] font-mono text-slate-500 mt-1">
                {filterQuery ? 'NO MATCHING FILES' : 'NO OUTPUT FILES FOUND'}
              </p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col">
            {filteredItems.map((item, idx) => (
              <FileTreeItem key={idx} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
