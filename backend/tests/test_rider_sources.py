import asyncio
import csv
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import threading
import zipfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rider_sources as sources
from parttime_source import SourceError, TemplatePlan
from test_parttime_source import template


PLAN = TemplatePlan('泉州','31029436','2026-07-01','2026-07-29','2026-07','半月结','template.xlsx',1)
TEAMS = {'123':'测试站点'}


class RiderSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, kind, rows, csv_format=False):
        path = self.root / (kind + ('.csv' if csv_format else '.xlsx'))
        if csv_format:
            with path.open('w', encoding='utf-8-sig', newline='') as output:
                csv.writer(output).writerows(rows)
        else:
            book = Workbook()
            for row in rows:
                book.active.append(row)
            book.save(path)
        return path

    def detail(self, day='2026-07-01', team='123', name='测试站点', rider='001'):
        return [['日期','骑手ID','团队ID','团队名称','有效完成单'],[day,rider,team,name,5]]

    def test_template_only_does_not_require_manual_files_or_recent_dates(self):
        path = self.root / 'template.xlsx'
        template(path, [['泉州','001','2026-07-01','2026-07-29','半月结']])
        self.assertEqual(sources.inspect_template(self.root).month, '2026-07')

    def test_two_templates_rejected(self):
        template(self.root / 'template.xlsx')
        template(self.root / 'other-template.xlsx')
        with self.assertRaises(SourceError):
            sources.inspect_template(self.root)

    def test_target_teams_use_agency_id_not_city_text(self):
        payload = {'code':0,'result':{'code':'200','data':[
            {'id':123,'agencyId':31029436,'team_name':'测试站点'},
            {'id':456,'agencyId':31030116,'team_name':'泉州同名站点'}]}}
        self.assertEqual(sources.target_teams(payload, PLAN.agency_id), TEAMS)

    def test_missing_or_duplicate_team_metadata_rejected(self):
        for rows in ([],[{'id':123,'agencyId':31030116,'team_name':'其他城市'}],
                     [{'id':123,'agencyId':31029436,'team_name':'测试站点'}] * 2):
            with self.subTest(rows=len(rows)), self.assertRaises(SourceError):
                sources.target_teams({'code':0,'result':{'code':'200','data':rows}}, PLAN.agency_id)

    def test_query_all_statuses_and_methods_required(self):
        for kind in ('rider_info','receive_account'):
            base = sources.QUERIES[kind] + '?pageIndex=1&pageSize=20'
            if kind == 'receive_account':
                base += '&month=2026-07'
            self.assertTrue(sources.query_scope(kind, base, PLAN))
            self.assertFalse(sources.query_scope(kind, base + '&workStatus=1', PLAN))
            self.assertFalse(sources.query_scope(kind, base + '&knightId=001', PLAN))
            self.assertFalse(sources.query_scope(kind, base + '&receiveType=1', PLAN))

    def test_wrong_month_and_period_query_rejected(self):
        self.assertFalse(sources.query_scope('receive_account','https://test/?month=2026-09', PLAN))
        self.assertFalse(sources.query_scope('rider_detail','https://test/?startAt=2026-07-02&endAt=2026-07-29', PLAN))

    def test_detail_query_closes_intercepting_calendar_and_commits_blur(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.plan, collector.page = PLAN, MagicMock()
        frame, team, inputs, first, last = (MagicMock() for _ in range(5))
        team.count.return_value = 0
        frame.locator.side_effect = lambda selector: inputs if selector == 'input.el-range-input' else team
        inputs.count.return_value = 2
        inputs.nth.side_effect = lambda index: first if index == 0 else last
        first.input_value.return_value, last.input_value.return_value = PLAN.start, PLAN.end
        state = {'calendar_open': True, 'committed': False, 'reverted': False, 'queries': 0}
        def keyboard(key):
            if key == 'Enter':
                state['calendar_open'] = True
            elif key == 'Escape':
                state['calendar_open'] = False
                if not state['committed']:
                    state['reverted'] = True
            elif key == 'Tab':
                state['committed'] = True
        last.press.side_effect = keyboard
        frame.get_by_role.return_value.press.side_effect = lambda key: state.update(calendar_open=False) if key == 'Escape' else None
        def query():
            if state['calendar_open'] or not state['committed'] or state['reverted']:
                raise TimeoutError('calendar intercepts query pointer events')
            state['queries'] += 1
        frame.get_by_role.return_value.click.side_effect = query
        response = SimpleNamespace(ok=True, json=lambda: {'code': 0, 'data': {}})
        collector.page.expect_response.return_value.__enter__.return_value.value = response
        self.assertEqual(collector._query('rider_detail', frame), {'code': 0, 'data': {}})
        self.assertEqual(state['queries'], 1)
        first.fill.assert_called_once_with(PLAN.start)
        last.fill.assert_called_once_with(PLAN.end)
        last.input_value.return_value = '2026-07-28'
        with self.assertRaisesRegex(SourceError, '页面读回 2026-07-01 至 2026-07-28'):
            collector._query('rider_detail', frame)
        self.assertEqual(state['queries'], 1)

    def test_daily_export_exact_scope(self):
        valid = {'teamIds':[123],'startAt':PLAN.start,'endAt':PLAN.end,'exportType':2,'fields':['pointDate','knightId']}
        self.assertTrue(sources.detail_export_scope(valid, PLAN, TEAMS))
        for changes in ({'teamIds':[]},{'teamIds':[123,456]},{'teamIds':[123,123]},
                        {'exportType':1},{'exportType':True},{'startAt':'2026-07-02'},
                        {'fields':[]},{'knightId':'001'}):
            with self.subTest(changes=changes):
                self.assertFalse(sources.detail_export_scope({**valid,**changes}, PLAN, TEAMS))

    def test_popup_visibility_is_waited_before_counting_matches(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.cancelled = threading.Event()
        collector.page = SimpleNamespace(is_closed=lambda:False)
        locator = Mock()
        locator.count.return_value = 0
        locator.first.wait_for.side_effect = lambda **kwargs:setattr(locator.count, 'return_value', 1)
        self.assertIs(collector._visible_one(locator, 'test menu'), locator)
        locator.first.wait_for.assert_called_once_with(state='visible', timeout=30000)

    def test_ambiguous_popup_is_rejected_after_wait(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.cancelled = threading.Event()
        collector.page = SimpleNamespace(is_closed=lambda:False)
        locator = Mock()
        locator.count.return_value = 2
        with self.assertRaisesRegex(sources.BillCollectionError, '唯一匹配'):
            collector._visible_one(locator, 'test menu')

    def test_actual_daily_csv_supported_and_not_modified(self):
        path = self.write('rider_detail', self.detail(), True)
        original = path.read_bytes()
        result = sources.validate_document(path, 'rider_detail', PLAN, TEAMS)
        self.assertEqual((result['rows'],result['date_min'],result['format']), (1,PLAN.start,'csv'))
        self.assertFalse(result['filtered_by_applicants'])
        self.assertEqual(path.read_bytes(), original)

    def test_unselected_team_date_and_blank_rider_rejected(self):
        for args in ({'team':'456'},{'day':'2026-07-30'},{'rider':''}):
            with self.subTest(args=args), self.assertRaises(SourceError):
                sources.validate_document(self.write('rider_detail',self.detail(**args)), 'rider_detail',PLAN,TEAMS)

    def test_detail_accepts_irregular_names_and_all_selected_teams(self):
        rows = self.detail(name='不规则名称（原站名）')
        rows.append(['2026-07-02', '002', '456', '外地命名站点', 3])
        result = sources.validate_document(self.write('rider_detail', rows), 'rider_detail', PLAN,
                                           {'123': '', '456': ''})
        self.assertEqual((result['rows'], result['team_count']), (2, 2))

    def test_all_team_agencies_do_not_require_city_names(self):
        payload = {'code': 0, 'result': {'code': '200', 'data': [
            {'id': 123, 'agencyId': 31029436}, {'id': 456, 'agencyId': 31030116}]}}
        self.assertEqual(sources.team_agencies(payload), {'123': '31029436', '456': '31030116'})

    def test_detail_selects_all_available_stations_with_header_checkbox(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.log = Mock()
        collector._one = lambda locator, _: locator
        dialog, panels, left, right = (MagicMock() for _ in range(4))
        dialog.locator.return_value = panels
        panels.count.return_value = 2
        panels.nth.side_effect = lambda index: left if index == 0 else right
        left.locator.return_value.evaluate_all.side_effect = [['123', '456'], []]
        right.locator.return_value.evaluate_all.side_effect = [[], ['123', '456'], ['123', '456']]
        collector._visible_one = Mock(return_value=dialog)
        teams = {}
        self.assertIs(collector._select_teams(MagicMock(), teams, all_available=True), dialog)
        self.assertEqual(set(teams), {'123', '456'})
        left.locator.assert_any_call('.el-transfer-panel__header .el-checkbox')
        self.assertFalse(any(':has(input' in str(call) for call in left.locator.call_args_list))

    def test_async_task_number_is_required(self):
        self.assertEqual(sources.detail_task_id({'code': 200, 'data': {'taskId': 29767523}}), '29767523')
        self.assertEqual(sources.detail_task_id({'code': 200, 'data': 29767523}), '29767523')
        self.assertIsNone(sources.detail_task_id({'code': 200, 'data': {'code': 1, 'message': '已受理'}}))
        for data in ({}, {'id': 1, 'taskId': 2}, None):
            with self.assertRaises(SourceError):
                sources.detail_task_id({'code': 200, 'data': data})
        with self.assertRaises(SourceError):
            sources.detail_task_id({'code': 200, 'data': {'code': 2, 'message': '失败'}})

    def detail_poller(self, texts, downloads):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.plan, collector.detail_task, collector.timeout = PLAN, '29767523', 90
        collector.checkpoint, collector.log = Mock(), Mock()
        collector._visible_one = lambda locator, _: locator
        frame = MagicMock()
        frame.url = 'https://lpd-service-center.faas.ele.me/#/export-list'
        rows = []
        for text in texts:
            row = MagicMock()
            row.inner_text.return_value = text
            row.is_visible.return_value = True
            row.get_by_text.return_value.click.side_effect = lambda: downloads.append('file')
            rows.append(row)
        frame.locator.return_value.all.return_value = rows
        collector.page = MagicMock()
        collector.page.frames = [frame]
        return collector, frame, rows

    def test_async_list_matches_exact_task_and_clicks_download_once(self):
        downloads = []
        prefix = PLAN.start + '-' + PLAN.end + '.骑手数据明细.'
        collector, frame, rows = self.detail_poller([
            prefix + '111.zip 导出完成 下载文件',
            prefix + '29767523.zip 导出完成 下载文件'], downloads)
        collector._poll_detail_task(downloads, [])
        self.assertEqual(downloads, ['file'])
        rows[0].get_by_text.assert_not_called()
        rows[1].get_by_text.return_value.click.assert_called_once()
        collector.page.reload.assert_not_called()

    def test_async_failed_or_duplicate_task_is_not_downloaded(self):
        text = PLAN.start + '-' + PLAN.end + '.骑手数据明细.29767523.zip '
        for texts in ([text + '导出失败'], [text + '导出完成'] * 2):
            downloads = []
            collector, _, rows = self.detail_poller(texts, downloads)
            with self.assertRaises(SourceError):
                collector._poll_detail_task(downloads, [])
            self.assertFalse(downloads)

    def test_async_pending_task_refreshes_without_resubmitting(self):
        downloads = []
        text = PLAN.start + '-' + PLAN.end + '.骑手数据明细.29767523.zip '
        collector, _, rows = self.detail_poller([text + '整理中'], downloads)
        rows[0].inner_text.side_effect = [text + '整理中', text + '导出完成']
        collector._poll_detail_task(downloads, [])
        collector.page.reload.assert_called_once()
        rows[0].get_by_text.return_value.click.assert_called_once()

    def test_ack_without_task_id_correlates_new_task_after_submission(self):
        downloads = []
        prefix = PLAN.start + '-' + PLAN.end + '.骑手数据明细.'
        collector, _, rows = self.detail_poller([
            prefix + '111.zip 导出完成', prefix + '29767523.zip 导出完成'], downloads)
        collector.detail_task = None
        collector.detail_acknowledged = True
        collector.detail_baseline = {'111'}
        collector.detail_submitted_at = datetime(2026, 7, 30, 12, 0)
        collector.detail_selected_teams = TEAMS
        collector.output_dir = self.root
        rows[1].locator.return_value.nth.return_value.inner_text.return_value = '2026-07-30 12:00:02'
        collector._poll_detail_task(downloads, [])
        self.assertEqual(collector.detail_task, '29767523')
        saved = json.loads((self.root / 'detail_task.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['selected_team_ids'], ['123'])
        rows[0].get_by_text.assert_not_called()

    def test_delayed_acknowledgement_is_waited_before_navigation(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.timeout = 90
        collector.detail_acknowledged = False
        collector.page, collector.log, collector.checkpoint = Mock(), Mock(), Mock()
        collector._visible_one = lambda locator, _: locator
        frame = Mock()
        order = []
        def acknowledged(_):
            order.append('ack')
            collector.detail_acknowledged = True
        collector.page.wait_for_timeout.side_effect = acknowledged
        frame.get_by_role.return_value.click.side_effect = lambda: order.append('navigate')
        collector._poll_detail_task = Mock()
        collector._wait_detail_download(frame, [], [])
        self.assertEqual(order, ['ack', 'navigate'])
        collector._poll_detail_task.assert_called_once()

    def test_submission_rejection_does_not_navigate_or_retry(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.timeout = 90
        collector.detail_acknowledged = False
        collector.page, collector.log, collector.checkpoint = Mock(), Mock(), Mock()
        frame = Mock()
        with self.assertRaisesRegex(SourceError, '拒绝'):
            collector._wait_detail_download(frame, [], ['官方拒绝'])
        frame.get_by_role.assert_not_called()
        collector.page.wait_for_timeout.assert_not_called()

    def test_submission_timeout_does_not_navigate_or_retry(self):
        collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        collector.timeout = 90
        collector.detail_acknowledged = False
        collector.page, collector.log, collector.checkpoint = Mock(), Mock(), Mock()
        frame = Mock()
        with patch.object(sources.time, 'monotonic', side_effect=[0, 91]), self.assertRaisesRegex(SourceError, '回执等待超时'):
            collector._wait_detail_download(frame, [], [])
        frame.get_by_role.assert_not_called()

    def test_detail_zip_preserves_archive_and_merges_all_parts(self):
        first = self.write('rider_detail', self.detail(), True)
        second = self.write('rider_detail_other', self.detail(day='2026-07-02', team='456', name='不规则站点'), True)
        path = self.root / 'detail.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.write(first, 'nested/first.csv')
            archive.write(second, 'second.csv')
        original = path.read_bytes()
        merged, info = sources.unpack_detail_archive(path, PLAN, {'123': '', '456': ''})
        self.assertEqual(info['rows'], 2)
        self.assertEqual(info['archive_members'], 2)
        self.assertTrue(merged.is_file())
        self.assertEqual(path.read_bytes(), original)

    def test_zip_unsafe_path_unknown_file_and_wrong_dates_rejected(self):
        member = self.write('detail', self.detail(day='2026-07-30'), True)
        for index, name in enumerate(('../outside.csv', 'unknown.exe', 'detail.csv')):
            path = self.root / (str(index) + '.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.write(member, name)
            with self.assertRaises(SourceError):
                sources.unpack_detail_archive(path, PLAN, TEAMS)

    def test_precision_risk_and_bad_row_rejected(self):
        for rows in (self.detail(team=123.5), self.detail(rider=1e17),
                     self.detail() + [['2026-07-01','001','123','测试站点',5, 'extra']]):
            with self.subTest(rows=rows), self.assertRaises(SourceError):
                sources.validate_document(self.write('rider_detail',rows, True),'rider_detail',PLAN,TEAMS)

    def test_valid_empty_headers_allowed_missing_file_not_empty(self):
        result = sources.validate_document(self.write('rider_detail',self.detail()[:1]),'rider_detail',PLAN,TEAMS)
        self.assertEqual((result['rows'],result['status']), (0,'empty'))
        with self.assertRaises(SourceError):
            sources.validate_document(self.write('rider_detail',[['<html>login</html>']], True),'rider_detail',PLAN,TEAMS)

    def test_identity_masked_and_blank_are_retained_not_inferred_as_binding(self):
        rows = [['团队ID','团队名称','骑手ID','收款方式','收款账户','收款账户姓名','收款账户身份证'],
                ['123','测试站点','001','银行卡','****1234','test','********1234'],
                ['123','测试站点','002','支付宝','','','']]
        result = sources.validate_document(self.write('receive_account',rows),'receive_account',PLAN,TEAMS)
        self.assertEqual((result['rows'],result['identity_masked'],result['identity_blank']), (2,1,1))

    def test_receive_account_preserves_all_city_export_without_team_validation(self):
        rows = [['团队ID','团队名称','骑手ID','收款方式','收款账户','收款账户姓名','收款账户身份证'],
                ['999','历史站点','001','银行卡','','',''],
                ['123','改名站点','002','支付宝','','',''],
                ['','未分配团队','003','支付宝','','','']]
        path = self.write('receive_account', rows)
        original = path.read_bytes()
        for teams in (TEAMS, {}):
            result = sources.validate_document(path, 'receive_account', PLAN, teams)
            self.assertEqual(result['rows'], 3)
            self.assertEqual(path.read_bytes(), original)

    def test_rider_info_all_statuses_kept(self):
        rows = [['骑手ID','姓名','部门','身份证','状态'],['001','test','测试站点','123456789012345678','在职'],
                ['002','test','测试站点','','离职']]
        result = sources.validate_document(self.write('rider_info',rows),'rider_info',PLAN,TEAMS)
        self.assertEqual(result['rows'],2)

    def test_management_blank_rider_ids_are_retained_in_original(self):
        rows = [['骑手ID','姓名','部门','身份证','状态','职位'],
                ['','test','测试站点','','在职','站长'],
                ['','test','测试站点','','离职','副站长'],
                ['','test','测试站点','','在职','队长'],
                ['001','test','测试站点','','在职','配送员']]
        path = self.write('rider_info',rows)
        original = path.read_bytes()
        result = sources.validate_document(path,'rider_info',PLAN,TEAMS)
        self.assertEqual((result['rows'],result['non_rider_rows']), (4,3))
        self.assertEqual(result['team_count'],1)
        self.assertEqual(path.read_bytes(),original)
        for position, rider in (('配送员',''),('站长','broken'),('未知','')):
            with self.subTest(position=position, rider=rider), self.assertRaises(SourceError):
                sources.validate_document(self.write('rider_info',[rows[0],[rider,'test','测试站点','','在职',position]]),
                                          'rider_info',PLAN,TEAMS)

    def test_download_manifest_partial_and_no_calculation(self):
        folder = self.root / 'upload_1'
        folder.mkdir()
        template(folder / 'template.xlsx')
        calls = []
        class Fake:
            def collect(self, kind):
                calls.append(kind)
                if kind == 'rider_info':
                    raise SourceError('官方导出验证失败；未重发短信')
                return {'path':kind + '.csv','rows':1,'status':'validated'}
        with self.assertRaisesRegex(SourceError,'官方导出验证失败'):
            sources.download_sources(folder,self.root,lambda _:None,threading.Event(),collector=lambda *args:Fake())
        manifest = json.loads(next(self.root.glob('rider_sources_*/manifest.json')).read_text(encoding='utf-8'))
        self.assertEqual(calls,list(sources.DOWNLOAD_ORDER))
        self.assertEqual(set(manifest['datasets']), {'rider_detail','receive_account'})
        self.assertEqual(manifest['stage'],'rider_info')
        self.assertFalse(manifest['payroll_executed'])
        self.assertFalse(manifest['binding_generated'])
        self.assertFalse(sources.COLLECTION_LOCK.locked())

    def test_cancel_and_busy_stop_before_export(self):
        folder = self.root / 'upload_1'
        folder.mkdir()
        template(folder / 'template.xlsx')
        cancelled = threading.Event()
        cancelled.set()
        calls = []
        with self.assertRaisesRegex(SourceError,'取消'):
            sources.download_sources(folder,self.root,lambda _:None,cancelled,collector=lambda *args:SimpleNamespace(collect=lambda kind:calls.append(kind)))
        self.assertFalse(calls)
        with patch.object(sources,'COLLECTION_LOCK') as lock:
            lock.acquire.return_value = False
            with self.assertRaisesRegex(SourceError,'另一项'):
                sources.download_sources(folder,self.root,lambda _:None,threading.Event())

    def test_stream_never_calls_payroll_and_reports_error(self):
        async def run():
            config = SimpleNamespace(sourcePath='invalid')
            with patch.object(sources,'owned_upload',side_effect=SourceError('本工作区上传目录无效')):
                return [event async for event in sources.run_rider_sources(config,'tester')]
        events = asyncio.run(run())
        self.assertIn('"status": "error"', events[-1])


class WaitPage:
    def __init__(self):
        self.now = 0
        self.closed = False
        self.url = sources.PAGES['rider_info']
        self.listeners = {}
        self.front_calls = 0
        self.step = lambda:None

    def is_closed(self):
        return self.closed

    def bring_to_front(self):
        self.front_calls += 1

    def on(self, event, handler):
        self.listeners[event] = handler

    def remove_listener(self, event, handler):
        assert self.listeners.pop(event) is handler

    def wait_for_timeout(self, milliseconds):
        self.now += milliseconds / 1000
        self.step()


class RiderSourceWaitTests(unittest.TestCase):
    def setUp(self):
        self.page = WaitPage()
        self.collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        self.collector.page = self.page
        self.collector.page_url = self.page.url
        self.collector.plan = PLAN
        self.collector.cancelled = threading.Event()
        self.collector.timeout = 1
        self.collector.human_timeout = 5
        self.collector.reveal = lambda page: page.bring_to_front()
        self.collector.conceal = Mock()
        self.logs = []
        self.collector.log = self.logs.append
        self.collector._verification_visible = Mock(return_value=False)
        self.clock = patch.object(sources.time, 'monotonic', side_effect=lambda:self.page.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def wait_download(self, downloads, rejected=None, errors=None, human=False, kind='rider_info'):
        self.collector._wait_download(kind, self.official_staff_frame(), downloads, rejected or [],
                                      errors if errors is not None else [], human)

    def test_sms_dialog_has_independent_human_deadline(self):
        downloads = []
        self.collector._verification_visible.return_value = True
        self.page.step = lambda:downloads.append('file') if self.page.now >= 3 else None
        self.wait_download(downloads)
        self.assertGreater(self.page.now, self.collector.timeout)
        self.assertEqual(downloads, ['file'])
        self.assertEqual(self.page.front_calls, 1)
        self.assertFalse(self.page.closed)

    def test_awaiting_user_click_export_is_already_human_wait(self):
        downloads = []
        self.page.step = lambda:downloads.append('file') if self.page.now >= 3 else None
        self.wait_download(downloads, human=True)
        self.assertEqual(downloads, ['file'])
        self.assertGreater(self.page.now, self.collector.timeout)

    def test_wrong_code_keeps_window_open_for_correction(self):
        downloads, errors = [], ['official verification rejected']
        self.collector._verification_visible.return_value = True
        self.page.step = lambda:downloads.append('file') if self.page.now >= 3 else None
        self.wait_download(downloads, errors=errors)
        self.assertFalse(errors)
        self.assertTrue(any('验证未通过' in message for message in self.logs))
        self.assertFalse(self.page.closed)

    def test_previous_failed_code_does_not_reject_later_download(self):
        downloads, errors = [], []
        def finish():
            errors.append('previous verification failure')
            downloads.append('file')
        self.page.step = finish
        self.wait_download(downloads, errors=errors, human=True)
        self.assertEqual(downloads, ['file'])
        self.assertFalse(errors)

    def test_human_wait_is_bounded_and_cancelable(self):
        with self.assertRaisesRegex(SourceError, '人工验证等待超时'):
            self.wait_download([], human=True)
        self.assertEqual(self.page.now, 5)
        self.page.now = 0
        self.page.step = self.collector.cancelled.set
        with self.assertRaisesRegex(SourceError, '已取消'):
            self.wait_download([], human=True)
        self.assertEqual(self.page.now, 0.25)

    def test_closed_window_is_distinct_from_timeout(self):
        self.page.closed = True
        with self.assertRaisesRegex(SourceError, 'Edge 被关闭'):
            self.wait_download([], human=True)

    def test_normal_download_timeout_and_guard_rejection_unchanged(self):
        with self.assertRaisesRegex(SourceError, '任务状态未知'):
            self.wait_download([], kind='rider_detail')
        self.assertEqual(self.page.now, 1)
        self.page.now = 0
        with self.assertRaisesRegex(SourceError, '导出参数不符'):
            self.wait_download([], rejected=['导出参数不符'], human=True)
        self.assertEqual(self.page.now, 0)

    def official_staff_frame(self):
        frame = Mock()
        frame.url = 'https://artemis.faas.ele.me/#' + sources.PAGES['rider_info'].split('#')[1]
        frame.is_detached.return_value = False
        frame.frame_element.return_value.is_visible.return_value = True
        return frame

    def test_detached_staff_frame_relocates_without_navigation_export_or_sms(self):
        from playwright.sync_api import Error
        original, replacement = self.official_staff_frame(), self.official_staff_frame()
        self.page.frames = [replacement]
        self.page.context, self.page.goto, self.page.get_by_role = Mock(), Mock(), Mock()
        self.collector._frame, self.collector._query, self.collector._select_teams = Mock(), Mock(), Mock()
        self.collector.auth = Mock()
        self.page.listeners['download'] = listener = Mock()
        downloads = []
        def visible(frame):
            if frame is original:
                raise Error('Locator.count: Frame was detached')
            self.assertIs(frame, replacement)
            return True
        self.collector._verification_visible.side_effect = visible
        self.page.step = lambda: downloads.append('original-download') if self.page.now >= 3 else None
        self.collector._wait_download('rider_info', original, downloads, [], [], True)
        self.assertEqual(downloads, ['original-download'])
        self.assertEqual(self.page.now, 3)
        self.assertIs(self.page.listeners['download'], listener)
        for operation in (self.page.goto, self.page.get_by_role, self.page.context.request.get,
                          self.page.context.request.post, self.collector.auth, self.collector._frame,
                          self.collector._query, self.collector._select_teams):
            operation.assert_not_called()
        self.assertEqual(sum('[等待页面]' in message for message in self.logs), 1)

    def test_navigation_without_replacement_still_receives_original_download(self):
        from playwright.sync_api import Error
        self.page.frames = []
        self.collector._verification_visible.side_effect = Error(
            'Locator.count: Execution context was destroyed, most likely because of a navigation')
        downloads = []
        self.page.step = lambda: downloads.append('original-download') if self.page.now >= 3 else None
        self.wait_download(downloads, human=True)
        self.assertEqual(downloads, ['original-download'])
        self.assertEqual(self.collector._verification_visible.call_count, 1)
        self.assertEqual(sum('[等待页面]' in message for message in self.logs), 1)

    def test_attached_frame_navigating_to_login_or_blank_reselects_target_without_clicks(self):
        for destination in ('about:blank', 'https://mozi-login.alibaba-inc.com/',
                            'https://artemis.faas.ele.me/'):
            with self.subTest(destination=destination):
                self.page.now = 0
                original, replacement = self.official_staff_frame(), self.official_staff_frame()
                self.page.frames = [original, replacement]
                downloads, seen = [], []
                def visible(frame):
                    seen.append(frame)
                    return frame is replacement
                def step():
                    original.url = destination
                    if self.page.now >= 3:
                        downloads.append('original-download')
                self.collector._verification_visible.side_effect = visible
                self.page.step = step
                self.page.goto, self.page.get_by_role, self.page.context = Mock(), Mock(), Mock()
                self.collector._wait_download('rider_info', original, downloads, [], [], True)
                self.assertIs(seen[0], original)
                self.assertIs(seen[1], replacement)
                self.assertEqual(seen.count(original), 1)
                original.is_detached.assert_called()
                self.assertEqual(downloads, ['original-download'])
                self.assertEqual(self.page.now, 3)
                self.page.goto.assert_not_called()
                self.page.get_by_role.assert_not_called()
                self.page.context.request.get.assert_not_called()
                self.page.context.request.post.assert_not_called()

    def test_detached_state_without_count_error_reselects_target_and_keeps_deadline(self):
        original, replacement = self.official_staff_frame(), self.official_staff_frame()
        original.is_detached.return_value = True
        self.page.frames = [original, replacement]
        self.collector._verification_visible.return_value = False
        with self.assertRaisesRegex(SourceError, '人工验证等待超时.*状态未知'):
            self.collector._wait_download('rider_info', original, [], [], [], True)
        self.assertEqual(self.page.now, 5)
        self.assertTrue(self.collector._verification_visible.called)
        self.assertTrue(all(call.args == (replacement,) for call in self.collector._verification_visible.call_args_list))

    def test_missing_staff_frame_keeps_original_human_deadline_and_unknown_state(self):
        from playwright.sync_api import Error
        self.page.frames = []
        self.collector._verification_visible.side_effect = Error('Locator.count: Frame was detached')
        with self.assertRaisesRegex(SourceError, '人工验证等待超时.*状态未知.*不自动重发短信或重新导出'):
            self.wait_download([], human=True)
        self.assertEqual(self.page.now, 5)
        self.assertEqual(sum('[等待页面]' in message for message in self.logs), 1)

    def test_repeated_context_navigation_does_not_extend_normal_deadline(self):
        from playwright.sync_api import Error
        self.page.frames = [self.official_staff_frame()]
        self.collector._verification_visible.side_effect = Error('Locator.count: Cannot find context with specified id')
        with self.assertRaisesRegex(SourceError, '任务状态未知'):
            self.wait_download([])
        self.assertEqual(self.page.now, 1)
        self.assertGreater(self.collector._verification_visible.call_count, 1)
        self.assertEqual(sum('[等待页面]' in message for message in self.logs), 1)

    def test_detached_frame_wait_still_cancels_immediately(self):
        from playwright.sync_api import Error
        self.page.frames = []
        self.collector._verification_visible.side_effect = Error('Locator.count: Frame was detached')
        self.page.step = self.collector.cancelled.set
        with self.assertRaisesRegex(SourceError, '已取消'):
            self.wait_download([], human=True)
        self.assertEqual(self.page.now, 0.25)

    def test_detached_frame_wait_still_detects_closed_main_page(self):
        from playwright.sync_api import Error
        self.page.frames = []
        self.collector._verification_visible.side_effect = Error('Locator.count: Frame was detached')
        self.page.step = lambda: setattr(self.page, 'closed', True)
        with self.assertRaisesRegex(SourceError, 'Edge 被关闭'):
            self.wait_download([], human=True)
        self.assertEqual(self.page.now, 0.25)

    def test_unrelated_errors_do_not_enter_frame_recovery(self):
        from playwright.sync_api import Error, TimeoutError
        self.collector._waiting_rider_info_frame = Mock()
        for exc in (TimeoutError('Locator.count: Timeout 30000ms exceeded'), Error('Invalid selector'),
                    RuntimeError('Execution context was destroyed'), SourceError('Frame was detached')):
            with self.subTest(exception=type(exc).__name__):
                self.collector._verification_visible.side_effect = exc
                with self.assertRaises(type(exc)) as caught:
                    self.wait_download([], human=True)
                self.assertIs(caught.exception, exc)
        self.collector._waiting_rider_info_frame.assert_not_called()
        self.assertFalse(self.logs)
        self.assertEqual(self.page.now, 0)

    def test_replacement_staff_frame_is_unique_visible_and_on_official_route(self):
        target = self.official_staff_frame()
        foreign, other_route, hidden, detached = (self.official_staff_frame() for _ in range(4))
        foreign.url = 'https://artemis.faas.ele.me.example/#/humanResource/staffManagement/index'
        other_route.url = 'https://artemis.faas.ele.me/#/payment/receive-account'
        hidden.frame_element.return_value.is_visible.return_value = False
        detached.is_detached.return_value = True
        self.page.frames = [foreign, other_route, hidden, detached, target]
        self.assertIs(self.collector._waiting_rider_info_frame(), target)
        self.page.frames.append(self.official_staff_frame())
        self.assertIsNone(self.collector._waiting_rider_info_frame())
        self.page.frames = [target]
        self.page.url = 'https://aeolus.ele.me/'
        self.assertIsNone(self.collector._waiting_rider_info_frame())

    def test_replacement_frame_navigation_is_ignored_but_unrelated_error_propagates(self):
        from playwright.sync_api import Error
        frame = self.official_staff_frame()
        self.page.frames = [frame]
        frame.frame_element.side_effect = Error('Frame.frame_element: Frame has been detached.')
        self.assertIsNone(self.collector._waiting_rider_info_frame())
        exc = Error('Frame.frame_element: Unexpected selector failure')
        frame.frame_element.side_effect = exc
        with self.assertRaises(Error) as caught:
            self.collector._waiting_rider_info_frame()
        self.assertIs(caught.exception, exc)

    def test_download_arriving_during_detach_is_preserved_but_rejection_still_fails(self):
        from playwright.sync_api import Error
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                downloads, rejection = [], []
                def detach(frame):
                    downloads.append('original-download')
                    if rejected:
                        rejection.append('导出参数不符')
                    raise Error('Locator.count: Frame was detached')
                self.collector._verification_visible.side_effect = detach
                if rejected:
                    with self.assertRaisesRegex(SourceError, '导出参数不符'):
                        self.collector._wait_download('rider_info', self.official_staff_frame(), downloads, rejection, [], True)
                else:
                    self.collector._wait_download('rider_info', self.official_staff_frame(), downloads, rejection, [], True)
                self.assertEqual(downloads, ['original-download'])
                self.assertEqual(self.page.now, 0)

    def response(self, status=200, query='pageIndex=1&pageSize=20'):
        return SimpleNamespace(url=sources.QUERIES['rider_info'] + '?' + query,
                               request=SimpleNamespace(method='GET'), status=status,
                               ok=status == 200, json=lambda:{'code':0,'data':{}})

    def test_query_permission_wait_observes_only_exact_scope_then_revalidates(self):
        self.collector._check_agency_context = Mock()
        frame = Mock()
        self.collector._frame = Mock(return_value=frame)
        self.collector._query = Mock(return_value={'code':0})
        replies = [self.response(query='pageIndex=1&workStatus=1'), self.response(403), self.response()]
        self.page.step = lambda:self.page.listeners['response'](replies.pop(0))
        result = self.collector._wait_query_access('rider_info', frame, 403)
        self.assertEqual(result, {'code':0})
        self.assertEqual(self.page.now, 0.75)
        self.collector._check_agency_context.assert_called_once()
        self.collector._query.assert_called_once_with('rider_info', frame, recover=False)
        self.assertFalse(self.page.listeners)
        self.assertFalse(self.page.closed)

    def test_query_permission_timeout_and_cancel_clean_up_listener(self):
        with self.assertRaisesRegex(SourceError, '查询权限等待超时'):
            self.collector._wait_query_access('rider_info', Mock(), 403)
        self.assertEqual(self.page.now, 5)
        self.assertFalse(self.page.listeners)
        self.page.step = self.collector.cancelled.set
        with self.assertRaisesRegex(SourceError, '已取消'):
            self.collector._wait_query_access('rider_info', Mock(), 403)
        self.assertFalse(self.page.listeners)

    def test_recovered_query_on_other_page_never_exports(self):
        self.collector._query = Mock()
        def reply():
            self.page.url = sources.PAGES['receive_account']
            self.page.listeners['response'](self.response())
        self.page.step = reply
        with self.assertRaisesRegex(SourceError, '页面已变化'):
            self.collector._wait_query_access('rider_info', Mock(), 403)
        self.collector._query.assert_not_called()
        self.assertFalse(self.page.listeners)

    def test_query_only_401_403_enters_manual_wait_without_resubmitting(self):
        frame = MagicMock()
        frame.locator.return_value.count.return_value = 1
        frame.locator.return_value.input_value.return_value = '全部'
        for status in (401, 403, 500):
            with self.subTest(status=status):
                pending = MagicMock()
                pending.__enter__.return_value.value = self.response(status)
                self.page.expect_response = Mock(return_value=pending)
                self.collector._wait_query_access = Mock(return_value={'code':0})
                if status in (401, 403):
                    self.assertEqual(self.collector._query('rider_info', frame), {'code':0})
                    self.collector._wait_query_access.assert_called_once_with('rider_info', frame, status)
                else:
                    with self.assertRaisesRegex(SourceError, 'HTTP 500'):
                        self.collector._query('rider_info', frame)
                    self.collector._wait_query_access.assert_not_called()
        self.assertFalse(self.page.closed)


class RiderDetailCityScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from profile_fixtures import rider_profile
        fixture_profile = patch.object(sources, 'source_profile', side_effect=rider_profile)
        fixture_profile.start()
        self.addCleanup(fixture_profile.stop)

    def collector(self, target=None, payload=None, foreign_file=False):
        page = MagicMock()
        page.is_closed.return_value = False
        page.context.pages = [page]
        payload = payload or {'code': 0, 'result': {'code': '200', 'data': [
            {'id': 123, 'agencyId': int(PLAN.agency_id), 'team_name': '测试站点'},
            {'id': 456, 'agencyId': 31030116, 'team_name': '其他城市站点'}]}}
        page.context.request.post.return_value = SimpleNamespace(ok=True, json=lambda: payload)
        options = {} if target is None else {'detail_target_city_only': target}
        collector = sources.RiderSourceCollector(page, PLAN, self.root, Mock(), threading.Event(), auth=Mock(), **options)
        collector._check_agency_context = Mock()
        collector._capture_detail_baseline = Mock()
        collector.detail_baseline = set()
        collector._frame = Mock(return_value=MagicMock())
        collector._query = Mock(return_value={})
        collector._visible_one = lambda locator, _: locator
        selections = []
        def select(frame, teams, all_available=False):
            if all_available:
                teams.update({'123': '', '456': ''})
            selections.append((dict(teams), all_available))
            return MagicMock()
        collector._select_teams = Mock(side_effect=select)
        def download(frame, downloads, rejection):
            collector.detail_task = '10001'
            def save(path):
                rows = [['日期', '骑手ID', '团队ID', '团队名称', '有效完成单'],
                        [PLAN.start, '001', '456' if foreign_file else '123', '原始站点名称', 3]]
                with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
                    csv.writer(stream).writerows(rows)
            downloads.append(SimpleNamespace(failure=lambda: None, suggested_filename='daily.csv', save_as=save))
        collector._wait_detail_download = Mock(side_effect=download)
        return collector, page, selections

    def test_default_detail_mode_preserves_all_available_team_behavior(self):
        collector, _, selections = self.collector()
        result = collector.collect('rider_detail')
        self.assertEqual(selections, [({'123': '', '456': ''}, True)])
        self.assertTrue(result['all_available_teams'])
        self.assertEqual(result['scope'], 'all_available_teams')
        self.assertEqual(result['team_agency_ids'], {'123': PLAN.agency_id, '456': '31030116'})

    def test_target_mode_selects_only_the_requested_agency_without_filtering_the_original(self):
        collector, _, selections = self.collector(True)
        result = collector.collect('rider_detail')
        self.assertEqual(selections, [({'123': '测试站点'}, False)])
        self.assertEqual(result['selected_team_ids'], ['123'])
        self.assertEqual(result['team_agency_ids'], {'123': PLAN.agency_id})
        self.assertFalse(result['all_available_teams'])
        self.assertEqual(result['scope'], 'target_city')
        self.assertEqual((self.root / result['path']).read_text(encoding='utf-8-sig'),
                         '日期,骑手ID,团队ID,团队名称,有效完成单\n' + PLAN.start + ',001,123,原始站点名称,3\n')

    def test_other_city_in_download_is_rejected_in_target_mode(self):
        collector, _, selections = self.collector(True, foreign_file=True)
        with self.assertRaisesRegex(SourceError, '非目标城市'):
            collector.collect('rider_detail')
        self.assertEqual(selections, [({'123': '测试站点'}, False)])

    def test_unknown_agency_or_missing_target_teams_fails_before_export(self):
        for records in ([{'id': 123, 'team_name': '测试站点'}],
                        [{'id': 456, 'agencyId': 31030116, 'team_name': '其他城市站点'}]):
            with self.subTest(records=records):
                collector, page, _ = self.collector(True, payload={'code': 0, 'result': {'code': '200', 'data': records}})
                with self.assertRaises(SourceError):
                    collector.collect('rider_detail')
                collector._select_teams.assert_not_called()
                collector._wait_detail_download.assert_not_called()
                page.context.route.assert_not_called()

    def test_exact_team_guard_rejects_foreign_city_or_unselected_team(self):
        request = {'teamIds': [123], 'startAt': PLAN.start, 'endAt': PLAN.end, 'exportType': 2,
                   'fields': ['pointDate', 'knightId']}
        self.assertTrue(sources.detail_export_scope(request, PLAN, TEAMS))
        for ids in ([456], [123, 456]):
            self.assertFalse(sources.detail_export_scope({**request, 'teamIds': ids}, PLAN, TEAMS))

    def test_constructor_rejects_nonboolean_city_scope_option(self):
        with self.assertRaises(SourceError):
            self.collector('true')


class RiderInfoStatusQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.collector = sources.RiderSourceCollector.__new__(sources.RiderSourceCollector)
        self.collector.plan, self.collector.output_dir = PLAN, self.root
        self.collector.profile = {}
        self.collector.cancelled = threading.Event()
        self.collector.page, self.frame = MagicMock(), MagicMock()
        self.collector.page.is_closed.return_value = False
        self.collector.auth = Mock()
        self.collector._check_agency_context = Mock()
        self.collector._frame = Mock(return_value=self.frame)
        self.status, self.option, self.menu = MagicMock(), MagicMock(), MagicMock()
        self.status.input_value.return_value = ''
        self.status.get_attribute.return_value = '请选择'
        self.buttons = {name: MagicMock() for name in ('重置', '查询', '导出')}
        self.frame.get_by_role.side_effect = lambda role, name, exact: self.buttons[name]
        selectors = {'.el-form-item:has(label:text-is("在职状态：")) input': self.status,
                     '.el-select-dropdown:visible li > span:text-is("全部")': self.option,
                     '.el-select-dropdown:visible': self.menu}
        self.frame.locator.side_effect = lambda selector: selectors[selector]
        self.collector._visible_one = lambda locator, description: locator
        self.response = SimpleNamespace(url=sources.QUERIES['rider_info'] + '?pageIndex=1&pageSize=20&workStatus=',
            request=SimpleNamespace(method='GET'), ok=True, status=200, json=lambda: {'code': 0, 'data': {}})
        owner = self
        class Pending:
            def __init__(self, predicate):
                self.predicate = predicate
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                if exc_type is None and not self.predicate(owner.response):
                    raise TimeoutError('no exact all-status response')
                return False
            @property
            def value(self):
                return owner.response
        self.collector.page.expect_response.side_effect = lambda predicate, timeout: Pending(predicate)

    def diagnostic(self):
        return json.loads((self.root / 'staff_status_selection.json').read_text(encoding='utf-8'))

    def test_empty_display_is_allowed_only_after_exact_unfiltered_query(self):
        self.assertEqual(self.collector._query('rider_info', self.frame), {'code': 0, 'data': {}})
        self.option.click.assert_called_once()
        self.menu.wait_for.assert_called_once_with(state='hidden', timeout=5000)
        self.buttons['查询'].click.assert_called_once()
        self.buttons['导出'].click.assert_not_called()
        diagnostic = self.diagnostic()
        self.assertEqual((diagnostic['display'], diagnostic['placeholder']), ('empty', 'select'))
        self.assertTrue(diagnostic['menu_closed'])
        self.assertTrue(diagnostic['strict_query_confirmed'])

    def test_delayed_display_update_does_not_fail_before_strict_response(self):
        display = ['在职']
        self.status.input_value.side_effect = lambda: display[0]
        self.menu.wait_for.side_effect = lambda **kwargs: display.__setitem__(0, '全部')
        self.assertEqual(self.collector._query('rider_info', self.frame), {'code': 0, 'data': {}})
        self.assertEqual(self.diagnostic()['display'], 'all')
        self.assertTrue(self.diagnostic()['strict_query_confirmed'])

    def test_nonempty_filters_never_reach_collect_export_or_team_query(self):
        for query in ('pageIndex=1&pageSize=20&workStatus=1', 'pageIndex=1&knightId=001',
                      'pageIndex=1&workStatus=&workStatus=1', 'pageIndex=1&workStatus=%20',
                      'pageIndex=1&workStatus=&workStatus='):
            with self.subTest(query=query):
                self.response.url = sources.QUERIES['rider_info'] + '?' + query
                self.status.input_value.return_value = '全部'
                with self.assertRaises(TimeoutError):
                    self.collector.collect('rider_info')
                self.assertFalse(self.diagnostic()['strict_query_confirmed'])
                self.assertEqual(self.diagnostic()['stage'], 'query_unconfirmed')
                self.buttons['导出'].click.assert_not_called()
                self.collector.page.context.request.post.assert_not_called()

    def test_response_scope_is_explicitly_rechecked_even_if_waiter_returns_wrong_response(self):
        self.response.url += '&workStatus=1'
        pending = MagicMock()
        pending.__enter__.return_value.value = self.response
        self.collector.page.expect_response.side_effect = None
        self.collector.page.expect_response.return_value = pending
        with self.assertRaisesRegex(SourceError, '实际查询'):
            self.collector.collect('rider_info')
        self.assertEqual(self.diagnostic()['stage'], 'query_scope_rejected')
        self.assertFalse(self.diagnostic()['strict_query_confirmed'])
        self.buttons['导出'].click.assert_not_called()
        self.collector.page.context.request.post.assert_not_called()

    def test_unclosed_dropdown_stops_before_query_and_export(self):
        self.menu.wait_for.side_effect = TimeoutError('menu remains open')
        with self.assertRaises(TimeoutError):
            self.collector.collect('rider_info')
        self.collector.page.expect_response.assert_not_called()
        self.buttons['查询'].click.assert_not_called()
        self.buttons['导出'].click.assert_not_called()
        self.assertFalse(self.diagnostic()['menu_closed'])
        self.assertFalse(self.diagnostic()['strict_query_confirmed'])

    def test_status_diagnostic_saves_enums_without_input_or_placeholder_values(self):
        self.status.input_value.return_value = 'synthetic-private-name'
        self.status.get_attribute.return_value = 'synthetic-private-phone'
        self.collector._query('rider_info', self.frame)
        text = (self.root / 'staff_status_selection.json').read_text(encoding='utf-8')
        self.assertNotIn('synthetic-private', text)
        self.assertEqual((self.diagnostic()['display'], self.diagnostic()['placeholder']), ('other', 'other'))


if __name__ == '__main__':
    unittest.main()
