import React, { useEffect, useRef, useState } from 'react';
import { Plus, Trash2, Upload, Download, Table2, SlidersHorizontal, Check, X } from 'lucide-react';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { extractDeductionColumns, validateDeductionRows, type DeductionRow } from '../lib/workbench';
import { DeductionStationPicker } from './DeductionStationPicker';
import { selectDeductionStation, type DeductionStation, type StationPlatform } from '../lib/deductionStations';

export const DeductionSettings = React.memo(function DeductionSettings({ batchId, apiFetch, onClose, onSaved, platform = 'fengshen' }: {
  batchId?: string; apiFetch: (url: string, init?: RequestInit) => Promise<Response>;
  onClose: () => void; onSaved: () => void; platform?: StationPlatform;
}) {
  const [scope, setScope] = useState<'default' | 'batch'>(batchId ? 'batch' : 'default');
  const [viewMode, setViewMode] = useState<'table' | 'detail'>('table');
  const [rows, setRows] = useState<DeductionRow[]>([]);
  const [version, setVersion] = useState('');
  const [frozen, setFrozen] = useState(false);
  const [index, setIndex] = useState(0);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [newColOpen, setNewColOpen] = useState(false);
  const [newColName, setNewColName] = useState('');
  const [confirmDeleteIdx, setConfirmDeleteIdx] = useState<number | null>(null);
  const [pendingAction, setPendingAction] = useState<{ type: 'close' } | { type: 'scope'; nextScope: 'default' | 'batch' } | null>(null);
  const [stationTarget,setStationTarget]=useState<{row:number|null}|null>(null);
  const [stationPlatform,setStationPlatform]=useState<StationPlatform>(platform);
  useEffect(()=>setStationPlatform(platform),[platform]);

  const upload = useRef<HTMLInputElement>(null);
  const url = scope === 'batch' ? `/api/workbench/batches/${batchId}/deductions` : '/api/workbench/deductions';

  useEffect(() => {
    const controller = new AbortController();
    setLoaded(false); setError(''); setMessage(''); setBusy(true); setPendingAction(null); setConfirmDeleteIdx(null);setStationTarget(null);
    void apiFetch(url, { signal: controller.signal }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '配置读取失败');
      setRows(validateDeductionRows(data.rows)); setVersion(data.version); setFrozen(!!data.frozen); setDirty(false); setIndex(0); setLoaded(true);
    }).catch(error => { if (!controller.signal.aborted) setError(String(error.message)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [url]);

  const requestClose = () => {
    if (!dirty) {
      onClose();
      return;
    }
    setPendingAction({ type: 'close' });
  };

  const requestScopeChange = (nextScope: 'default' | 'batch') => {
    if (nextScope === scope) return;
    if (!dirty) {
      setScope(nextScope);
      return;
    }
    setPendingAction({ type: 'scope', nextScope });
  };

  const confirmPendingAction = () => {
    if (!pendingAction) return;
    const action = pendingAction;
    setPendingAction(null);
    setDirty(false);
    if (action.type === 'close') onClose();
    else setScope(action.nextScope);
  };

  const updateRowField = (rowIndex: number, key: string, value: DeductionRow[string]) => {
    setRows(previous => previous.map((row, i) => i === rowIndex ? { ...row, [key]: value } : row));
    setDirty(true);
    setMessage('');
  };

  const update = (key: string, value: DeductionRow[string]) => {
    updateRowField(index, key, value);
  };

  const handleAddColumn = () => {
    const trimmed = newColName.trim();
    if (!trimmed) return;
    setRows(previous => previous.map((row, i) => {
      if (viewMode === 'table' || i === index) {
        return Object.hasOwn(row, trimmed) ? row : { ...row, [trimmed]: 0 };
      }
      return row;
    }));
    setDirty(true);
    setMessage('');
    setNewColName('');
    setNewColOpen(false);
  };

  const handleDeleteRow = (targetIdx: number) => {
    if (rows.length <= 1) return;
    setRows(previous => previous.filter((_, i) => i !== targetIdx));
    setIndex(prev => (prev >= targetIdx ? Math.max(0, prev - 1) : prev));
    setConfirmDeleteIdx(null);
    setDirty(true);
    setMessage('');
  };

  const save = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      validateDeductionRows(rows);
      const response = await apiFetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows, version }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '配置保存失败');
      setVersion(data.version); setDirty(false); setPendingAction(null);
      setMessage(scope === 'batch' ? '已保存，仅用于本批次。' : '默认配置已保存，原版本已备份。');
      onSaved();
    } catch (error) { setError(error instanceof Error ? error.message : '配置保存失败'); }
    finally { setBusy(false); }
  };

  const selected = rows[index];
  const { metaColumns, deductionColumns } = extractDeductionColumns(rows);
  const filteredRows = rows
    .map((row, i) => ({ row, i }))
    .filter(({ row }) => `${row['城市'] || ''} ${row['团队名称'] || ''} ${row['团队ID'] || ''}`.toLowerCase().includes(search.trim().toLowerCase()));
  const pickerRow=stationTarget?.row!=null?rows[stationTarget.row]:undefined;
  const addManualStation=()=>{
    if(frozen||busy)return;
    const defaultCols=Object.fromEntries(deductionColumns.map(col=>[col,0]));
    setRows(previous=>[...previous,{城市:'',团队名称:'',团队ID:'',...defaultCols}]);
    setIndex(rows.length);setSearch('');setDirty(true);setStationTarget(null);setMessage('');
  };
  const chooseStation=(station:DeductionStation)=>{
    if(frozen||busy)throw Error('本批次配置当前不可修改，请返回后检查状态。');
    if(!stationTarget)throw Error('请选择要维护的配置行。');
    const defaults=Object.fromEntries(deductionColumns.map(col=>[col,0]));
    const updated=selectDeductionStation(rows,stationTarget.row,station,defaults);
    setRows(updated);setIndex(stationTarget.row??rows.length);setSearch('');setDirty(true);setError('');
    setMessage(`已选 ${station.city} · ${station.name}，保存后生效。`);setStationTarget(null);
  };

  return (
    <WorkbenchDrawer title="站点扣款配置" wide onClose={requestClose}>
      <p className="wb-muted">默认配置用于后续核算；可按站点维护扣款，或为本次核算保存独立配置。</p>
      <div className="wb-row wb-space">
        <div className="wb-row gap-2">
          <div className="wb-segment" aria-label="配置作用范围">
            {(['default', 'batch'] as const).filter(value => value === 'default' || batchId).map(value => (
              <button
                key={value}
                type="button"
                aria-pressed={scope === value}
                disabled={busy}
                onClick={() => requestScopeChange(value)}
              >
                {value === 'default' ? '默认配置' : '仅本次核算'}
              </button>
            ))}
          </div>
          <div className="wb-segment" role="group" aria-label="扣款视图模式切换">
            <button
              type="button"
              aria-pressed={viewMode === 'table'}
              onClick={() => setViewMode('table')}
              className="inline-flex items-center gap-1.5"
            >
              <Table2 size={14} />表格总览
            </button>
            <button
              type="button"
              aria-pressed={viewMode === 'detail'}
              onClick={() => setViewMode('detail')}
              className="inline-flex items-center gap-1.5"
            >
              <SlidersHorizontal size={14} />单站维护
            </button>
          </div>
        </div>
        {loaded && <span className="wb-muted">{rows.length} 个站点 · {deductionColumns.length} 项扣款列 · 版本 {version.slice(0, 8)}</span>}
      </div>

      {pendingAction && (
        <div role="alert" className="wb-inline-confirm-bar">
          <span>当前有未保存的扣款调整，确认放弃修改吗？</span>
          <div className="wb-row gap-2">
            <button type="button" className="wb-button text-xs py-1 px-2.5 min-h-[30px]" onClick={() => setPendingAction(null)}>继续编辑</button>
            <button type="button" className="wb-primary text-xs py-1 px-3 min-h-[30px] bg-rose-600 border-rose-600 hover:bg-rose-700" onClick={confirmPendingAction}>放弃修改</button>
          </div>
        </div>
      )}

      {frozen && <p className="wb-notice">本批次已采用固定配置，此处只读。修改默认配置不会改变本次结果。</p>}
      {busy && !loaded && <p role="status">正在读取配置…</p>}
      {error && <p role="alert" className="wb-error">{error}</p>}
      {message && <p role="status" className="wb-success">{message}</p>}

      {loaded && (
        <>
          {(viewMode === 'table' || viewMode === 'detail') && (
            <>
              <div className="wb-row wb-space">
                <input
                  className="wb-input flex-1 max-w-xs"
                  aria-label="查找城市或站点"
                  placeholder="查找城市、站点名称或团队ID…"
                  value={search}
                  onChange={event => setSearch(event.target.value)}
                />
                <div className="wb-row gap-2">
                  {newColOpen ? (
                    <div className="wb-row gap-1.5">
                      <input
                        className="wb-input text-xs py-1.5 px-2.5 w-36"
                        aria-label="输入扣款项名称"
                        placeholder="新扣款项名称"
                        value={newColName}
                        onChange={event => setNewColName(event.target.value)}
                        onKeyDown={event => {
                          if (event.key === 'Enter') handleAddColumn();
                          if (event.key === 'Escape') { setNewColOpen(false); setNewColName(''); }
                        }}
                      />
                      <button type="button" className="wb-primary text-xs py-1 px-2.5 min-h-[32px]" disabled={!newColName.trim()} onClick={handleAddColumn}><Check size={14} />添加</button>
                      <button type="button" className="wb-button text-xs py-1 px-2 min-h-[32px]" onClick={() => { setNewColOpen(false); setNewColName(''); }}><X size={14} /></button>
                    </div>
                  ) : (
                    <button type="button" className="wb-button" disabled={frozen || busy} onClick={() => setNewColOpen(true)}>
                      <Plus size={15} />添加扣款项
                    </button>
                  )}
                  <button
                    type="button"
                    className="wb-primary"
                    disabled={frozen || busy}
                    onClick={() => setStationTarget({row:null})}
                  >
                    <Plus size={15} />从平台新增站点
                  </button>
                  <button type="button" className="wb-button" disabled={frozen||busy} onClick={addManualStation}>手动新增</button>
                </div>
              </div>

              {viewMode === 'table' ? (
                <div className="wb-deduction-table-wrap" role="region" aria-label="多站点扣款横向对比表">
                  <table className="wb-deduction-table">
                    <thead>
                      <tr>
                        {metaColumns.map(col => (
                          <th key={col} className="is-sticky-col">{col}</th>
                        ))}
                        {deductionColumns.map(col => (
                          <th key={col}>{col}</th>
                        ))}
                        <th className="w-24 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRows.length === 0 ? (
                        <tr>
                          <td colSpan={metaColumns.length + deductionColumns.length + 1} className="wb-empty">
                            没有匹配的站点记录
                          </td>
                        </tr>
                      ) : (
                        filteredRows.map(({ row, i }) => (
                          <tr key={i} className={index === i ? 'is-selected-row' : ''} onClick={() => setIndex(i)}>
                            {metaColumns.map(col => (
                              <td key={col} className="is-sticky-col">
                                {col==='团队名称'?<div className="wb-station-field"><input
                                  className="wb-table-cell-input is-meta"
                                  aria-label={`${row['团队名称']||`站点${i+1}`} ${col}`}
                                  value={String(row[col]??'')} placeholder={col} disabled={frozen||busy}
                                  onChange={event=>updateRowField(i,col,event.target.value)}/>
                                  <button type="button" className="wb-link" disabled={frozen||busy} aria-label={`从平台选择站点 ${row['团队名称']||i+1}`} onClick={event=>{event.stopPropagation();setStationTarget({row:i});}}>从平台选择</button>
                                </div>:<input
                                  className="wb-table-cell-input is-meta"
                                  aria-label={`${row['团队名称'] || `站点${i + 1}`} ${col}`}
                                  value={String(row[col] ?? '')}
                                  placeholder={col}
                                  disabled={frozen || busy}
                                  onChange={event => updateRowField(i, col, event.target.value)}
                                />}
                              </td>
                            ))}
                            {deductionColumns.map(col => {
                              const val = row[col];
                              if (typeof val === 'boolean') {
                                return (
                                  <td key={col} className="text-center">
                                    <input
                                      type="checkbox"
                                      aria-label={`${row['团队名称'] || `站点${i + 1}`} ${col}`}
                                      checked={val}
                                      disabled={frozen || busy}
                                      onChange={event => updateRowField(i, col, event.target.checked)}
                                    />
                                  </td>
                                );
                              }
                              const isNumeric = typeof val === 'number' || val === undefined || val === null || val === '';
                              return (
                                <td key={col}>
                                  <input
                                    className="wb-table-cell-input font-mono"
                                    aria-label={`${row['团队名称'] || `站点${i + 1}`} ${col}`}
                                    type={isNumeric ? 'number' : 'text'}
                                    step="any"
                                    value={val ?? ''}
                                    disabled={frozen || busy}
                                    onChange={event => {
                                      const raw = event.target.value;
                                      updateRowField(i, col, isNumeric ? (raw === '' ? '' : Number(raw)) : raw);
                                    }}
                                  />
                                </td>
                              );
                            })}
                            <td className="text-right whitespace-nowrap">
                              {confirmDeleteIdx === i ? (
                                <span className="inline-flex items-center gap-1">
                                  <button type="button" className="text-xs text-rose-600 font-semibold px-1" onClick={e => { e.stopPropagation(); handleDeleteRow(i); }}>确认</button>
                                  <button type="button" className="text-xs text-slate-500 px-1" onClick={e => { e.stopPropagation(); setConfirmDeleteIdx(null); }}>取消</button>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    className="wb-link text-xs"
                                    onClick={e => { e.stopPropagation(); setIndex(i); setViewMode('detail'); }}
                                  >
                                    详情
                                  </button>
                                  <button
                                    type="button"
                                    className="wb-icon text-slate-400 hover:text-rose-600"
                                    aria-label={`删除站点 ${row['团队名称'] || i + 1}`}
                                    disabled={frozen || busy || rows.length <= 1}
                                    onClick={e => { e.stopPropagation(); setConfirmDeleteIdx(i); }}
                                  >
                                    <Trash2 size={14} />
                                  </button>
                                </span>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="wb-settings-grid">
                  <div className="wb-site-list">
                    {filteredRows.map(({ row, i }) => (
                      <button key={i} type="button" className={index === i ? 'selected' : ''} onClick={() => setIndex(i)}>
                        <small>{row['城市'] || '未填城市'}</small>
                        <span>{row['团队名称'] || '新站点'}</span>
                      </button>
                    ))}
                  </div>
                  {selected && (
                    <div className="wb-fields">
                      <div className="wb-row wb-space">
                        <h3>站点与扣款项</h3>
                        {confirmDeleteIdx === index ? (
                          <div className="wb-row gap-1.5">
                            <span className="text-xs text-rose-700">确认移除此站点？</span>
                            <button type="button" className="wb-button text-xs text-rose-700 border-rose-300 py-1 px-2 min-h-[28px]" onClick={() => handleDeleteRow(index)}>确认移除</button>
                            <button type="button" className="wb-button text-xs py-1 px-2 min-h-[28px]" onClick={() => setConfirmDeleteIdx(null)}>取消</button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="wb-icon"
                            aria-label="删除当前站点"
                            disabled={frozen || busy || rows.length <= 1}
                            onClick={() => setConfirmDeleteIdx(index)}
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                      {Object.entries(selected).map(([key, value]) => key==='团队名称'?(
                        <div key={key} className="wb-station-detail-field"><label><span>团队名称</span><input className="wb-input" aria-label="当前站点团队名称" value={String(value??'')} disabled={frozen||busy} onChange={event=>update(key,event.target.value)}/></label><button type="button" className="wb-button" disabled={frozen||busy} onClick={()=>setStationTarget({row:index})}>从平台选择</button></div>
                      ):(
                        <label key={key}>
                          <span>{key}</span>
                          {typeof value === 'boolean' ? (
                            <input
                              type="checkbox"
                              checked={value}
                              disabled={frozen || busy}
                              onChange={event => update(key, event.target.checked)}
                            />
                          ) : (
                            <input
                              className="wb-input"
                              value={value ?? ''}
                              disabled={frozen || busy}
                              type={typeof value === 'number' ? 'number' : 'text'}
                              step="any"
                              onChange={event =>
                                update(
                                  key,
                                  typeof value === 'number'
                                    ? event.target.value === ''
                                      ? ''
                                      : Number(event.target.value)
                                    : event.target.value,
                                )
                              }
                            />
                          )}
                        </label>
                      ))}
                      <p className="wb-muted">名称、团队 ID 及扩展字段按原配置保存。删除某项请清空其值，或通过配置文件导入调整。</p>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          <input
            ref={upload}
            type="file"
            accept=".json,.xlsx,.xls"
            className="hidden"
            aria-label="导入扣款配置"
            onChange={async event => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (!file) return;
              try {
                let imported: unknown;
                if (/\.json$/i.test(file.name)) imported = JSON.parse(await file.text());
                else {
                  const XLSX = await import('xlsx');
                  const book = XLSX.read(await file.arrayBuffer(), { type: 'array' });
                  const sheet = book.Sheets[book.SheetNames[0]];
                  const raw = XLSX.utils.sheet_to_json<DeductionRow>(sheet, { defval: null });
                  const formatted = XLSX.utils.sheet_to_json<DeductionRow>(sheet, { raw: false, defval: null });
                  imported = raw.map((row, idx) => ({ ...row, ...('团队ID' in row ? { 团队ID: String(formatted[idx]['团队ID'] ?? '') } : {}) }));
                }
                setRows(validateDeductionRows(imported));
                setIndex(0);
                setDirty(true);
                setError('');
              } catch (error) {
                setError(error instanceof Error ? error.message : '配置文件无效');
              }
            }}
          />
          <footer className="wb-row wb-space wb-settings-footer">
            <div className="wb-row">
              <button type="button" className="wb-button" disabled={frozen || busy} onClick={() => upload.current?.click()}><Upload size={15} />导入配置</button>
              <button
                type="button"
                className="wb-button"
                onClick={async () => {
                  const XLSX = await import('xlsx');
                  const book = XLSX.utils.book_new();
                  XLSX.utils.book_append_sheet(book, XLSX.utils.json_to_sheet(rows), '扣款配置');
                  XLSX.writeFile(book, '扣款配置.xlsx');
                }}
              >
                <Download size={15} />导出 Excel
              </button>
              <button
                type="button"
                className="wb-button"
                onClick={() => {
                  const blobUrl = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' }));
                  const link = document.createElement('a');
                  link.href = blobUrl;
                  link.download = '扣款配置.json';
                  link.click();
                  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
                }}
              >
                <Download size={15} />导出 JSON
              </button>
            </div>
            <button type="button" className="wb-primary" disabled={frozen || busy || !dirty} onClick={() => void save()}>
              {busy ? '保存中…' : scope === 'batch' ? '保存本批次扣款' : '保存为后续核算默认扣款'}
            </button>
          </footer>
        </>
      )}
      {stationTarget&&<DeductionStationPicker apiFetch={apiFetch} platform={stationPlatform} onPlatformChange={setStationPlatform}
        current={pickerRow?{city:String(pickerRow['城市']??''),name:String(pickerRow['团队名称']??''),id:String(pickerRow['团队ID']??'')}:undefined}
        disabled={frozen||busy} onSelect={chooseStation} onClose={()=>setStationTarget(null)}
        onManual={()=>{if(stationTarget.row===null)addManualStation();else{setIndex(stationTarget.row);setViewMode('detail');setStationTarget(null);}}}/>}
    </WorkbenchDrawer>
  );
});
