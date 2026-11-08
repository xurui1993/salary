"""Conservative local arithmetic OCR; never evaluate page-provided code."""
import base64
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import unicodedata
import queue
import threading

_ocr_lock = threading.Lock()
_ocr_pending = set()
_ocr_results = {}
_ocr_queue = queue.Queue(maxsize=2)
_ocr_worker = None


def _run_ocr():
    while True:
        key, image = _ocr_queue.get()
        try:
            try:answer = recognize_image(image)
            except Exception:answer = None
            with _ocr_lock:
                _ocr_results[key] = answer
                while len(_ocr_results) > 16:
                    _ocr_results.pop(next(iter(_ocr_results)))
        finally:
            with _ocr_lock:
                _ocr_pending.discard(key)
            _ocr_queue.task_done()


def deferred_answer(image):
    """Only the image leaves the browser thread; never a locator or credentials."""
    global _ocr_worker
    key = hashlib.sha256(image).hexdigest()
    with _ocr_lock:
        if key in _ocr_results:
            answer = _ocr_results[key]
            return ('solved' if answer else 'manual'), answer
        if key not in _ocr_pending:
            try:
                _ocr_queue.put_nowait((key, image))
                _ocr_pending.add(key)
                if _ocr_worker is None or not _ocr_worker.is_alive():
                    _ocr_worker = threading.Thread(target=_run_ocr, daemon=True, name='captcha-ocr')
                    _ocr_worker.start()
            except queue.Full:
                pass
    return 'recognizing', None


def solve_expression(text):
    if not isinstance(text,str) or len(text)>80:return None
    text=unicodedata.normalize('NFKC',text)
    match=re.fullmatch(r'\s*(\d{1,3})\s*([+\-×xX*÷/])\s*(\d{1,3})\s*(?:=\s*[?？]?)?\s*',text)
    if not match:return None
    a,op,b=int(match[1]),match[2],int(match[3])
    op={'x':'*','X':'*','×':'*','÷':'/'}.get(op,op)
    if op=='/' and (b==0 or a%b):return None
    value=a+b if op=='+' else a-b if op=='-' else a*b if op=='*' else a//b
    return {'expression':f'{a} {op} {b}', 'answer':str(value)}


@lru_cache(maxsize=16)
def recognize_image(image):
    if os.name!='nt' or not isinstance(image,bytes) or not image.startswith(b'\x89PNG') or len(image)>262144:return None
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('auth_captcha_ocr.ps1'))],
            input=json.dumps({'image':base64.b64encode(image).decode()}),encoding='utf8',capture_output=True,timeout=12,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        payload=json.loads(result.stdout.lstrip('\ufeff').strip())
        if not isinstance(payload,dict):return None
        texts=payload.get('texts',[])
        values=[solve_expression(text) for text in texts]
        # Require agreement at original and enlarged scales. Ambiguity is manual.
        return values[0] if len(values)==2 and values[0] is not None and values[0]==values[1] else None
    except (OSError,subprocess.TimeoutExpired,ValueError,TypeError):return None


def inspect_captcha(page,fields,bindings,*,deferred=False):
    target=next((field for field in fields if field.get('role')=='math'),None)
    if not target:return None
    from desktop_auth_page import trusted
    deadline=time.perf_counter()+4
    for frame in page.frames:
        if not trusted('baize',frame.url):continue
        for image in frame.locator('img:visible, canvas:visible').all()[:20]:
            if time.perf_counter()>deadline:break
            box=image.bounding_box(timeout=500)
            if not box or not 35<=box['width']<=350 or not 12<=box['height']<=160:continue
            hint=' '.join(str(image.get_attribute(key,timeout=500) or '') for key in ('class','id','alt','title')).lower()
            if 'logo' in hint or not re.search(r'captcha|verify|validate|login.code|验证码|算式|计算',hint):continue
            try:
                loaded=image.evaluate("e=>e.tagName!=='IMG'||e.naturalWidth>0",timeout=500)
                if loaded is False:return {'field_id':target['id'],'state':'unavailable','id':hashlib.sha256(hint.encode()).hexdigest(),'_refresh':image}
                data=image.screenshot(type='png',timeout=1000)
            except Exception:continue
            if not isinstance(data,bytes) or len(data)>262144:continue
            direct=next((value for key in ('alt','title') if (value:=solve_expression(image.get_attribute(key,timeout=500)))),None)
            state, answer = ('solved',direct) if direct else deferred_answer(data) if deferred else ('manual',recognize_image(data))
            if answer:state='solved'
            return {'field_id':target['id'],'id':hashlib.sha256(data).hexdigest(),
                    'image':'data:image/png;base64,'+base64.b64encode(data).decode(),
                    'state':state,'_refresh':image,**(answer or {})}
    return {'field_id':target['id'],'state':'unavailable'}
