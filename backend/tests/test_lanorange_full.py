import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import zipfile
from openpyxl import Workbook,load_workbook
sys.path.insert(0,str(Path(__file__).parents[1]))
from fengshen_bill import BillCollectionError,atomic_json
from lanorange_full import collect_full,partition_plan,merge_partitions,baseline
from download_service import validate_request,execute_downloads
from download_jobs import DownloadManager,FINAL_STATUSES
from rider_archive import COLUMNS

KIND='lanorange_rider_archive'


def write_original(root,kind,city,rows):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    book=Workbook();sheet=book.active;sheet.title='骑手档案'
    sheet.append(['项目','城市','站点','骑手ID','姓名','身份证号','合作类型','当前生效兼职价格',
                  '合作日期','推荐人身份证号','三方公司/推荐人','招聘来源','状态','是否寒暑假工'])
    for index in range(rows):
        sheet.append(['U+B',city+'市','站点A','001234567890123456','骑手'+str(index),
                      '460200199001010011','全职',None,None,None,None,'骑手内推','正常','=literal'])
        sheet.cell(sheet.max_row,14).data_type='s'
    options=book.create_sheet('options_0');options.append(['option']);options.sheet_state='hidden'
    file=root/'原表.xlsx';book.save(file);book.close()
    info={'dataset':kind,'path':file.name,'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
          'status':'validated','filters':{} if city=='全部城市' else {'city':city},'business_rows':rows,
          'sheets':[{'name':'骑手档案','rows':rows,'state':'visible','selected_rows':rows}], 'original_unchanged':True}
    atomic_json(root/'source_receipt.json',info);return file


class FullDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);self.root=Path(self.temp.name)
        self.cancel=threading.Event();self.calls=[];self.fail_city=None

    def tearDown(self):self.temp.cleanup()

    def fallback_collect(self,kind,directory,log,cancel,**kwargs):
        city=kwargs.get('city','全部城市');self.calls.append(city)
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        if city=='全部城市' or city==self.fail_city:
            atomic_json(directory/'http_submission.json',{'http_status':200,'submission_state':'unknown'})
            raise BillCollectionError('simulated incomplete stream')
        return write_original(directory,kind,city,2 if city=='泉州' else 1)

    def patches(self,baseline_value=None):
        stack=contextlib.ExitStack()
        stack.enter_context(patch('lanorange_full.collect',side_effect=self.fallback_collect))
        stack.enter_context(patch('lanorange_full.baseline',return_value=baseline_value or {'total':3}))
        stack.enter_context(patch('lanorange_full.load_cities',return_value={'泉州':'101','韶关':'102','其他授权城市':'103'}))
        stack.enter_context(patch('lanorange_full.authenticated',side_effect=lambda *_:contextlib.nullcontext(Mock())))
        stack.enter_context(patch('lanorange_full.query',side_effect=lambda *a,**kw:{'total':{'101':2,'102':1,'103':0}[a[3]['cityId']]}))
        return stack

    def test_direct_full_keeps_platform_bytes_and_never_loads_city_directory(self):
        def direct(kind,directory,*args,**kwargs):return write_original(directory,kind,'全部城市',3)
        with patch('lanorange_full.baseline',return_value={'total':3}),patch('lanorange_full.collect',side_effect=direct), \
             patch('lanorange_full.load_cities',side_effect=AssertionError('unnecessary partition')):
            file=collect_full(KIND,self.root/'direct',lambda *_:None,self.cancel)
        self.assertEqual(file.read_bytes(),(file.parent/'全量原表/原表.xlsx').read_bytes())
        info=json.loads((file.parent/'source_receipt.json').read_text('utf-8'))
        self.assertEqual(info['delivery_kind'],'platform_original');self.assertTrue(info['original_unchanged'])

    def test_fallback_all_cities_one_marked_file_with_typed_cells_and_no_hidden_options(self):
        with self.patches():file=collect_full(KIND,self.root/'fallback',lambda *_:None,self.cancel)
        self.assertEqual(self.calls,['全部城市','泉州','韶关'])
        self.assertIn('系统合并',file.name)
        book=load_workbook(file,read_only=True,data_only=False)
        try:
            self.assertNotIn('options_0',book.sheetnames)
            rows=list(book['骑手档案'].iter_rows())
            self.assertEqual(len(rows),4);self.assertEqual(rows[1][3].value,'001234567890123456')
            self.assertEqual(rows[1][13].value,'=literal');self.assertEqual(rows[1][13].data_type,'s')
        finally:book.close()
        info=json.loads((file.parent/'source_receipt.json').read_text('utf-8'))
        self.assertEqual(info['business_rows'],3);self.assertFalse(info['original_unchanged'])

    def test_resume_only_failed_partition_no_repeat_full_or_successful_city(self):
        self.fail_city='韶关'
        with self.patches():
            with self.assertRaisesRegex(BillCollectionError,'未完整'):
                collect_full(KIND,self.root/'failed',lambda *_:None,self.cancel)
            self.assertFalse((self.root/'failed/source_receipt.json').exists())
            self.fail_city=None
            file=collect_full(KIND,self.root/'resumed',lambda *_:None,self.cancel,self.root/'failed')
        self.assertEqual(self.calls,['全部城市','泉州','韶关','韶关']);self.assertTrue(file.exists())

    def test_uncovered_records_refuse_to_publish_before_partition_exports(self):
        with self.patches({'total':4}):
            with self.assertRaisesRegex(BillCollectionError,'未覆盖'):
                collect_full(KIND,self.root/'gap',lambda *_:None,self.cancel)
        self.assertEqual(self.calls,['全部城市']);self.assertFalse((self.root/'gap/source_receipt.json').exists())

    def test_unassigned_detail_records_are_not_silently_lost(self):
        with patch('lanorange_full.load_cities',return_value={'泉州':'101'}):
            with self.assertRaisesRegex(BillCollectionError,'无城市归属'):
                partition_plan('lanorange_rider_report',{'total':3,'unassigned':1,'groups':{}},lambda *_:None,self.cancel)

    def test_auth_failure_does_not_trigger_mass_partition_exports(self):
        def rejected(kind,directory,*args,**kwargs):
            Path(directory).mkdir(parents=True);atomic_json(Path(directory)/'http_submission.json',{'http_status':403})
            raise BillCollectionError('permission denied')
        with patch('lanorange_full.baseline',return_value={'total':3}),patch('lanorange_full.collect',side_effect=rejected), \
             patch('lanorange_full.load_cities',side_effect=AssertionError('must not export')):
            with self.assertRaisesRegex(BillCollectionError,'permission denied'):
                collect_full(KIND,self.root/'permission',lambda *_:None,self.cancel)

    def test_identity_baseline_counts_authorized_application_details_not_applications_or_orphans(self):
        parents=[{'id':'10'},{'id':'20'}]
        details=[{'id':str(i),'changeId':parent,'cityId':city,'cityName':name}
                 for i,parent,city,name in [(1,'10','101','泉州市'),(2,'10','101','泉州市'),
                                           (3,'20','102','韶关市'),(4,'99','101','泉州市')]]
        with patch('lanorange_full.authenticated',return_value=contextlib.nullcontext(Mock())), \
             patch('lanorange_full.all_list',side_effect=[parents,details]):
            info=baseline('lanorange_identity_change',lambda *_:None,self.cancel)
        self.assertEqual(info['total'],3);self.assertEqual(info['groups']['101']['total'],2)
        self.assertEqual(info['groups']['102']['total'],1)

    def test_completed_original_after_interruption_is_recovered_without_export(self):
        root=self.root/'interrupted';original=write_original(root/'全量原表',KIND,'全部城市',3)
        atomic_json(root/'full_strategy.json',{'version':1,'dataset':KIND,'baseline':{'total':3},'phase':'full','partitions':[]})
        with patch('lanorange_full.baseline',return_value={'total':3}), \
             patch('lanorange_full.collect',side_effect=AssertionError('must not export again')):
            result=collect_full(KIND,self.root/'recovered',lambda *_:None,self.cancel,root)
        self.assertEqual(result.read_bytes(),original.read_bytes())

    def test_data_change_during_partitions_does_not_publish_a_mixed_snapshot(self):
        with self.patches(),patch('lanorange_full.baseline',side_effect=[{'total':3},{'total':4}]):
            with self.assertRaisesRegex(BillCollectionError,'基准发生变化'):
                collect_full(KIND,self.root/'changed',lambda *_:None,self.cancel)
        self.assertFalse((self.root/'changed/source_receipt.json').exists())

    def test_manager_delivers_one_file_and_raw_package_is_owner_isolated(self):
        def execute(config,root,log,cancel,update):
            with self.patches():return execute_downloads(config,root,log,cancel,update)
        manager=DownloadManager(self.root/'db/tasks.sqlite3',self.root/'outputs',execute)
        try:
            run=manager.create('owner',validate_request({'datasets':[KIND]}));deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=manager.get_run('owner',run['id'])
                if run['status'] in FINAL_STATUSES:break
                threading.Event().wait(.02)
            self.assertEqual(run['status'],'success',run.get('error'));self.assertEqual(len(run['files']),1)
            self.assertEqual(run['files'][0]['delivery_kind'],'system_merged')
            delivered,_=manager.get_file('owner',run['id'],run['files'][0]['id'])
            book=load_workbook(delivered,read_only=True,data_only=False)
            try:
                sheet=next(ws for ws in book.worksheets if ws.title.endswith('骑手档案'))
                rows=list(sheet.iter_rows())
                self.assertEqual([cell.value for cell in rows[0]],list(COLUMNS))
                self.assertEqual(len(rows),4)
            finally:book.close()
            bundle,_=manager.get_bundle('owner',run['id'])
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(len(archive.namelist()),1)
                self.assertNotIn('文件清单.csv',archive.namelist())
            raw,_=manager.get_raw_bundle('owner',run['id'])
            with zipfile.ZipFile(raw) as archive:self.assertTrue(any('城市批次' in n for n in archive.namelist()))
            with self.assertRaises(Exception):manager.get_raw_bundle('other',run['id'])
        finally:manager.shutdown()

    def test_manager_retry_retains_full_scope_and_resumes_only_failed_city(self):
        self.fail_city='韶关'
        def execute(config,root,log,cancel,update):
            with self.patches():return execute_downloads(config,root,log,cancel,update)
        manager=DownloadManager(self.root/'retry/tasks.sqlite3',self.root/'retry/outputs',execute)
        def wait(run):
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=manager.get_run('owner',run['id'])
                if run['status'] in FINAL_STATUSES:return run
                threading.Event().wait(.02)
            self.fail('job did not finish')
        try:
            run=wait(manager.create('owner',validate_request({'datasets':[KIND]})))
            self.assertEqual(run['status'],'error');self.assertFalse(run['files'])
            self.assertEqual(run['items'][0]['recovery']['mode'],'resume_existing')
            selection={key:run['items'][0][key] for key in ('city','dataset','start','end')}
            self.fail_city=None
            repaired=wait(manager.retry('owner',run['id'],[selection],request_id='retry-only-missing'))
            self.assertEqual(repaired['status'],'success',repaired.get('error'))
            self.assertTrue(repaired['lanorange_full_delivery']);self.assertEqual(len(repaired['files']),1)
            self.assertEqual(self.calls,['全部城市','泉州','韶关','韶关'])
        finally:manager.shutdown()


if __name__=='__main__':unittest.main()
