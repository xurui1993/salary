import csv
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from payroll_unified_download import execute
from download_service import DownloadCancelled
from download_service import _requested_items


class SourceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'task_kind':'payroll_source','payroll_unified':True,'payroll_scope_mode':'single','exclude_separation':False,'lanorange_by_city':True,
                     'cities':['测试城'],'datasets':['delivery_fee','payment_binding','penalty','lanorange_part_price'],
                     'months':['2026-10'],'start':'2026-10-01','end':'2026-10-15'}

    def publish(self,child,root,changed):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        dataset=child['datasets'][0];path=root/(dataset+'.csv')
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['骑手ID','日期','团队名称']);writer.writerow(['1','2026-10-01','普通站'])
        description={**_requested_items(child)[0],'relative_path':path.name}
        changed({**description,'status':'success','files':[description]})

    def test_binding_verification_waits_and_continues_before_other_sources(self):
        calls=[];updates=[];logs=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            self.assertEqual(len(child['datasets']),1);kind=child['datasets'][0];calls.append(kind)
            if kind=='payment_binding':
                changed({'_run_event':True,'status':'waiting_login','phase':'waiting_manual'})
                self.assertFalse(cancelled.is_set())
            self.assertFalse(cancelled.is_set());self.publish(child,root,changed);return []
        with patch('download_service.execute_downloads',side_effect=provider):
            files=execute(self.config,self.root,logs.append,threading.Event(),updates.append)
        self.assertEqual(calls,['payment_binding','delivery_fee','penalty','lanorange_part_price'])
        self.assertEqual({entry['dataset'] for entry in files},set(self.config['datasets']))
        self.assertTrue(any(entry['status']=='waiting_login' and entry['payroll_verification_required'] for entry in updates))
        self.assertFalse(any(entry['status']=='error' for entry in updates))

    def test_curated_item_error_is_retained_and_does_not_stop_other_items(self):
        updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            if child['datasets']==['penalty']:
                changed({'city':'测试城','dataset':'penalty','start':child['start'],'end':child['end'],
                         'status':'error','phase':'failed','error':'平台导出文件下载超时'})
            else:self.publish(child,root,changed)
            return []
        with patch('download_service.execute_downloads',side_effect=provider):
            files=execute(self.config,self.root,lambda *_:None,threading.Event(),updates.append)
        failure=next(entry for entry in updates if entry.get('dataset')=='penalty' and entry['status']=='error')
        self.assertEqual(failure['error'],'平台导出文件下载超时')
        self.assertEqual(len(files),3)

    def test_dependency_authentication_is_reported_on_its_parent_material(self):
        updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            if child['datasets']==['payment_binding']:
                changed({'city':'测试城','dataset':'rider_info','start':child['start'],'end':child['end'],
                         'status':'waiting_login','phase':'waiting_manual'})
                raise DownloadCancelled('dependency auth')
            self.publish(child,root,changed);return []
        from parttime_source import SourceError
        with patch('download_service.execute_downloads',side_effect=provider), self.assertRaisesRegex(SourceError,'未生成工资表'):
            execute(self.config,self.root,lambda *_:None,threading.Event(),updates.append)
        waiting=next(entry for entry in updates if entry['status']=='waiting_login')
        self.assertEqual(waiting['dataset'],'payment_binding')
        self.assertTrue(waiting['payroll_verification_required'])

    def test_unknown_errors_never_persist_private_payloads(self):
        logs=[];updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            if child['datasets']==['penalty']:raise RuntimeError('token=private https://secret.invalid 15171558368')
            self.publish(child,root,changed);return []
        with patch('download_service.execute_downloads',side_effect=provider):
            execute(self.config,self.root,logs.append,threading.Event(),updates.append)
        rendered=repr(logs)+repr(updates)
        for private in ('private','secret.invalid','15171558368'):self.assertNotIn(private,rendered)
        self.assertTrue(any(entry.get('dataset')=='penalty' and entry['status']=='error' for entry in updates))

    def test_user_stop_never_continues_to_another_source(self):
        stop=threading.Event();calls=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            calls.append(child['datasets'][0]);stop.set();raise DownloadCancelled('任务已停止')
        with patch('download_service.execute_downloads',side_effect=provider),self.assertRaises(DownloadCancelled):
            execute(self.config,self.root,lambda *_:None,stop,lambda *_:None)
        self.assertEqual(calls,['payment_binding'])

    def test_fraud_and_problem_share_one_collection_pass(self):
        self.config['datasets']=['delivery_fee','fraud','problem','penalty']
        calls=[];updates=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            calls.append(list(child['datasets']))
            for description in _requested_items(child):
                path=Path(root)/(description['dataset']+'.csv')
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('w',encoding='utf-8-sig',newline='') as stream:
                    writer=csv.writer(stream);writer.writerow(['骑手ID','日期','团队名称']);writer.writerow(['1','2026-10-01','普通站'])
                changed({**description,'status':'success','files':[{**description,'relative_path':path.name}]})
            return []
        with patch('download_service.execute_downloads',side_effect=provider):
            files=execute(self.config,self.root,lambda *_:None,threading.Event(),updates.append)
        self.assertEqual(calls,[['delivery_fee'],['fraud','problem'],['penalty']])
        self.assertEqual({entry['dataset'] for entry in files},{'delivery_fee','fraud','problem','penalty'})
        self.assertFalse(any(entry.get('status')=='error' for entry in updates))

    def test_single_order_kind_keeps_its_own_batch(self):
        self.config['datasets']=['fraud']
        calls=[]
        def provider(child,root,log,cancelled,changed,runner_factory=None):
            calls.append(list(child['datasets']));return []
        with patch('download_service.execute_downloads',side_effect=provider):
            execute(self.config,self.root,lambda *_:None,threading.Event(),lambda *_:None)
        self.assertEqual(calls,[['fraud']])
