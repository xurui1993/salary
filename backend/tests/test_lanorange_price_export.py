import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
import zipfile
from openpyxl import load_workbook

from lanorange_approval_client import OfficialApprovalClient,ApprovalError
from lanorange_price_export import PriceExports,query,latest,groups,read_station,long_rows
from price_export_workbook import WorkbookStream,HEADERS


class World:
    def __init__(self):
        self.actor='u1';self.version='v1';self.changed=False;self.calls=[]
        self.parents=[dict(id='p1',projectCode='project',cityId='c',siteId='s1',riderType='1',settleType='2',settleMonth='2026-10',settleStartDate='2026-10-01',settleEndDate='2026-10-02',cityName='合成市',siteName='合成站')]
        self.versions={'p1':[dict(id='b1',priceId='p1',version=1,status='3')]}
        self.headers={'b1':dict(id='b1',priceId='p1',version=1,status='3',settleType='2',settleStartDate='2026-10-01',settleEndDate='2026-10-02',cityName='合成市',siteName='合成站',areaName=None,riderNum=2)}
        self.rows={'b1':[dict(id='r1',batchId='b1',riderName='甲',idCard='000000000000000001',day1=0,day2=None),dict(id='r2',batchId='b1',riderName='乙',idCard='123456789012345678',day1='6.50',day2='')]}
    def factory(self):return Client(self)


class Client(OfficialApprovalClient):
    def __init__(self,world):self.w=world
    def __enter__(self):self.actor=self.w.actor;self.actor_label='合成账号';return self
    def __exit__(self,*args):pass
    def _get(self,path,params=None):
        w=self.w;params=params or {};w.calls.append((path,copy.deepcopy(params)))
        if path.endswith('/audit_status'):return {'data':[{'dictValue':k,'dictLabel':v} for k,v in [('0','审核通过'),('1','审核拒绝'),('2','待审核'),('3','审批中')]]}
        if path.endswith('/settle_type'):return {'data':[{'dictValue':'2','dictLabel':'月结'}]}
        if path=='salary/riderPrice/list':rows=w.parents
        elif path=='salary/partPriceBatch/list':rows=w.versions[params['priceId']]
        elif path=='salary/partPriceBatchDetail/list':
            assert params['delFlag']=='1';rows=copy.deepcopy(w.rows[params['batchId']])
            if w.changed and sum(p==path for p,_ in w.calls)>1:rows[0]['day1']=9
        elif path.startswith('salary/partPriceBatch/'):return {'data':copy.deepcopy(w.headers[path.rsplit('/',1)[1]])}
        else:raise AssertionError(path)
        page,size=params['pageNum'],params['pageSize'];return {'rows':copy.deepcopy(rows[(page-1)*size:page*size]),'total':len(rows)}


class DailyExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.w=World();self.filters=query({'month':'2026-10'})
        self.manager=PriceExports(self.root,self.w.factory,lambda:self.w.version)
    def read(self):return read_station(self.w.factory,self.w.parents,self.filters,'u1','v1',lambda:self.w.version,{'1':'审核拒绝','2':'待审核','3':'审批中'},{'2':'月结'},lambda:False)
    def start(self,scope='space1',request_id='request-0001'):
        return self.manager.start(scope,{'query':self.filters,'request_id':request_id},background=False)
    def test_latest_compares_all_versions_before_filtering_state(self):
        self.w.versions['p1'].append(dict(id='b2',priceId='p1',version=2,status='1'))
        receipt,snapshot=self.read();self.assertIsNone(snapshot);self.assertEqual(receipt['version'],'2');self.assertEqual(receipt['result'],'已跳过')
        self.assertFalse(any(p=='salary/partPriceBatch/b1' for p,_ in self.w.calls))
    def test_both_target_states_and_all_dates_preserve_zero_blank_and_exact_id(self):
        for status in ('2','3'):
            self.w.versions['p1'][0]['status']=status;self.w.headers['b1']['status']=status
            receipt,snapshot=self.read();self.assertEqual(receipt['result'],'已导出');rows=list(long_rows(snapshot));self.assertEqual(len(rows),4)
            by_name={name:[r for r in rows if r[5]==name] for name in ('甲','乙')}
            self.assertEqual(by_name['甲'][0][6],'000000000000000001');self.assertEqual(by_name['甲'][0][7],Decimal(0));self.assertIsNone(by_name['甲'][1][7]);self.assertIsNone(by_name['乙'][1][7]);self.assertEqual(by_name['乙'][0][7],Decimal('6.50'))
    def test_version_tie_unknown_status_and_missing_daily_column_fail_explicitly(self):
        cases=[lambda:self.w.versions['p1'].append(dict(id='duplicate',version=1,priceId='p1',status='3')),lambda:self.w.versions['p1'][0].update(status='unknown'),lambda:self.w.rows['b1'][0].pop('day2')]
        for change in cases:
            self.w=World();change();receipt,snapshot=self.read();self.assertIsNone(snapshot);self.assertEqual(receipt['result'],'失败')
    def test_source_change_or_identity_change_never_exports_mixed_prices(self):
        self.w.changed=True;self.assertEqual(self.read()[0]['result'],'失败');self.w.changed=False;self.w.actor='u2';self.assertEqual(self.read()[0]['result'],'失败');self.w.actor='u1';self.w.version='v2';self.assertEqual(self.read()[0]['result'],'失败')
    def test_date_filter_trims_period_without_removing_blank(self):
        self.filters.update(date_from='2026-10-02',date_to='2026-10-02');receipt,snapshot=self.read();rows=list(long_rows(snapshot));self.assertEqual(len(rows),2);self.assertTrue(all(r[1]==date(2026,10,2) and r[7] is None for r in rows))
    def test_pages_are_complete_and_business_groups_do_not_use_my_pending(self):
        self.w.rows['b1']=[dict(self.w.rows['b1'][0],id='r'+str(i)) for i in range(105)];self.w.headers['b1']['riderNum']=105
        with self.w.factory() as api:self.assertEqual(len(groups(api,self.filters)),1)
        receipt,snapshot=self.read();self.assertEqual(receipt['row_count'],210);self.assertEqual(len(snapshot['rows']),105);self.assertFalse(any('workflow' in p for p,_ in self.w.calls))
    def test_job_is_idempotent_scoped_and_download_is_hash_verified(self):
        job=self.start();self.assertEqual(job['id'],self.start()['id']);self.manager.run(job['id']);value=self.manager.get('space1',job['id']);self.assertEqual(value['status'],'completed');self.assertEqual(value['rows'],4)
        path=self.manager.result('space1',job['id']);self.assertEqual(len(self.manager.history('other')),0)
        with self.assertRaises(ApprovalError):self.manager.result('other',job['id'])
        book=load_workbook(path,read_only=True);self.addCleanup(book.close);self.assertEqual([c.value for c in next(book['每日价格'].rows)],HEADERS)
        values=list(book['每日价格'].values)[1:];self.assertEqual(len(values),4);self.assertEqual({r[6] for r in values},{'000000000000000001','123456789012345678'});self.assertTrue(all(isinstance(r[1],__import__('datetime').datetime) for r in values));self.assertEqual(book['每日价格']['G2'].data_type,'s')
        book.close();path.write_bytes(b'corrupt')
        with self.assertRaises(ApprovalError):self.manager.result('space1',job['id'])
    def test_station_failure_produces_partial_receipt_without_silent_data_loss(self):
        self.w.rows['b1'][0].pop('day1');job=self.start();self.manager.run(job['id']);value=self.manager.get('space1',job['id']);self.assertEqual(value['status'],'partial');self.assertEqual(value['receipts'][0]['result'],'失败');self.assertEqual(value['rows'],0)
    def test_restart_never_restarts_queued_export_and_stop_does_not_publish_file(self):
        job=self.start();fresh=PriceExports(self.root,self.w.factory,lambda:'v1');self.assertEqual(fresh.get('space1',job['id'])['status'],'interrupted')
        self.manager=fresh;job=self.start(request_id='request-0002');self.manager.update(job['id'],stop=1);self.manager.run(job['id']);self.assertEqual(self.manager.get('space1',job['id'])['status'],'cancelled')
        with self.assertRaises(ApprovalError):self.manager.result('space1',job['id'])
    def test_workbook_splits_before_excel_limit_and_text_cannot_be_formula(self):
        path=self.root/'split.xlsx'
        with WorkbookStream(path,'合成筛选',row_limit=3) as book:
            for i in range(5):book.append(['月结',date(2026,10,28),'市','','=2+2','骑手','000000000000000001',Decimal(0)])
            book.finish([{'business_id':'=HYPERLINK("bad")','result':'已导出'}])
        with zipfile.ZipFile(path) as source:self.assertIsNone(source.testzip())
        wb=load_workbook(path,read_only=True);self.addCleanup(wb.close);self.assertEqual(wb.sheetnames,['每日价格','每日价格2','每日价格3','采集记录']);self.assertEqual(sum(len(list(wb[s].values))-1 for s in wb.sheetnames[:-1]),5)
        self.assertEqual(wb['每日价格']['E2'].data_type,'s');self.assertEqual(wb['每日价格']['G2'].value,'000000000000000001');self.assertEqual(wb['每日价格']['G2'].number_format,'@');self.assertEqual(wb['采集记录']['A5'].data_type,'s')
        with zipfile.ZipFile(path) as source:
            xml=source.read('[Content_Types].xml');self.assertIn(b'<Types xmlns=',xml);self.assertIn(b'encoding="UTF-8"',xml)
    def test_invalid_queries_and_versions_are_not_guessed(self):
        for value in ({},{'month':'2026-99'},{'month':'2026-10','date_from':'bad'},{'month':'2026-10','status':'3'}):
            with self.assertRaises(ApprovalError):query(value)
        for versions in ([],[{'id':'b','version':'NaN'}],[{'id':'b','version':'bad'}]):
            with self.assertRaises(ApprovalError):latest(versions)


if __name__=='__main__':unittest.main()
