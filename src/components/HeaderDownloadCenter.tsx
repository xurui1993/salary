import { taskGuidance } from '../lib/taskGuidance';
import React, { useEffect, useRef, useState } from 'react';
import { Bell, ArrowUpRight } from 'lucide-react';

interface Props {
  apiFetch:(url:string,init?:RequestInit)=>Promise<Response>;
  runningTask?:string|null; progress?:number; progressText?:string;
  onNavigateHistory:()=>void; onOpenPlatformAuth:(platformKey?:string)=>void;
  onShowToast?:(msg:string,type?:'info'|'success'|'warn'|'error')=>void;
}


/** A notification is a link to real work, never a second file-delivery system. */
export function HeaderDownloadCenter({apiFetch,onNavigateHistory,runningTask,progressText}:Props) {
  const api=useRef(apiFetch);api.current=apiFetch;
  const wrap=useRef<HTMLDivElement>(null);
  const [open,setOpen]=useState(false),[error,setError]=useState('');
  const [tasks,setTasks]=useState<{id:string;title:string;status:string}[]>([]);
  const [counts,setCounts]=useState({active:0,attention:0,all:0});
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try {
        const response=await api.current('/api/workbench/task-center?page_size=20',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15000)])});
        const data=await response.json();if(!response.ok)throw new Error();
        if(!controller.signal.aborted){setCounts(data.counts);setTasks(data.records.slice(0,5).map((r:any)=>({id:r.id,title:r.title||`${r.kind==='payroll'?'薪资核算':r.kind==='generate'?'业务报表':'资料下载'} · ${r.cities.join('、')}`,status:r.status})));setError(data.warnings?.length?'部分记录暂不可读':'');}
      }catch{if(!controller.signal.aborted)setError('任务通知暂不可读，请到任务中心查看');}
      if(!controller.signal.aborted)timer=setTimeout(poll,6000);
    };void poll();return()=>{controller.abort();clearTimeout(timer);};
  },[]);
  useEffect(()=>{
    const outside=(e:MouseEvent)=>{if(!wrap.current?.contains(e.target as Node))setOpen(false);};
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setOpen(false);};
    document.addEventListener('mousedown',outside);document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('mousedown',outside);document.removeEventListener('keydown',key);};
  },[]);
  const go=()=>{setOpen(false);onNavigateHistory();};
  return <div className="tc-notifications" ref={wrap}>
    <button className="wb-icon" aria-expanded={open} aria-label={`任务通知：${error?'状态暂不可读':`${counts.active} 进行中，${counts.attention} 待处理`}`} onClick={()=>setOpen(!open)}><Bell size={20}/>{(counts.active>0||counts.attention>0||runningTask)&&<span className="tc-notification-dot"/>}</button>
    {open&&<section className="tc-notification-panel" aria-label="任务通知"><header><strong>任务通知</strong><button className="wb-link" onClick={go}>任务中心 <ArrowUpRight size={13}/></button></header>
      <p className="wb-muted">{counts.active} 进行中 · {counts.attention} 待处理</p>
      {runningTask&&<p className="wb-muted">{progressText||'当前操作正在执行'}</p>}
      {error&&<p role="status" className="wb-notice">{error}</p>}
      {!tasks.length&&!error&&<p className="tc-empty">暂无任务</p>}
      {tasks.map(t=><button className="tc-notification-item" key={t.id} onClick={go}><span>{t.title}</span><small>{taskGuidance({status:t.status}).label}</small></button>)}
    </section>}
  </div>;
}
