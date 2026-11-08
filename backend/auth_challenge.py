"""Human-operated official security widget: bounded gestures and redacted notices."""
import math
import re
from fastapi import HTTPException

# Redaction runs inside the page: input values never leave the browser.
NOTICE_SCRIPT = r"""e=>{
  let text=e.innerText||'';
  for(const field of e.ownerDocument.querySelectorAll('input,textarea')){
    if(field.value)text=text.split(field.value).join('[已隐藏]');
  }
  return text.replace(/https?:\/\/\S+/gi,'[地址已隐藏]')
    .replace(/[A-Za-z0-9_@.+\/-]{4,}/g,'[已隐藏]').replace(/\d+/g,'*').slice(0,160);
}"""


def notice_detail(element):
    try:value=element.evaluate(NOTICE_SCRIPT)
    except Exception:return ''
    if not isinstance(value,str):return ''
    value=re.sub(r'https?://\S+','[地址已隐藏]',value[:500],flags=re.I)
    value=re.sub(r'[A-Za-z0-9_@.+/\-]{4,}','[已隐藏]',value)
    return re.sub(r'\d+','*',value)[:160]


def region(box):
    if not isinstance(box,dict):return None
    if any(type(box.get(k)) not in (int,float) or not math.isfinite(box[k]) for k in ('x','y','width','height')):return None
    if not (100<=box['width']<=1000 and 60<=box['height']<=750 and box['x']>=0 and box['y']>=0 and box['x']+box['width']<=1100 and box['y']+box['height']<=850):return None
    return {key:box[key] for key in ('x','y','width','height')}


def gesture(command):
    points=command.get('points');duration=command.get('duration_ms',500)
    if any(not isinstance(command.get(k),str) or not 1<=len(command[k])<=64 for k in ('challenge_id','challenge_version')) or not isinstance(points,list) or not 1<=len(points)<=64 or type(duration) is not int or not 100<=duration<=3000:
        raise HTTPException(400,'官方验证操作格式无效')
    if any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in p) for p in points):
        raise HTTPException(400,'验证位置超出官方验证区域')
    return {'challenge_id':command['challenge_id'],'challenge_version':command['challenge_version'],'points':points,'duration_ms':duration}


def apply_gesture(page,widget,expected,payload):
    actual=region(widget.bounding_box(timeout=1000))
    if widget.is_visible() is not True or actual is None or any(abs(actual[k]-expected[k])>2 for k in actual):
        raise ValueError('Official challenge changed')
    points=payload['points'];first=points[0]
    if len(points)==1:
        widget.click(position={'x':first[0]*actual['width'],'y':first[1]*actual['height']},timeout=1500)
        return
    def move(p):page.mouse.move(actual['x']+p[0]*actual['width'],actual['y']+p[1]*actual['height'])
    move(first);page.mouse.down()
    try:
        for point in points[1:]:
            move(point);page.wait_for_timeout(payload['duration_ms']/(len(points)-1))
    finally:page.mouse.up()
