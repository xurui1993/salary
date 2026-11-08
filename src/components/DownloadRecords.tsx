import { taskGuidance, taskHandoffs } from '../lib/taskGuidance';
import { TaskOutcome } from './TaskOutcome';
import React, { useEffect, useRef, useState } from 'react';
import { Download, FolderOpen, RefreshCw, Search, ChevronDown, Archive } from 'lucide-react';
import { readDownloadResponse, saveDownloadBlob, downloadErrorMessage } from '../lib/outputDownload';
import { datasetGroup, isGlobalDataset, type DownloadFetch } from '../lib/downloadCenterLogic';
import type { RecordModule } from '../lib/downloadModules';
import { WorkbenchDrawer } from './WorkbenchDrawer';
import { WorkbenchDatePicker } from './WorkbenchDatePicker';

interface File { id:string; run_id:string; name:string; city:string; bytes:number; available:boolean; unavailable_reason?:string }
interface Task {
  id:string; kind:string; title?:string; price_id?:string; batch_id?:string; output?:string;
  cities:string[]; datasets:string[]; start:string; end:string; status:string; created_at:string;
  files:File[]; source_files?:File[]; available_files:number; failed_items:number; completed_items:number; total_items:number;
  member_ids:string[]; attempts:{id:string;status:string}[]; action_run_id:string; summary_issue?:boolean;
}
const API='/api/workbench/task-center';
const ACTIVE=new Set(['queued','running','waiting_login','waiting_manual','cancelling','preparing','stopping']);
const ENDED=new Set(['success','partial','error','cancelled','interrupted']);
const statusLabel=(status:string)=>taskGuidance({status}).label;
const KINDS:Record<string,string>={download:'资料下载',generate:'业务报表',payroll:'薪资核算',approval:'价格审批','price-export':'每日价格'};
const SYSTEMS:Record<string,string>={fengshen:'风神',lanorange:'蓝橙',baize:'商翼',xiaoxiang:'灯塔'};
const stamp=(v:string)=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
const size=(n:number)=>n>=1048576?`${(n/1048576).toFixed(1)} MB`:`${Math.max(1,Math.ceil(n/1024))} KB`;

