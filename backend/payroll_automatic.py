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
    from deduction_confirmation import preflight, confirm, require_confirmation, finalize_intent, DEFAULT_COLUMNS, legacy_rows, normalize
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
    # Only a unique exact normalized suggestion is eligible for automatic aliasing.
    # Similar names and conflicting IDs are never silently accepted.
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
    if data['unresolved']:
        names='、'.join(row['name'] for row in data['unresolved'][:8])
        raise SourceError('站点身份无法唯一确定：'+names+'。请修正模板名称或编号、更新站点配置后重试；原资料保留')
    if data['differences']:
        rows='、'.join(str(d['row']) for d in data['differences'][:8])
        raise SourceError('申请与账单归属不一致（申请第'+rows+'行），请修正来源数据后重试；不需要重复确认正常项目')
    entries=copy.deepcopy(data['entries']);zero_sites=[];sources=[]
    legacy = legacy_rows('xiaoxiang' if state['mode']=='xiaoxiang' else 'fengshen', root)
    for entry in entries:
        configured=bool(entry['configured'] or entry.get('legacy'))
        ambiguous_legacy = [r for r in legacy
                            if r.get('城市')==entry['station']['city'] and normalize(r.get('团队名称'))==normalize(entry['station']['name'])]
        if not configured and len(ambiguous_legacy)>1:
            raise SourceError(entry['station']['name']+'存在多份冲突扣款配置，请在扣款设置中整理后重试，未按零扣款替代已有配置')
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
                except ValueError: raise SourceError(entry['station']['name']+'的'+col+'配置不是有效金额，请修改扣款配置后重试') from None
        entry['zero_confirmed']=True
        sources.append({'station':entry['station'],'source':source,'row':copy.deepcopy(entry['row'])})
    # Use the existing validation and receipt contract; this is an automatic policy,
    # not a fabricated user confirmation and never writes shared defaults.
    deduction,receipt=confirm(folder,state,root,directory,{'entries':entries,'review_version':data['review_version'],
        'accepted_differences':[],'confirmed':True,'save_defaults':False})
    receipt['mode']='automatic';receipt['policy']=WORKFLOW
    state.update(deductions=deduction,deduction_confirmation=receipt,
                 automatic_deductions={'policy':WORKFLOW,'zero_stations':zero_sites,'sources':sources,'captured_at':datetime.now(timezone.utc).isoformat()})
    state.setdefault('audit',[]).append({'action':'automatic_deduction_snapshot','version':deduction['version'],'zero_stations':zero_sites,'at':receipt['confirmed_at']})
