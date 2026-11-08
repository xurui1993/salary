"""Metadata only: credentials stay in the browser worker, never in snapshots/logs."""
import hashlib
import secrets
import re
import time
from urllib.parse import urlparse

ROOTS = {'lanorange': ('madouren.cdevelopment.cn', 'login.dingtalk.com'), 'baize': ('merchant.shangyiworker.com',),
         'xiaoxiang': ('meituan.com', 'sankuai.com')}
MODES = {'账号登录','扫码登录','短信登录','密码登录','二维码登录','验证码登录','手机验证码登录','手机号登录','短信验证码登录','手机动态码登录','动态码登录','账号密码登录','通过手机号登录','通过邮箱登录'}
SUBMITS = {'登录', '登 录', '立即登录', '确认登录', '验证并登录','下一步','验证'}
OTHER = {'获取验证码','发送验证码','获取短信验证码','发送短信验证码','获取动态码','发送动态码','获取手机动态码','发送手机动态码','刷新二维码','刷新','点击刷新'}
COUNTDOWN = r'(?:重新获取|重新发送|重发|获取验证码)?[（(]?\s*(\d{1,3})\s*(?:秒|s)[）)]?(?:后重新获取|后重试|后重发)?'
CONSENT_LABEL = '我已阅读并同意《用户协议》《隐私政策》'



def official_notice(message):
    """Known categories only: never echo a phone, password or server payload."""
    if not isinstance(message,str) or not message.strip():return '', ''
    message=message[:1000]
    if re.search(r'(?:验证码|动态码|短信)已发送',message):
        return '官方已受理验证码发送；是否收到请以手机为准', 'sms_sent'
    if re.search(r'频繁|次数.{0,8}(过多|上限)|发送.{0,8}(上限|限制)',message):
        return '官方限制验证码发送频率，请按官方提示稍后重试；不会自动重发', 'sms_rejected'
    if re.search(r'(手机号|手机号码).{0,12}(错误|不正确|无效|不存在|未注册)|请输入正确的?(手机号|手机号码)',message):
        return '官方未接受该手机号，请核对号码与平台账号', 'sms_rejected'
    if re.search(r'网络.{0,8}(异常|错误|超时)|(?:发送|短信|动态码).{0,12}(失败|异常)',message):
        return '官方尚未确认验证码发送成功，请检查网络及官方提示；不会自动重发', 'sms_rejected'
    if re.search(r'验证码.{0,8}(错误|失效|过期)|验证码不正确',message):
        return '官方提示验证码无效，请核对或按官方提示重新获取', 'login_error'
    if re.search(r'密码.{0,8}(错误|不正确)|账号.{0,8}(不存在|错误)|登录失败',message):
        return '官方未接受此次登录，请核对账号和密码', 'login_error'
    # Consent prompts often mention 账号安全, so they must win over the challenge rule.
    if re.search(r'勾选|未同意|(?:同意|阅读).{0,10}(?:协议|条款|隐私)',message):
        return '官方要求先勾选并同意用户协议；请勾选协议后重新点击登录', 'consent_required'
    if re.search(r'滑块|拼图|拖动|安全验证|风控|风险|完成.{0,8}验证|为了您的账号安全|账号存在异常|请进行验证',message):
        return '官方要求完成安全验证，验证码尚未确认发送', 'challenge'
    if re.search(r'环境.{0,8}(异常|不安全)|访问.{0,8}(限制|禁止)|权限|禁止',message):
        return '官方未通过当前认证环境或访问权限检查，验证码尚未确认发送', 'environment_rejected'
    if re.search(r'异常|失败|错误',message):
        return '官方未接受此次操作，验证码尚未确认发送；请查看下方官方提示', 'rejected'
    return '官方返回了其他提示，本次操作结果尚未确认；请按官方页面提示核对', 'unknown'


def usable(element):
    """Playwright :visible alone includes transparent, inactive login panels."""
    return element.evaluate("""e=>{
      for(let a=e;a;a=a.parentElement){let s=getComputedStyle(a);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.01||a.inert||a.getAttribute('aria-hidden')==='true')return false;}
      let r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
      if(r.width<1||r.height<1||x<0||y<0||x>=innerWidth||y>=innerHeight)return false;
      let hit=document.elementFromPoint(x,y);return hit===e||!!hit&&e.contains(hit);
    }""")


def trusted(source, url):
    parsed = urlparse(url)
    host = parsed.hostname or ''
    return parsed.scheme == 'https' and any(host == root or host.endswith('.' + root) for root in ROOTS[source])


def field_role(source,kind,hint):
    if kind=='password' or re.search(r'password|密码',hint,re.I):return 'password'
    if kind=='checkbox':return 'consent'
    if re.search(r'语音.{0,8}验证码|语音码|固定码',hint):return 'voice_code'
    if re.search(r'captcha|验证码|校验码|动态码|\bcode\b',hint,re.I):return 'math' if source=='baize' else 'sms_code'
    if re.search(r'phone|mobile|tel|手机',hint,re.I):return 'phone'
    return 'username'


