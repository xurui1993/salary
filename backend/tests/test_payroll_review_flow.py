"""Synthetic finish events carry the same persisted review shown after reload."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
import payroll_inputs as inputs


class PayrollReviewFlowTests(unittest.TestCase):
    def test_unfinished_binding_verification_never_reaches_calculation_even_if_delivery_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            state={'id':'synthetic','mode':'fengshen','status':'preparing','workflow':'two_step_v1','input_policy':'readable_delivery_v1',
                   'jobs':['job'],'download_scope':'single_selection','download_owner':'test',
                   'plan':{'city':'测试城','start':'2026-10-01','end':'2026-10-15'},
                   'items':{'delivery_fee':{'label':'配送费','status':'pending'},'payment_binding':{'label':'支付绑定','status':'pending'}}}
            run={'id':'job','status':'error','phase':'failed','progress':0,'files':[], 'payroll_verification_required':True,
                 'items':[{'dataset':'payment_binding','status':'error','phase':'failed','error':'验证未完成'},
                          {'dataset':'delivery_fee','status':'success','phase':'completed'}]}
            from unittest.mock import Mock
            manager=Mock();manager.get_run.return_value=run
            def collect(*args):
                state['status']='ready';state['items']['delivery_fee']['status']='ready';state['items']['payment_binding']['status']='omitted'
            async def execute():
                return [event async for event in inputs._run_payroll(SimpleNamespace(),None,folder,state,__import__('threading').Event(),context=('shared','test'))]
            with patch('download_jobs.get_manager',return_value=manager),patch.object(inputs,'collect_finished',side_effect=collect),patch('tasks.run_main_calculation_gen') as engine:
                with self.assertRaisesRegex(inputs.SourceError,'未生成工资表'):asyncio.run(execute())
                engine.assert_not_called()

    def test_success_persists_summary_and_export_without_changing_engine_options(self):
        self.run_flow(False)

    def test_review_export_failure_keeps_calculated_result_and_reports_gap(self):
        self.run_flow(True)

    def run_flow(self, export_failure):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'input'
            source.mkdir()
            output = root/'output'
            output.mkdir()
            book = Workbook()
            book.active.title = '申请名单'
            book.active.append(['骑手ID'])
            book.active.append(['00123'])
            book.save(source/'test-template.xlsx')
            book.close()
            state = {'id':'synthetic','mode':'manual','status':'ready','jobs':[], 'created_at':'2026-10-31T00:00:00',
                     'template_hash':'template-hash', 'deductions':{'version':'rules-v1','rows':[{'保险':3}],'frozen':True},
                     'plan':{'city':'测试城','start':'2026-10-01','end':'2026-10-15','cycle':'半月结','applicants':1,'template':'test-template.xlsx'},
                     'items':{'delivery_fee':{'label':'配送费','status':'ready'},'lanorange_part_price':{'label':'价格档案','status':'omitted'},'payment_binding':{'label':'支付绑定','status':'omitted'}}}
            calls = []
            async def engine(*args, **kwargs):
                calls.append(kwargs)
                for name in ('工资表.xlsx','蓝橙无单价&未绑名单.xlsx'):
                    result=Workbook();result.save(output/name);result.close()
                yield 'data: '+json.dumps({'type':'finish','status':'success','out_file':str(output),'stats':{'riders':1,'orders':10,'no_price':1,'unbound':0,'intercepted':0}})+'\n\n'
            async def run():
                config = SimpleNamespace(payrollSourceMode='manual',payrollPreparationId='synthetic',basePath='',theme='',enableInterceptor=True,enableCrossStationMerge=False,deductionConfigVersion='rules-v1')
                return [event async for event in inputs.run_payroll(config, SimpleNamespace())]
            from payroll_review import write_review
            with patch.object(inputs,'workspace',return_value='shared'), patch.object(inputs,'load',return_value=(root,state)), \
                 patch.object(inputs,'claim_calculation',return_value=(root,state,source)), patch.object(inputs,'verified_hashes',return_value={}), \
                 patch.object(inputs,'publish_result',return_value=output), patch('tasks.run_main_calculation_gen',engine), \
                 patch('payroll_review.write_review',side_effect=OSError('synthetic-full-disk') if export_failure else write_review):
                events = asyncio.run(run())
            decoded = [json.loads(event[6:]) for event in events if event.startswith('data: ')]
            finish = next(event for event in decoded if event['type']=='finish')
            stored = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['status'],'calculated')
            self.assertEqual(finish['review_summary'],stored['result']['review_summary'])
            self.assertEqual(finish['review_summary']['status'],'pending_review')
            self.assertTrue(calls[0]['strict_inputs'])
            self.assertEqual(calls[0]['deductionRules'],[{'保险':3}])
            self.assertTrue(calls[0]['force_no_price'])
            if export_failure:
                self.assertIn('export_error',finish['review_summary'])
            else:
                self.assertEqual({p.name for p in output.iterdir()},{'工资表.xlsx','蓝橙无单价&未绑名单.xlsx'})
                result=load_workbook(output/'工资表.xlsx');self.assertIn('核算复核清单',result.sheetnames);result.close()
                self.assertEqual(stored['result']['delivery_layout'],'payroll_workbooks_v1')


if __name__ == '__main__':
    unittest.main()
