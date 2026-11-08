"""Passive, bounded metadata for the official SMS handshake. Never replays a request."""
import re
from urllib.parse import urlsplit
from desktop_auth_page import official_notice

ENDPOINTS={
    ('passport.meituan.com','/api/v3/account/mobileloginapply'):'sms_apply',
    ('passport.meituan.com','/api/v3/account/mobilelogin'):'sms_login',
    ('passport.meituan.com','/api/v1/account/verifylogin'):'login_verification',
    ('verify.meituan.com','/v2/ext_api/page_data'):'verification_config',
    ('verify.meituan.com','/v2/ext_api/extinfo'):'verification_result',
}

def endpoint(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme=='https' and parsed.hostname=='verify.meituan.com' and re.fullmatch(r'/v2/ext_api/[A-Za-z0-9_-]{1,64}/(info|verify)',parsed.path):
            return 'verification_info' if parsed.path.endswith('/info') else 'verification_submit'
        return ENDPOINTS.get((parsed.hostname,parsed.path)) if parsed.scheme=='https' else None
    except (TypeError,ValueError):return None

def result_code(value):
    if type(value) is int and -999999<=value<=999999:return str(value)
    if isinstance(value,str) and re.fullmatch(r'-?\d{1,6}',value):return value
    return None

class OfficialAuthTrace:
    def __init__(self,publish):self.publish=publish;self.events=[]

    def attach(self,context):
        context.on('requestfinished',self.finished)
        context.on('requestfailed',self.failed)

    def add(self,value):
        self.events.append(value);self.events=self.events[-8:]
        self.publish([dict(event) for event in self.events])

    def finished(self,request):
        stage=endpoint(request.url)
        if not stage:return
        try:
            response=request.response()
            if response is None:return
            event={'stage':stage,'http_status':int(response.status)}
            # Whitelisted JSON endpoints only. No URLs, headers, cookies, request
            # data, tokens or response payloads are retained in the event.
            try:payload=response.json()
            except Exception:
                event['result']='unreadable';self.add(event);return
            if isinstance(payload,dict):
                error=payload.get('error') if isinstance(payload.get('error'),dict) else {}
                code=result_code(error.get('code',payload.get('code',payload.get('status'))))
                if code is not None:event['official_code']=code
                message=error.get('message',payload.get('message',payload.get('msg','')))
                if isinstance(message,str) and message:
                    _,kind=official_notice(message)
                    event['category']=kind
            self.add(event)
        except Exception:
            # Exceptions may contain credentials or raw upstream payloads.
            self.add({'stage':stage,'result':'unreadable'})

    def failed(self,request):
        stage=endpoint(request.url)
        if stage:self.add({'stage':stage,'result':'network_failed'})
