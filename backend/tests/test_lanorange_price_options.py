import copy,unittest
from unittest.mock import patch
import lanorange_price_options as options
from lanorange_approval_client import ApprovalError


class Fake:
    actor_label='合成账号'
    def __init__(self):self.calls=[];self.version='v1'
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def _get(self,path,params=None):
        self.calls.append((path,params))
        if path=='base/baseCity/queryList':return {'data':[{'id':'1','cityName':'甲市'},{'id':'2','cityName':'乙市'}]}
        if path=='base/baseSite/queryList':
            assert params=={'status':0}
            return {'data':[{'id':'s1','cityId':'1','siteName':'同名站'},{'id':'s2','cityId':'2','siteName':'同名站'},{'id':'s3','cityId':'not-authorized','siteName':'越界站'}]}
        if path=='salary/riderPrice/list':
            assert set(params)=={'pageNum','pageSize'}
            return {'total':3,'rows':[{'id':'p1','settleMonth':'2026-10'},{'id':'p2','settleMonth':'2026-09'},{'id':'p3','settleMonth':'2026-10'}]}
        raise AssertionError(path)


class OptionTests(unittest.TestCase):
    def setUp(self):options._cache.clear();self.api=Fake()
    def test_actual_authorized_directories_and_distinct_business_months_only(self):
        value=options.load_options(self.api)
        self.assertEqual(value['cities'],['乙市','甲市']);self.assertEqual(value['months'],['2026-10','2026-09'])
        self.assertEqual(len(value['stations']),2);self.assertEqual({s['city'] for s in value['stations']},{'甲市','乙市'})
        self.assertNotIn('NoPermission',str(self.api.calls));self.assertFalse(any('Detail' in p or 'complete' in p for p,_ in self.api.calls))
    def test_cache_copies_data_and_isolated_by_owner_and_session_version(self):
        kwargs={'factory':lambda:self.api,'version_fn':lambda:self.api.version}
        first=options.options('owner',**kwargs);first['cities'].clear()
        self.assertEqual(len(options.options('owner',**kwargs)['cities']),2);self.assertEqual(len(self.api.calls),3)
        options.options('other',**kwargs);self.assertEqual(len(self.api.calls),6)
        self.api.version='v2';self.assertEqual(options.options('other',**kwargs)['session_version'],'v2');self.assertEqual(len(self.api.calls),9)
        options.options('other',True,**kwargs);self.assertEqual(len(self.api.calls),12)
    def test_switch_during_loading_discards_result(self):
        with self.assertRaises(ApprovalError):options.options('owner',factory=lambda:self.api,version_fn=iter(['v1','v2']).__next__)
        self.assertFalse(options._cache)
    def test_incomplete_or_repeated_pages_are_rejected(self):
        original=self.api._get
        def broken(path,params=None):
            result=original(path,params)
            if 'total' in result:result['total']=4
            return result
        self.api._get=broken
        with self.assertRaises(ApprovalError):options.load_options(self.api)
    def test_directory_failure_does_not_cache_empty_choices(self):
        self.api._get=lambda *args:{'data':None}
        with self.assertRaises(ApprovalError):options.options('owner',factory=lambda:self.api,version_fn=lambda:'v1')
        self.assertFalse(options._cache)

if __name__=='__main__':unittest.main()
