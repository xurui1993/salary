import React,{useEffect,useRef,useState} from 'react';
import {platformAuthRequest,PlatformAuthError} from '../lib/platformAuthApi';

type Fetcher=(url:string,init?:RequestInit)=>Promise<Response>;
type Point=[number,number];
export function OfficialVerification({apiFetch,sessionId,challengeId,version,disabled,onCommand}:{apiFetch:Fetcher;sessionId:string;challengeId:string;version:string;disabled:boolean;onCommand:(id:number)=>void}){
  const fetchRef=useRef(apiFetch);fetchRef.current=apiFetch;
  const [url,setUrl]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[dragging,setDragging]=useState(false),[uncertain,setUncertain]=useState(false),[reload,setReload]=useState(0);
  const path=useRef<Point[]>([]),started=useRef(0),lastPoint=useRef(0),inflight=useRef(false),imageUrl=useRef(''),imageVersion=useRef(''),gestureVersion=useRef('');
  const endpoint='/api/fengshen-downloads/source-auth/xiaoxiang';
  useEffect(()=>{
    if(dragging)return;
    let disposed=false;const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
    void (async()=>{
      try{
        const response=await fetchRef.current(`${endpoint}/frame?session_id=${encodeURIComponent(sessionId)}&v=${encodeURIComponent(version)}`,{signal:controller.signal,cache:'no-store'});
        if(!response.ok || !response.headers.get('content-type')?.startsWith('image/png'))throw new Error();
        const blob=await response.blob();if(!blob.size || blob.size>512*1024)throw new Error();
        if(!disposed){const objectUrl=URL.createObjectURL(blob),previous=imageUrl.current;imageUrl.current=objectUrl;imageVersion.current=version;setUrl(objectUrl);setError('');if(previous)URL.revokeObjectURL(previous);}
      }catch{if(!disposed)setError('官方验证画面暂未读到，请稍候。');}
      finally{clearTimeout(timer);}
    })();
    return()=>{disposed=true;controller.abort();clearTimeout(timer);};
  },[sessionId,challengeId,version,dragging,reload]);
  useEffect(()=>()=>{if(imageUrl.current)URL.revokeObjectURL(imageUrl.current);},[]);
  function point(event:React.PointerEvent<HTMLImageElement>):Point{
    const box=event.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))];
  }
  async function submit(points:Point[],duration:number,shownVersion:string){
    if(inflight.current)return;inflight.current=true;setBusy(true);setError('');
    try{
      if(uncertain){setError('上次验证操作结果尚未确认，请等待平台更新后操作。');return;}
      const result=await platformAuthRequest<{command_id:number}>(fetchRef.current,endpoint+'/interact',{action:'challenge_gesture',session_id:sessionId,challenge_id:challengeId,challenge_version:shownVersion,points,duration_ms:Math.max(100,Math.min(3000,duration))});
      onCommand(result.command_id);
    }catch(err){if(err instanceof PlatformAuthError && err.uncertain)setUncertain(true);setError(err instanceof Error?err.message:'验证操作未完成，请稍候。');}
    finally{inflight.current=false;setBusy(false);}
  }
  return <section aria-label="官方安全验证" style={{border:'1px solid #d5e2ed',borderRadius:12,padding:12,marginBottom:16}}>
    <p>请按官方提示手动点击或拖动完成安全验证。</p>
    <p className="wb-muted">这里只显示官方验证区域。完成后等待平台继续，短信发送结果以官方提示为准。</p>
    {url?<img src={url} alt="官方安全验证区域，可点击或拖动" draggable={false} style={{display:'block',maxWidth:'100%',maxHeight:'55vh',width:'auto',height:'auto',touchAction:'none',cursor:disabled || busy?'wait':'pointer',userSelect:'none'}}
      onPointerDown={event=>{
        if(disabled || busy || uncertain || error || event.button!==0)return;
        event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);path.current=[point(event)];gestureVersion.current=imageVersion.current;started.current=Date.now();lastPoint.current=started.current;setDragging(true);
      }}
      onPointerMove={event=>{
        if(!path.current.length)return;event.preventDefault();if(Date.now()-lastPoint.current>=30 && path.current.length<63){path.current.push(point(event));lastPoint.current=Date.now();}
      }}
      onPointerUp={event=>{
        if(!path.current.length)return;event.preventDefault();const points=[...path.current,point(event)];path.current=[];setDragging(false);
        const first=points[0];const moved=points.some(p=>Math.abs(p[0]-first[0])>.015 || Math.abs(p[1]-first[1])>.015);
        void submit(moved?points:[first],Date.now()-started.current,gestureVersion.current);
      }}
      onPointerCancel={()=>{path.current=[];setDragging(false);}}
    />:<p role="status" className="wb-muted">正在读取官方验证画面…</p>}
    {(busy || disabled) && <p role="status" className="wb-muted">正在等待平台处理验证操作。</p>}
    {error && <p role="alert" className="wb-error">{error}</p>}
    {error && !uncertain && <button type="button" className="wb-button" disabled={busy || disabled} onClick={()=>setReload(value=>value+1)}>重新读取验证画面</button>}
    {uncertain && <button type="button" className="wb-button" disabled={busy} onClick={()=>void (async()=>{
      setBusy(true);
      try{const state=await platformAuthRequest<{input_pending?:boolean}>(fetchRef.current,endpoint,undefined,10000);if(state.input_pending){setError('验证操作仍在处理中，请稍候。');return;}setUncertain(false);setError('');}
      catch{setError('状态暂未读到，请稍候。');}finally{setBusy(false);}
    })()}>重新读取验证状态</button>}
  </section>;
}
