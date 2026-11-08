"""Display-only download progress. It never grants payroll readiness."""
PHASES = {'queued':'排队中','preparing':'准备中','waiting_collection':'等待采集资源','waiting_login':'等待平台登录',
          'waiting_manual':'等待平台验证','submitting':'提交导出','waiting_export':'等待平台生成文件',
          'downloading':'正在下载','validating':'校验文件','generating':'生成支付绑定','publishing':'保存文件',
          'completed':'文件已下载','failed':'获取失败','cancelled':'已停止'}


def material_log_changes(materials, previous):
    """Emit named transitions only; changes in unrelated run percentages are silent."""
    current = {}
    messages = []
    for row in materials:
        for group in row['groups']:
            key = (row['key'], group['scope'])
            detail = '文件已下载，等待校验' if group['status'] == 'success' else group['detail']
            if group['status'] in ('error', 'interrupted'): detail = '获取失败，请重试；已有文件保留'
            if group['status'] == 'cancelled': detail = '已停止，已有文件保留'
            current[key] = (group['status'], detail)
            if previous.get(key) != current[key]:
                messages.append(f"【{row['label']} · {group['label']}】{detail}")
    return messages, current


def material_progress(state, runs):
    from download_service import GENERATOR_DEPENDENCIES
    latest = {}
    for run in runs:
        scope = state.get('job_scopes', {}).get(run['id'], 'normal')
        for item in run['items']:
            latest[(scope, item['dataset'])] = (run, item)
    result = []
    relaxed=state.get('input_policy')=='readable_delivery_v1'
    for kind, value in state['items'].items():
        scopes = ['normal']
        if relaxed:scopes=list(dict.fromkeys(scope for scope,dataset in latest if dataset==kind)) or ['normal']
        elif state.get('include_separation') and kind != 'lanorange_part_price': scopes += state.get('separation_agencies', [])
        groups = []
        for scope in scopes:
            pair = latest.get((scope, kind))
            if not pair: continue
            run, item = pair
            status = item['status']
            phase = 'queued' if status == 'queued' else item.get('phase') or run.get('phase') or status
            detail = PHASES.get(phase, '正在处理' if status=='running' else '待下载')
            sources = ('rider_detail','receive_account','rider_info','baize_employees') if kind=='payment_binding' else GENERATOR_DEPENDENCIES.get(kind, [])
            dependencies = [latest.get((scope, source)) for source in sources]
            waiting = [entry for entry in dependencies if entry and entry[1]['status']=='waiting_login']
            running = [entry for entry in dependencies if entry and entry[1]['status']=='running']
            if status=='queued' and (waiting or running):
                status = 'waiting_login' if waiting else 'preparing'
                detail = '等待来源平台登录' if waiting else '正在准备关联来源资料'
            if status=='queued' and run.get('status')=='waiting_login':
                status='waiting_login';detail='等待来源平台登录'
            groups.append({'scope':scope,'label':'普通资料' if scope=='normal' else '取分离资料','status':status,'detail':detail,
                           'error':item.get('error',''),'files':[f['name'] for f in run.get('files',[]) if f['dataset']==kind and f.get('artifact_role')!='summary' and f.get('name')]})
        statuses = [g['status'] for g in groups]
        verified = value['status']=='ready'
        if verified: status='ready';detail='已下载并校验'
        elif value['status']=='omitted': status='omitted';detail=value.get('note') or '原批次未提供'
        elif value['status']=='failed' or any(s in ('error','interrupted') for s in statuses):status='failed';detail=value.get('error') or next((g['error'] for g in groups if g['error']),'获取未完成')
        elif len(groups)==len(scopes) and all(s=='success' for s in statuses):status='validating';detail='文件已下载，等待本批次校验'
        elif 'waiting_login' in statuses:status='waiting_login';detail=next((g['detail'] for g in groups if g['status']=='waiting_login'), '等待平台验证，完成后继续')
        elif any(s in ('running','preparing') for s in statuses):status='running';detail=next(g['detail'] for g in groups if g['status'] in ('running','preparing'))
        elif any(s=='cancelled' for s in statuses) or state['status'] in ('cancelled','stopping'):status='cancelled';detail='已停止，已有文件保留'
        else:status='pending';detail='等待下载'
        completed=sum(s=='success' for s in statuses)
        if relaxed:
            if status=='ready':detail='本次可用资料已读取'
            elif status=='validating':detail='正在整理资料'
            elif status in ('failed','omitted'):
                status='omitted';detail=value.get('note') or detail+'；未参与本次核算'
            group_status='success' if completed==len(scopes) else 'waiting_login' if status=='waiting_login' else 'running' if status in ('running','validating') else 'omitted' if status=='omitted' else 'queued'
            scope_label='统一资料'
            if state.get('download_scope')=='single_selection':
                if 'exclude_separation' in state:
                    scope_label='普通站点（排除取分离）' if state['exclude_separation'] else '全部站点'
                else:
                    scope_label='取分离站点' if state.get('only_separation') else '普通站点'
            groups=[{'scope':'all','label':scope_label,'status':group_status,'detail':detail,'error':'','files':list(dict.fromkeys(f for g in groups for f in g['files']))}]
            completed=int(completed==len(scopes));scopes=['all']
        result.append({'key':kind,'label':value['label'],'status':status,'detail':detail,'groups':groups,
                       'completed_groups':completed,'total_groups':len(scopes)})
    return result
