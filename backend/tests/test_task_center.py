import copy
from contextlib import contextmanager
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_center as center


def request(method='GET', query='', client='127.0.0.1', origin='http://localhost:3000'):
    return Request({'type':'http','method':method,'scheme':'http','path':'/api/workbench/task-center',
        'query_string':query.encode(), 'server':('localhost',3000), 'client':(client,1234),
        'headers':[(b'host',b'localhost:3000'),(b'origin',origin.encode()),(b'content-type',b'application/json')]})


def record(key, status='success', **extra):
    return dict(id=key, status=status, kind='download', cities=['上海'], datasets=['delivery_fee'],
        files=[], created_at='2026-10-30T20:00:00+00:00', member_ids=[key], **extra)


class SharedListTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.rows=[record('a'),record('b','running'),record('c','waiting_manual'),record('d','needs_review')]
        for target, value in [('ROOT',self.root),('collect',lambda _: (copy.deepcopy(self.rows),[]))]:
            mock=patch.object(center,target,value);mock.start();self.addCleanup(mock.stop)

    def test_shared_persistent_hide_restore_keeps_files_and_original_records(self):
        file=self.root/'result.xlsx';file.write_bytes(b'original evidence')
        before=copy.deepcopy(self.rows)
        self.assertEqual(center.visibility({'ids':['a']},request('POST'))['changed'],1)
        self.assertEqual(center.listing(request())['total'],3)
        self.assertEqual(center.listing(request(client='192.168.1.20', query='archived=1'))['records'][0]['id'],'a')
        self.assertEqual(file.read_bytes(),b'original evidence')
        self.assertEqual(self.rows,before)
        self.assertEqual(center.hidden_ids(),{'a'})
        center.visibility({'ids':['a'],'restore':True},request('POST'))
        self.assertEqual(center.listing(request())['total'],4)

    def test_mixed_active_waiting_and_unknown_rejections_are_atomic(self):
        for key in ['b','c','missing']:
            with self.assertRaises(HTTPException):center.visibility({'ids':['a',key]},request('POST'))
            self.assertEqual(center.hidden_ids(),set())

    def test_active_retry_reappears_and_one_group_covers_all_attempts(self):
        self.rows[0]['member_ids']=['a','retry']
        center.visibility({'ids':['a']},request('POST'))
        self.assertNotIn('a',[r['id'] for r in center.listing(request())['records']])
        self.rows[0]['status']='running'
        self.assertIn('a',[r['id'] for r in center.listing(request())['records']])

    def test_stop_then_hide_waits_for_ack_and_can_restore(self):
        def stop(row,_):
            next(r for r in self.rows if r['id']==row['id'])['status']='cancelling'
        with patch.object(center,'stop_record',side_effect=stop):
            center.visibility({'ids':['b'],'stop_first':True},request('POST'))
        self.assertIn('b',[r['id'] for r in center.listing(request())['records']])
        self.assertNotIn('b',center.hidden_ids())
        self.rows[1]['status']='cancelled'
        self.assertNotIn('b',[r['id'] for r in center.listing(request())['records']])
        self.assertIn('b',[r['id'] for r in center.listing(request(query='archived=1'))['records']])
        center.visibility({'ids':['b'],'restore':True},request('POST'))
        self.assertIn('b',[r['id'] for r in center.listing(request())['records']])

    def test_waiting_payroll_can_be_hidden_and_restored(self):
        self.rows.append(record('payroll_x','awaiting_confirmation'))
        center.visibility({'ids':['payroll_x']},request('POST'))
        self.assertNotIn('payroll_x',[r['id'] for r in center.listing(request())['records']])
        center.visibility({'ids':['payroll_x'],'restore':True},request('POST'))
        self.assertIn('payroll_x',[r['id'] for r in center.listing(request())['records']])

    def test_stop_dispatches_to_existing_task_managers(self):
        with patch('payroll_control.stop') as payroll,patch('payroll_inputs.workspace',return_value='shared'),patch('payroll_inputs.account',return_value='user'):
            center.stop_record({'kind':'payroll','batch_id':'batch'},request('POST'))
            payroll.assert_called_once_with('shared','batch','user')
        with patch('lanorange_approvals.stop') as approval:
            center.stop_record({'kind':'approval','price_id':'approval'},request('POST'))
            self.assertEqual(approval.call_args.args[:2],('approval',{'confirm':True}))
        with patch('lanorange_price_export.stop') as export:
            center.stop_record({'kind':'price-export','price_id':'price'},request('POST'))
            self.assertEqual(export.call_args.args[:2],('price',{}))
        from unittest.mock import Mock
        manager=Mock();manager.get_run.return_value={'status':'running'};manager.run_owner.return_value='user'
        with patch('download_jobs.get_manager',return_value=manager),patch.object(center,'require_account',return_value={'owner':'user','role':'admin'}):
            for kind in ('download','generate','payroll_source'):
                center.stop_record({'kind':kind,'member_ids':['original','retry']},request('POST'))
        self.assertEqual(manager.cancel.call_count,6)

    def test_new_attempt_is_not_hidden_by_an_old_pending_stop(self):
        with patch.object(center,'stop_record'):
            center.visibility({'ids':['b'],'stop_first':True},request('POST'))
        self.rows[1].update(status='success',member_ids=['b','new-attempt'])
        self.assertIn('b',[r['id'] for r in center.listing(request())['records']])

    def test_completed_retry_between_polls_reappears(self):
        center.visibility({'ids':['a']},request('POST'))
        self.rows[0]['member_ids'].append('new-successful-retry')
        self.assertIn('a',[r['id'] for r in center.listing(request())['records']])
        self.assertEqual(center.listing(request(query='archived=1'))['total'],0)
        self.rows[0]['status']='success'
        self.assertIn('a',[r['id'] for r in center.listing(request())['records']])

    def test_server_paging_search_dates_and_filters(self):
        self.rows=[record(f'{i:03}') for i in range(45)]
        result=center.listing(request(),page=2)
        self.assertEqual((len(result['records']),result['total'],result['pages'],result['page']),(20,45,3,2))
        self.assertEqual(center.listing(request(query='from=2026-10-31&to=2026-10-31'))['total'],45)
        self.assertEqual(center.listing(request(query='q=000'))['total'],1)
        self.assertEqual(center.listing(request(query='system=lanorange'))['total'],0)
        self.assertEqual(center.listing(request(query='system=lanorange'))['counts']['all'],0)
        self.assertEqual(len(center.organize_preview(request())['records']),45)

    def test_price_history_is_unlimited_metadata_without_loading_snapshots(self):
        path=self.root/'prices.sqlite3'
        @contextmanager
        def connection():
            db=sqlite3.connect(path);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()
        with connection() as db:
            db.execute('CREATE TABLE batches(id TEXT, scope TEXT, created REAL, status TEXT)')
            db.execute('CREATE TABLE items(batch_id TEXT, status TEXT, snapshot TEXT)')
            db.executemany('INSERT INTO batches VALUES (?,?,?,?)',[(str(i),'space',i,'completed') for i in range(45)]+[('private','other',99,'completed')])
            db.execute('INSERT INTO items VALUES (?,?,?)',('0','success','private snapshot never needed'))
        rows=center.price_summaries(SimpleNamespace(connection=connection),'space','approval')
        self.assertEqual(len(rows),45)
        self.assertTrue(all('snapshot' not in row and row['available'] for row in rows))
        self.assertEqual(next(r for r in rows if r['id']=='0')['completed'],1)

    def test_write_origin_and_remote_open_are_rejected(self):
        with self.assertRaises(HTTPException) as error:center.visibility({'ids':['a']},request('POST',origin='http://evil.invalid'))
        self.assertEqual(error.exception.status_code,403)
        with self.assertRaises(HTTPException) as error:center.open_directory({},request('POST',client='192.168.1.20'))
        self.assertEqual(error.exception.status_code,403)

    def test_open_only_resolved_directory_no_user_supplied_path(self):
        folder=self.root/'allowed';folder.mkdir()
        with patch.object(center,'directory',return_value=folder),patch.object(center.os,'startfile',create=True) as opened,patch.object(center.os,'name','nt'):
            center.open_directory({},request('POST'))
            opened.assert_called_once_with(str(folder))
            with self.assertRaises(HTTPException):center.open_directory({'path':'C:/arbitrary'},request('POST'))


if __name__=='__main__':unittest.main()
