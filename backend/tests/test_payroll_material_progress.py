import unittest
from payroll_material_progress import material_progress


def run(key,status,kind='delivery_fee',phase='downloading',files=None):
    return {'id':key,'status':status,'phase':phase,'items':[{'dataset':kind,'status':status,'phase':phase}],
            'files':files or []}


class MaterialProgressTests(unittest.TestCase):
    def test_named_log_changes_do_not_repeat_or_expose_run_ids_and_percentages(self):
        from payroll_material_progress import material_log_changes
        rows=material_progress(self.state(),[run('abcdef','running')])
        messages,previous=material_log_changes(rows,{})
        self.assertEqual(messages,['【配送费 · 普通资料】正在下载'])
        self.assertEqual(material_log_changes(rows,previous)[0],[])
        rows=material_progress(self.state(),[run('abcdef','running',phase='waiting_export')])
        self.assertEqual(material_log_changes(rows,previous)[0],['【配送费 · 普通资料】等待平台生成文件'])
    def test_queued_dataset_never_inherits_other_items_downloading_phase(self):
        rows=material_progress(self.state(),[run('abcdef','queued',phase='downloading')])
        self.assertEqual(rows[0]['groups'][0]['detail'],'排队中')
    def state(self):return {'status':'preparing','items':{'delivery_fee':{'label':'配送费','status':'pending'}}}
    def test_item_phase_updates_before_overall_run_progress_changes(self):
        state=self.state();first=material_progress(state,[run('a','running')]);second=material_progress(state,[run('a','running',phase='waiting_export')])
        self.assertEqual(first[0]['status'],'running');self.assertEqual(second[0]['detail'],'等待平台生成文件');self.assertNotEqual(first,second)
        self.assertEqual(state['items']['delivery_fee']['status'],'pending')
    def test_downloaded_waits_for_integrity_and_ready_state_remains_authoritative(self):
        state=self.state();files=[{'dataset':'delivery_fee','name':'配送费.csv'}]
        item=material_progress(state,[run('a','success',files=files)])[0]
        self.assertEqual(item['status'],'validating');self.assertEqual(item['groups'][0]['files'],['配送费.csv'])
        state['items']['delivery_fee']['status']='ready';self.assertEqual(material_progress(state,[run('a','success',files=files)])[0]['status'],'ready')
    def test_two_scopes_and_retry_chain_do_not_inflate_the_file_count(self):
        state=self.state();state.update(include_separation=True,separation_agencies=['200'],job_scopes={'a':'normal','b':'200','c':'200'})
        rows=[run('a','success'),run('b','error'),run('c','running')]
        item=material_progress(state,rows)[0];self.assertEqual(item['status'],'running');self.assertEqual(item['completed_groups'],1);self.assertEqual(item['total_groups'],2);self.assertEqual(len(item['groups']),2)
    def test_payment_binding_shows_waiting_prerequisite_not_fake_downloading(self):
        state={'status':'preparing','items':{'payment_binding':{'label':'支付绑定','status':'pending'}}}
        rows=[run('a','queued','payment_binding'),{'id':'b','status':'waiting_login','items':[{'dataset':'rider_detail','status':'waiting_login'}],'files':[]}]
        item=material_progress(state,rows)[0];self.assertEqual(item['status'],'waiting_login');self.assertIn('来源',item['groups'][0]['detail'])

    def test_readable_progress_retains_source_cause_without_retry_guidance(self):
        from payroll_material_progress import material_log_changes
        state=self.state();state.update(input_policy='readable_delivery_v1',download_scope='single_selection',exclude_separation=True)
        source=run('a','error');source['items'][0]['error']='平台导出文件下载超时'
        rows=material_progress(state,[source]);messages,_=material_log_changes(rows,{})
        self.assertIn('平台导出文件下载超时',messages[0]);self.assertNotIn('重试',messages[0])
