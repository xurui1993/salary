"""Business task intent; execution remains in the existing collectors/engines."""
# Presentation and scope contract for the report builder. Adding a report also
# requires its dataset/collector implementation; the page itself stays generic.
REPORTS = (
    {'id':'payment_binding', 'label':'骑手支付绑定', 'scope':'city_month',
     'systems':['风神','蓝橙','商翼'], 'station_rule':'separation',
     'description':'按城市和月份整理骑手支付绑定信息。',
     '_source_labels':['风神骑手数据明细','风神骑手绑定','风神骑手信息','蓝橙代领资料','商翼员工资料']},
    {'id':'abnormal_followup', 'label':'异常骑手跟进', 'scope':'city_month',
     'systems':['风神','蓝橙','商翼'], 'station_rule':'separation',
     'description':'以支付绑定为基准生成异常骑手跟进表。', '_source_group':'FOLLOWUP_DEPENDENCIES'},
    {'id':'abnormal_riders', 'label':'异常骑手整理', 'scope':'all',
     'systems':['蓝橙'], 'station_rule':'none',
     'description':'整理蓝橙全量异常骑手资料。', '_source_group':'ABNORMAL_RIDERS_DEPENDENCIES'},
)
GENERATORS = tuple(report['id'] for report in REPORTS)
TASK_LABELS = {'download': '资料下载', 'generate': '业务表生成', 'payroll': '兼职薪资核算'}


def intent(payload):
    # Requests saved before task categories existed must keep their fingerprint.
    if 'task_kind' not in payload:
        return {}
    kind = payload['task_kind']
    selected = payload.get('datasets')
    if kind not in ('download', 'generate'):
        raise ValueError('请选择资料下载或业务表生成')
    if not isinstance(selected, list) or not selected:
        raise ValueError('请选择需要处理的资料或生成表')
    if kind == 'download':
        if any(value in GENERATORS for value in selected):
            raise ValueError('生成表请在业务表生成分类中选择')
        return {'task_kind': kind}
    target = payload.get('generation_target')
    if target not in GENERATORS or selected != [target]:
        raise ValueError('一次业务表生成任务只能选择一张目标表，来源资料由系统关联')
    return {'task_kind': kind, 'generation_target': target}


def category(run):
    explicit = run.get('task_kind')
    if explicit in ('download', 'generate', 'payroll_source'):
        return explicit
    return 'generate' if any(value in GENERATORS for value in run.get('datasets', [])) else 'download'


def generators():
    import download_service as service
    return [{**{key:value for key,value in report.items() if not key.startswith('_')},
             'sources': report.get('_source_labels') or [service.DATASETS[key] for key in getattr(service,report['_source_group'])]}
            for report in REPORTS]
