"""Full export first, bounded city partitions second, one verified deliverable."""
from collections import Counter
import hashlib
import hashlib_compat
import json
from pathlib import Path
import re
import shutil

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from binding_sources_http import authenticated, query
from binding_recovery import verified_file
from fengshen_bill import BillCollectionError, atomic_json
from lanorange_catalog import DATASETS, ALL_CITIES, date_range, source_filters
from lanorange_download import collect, load_cities, validate_original, business_rows

LISTS = {
    'lanorange_rider_quit':'info/riderQuit/list',
    'lanorange_part_price':'salary/partRiderPrice/list',
    'lanorange_rider_archive':'info/riderInfo/list',
    'lanorange_rider_leave':'info/riderLeave/list',
    'lanorange_salary_replace':'info/riderSalaryReplace/list',
}
DETAILS = {'lanorange_rider_report':'info/riderReportDetail/queryList',
           'lanorange_batch_quit':'info/riderBatchQuitDetail/queryList'}
IDENTITY='lanorange_identity_change'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def all_list(session, endpoint, cancelled):
    rows=[];total=None;page=1
    while True:
        if cancelled.is_set():raise BillCollectionError('蓝橙全量基准核对已取消')
        data=query(session,'lanorange',endpoint,{'pageNum':page,'pageSize':1000})
        batch=data.get('rows');count=data.get('total')
        if type(count) is not int or count<0 or not isinstance(batch,list) or (total is not None and count!=total):
            raise BillCollectionError('蓝橙基准分页总数变化或结构异常')
        total=count;rows.extend(batch)
        if len(rows)==total:break
        if not batch or len(rows)>total:raise BillCollectionError('蓝橙基准分页不完整')
        page+=1
    ids=[str(row.get('id','')) for row in rows]
    if any(not key for key in ids) or len(ids)!=len(set(ids)):raise BillCollectionError('蓝橙基准分页编号重复或缺失')
    return rows


def list_params(months=None):
    params = {'pageNum': 1, 'pageSize': 1}
    if months:
        begin, end = date_range(months)
        params['params[beginTime]'] = begin
        params['params[endTime]'] = end
    return params


def baseline(dataset, log, cancelled, months=None):
    if cancelled.is_set(): raise BillCollectionError('蓝橙全量下载已取消')
    with authenticated('lanorange', log, cancelled) as session:
        if dataset in LISTS:
            value=query(session,'lanorange',LISTS[dataset],list_params(months)).get('total')
            if type(value) is not int or value < 0: raise BillCollectionError('蓝橙全量基准数量未确认')
            return {'total':value}
        if dataset==IDENTITY:
            parents=all_list(session,'info/riderIdentityChange/list',cancelled)
            parent_ids={str(row['id']) for row in parents}
            details=all_list(session,'info/riderIdentityChangeDetail/list',cancelled)
            # The official export expands authorized applications, rather than
            # exporting unrelated/orphaned detail rows from the detail list.
            rows=[row for row in details if str(row.get('changeId')) in parent_ids]
        else:
            rows=query(session,'lanorange',DETAILS[dataset]).get('data')
    if not isinstance(rows,list): raise BillCollectionError('蓝橙全量详情基准未确认')
    ids=[]; groups={}; missing=0
    for row in rows:
        key=str(row.get('id',''))
        if not key: raise BillCollectionError('蓝橙详情缺少唯一编号，不能确认全量')
        ids.append(key)
        city_id=str(row.get('cityId') or '')
        name=str(row.get('cityName') or '').removesuffix('市')
        if not re.fullmatch(r'\d{1,20}',city_id) or not name:
            missing+=1;continue
        group=groups.setdefault(city_id,{'city':name,'total':0})
        if group['city']!=name: raise BillCollectionError('蓝橙城市编号对应多个名称，不能确认全量')
        group['total']+=1
    if len(ids)!=len(set(ids)): raise BillCollectionError('蓝橙详情基准编号重复，不能确认全量')
    return {'total':len(ids),'identity_digest':hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest(),
            'groups':groups,'unassigned':missing}


def partition_plan(dataset, initial, log, cancelled, months=None):
    cities=load_cities(log,cancelled)
    by_id={code:city for city,code in cities.items()}
    if len(by_id)!=len(cities): raise BillCollectionError('蓝橙城市目录编号重复')
    if dataset not in LISTS:
        if initial['unassigned']:
            raise BillCollectionError(f"蓝橙有 {initial['unassigned']} 条无城市归属资料，分批不能覆盖全量，未发布文件")
        # Include historical cities observed in authorized global detail data.
        groups=initial['groups']; result=[]
        for code,group in groups.items():
            if code in by_id and by_id[code]!=group['city']:
                raise BillCollectionError('蓝橙全量基准与城市目录名称冲突')
            result.append({'id':code,'city':group['city'],'expected':group['total'],'status':'pending'})
        return result
    result=[]
    with authenticated('lanorange',log,cancelled) as session:
        for city,code in cities.items():
            if cancelled.is_set(): raise BillCollectionError('蓝橙城市覆盖核对已取消')
            value=query(session,'lanorange',LISTS[dataset],
                        {**list_params(months),'cityId':code,'cityIds[0]':code}).get('total')
            if type(value) is not int or value < 0: raise BillCollectionError('蓝橙城市分批基准未确认')
            result.append({'id':code,'city':city,'expected':value,'status':'pending' if value else 'empty'})
    covered=sum(item['expected'] for item in result)
    if covered!=initial['total']:
        raise BillCollectionError(f"蓝橙城市分批覆盖 {covered}/{initial['total']} 条；存在未覆盖或无城市归属资料，未发布全量文件")
    return result