def inspect_login_page(source, page, previous=None):
    fields, controls, bindings = [], [], {}
    deadline=time.perf_counter()+4
    boxes, qr = [], None
    seen_controls = set()
    qr_expired, feedback, feedback_kind, detail = False, '', '', ''
    challenge=None;challenge_region=None;challenge_id=None;qr_element=None
    for frame_index, frame in enumerate(page.frames):
        if time.perf_counter()>deadline:break
        if not trusted(source, frame.url):
            continue
        for index, element in enumerate(frame.locator('input:visible:not([type=hidden]), textarea:visible').all()[:60]):
            if time.perf_counter()>deadline or len(fields)>=12:break
            if not usable(element):continue
            data = element.evaluate("e=>({type:e.type||'text',name:e.name||e.id||'',label:e.getAttribute('aria-label')||e.placeholder||(e.type==='checkbox'?e.closest('label')?.innerText:'')||'',filled:e.type==='checkbox'?e.checked:!!e.value,focused:e===document.activeElement,disabled:e.disabled||e.readOnly})")
            if data.get('disabled') or data['type'] in ('radio', 'button', 'submit', 'file'):
                continue
            key = hashlib.sha256(f'{frame_index}:{frame.url}:{index}:{data["type"]}:{data["name"]}:{data["label"]}'.encode()).hexdigest()[:20]
            label = data['label'][:60] or ('密码' if data['type'] == 'password' else data['name'][:40] or '输入项')
            role=field_role(source,data['type'],data['name']+' '+label)
            fields.append({'id': key, 'type': data['type'], 'role':role, 'label': label,
                           'filled': data['filled'], 'focused': data['focused']})
            bindings[key] = element
            box = element.bounding_box()
            if box: boxes.append(box)
        named=re.compile(r'^\s*(?:'+ '|'.join(re.escape(label) for label in MODES|SUBMITS|OTHER) +'|'+COUNTDOWN+r')\s*$')
        selector='button:visible, input[type=button]:visible, input[type=submit]:visible, [role=button]:visible, [role=tab]:visible, a:visible'
        # Do not walk unrelated decorative spans on each form poll; exact
        # named controls below still include span-based buttons and mode tabs.
        candidates=frame.locator(selector+('' if source in ('baize','xiaoxiang') else ', span:visible')).all()[:160]
        candidates+=frame.get_by_text(named).all()[:40]
        for index, element in enumerate(candidates):
            if time.perf_counter()>deadline:break
            label = ' '.join(element.evaluate("e=>e.tagName==='INPUT'?e.value:e.innerText").split())
            countdown=re.fullmatch(COUNTDOWN,label)
            if label not in MODES | SUBMITS | OTHER and not countdown:continue
            if not usable(element):continue
            if (frame_index, label) in seen_controls:
                continue
            seen_controls.add((frame_index, label))
            canonical='获取验证码' if countdown else label
            key = hashlib.sha256(f'{frame_index}:{frame.url}:button:{index}:{canonical}'.encode()).hexdigest()[:20]
            controls.append({'id': key, 'label': label, 'kind': 'mode' if label in MODES else 'submit' if label in SUBMITS else 'sms' if '验证码' in canonical or '动态码' in canonical or countdown else 'other','enabled':bool(element.is_enabled()) and not bool(countdown),'retry_after':int(countdown[1]) if countdown else 0,'issuer':urlparse(frame.url).hostname or ''})
            bindings[key] = element
            box = element.bounding_box()
            if box: boxes.append(box)
        for element in frame.locator('canvas:visible, img:visible').all()[:30]:
            if time.perf_counter()>deadline:break
            box = element.bounding_box()
            if not box or not 110 <= box['width'] <= 500 or not .8 <= box['width'] / max(box['height'], 1) <= 1.2:
                continue
            hint = ' '.join((element.get_attribute(k) or '') for k in ('class', 'id', 'src', 'alt')).lower()
            if 'captcha' in hint: continue
            is_canvas = element.evaluate('e=>e.tagName') == 'CANVAS'
            if not is_canvas and 'qr' not in hint and '二维码' not in hint: continue
            score = 3 + (5 if is_canvas else 0) + (8 if 'qr' in hint or '二维码' in hint else 0)
            if qr is None or score > qr[0]: qr = (score, box, element)
        try:
            expired = frame.get_by_text(re.compile(r'二维码.{0,6}(已失效|已过期|失效|过期)|扫码.{0,4}超时')).first
            if expired.is_visible() is True: qr_expired = True
        except Exception:
            pass
        for element in frame.locator('[role=alert]:visible, .el-message--error:visible, .ant-message-error:visible, .error-message:visible, .error-info:visible, #iLoginCompShowTip:visible, #firstTip:visible, #secondTip:visible, #confirmTip:visible').all()[:8]:
            message = element.inner_text()
            notice,kind=official_notice(message)
            if notice and (feedback_kind!='challenge' or kind=='challenge'):
                feedback,feedback_kind=notice,kind
                from auth_challenge import notice_detail
                detail=notice_detail(element)
        if source=='xiaoxiang':
            # 美团协议勾选框是隐藏 input（input:visible 永远读不到），
            # 这里单独识别并交给系统自动勾选，面板只展示可取消的复选框。
            if fields:
                try:
                    consent_elements=frame.locator('#iloginUserConfirm input#inputChecked, .iLoginComp-user-confirm input[type=checkbox]').all()[:1]
                except Exception:
                    consent_elements=[]
                for element in consent_elements:
                    try:
                        consent=element.evaluate("e=>({checked:!!e.checked})")
                    except Exception:
                        consent=None
                    if not isinstance(consent,dict) or not isinstance(consent.get('checked'),bool):
                        continue
                    consent_id=hashlib.sha256(b'xiaoxiang:consent').hexdigest()[:20]
                    if not any(item['id']==consent_id for item in fields):
                        fields.append({'id':consent_id,'type':'checkbox','role':'consent','label':CONSENT_LABEL,
                                       'filled':consent['checked'],'focused':False,'auto':True})
                        bindings[consent_id]=element
                    break
            # 语音验证页的隐藏 Yoda 根节点会残留，误报安全验证；以页面上的语音验证码输入框为准。
            voice_stage=any(item['role']=='voice_code' for item in fields)
            if voice_stage and not feedback:
                feedback,feedback_kind='官方已进入语音二次验证；语音验证码为动态码，请接听语音电话后填入','voice_required'
            if not voice_stage:
                for element in frame.locator('#smdcodeYodaRoot:visible, #secYodaRoot:visible, #thirdYodaRoot:visible').all()[:3]:
                    if element.is_visible() is True and usable(element):
                        feedback,feedback_kind='官方要求安全验证，验证码尚未确认发送；请先完成官方验证，不会自动重发', 'challenge'
                        from auth_challenge import region as challenge_box
                        box=challenge_box(element.bounding_box(timeout=500))
                        # Capture only a dedicated Yoda root, never a login form.
                        if box is not None and element.locator('input[type=password], input[type=tel], #phoneNumInput, #codeInput').count()==0:
                            challenge=element;challenge_region=box
                            challenge_id=hashlib.sha256((str(frame_index)+frame.url+str(element.get_attribute('id'))+repr(box)).encode()).hexdigest()[:24]
                        break
    def region(box, padding=24):
        x, y = min(1099, max(0, box['x'] - padding)), min(849, max(0, box['y'] - padding))
        right, bottom = min(1100, box['x'] + box['width'] + padding), min(850, box['y'] + box['height'] + padding)
        return {'x': x, 'y': y, 'width': max(1, right - x), 'height': max(1, bottom - y)}
    if source=='lanorange':
        for control in controls:
            if control['label']=='刷新二维码' or (control['label'] in ('刷新','点击刷新') and qr_expired):control['kind']='qr_refresh'
    regions = {}
    if challenge_region:regions['challenge']=challenge_region
    if qr:
        regions['qr'] = region(qr[1])
        qr_element = qr[2]
    if boxes:
        x, y = min(b['x'] for b in boxes), min(b['y'] for b in boxes)
        regions['login'] = region({'x': x, 'y': y,
                                  'width': max(b['x'] + b['width'] for b in boxes) - x,
                                  'height': max(b['y'] + b['height'] for b in boxes) - y})
    math_captcha=None
    if source=='baize':
        from auth_math_captcha import inspect_captcha
        math_captcha=inspect_captcha(page,fields,bindings,deferred=True)
        refresh=(math_captcha or {}).pop('_refresh',None)
        if refresh is not None:
            control_id=hashlib.sha256(('captcha:'+str((math_captcha or {}).get('id',''))).encode()).hexdigest()[:20]
            controls.append({'id':control_id,'label':'刷新算式','kind':'captcha_refresh','enabled':True,'retry_after':0});bindings[control_id]=refresh
    signature = hashlib.sha256((page.url + repr([(f['id'], f['type']) for f in fields]) + repr([(c['id'],c['kind']) for c in controls])+str((math_captcha or {}).get('id',''))).encode()).hexdigest()
    version = previous['form_id'] if previous and previous.get('_signature') == signature else secrets.token_urlsafe(18)
    return {'fields': fields, 'controls': controls, 'math_captcha':math_captcha, 'regions': regions, 'form_id': version, '_signature': signature,
            'qr_state': 'expired' if qr_expired else 'visible' if qr else 'not_detected', 'official_feedback': feedback, 'official_feedback_kind':feedback_kind, 'official_feedback_detail':detail,
            'challenge_id':challenge_id,'_challenge':challenge,'_qr_element':qr_element,
            'form_detection': 'fields_detected' if fields else 'qr_only' if qr else 'not_detected'}, bindings
