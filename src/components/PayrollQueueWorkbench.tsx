import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {FileSpreadsheet, Download, Square, FolderOpen, ChevronDown, ArchiveRestore, X, Loader2, Check, Pencil, Sparkles, FolderKanban, SlidersHorizontal, Search, ShieldAlert} from 'lucide-react';
import type {CorePageProps} from './CorePage';
import {ControlPanel} from './ControlPanel';
import {PayrollReviewSummary} from './PayrollReviewSummary';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {toneClass} from '../lib/statusSemantics';
import {SystemTemplatesPanel} from './SystemTemplatesPanel';
import {readDownloadResponse,saveDownloadBlob} from '../lib/outputDownload';
import {businessLogEntries} from '../lib/payrollBusinessLogs';
import {legacyPayrollTask,payrollElapsed,payrollModeName,payrollQueueRunning,payrollQueueStatus,type PayrollQueueTask} from '../lib/payrollQueue';
import {paginateEntries} from '../lib/deductionCategories';
import {filterPayrollQueueTasks,type PayrollQueueFilterTab} from '../lib/workbenchFilters';

type Props=Pick<CorePageProps,'config'|'onConfigChange'|'progress'|'progressText'|'logs'|'payrollPreparation'|'apiFetch'|'onPreparationChange'|'onUploadFiles'|'onRun'|'onOpenConnections'|'onOpenFengshenLogin'|'onOpenDeductions'|'onOpenSettings'|'uploadExtracted'>&{isRunning:boolean;onOtherMode:(mode:'fengshen'|'manual'|'xiaoxiang')=>void};
const API='/api/parttime/queue';

const PAYROLL_WORKBENCH_MODES = [
  {
    key: 'fengshen' as const,
    title: '自动核算',
    hint: '上传申请表自动齐套风神/蓝橙云端源表',
    icon: Sparkles,
  },
  {
    key: 'manual' as const,
    title: '手动上传',
    hint: '上传含申请表与本地补充源表的资料目录',
    icon: FolderKanban,
  },
] as const;

function payrollPeriod(value:string){
  const match=/^(\d{4})-(\d{2})-(\d{2})/.exec(value||'');
  return match?`${match[2]}.${match[3]}`:value||'';
}
function payrollScope(plan?:PayrollQueueTask['plan']){
  if(!plan)return '';
  const start=payrollPeriod(plan.start),end=payrollPeriod(plan.end);
  const period=start&&end?`${start}-${end}`:start||end;
  return [period,plan.cycle].filter(Boolean).join(' · ');
}
function taskLabel(task:PayrollQueueTask){
  return (task.approval_code||'').trim()||'未填写审批编号的任务';
}
function ApprovalCell({task,onSave}:{task:PayrollQueueTask;onSave:(task:PayrollQueueTask,code:string)=>Promise<void>}){
  const [editing,setEditing]=useState(false),[draft,setDraft]=useState(task.approval_code||''),[saving,setSaving]=useState(false);
  useEffect(()=>{if(!editing)setDraft(task.approval_code||'');},[task.approval_code,editing]);
  const code=(task.approval_code||'').trim();
  const cancel=()=>{setDraft(task.approval_code||'');setEditing(false);};
  const commit=async()=>{
    const next=draft.trim();
    if(next===code){setEditing(false);return;}
    setSaving(true);
    try{await onSave(task,next);setEditing(false);}
    catch{/* Keep the editor open so the number can be corrected. */}
    finally{setSaving(false);}
  };
  if(task.legacy)return <span className={`pq-approval-value${code?'':' is-empty'}`} title="历史批次审批编号请在原批次维护">{code||'待填写审批编号'}</span>;
  if(editing)return <div className="pq-approval-edit" onClick={event=>event.stopPropagation()}>
    <input autoFocus value={draft} maxLength={64} placeholder="填写审批编号" aria-label="核算审批编号"
      onChange={event=>setDraft(event.target.value)}
      onKeyDown={event=>{if(event.key==='Enter')void commit();else if(event.key==='Escape')cancel();}}/>
    <button type="button" className="pq-icon-button" title={saving?'保存中':'保存审批编号'} aria-label="保存审批编号" disabled={saving} onClick={()=>void commit()}>{saving?<Loader2 size={13} className="animate-spin"/>:<Check size={14}/>}</button>
    <button type="button" className="pq-icon-button" title="取消修改" aria-label="取消修改审批编号" disabled={saving} onClick={cancel}><X size={14}/></button>
  </div>;
  return <div className="pq-approval" onClick={event=>event.stopPropagation()}>
    <button type="button" className={`pq-approval-value${code?'':' is-empty'}`} title={code||'点击填写核算审批编号'} onClick={()=>setEditing(true)}>{code||'待填写审批编号'}</button>
    <button type="button" className="pq-icon-button pq-approval-edit-btn" title={code?'修改审批编号':'填写审批编号'} aria-label={`${code?'修改':'填写'} ${taskLabel(task)}`} onClick={()=>setEditing(true)}><Pencil size={13}/></button>
  </div>;
}

