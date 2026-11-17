import React, {useCallback, useEffect, useRef, useState} from 'react';
import {FileSpreadsheet, Download, Square, FolderOpen, ChevronRight, ChevronDown, ArchiveRestore, X, Loader2, UploadCloud} from 'lucide-react';
import type {CorePageProps} from './CorePage';
import {ControlPanel} from './ControlPanel';
import {PayrollReviewSummary} from './PayrollReviewSummary';
import {WorkbenchDrawer} from './WorkbenchDrawer';
import {EmptyState} from './EmptyState';
import {toneClass} from '../lib/statusSemantics';
import {SystemTemplatesPanel} from './SystemTemplatesPanel';
import {readDownloadResponse,saveDownloadBlob} from '../lib/outputDownload';
import {businessLogEntries} from '../lib/payrollBusinessLogs';
import {legacyPayrollTask,payrollElapsed,payrollModeName,payrollQueueRunning,payrollQueueStatus,type PayrollQueueTask} from '../lib/payrollQueue';

type Props=Pick<CorePageProps,'config'|'onConfigChange'|'progress'|'progressText'|'logs'|'payrollPreparation'|'apiFetch'|'onPreparationChange'|'onUploadFiles'|'onRun'|'onOpenDownloads'|'onOpenConnections'|'onOpenFengshenLogin'|'onOpenDeductions'|'onOpenSettings'|'uploadExtracted'>&{isRunning:boolean;onOtherMode:(mode:'fengshen'|'manual'|'xiaoxiang')=>void};
const API='/api/parttime/queue';