export function DownloadRecords({apiFetch,workspaceId,selectedRunId,onOpenAttempt,execution,datasetLabel,refreshVersion=0,recordModule,onOpenPayroll,onNavigateGenerate,onNavigatePayroll,onOpenPrice,initialRunId,onInitialFocusHandled}:{
  initialRunId?:string; onInitialFocusHandled?:()=>void;
  apiFetch:DownloadFetch; workspaceId:string; selectedRunId:string; onOpenAttempt:(id:string)=>void; execution:React.ReactNode;
  datasetLabel:(id:string)=>string; refreshVersion?:number; unified?:boolean; recordModule?:RecordModule; onOpenPayroll?:(id:string)=>void;
  onNavigateGenerate?:(cities:string[],start:string,end:string)=>void; onNavigatePayroll?:(city?:string)=>void; onOpenPrice?:(view:'approval'|'price-export',id?:string)=>void;
}) {
  const api=useRef(apiFetch);api.current=apiFetch;
  const [records,setRecords]=useState<Task[]>([]),[total,setTotal]=useState(0),[page,setPage]=useState(1),[pages,setPages]=useState(1);
  const [counts,setCounts]=useState<Record<string,number>>({}),[search,setSearch]=useState(''),[query,setQuery]=useState('');
  const [status,setStatus]=useState(''),[system,setSystem]=useState(''),[kind,setKind]=useState('');
  const [from,setFrom]=useState(''),[to,setTo]=useState(''),[archived,setArchived]=useState(false);
  const [selected,setSelected]=useState<string[]>([]),[focused,setFocused]=useState<Task|null>(null),[filesOpen,setFilesOpen]=useState('');
  const [version,setVersion]=useState(0),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[pollError,setPollError]=useState('');
  const [confirm,setConfirm]=useState<Task[]|null>(null);
  const [directory,setDirectory]=useState<{path:string;exists:boolean;can_open:boolean;record_id?:string}|null>(null);
  const busyRef=useRef(false),focusRef=useRef<Task|null>(null),selectedRef=useRef<string[]>([]);
  focusRef.current=focused;selectedRef.current=selected;
  const reset=()=>{setPage(1);setSelected([]);setFilesOpen('');};
  useEffect(()=>{const timer=setTimeout(()=>{setQuery(search);reset();},300);return()=>clearTimeout(timer);},[search]);
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try {
        const params=new URLSearchParams({page:String(page),q:query,status,system,kind,from,to,archived:archived?'1':'0',module:recordModule||'',focus:focusRef.current?.id||''});
        const response=await api.current(`${API}?${params}`,{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)])});
        const data=await response.json();if(!response.ok)throw new Error(data.detail||'任务列表暂不可读');
        if(controller.signal.aborted)return;
        setRecords(previous=>selectedRef.current.length?previous.map(r=>data.records.find((next:Task)=>next.id===r.id)||r):data.records);setTotal(data.total);setPages(data.pages);setPage(data.page);setCounts(data.counts);setLoading(false);setPollError((data.warnings||[]).join('；'));
        setFocused(previous=>previous?(data.focused?.id===previous.id?data.focused:data.records.find((r:Task)=>r.id===previous.id)||previous):null);
      }catch(e){if(!controller.signal.aborted){setPollError(downloadErrorMessage(e));setLoading(false);}}
      if(!controller.signal.aborted)timer=setTimeout(poll,5000);
    };setLoading(true);void poll();return()=>{controller.abort();clearTimeout(timer);};
  },[page,query,status,system,kind,from,to,archived,recordModule,version,refreshVersion]);
  useEffect(()=>{
    if(!initialRunId)return;
    const record=records.find(r=>r.member_ids.includes(initialRunId)||r.action_run_id===initialRunId);
    if(record){setFocused(record);onInitialFocusHandled?.();}
  },[initialRunId,records,onInitialFocusHandled]);
  const title=(r:Task)=>r.title||(r.kind==='payroll'?'兼职薪资核算':r.datasets.map(datasetLabel).join('、').replaceAll('（生成表）',''));
  const platform=(r:Task)=>r.price_id?'蓝橙':r.kind==='payroll'?'风神 / 蓝橙':[...new Set(r.datasets.map(id=>SYSTEMS[datasetGroup(id)]))].join(' / ');
  const scope=(r:Task)=>!r.datasets.length?'详见业务记录':r.datasets.every(isGlobalDataset)?'全量':r.datasets.every(id=>id==='rider_archive')?'当前快照':`${r.start} 至 ${r.end}`;
  const open=(r:Task)=>{setFocused(r);if(r.action_run_id){onOpenAttempt(r.action_run_id);}};
  const request=async(url:string,payload?:unknown)=>{
    const response=await api.current(url,payload===undefined?{signal:AbortSignal.timeout(120000)}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(120000)});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||'操作未完成，请重试');}return response;
  };
  const act=async(work:()=>Promise<void>)=>{
    if(busyRef.current)return;busyRef.current=true;setBusy(true);setError('');setNotice('');
    try{await work();}catch(e){setError(downloadErrorMessage(e));}finally{busyRef.current=false;setBusy(false);}
  };
  const download=(r:Task,file?:File,sources=false)=>act(async()=>{
    let url:string,filename:string;
    if(r.kind==='payroll'){url=`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(r.batch_id||'')}`;filename='薪资核算结果.zip';}
    else if(r.kind==='approval'){url=`/api/fengshen-downloads/lanorange-approvals/batches/${r.price_id}/result.csv`;filename='蓝橙价格审批回执.csv';}
    else if(r.kind==='price-export'){url=`/api/fengshen-downloads/lanorange-prices/exports/${r.price_id}/result.xlsx`;filename='蓝橙待审每日价格.xlsx';}
    else{url=file?`/api/fengshen-downloads/runs/${file.run_id}/files/${file.id}`:`/api/fengshen-downloads/records/${r.id}/bundle${sources?'?purpose=sources':''}`;filename=file?.name||`${sources?'来源':'结果'}_${r.id.slice(0,8)}.zip`;}
    const response=await request(url);
    const disposition=response.headers.get('content-disposition')||'';
    const encoded=/filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    if(encoded){try{const actual=decodeURIComponent(encoded);if(actual&&!/[\\/\x00-\x1f]/.test(actual))filename=actual;}catch{}}
    saveDownloadBlob(await readDownloadResponse(response,filename),filename);setNotice('已发起文件保存，请在浏览器下载记录中确认。');
  });
  const downloadResult=(r:Task)=>{const files=r.files.filter(f=>f.available);void download(r,files.length===1?files[0]:undefined);};
  const showDirectory=(r?:Task)=>act(async()=>{const response=await request(`${API}/directory${r?`?record_id=${encodeURIComponent(r.id)}`:''}`);const info=await response.json();setDirectory({...info,record_id:r?.id});if(info.exists&&info.can_open)await request(`${API}/directory/open`,{record_id:r?.id});});
  const changeVisibility=(rows:Task[])=>act(async()=>{
    await request(`${API}/visibility`,{ids:rows.map(r=>r.id),restore:archived,stop_first:true});setConfirm(null);setSelected([]);setFocused(null);setVersion(v=>v+1);
    setNotice(archived?`已恢复 ${rows.length} 个任务，所有同事同步可见。`:'已提交移出请求，进行中任务确认停止后移出。文件保留，可在“已移出”恢复。');
  });
  const chosen=records.filter(r=>selected.includes(r.id));
  const canBatch=chosen.length>0&&chosen.length<=20&&chosen.every(r=>['download','generate','payroll_source'].includes(r.kind)&&r.available_files>0);
  const context=(r:Task)=>({status:r.status,kind:r.kind,availableFiles:r.available_files,failedItems:r.failed_items,summaryIssue:r.summary_issue});
  const needsAction=(r:Task)=>taskGuidance(context(r)).needsAction;
  const actionLabel=(r:Task)=>taskGuidance(context(r)).action;
  const files=(r:Task,list:File[])=> <ul className="tc-files">{list.map(f=><li key={`${f.run_id}:${f.id}`}><div><span>{f.name}</span><small>{f.city} · {f.available?size(f.bytes):f.unavailable_reason||'文件不可用'}</small></div><button className="wb-button" disabled={busy||!f.available} onClick={()=>void download(r,f)}><Download size={14}/>下载</button></li>)}</ul>;
  const openPayroll=(r:Task)=>{setFocused(null);onOpenPayroll?.(r.batch_id!);};
  const openPrice=(r:Task)=>{setFocused(null);onOpenPrice?.(r.kind as 'approval'|'price-export',r.price_id);};
  const mainAction=(r:Task)=>r.kind==='payroll'?openPayroll(r):r.price_id?openPrice(r):open(r);
  const handoffs=focused?taskHandoffs(focused.kind,focused.datasets,focused.cities):null;
  return <section className="tc-center" aria-label="任务中心列表">
    <div className="tc-toolbar">
      <div className="wb-quick-filters" role="group" aria-label="任务状态">{[['','全部','all'],['active','进行中','active'],['attention','待处理','attention'],['success','已完成','success']].map(([key,label,count])=><button key={key} aria-pressed={status===key} onClick={()=>{setStatus(key);reset();}}>{label}<span className="tc-count">{counts[count]||0}</span></button>)}</div>
      <div className="tc-detail-actions">
        {!archived&&<button className="wb-button" disabled={busy} onClick={()=>void act(async()=>{const params=new URLSearchParams({q:query,system,kind,from,to,module:recordModule||''});const response=await request(`${API}/organize-preview?${params}`);const data=await response.json();if(data.records.length)setConfirm(data.records);else setNotice('当前筛选范围内没有可整理的已完成任务。');})}>整理已完成</button>}
        <button className="wb-button" disabled={busy} onClick={()=>void showDirectory()}><FolderOpen size={16}/>打开生成根目录</button>
        <button className={`wb-button ${archived?'tc-archive-active':''}`} onClick={()=>{setArchived(!archived);reset();}}><Archive size={15}/>{archived?'返回任务列表':'已移出'}</button>
      </div>
    </div>
    <div className="tc-searchbar"><label className="tc-search"><Search size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索任务、城市、文件名或编号" aria-label="搜索任务"/></label>
      {!recordModule&&<><select className="wb-select" aria-label="筛选平台" value={system} onChange={e=>{setSystem(e.target.value);reset();}}><option value="">全部平台</option>{Object.entries(SYSTEMS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><select className="wb-select" aria-label="筛选任务类型" value={kind} onChange={e=>{setKind(e.target.value);reset();}}><option value="">全部类型</option>{Object.entries(KINDS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></>}
      <details className="tc-filters"><summary className="wb-button">日期筛选{from||to?' · 已启用':''}</summary><div><div className="tc-filter-date-item"><span>创建日期从</span><WorkbenchDatePicker ariaLabel="创建日期从" value={from} rangeRole="start" rangeStart={from} rangeEnd={to} allowClear align="right" onChange={v=>{setFrom(v);reset();}}/></div><div className="tc-filter-date-item"><span>至</span><WorkbenchDatePicker ariaLabel="创建日期至" value={to} rangeRole="end" rangeStart={from} rangeEnd={to} allowClear align="right" onChange={v=>{setTo(v);reset();}}/></div><button className="wb-link" onClick={()=>{setFrom('');setTo('');reset();}}>清除日期</button></div></details><button className="wb-icon" aria-label="刷新任务列表" onClick={()=>setVersion(v=>v+1)}><RefreshCw size={17}/></button></div>
    {archived&&<p className="tc-info">已移出的任务仍保留文件和处理记录，恢复后所有同事同步可见。</p>}
    {pollError&&<p role="status" className="wb-notice">{pollError}；正在自动重试，现有记录保留。</p>}{error&&<p role="alert" className="wb-error">{error}</p>}{notice&&<p role="status" className="tc-info">{notice}</p>}
    {!!selected.length&&<div className="tc-batchbar"><strong>已选 {selected.length} 项（当前页）</strong><button className="wb-button" disabled={busy||!canBatch} title="最多20个有文件的资料或报表任务" onClick={()=>void act(async()=>{const response=await request(`${API}/bundle`,{ids:selected});saveDownloadBlob(await readDownloadResponse(response,'批量任务结果.zip'),'批量任务结果.zip');setNotice('已发起批量文件保存。');})}><Download size={15}/>批量下载</button><button className="wb-button" disabled={busy||!chosen.length} onClick={()=>setConfirm(chosen)}>{archived?'恢复显示':'移出列表'}</button><button className="wb-link" onClick={()=>setSelected([])}>取消选择</button></div>}
    <div className="tc-table-scroll"><table className="tc-table"><thead><tr><th><input type="checkbox" aria-label="选择当前页任务" checked={records.length>0&&records.every(r=>selected.includes(r.id))} onChange={e=>setSelected(e.target.checked?records.map(r=>r.id):[])}/></th><th>任务内容</th><th>范围 / 账期</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead><tbody>{records.map(r=><React.Fragment key={r.id}><tr data-task-ids={r.member_ids.join(' ')}><td><input type="checkbox" aria-label={`选择${title(r)}`} checked={selected.includes(r.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,r.id]:v.filter(id=>id!==r.id))}/></td><td className="tc-title"><button onClick={()=>open(r)} title={title(r)}>{title(r)}</button><small>{platform(r)} · {KINDS[r.kind]||'资料下载'} · {r.id.slice(-6).toUpperCase()}</small></td><td className="tc-scope"><span title={r.cities.join('、')}>{r.cities.length>2?`${r.cities.slice(0,2).join('、')}等${r.cities.length}城`:r.cities.join('、')}</span><small>{scope(r)}</small></td><td className="tc-time">{stamp(r.created_at)}</td><td><span className={`tc-status is-${r.status}`}>{taskGuidance(context(r)).label}</span><small>{r.files.length&&!r.available_files?'文件不可用':r.available_files?`${r.available_files} 个文件`:ACTIVE.has(r.status)?`${r.completed_items}/${r.total_items} 项`:''}</small></td><td><div className="tc-actions">{needsAction(r)?<button className="wb-primary" onClick={()=>mainAction(r)}>{actionLabel(r)}</button>:r.available_files>0?<button className="wb-primary" disabled={busy} onClick={()=>downloadResult(r)}>下载结果</button>:null}{r.files.length>1&&<button className="wb-link" aria-expanded={filesOpen===r.id} onClick={()=>setFilesOpen(filesOpen===r.id?'':r.id)}>文件<ChevronDown size={13}/></button>}<button className="wb-link" onClick={()=>open(r)}>详情</button>{!archived&&ACTIVE.has(r.status)&&<button className="wb-link" disabled={busy||['stopping','cancelling'].includes(r.status)} onClick={()=>void act(async()=>{await request(`${API}/stop`,{id:r.id});setVersion(v=>v+1);setNotice('已请求停止，确认停止前任务保留在列表。');})}>停止</button>}<button className="wb-link" disabled={busy} onClick={()=>setConfirm([r])}>{archived?'恢复':ACTIVE.has(r.status)?'停止并移出':'移出'}</button></div></td></tr>{filesOpen===r.id&&<tr className="tc-file-row"><td/><td colSpan={5}>{r.failed_items>0&&<p className="wb-notice">另有 {r.failed_items} 项未完成，已有文件可先领取。</p>}{files(r,r.files)}</td></tr>}</React.Fragment>)}</tbody></table></div>
    {!records.length&&<div className="tc-empty">{loading?'正在读取任务…':pollError?'暂时无法读取，请刷新重试。':archived?'暂无已移出的任务。':'没有符合条件的任务。'}</div>}
    <footer className="tc-pagination"><span>共 {total} 条 · 每页 20 条</span><div><button className="wb-button" disabled={page<=1||loading} onClick={()=>{setPage(p=>p-1);setSelected([]);}}>上一页</button><span>{page} / {pages}</span><button className="wb-button" disabled={page>=pages||loading} onClick={()=>{setPage(p=>p+1);setSelected([]);}}>下一页</button></div></footer>
    {focused&&<WorkbenchDrawer title="任务详情" wide onClose={()=>setFocused(null)} bodyClassName="tc-detail"><div className="tc-detail-title"><h3>{title(focused)}</h3><span className={`tc-status is-${focused.status}`}>{statusLabel(focused.status)}</span></div><p className="wb-muted">{platform(focused)} · {focused.cities.join('、')} · {scope(focused)}</p><p className="wb-muted">{stamp(focused.created_at)} · 编号 {focused.id.slice(-8).toUpperCase()}</p>
      <TaskOutcome task={context(focused)}/>
      <div className="tc-detail-actions">{focused.available_files>0&&<button className="wb-primary" disabled={busy} onClick={()=>downloadResult(focused)}>下载结果</button>}{<button className="wb-button" disabled={busy} onClick={()=>void showDirectory(focused)}><FolderOpen size={15}/>打开任务目录</button>}{true&&<button className="wb-button" disabled={busy} onClick={()=>setConfirm([focused])}>{archived?'恢复显示':ACTIVE.has(focused.status)?'停止并移出':'移出列表'}</button>}</div>
      {error&&<p role="alert" className="wb-error">{error}</p>}
      {!!focused.files.length&&<section><h4>结果文件（{focused.available_files} 个可用）</h4>{focused.failed_items>0&&<p className="wb-notice">部分资料未完成，已生成文件可先领取；压缩包内附缺失说明。</p>}{files(focused,focused.files)}</section>}
      {focused.kind==='payroll'&&<button className="wb-button" onClick={()=>openPayroll(focused)}>打开核算批次</button>}{focused.price_id&&<button className="wb-button" onClick={()=>openPrice(focused)}>查看{focused.kind==='approval'?'审批':'价格导出'}记录</button>}
      {['download','generate','payroll_source'].includes(focused.kind)&&ENDED.has(focused.status)&&<details><summary>复核资料</summary><p className="wb-muted">领取来源原件，文件平铺并附来源清单；相同原件只保留一份。</p><button className="wb-button" disabled={busy} onClick={()=>void download(focused,undefined,true)}>下载复核资料包</button>{!!focused.source_files?.length&&<details><summary>关联资料（{focused.source_files.length}）</summary>{files(focused,focused.source_files)}</details>}</details>}
      {focused.action_run_id&&<details key={focused.id} open={needsAction(focused)} className="tc-execution"><summary>{needsAction(focused)?'进度与异常处理':'处理记录与核验信息'}</summary><div className="tc-attempts">{focused.attempts.length>1&&focused.attempts.map((a,i)=><button key={a.id} className="wb-button" aria-pressed={selectedRunId===a.id} onClick={()=>{onOpenAttempt(a.id);}}>{i?'后续处理':'首次下载'} · {statusLabel(a.status)}</button>)}</div>{focused.member_ids.includes(selectedRunId)?execution:<button className="wb-link" onClick={()=>open(focused)}>加载处理记录</button>}</details>}
      {focused.status==='success'&&handoffs&&(handoffs.generate||handoffs.payroll)&&<section className="wb-handoff"><h4>接下来要做什么？</h4><p>带入可用城市与日期，目标模块会再次检查所需资料。</p><div className="wb-handoff-actions">{handoffs.generate&&onNavigateGenerate&&<button className="wb-button" onClick={()=>{setFocused(null);onNavigateGenerate(handoffs.cities,focused.start,focused.end);}}>生成专项报表</button>}{handoffs.payroll&&onNavigatePayroll&&<button className="wb-button" onClick={()=>{setFocused(null);onNavigatePayroll(handoffs.cities[0]);}}>准备薪资核算</button>}</div></section>}
    </WorkbenchDrawer>}
    {directory&&<WorkbenchDrawer title="生成文件目录" onClose={()=>setDirectory(null)}><p className="wb-muted">这是运行本系统的电脑上的目录，浏览器下载位置由浏览器设置决定。</p><label className="tc-path">{directory.record_id?'本次任务目录':'生成根目录'}<textarea readOnly value={directory.path} onFocus={e=>e.target.select()}/></label>{!directory.exists&&<p className="wb-notice">目录尚未生成或已被移动。</p>}<div className="tc-detail-actions"><button className="wb-primary" disabled={busy||!directory.exists||!directory.can_open} onClick={()=>void act(async()=>{await request(`${API}/directory/open`,{record_id:directory.record_id});setNotice('已打开资源管理器。');})}><FolderOpen size={16}/>打开文件夹</button><button className="wb-button" onClick={()=>void act(async()=>{await navigator.clipboard.writeText(directory.path);setNotice('目录路径已复制。');})}>复制路径</button></div>{!directory.can_open&&<p className="wb-muted">远程访问请下载文件，或使用管理员提供的共享路径。</p>}{error&&<p className="wb-error" role="alert">{error}</p>}<details><summary>新任务目录结构</summary><pre className="tc-tree">{'任务名称_生成时间_编号 /\n  汇总报表.xlsx\n  城市_报表.xlsx\n  文件清单.csv\n\n成品直接平铺；原始资料单独保留，需要时领取复核资料包。'}</pre></details></WorkbenchDrawer>}
    {confirm&&<WorkbenchDrawer title={archived?'恢复任务显示':'移出任务列表'} onClose={()=>setConfirm(null)}><p>将{archived?'恢复':'移出'} {confirm.length} 个任务，对共享工作台所有同事生效。</p><p className="wb-muted">进行中的任务确认停止后移出。文件、处理记录和业务资料均保留。{archived?'':'之后可在“已移出”中恢复。'}</p><ul className="tc-confirm-list">{confirm.slice(0,30).map(r=><li key={r.id}>{title(r)} · {r.id.slice(-6).toUpperCase()}</li>)}</ul>{error&&<p className="wb-error" role="alert">{error}</p>}<div className="tc-detail-actions"><button className="wb-button" onClick={()=>setConfirm(null)}>取消</button><button className="wb-primary" disabled={busy} onClick={()=>void changeVisibility(confirm)}>{busy?'处理中…':archived?'确认恢复':'确认移出，保留文件'}</button></div></WorkbenchDrawer>}
  </section>;
}
