import React, {useCallback, useEffect, useRef, useState} from 'react';
import {FileSpreadsheet, Download, MoreHorizontal, Square, FolderOpen, ChevronRight, ArchiveRestore, X, Loader2} from 'lucide-react';
import type {CorePageProps} from './CorePage';
import {ControlPanel} from './ControlPanel';
import {PayrollPreparation, type PayrollPreparationState} from './PayrollPreparation';
import {PayrollDeductionReview} from './PayrollDeductionReview';
import {PayrollReviewSummary} from './PayrollReviewSummary';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {SystemTemplatesPanel} from './SystemTemplatesPanel';
import {readDownloadResponse,saveDownloadBlob} from '../lib/outputDownload';
import {businessLogEntries} from '../lib/payrollBusinessLogs';
import {hasFullPayrollPreparation,legacyPayrollTask,payrollElapsed,payrollModeName,payrollQueueRunning,payrollQueueStatus,type PayrollQueueTask} from '../lib/payrollQueue';

type Props=Pick<CorePageProps,'config'|'onConfigChange'|'progress'|'progressText'|'logs'|'payrollPreparation'|'apiFetch'|'onPreparationChange'|'onUploadFiles'|'onRun'|'onOpenDownloads'|'onOpenConnections'|'onOpenFengshenLogin'|'onOpenDeductions'|'onOpenSettings'|'uploadExtracted'>&{isRunning:boolean;onOtherMode:(mode:'fengshen'|'manual'|'xiaoxiang')=>void};
const API='/api/parttime/queue';

