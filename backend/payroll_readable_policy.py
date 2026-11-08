"""User-selected policy: readable template + delivery; other inputs are optional."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace

from parttime_source import SourceError

POLICY='readable_delivery_v1'


def collect(folder,state,manager):
    from payroll_inputs import LABELS,validate_upload,save,readiness
    from parttime_source import clean_rider_bill
    from payroll_unified_download import merge_tables
    from payroll_source_notes import source_reason,input_note
    latest={}
    for job in state['jobs']:
        run=manager.get_run(state['download_owner'],job)
        scope=state.get('job_scopes',{}).get(job,'all')
        for item in run['items']:
            if item['dataset'] in LABELS:latest[(scope,item['dataset'])]=(job,run,item)
    for kind,old in list(state['items'].items()):
        # Files are staged under a dedicated directory so skipped/corrupt optional
        # sources cannot be rediscovered by the calculation engine's file scanner.
        destination=folder/'input'/'usable';destination.mkdir(parents=True,exist_ok=True)
        for obsolete in destination.glob(LABELS[kind]+'*'):
            if obsolete.is_file() and not obsolete.is_symlink():obsolete.unlink()
        parts=[];reasons=[]
        for (scope,dataset),(job,run,item) in latest.items():
            if dataset!=kind:continue
            if item.get('error'):reasons.append(source_reason(item['error']))
            for info in run.get('files',[]):
                if info.get('dataset')!=kind or info.get('artifact_role')=='summary':continue
                try:
                    path,_=manager.get_file(state['download_owner'],job,info['id'],verify_integrity=False)
                    validate_upload(Path(path),kind,readability_only=True)
                    raw=folder/'evidence'/'available';raw.mkdir(parents=True,exist_ok=True)
                    part=raw/(kind+'_'+scope+'_'+info['id']+Path(path).suffix)
                    if kind=='rider_monthly':
                        part=part.with_suffix('.csv');clean_rider_bill(path,part,SimpleNamespace(**state['plan']))
                    else:shutil.copy2(path,part)
                    parts.append(part)
                except Exception as exc:
                    # No failure ledger/retry item is created for optional inputs.
                    reasons.append('文件无法读取：'+source_reason(exc,'input_validation'))
                    continue
        if parts:
            try:
                target=destination/((('UB骑手账单_cleaned_'+state['plan']['month']) if kind=='rider_monthly' else LABELS[kind])+parts[0].suffix)
                merge_tables(parts,target)
                state['items'][kind]={'label':old['label'],'status':'ready','file':str(target.relative_to(folder/'input'))}
                continue
            except Exception as exc:reasons.append('资料整理失败：'+source_reason(exc,'input_validation'))
        note=input_note(reasons)
        state['items'][kind]={'label':old['label'],'status':'unavailable' if kind=='delivery_fee' else 'omitted',
                              'note':note}
        message=f"【{old['label']}】{note}"
        history=state.setdefault('execution_logs',[])
        if not any(entry.get('text')==message for entry in history):history.append({'text':message,'level':'WARN'})
        state['execution_logs']=history[-300:]
    # The template itself is copied into the calculation directory; the source
    # template and all downloaded originals remain untouched.
    template=folder/'input'/state['plan']['template']
    shutil.copy2(template,destination/Path(state['plan']['template']).name)
    state['calculation_input']='usable'
    readiness(state);save(folder,state)


def inputs(folder,state):
    from openpyxl import load_workbook
    from payroll_inputs import validate_upload
    root=(folder/'input'/state.get('calculation_input','')).resolve()
    base=(folder/'input').resolve()
    if not root.is_relative_to(base):raise SourceError('资料目录不可访问，本次任务结束')
    template=root/Path(state['plan']['template']).name
    try:
        book=load_workbook(template,read_only=True);book.close()
        value=state['items']['delivery_fee']
        if value['status']!='ready':raise ValueError()
        path=(base/value['file']).resolve()
        if not path.is_relative_to(base):raise ValueError()
        validate_upload(path,'delivery_fee',readability_only=True)
    except Exception:raise SourceError('模板或配送费无法读取，本次任务结束') from None
    return root


def capture_rules(folder,state,root):
    from deduction_confirmation import affiliations,normalize,profile,DEFAULT_COLUMNS
    from workbench import read_defaults,version
    from payroll_inputs import save
    if state.get('deductions',{}).get('rows'):
        return
    platform='fengshen'
    try:defaults=profile(platform,root)
    except SourceError:defaults={'entries':{},'cities':{}}
    try:legacy=read_defaults(root)['rows']
    except SourceError:legacy=[]
    names={}
    for path in [folder/'input'/state['plan']['template'],folder/'input'/state['items']['delivery_fee']['file']]:
        try:
            for _,name,_,code in affiliations(path,True,'申请名单' if path.name==Path(state['plan']['template']).name else None):
                if name:names.setdefault(name,code)
        except SourceError:continue
    rows=[];sources=[];zero=[]
    city=state['plan']['city']
    for name,code in names.items():
        sites=[e['row'] for e in defaults['entries'].values() if e['row'].get('城市')==city]
        candidates=[r for r in sites if code and str(r.get('团队ID',''))==code] or [r for r in sites if normalize(r.get('团队名称'))==normalize(name)]
        city_rules=[e['row'] for e in defaults['cities'].values() if e['row'].get('城市')==city]
        old=[r for r in legacy if r.get('城市')==city and ((code and str(r.get('团队ID',''))==code) or normalize(r.get('团队名称'))==normalize(name))]
        chosen=candidates or city_rules or old
        source='站点配置' if candidates else '城市配置' if city_rules else '历史配置' if old else '无配置按零扣款'
        row={**(copy.deepcopy(chosen[0]) if chosen else {}),'城市':city,'团队名称':name,'团队ID':code or (chosen[0].get('团队ID','') if chosen else '')}
        for col in DEFAULT_COLUMNS:
            value=row.get(col)
            if value is None or value=='':row[col]=0
        if not chosen:zero.append(name)
        rows.append(row);sources.append({'station':{'name':name},'source':source,'row':row})
    if not rows:
        # A readable source with no rows still needs a legal rule container for
        # the unchanged engine; it does not create synthetic rider records.
        rows=[{'城市':city,'团队名称':'本次未匹配站点',**{c:0 for c in DEFAULT_COLUMNS}}]
    now=datetime.now(timezone.utc).isoformat()
    state['deductions']={'rows':rows,'version':version(rows),'scope':'batch','frozen':False}
    state['automatic_deductions']={'policy':POLICY,'zero_stations':zero,'sources':sources,'captured_at':now}
    state.pop('deduction_intent',None);state.pop('deduction_confirmation',None)
    save(folder,state)