export function PayrollQueueTable({tasks,selectedId,expandedId,checked,onSelect,onToggleExpand,onCheck,onCheckAll,onStop,onRemove,onDownload,onOpenDirectory,onRestore,renderDetail,busy=false,hidden=false}:{
  tasks:PayrollQueueTask[];selectedId?:string;expandedId?:string;checked:string[];onSelect:(id:string)=>void;onToggleExpand:(id:string)=>void;onCheck:(id:string)=>void;onCheckAll:()=>void;
  onStop:(task:PayrollQueueTask)=>void;onRemove:(tasks:PayrollQueueTask[])=>void;onDownload:(task:PayrollQueueTask)=>void;
  onOpenDirectory:(task:PayrollQueueTask)=>void;onRestore:(tasks:PayrollQueueTask[])=>void;renderDetail?:(task:PayrollQueueTask)=>React.ReactNode;busy?:boolean;hidden?:boolean;
}){
  const allChecked=tasks.length>0&&tasks.every(task=>checked.includes(task.id));
  return <div className="pq-table-scroll wbx-table-scroll wbx-payroll__scroll"><table className="pq-table wbx-table wbx-payroll__table"><thead><tr>
    <th className="pq-check"><input type="checkbox" aria-label="选择全部任务" checked={allChecked} disabled={!tasks.length||busy} onChange={onCheckAll}/></th>
    <th>核算任务</th><th>城市与周期</th><th className="pq-applicants">申请人数</th><th>当前进度</th><th className="pq-row-actions-heading pq-ops-cell">操作</th>
  </tr></thead><tbody>{tasks.map(task=>{
    const state=payrollQueueStatus(task.status),running=payrollQueueRunning(task),done=task.status==='completed';
    const expanded=expandedId===task.id;
    return <React.Fragment key={task.id}>
    <tr className={`${task.id===selectedId?'is-selected':''}${expanded?' is-expanded':''}`} onClick={()=>onSelect(task.id)}>
      <td className="pq-check"><input type="checkbox" aria-label={`选择任务 ${task.template_name}`} checked={checked.includes(task.id)} disabled={busy} onClick={event=>event.stopPropagation()} onChange={()=>onCheck(task.id)}/></td>
      <td className="pq-task-cell">
        <button
          type="button"
          className="pq-expand-toggle"
          aria-expanded={expanded}
          aria-label={expanded?`收起 ${task.template_name} 详情`:`展开 ${task.template_name} 详情`}
          onClick={event=>{event.stopPropagation();onToggleExpand(task.id);}}
        >
          <ChevronDown size={15}/>
        </button>
        <button className="pq-task-name" aria-pressed={task.id===selectedId} onClick={()=>onSelect(task.id)}><FileSpreadsheet size={17}/><span>{task.template_name}</span><ChevronRight size={14}/></button><small>{payrollModeName(task.mode)}{task.legacy?' · 历史批次':''}</small>
      </td>
      <td className="pq-scope-cell"><strong>{task.plan?.city||(task.status==='queued'?'待识别':'识别模板中')}</strong><small>{task.plan?`${task.plan.start} 至 ${task.plan.end}`:'按上传顺序执行'}</small></td>
      <td className="pq-applicants">{task.plan?.applicants??'—'}</td>
      <td className="pq-progress-cell">
        <span className={`wbx-pill ${toneClass(state.tone)}`}>{running&&task.status!=='stopping'?<Loader2 size={13} className="animate-spin"/>:<span className="wbx-dot"/>}{state.label}</span>
        {!!task.current_action&&<small className="pq-progress-desc" title={task.current_action}>{task.current_action}</small>}
        {!!task.elapsed_seconds&&<small className="pq-elapsed">已用时 {payrollElapsed(task.elapsed_seconds)}</small>}
      </td>
      <td className="pq-ops-cell"><div className="pq-row-actions" onClick={event=>event.stopPropagation()}>{hidden?<button className="wb-link" disabled={busy} onClick={()=>onRestore([task])}><ArchiveRestore size={14}/>恢复</button>:<>
        {done&&task.batch_id&&<><button className="pq-icon-button" title="下载核算结果" aria-label={`下载 ${task.template_name} 核算结果`} disabled={busy} onClick={()=>onDownload(task)}><Download size={15}/></button><button className="pq-icon-button" title="打开结果目录" aria-label={`打开 ${task.template_name} 结果目录`} disabled={busy} onClick={()=>onOpenDirectory(task)}><FolderOpen size={16}/></button></>}
        {running&&<button className="wb-link" title={task.status==='stopping'?'停止中':'停止'} aria-label={task.status==='stopping'?'停止中':`停止 ${task.template_name}`} disabled={busy||task.status==='stopping'} onClick={()=>onStop(task)}><Square size={12}/>{task.status==='stopping'?'停止中':'停止'}</button>}
        <button className="pq-icon-button" title={running?'停止并移出':'移出任务'} aria-label={`${running?'停止并移出':'移出'} ${task.template_name}`} disabled={busy||task.status==='stopping'} onClick={()=>onRemove([task])}><X size={15}/></button>
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

export function FlashPayrollWorkbench({config,onConfigChange,isRunning,progress,progressText,logs,payrollPreparation:value,apiFetch,onPreparationChange,onUploadFiles,onOpenDownloads,onOpenConnections,onOpenFengshenLogin,onOpenDeductions,onOpenSettings,onOtherMode}:Props){
  const [tasks,setTasks]=useState<PayrollQueueTask[]>([]),[selectedId,setSelectedId]=useState(''),[checked,setChecked]=useState<string[]>([]);
  /** 行内展开的任务 id（T6-1a A2）：详情从页面级 section 搬进表格行 */
  const [expandedId,setExpandedId]=useState('');
  const [loading,setLoading]=useState(true),[uploading,setUploading]=useState(false),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[loadError,setLoadError]=useState(''),[templates,setTemplates]=useState(false),[hidden,setHidden]=useState(false);
  const [removeTargets,setRemoveTargets]=useState<PayrollQueueTask[]>([]),[skipLegacy,setSkipLegacy]=useState(false);
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
  const selected=visible.find(task=>task.id===selectedId)||visible.find(task=>task.batch_id===value?.id)||visible.find(payrollQueueRunning)||visible[0];
  useEffect(()=>{if(selected&&selected.id!==selectedId)setSelectedId(selected.id);},[selected?.id,selectedId]);
  const chosen=visible.filter(task=>checked.includes(task.id));
  const downloadable=(chosen.length?chosen:visible).filter(task=>task.status==='completed'&&task.batch_id);
  const completed=visible.filter(task=>task.status==='completed').length,running=visible.filter(payrollQueueRunning).length;
  const act=async(work:()=>Promise<void>)=>{if(guard.current)return;guard.current=true;setBusy(true);setError('');try{await work();}catch(e){setError(e instanceof Error?e.message:'操作未完成');}finally{guard.current=false;setBusy(false);}};
  const upload=async(files:{file:File;relativePath:string}[])=>{
    if(uploading)return;setUploading(true);setError('');
    try{
      if((mode==='fengshen'||mode==='xiaoxiang')&&files.some(item=>!item.file.name.toLowerCase().endsWith('.xlsx')||!item.file.name.toLowerCase().includes('template')))throw Error('请选择文件名含 template 的 .xlsx 标准模板，可一次选择多份。');
      if(mode==='xiaoxiang'&&files.some(item=>!/(小象|灯塔)/.test(item.file.name)))throw Error('小象自动核算请选择文件名含“小象”或“灯塔”的 .xlsx 模板。');
      if(mode==='xiaoxiang'){
        const accountResponse=await api.current('/api/fengshen-downloads/platform-auth/baize/accounts',{cache:'no-store',signal:AbortSignal.timeout(15000)});
        const account=await accountResponse.json().catch(()=>({}));
        if(!accountResponse.ok)throw Error(typeof account.detail==='string'?account.detail:'商翼账户状态读取失败，请稍后重试。');
        if(account.account_type!=='xiaoxiang')throw Error(`商翼当前为${account.account_type==='shanggou'?'闪购账户':account.account_type==='unknown'?'未识别账户':'非小象账户'}${account.region_text?`（${account.region_text}）`:''}，请先在系统连接中切换到小象账户。`);
      }
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
  /** 行内详情（T6-1a A2）：承载原页面级 .pq-detail 的全部任务级信息，不再重复文件名。 */
  const renderRowDetail=(task:PayrollQueueTask)=><div className="wbx-payroll__detail">
    <div className="wbx-payroll__detail-head">
      <span className={`wbx-pill ${toneClass(payrollQueueStatus(task.status).tone)}`}>{payrollQueueStatus(task.status).label}</span>
      <span className="wbx-hint">{payrollModeName(task.mode)}{task.legacy?' · 历史批次':''}</span>
      {!!task.elapsed_seconds&&<span className="wbx-hint">已用时 {payrollElapsed(task.elapsed_seconds)}</span>}
    </div>
    {task.status==='error'&&<p className="wbx-hint">任务已结束，具体原因见下方任务动态。</p>}
    {task.preparation?.execution?.waiting_login&&<p role="status" className="wbx-hint">{task.preparation.execution.waiting_verification?'本任务正在等待骑手信息导出验证，完成后自动继续；收起验证窗口会保留等待。':'本任务正在等待平台登录，完成后自动继续。'}<button className="wb-link" onClick={task.mode==='fengshen'?onOpenFengshenLogin:onOpenConnections}>{task.preparation.execution.waiting_verification?'打开验证码窗口':'完成平台登录'}</button></p>}
    <PayrollTaskActivity logs={task.logs?.length?task.logs:task.preparation?.execution_logs}/>
    {task.preparation?.automatic_deductions&&<details className="wbx-disclosure"><summary>本次扣款规则</summary><p className="wbx-hint">沿用已有站点或城市配置，无配置站点按零扣款；不修改默认配置。</p><ul className="pq-rule-list">{task.preparation.automatic_deductions.sources.map((entry,index)=><li key={index}><span>{entry.station.name}</span><small>{entry.source}</small></li>)}</ul></details>}
    {task.status==='completed'&&<><p className="wbx-hint">打开结果后，请在 Excel / WPS 中重算并复核。</p><details className="wbx-disclosure"><summary>复核信息</summary><PayrollReviewSummary review={task.preparation?.result?.review_summary}/></details></>}
    </div>;
  /** 跨任务全局业务记录（页面底部唯一一条 details）。 */
  const globalLogs=visible.flatMap(task=>businessLogEntries(task.logs?.length?task.logs:task.preparation?.execution_logs).business);
  /** 真空态：首次使用或本轮全部移出后，队列没有任何记录。 */
  const isEmpty=!loading&&!visible.length&&!hidden;
  const emptyUploadRef=useRef<HTMLInputElement>(null);
  const pickFiles=(list:FileList|null)=>{
    const files=[...(list||[])].map(file=>({file,relativePath:file.name}));
    if(files.length)void upload(files);
  };
  return <div className={`pq-workbench wbx-payroll${isEmpty?' is-empty':''}`}>
    <div className="pq-mode-bar wbx-payroll__bar">
      <div className="pq-mode-left">
        <div className="wb-subview-segmented pq-mode-tabs" role="tablist" aria-label="核算方式">
          {([
            ['fengshen', '闪购自动'],
            ['manual', '闪购手动'],
            ['xiaoxiang', '小象超市'],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={mode === key}
              className={`wb-subview-tab wbx-tabs__tab ${mode === key ? 'is-active' : ''}`}
              disabled={uploading}
              onClick={() => {
                if (mode !== key) onOtherMode(key);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="wbx-payroll__mode-hint">
          {mode === 'fengshen'
            ? '闪购自动：上传申请表后自动拉取风神/蓝橙云端资料并执行核算'
            : mode === 'xiaoxiang'
              ? '小象超市：上传申请表后自动匹配灯塔日数据与考勤执行核算'
              : '闪购手动：按批次手动准备与上传齐套来源表后执行核算'}
        </span>
      </div>
    </div>
    {(() => {
      const waiting = visible.find(task => task.preparation?.execution?.waiting_verification);
      if (!waiting) return null;
      return <p className="pq-message" role="status">等待骑手信息导出验证，完成后自动继续。<button className="wb-link" onClick={onOpenFengshenLogin}>打开验证码窗口</button><span className="wbx-hint">收起验证窗口会保留等待。</span></p>;
    })()}
    {isEmpty&&mode==='fengshen'&&<div className="wbx-payroll__vacant-options"><label><input type="checkbox" aria-label="排除取分离站点" checked={excludeSeparation} disabled={uploading} onChange={event=>onConfigChange({payrollExcludeSeparation:event.target.checked})}/>排除取分离站点</label><span>取消勾选则下载全部站点，范围在任务建立时固定。</span></div>}
    {!isEmpty&&<section className="pq-intake" aria-label="添加核算任务"><ControlPanel payrollSourceMode={mode} onUploadFiles={upload} onOpenTemplates={()=>setTemplates(true)} isRunning={uploading||(mode==='xiaoxiang'&&isRunning)} separationOption={mode==='fengshen'?<label className="pq-intake-option" title="取消勾选则下载全部站点，范围在任务建立时固定。"><input type="checkbox" aria-label="排除取分离站点" checked={excludeSeparation} disabled={uploading} onChange={event=>onConfigChange({payrollExcludeSeparation:event.target.checked})}/><span>排除取分离站点</span></label>:undefined}/></section>}
    {error&&<p className="pq-message is-error" role="alert">{error}</p>}
    {loadError&&<p className="pq-message" role="status">{loadError}；现有记录保留，系统会继续更新。</p>}
    {isEmpty&&<div className="wbx-payroll__vacant wbx-payroll__empty">
      <input
        ref={emptyUploadRef}
        type="file"
        accept=".xlsx"
        multiple
        aria-label="上传薪资申请表模板"
        className="wbx-visually-hidden"
        onChange={event=>{pickFiles(event.target.files);event.target.value='';}}
      />
      <EmptyState
        icon={FileSpreadsheet}
        title="还没有核算批次"
        description="上传标准薪资申请表模板即可启动第一份自动化薪资核算。"
        hint={(
          <ol className="wbx-payroll__steps">
            <li>
              <strong>01 · 上传标准薪资申请表</strong>
              <span>支持一次选择多份 .xlsx 模板，每份自动生成独立核算批次</span>
            </li>
            <li>
              <strong>02 · 自动继承扣款与齐套核验</strong>
              <span>自动匹配城市与站点默认扣款规则，仅需对特殊站点做例外调整</span>
            </li>
            <li>
              <strong>03 · 复核明细并一键导出成品</strong>
              <span>核算完成后在队列中核对复核摘要，直接打包下载全套核算结果</span>
            </li>
          </ol>
        )}
        actions={[
          {label:'上传薪资申请表',tone:'primary',icon:UploadCloud,onClick:()=>emptyUploadRef.current?.click(),disabled:uploading},
          {label:'打开模板中心',icon:FileSpreadsheet,onClick:()=>setTemplates(true)},
          {label:'查看历史批次',tone:'ghost',icon:FolderOpen,onClick:onOpenDownloads},
        ]}
      />
    </div>}
    {!isEmpty&&<section className="pq-queue" aria-label="核算任务队列" aria-busy={loading}>
      <header className="pq-queue-heading"><div><h3>{hidden?'已移出任务':'任务队列'}<span>{visible.length}</span></h3>{!hidden&&visible.length>0&&<p>{visible.length} 个任务 · {running} 运行中 · {completed} 已完成</p>}</div><div className="pq-queue-actions">{chosen.length>0&&<span className="pq-selection">已选 {chosen.length} 项</span>}{hidden?<>{chosen.length>0&&<button className="wb-button" disabled={busy} onClick={()=>restore(chosen)}>恢复已选</button>}</>:<>
        {!!downloadable.length&&<button className="wbx-btn wbx-btn--primary" disabled={busy} onClick={()=>void act(async()=>{if(downloadable.length===1){const response=await request(`/api/fengshen-downloads/delivery-download?batch_id=${encodeURIComponent(downloadable[0].batch_id!)}`);saveDownloadBlob(await readDownloadResponse(response,'薪资核算结果.zip'),'薪资核算结果.zip');}else{const queueEntries=downloadable.filter(task=>!task.legacy);if(queueEntries.length!==downloadable.length)throw Error('历史批次请在对应行单独下载；其余任务可勾选后批量下载。');const response=await request(API+'/bundle',{ids:queueEntries.map(task=>task.id)});saveDownloadBlob(await readDownloadResponse(response,'批量薪资核算结果.zip'),'批量薪资核算结果.zip');}})}><Download size={14}/>{chosen.length?'下载已选结果':'下载已完成'}（{downloadable.length}）</button>}
        {chosen.length>0&&<button className="wbx-btn wbx-btn--ghost" disabled={busy} onClick={()=>setRemoveTargets(chosen)}>移出已选</button>}
      </>}<button className="wb-link" onClick={()=>setHidden(previous=>!previous)}>{hidden?'返回队列':'已移出'}</button></div></header>
      {loading&&!visible.length?<div className="pq-empty"><Loader2 size={23} className="animate-spin"/><p>正在读取任务队列…</p></div>:<PayrollQueueTable tasks={visible} selectedId={selected?.id} expandedId={expandedId} onToggleExpand={(id:string)=>setExpandedId(previous=>previous===id?'':id)} renderDetail={renderRowDetail} onSelect={(id:string)=>{setSelectedId(id);setExpandedId(id);}} checked={checked} onCheck={id=>setChecked(previous=>previous.includes(id)?previous.filter(item=>item!==id):[...previous,id])} onCheckAll={()=>setChecked(visible.every(task=>checked.includes(task.id))?[]:visible.map(task=>task.id))} onStop={stop} onRemove={setRemoveTargets} onDownload={download} onOpenDirectory={directory} onRestore={restore} busy={busy} hidden={hidden}/>}
    </section>}
        {!isEmpty&&visible.length>0&&<details className="wbx-disclosure wbx-payroll__global-logs">
      <summary>全部业务记录（{globalLogs.length}）</summary>
      {globalLogs.length?<ol className="pq-log-list pq-log-history">{globalLogs.map((entry,index)=>logLine(entry,index))}</ol>:<p className="wbx-hint">暂无业务记录。</p>}
    </details>}
    {templates&&<WorkbenchDrawer title="系统模板" wide onClose={()=>setTemplates(false)}><SystemTemplatesPanel onNavigatePayroll={()=>setTemplates(false)}/></WorkbenchDrawer>}
    {!!removeTargets.length&&<WorkbenchDrawer title={removeTargets.some(payrollQueueRunning)?'停止并移出任务':'移出任务列表'} onClose={()=>setRemoveTargets([])}><p>{removeTargets.length} 项任务将从共享列表移出；文件和处理记录保留，可在“已移出”恢复。</p>{removeTargets.some(payrollQueueRunning)&&<p>执行中的任务会先停止。</p>}<div className="pq-dialog-actions"><button className="wb-button" disabled={busy} onClick={()=>setRemoveTargets([])}>取消</button><button className="wb-primary" disabled={busy} onClick={()=>void act(async()=>{const current=removeTargets.filter(task=>!task.legacy),old=removeTargets.filter(task=>task.legacy);if(current.length)await request(API+'/visibility',{ids:current.map(task=>task.id),restore:false,stop_first:true});if(old.length){await request('/api/workbench/task-center/visibility',{ids:old.map(task=>'payroll_'+task.batch_id),restore:false,stop_first:true});setSkipLegacy(true);}setRemoveTargets([]);setChecked([]);await refresh();})}>确认移出，保留文件</button></div></WorkbenchDrawer>}
  </div>;
}