def checked_source(directory, dataset, filters, legacy=None):
    info=read_json(directory/'source_receipt.json')
    if info.get('status')!='validated' or info.get('dataset')!=dataset or info.get('filters') not in (filters, legacy):
        raise BillCollectionError('蓝橙已下载资料回执范围不符')
    return Path(verified_file(directory,info)),info


def finish_original(dataset,directory,initial,state,log,cancelled,months=None):
    filters=source_filters(ALL_CITIES,months)
    direct,info=checked_source(directory/'全量原表',dataset,filters,source_filters(ALL_CITIES))
    if info['business_rows']!=initial['total']:raise BillCollectionError('蓝橙全量原表与基准数量不一致')
    if baseline(dataset,log,cancelled,months)!=initial:raise BillCollectionError('蓝橙采集期间数据变化，请重新发起全量任务')
    target=directory/direct.name;shutil.copy2(direct,target)
    info.update(path=target.name,delivery_kind='platform_original',completeness='verified')
    atomic_json(directory/'source_receipt.json',info)
    state.update(phase='complete',delivery_kind='platform_original');atomic_json(directory/'full_strategy.json',state)
    return target


def merge_partitions(dataset, partitions, output, cancelled, months=None):
    """Copy typed cells; city originals remain byte-for-byte unchanged."""
    book=Workbook(write_only=True); targets={}; headers={}; counts=Counter(); excluded=0
    try:
        for item,path in partitions:
            source=load_workbook(path,read_only=True,data_only=False)
            try:
                selected=0
                for sheet in source:
                    if sheet.sheet_state!='visible':continue
                    rows=sheet.iter_rows(); header=tuple(cell.value for cell in next(rows,[]))
                    columns=[i for i,value in enumerate(header) if value in ('城市','城市名称')]
                    if not header or not columns: raise BillCollectionError('蓝橙分批文件缺少表头或城市字段，未生成全量合并表')
                    key=sheet.title
                    if key not in targets:
                        targets[key]=book.create_sheet(key[:31]);headers[key]=header
                        targets[key].append(list(header))
                    if headers[key]!=header: raise BillCollectionError('蓝橙城市原表字段不一致，未生成全量合并表')
                    for row in rows:
                        if cancelled.is_set(): raise BillCollectionError('蓝橙全量合并已取消')
                        if not any(cell.value is not None for cell in row):continue
                        if any(str(row[i].value or '').removesuffix('市')!=item['city'].removesuffix('市') for i in columns):
                            if dataset!='lanorange_batch_quit': raise BillCollectionError('蓝橙城市分批包含其他城市，未生成全量合并表')
                            excluded+=1;continue
                        if counts[key]>=1_048_575: raise BillCollectionError('蓝橙合并超过 Excel 单表行数上限，分批原表已保留')
                        target=targets[key]; values=[]
                        for cell in row:
                            copied=WriteOnlyCell(target,cell.value);copied.data_type=cell.data_type
                            if cell.number_format is not None: copied.number_format=cell.number_format
                            values.append(copied)
                        target.append(values);counts[key]+=1;selected+=1
                if selected!=item['expected']:
                    raise BillCollectionError(f"蓝橙{item['city']}分批有效记录 {selected}/{item['expected']} 条，未发布全量文件")
            finally:source.close()
        if not targets: raise BillCollectionError('蓝橙没有可校验的分批表头，未生成空壳全量文件')
        note=book.create_sheet('全量下载说明')
        note.append(['文件性质','系统合并；不是平台单次导出的原始表'])
        note.append(['数据范围','账号全部可访问数据；全部状态、' + ('日期 ' + '、'.join(months) if months else '不按日期筛选')])
        note.append(['完整性','所有分批及全量数量核对通过；城市原始表保留于后台'])
        note.append(['跨城市批次记录','原始表保持原样；合并时按行城市归属纳入，排除数：'+str(excluded)])
        note.append(['城市','城市ID','有效记录数'])
        for item,_ in partitions:note.append([item['city'],item['id'],item['expected']])
        book.save(output)
        return sum(counts.values()),excluded
    finally:book.close()