export function PayrollQueueTable({tasks,selectedId,expandedId,checked,onSelect,onToggleExpand,onCheck,onCheckAll,onStop,onRemove,onDownload,onOpenDirectory,onRestore,onApproval,renderDetail,busy=false,hidden=false}:{
  tasks:PayrollQueueTask[];selectedId?:string;expandedId?:string;checked:string[];onSelect:(id:string)=>void;onToggleExpand:(id:string)=>void;onCheck:(id:string)=>void;onCheckAll:()=>void;
  onStop:(task:PayrollQueueTask)=>void;onRemove:(tasks:PayrollQueueTask[])=>void;onDownload:(task:PayrollQueueTask)=>void;
  onOpenDirectory:(task:PayrollQueueTask)=>void;onRestore:(tasks:PayrollQueueTask[])=>void;onApproval:(task:PayrollQueueTask,code:string)=>Promise<void>;
  renderDetail?:(task:PayrollQueueTask)=>React.ReactNode;busy?:boolean;hidden?:boolean;
}){
  const allChecked=tasks.length>0&&tasks.every(task=>checked.includes(task.id));
  return <div className="pq-table-scroll wbx-table-scroll wbx-payroll__scroll"><table className="pq-table wbx-table wbx-payroll__table"><thead><tr>
    <th className="pq-check"><input type="checkbox" aria-label="选择全部任务" checked={allChecked} disabled={!tasks.length||busy} onChange={onCheckAll}/></th>
    <th>核算任务</th><th>城市与周期</th><th className="pq-applicants">申请人数</th><th>当前进度</th><th className="pq-row-actions-heading pq-ops-cell">操作</th>
  </tr></thead><tbody>{tasks.map((task,index)=>{
    const state=payrollQueueStatus(task.status),running=payrollQueueRunning(task),done=task.status==='completed';
    const expanded=expandedId===task.id;
    const errorHint=task.status==='error'&&!task.current_action
      ?(businessLogEntries(task.logs?.length?task.logs:task.preparation?.execution_logs).business.filter(entry=>/ERROR|WARN/.test(entry.level||'')).pop()?.text||'')
      :'';
    const progressDesc=task.current_action||errorHint;
    return <React.Fragment key={task.id}>
    <tr className={`pq-row${index%2===1?' is-alt':''}${task.id===selectedId?' is-selected':''}${expanded?' is-expanded':''}`} onClick={()=>onSelect(task.id)}>
      <td className="pq-check"><input type="checkbox" aria-label={`选择任务 ${taskLabel(task)}`} checked={checked.includes(task.id)} disabled={busy} onClick={event=>event.stopPropagation()} onChange={()=>onCheck(task.id)}/></td>
      <td className="pq-task-cell">
        <div className="pq-task-row">
          <button
            type="button"
            className="pq-expand-toggle"
            aria-expanded={expanded}
            aria-label={expanded?`收起 ${taskLabel(task)} 详情`:`展开 ${taskLabel(task)} 详情`}
            onClick={event=>{event.stopPropagation();onToggleExpand(task.id);}}
          >
            <ChevronDown size={15}/>
          </button>
          <ApprovalCell task={task} onSave={onApproval}/>
        </div>
      </td>
      <td className="pq-scope-cell"><strong>{task.plan?.city||(task.status==='queued'?'待识别':'识别模板中')}</strong><small>{task.plan?payrollScope(task.plan):'按上传顺序执行'}</small></td>
      <td className="pq-applicants">{task.plan?.applicants??'—'}</td>
      <td className="pq-progress-cell">
        <span className={`wbx-pill ${toneClass(state.tone)}`}>{running&&task.status!=='stopping'?<Loader2 size={13} className="animate-spin"/>:<span className="wbx-pill__dot" aria-hidden="true"/>}{state.label}</span>
        {running&&Number.isFinite(task.progress)&&(
          <div className="pq-inline-progress" aria-label={`进度 ${Math.round(task.progress)}%`}>
            <div className="pq-inline-progress__track"><span style={{width:`${Math.max(4,Math.min(100,Math.round(task.progress)))}%`}}/></div>
            <span className="tabular-nums">{Math.round(task.progress)}%</span>
          </div>
        )}
        {!!progressDesc&&<small className="pq-progress-desc" title={progressDesc}>{progressDesc}</small>}
        {!!task.elapsed_seconds&&<small className="pq-elapsed tabular-nums">已用时 {payrollElapsed(task.elapsed_seconds)}</small>}
      </td>
      <td className="pq-ops-cell"><div className="pq-row-actions" onClick={event=>event.stopPropagation()}>{hidden?<button className="wb-link" disabled={busy} onClick={()=>onRestore([task])}><ArchiveRestore size={14}/>恢复</button>:<>
        {done&&task.batch_id&&<><button className="pq-icon-button" title="下载核算成品包" aria-label={`下载 ${taskLabel(task)} 核算成品包`} disabled={busy} onClick={()=>onDownload(task)}><Download size={15}/></button><button className="pq-icon-button" title="打开结果目录" aria-label={`打开 ${taskLabel(task)} 结果目录`} disabled={busy} onClick={()=>onOpenDirectory(task)}><FolderOpen size={16}/></button></>}
        {running&&<button className="wb-link" title={task.status==='stopping'?'停止中':'停止'} aria-label={task.status==='stopping'?'停止中':`停止 ${taskLabel(task)}`} disabled={busy||task.status==='stopping'} onClick={()=>onStop(task)}><Square size={12}/>{task.status==='stopping'?'停止中':'停止'}</button>}
        <button className="pq-icon-button" title={running?'停止并移出':'移出任务'} aria-label={`${running?'停止并移出':'移出'} ${taskLabel(task)}`} disabled={busy||task.status==='stopping'} onClick={()=>onRemove([task])}><X size={15}/></button>
      </>}</div></td>
    </tr>
    {expanded&&renderDetail&&<tr className="pq-row-detail"><td colSpan={6}><div className="pq-row-detail__inner">{renderDetail(task)}</div></td></tr>}
    </React.Fragment>;
  })}</tbody></table>{!tasks.length&&<div className="pq-empty"><FileSpreadsheet size={28}/><strong>{hidden?'没有已移出的任务':'还没有核算任务'}</strong><p>{hidden?'移出只隐藏记录，原文件始终保留。':'上传多个 template 后，每份模板会建立一个独立任务。'}</p></div>}</div>;
}

