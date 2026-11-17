"""Two-step orchestration policy. Existing calculation formulas remain unchanged."""
import copy
from datetime import datetime, timezone

from parttime_source import SourceError

WORKFLOW = 'two_step_v1'


def prepare_scope(folder, state):
    from payroll_inputs import digest, save
    from deduction_confirmation import affiliations
    if state.get('input_policy')!='readable_delivery_v1' and digest(folder/'input'/state['plan']['template']) != state['template_hash']:
        raise SourceError('申请模板已变化，请重新上传原始模板')
    names = {name for _,name,_,_ in affiliations(folder/'input'/state['plan']['template'], True, '申请名单')}
    if state.get('input_policy')!='readable_delivery_v1' and (not names or any(not name.strip() for name in names)):
        raise SourceError('申请名单存在空白站点名称，请修正模板后重新上传')
    separation = sorted(name for name in names if '取分离' in name)
    if state['mode'] != 'fengshen' or not separation:
        return
    if state.get('scope_prepared') and state.get('include_separation'):
        return
    from station_directory import ready_directory, sync_separation
    # Fetch only the current city. This does not wait for an all-city scan.
    ready_directory('fengshen', state['plan']['city'])
    data = sync_separation(state['plan']['city'])
    agencies = sorted({s.get('agency_id') or s['city_id'] for s in data['stations'] if s['city']==state['plan']['city'] and (s.get('separation') or '取分离' in s['name'])})
    if not agencies:
        raise SourceError('模板含取分离站点，后台未返回对应资料范围；请检查风神账号权限后重试')
    state.update(include_separation=True, separation_agencies=agencies, scope_prepared=True)
    state.setdefault('audit',[]).append({'action':'automatic_separation_scope','names':separation,'at':datetime.now(timezone.utc).isoformat()})
    save(folder,state)


def capture_rules(folder, state, root, directory):
    from deduction_confirmation import preflight, require_confirmation, finalize_intent, DEFAULT_COLUMNS, legacy_rows, normalize
    from workbench import version
    # Preserve amounts explicitly captured by an older batch, including retries.
    if state.get('deductions',{}).get('frozen'):
        require_confirmation(state,state['deductions']['version'])
        return
    if state.get('deduction_intent'):
        finalize_intent(folder,state,root,directory)
        return
    if state.get('deduction_confirmation') and state['deduction_confirmation'].get('stage','final')=='final':
        require_confirmation(state,state['deductions']['version'])
        return
    data=preflight(folder,state,root,directory)
    # Unmatched stations and application/bill differences are not a hard stop:
    # this automatic policy leaves those stations without a rule, so the engine
    # applies zero deduction instead of asking for an execution-time confirmation.
    links=dict(state.get('station_links',{}))
    for row in data['unresolved']:
        matches=[r for r in row.get('recommendations',[]) if r['score']==1]
        if row['code'] not in ('id_conflict','history_invalid') and len(matches)==1:
            links[row['name']]=matches[0]['key']
    if links!=state.get('station_links',{}):
        candidate={**state,'station_links':links}
        data=preflight(folder,candidate,root,directory)
        state['station_links']=links
        state.setdefault('audit',[]).append({'action':'automatic_station_identity','links':links,'at':datetime.now(timezone.utc).isoformat()})
    entries=copy.deepcopy(data['entries']);zero_sites=[];sources=[];rows=[]
    legacy = legacy_rows('xiaoxiang' if state['mode']=='xiaoxiang' else 'fengshen', root)
    for entry in entries:
        configured=bool(entry['configured'] or entry.get('legacy'))
        source='站点配置' if entry.get('station_override') else '城市配置' if entry.get('inherited_city') else '历史配置' if entry.get('legacy') else '无配置按零扣款'
        if not configured:
            zero_sites.append(entry['station']['name'])
        for col in data['columns']:
            value=entry['row'][col]
            if col.endswith('_maxDays'):
                continue
            if not configured or value is None or value=='':
                entry['row'][col]='' if col=='招聘来源' else 0
            elif col in DEFAULT_COLUMNS and isinstance(value,str):
                try: entry['row'][col]=float(value)
                except ValueError: entry['row'][col]=0
        entry['zero_confirmed']=True
        row={**entry['row'], **{key: entry['row'].get(key) for key in ('城市','团队名称','团队ID')}}
        rules=entry.get('effective_problem_rules') or []
        if rules:
            row.update({'问题单扣款':0,'问题单扣款_isKw':True,'_problemRules':rules})
        rows.append(row)
        sources.append({'station':entry['station'],'source':source,'row':copy.deepcopy(entry['row'])})
    if not rows:
        rows=[{'城市':state['plan']['city'],'团队名称':'本次未匹配站点','团队ID':'',
               **{column:0 for column in data['columns']}}]
    deduction={'rows':rows,'version':version(rows),'scope':'automatic','frozen':False}
    receipt={'rules_version':deduction['version'],'input_signature':data['input_signature'],
             'stage':'final','confirmed_at':datetime.now(timezone.utc).isoformat(),
             'directory_version':directory['session_version'],'plan':state['plan'],
             'mode':'automatic','policy':WORKFLOW,
             'unresolved':[row['name'] for row in data.get('unresolved',[])],
             'differences':len(data.get('differences',[]))}
    state.update(deductions=deduction,deduction_confirmation=receipt,
                 automatic_deductions={'policy':WORKFLOW,'zero_stations':zero_sites,'sources':sources,'captured_at':receipt['confirmed_at']})
    state.setdefault('audit',[]).append({'action':'automatic_deduction_snapshot','version':deduction['version'],'zero_stations':zero_sites,'at':receipt['confirmed_at']})