export function PayrollQueueTable({tasks,selectedId,checked,onSelect,onCheck,onCheckAll,onStop,onRemove,onDownload,onOpenDirectory,onConfirm,onRestore,busy=false,hidden=false}:{
  tasks:PayrollQueueTask[];selectedId?:string;checked:string[];onSelect:(id:string)=>void;onCheck:(id:string)=>void;onCheckAll:()=>void;
  onStop:(task:PayrollQueueTask)=>void;onRemove:(tasks:PayrollQueueTask[])=>void;onDownload:(task:PayrollQueueTask)=>void;
  onOpenDirectory:(task:PayrollQueueTask)=>void;onConfirm:(task:PayrollQueueTask)=>void;onRestore:(tasks:PayrollQueueTask[])=>void;busy?:boolean;hidden?:boolean;
}){
  const allChecked=tasks.length>0&&tasks.every(task=>checked.includes(task.id));
  return <div className="pq-table-scroll"><table className="pq-table"><thead><tr>
    <th className="pq-check"><input type="checkbox" aria-label="选择全部任务" checked={allChecked} disabled={!tasks.length||busy} onChange={onCheckAll}/></th>
    <th>核算任务</th><th>城市与周期</th><th className="pq-applicants">申请人数</th><th>当前进度</th><th className="pq-row-actions-heading">操作</th>
  </tr></thead><tbody>{tasks.map(task=>{
    const state=payrollQueueStatus(task.status),running=payrollQueueRunning(task),done=task.status==='completed';
    const action=businessLogEntries([{text:task.current_action||'',level:'INFO'}]).business.at(-1)?.text;
    return <tr key={task.id} className={task.id===selectedId?'is-selected':''} onClick={()=>onSelect(task.id)}>
      <td className="pq-check"><input type="checkbox" aria-label={`选择任务 ${task.template_name}`} checked={checked.includes(task.id)} disabled={busy} onClick={event=>event.stopPropagation()} onChange={()=>onCheck(task.id)}/></td>
      <td className="pq-task-cell"><button className="pq-task-name" aria-pressed={task.id===selectedId} onClick={()=>onSelect(task.id)}><FileSpreadsheet size={17}/><span>{task.template_name}</span><ChevronRight size={14}/></button><small>{payrollModeName(task.mode)}{task.legacy?' · 历史批次':''}</small></td>
      <td className="pq-scope-cell"><strong>{task.plan?.city||(task.status==='queued'?'待识别':'识别模板中')}</strong><small>{task.plan?`${task.plan.start} 至 ${task.plan.end}`:'按上传顺序执行'}</small></td>
      <td className="pq-applicants">{task.plan?.applicants??'—'}</td>
      <td className="pq-progress-cell"><span className={`pq-state is-${state.tone}`}>{running&&task.status!=='stopping'?<Loader2 size={13} className="animate-spin"/>:<i/>}{state.label}</span>
        {action&&action!==state.label&&task.status!=='queued'&&<small className="pq-current-action">{action}</small>}
        {task.status==='calculating'&&Number(task.progress)>0&&<div className="pq-progress" aria-label={`核算进度 ${Math.min(100,Math.round(task.progress!))}%`}><span style={{width:`${Math.max(0,Math.min(100,task.progress!))}%`}}/></div>}
        {!!task.elapsed_seconds&&<small className="pq-elapsed">已用时 {payrollElapsed(task.elapsed_seconds)}</small>}
      </td>
      <td><div className="pq-row-actions" onClick={event=>event.stopPropagation()}>{hidden?<button className="wb-link" disabled={busy} onClick={()=>onRestore([task])}><ArchiveRestore size={14}/>恢复</button>:<>
        {done&&task.batch_id&&<><button className="pq-download" disabled={busy} onClick={()=>onDownload(task)}><Download size={14}/>下载</button><button className="pq-icon-button" title="打开结果目录" aria-label={`打开 ${task.template_name} 结果目录`} disabled={busy} onClick={()=>onOpenDirectory(task)}><FolderOpen size={16}/></button></>}
        {task.status==='waiting_confirmation'&&task.batch_id&&<button className="wb-link" disabled={busy} onClick={()=>onConfirm(task)}>{task.preparation?.deductions?.frozen?'继续核算':'确认扣款'}</button>}
        {running&&<button className="wb-link" disabled={busy||task.status==='stopping'} onClick={()=>onStop(task)}><Square size={12}/>{task.status==='stopping'?'停止中':'停止'}</button>}
        <button className="pq-icon-button" title={running?'停止并移出':'移出任务'} aria-label={`${running?'停止并移出':'移出'} ${task.template_name}`} disabled={busy||task.status==='stopping'} onClick={()=>onRemove([task])}><X size={15}/></button>
      </>}</div></td>
    </tr>;
  })}</tbody></table>{!tasks.length&&<div className="pq-empty"><FileSpreadsheet size={28}/><strong>{hidden?'没有已移出的任务':'还没有核算任务'}</strong><p>{hidden?'移出只隐藏记录，原文件始终保留。':'上传多个 template 后，每份模板会建立一个独立任务。'}</p></div>}</div>;
}

export function PayrollTaskActivity({logs}:{logs:PayrollQueueTask['logs']}){
  const {business,technical}=businessLogEntries(logs||[]);
  const recent=business.slice(-5);
  const line=(entry:typeof business[number],index:number)=><li key={index} className={/ERROR|WARN/.test(entry.level)?'is-attention':''}>{entry.time&&<time>{formatLogTime(entry.time)}</time>}<span>{entry.text}</span></li>;
  return <div className="pq-activity"><h4>最近动态</h4>{recent.length?<ol className="pq-log-list">{recent.map(line)}</ol>:<p className="pq-muted">任务开始后在这里显示关键进展。</p>}
    {business.length>5&&<details className="pq-disclosure"><summary>全部业务记录（{business.length}）</summary><ol className="pq-log-list pq-log-history">{business.map(line)}</ol></details>}
    {!!technical.length&&<details className="pq-disclosure pq-technical"><summary>详细诊断（{technical.length}）</summary><pre>{technical.map(entry=>entry.text).join('\n')}</pre></details>}
  </div>;
}
function formatLogTime(value:string){
  const date=new Date(value);
  if(Number.isFinite(date.getTime()))return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date);
  return value.match(/(?:T|\s)(\d{2}:\d{2}(?::\d{2})?)/)?.[1]||value;
}

