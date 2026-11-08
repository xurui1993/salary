import copy,csv,datetime as dt,json,threading,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
from openpyxl import load_workbook
from fengshen_http import FengshenHttpClient,API_METHODS,READ_ONLY_URLS,TEAMS_URL,HttpTransportError
from fengshen_merchant_exports import *
from download_service import validate_request,ValidationError,execute_downloads,_requested_items
from download_jobs import _initial_items


class Fake(FengshenHttpClient):
    def __init__(self):
        self.cancelled=threading.Event();self.agency='2';self.calls=[];self.posts=[];self.urls={};self.download_failure=False;self.unknown=False;self.changed=False;self.bad_dates=False;self.bad_headers=False
        self.records=[dict(id=i,templateId=2751612,invitingParticipantId=1160452791,invitingParticipantName='合成邀请人',invitedParticipantId=1167140117,inviteMobile='13800001234',invitedName='合成新人'+str(i),inviteStatus=1,inviteDate='2026-10-27 16:13:04',entryDate='2026-10-28 09:00:00',entryStatus=0,teamId=917570885,teamName='合成站',entryTeamId=917570885,entryTeamName='',itemVOList=[{'activityId':'a','instanceId':'300000101948977323','startDate':'2026-10-01','endDate':'2026-10-31','inviteStatus':0},{'activityId':'b','instanceId':'300000101948978347','startDate':'2026-10-01','endDate':'2026-11-30','inviteStatus':1}]) for i in range(43)]
    def identity(self):return {'agencyId':self.agency}
    def assert_city(self,agency):
        if agency!=self.agency:raise HttpTransportError('商家变化')
    def request_json(self,method,url,params=None,body=None,**kwargs):
        self.calls.append((method,url,copy.deepcopy(params or body)))
        if url==INVITE_AUTH:return {'data':{}}
        if url==INVITE_TEAMS:return {'data':[{'id':1,'name':'合成站'},{'id':9,'name':'其他商家可见站'}]}
        if url==INVITE_QUERY:
            assert set(params)=={'activityType','stationIds','pageSize','pageNum'} and params['activityType']==26 and json.loads(params['stationIds'])==[1]
            rows=copy.deepcopy(self.records);page=params['pageNum'];size=params['pageSize']
            if self.changed and sum(u==url and b['pageNum']==1 for _,u,b in self.calls)>1:rows[0]['invitedName']='采集中变化'
            return {'data':{'value':rows[(page-1)*size:page*size],'totalItems':len(rows)}}
        if url==TEAMS_URL:return {'result':{'data':[{'id':1,'agencyId':2,'team_name':'合成站'},{'id':9,'agencyId':9,'team_name':'其他商家站点'}]}}
        if url==GRAY_URL:return {'result':{'data':[{'teamId':1,'grayDate':'2026-10-10'}]}}
        if url==ATTENDANCE_EXPORT:
            request=body['params']['request'];assert request['teamIds']==[1];self.posts.append(copy.deepcopy(request))
            if self.unknown:raise HttpTransportError('合成网络中断','submitting','unknown')
            url='https://synthetic.oss-cn-hangzhou.aliyuncs.com/'+request['startDate']+'_'+request['endDate']+'.csv';self.urls[url]=request
            return {'result':{'data':{'url':url}}}
        raise AssertionError(url)
    def download(self,url,path,**kwargs):
        if self.download_failure:self.download_failure=False;raise HttpTransportError('合成文件领取中断','downloading','submitted')
        request=self.urls[url]
        with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['日期','团队ID','骑手ID','骑手姓名','排班状态','完单量','有效在线时长'] if not self.bad_headers else ['其他日期','团队ID','骑手ID','骑手姓名'])
            day=dt.date.fromisoformat(request['startDate']);last=dt.date.fromisoformat(request['endDate'])
            while day<=last:
                writer.writerow(['2000-01-01' if self.bad_dates else day.isoformat(),'1','000000000000000001','合成骑手','已排班','0','00小时30分钟']);day+=dt.timedelta(days=1)


class MerchantTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.api=Fake();self.collector=MerchantCollector(self.api,crypt=lambda value,decrypt=False:value)
    def collect(self,kind=INVITATIONS,folder='raw',resume=None):return self.collector.collect(kind,self.root/folder,'2026-10-01','2026-10-31',resume)
    def test_invitation_all_pages_no_filters_and_parallel_gift_lines(self):
        path=self.collect();book=load_workbook(path,read_only=True);self.addCleanup(book.close);rows=list(book['邀请记录'].values);self.assertEqual(list(rows[0]),HEADERS);self.assertEqual(len(rows),44);self.assertEqual(rows[1][0],MERCHANT);self.assertEqual(rows[1][10],'未入职');self.assertEqual(rows[1][17].count('\n'),1);self.assertEqual(rows[1][18],'任务冲单中\n任务审核中');self.assertFalse(self.api.posts)
        self.assertEqual([b['pageNum'] for _,u,b in self.api.calls if u==INVITE_QUERY],[1,2,3,1])
        self.assertEqual(book['采集记录']['D5'].value,'全量记录（不按日期筛选）');self.assertNotIn('start',book['采集记录']['B2'].value)
    def test_invitation_shows_every_platform_field_with_city_first(self):
        path=self.collect();book=load_workbook(path,read_only=True);self.addCleanup(book.close);rows=list(book['邀请记录'].values)
        self.assertEqual(list(rows[0]),['城市','活动ID','邀请人ID','邀请人','新人ID','新人姓名','新人手机号','邀请状态','邀请时间','入职时间','新人入职状态','邀请团队ID','邀请站点','入职团队ID','入职站点','新人礼活动ID','新人礼实例ID','新人礼活动时间','新人礼达成状态'])
        record=rows[1]
        self.assertEqual(record[:11],(MERCHANT,'2751612','1160452791','合成邀请人','1167140117','合成新人0','13800001234','进行中','2026-10-27 16:13:04','2026-10-28 09:00:00','未入职'))
        self.assertEqual(record[11:15],('917570885','合成站','917570885','-'))
        self.assertEqual(record[15],'a\nb');self.assertEqual(record[16],'300000101948977323\n300000101948978347')
        self.assertEqual(record[17],'2026-10-01至2026-10-31\n2026-10-01至2026-11-30')
    def test_invitation_workbook_uses_attachment_standard_style_and_auto_width(self):
        path=self.collect();wb=load_workbook(path);self.addCleanup(wb.close);sheet=wb['邀请记录']
        self.assertEqual(sheet.freeze_panes,'A2')
        for coord in ('A1','S1'):
            cell=sheet[coord];self.assertEqual((cell.font.name,cell.font.size),('微软雅黑',10.0));self.assertFalse(cell.font.bold)
            self.assertEqual(cell.font.color.theme,1);self.assertEqual(cell.alignment.horizontal,'center');self.assertEqual(cell.alignment.vertical,'center')
            self.assertEqual(cell.fill.fgColor.rgb,'FFF8CBAD')
        cell=sheet['A2'];self.assertEqual((cell.font.name,cell.font.size),('微软雅黑',10.0));self.assertFalse(cell.font.bold);self.assertEqual(cell.alignment.horizontal,'center');self.assertIsNone(cell.fill.patternType)
        widths={k:d.width for k,d in sheet.column_dimensions.items()}
        self.assertTrue(all(width and width>=10 for width in widths.values()))
        self.assertGreaterEqual(widths['G'],len('13800001234')+2)
        self.assertGreaterEqual(widths['B'],len('2751612')+2)
    def test_invitation_keeps_records_with_identical_visible_names_and_zero_status(self):
        self.api.records[1].update({k:v for k,v in self.api.records[0].items() if k!='id'});path=self.collect();wb=load_workbook(path,read_only=True);self.addCleanup(wb.close);self.assertEqual(len(list(wb['邀请记录'].values)),44)
    def test_invitation_changed_or_duplicate_page_is_not_published(self):
        self.api.changed=True
        with self.assertRaises(BillCollectionError):self.collect()
        self.assertFalse((self.root/'raw/result.xlsx').exists())
    def test_empty_invitation_is_valid_only_after_successful_full_query(self):
        self.api.records=[];path=self.collect();wb=load_workbook(path,read_only=True);self.addCleanup(wb.close);self.assertEqual(len(list(wb['邀请记录'].values)),1)
    def test_invitation_zero_and_unknown_status_do_not_turn_into_other_status(self):
        row=invitation_row({**self.api.records[0],'entryStatus':0,'inviteStatus':99});self.assertEqual(row[10],'未入职');self.assertIn('99',row[7]);self.assertEqual(label(3,GIFT_STATUS),'')
    def test_october_segments_cover_every_day_once_and_split_before_gray_boundary(self):
        parts=segments('2026-10-01','2026-10-31',['2026-10-10']);days=[]
        for first,last in parts:
            a,b=dt.date.fromisoformat(first),dt.date.fromisoformat(last);days.extend(a+dt.timedelta(days=i) for i in range((b-a).days+1));self.assertFalse(first<'2026-10-10'<=last)
        self.assertEqual(len(days),31);self.assertEqual(len(set(days)),31);self.assertEqual(len(parts),6)
    def test_attendance_all_current_merchant_teams_and_merged_file(self):
        path=self.collect(ATTENDANCE);wb=load_workbook(path,read_only=True);self.addCleanup(wb.close);rows=list(wb['出勤明细'].values);self.assertEqual(len(rows),32);self.assertEqual(rows[1][2],'000000000000000001');self.assertEqual(rows[-1][0],'2026-10-31');self.assertEqual(len(self.api.posts),6);self.assertEqual(len(list(wb['采集记录'].values)),10)
    def test_explicit_resume_downloads_original_url_without_reexporting_first_segment(self):
        self.api.download_failure=True
        with self.assertRaises(HttpTransportError):self.collect(ATTENDANCE)
        self.assertEqual(len(self.api.posts),1);source=recoverable_source(self.root/'raw',ATTENDANCE,'2026-10-01','2026-10-31');path=self.collect(ATTENDANCE,'recovered',source);self.assertTrue(path.exists());self.assertEqual(len(self.api.posts),6)
    def test_unknown_submission_is_never_repeated_on_restart_or_recovery(self):
        self.api.unknown=True
        with self.assertRaises(HttpTransportError):self.collect(ATTENDANCE)
        self.api.unknown=False
        with self.assertRaises(BillCollectionError):recoverable_source(self.root/'raw',ATTENDANCE,'2026-10-01','2026-10-31')
        with self.assertRaises(HttpTransportError):self.collect(ATTENDANCE)
        self.assertEqual(len(self.api.posts),1)
    def test_completed_segment_is_verified_and_resume_is_local_merge(self):
        self.collect(ATTENDANCE);self.collect(ATTENDANCE,'recovered',self.root/'raw');self.assertEqual(len(self.api.posts),6)
        file=next((self.root/'raw').glob('*/source.bin'));file.write_bytes(b'changed')
        with self.assertRaises(BillCollectionError):recoverable_source(self.root/'raw',ATTENDANCE,'2026-10-01','2026-10-31')
    def test_changed_merchant_does_not_mix_scope_and_does_not_switch_it(self):
        self.collect(ATTENDANCE);self.api.agency='9'
        with self.assertRaises(BillCollectionError):self.collect(ATTENDANCE)
        self.assertEqual(len(self.api.posts),6)
    def test_out_of_period_rows_or_missing_date_header_do_not_publish(self):
        for field in ('bad_dates','bad_headers'):
            self.api=Fake();self.collector=MerchantCollector(self.api,crypt=lambda value,decrypt=False:value);setattr(self.api,field,True)
            with self.assertRaises(HttpTransportError):self.collect(ATTENDANCE,field)
            self.assertFalse((self.root/field/'result.xlsx').exists())
    def test_scope_validator_ignores_invite_dates_and_enforces_attendance_official_window(self):
        today=dt.date(2026,11,1);value=validate_request({'datasets':[INVITATIONS],'cities':[],'start':'bad','end':'bad'},today=today);self.assertEqual(value['cities'],[MERCHANT]);self.assertEqual(value['start'],'2026-11-01')
        with self.assertRaises(ValidationError):validate_request({'datasets':[INVITATIONS,ATTENDANCE],'cities':['伪造站点'],'start':'2026-10-01','end':'2026-10-31'},today=today)
        value=validate_request({'datasets':[INVITATIONS,ATTENDANCE],'cities':[MERCHANT],'start':'2026-10-01','end':'2026-10-31'},today=today);self.assertEqual(value['cities'],[MERCHANT]);self.assertEqual(len(_initial_items(value)),2);self.assertEqual(len(_requested_items(value)),2)
        for payload in ({'datasets':[ATTENDANCE],'start':'2026-10-01','end':'2026-11-01'},{'datasets':[INVITATIONS,'delivery_fee']},{'datasets':[INVITATIONS,{}]}):
            with self.assertRaises((ValidationError,ValueError)):validate_request(payload,today=today)
    def test_verified_http_methods_only_export_is_mutation(self):
        self.assertEqual(API_METHODS[ATTENDANCE_EXPORT],'POST');self.assertNotIn(ATTENDANCE_EXPORT,READ_ONLY_URLS)
        for url in (INVITE_AUTH,INVITE_QUERY,INVITE_TEAMS,GRAY_URL):self.assertIn(url,READ_ONLY_URLS)
    def test_two_download_items_execute_and_publish_inside_normal_download_pipeline(self):
        today=dt.date(2026,11,1);config=validate_request({'datasets':[INVITATIONS,ATTENDANCE],'start':'2026-10-01','end':'2026-10-31'},today=today);config['owner']='synthetic';events=[]
        collector=self.collector
        class Runner:
            def merchant_source(self,*args):return collector.collect(*args)
        @contextmanager
        def factory(*args):yield Runner()
        files=execute_downloads(config,self.root/'task',lambda value:None,self.api.cancelled,events.append,runner_factory=factory)
        self.assertEqual({v['dataset'] for v in files},{INVITATIONS,ATTENDANCE});self.assertEqual(len([v for v in events if v.get('status')=='success']),2);self.assertTrue(all((self.root/'task'/v['relative_path']).is_file() for v in files))
    def test_duplicate_team_names_are_retained_by_distinct_id_without_other_merchants(self):
        value=merchant_teams({'result':{'data':[{'id':1,'agencyId':2,'team_name':'同名站'},{'id':2,'agencyId':2,'team_name':'同名站'},{'id':3,'agencyId':9,'team_name':'其他站'}]}},'2');self.assertEqual(set(value),{'1','2'})

    def test_selected_cities_are_switched_and_archived_without_scope_collision(self):
        class Multi(Fake):
            def select_city(self,agency):
                if agency not in ('2','3'):raise HttpTransportError('无权商家')
                self.agency=agency
            def request_json(self,method,url,**kwargs):
                if url==TEAMS_URL:return {'result':{'data':[{'id':1,'agencyId':int(self.agency),'team_name':'合成站'}]}}
                return super().request_json(method,url,**kwargs)
        self.api=Multi();collector=MerchantCollector(self.api,crypt=lambda value,decrypt=False:value)
        class Runner:
            def merchant_source(self,*args,**kwargs):return collector.collect(*args,**kwargs)
        @contextmanager
        def factory(*args):yield Runner()
        with patch('download_service.city_catalog.selectable_cities',return_value=['深圳','三亚']):
            config=validate_request({'datasets':[INVITATIONS,ATTENDANCE],'cities':['深圳','三亚'],'merchant_by_city':True,'start':'2026-10-01','end':'2026-10-31'},today=dt.date(2026,11,1))
        config['owner']='synthetic';self.assertTrue(config['merchant_by_city']);self.assertEqual(len(_initial_items(config)),4)
        with patch('download_service.cities',return_value={'深圳':'2','三亚':'3'}):
            files=execute_downloads(config,self.root/'multi',lambda *_:None,self.api.cancelled,lambda *_:None,runner_factory=factory)
        self.assertEqual(len(files),5);self.assertEqual({r['city'] for r in files},{'深圳','三亚','多城市'});self.assertEqual(len(self.api.posts),12)
        summary=[r for r in files if r['dataset']=='invitation_summary']
        self.assertEqual(len(summary),1);self.assertEqual(summary[0]['artifact_role'],'summary');self.assertIn('多城市邀请记录汇总',summary[0]['name'])
        from download_jobs import delivery_scope_error
        self.assertIsNone(delivery_scope_error(summary[0],config,'.xlsx'))
        self.assertIsNotNone(delivery_scope_error(summary[0],{**config,'cities':['深圳']},'.xlsx'))
        merged=load_workbook(self.root/'multi'/summary[0]['relative_path'],read_only=True);self.addCleanup(merged.close)
        rows=list(merged['邀请记录汇总'].values);self.assertEqual(list(rows[0]),HEADERS);self.assertEqual(len(rows),87)
        self.assertEqual({row[0] for row in rows[1:]},{'深圳','三亚'})
        a=source_directory(self.root/'multi',ATTENDANCE,'深圳');b=source_directory(self.root/'multi',ATTENDANCE,'三亚')
        self.assertNotEqual(a,b);self.assertEqual(load(a/'scope.json')['agency_id'],'2');self.assertEqual(load(b/'scope.json')['agency_id'],'3')
        recoverable_source(a,ATTENDANCE,'2026-10-01','2026-10-31','深圳')
        with self.assertRaises(BillCollectionError):recoverable_source(a,ATTENDANCE,'2026-10-01','2026-10-31','三亚')

    def test_manager_keeps_city_scope_in_task_fingerprint_and_retry(self):
        from download_jobs import DownloadManager,_fingerprint
        config={'cities':['深圳','三亚'],'datasets':[INVITATIONS],'start':'2026-10-28','end':'2026-10-28','months':['2026-10'],'merchant_by_city':True}
        self.assertNotEqual(_fingerprint(config),_fingerprint({**config,'merchant_by_city':False}))
        started=threading.Event();release=threading.Event()
        def executor(*args):started.set();release.wait(3);return []
        manager=DownloadManager(self.root/'multi-jobs.sqlite3',self.root/'jobs',executor)
        try:
            job=manager.create('owner',config,request_id='multi-city');self.assertTrue(started.wait(1));self.assertTrue(manager.get_run('owner',job['id'])['merchant_by_city'])
            with manager._connection() as db:saved=json.loads(db.execute('SELECT config_json FROM download_runs WHERE id=?',(job['id'],)).fetchone()[0])
            self.assertTrue(saved['merchant_by_city'])
        finally:release.set();manager.shutdown()
    def test_download_manager_recovers_only_original_owner_and_reuses_segment_receipt(self):
        import time
        from download_jobs import DownloadManager,DownloadNotFound,FINAL_STATUSES
        collector=self.collector
        class Runner:
            def merchant_source(self,*args):return collector.collect(*args)
        @contextmanager
        def factory(*args):yield Runner()
        def executor(config,root,log,cancelled,update):return execute_downloads(config,root,log,cancelled,update,runner_factory=factory)
        manager=DownloadManager(self.root/'jobs.sqlite3',self.root/'jobs',executor);self.addCleanup(manager.shutdown)
        config=validate_request({'datasets':[ATTENDANCE],'start':'2026-10-01','end':'2026-10-31'},today=dt.date(2026,11,1))
        def finish(key):
            for _ in range(300):
                value=manager.get_run('owner',key)
                if value['status'] in FINAL_STATUSES:return value
                time.sleep(.01)
            self.fail('Synthetic job did not finish')
        self.api.download_failure=True;job=manager.create('owner',config,request_id='merchant-original');first=finish(job['id']);self.assertEqual(first['items'][0]['recovery']['mode'],'resume_existing');selection={k:first['items'][0][k] for k in ('city','dataset','start','end')}
        with self.assertRaises(DownloadNotFound):manager.retry('other',job['id'],[selection],'merchant-wrong-owner')
        recovered=manager.retry('owner',job['id'],[selection],'merchant-resume');final=finish(recovered['id']);self.assertEqual(final['status'],'success');self.assertEqual(len(self.api.posts),6)
    def test_large_csv_utf8_sample_boundary_and_formula_shaped_text_are_preserved(self):
        from fengshen_merchant_exports import _source_tables
        from tabular_export_workbook import TabularWorkbook
        source=self.root/'utf8.csv';source.write_text('日期,骑手姓名,备注\n2026-10-01,合成,'+'甲'*22000+'\n',encoding='utf-8-sig')
        tables=_source_tables(source,self.root);rows=next(tables);self.assertEqual(next(rows),['日期','骑手姓名','备注']);self.assertEqual(len(next(rows)[2]),22000);tables.close()
        output=self.root/'literal.xlsx'
        with TabularWorkbook(output,['编号','内容'],'测试','合成') as book:book.append(['000000000000000001','=1+1']);book.finish([])
        wb=load_workbook(output,read_only=True);self.addCleanup(wb.close);self.assertEqual(wb['测试']['B2'].data_type,'s');self.assertEqual(wb['测试']['A2'].value,'000000000000000001');self.assertIn('aero-rush.ele.me',wb['采集记录']['B1'].value)
    def test_platform_xlsx_false_declared_dimension_is_read_by_content(self):
        import os,re,zipfile
        from openpyxl import Workbook
        from fengshen_merchant_exports import _source_tables
        source=self.root/'false_dimension.xlsx'
        book=Workbook();sheet=book.active;sheet.title='出勤明细数据'
        sheet.append(['站点ID','骑手姓名','考勤日期','完单量'])
        for n in range(3):sheet.append([str(917578910+n),'合成骑手'+str(n),'2026-10-0'+str(n+1),str(n)])
        book.save(source)
        rewritten=self.root/'rewritten.xlsx'
        with zipfile.ZipFile(source) as origin,zipfile.ZipFile(rewritten,'w',zipfile.ZIP_DEFLATED) as target:
            for item in origin.infolist():
                data=origin.read(item.filename)
                if item.filename=='xl/worksheets/sheet1.xml':data=re.sub(rb'<dimension ref="[^"]+"/>',b'<dimension ref="A1"/>',data)
                target.writestr(item,data)
        os.replace(rewritten,source)
        tables=_source_tables(source,self.root);rows=next(tables)
        self.assertEqual(next(rows),['站点ID','骑手姓名','考勤日期','完单量']);self.assertEqual(next(rows)[2],'2026-10-01');self.assertEqual(next(rows)[1],'合成骑手1');tables.close()
    def test_manager_recovery_accepts_flat_workspace_archive_root(self):
        import time
        from download_jobs import DownloadManager,FINAL_STATUSES
        collector=self.collector
        class Runner:
            def merchant_source(self,*args):return collector.collect(*args)
        @contextmanager
        def factory(*args):yield Runner()
        def executor(config,root,log,cancelled,update):return execute_downloads(config,root,log,cancelled,update,runner_factory=factory)
        manager=DownloadManager(self.root/'db'/'tasks.sqlite3',self.root/'outputs',executor);self.addCleanup(manager.shutdown)
        config=validate_request({'datasets':[ATTENDANCE],'start':'2026-10-01','end':'2026-10-31'},today=dt.date(2026,11,1))
        def finish(key):
            for _ in range(300):
                value=manager.get_run('owner',key)
                if value['status'] in FINAL_STATUSES:return value
                time.sleep(.01)
            self.fail('Synthetic job did not finish')
        self.api.download_failure=True;job=manager.create('owner',config,request_id='merchant-original');first=finish(job['id'])
        self.assertEqual(first['items'][0]['recovery']['mode'],'resume_existing')
        selection={k:first['items'][0][k] for k in ('city','dataset','start','end')}
        recovered=manager.retry('owner',job['id'],[selection],'merchant-resume');final=finish(recovered['id'])
        self.assertEqual(final['status'],'success');self.assertEqual(final['items'][0]['status'],'success');self.assertEqual(len(self.api.posts),6)
    def test_hours_value_converts_and_rejects_format_drift(self):
        self.assertEqual(hours_value('02小时52分钟'),2.87);self.assertEqual(hours_value('00小时18分钟'),0.3)
        self.assertIsNone(hours_value(None));self.assertIsNone(hours_value(''))
        with self.assertRaises(BillCollectionError):hours_value('2小时52分')
    def test_attendance_publishes_yahei_centered_hours_column(self):
        path=self.collect(ATTENDANCE);wb=load_workbook(path);self.addCleanup(wb.close)
        sheet=wb['出勤明细']
        self.assertEqual(sheet.max_column,8);self.assertEqual(sheet.cell(1,8).value,'有效在线时长')
        self.assertEqual(sheet['H2'].value,0.5);self.assertEqual(sheet['H2'].number_format,'0.00')
        for coord in ('A1','H1'):
            cell=sheet[coord];self.assertEqual((cell.font.name,cell.font.size),('微软雅黑',10.0));self.assertFalse(cell.font.bold)
            self.assertEqual(cell.font.color.theme,1);self.assertEqual(cell.alignment.horizontal,'center');self.assertEqual(cell.alignment.vertical,'center')
        self.assertEqual(sheet['A1'].fill.fgColor.rgb,'FFFCE4D3');self.assertEqual(sheet['H1'].fill.fgColor.rgb,'FFFFFF00')
        cell=sheet['A2'];self.assertEqual((cell.font.name,cell.font.size),('微软雅黑',10.0));self.assertFalse(cell.font.bold);self.assertEqual(cell.alignment.horizontal,'center');self.assertIsNone(cell.fill.patternType)
        self.assertEqual(sheet['H2'].font.name,'微软雅黑');self.assertEqual(sheet['H2'].alignment.horizontal,'center')
        self.assertEqual(sheet.freeze_panes,'A2');self.assertIsNone(sheet.auto_filter.ref);self.assertIn(sheet.sheet_view.showGridLines,(None,True))
        self.assertEqual(sheet.sheet_format.defaultRowHeight,16.5);self.assertIsNone(sheet.row_dimensions[2].height)
        widths={k:d.width for k,d in sheet.column_dimensions.items()}
        self.assertEqual(widths['A'],10.5);self.assertEqual(widths['B'],22);self.assertEqual(widths['D'],16.125);self.assertEqual(widths['G'],8);self.assertEqual(widths['H'],8)
    def test_wide_tables_and_excel_row_limit_split_without_losing_columns(self):
        from tabular_export_workbook import TabularWorkbook
        output=self.root/'wide.xlsx';headers=['列'+str(n) for n in range(28)]
        with TabularWorkbook(output,headers,'明细','合成',row_limit=3) as book:
            for n in range(3):book.append(list(range(28)))
            book.finish([])
        wb=load_workbook(output,read_only=False);self.addCleanup(wb.close);self.assertEqual(wb.sheetnames,['明细','明细2','采集记录']);self.assertEqual(wb['明细']['AB3'].value,27);self.assertEqual(wb['明细2']['AB2'].value,27);self.assertEqual(wb['明细'].auto_filter.ref,'A1:AB3')
    def test_attendance_preserves_identical_source_rows_without_business_deduplication(self):
        original=self.api.download
        def duplicate(url,path,**kwargs):
            original(url,path,**kwargs)
            with Path(path).open('r',encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
            with Path(path).open('a',encoding='utf-8',newline='') as stream:csv.writer(stream).writerow(rows[1])
        self.api.download=duplicate;output=self.collect(ATTENDANCE);wb=load_workbook(output,read_only=True);self.addCleanup(wb.close);self.assertEqual(len(list(wb['出勤明细'].values)),38)


if __name__=='__main__':unittest.main()
