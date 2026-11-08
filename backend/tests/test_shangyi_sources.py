import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shangyi_sources as sources
from parttime_source import SourceError

HEADERS = ['姓名', '身份证号', '银行预留手机号', '银行卡号', '企业名称', '小组名称', '状态',
           '创建时间', '合同信息', '身份证正面', '身份证背面']
ROW = ['测试', '0' * 17 + 'X', '0' * 11, '0' * 19, '测试企业', '泉州', '已签约',
       '2026-07-01', '', '', '']


class ShangyiSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows=None, headers=None, extra_sheet=False):
        book = Workbook()
        book.active.append(headers or HEADERS)
        for row in ([ROW] if rows is None else rows):
            book.active.append(row)
        if extra_sheet:
            book.create_sheet('Other')
        path = self.root / 'merchantFreelancer.xlsx'
        book.save(path)
        book.close()
        return path

    def test_all_regions_and_statuses_preserved_with_original_bytes(self):
        rows = [ROW, [*ROW[:5], '上海UB', '未签约', *ROW[7:]], [*ROW[:5], '广州UB', '签约中', *ROW[7:]]]
        path = self.write(rows)
        before = path.read_bytes()
        info = sources.validate_employees(path, 3)
        self.assertEqual(info['rows'], 3)
        self.assertEqual(set(info['groups']), {'泉州', '上海UB', '广州UB'})
        self.assertEqual(set(info['statuses']), {'已签约', '未签约', '签约中'})
        self.assertFalse(info['payroll_executed'])
        self.assertFalse(info['binding_generated'])
        self.assertEqual(before, path.read_bytes())

    def test_page_counts_never_block_valid_export(self):
        for total in (2, -1, True, None, 'unavailable'):
            with self.subTest(total=total):
                info = sources.validate_employees(self.write(), total)
                self.assertEqual(info['rows'], 1)
                self.assertEqual(info['count_comparison'], 'disabled')
                self.assertNotIn('page_total', info)

    def test_empty_export_does_not_depend_on_page_count(self):
        self.assertEqual(sources.validate_employees(self.write([]), 10)['rows'], 0)

    def test_numeric_and_formula_identifiers_rejected(self):
        for index, value in ((1, 123456789012345678), (3, 1234567890123456789), (2, 12345678901), (1, '=1+1')):
            row = ROW.copy()
            row[index] = value
            with self.subTest(index=index, value_type=type(value).__name__), self.assertRaisesRegex(SourceError, '精度风险'):
                sources.validate_employees(self.write([row]))

    def test_masked_or_blank_identity_retained_not_invented(self):
        a, b = ROW.copy(), ROW.copy()
        a[1], b[1] = '****001X', None
        info = sources.validate_employees(self.write([a, b]), 2)
        self.assertEqual((info['identity_masked'], info['identity_blank']), (1, 1))

    def test_bad_headers_extra_sheet_and_html_rejected(self):
        for headers in (HEADERS[:-1], [*HEADERS, '姓名']):
            with self.assertRaises(SourceError):
                sources.validate_employees(self.write(headers=headers))
        with self.assertRaises(SourceError):
            sources.validate_employees(self.write(extra_sheet=True))
        path = self.root / 'login.xlsx'
        path.write_text('<html>login</html>')
        with self.assertRaises(sources.BillCollectionError):
            sources.validate_employees(path)

    def test_workspace_must_not_escape_or_use_windows_devices(self):
        for workspace in (None, '', '../55', 'a/b', 'CON', 'LPT1', 'a' * 129):
            with self.subTest(workspace=workspace), self.assertRaises(SourceError):
                sources.workspace_directory(workspace, self.root)
        self.assertEqual(sources.workspace_directory('55', self.root), self.root / 'uploads' / '55')

    def test_failure_stage_and_raw_file_are_retained(self):
        cancelled = threading.Event()
        def factory(output, log, event):
            def collect():
                (output / 'raw.xlsx').write_bytes(b'original')
                raise SourceError('全量行数不一致')
            return SimpleNamespace(stage='validate', collect=collect)
        with patch.object(sources, 'ROOT', self.root), patch.object(sources, 'workspace_directory', return_value=self.root):
            with self.assertRaisesRegex(SourceError, '行数不一致'):
                sources.download_employees('55', lambda _: None, cancelled, factory)
        run = next(self.root.glob('shangyi_sources_*'))
        manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['status'], manifest['stage']), ('error', 'validate'))
        self.assertFalse(manifest['credentials_saved'])
        self.assertEqual((run / 'raw.xlsx').read_bytes(), b'original')
        self.assertFalse(sources.COLLECTION_LOCK.locked())

    def test_collection_lock_prevents_duplicate_download(self):
        with patch.object(sources, 'workspace_directory', return_value=self.root):
            sources.COLLECTION_LOCK.acquire()
            try:
                with self.assertRaisesRegex(SourceError, '正在运行'):
                    sources.download_employees('55', lambda _: None, threading.Event())
            finally:
                sources.COLLECTION_LOCK.release()

    def test_count_difference_is_published_as_success_without_altering_file(self):
        path = self.write()
        def factory(output, log, event):
            def collect():
                saved = output / path.name
                saved.write_bytes(path.read_bytes())
                return sources.validate_employees(saved, 2)
            return SimpleNamespace(stage='validate', collect=collect)
        with patch.object(sources, 'workspace_directory', return_value=self.root):
            run, manifest = sources.download_employees('55', lambda _: None, threading.Event(), factory)
        self.assertEqual(manifest['status'], 'success')
        self.assertEqual(manifest['datasets']['merchant_employees']['count_comparison'], 'disabled')
        self.assertEqual((run / path.name).read_bytes(), path.read_bytes())

    def test_failure_is_written_before_browser_cleanup(self):
        page, browser, pw, manager = Mock(), Mock(), Mock(), Mock()
        browser.new_context.return_value.new_page.return_value = page
        pw.chromium.launch.return_value = browser
        manager.__enter__ = Mock(return_value=pw)
        manager.__exit__ = Mock(side_effect=RuntimeError('cleanup failed'))
        collector = Mock(stage='validate')
        collector.collect.side_effect = SourceError('校验失败')
        def close():
            manifest = json.loads(next(self.root.glob('shangyi_sources_*/manifest.json')).read_text(encoding='utf-8'))
            self.assertEqual((manifest['status'], manifest['error']), ('error', '校验失败'))
        browser.close.side_effect = close
        with patch.object(sources, 'workspace_directory', return_value=self.root), patch.object(sources, 'owned_driver', return_value=None), patch.object(sources, 'ShangyiCollector', return_value=collector), patch('playwright.sync_api.sync_playwright', return_value=manager):
            with self.assertRaisesRegex(SourceError, '校验失败'):
                sources.download_employees('55', lambda _: None, threading.Event())
        self.assertFalse(sources.COLLECTION_LOCK.locked())

    def test_cleanup_watchdog_only_terminates_owned_driver(self):
        browser, process, owner, child, timer = Mock(), Mock(), Mock(), Mock(), Mock()
        owner.pid = 5
        process.create_time.return_value = 10
        process.ppid.return_value = 5
        process.children.return_value = [child]
        def make_timer(timeout, callback):
            timer.start.side_effect = callback
            return timer
        with patch.object(sources.threading, 'Timer', side_effect=make_timer), patch.object(sources.psutil, 'Process', side_effect=lambda pid=None: owner if pid is None else process):
            sources.close_browser(browser, (7, 10), lambda _: None)
        process.terminate.assert_called_once()
        child.terminate.assert_called_once()
        timer.cancel.assert_called_once()

    def test_cleanup_watchdog_does_not_terminate_reused_or_foreign_pid(self):
        for created, parent in ((11, 5), (10, 8)):
            browser, process, owner, timer = Mock(), Mock(), Mock(), Mock()
            owner.pid = 5
            process.create_time.return_value = created
            process.ppid.return_value = parent
            def make_timer(timeout, callback):
                timer.start.side_effect = callback
                return timer
            with patch.object(sources.threading, 'Timer', side_effect=make_timer), patch.object(sources.psutil, 'Process', side_effect=lambda pid=None: owner if pid is None else process):
                sources.close_browser(browser, (7, 10), lambda _: None)
            process.terminate.assert_not_called()
            process.children.assert_not_called()

    def test_driver_discovery_rejects_ambiguous_processes(self):
        first, second, owner = Mock(pid=1), Mock(pid=2), Mock()
        for process in (first, second):
            process.create_time.return_value = 10
            process.cmdline.return_value = ['C:/site-packages/playwright/driver/node.exe', 'cli.js', 'run-driver']
        owner.children.return_value = [first, second]
        with patch.object(sources.psutil, 'Process', return_value=owner):
            self.assertIsNone(sources.owned_driver(set()))
            self.assertEqual(sources.owned_driver({(2, 10)}), (1, 10))

    def collector(self, page):
        return sources.ShangyiCollector(page, self.root, lambda _: None, threading.Event(), human_timeout=2, download_timeout=2)

    def test_cancel_and_close_are_explicit(self):
        page = Mock()
        page.is_closed.return_value = False
        collector = self.collector(page)
        collector.cancelled.set()
        with self.assertRaisesRegex(SourceError, '取消'):
            collector.checkpoint()
        collector.cancelled.clear()
        page.is_closed.return_value = True
        with self.assertRaisesRegex(SourceError, '已关闭'):
            collector.checkpoint()

    def test_human_login_wait_never_fills_codes_or_auto_logs_in(self):
        page = Mock()
        page.is_closed.return_value = False
        page.url = 'https://merchant.shangyiworker.com/login?redirect=/index'
        collector = self.collector(page)
        with patch.object(collector, 'logged_in', side_effect=[False, True]):
            collector.wait_login()
        page.bring_to_front.assert_called_once()
        page.get_by_placeholder.assert_not_called()
        page.get_by_role.assert_not_called()
        page.wait_for_timeout.assert_called_once_with(500)

    def test_login_timeout_and_foreign_redirect_do_not_export(self):
        page = Mock()
        page.is_closed.return_value = False
        page.url = 'https://merchant.shangyiworker.com/login'
        collector = self.collector(page)
        with patch.object(collector, 'logged_in', return_value=False), patch.object(sources.time, 'monotonic', side_effect=[0, 3]):
            with self.assertRaisesRegex(SourceError, '30 分钟'):
                collector.wait_login()
        page.url = 'https://other.example/login'
        with patch.object(collector, 'logged_in', return_value=False):
            with self.assertRaisesRegex(SourceError, '未确认网站'):
                collector.wait_login()
        page.get_by_role.assert_not_called()

    def test_active_filters_block_export(self):
        page = Mock()
        page.is_closed.return_value = False
        field = Mock()
        field.input_value.return_value = '泉州'
        page.get_by_placeholder.return_value = field
        collector = self.collector(page)
        with patch.object(collector, 'one', side_effect=lambda locator, _: locator):
            with self.assertRaisesRegex(SourceError, '未清空'):
                collector.prepare()
        page.get_by_role.assert_called_once()

    def test_full_download_clicks_export_once_and_removes_listener(self):
        path = self.write()
        download = Mock(suggested_filename='merchantFreelancer.xlsx')
        download.failure.return_value = None
        download.save_as.side_effect = lambda output: output.write_bytes(path.read_bytes())
        page = Mock()
        page.is_closed.return_value = False
        button = Mock()
        handlers = {}
        page.on.side_effect = lambda name, handler: handlers.update({name: handler})
        button.click.side_effect = lambda: handlers['download'](download)
        page.get_by_role.return_value = button
        collector = self.collector(page)
        with patch.object(collector, 'wait_login'), patch.object(collector, 'prepare', return_value=1), patch.object(collector, 'one', side_effect=lambda loc, _: loc):
            info = collector.collect()
        self.assertEqual(info['rows'], 1)
        button.click.assert_called_once()
        page.remove_listener.assert_called_once()

    def test_download_timeout_never_resubmits(self):
        page = Mock()
        page.is_closed.return_value = False
        button = Mock()
        page.get_by_role.return_value = button
        collector = self.collector(page)
        with patch.object(collector, 'wait_login'), patch.object(collector, 'prepare', return_value=1), patch.object(collector, 'one', side_effect=lambda loc, _: loc), patch.object(collector, 'logged_in', return_value=True), patch.object(sources.time, 'monotonic', side_effect=[0, 3]):
            with self.assertRaisesRegex(SourceError, '超时'):
                collector.collect()
        button.click.assert_called_once()
        page.remove_listener.assert_called_once()


class HttpEmployeeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.path = self.employee_file()

    def tearDown(self):
        self.tmp.cleanup()

    def employee_file(self):
        book = Workbook()
        book.active.append(HEADERS)
        book.active.append(ROW)
        book.active.append(list(ROW))
        book.active.append([ROW[0], '1' * 17 + 'X', *ROW[2:]])
        path = self.root / 'merchantFreelancer.xlsx'
        book.save(path)
        book.close()
        return path

    def fake_sources(self, **changes):
        source = self.path
        class FakeSources:
            def __init__(self, root, log, cancelled):
                self.root = Path(root)
            def employees(self):
                target = self.root / 'baize' / 'merchantFreelancer_白泽全量.xlsx'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                info = {**sources.validate_bill_file(target), 'path': target.name, 'rows': 3, **changes}
                (target.parent / 'manifest.json').write_text(json.dumps(
                    {**info, 'status': 'success', 'scope': 'all', 'transport': 'http'},
                    ensure_ascii=False), encoding='utf-8')
                return target
        return FakeSources

    def test_http_download_writes_employee_manifest_with_local_evidence(self):
        with patch.object(sources, 'workspace_directory', return_value=self.root), \
             patch('binding_sources_http.BindingSources', self.fake_sources()):
            run, manifest = sources.download_employees_http('55', lambda _: None, threading.Event())
        info = manifest['datasets']['merchant_employees']
        self.assertEqual((manifest['status'], manifest['transport']), ('success', 'http'))
        self.assertEqual(info['rows'], 3)
        self.assertEqual(info['path'], 'baize/merchantFreelancer_白泽全量.xlsx')
        self.assertTrue((run / info['path']).is_file())
        self.assertFalse(sources.COLLECTION_LOCK.locked())

    def test_run_shangyi_sources_uses_http_not_a_browser(self):
        async def execute():
            return [event async for event in sources.run_shangyi_sources(SimpleNamespace(), '55')]
        with patch.object(sources, 'workspace_directory', return_value=self.root), \
             patch('binding_sources_http.BindingSources', self.fake_sources()), \
             patch.object(sources, 'download_employees') as legacy:
            events = asyncio.run(execute())
        legacy.assert_not_called()
        self.assertIn('"status": "success"', events[-1])
        self.assertEqual(sources.COLLECTION_LOCK.locked(), False)


class ShangyiRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_does_not_call_payroll_or_require_source(self):
        import main
        request = SimpleNamespace(headers={'x-workspace-id': '55', 'content-type': 'application/json'},
                                  url=SimpleNamespace(hostname='127.0.0.1'), method='POST')
        config = main.ConfigRequest(city='', sourcePath='', action='download_shangyi_employees')
        async def run(config, workspace):
            self.assertEqual(workspace, '55')
            yield 'data: {"type":"finish","status":"success"}\n\n'
        with patch.object(sources, 'run_shangyi_sources', side_effect=run), patch('tasks.run_main_calculation_gen') as payroll, \
                patch('auth_preflight.ensure_ready', lambda *args, **kwargs: None):
            response = await main.run_calculation(config, request)
            output = ''.join([value async for value in response.body_iterator])
        self.assertIn('success', output)
        payroll.assert_not_called()


if __name__ == '__main__':
    unittest.main()