export function PayrollTaskActivity({logs}:{logs:PayrollQueueTask['logs']}){
  const {business,technical}=businessLogEntries(logs||[]);
  const recent=business.slice(-5);
  return <div className="pq-activity"><h4>任务动态</h4>{recent.length?<ol className="pq-log-list">{recent.map((entry,index)=>logLine(entry,index))}</ol>:<p className="wbx-hint">任务开始后在这里显示关键进展。</p>}
    {business.length>5&&<details className="pq-disclosure"><summary>全部业务记录（{business.length}）</summary><ol className="pq-log-list pq-log-history">{business.map((entry,index)=>logLine(entry,index))}</ol></details>}
    {!!technical.length&&<details className="pq-disclosure pq-technical"><summary>详细诊断（{technical.length}）</summary><pre>{technical.map(entry=>entry.text).join('\n')}</pre></details>}
  </div>;
}
function logLine(entry:{time?:string;text:string;level?:string},index:number){
  return <li key={index} className={/ERROR|WARN/.test(entry.level||'')?'is-attention':''}>{entry.time&&<time>{formatLogTime(entry.time)}</time>}<span>{entry.text}</span></li>;
}
function formatLogTime(value:string){
  const date=new Date(value);
  if(Number.isFinite(date.getTime()))return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date);
  return value.match(/(?:T|\s)(\d{2}:\d{2}(?::\d{2})?)/)?.[1]||value;
}

