import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from delivery_store import DeliveryStore,digest,delivery_bundle,external_delivery
import download_jobs as jobs
import download_records as records
from test_download_jobs import CONFIG,make_file
import migrate_flat_deliveries as migration


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.store=DeliveryStore(self.root/'db/deliveries.sqlite3',self.root/'outputs')
    def source(self,name='result.xlsx',content=b'one'):
        path=self.root/'staging'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content);return path
    def publish(self,entries,key='task'):
        return self.store.publish(key,'2026-10-31T01:02:03+00:00','业务报表',entries)
    def entry(self,path,run='run',file='file',**extra):
        return dict(run_id=run,id=file,path=str(path),city='泉州',**extra)

    def test_new_payroll_publishes_only_two_workbooks_and_keeps_legacy_deliveries(self):
        from openpyxl import Workbook
        import payroll_inputs as payroll
        key='b'*32
        folder=self.root/'uploads/shared'/('payroll_'+key);folder.mkdir(parents=True)
        output=self.root/'outputs/payroll_batches/shared'/key/'attempt_1';output.mkdir(parents=True)
        for name in ('工资表.xlsx','蓝橙无单价&未绑名单.xlsx'):
            book=Workbook();book.save(output/name);book.close()
        (output/'private.json').write_text('internal proof')
        state=dict(id=key,created_at='2026-11-02T01:00:00Z',plan={'city':'测试城','start':'2026-10-01'},
                   result={'output':str(output),'delivery_layout':'payroll_workbooks_v1'})
        with patch.object(payroll,'ROOT',self.root),patch.object(payroll,'delivery_store',return_value=self.store):
            destination=payroll.publish_result('shared',folder,state)
            self.assertEqual({p.name for p in destination.iterdir()},{'工资表.xlsx','蓝橙无单价&未绑名单.xlsx'})
            target,_=delivery_bundle(self.store,'payroll:shared:'+key)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()),{'工资表.xlsx','蓝橙无单价&未绑名单.xlsx'})
            self.assertEqual(payroll.publish_result('shared',folder,state),destination)
            self.assertTrue((output/'private.json').exists())
            with self.store.db() as db:
                self.assertEqual(len(db.execute('SELECT sha256 FROM artifacts WHERE task_key=?',('payroll:shared:'+key,)).fetchall()),2)
    def manager(self,flat=True):
        def executor(config,folder,log,cancelled,update):
            raw=folder/'原始资料/泉州/rider_info';raw.mkdir(parents=True)
            (raw/'source.xlsx').write_bytes(b'platform source')
            (raw/'receipt.json').write_text('{"token":"never export"}')
            duplicate=raw.parent/'rider_detail';duplicate.mkdir();(duplicate/'source.xlsx').write_bytes(b'platform source')
            generated=raw.parent/'generated';generated.mkdir();(generated/'result.xlsx').write_bytes(b'generated copy')
            entry=make_file(folder,config);update({**entry,'status':'success'});return [entry]
        manager=jobs.DownloadManager(self.root/'db/tasks.sqlite3',self.root/'outputs',executor,flat_delivery=flat)
        self.addCleanup(manager.shutdown)
        created=manager.create('tester',CONFIG)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            run=manager.get_run('tester',created['id'])
            if run['status'] in jobs.FINAL_STATUSES:
                # Terminal business status precedes atomic delivery publication.
                folder=manager.deliveries.directory(run['id']) if flat else None
                if not flat or folder and any(path.is_file() for path in folder.iterdir()):return manager,run
            time.sleep(.02)
        self.fail('publication did not finish')
    def test_flat_default_keeps_sources_private_and_downloads_verified(self):
        manager,run=self.manager()
        folder=manager.deliveries.directory(run['id']);workspace=manager._run_directory('tester',run['id'])
        self.assertEqual(folder.parent.parent,manager.output_root)
        self.assertRegex(folder.parent.name,r'^\d{6}$')
        self.assertRegex(folder.name,r'^10月配送费\d{12}$')
        self.assertTrue(workspace.is_relative_to(manager.workspace_root))
        self.assertFalse(any(path.is_dir() for path in folder.iterdir()))
        file=run['files'][0];path,name=manager.get_file('tester',run['id'],file['id'])
        self.assertEqual(path.parent,folder);self.assertIn('泉州',name)
        self.assertFalse((workspace/'result.csv').exists())
        with self.assertRaises(jobs.DownloadNotFound):manager.get_file('other',run['id'],file['id'])
        bundle,_=manager.get_bundle('tester',run['id'])
        with zipfile.ZipFile(bundle) as archive:
            self.assertNotIn('文件清单.csv',archive.namelist());self.assertTrue(all('/' not in name for name in archive.namelist()))
            self.assertFalse(any(name.endswith('.json') for name in archive.namelist()))
        bundle.unlink()
        sources,_=records.record_bundle(manager,'tester',run['id'],purpose='sources')
        with zipfile.ZipFile(sources) as archive:
            names=archive.namelist();self.assertEqual(len(names),2);self.assertIn('来源清单.csv',names)
            self.assertTrue(all('/' not in name for name in names))
        sources.unlink()
        path.write_bytes(b'changed')
        with self.assertRaises(jobs.DownloadNotFound):manager.get_file('tester',run['id'],file['id'])
    def test_same_names_are_flat_and_never_overwrite_unregistered_files(self):
        a=self.source('a.xlsx');b=self.source('b.xlsx',b'two')
        folder=self.publish([self.entry(a,file='1',name='报表.xlsx'),self.entry(b,file='2',name='报表.xlsx')])
        self.assertEqual(len(list(folder.glob('*.xlsx'))),2)
        self.assertEqual({p.read_bytes() for p in folder.glob('*.xlsx')},{b'one',b'two'})
        c=self.source('c.xlsx',b'three');(folder/'泉州_新表.xlsx').write_bytes(b'user file')
        with self.assertRaises(ValueError):self.publish([self.entry(c,file='3',name='新表.xlsx')])
        self.assertEqual(c.read_bytes(),b'three');self.assertEqual((folder/'泉州_新表.xlsx').read_bytes(),b'user file')
    def test_superseded_results_are_retained_privately_and_mutation_blocks_overwrite(self):
        a=self.source();folder=self.publish([self.entry(a,run='payroll:shared:task')])
        old=self.store.location('payroll:shared:task','file')
        b=self.source('new.xlsx',b'two');self.publish([self.entry(b,run='retry',name='result.xlsx')])
        self.assertEqual(self.store.location('payroll:shared:task','file').read_bytes(),b'one')
        self.assertTrue(self.store.location('payroll:shared:task','file').is_relative_to(self.store.private))
        current=self.store.location('retry','file');current.write_bytes(b'user modification')
        c=self.source('next.xlsx',b'three')
        with self.assertRaises(ValueError):self.publish([self.entry(c,run='retry',name='result.xlsx')])
        self.assertEqual(current.read_bytes(),b'user modification')
        self.assertEqual(c.read_bytes(),b'three')
    def test_journal_recovers_interrupted_rename_before_index_commit(self):
        a=self.source();original=a
        native=self.store.location
        with patch.object(self.store,'location',side_effect=RuntimeError('simulated interruption')):
            with self.assertRaises(RuntimeError):self.publish([self.entry(a)])
        # Inject a failure after the physical move and before artifact index save.
        from unittest.mock import MagicMock
        original_transfer=self.store._transfer
        def interrupted(*args):original_transfer(*args);raise RuntimeError('power loss')
        with patch.object(self.store,'_transfer',side_effect=interrupted):
            with self.assertRaises(RuntimeError):self.publish([self.entry(a)])
        self.assertFalse(original.exists());recovered=self.store.relocated(original)
        self.assertIsNotNone(recovered);self.assertEqual(recovered.read_bytes(),b'one')
        self.publish([self.entry(recovered)])
        self.assertEqual(self.store.location('run','file'),recovered)
    def test_external_deliveries_and_zip_exclude_metadata_and_tampering(self):
        a=self.source();self.source('technical.json',b'secret')
        folder=external_delivery('payroll:shared:abcd','2026-10-31T01:00:00Z','薪资核算',a.parent,store=self.store)
        self.assertEqual({p.suffix for p in folder.iterdir()},{'.xlsx'})
        self.assertFalse((folder/'文件清单.csv').exists())
        bundle,_=delivery_bundle(self.store,'payroll:shared:abcd');bundle.unlink()
        next(folder.glob('*.xlsx')).write_bytes(b'altered')
        with self.assertRaises(ValueError):delivery_bundle(self.store,'payroll:shared:abcd')
        self.assertFalse(list((self.store.private/'bundles').glob('*.zip')))
    def test_sequence_collision_suffix_for_download_folders(self):
        created='2026-10-31T01:02:03+00:00'
        folders=[]
        for index in range(3):
            source=self.source(f'c{index}.xlsx',f'content{index}'.encode())
            folders.append(self.store.publish(str(index)*32,created,'业务报表',
                                              [self.entry(source,file=str(index))],sequence_collision=True))
        self.assertEqual([folder.name for folder in folders],['业务报表','业务报表_2','业务报表_3'])
        default_source=self.source('d.xlsx',b'four')
        default=self.store.publish('d'*32,created,'业务报表',[self.entry(default_source,file='4')])
        self.assertRegex(default.name,r'^业务报表_\d{8}-\d{6}_[0-9A-F]{6}$')

    def test_historical_migration_has_verified_backup_and_preserves_registry(self):
        manager,run=self.manager(flat=False);manager.shutdown()
        report=migration.migrate(manager.db_path,manager.output_root,True)
        self.assertTrue(report['applied']);self.assertEqual(report['eligible'],1)
        backup=Path(report['backup']);self.assertTrue((backup/'tasks.sqlite3').is_file())
        self.assertTrue(report['tasks'][0]['backup_verified'])
        restored=jobs.DownloadManager(manager.db_path,manager.output_root);self.addCleanup(restored.shutdown)
        self.assertEqual(restored.get_file('tester',run['id'],run['files'][0]['id'])[0].read_text(), 'synthetic,data\n')
        self.assertTrue((restored._run_directory('tester',run['id'])/'原始资料/泉州/rider_info/source.xlsx').is_file())
    def test_configured_root_change_preserves_existing_delivery_location(self):
        source=self.source();folder=self.publish([self.entry(source)])
        changed=DeliveryStore(self.store.path,self.root/'new_outputs')
        self.assertEqual(changed.directory('task'),folder)
        self.assertEqual(changed.location('run','file').read_bytes(),b'one')
        new=self.source('new.xlsx',b'two')
        next_folder=changed.publish('new','2026-10-31T00:00:00Z','新任务',[self.entry(new,run='new')])
        self.assertEqual(next_folder.parent,changed.root/'261031')
    def test_failed_migration_rolls_back_bytes_paths_and_index(self):
        manager,run=self.manager(flat=False);source=manager._run_directory('tester',run['id']);before=migration.inventory(source);manager.shutdown()
        with patch.object(jobs.DownloadManager,'publish_delivery',side_effect=RuntimeError('simulated disk failure')):
            with self.assertRaises(RuntimeError):migration.migrate(manager.db_path,manager.output_root,True)
        self.assertEqual(migration.inventory(source),before)
        restored=jobs.DownloadManager(manager.db_path,manager.output_root,flat_delivery=False);self.addCleanup(restored.shutdown)
        self.assertEqual(restored._run_directory('tester',run['id']),source)
        self.assertIsNone(restored.deliveries.directory(run['id']))
    def test_migration_copy_fallback_verifies_and_removes_only_backed_up_originals(self):
        manager,run=self.manager(flat=False);source=manager._run_directory('tester',run['id']);manager.shutdown()
        replace=migration.os.replace
        def deny_directory_rename(original,target):
            if Path(original)==source:raise PermissionError('simulated Explorer handle')
            return replace(original,target)
        with patch.object(migration.os,'replace',side_effect=deny_directory_rename):
            report=migration.migrate(manager.db_path,manager.output_root,True)
        self.assertTrue(report['applied']);self.assertTrue(report['tasks'][0]['copy_fallback'])
        self.assertEqual(report['tasks'][0]['cleanup_pending'],[])
        self.assertFalse(source.exists())
        self.assertTrue((Path(report['backup'])/'originals'/run['id']).is_dir())
    def test_interrupted_workspace_copy_keeps_original_and_rolls_back_index(self):
        manager,run=self.manager(flat=False);source=manager._run_directory('tester',run['id']);before=migration.inventory(source);manager.shutdown()
        replace=migration.os.replace;copytree=migration.shutil.copytree
        def deny(original,target):
            if Path(original)==source:raise PermissionError('rename denied')
            return replace(original,target)
        def copy_then_fail(original,target,*args,**kwargs):
            result=copytree(original,target,*args,**kwargs)
            if Path(target).is_relative_to(manager.workspace_root):raise OSError('simulated interrupted copy')
            return result
        with patch.object(migration.os,'replace',side_effect=deny),patch.object(migration.shutil,'copytree',side_effect=copy_then_fail):
            with self.assertRaises(OSError):migration.migrate(manager.db_path,manager.output_root,True)
        self.assertEqual(migration.inventory(source),before)
        self.assertEqual(len(migration.plan(manager.db_path)),1)

    def test_payroll_publication_and_authorized_endpoint_reject_other_workspaces(self):
        import payroll_inputs as payroll
        import parttime_source
        import download_routes as routes
        from starlette.requests import Request
        from fastapi import HTTPException
        key='a'*32;folder=self.root/'uploads/shared'/('payroll_'+key);folder.mkdir(parents=True)
        output=self.root/'outputs/payroll_batches/shared'/key/'2026年/10月/泉州';output.mkdir(parents=True)
        (output/'薪资.xlsx').write_bytes(b'payroll result')
        (output/'proof.json').write_bytes(b'private proof')
        state=dict(id=key,mode='manual',status='calculated',created_at='2026-10-31T01:00:00Z',plan={'city':'泉州','start':'2026-10-01'},result={'output':str(output)})
        payroll.save(folder,state)
        def request(wid):
            return Request({'type':'http','method':'GET','scheme':'http','path':'/api/fengshen-downloads/delivery-download','query_string':b'',
                'headers':[(b'host',b'localhost:3000'),(b'x-workspace-id',wid.encode())],'server':('localhost',3000),'client':('127.0.0.1',1234)})
        with patch.object(payroll,'ROOT',self.root),patch.object(parttime_source,'ROOT',self.root):
            response=routes.payroll_delivery_download(request('shared'),batch_id=key)
            with zipfile.ZipFile(response.path) as archive:
                self.assertEqual(set(archive.namelist()),{'薪资.xlsx'})
            asyncio.run(response.background())
            saved=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));delivery=Path(saved['result']['output'])
            self.assertEqual(delivery.parent,self.root/'outputs/fengshen_downloads'/'261031')
            self.assertTrue((output/'proof.json').exists());self.assertFalse((output/'薪资.xlsx').exists())
            with self.assertRaises(HTTPException):routes.payroll_delivery_download(request('other'),batch_id=key)
            with self.assertRaises(HTTPException):routes.payroll_delivery_download(request('shared'),path=str(self.root/'db'))
            response=routes.payroll_delivery_download(request('shared'),path=str(delivery));asyncio.run(response.background())


if __name__=='__main__':unittest.main()
