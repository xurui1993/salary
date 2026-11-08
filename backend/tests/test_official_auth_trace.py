import unittest
from unittest.mock import Mock
from official_auth_trace import OfficialAuthTrace,endpoint,result_code

class AuthTraceTests(unittest.TestCase):
    def request(self,payload,url='https://passport.meituan.com/api/v3/account/mobileloginapply?mobile=synthetic-secret'):
        request=Mock();request.url=url;request.response.return_value.status=200;request.response.return_value.json.return_value=payload
        return request

    def test_trace_is_passive_and_registers_only_completion_notifications(self):
        context=Mock();trace=OfficialAuthTrace(Mock());trace.attach(context)
        self.assertEqual([call.args[0] for call in context.on.call_args_list],['requestfinished','requestfailed'])
        context.route.assert_not_called();context.request.post.assert_not_called()

    def test_only_allowlisted_official_endpoint_is_read(self):
        for url in ('https://passport.meituan.com.attacker.test/api/v3/account/mobileloginapply','http://passport.meituan.com/api/v3/account/mobileloginapply','https://passport.meituan.com/unrelated'):
            request=self.request({},url);sink=Mock();OfficialAuthTrace(sink).finished(request)
            request.response.assert_not_called();sink.assert_not_called()

    def test_dynamic_official_verification_actions_keep_only_phase_not_action_or_query(self):
        self.assertEqual(endpoint('https://verify.meituan.com/v2/ext_api/synthetic_action/info?token=secret'),'verification_info')
        self.assertEqual(endpoint('https://verify.meituan.com/v2/ext_api/synthetic_action/verify'),'verification_submit')
        self.assertIsNone(endpoint('https://verify.meituan.com/v2/ext_api/synthetic_action/unrelated'))
        self.assertIsNone(endpoint('https://verify.meituan.com.attacker.test/v2/ext_api/synthetic_action/info'))

    def test_error_metadata_omits_phone_tokens_payload_query_and_message(self):
        request=self.request({'error':{'code':1001,'message':'请求异常，拒绝操作 synthetic-secret','data':{'token':'synthetic-token'}},'mobile':'synthetic-phone'})
        sink=Mock();OfficialAuthTrace(sink).finished(request);event=sink.call_args.args[0][0]
        self.assertEqual(event,{'stage':'sms_apply','http_status':200,'official_code':'1001','category':'rejected'})
        self.assertNotIn('synthetic',str(event));request.post_data.assert_not_called()

    def test_network_failure_never_reads_payload_or_failure_text(self):
        request=self.request({});sink=Mock();OfficialAuthTrace(sink).failed(request)
        self.assertEqual(sink.call_args.args[0],[{'stage':'sms_apply','result':'network_failed'}]);request.response.assert_not_called()

    def test_result_limit_and_snapshot_do_not_leak_previous_mutations(self):
        sink=Mock();trace=OfficialAuthTrace(sink)
        for index in range(12):trace.finished(self.request({'code':index}))
        self.assertEqual(len(trace.events),8);self.assertEqual(trace.events[0]['official_code'],'4')
        snapshot=sink.call_args.args[0];snapshot[0]['official_code']='changed';self.assertEqual(trace.events[0]['official_code'],'4')

    def test_bad_payload_and_parser_exception_do_not_echo_exception_text(self):
        sink=Mock();trace=OfficialAuthTrace(sink);request=self.request({});request.response.return_value.json.side_effect=RuntimeError('synthetic-secret')
        trace.finished(request);self.assertEqual(sink.call_args.args[0],[{'stage':'sms_apply','http_status':200,'result':'unreadable'}])

    def test_non_json_shape_is_not_retained(self):
        sink=Mock();OfficialAuthTrace(sink).finished(self.request(['synthetic-secret']))
        self.assertEqual(sink.call_args.args[0],[{'stage':'sms_apply','http_status':200}])

    def test_code_format_excludes_phones_and_arbitrary_strings(self):
        for value in (True,'12345678901','synthetic-secret','1234567',9999999,{},None):self.assertIsNone(result_code(value))
        self.assertEqual(result_code(-1),'-1');self.assertEqual(result_code('101000'),'101000')

    def test_rejection_status_survives_authentication_timeout_without_credentials(self):
        from xiaoxiang_source_auth import XiangAuth,SOURCE
        instance=XiangAuth();events=[{'stage':'sms_apply','http_status':403}]
        instance.states[SOURCE]={'state':'waiting_login','auth_network':events}
        instance._set('error','synthetic timeout');self.assertEqual(instance.status()['auth_network'],events)

    def test_login_page_processes_inputs_without_business_probe(self):
        from xiaoxiang_source_auth import XiangAuth,SOURCE
        import threading
        instance=XiangAuth();cancel=threading.Event();instance.cancelled[SOURCE]=cancel
        page=Mock();page.url='https://passport.meituan.com/useraccount/login';context=Mock();context.storage_state.return_value={'cookies':[]}
        instance._active_page=Mock(return_value=page);instance._capture_desktop=Mock()
        count=[0]
        def apply(*_):
            count[0]+=1
            if count[0]>=3:cancel.set()
        instance._apply_inputs=Mock(side_effect=apply);probe=Mock()
        self.assertFalse(instance._probe_until(context,page,probe));probe.assert_not_called();self.assertEqual(count[0],3)

    def test_official_redirect_triggers_real_business_verification(self):
        from xiaoxiang_source_auth import XiangAuth
        import time
        instance=XiangAuth();page=Mock();page.url='https://passport.meituan.com/useraccount/login'
        context=Mock();context.storage_state.return_value={'cookies':[]}
        instance._active_page=Mock(return_value=page);instance._apply_inputs=Mock();captures=[0]
        def capture(*_):
            captures[0]+=1
            if captures[0]>=2:page.url='https://maicaipeisong.meituan.com/notice/list.html'
        instance._capture_desktop=Mock(side_effect=capture);page.wait_for_timeout.side_effect=lambda _:time.sleep(.005)
        probe=Mock();self.assertTrue(instance._probe_until(context,page,probe));probe.assert_called_once()