export function FlashPayrollWorkbench({config,onConfigChange,uploadExtracted,isRunning,progress,progressText,logs,payrollPreparation:value,apiFetch,onPreparationChange,onUploadFiles,onRun,onOpenDownloads,onOpenConnections,onOpenFengshenLogin,onOpenDeductions,onOpenSettings,onOtherMode}:Props){
  const [tasks,setTasks]=useState<PayrollQueueTask[]>([]),[selectedId,setSelectedId]=useState(''),[checked,setChecked]=useState<string[]>([]);
  const [loading,setLoading]=useState(true),[uploading,setUploading]=useState(false),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[loadError,setLoadError]=useState(''),[more,setMore]=useState(false),[templates,setTemplates]=useState(false),[hidden,setHidden]=useState(false);
  const [reviewId,setReviewId]=useState(''),[removeTargets,setRemoveTargets]=useState<PayrollQueueTask[]>([]),[skipLegacy,setSkipLegacy]=useState(false);
  const api=useRef(apiFetch);api.current=apiFetch;
  const selectedRef=useRef(selectedId);selectedRef.current=selectedId;
  const guard=useRef(false),fetching=useRef(false),readController=useRef<AbortController|null>(null),mounted=useRef(true);
  const mode=config.payrollSourceMode||value?.mode||'fengshen';
  const excludeSeparation=config.payrollExcludeSeparation??true;
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
      if(mounted.current&&!controller.signal.aborted){setTasks(result.tasks);setLoadError('');}
      return result.tasks as PayrollQueueTask[];
    }catch(e){if(mounted.current&&!controller.signal.aborted)setLoadError(e instanceof Error?e.message:'任务队列暂时无法更新');return null;}
    finally{fetching.current=false;if(mounted.current)setLoading(false);}
  },[hidden]);
  useEffect(()=>{mounted.current=true;void refresh();const timer=setInterval(()=>void refresh(),2500);return()=>{mounted.current=false;clearInterval(timer);readController.current?.abort();};},[refresh]);
  useEffect(()=>{void refresh();},[selectedId,refresh]);
  useEffect(()=>{const changed=()=>void refresh();window.addEventListener('payroll-queue:changed',changed);return()=>window.removeEventListener('payroll-queue:changed',changed);},[refresh]);
  useEffect(()=>{setChecked([]);setSelectedId('');setReviewId('');setTasks([]);setLoading(true);},[hidden]);
  useEffect(()=>{setSkipLegacy(false);},[value?.id]);
  useEffect(()=>{const open=()=>setMore(true);window.addEventListener('workbench:payroll-more',open);return()=>window.removeEventListener('workbench:payroll-more',open);},[]);
  const legacy=value&&!hidden&&!skipLegacy&&!tasks.some(task=>task.batch_id===value.id)?legacyPayrollTask(value,logs,progress,progressText):null;
  const visible=legacy?[legacy,...tasks]:tasks;
  const selected=visible.find(task=>task.id===selectedId)||visible.find(task=>task.batch_id===value?.id)||visible.find(payrollQueueRunning)||visible[0];
  useEffect(()=>{if(selected&&selected.id!==selectedId)setSelectedId(selected.id);},[selected?.id,selectedId]);
  const chosen=visible.filter(task=>checked.includes(task.id));
  const downloadable=(chosen.length?chosen:visible).filter(task=>task.status==='completed'&&task.batch_id);
  const completed=visible.filter(task=>task.status==='completed').length,running=visible.filter(payrollQueueRunning).length;
  const act=async(work:()=>Promise<void>)=>{if(guard.current)return;guard.current=true;setBusy(true);setError('');try{await work();}catch(e){setError(e instanceof Error?e.message:'操作未完成');}finally{guard.current=false;setBusy(false);}};
  const upload=async(files:{file:File;relativePath:string}[])=>{
    if(uploading)return;setUploading(true);setError('');
    try{
      if(mode==='fengshen'&&files.some(item=>!item.file.name.toLowerCase().endsWith('.xlsx')||!item.file.name.toLowerCase().includes('template')))throw Error('请选择文件名含 template 的 .xlsx 标准模板，可一次选择多份。');
      const previous=new Set(tasks.map(task=>task.id));await onUploadFiles(files);
      if(hidden){setHidden(false);return;}
      const next=await refresh();const added=next?.find(task=>!previous.has(task.id));if(added)setSelectedId(added.id);
    }catch(e){setError(e instanceof Error?e.message:'资料上传未完成');}finally{setUploading(false);}
  };
  const stop=(task:PayrollQueueTask)=>void act(async()=>{
    if(task.legacy){await request('/api/workbench/task-center/stop',{id:'payroll_'+task.batch_id});onPreparationChange(await(await request(`/api/parttime/preparations/${task.batch_id}`)).json());}
    else await request(`${API}/${task.id}/stop`,{});
    await refresh();
  });
  const download=(task:PayrollQueueTask)=>void act(async()=>{const response=await request(`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(task.batch_id!)}`);saveDownloadBlob(await readDownloadResponse(response,'薪资核算结果.zip'),task.template_name.replace(/\.xlsx?$/i,'')+'_核算结果.zip');});
  const directory=(task:PayrollQueueTask)=>void act(async()=>{await request('/api/workbench/task-center/directory/open',{record_id:'payroll_'+task.batch_id});});
  const restore=(entries:PayrollQueueTask[])=>void act(async()=>{await request(API+'/visibility',{ids:entries.map(task=>task.id),restore:true});setChecked([]);await refresh();});
  const continueTask=async(task:PayrollQueueTask,version:string)=>{
    if(task.legacy){const prep=task.preparation!;onRun({action:'core',payrollPreparationId:prep.id,payrollSourceMode:prep.mode,city:prep.plan.city,preparationOnly:false,deductionConfigVersion:version});}
    else await request(`${API}/${task.id}/continue`,{version});
    setReviewId('');await refresh();
  };
  const confirm=(task:PayrollQueueTask)=>void act(async()=>{
    setSelectedId(task.id);
    let current=task;
    if(!hasFullPayrollPreparation(current.preparation)&&!current.legacy){
      const result=await(await request(`${API}?detail_id=${encodeURIComponent(task.id)}`)).json();
      current=result.tasks?.find((entry:PayrollQueueTask)=>entry.id===task.id);
      if(!hasFullPayrollPreparation(current?.preparation))throw Error('本任务资料尚未就绪，请等待状态更新。');
      setTasks(result.tasks);
    }
    if(current.preparation?.deductions?.frozen)await continueTask(current,current.preparation.deductions.version);
    else setReviewId(current.id);
  });
  const updatePreparation=(task:PayrollQueueTask,next:PayrollPreparationState)=>{if(task.legacy)onPreparationChange(next);else setTasks(previous=>previous.map(entry=>entry.id===task.id?{...entry,preparation:next}:entry));};
  const review=visible.find(task=>task.id===reviewId);
  return <div className="pq-workbench">
    <header className="pq-heading"><h2>兼职薪资核算</h2><div className="pq-heading-actions"><button className="wb-link" onClick={onOpenDownloads}>任务记录</button><button className="pq-icon-button" aria-label="更多核算设置" onClick={()=>setMore(true)}><MoreHorizontal size={21}/></button></div></header>
    <div className="pq-mode-bar"><div className="wb-segment pq-mode-tabs" role="tablist" aria-label="核算方式">{([['fengshen','闪购自动'],['manual','闪购手动'],['xiaoxiang','小象超市']] as const).map(([key,label])=><button key={key} role="tab" aria-selected={mode===key} className={mode===key?'is-active':''} disabled={uploading} onClick={()=>{if(mode!==key)onOtherMode(key);}}>{label}</button>)}</div><span className="pq-mode-hint">{mode==='fengshen'?'上传后自动执行':'按任务准备资料并核算'}</span></div>
    <section className="pq-intake" aria-label="添加核算任务"><ControlPanel payrollSourceMode={mode} onUploadFiles={upload} onOpenTemplates={()=>setTemplates(true)} isRunning={uploading||(mode==='xiaoxiang'&&isRunning)}/>{mode==='fengshen'&&<div className="pq-intake-options"><label><input type="checkbox" aria-label="排除取分离站点" checked={excludeSeparation} disabled={uploading} onChange={event=>onConfigChange({payrollExcludeSeparation:event.target.checked})}/>排除取分离站点</label><span>取消勾选则下载全部站点，范围在任务建立时固定。</span></div>}</section>
    {error&&<p className="pq-message is-error" role="alert">{error}</p>}
    {loadError&&<p className="pq-message" role="status">{loadError}；现有记录保留，系统会继续更新。</p>}
    <section className="pq-queue" aria-label="核算任务队列" aria-busy={loading}>
      <header className="pq-queue-heading"><div><h3>{hidden?'已移出任务':'任务队列'}<span>{visible.length}</span></h3>{!hidden&&visible.length>0&&<p>{running} 项进行中 · {completed} 项已完成</p>}</div><div className="pq-queue-actions">{chosen.length>0&&<span className="pq-selection">已选 {chosen.length} 项</span>}{hidden?<>{chosen.length>0&&<button className="wb-button" disabled={busy} onClick={()=>restore(chosen)}>恢复已选</button>}</>:<>
        {!!downloadable.length&&<button className="wb-button" disabled={busy} onClick={()=>void act(async()=>{if(downloadable.length===1){const response=await request(`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(downloadable[0].batch_id!)}`);saveDownloadBlob(await readDownloadResponse(response,'薪资核算结果.zip'),'薪资核算结果.zip');}else{const queueEntries=downloadable.filter(task=>!task.legacy);if(queueEntries.length!==downloadable.length)throw Error('历史批次请在对应行单独下载；其余任务可勾选后批量下载。');const response=await request(API+'/bundle',{ids:queueEntries.map(task=>task.id)});saveDownloadBlob(await readDownloadResponse(response,'批量薪资核算结果.zip'),'批量薪资核算结果.zip');}})}><Download size={14}/>{chosen.length?'下载已选结果':'下载已完成'}（{downloadable.length}）</button>}
        {chosen.length>0&&<button className="wb-button" disabled={busy} onClick={()=>setRemoveTargets(chosen)}>移出已选</button>}
      </>}<button className="wb-link" onClick={()=>setHidden(previous=>!previous)}>{hidden?'返回队列':'已移出'}</button></div></header>
      {loading&&!visible.length?<div className="pq-empty"><Loader2 size={23} className="animate-spin"/><p>正在读取任务队列…</p></div>:<PayrollQueueTable tasks={visible} selectedId={selected?.id} checked={checked} onSelect={setSelectedId} onCheck={id=>setChecked(previous=>previous.includes(id)?previous.filter(item=>item!==id):[...previous,id])} onCheckAll={()=>setChecked(visible.every(task=>checked.includes(task.id))?[]:visible.map(task=>task.id))} onStop={stop} onRemove={setRemoveTargets} onDownload={download} onOpenDirectory={directory} onConfirm={confirm} onRestore={restore} busy={busy} hidden={hidden}/>}
    </section>
    {selected&&<section className="pq-detail" aria-label="所选任务详情"><header className="pq-detail-heading"><div><span className="pq-eyebrow">所选任务</span><h3>{selected.template_name}</h3></div><span className={`pq-state is-${payrollQueueStatus(selected.status).tone}`}>{payrollQueueStatus(selected.status).label}</span></header>
      {selected.status==='error'&&<p className="pq-detail-note">任务已结束，具体原因见下方业务记录。</p>}
      {selected.preparation?.execution?.waiting_login&&<p role="status" className="pq-message">{selected.preparation.execution.waiting_verification?'本任务正在等待骑手信息导出验证，完成后自动继续；收起验证窗口会保留等待。':'本任务正在等待平台登录，完成后自动继续。'}<button className="wb-link" onClick={selected.mode==='fengshen'?onOpenFengshenLogin:onOpenConnections}>{selected.preparation.execution.waiting_verification?'打开验证码窗口':'完成平台登录'}</button></p>}
      <PayrollTaskActivity logs={selected.logs?.length?selected.logs:selected.preparation?.execution_logs}/>
      {selected.preparation?.automatic_deductions&&<details className="pq-disclosure"><summary>本次扣款规则</summary><p className="pq-muted">沿用已有站点或城市配置，无配置站点按零扣款；不修改默认配置。</p><ul className="pq-rule-list">{selected.preparation.automatic_deductions.sources.map((entry,index)=><li key={index}><span>{entry.station.name}</span><small>{entry.source}</small></li>)}</ul></details>}
      {selected.status==='completed'&&<><p className="pq-detail-note">打开结果后，请在 Excel / WPS 中重算并复核。</p><details className="pq-disclosure"><summary>复核信息</summary><PayrollReviewSummary review={selected.preparation?.result?.review_summary}/></details></>}
      {selected.mode!=='fengshen'&&hasFullPayrollPreparation(selected.preparation)&&selected.status==='waiting_confirmation'&&reviewId!==selected.id&&<details className="pq-disclosure" open={selected.preparation.status==='waiting_materials'}><summary>本任务资料</summary><PayrollPreparation value={selected.preparation} busy={busy} apiFetch={apiFetch} onChange={next=>updatePreparation(selected,next)} onContinue={()=>confirm(selected)} upload={uploadExtracted}/></details>}
      {review&&review.preparation&&review.id===selected.id&&<PayrollDeductionReview key={review.id} apiFetch={apiFetch} batchId={review.batch_id!} platform={review.mode==='xiaoxiang'?'xiaoxiang':'fengshen'} plan={review.plan||undefined} onOpenConnections={onOpenConnections} inline onClose={()=>setReviewId('')} onConfirmed={(next,version)=>{updatePreparation(review,next);void act(()=>continueTask(review,version));}}/>}
    </section>}
    {more&&<WorkbenchDrawer title="核算设置" onClose={()=>setMore(false)}><div className="pq-settings"><button className="wb-button" onClick={()=>{setMore(false);onOpenDeductions(true);}}>站点默认扣款</button><button className="wb-button" onClick={()=>{setMore(false);onOpenConnections();}}>平台登录</button>{onOpenSettings&&<button className="wb-button" onClick={()=>{setMore(false);onOpenSettings();}}>工作台设置</button>}</div></WorkbenchDrawer>}
    {templates&&<WorkbenchDrawer title="系统模板" wide onClose={()=>setTemplates(false)}><SystemTemplatesPanel onNavigatePayroll={()=>setTemplates(false)}/></WorkbenchDrawer>}
    {!!removeTargets.length&&<WorkbenchDrawer title={removeTargets.some(payrollQueueRunning)?'停止并移出任务':'移出任务列表'} onClose={()=>setRemoveTargets([])}><p>{removeTargets.length} 项任务将从共享列表移出；文件和处理记录保留，可在“已移出”恢复。</p>{removeTargets.some(payrollQueueRunning)&&<p>执行中的任务会先停止。</p>}<div className="pq-dialog-actions"><button className="wb-button" disabled={busy} onClick={()=>setRemoveTargets([])}>取消</button><button className="wb-primary" disabled={busy} onClick={()=>void act(async()=>{const current=removeTargets.filter(task=>!task.legacy),old=removeTargets.filter(task=>task.legacy);if(current.length)await request(API+'/visibility',{ids:current.map(task=>task.id),restore:false,stop_first:true});if(old.length){await request('/api/workbench/task-center/visibility',{ids:old.map(task=>'payroll_'+task.batch_id),restore:false,stop_first:true});setSkipLegacy(true);}setRemoveTargets([]);setChecked([]);await refresh();})}>确认移出，保留文件</button></div></WorkbenchDrawer>}
  </div>;
}