def collect_full(dataset, directory, log, cancelled, resume=None, months=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    strategy_file=directory/'full_strategy.json'
    filters=source_filters(ALL_CITIES,months);legacy=source_filters(ALL_CITIES)
    if resume:
        source=Path(resume)
        if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
            raise BillCollectionError('蓝橙恢复目录包含不安全路径')
        source=source.resolve()
        if source!=directory.resolve():shutil.copytree(source,directory,dirs_exist_ok=True)
    try:
        if (directory/'source_receipt.json').exists():
            path,info=checked_source(directory,dataset,filters,legacy)
            log('[恢复] 复用已完整校验的全量成品，不重新提交导出')
            return path
        if strategy_file.exists():
            state=read_json(strategy_file)
            if (state.get('version')!=1 or state.get('dataset')!=dataset
                    or state.get('months')!=months): raise BillCollectionError('蓝橙全量续作范围无效')
            initial=state['baseline']
            if state.get('phase')=='full' and (directory/'全量原表/source_receipt.json').exists():
                return finish_original(dataset,directory,initial,state,log,cancelled,months)
        else:
            initial=baseline(dataset,log,cancelled,months)
            state={'version':1,'dataset':dataset,'baseline':initial,'phase':'full','partitions':[],
                   'months':months}
            atomic_json(strategy_file,state)
            try:
                direct=collect(dataset,directory/'全量原表',log,cancelled,months=months)
                return finish_original(dataset,directory,initial,state,log,cancelled,months)
            except Exception as exc:
                ledger=directory/'全量原表/http_submission.json'
                receipt=read_json(ledger) if ledger.exists() else {}
                allowed=(not cancelled.is_set() and '采集期间数据变化' not in str(exc)
                         and (receipt.get('http_status')==200 or receipt.get('submission_state')=='submitted'))
                state.update(phase='partition' if allowed else 'blocked',full_error=str(exc),fallback_allowed=allowed)
                atomic_json(strategy_file,state)
                if not allowed:raise
                log('[下载] 全量原表未完成，切换后台城市分批；不重复全量请求')
        if not state.get('fallback_allowed'): raise BillCollectionError('蓝橙原请求状态未确认，不能自动重复提交，请检查回执')
        if not state['partitions']:
            state['partitions']=partition_plan(dataset,initial,log,cancelled,months);atomic_json(strategy_file,state)
        completed=[]; failures=[]
        for index,item in enumerate(state['partitions'],1):
            if cancelled.is_set(): raise BillCollectionError('蓝橙分批下载已取消，已完成批次保留')
            if item['status']=='empty':continue
            base=directory/'城市批次'/item['id'];base.mkdir(parents=True,exist_ok=True)
            existing=base/item.get('attempt','attempt_001')
            try:
                if item['status']=='complete':
                    path,info=checked_source(existing,dataset,source_filters(item['city'],months),
                                             source_filters(item['city']))
                else:
                    # Only an explicitly resumed task starts another attempt.
                    attempt=len(list(base.glob('attempt_*')))+1
                    item['attempt']=f'attempt_{attempt:03d}';existing=base/item['attempt']
                    log(f"[下载] 后台分批 {index}/{len(state['partitions'])}：{item['city']}")
                    path=collect(dataset,existing,log,cancelled,city=item['city'],city_id=item['id'],months=months)
                    _,info=checked_source(existing,dataset,source_filters(item['city'],months),
                                          source_filters(item['city']))
                    actual=sum(s.get('selected_rows',0) for s in info['sheets'] if s.get('state')=='visible')
                    if actual!=item['expected']: raise BillCollectionError(f"该城市分批记录 {actual}/{item['expected']} 条，未完整")
                    item.update(status='complete',error='')
                completed.append((item,path))
            except Exception as exc:
                item.update(status='failed',error=str(exc));failures.append(item['city'])
            atomic_json(strategy_file,state)
        if failures: raise BillCollectionError('蓝橙全量未完整：'+ '、'.join(failures)+' 分批失败；成功批次保留，可仅补失败部分')
        if baseline(dataset,log,cancelled,months)!=initial: raise BillCollectionError('蓝橙分批期间全量基准发生变化，未发布合并文件')
        target=directory/(DATASETS[dataset][0]+'_系统合并.xlsx')
        rows,excluded=merge_partitions(dataset,completed,target,cancelled,months)
        if rows!=initial['total']: raise BillCollectionError('蓝橙合并数量与全量基准不一致，未发布文件')
        with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        info={'dataset':dataset,'status':'validated','filters':filters,'scope':'all_authorized_data',
              'path':target.name,'bytes':target.stat().st_size,'sha256':digest,
              'business_rows':rows,'original_unchanged':False,'delivery_kind':'system_merged','completeness':'verified',
              'query_total':initial['total'],'excluded_batch_rows':excluded,'cities':[i['city'] for i,_ in completed]}
        atomic_json(directory/'source_receipt.json',info)
        state.update(phase='complete',delivery_kind='system_merged');atomic_json(strategy_file,state)
        return target
    except Exception as exc:
        state=read_json(strategy_file) if strategy_file.exists() else {}
        if state:
            state.update(error=str(exc));atomic_json(strategy_file,state)
        error=BillCollectionError(str(exc) if isinstance(exc,BillCollectionError) else '蓝橙全量下载未完整，分批回执已保留')
        error.download_submission_state='unknown' if strategy_file.exists() else 'not_submitted'
        raise error from None