export function FlashPayrollWorkbench({config,onConfigChange,isRunning,progress,progressText,logs,payrollPreparation:value,apiFetch,onPreparationChange,onUploadFiles,onOpenConnections,onOpenFengshenLogin,onOpenDeductions,onOpenSettings,onOtherMode}:Props){
  const [tasks,setTasks]=useState<PayrollQueueTask[]>([]),[selectedId,setSelectedId]=useState(''),[checked,setChecked]=useState<string[]>([]);
  /** 行内展开的任务 id（T6-1a A2）：详情从页面级 section 搬进表格行 */
  const [expandedId,setExpandedId]=useState('');
  const [loading,setLoading]=useState(true),[uploading,setUploading]=useState(false),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[loadError,setLoadError]=useState(''),[notice,setNotice]=useState(''),[templates,setTemplates]=useState(false),[hidden,setHidden]=useState(false);
  const [removeTargets,setRemoveTargets]=useState<PayrollQueueTask[]>([]),[skipLegacy,setSkipLegacy]=useState(false);
  const [queueFilterTab,setQueueFilterTab]=useState<PayrollQueueFilterTab>('all');
  const [queueSearch,setQueueSearch]=useState('');
  const [queuePage,setQueuePage]=useState(1);
  const [queuePageSize,setQueuePageSize]=useState(10);
  const api=useRef(apiFetch);api.current=apiFetch;
  const selectedRef=useRef(selectedId);selectedRef.current=selectedId;
  const guard=useRef(false),fetching=useRef(false),readController=useRef<AbortController|null>(null),mounted=useRef(true);
  const rawMode=config.payrollSourceMode||value?.mode||'fengshen';
  const mode:'fengshen'|'manual'=rawMode==='manual'?'manual':'fengshen';
  const excludeSeparation=config.payrollExcludeSeparation??true;

  useEffect(()=>{
    if(config.payrollSourceMode==='xiaoxiang'){
      onConfigChange({payrollSourceMode:'fengshen'});
    }
  },[config.payrollSourceMode,onConfigChange]);

  const request=useCallback(async(url:string,body?:unknown)=>{
    const response=await api.current(url,body===undefined?{cache:'no-store',signal:AbortSignal.timeout(120000)}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
    if(!response.ok){const result=await response.json().catch(()=>({}));throw Error(typeof result.detail==='string'?result.detail:typeof result.error==='string'?result.error:`操作未完成（${response.status}），请检查连接后再操作。`);}
    return response;
  },[]);
  const refresh=useCallback(async()=>{
    if(fetching.current)return null;fetching.current=true;
    const controller=new AbortController();readController.current=controller;
    try{
      const parameters=new URLSearchParams();if(hidden)parameters.set('hidden','true');if(selectedRef.current)parameters.set('detail_id',selectedRef.current);
      const response=await api.current(API+(parameters.size?'?'+parameters.toString():''),{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15000)])});
      const result=await response.json();if(!response.ok||!Array.isArray(result.tasks))throw Error(typeof result.detail==='string'?result.detail:'任务队列暂时无法更新');
      if(mounted.current&&!controller.signal.aborted){
        setTasks(result.tasks);
        setLoadError('');
      }
      return result.tasks as PayrollQueueTask[];
    }catch(e){
      if(mounted.current&&!controller.signal.aborted){
        setLoadError(e instanceof Error?e.message:'任务队列暂时无法更新');
      }
      return null;
    }
    finally{fetching.current=false;if(mounted.current)setLoading(false);}
  },[hidden]);
  /**
   * 队列轮询（P1-5 降噪）：可见时 2.5s，后台标签页降到 10s；
   * 切回可见时立刻刷新一次并重建定时器，避免"回前台还要等一个周期"。
   * 请求参数与接口未做任何改动。
   */
  useEffect(()=>{
    mounted.current=true;
    void refresh();
    let timer=0;
    const interval=()=>document.visibilityState==='visible'?2500:10000;
    const schedule=()=>{window.clearInterval(timer);timer=window.setInterval(()=>void refresh(),interval());};
    const onVisibility=()=>{if(document.visibilityState==='visible')void refresh();schedule();};
    schedule();
    document.addEventListener('visibilitychange',onVisibility);
    return()=>{mounted.current=false;window.clearInterval(timer);document.removeEventListener('visibilitychange',onVisibility);readController.current?.abort();};
  },[refresh]);
  useEffect(()=>{void refresh();},[selectedId,refresh]);
  useEffect(()=>{const changed=()=>void refresh();window.addEventListener('payroll-queue:changed',changed);return()=>window.removeEventListener('payroll-queue:changed',changed);},[refresh]);
  useEffect(()=>{setChecked([]);setSelectedId('');setTasks([]);setLoading(true);},[hidden]);
  useEffect(()=>{setSkipLegacy(false);},[value?.id]);
  const legacy=value&&!hidden&&!skipLegacy&&!tasks.some(task=>task.batch_id===value.id)?legacyPayrollTask(value,logs,progress,progressText):null;
  const visible=legacy?[legacy,...tasks]:tasks;
  const filteredVisible=useMemo(()=>filterPayrollQueueTasks(visible,queueFilterTab,queueSearch),[visible,queueFilterTab,queueSearch]);
  const pagedQueue=useMemo(()=>paginateEntries(filteredVisible,queuePage,queuePageSize),[filteredVisible,queuePage,queuePageSize]);
  const pagedTasks=pagedQueue.items;
  const tabCounts=useMemo(()=>({
    all:visible.length,
    active:filterPayrollQueueTasks(visible,'active','').length,
    waiting:filterPayrollQueueTasks(visible,'waiting','').length,
    completed:filterPayrollQueueTasks(visible,'completed','').length,
    issue:filterPayrollQueueTasks(visible,'issue','').length,
  }),[visible]);
  const selected=filteredVisible.find(task=>task.id===selectedId)||visible.find(task=>task.id===selectedId)||visible.find(task=>task.batch_id===value?.id)||visible.find(payrollQueueRunning)||visible[0];
  useEffect(()=>{if(selected&&selected.id!==selectedId)setSelectedId(selected.id);},[selected?.id,selectedId]);
  const chosen=visible.filter(task=>checked.includes(task.id));
  const downloadable=(chosen.length?chosen:filteredVisible).filter(task=>task.status==='completed'&&task.batch_id);
  const completed=visible.filter(task=>task.status==='completed').length,running=visible.filter(payrollQueueRunning).length;
  const waitingConfirmCount=visible.filter(task=>task.status==='waiting_confirmation').length;
  const act=async(work:()=>Promise<void>)=>{if(guard.current)return;guard.current=true;setBusy(true);setError('');setNotice('');try{await work();}catch(e){setError(e instanceof Error?e.message:'操作未完成');}finally{guard.current=false;setBusy(false);}};
  const upload=async(files:{file:File;relativePath:string}[])=>{
    if(uploading)return;setUploading(true);setError('');
    try{
      if(mode==='fengshen'&&files.some(item=>!item.file.name.toLowerCase().endsWith('.xlsx')||!item.file.name.toLowerCase().includes('template')))throw Error('请选择文件名含 template 的 .xlsx 标准模板，可一次选择多份。');
      const previous=new Set(tasks.map(task=>task.id));await onUploadFiles(files);
      if(hidden){setHidden(false);return;}
      const next=await refresh();const added=next?.filter(task=>!previous.has(task.id))||[];
      if(added.length){
        setSelectedId(added[0].id);
        setQueueFilterTab('all');
        setQueueSearch('');
        setQueuePage(Math.max(1, Math.ceil((next?.length||0)/queuePageSize)));
        setNotice(`已加入 ${added.length} 个核算任务，请逐行填写审批编号。`);
      }
    }catch(e){setError(e instanceof Error?e.message:'资料上传未完成');}finally{setUploading(false);}
  };
  const updateApproval=async(task:PayrollQueueTask,code:string)=>{
    setError('');setNotice('');
    try{
      const response=await request(`${API}/${task.id}/approval`,{approval_code:code});
      await response.json().catch(()=>({}));
      setNotice('审批编号已更新');
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:'审批编号保存失败');throw e;}
  };
  const stop=(task:PayrollQueueTask)=>void act(async()=>{
    if(task.legacy){await request('/api/workbench/task-center/stop',{id:'payroll_'+task.batch_id});onPreparationChange(await(await request(`/api/parttime/preparations/${task.batch_id}`)).json());}
    else await request(`${API}/${task.id}/stop`,{});
    await refresh();
  });
  const download=(task:PayrollQueueTask)=>void act(async()=>{
    const response=await request(`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(task.batch_id!)}`);saveDownloadBlob(await readDownloadResponse(response,'薪资核算结果.zip'),task.template_name.replace(/\.xlsx?$/i,'')+'_核算结果.zip');
  });
  const directory=(task:PayrollQueueTask)=>void act(async()=>{
    await request('/api/workbench/task-center/directory/open',{record_id:'payroll_'+task.batch_id});
  });
  const restore=(entries:PayrollQueueTask[])=>void act(async()=>{
    await request(API+'/visibility',{ids:entries.map(task=>task.id),restore:true});setChecked([]);await refresh();
  });
  /** 行内详情（T6-1a A2）：承载原页面级 .pq-detail 的全部任务级信息，不再重复文件名。 */
  const renderRowDetail=(task:PayrollQueueTask)=><div className="wbx-payroll__detail">
    <div className="wbx-payroll__detail-head">
      <span className={`wbx-pill ${toneClass(payrollQueueStatus(task.status).tone)}`}>{payrollQueueStatus(task.status).label}</span>
      <span className="wbx-hint" title={task.template_name}>模板：{task.template_name}</span>
      <span className="wbx-hint">{payrollModeName(task.mode)}{task.legacy?' · 历史批次':''}</span>
      {!!task.elapsed_seconds&&<span className="wbx-hint">已用时 {payrollElapsed(task.elapsed_seconds)}</span>}
    </div>
    {task.status==='error'&&<p className="wbx-hint">任务已结束，具体原因见下方任务动态。</p>}
    {task.preparation?.execution?.waiting_login&&<p role="status" className="wbx-hint">{task.preparation.execution.waiting_verification?'本任务正在等待骑手信息导出验证，完成后自动继续；收起验证窗口会保留等待。':'本任务正在等待平台登录，完成后自动继续。'}<button className="wb-link" onClick={task.mode==='fengshen'?onOpenFengshenLogin:onOpenConnections}>{task.preparation.execution.waiting_verification?'打开验证码窗口':'完成平台登录'}</button></p>}
    <PayrollTaskActivity logs={task.logs?.length?task.logs:task.preparation?.execution_logs}/>
    {task.preparation?.automatic_deductions&&<details className="wbx-disclosure"><summary>本次扣款规则</summary><p className="wbx-hint">沿用已有站点或城市配置，无配置站点按零扣款；不修改默认配置。</p><ul className="pq-rule-list">{task.preparation.automatic_deductions.sources.map((entry,index)=><li key={index}><span>{entry.station.name}</span><small>{entry.source}</small></li>)}</ul></details>}
    {task.status==='completed'&&<><p className="wbx-hint">打开结果后，请在 Excel / WPS 中重算并复核。</p><details className="wbx-disclosure"><summary>复核信息</summary><PayrollReviewSummary review={task.preparation?.result?.review_summary}/></details></>}
    </div>;
  const activeMode = PAYROLL_WORKBENCH_MODES.find(item => item.key === mode) || PAYROLL_WORKBENCH_MODES[0];

  return <div className="pq-workbench wbx-payroll">
    {/* 顶部：精简模式切换条与快捷入口 */}
    <section className="wbx-payroll__topbar" aria-label="核算模式与规则入口">
      <div className="wbx-payroll__mode-switch-group">
        <div className="wbx-segmented" role="tablist" aria-label="核算方式">
          {PAYROLL_WORKBENCH_MODES.map(item => {
            const Icon = item.icon;
            const active = mode === item.key;
            return (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={active}
                className={`wbx-segmented__item ${active ? 'is-active' : ''}`}
                disabled={uploading}
                onClick={() => {
                  if (mode !== item.key) onOtherMode(item.key);
                }}
              >
                <Icon size={14} />
                <span>{item.title}</span>
              </button>
            );
          })}
        </div>
        <span className="wbx-payroll__mode-hint">{activeMode.hint}</span>
      </div>

      <div className="wbx-payroll__topbar-actions">
        <button
          type="button"
          className="wbx-btn wbx-btn--ghost wbx-btn--sm"
          onClick={() => onOpenDeductions(false)}
        >
          <SlidersHorizontal size={14} />
          扣款规则
        </button>
        <button
          type="button"
          className="wbx-btn wbx-btn--ghost wbx-btn--sm"
          onClick={() => setTemplates(true)}
        >
          <FileSpreadsheet size={14} />
          标准模板
        </button>
      </div>
    </section>

    {/* 中部：常驻一站式拖拽/点选上传工作台 */}
    <section className="pq-intake" aria-label="添加核算任务">
      <ControlPanel
        payrollSourceMode={mode}
        onUploadFiles={upload}
        onOpenTemplates={() => setTemplates(true)}
        isRunning={uploading}
        separationOption={
          mode === 'fengshen' ? (
            <label
              className="pq-intake-option"
              title="取消勾选则下载全部站点，范围在任务建立时固定。"
            >
              <input
                type="checkbox"
                aria-label="排除取分离站点"
                checked={excludeSeparation}
                disabled={uploading}
                onChange={event =>
                  onConfigChange({ payrollExcludeSeparation: event.target.checked })
                }
              />
              <span>排除取分离站点</span>
            </label>
          ) : undefined
        }
      />
    </section>

    {error&&<p className="pq-message is-error" role="alert">{error}</p>}
    {notice&&<p className="pq-message" role="status">{notice}</p>}
    {loadError&&<p className="pq-message" role="status">{loadError}；现有记录保留，系统会继续更新。</p>}

    {/* 底部：常驻批次队列与齐套核验面板 */}
    <section className="pq-queue" aria-label="核算任务队列" aria-busy={loading}>
      <header className="pq-queue-heading">
        <div className="pq-queue-title-group">
          <h3>
            {hidden ? '已移出批次' : '核算批次队列'}
            <span className="tabular-nums">{visible.length}</span>
          </h3>
          <p className="tabular-nums">
            {visible.length > 0
              ? `实时队列 · ${running} 运行中 · ${waitingConfirmCount} 待确认 · ${completed} 已完成（点击行首箭头展开日志）`
              : mode === 'fengshen'
                ? '拖入或选择 .xlsx 标准薪资申请表即可启动自动算薪'
                : '拖入或选择含模板与本地源表的资料目录即可启动核验'}
          </p>
        </div>
        <div className="pq-queue-actions">
          {chosen.length>0&&<span className="pq-selection tabular-nums">已选 {chosen.length} 项</span>}
          {hidden?<>{chosen.length>0&&<button className="wb-button" disabled={busy} onClick={()=>restore(chosen)}>恢复已选</button>}</>:<>
            {!!downloadable.length&&<button className="wbx-btn wbx-btn--primary" disabled={busy} onClick={()=>void act(async()=>{if(downloadable.length===1){const response=await request(`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(downloadable[0].batch_id!)}`);saveDownloadBlob(await readDownloadResponse(response,'薪资核算结果.zip'),'薪资核算结果.zip');}else{const queueEntries=downloadable.filter(task=>!task.legacy);if(queueEntries.length!==downloadable.length)throw Error('历史批次请在对应行单独下载；其余任务可勾选后批量下载。');const response=await request(API+'/bundle',{ids:queueEntries.map(task=>task.id)});saveDownloadBlob(await readDownloadResponse(response,'批量薪资核算结果.zip'),'批量薪资核算结果.zip');}})}><Download size={14}/>{chosen.length?'下载已选结果':'下载已完成'}（{downloadable.length}）</button>}
            {chosen.length>0&&<button className="wbx-btn wbx-btn--ghost" disabled={busy} onClick={()=>setRemoveTargets(chosen)}>移出已选</button>}
          </>}
          <button className="wb-link" onClick={()=>{setHidden(previous=>!previous);setQueuePage(1);}}>{hidden?'返回队列':'已移出'}</button>
        </div>
      </header>

      {(() => {
        const waiting = visible.find(task => task.preparation?.execution?.waiting_verification);
        if (!waiting) return null;
        return (
          <div className="wbx-payroll__verify-banner" role="status">
            <div className="wbx-payroll__verify-banner-copy">
              <ShieldAlert size={15} />
              <span>等待骑手信息导出验证，完成后自动继续。</span>
              <span className="wbx-hint">收起验证窗口会保留等待。</span>
            </div>
            <button
              type="button"
              className="wbx-btn wbx-btn--sm wbx-payroll__verify-btn"
              onClick={onOpenFengshenLogin}
            >
              打开验证码窗口
            </button>
          </div>
        );
      })()}

      {visible.length>0&&(
        <div className="wbx-payroll__filter-bar">
          <div className="wbx-segmented" role="tablist" aria-label="按队列状态筛选">
            {([
              ['all','全部',tabCounts.all],
              ['active','执行中',tabCounts.active],
              ['waiting','待确认',tabCounts.waiting],
              ['completed','已完成',tabCounts.completed],
              ['issue','异常/已结束',tabCounts.issue],
            ] as const).map(([key,label,count])=>(
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={queueFilterTab===key}
                className={`wbx-segmented__item ${queueFilterTab===key?'is-active':''}`}
                onClick={()=>{setQueueFilterTab(key);setQueuePage(1);setChecked([]);}}
              >
                <span>{label}</span>
                <span className="tabular-nums">({count})</span>
              </button>
            ))}
          </div>
          <label className="wbx-payroll__search">
            <Search size={14}/>
            <input
              type="search"
              value={queueSearch}
              onChange={e=>{setQueueSearch(e.target.value);setQueuePage(1);}}
              placeholder="筛选模板名、城市或当前进展..."
              aria-label="筛选核算批次"
            />
          </label>
        </div>
      )}

      {loading && !visible.length ? (
        <div className="pq-empty">
          <Loader2 size={23} className="animate-spin" />
          <p>正在读取任务队列…</p>
        </div>
      ) : filteredVisible.length > 0 ? (
        <>
          <PayrollQueueTable
            tasks={pagedTasks}
            selectedId={selected?.id}
            expandedId={expandedId}
            onToggleExpand={(id: string) => setExpandedId(previous => (previous === id ? '' : id))}
            renderDetail={renderRowDetail}
            onSelect={(id: string) => {
              setSelectedId(id);
              setExpandedId(previous => (previous === id ? '' : id));
            }}
            checked={checked}
            onCheck={id =>
              setChecked(previous =>
                previous.includes(id) ? previous.filter(item => item !== id) : [...previous, id]
              )
            }
            onCheckAll={() => {
              const pageIds = pagedTasks.map(task => task.id);
              const allPageChecked = pageIds.length > 0 && pageIds.every(id => checked.includes(id));
              setChecked(previous =>
                allPageChecked
                  ? previous.filter(id => !pageIds.includes(id))
                  : Array.from(new Set([...previous, ...pageIds])),
              );
            }}
            onStop={stop}
            onRemove={setRemoveTargets}
            onDownload={download}
            onOpenDirectory={directory}
            onRestore={restore}
            onApproval={updateApproval}
            busy={busy}
            hidden={hidden}
          />
          <footer className="wbx-payroll__pagination" aria-label="核算批次队列分页">
            <div className="wbx-payroll__pagination-meta tabular-nums">
              <span>共 {pagedQueue.total} 条 · 当前第 {pagedQueue.startIndex + 1}-{pagedQueue.endIndex} 条</span>
              <label className="wbx-payroll__page-size">
                <span>每页</span>
                <select
                  className="wb-select"
                  aria-label="核算队列每页条数"
                  value={queuePageSize}
                  onChange={e => {
                    setQueuePageSize(Number(e.target.value));
                    setQueuePage(1);
                  }}
                >
                  <option value={10}>10 条</option>
                  <option value={20}>20 条</option>
                  <option value={50}>50 条</option>
                </select>
              </label>
            </div>
            <div className="wbx-payroll__pagination-controls">
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={pagedQueue.page <= 1}
                onClick={() => setQueuePage(Math.max(1, pagedQueue.page - 1))}
              >
                上一页
              </button>
              <span className="tabular-nums wbx-payroll__page-indicator">
                第 {pagedQueue.page} / {pagedQueue.totalPages} 页
              </span>
              <button
                type="button"
                className="wbx-btn wbx-btn--sm"
                disabled={pagedQueue.page >= pagedQueue.totalPages}
                onClick={() => setQueuePage(Math.min(pagedQueue.totalPages, pagedQueue.page + 1))}
              >
                下一页
              </button>
            </div>
          </footer>
        </>
      ) : visible.length > 0 ? (
        <div className="pq-empty">
          <FileSpreadsheet size={26}/>
          <strong>当前筛选下没有匹配的核算批次</strong>
          <p>可切换状态分类或清空关键词，恢复查看全部 {visible.length} 个批次。</p>
          <button type="button" className="wbx-btn wbx-btn--sm" onClick={()=>{setQueueFilterTab('all');setQueueSearch('');}}>重置队列筛选</button>
        </div>
      ) : (
        <div className="pq-empty">
          <FileSpreadsheet size={28} />
          <strong>{hidden ? '暂无已移出批次' : '暂无核算批次'}</strong>
          <p>
            {hidden
              ? '移出的任务会保留在此，可随时恢复。'
              : mode === 'fengshen'
                ? '上传 1 份或多份 .xlsx 标准申请表模板后，系统会自动建批并发起云端齐套与算薪。'
                : '上传包含标准模板与本地源表的资料文件夹后，系统会核验齐套度并展示各批次详情。'}
          </p>
        </div>
      )}
    </section>

    {templates&&<WorkbenchDrawer title="系统模板" wide onClose={()=>setTemplates(false)}><SystemTemplatesPanel onNavigatePayroll={()=>setTemplates(false)}/></WorkbenchDrawer>}
    {!!removeTargets.length&&<WorkbenchDrawer title={removeTargets.some(payrollQueueRunning)?'停止并移出任务':'移出任务列表'} onClose={()=>setRemoveTargets([])}><p>{removeTargets.length} 项任务将从共享列表移出；文件和处理记录保留，可在“已移出”恢复。</p>{removeTargets.some(payrollQueueRunning)&&<p>执行中的任务会先停止。</p>}<div className="pq-dialog-actions"><button className="wb-button" disabled={busy} onClick={()=>setRemoveTargets([])}>取消</button><button className="wb-primary" disabled={busy} onClick={()=>void act(async()=>{const current=removeTargets.filter(task=>!task.legacy),old=removeTargets.filter(task=>task.legacy);if(current.length)await request(API+'/visibility',{ids:current.map(task=>task.id),restore:false,stop_first:true});if(old.length){await request('/api/workbench/task-center/visibility',{ids:old.map(task=>'payroll_'+task.batch_id),restore:false,stop_first:true});setSkipLegacy(true);}setRemoveTargets([]);setChecked([]);await refresh();})}>确认移出，保留文件</button></div></WorkbenchDrawer>}
  </div>;
}

