import React,{useEffect,useState} from 'react';
import {CheckCircle2,Clock3,Loader2,AlertCircle,FileSpreadsheet} from 'lucide-react';
import type {PayrollPreparationState} from './PayrollPreparation';
const labels:Record<string,string>={pending:'待下载',running:'下载中',validating:'校验中',ready:'已完成',failed:'获取失败',waiting_login:'待登录',cancelled:'已停止',omitted:'原批次未提供'};
export function PayrollDownloadProgress({value,running=false}:{value:PayrollPreparationState;running?:boolean}){
  const [now,setNow]=useState(Date.now());
  const relaxed=value.input_policy==='readable_delivery_v1';
  const active=running||['preparing','calculating','stopping'].includes(value.status);
  useEffect(()=>{if(!active)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[active,value.id]);
  const rows=value.downloads||Object.entries(value.items).map(([key,item])=>({key,label:item.label,status:item.status==='ready'?'ready':item.status==='failed'?'failed':item.status==='omitted'?'omitted':'pending',detail:item.error||'',completed_groups:0,total_groups:1,groups:[]}));
  const visibleRows=relaxed?rows.filter(row=>!['failed','unavailable'].includes(row.status)):rows;
  const complete=rows.filter(row=>row.status==='ready').length;
  const downloaded=rows.filter(row=>row.status==='ready'||row.total_groups>0&&row.completed_groups===row.total_groups).length;
  const started=Date.parse(value.execution_started_at||'');const elapsed=Number.isFinite(started)?Math.max(0,Math.floor((now-started)/1000)):0;
  const duration=elapsed>=60?`${Math.floor(elapsed/60)}分${elapsed%60}秒`:`${elapsed}秒`;
  const stage=value.status==='calculating'?(relaxed?'正在使用可用资料核算':'资料已齐，正在核算'):value.status==='calculated'?'核算完成':value.status==='waiting_materials'?(relaxed?'配送费不可用，请重新上传模板':'获取已暂停，已有文件保留'):value.execution?.waiting_login?'等待平台登录':active?(complete===rows.length?(relaxed?'正在核算':'下载完成，正在核对账单与扣款'):'正在获取本次核算资料'):'本次所需资料';
  const content=<section className="payroll-downloads" aria-label="核算资料下载清单"><header><div><h3>资料下载清单</h3><p role="status">{stage} · 已下载 {downloaded} / {rows.length} 项 · {relaxed?'已读取':'已校验'} {complete} 项{active&&Number.isFinite(started)?` · 已用时 ${duration}`:''}</p></div><span>{rows.length} 项资料</span></header>
    <div className="payroll-download-rows">{visibleRows.map(row=>{
      const busy=['running','validating'].includes(row.status);const files=row.groups.flatMap(group=>group.files);
      return <div key={row.key} className={`payroll-download-row is-${row.status}`}><div className="payroll-download-icon">{row.status==='ready'?<CheckCircle2 size={19}/>:row.status==='failed'?<AlertCircle size={19}/>:busy?<Loader2 className="animate-spin" size={19}/>:row.status==='pending'?<Clock3 size={19}/>:<FileSpreadsheet size={19}/>}</div><div className="payroll-download-name"><strong>{row.label}</strong><small>{row.detail||(relaxed?'上传后自动获取':'确认扣款后自动获取')}</small>{row.total_groups>1&&<div className="payroll-download-groups">{row.groups.map(group=><span key={group.scope}>{group.label} · {group.status==='success'?'已下载':group.detail}</span>)}<span>{row.completed_groups}/{row.total_groups} 组已下载</span></div>}{!!files.length&&<details><summary>文件（{files.length}）</summary>{files.map((name,index)=><small key={index}>{name}</small>)}</details>}</div><span className="payroll-download-state">{relaxed?(row.status==='validating'?'整理中':row.status==='omitted'?'未提供':row.status==='ready'?'可用':labels[row.status]||'处理中'):labels[row.status]||'处理中'}</span></div>;
    })}</div>
    {active&&<footer>各平台依次处理，文件生成较慢时会继续检查。可离开页面，稍后在任务记录查看。</footer>}
  </section>;
  return value.status==='awaiting_confirmation'&&!running?<details className="fp-details"><summary>确认后自动获取 {rows.length} 项资料</summary>{content}</details>:content;
}
