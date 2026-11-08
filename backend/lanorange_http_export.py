"""Official Blue Orange file downloads using the bundled Node HTTP runtime."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlencode
import zipfile
from fengshen_bill import BillCollectionError, atomic_json
from lanorange_catalog import DATASETS


def export_once(session, source, endpoint, params, output, cancelled):
    if source != 'lanorange' or endpoint not in {v[1] for v in DATASETS.values()}:
        raise BillCollectionError('蓝橙 HTTP 导出范围无效，未提交导出')
    if cancelled.is_set(): raise BillCollectionError('蓝橙下载已取消，未提交导出')
    node = os.environ.get('NODE_EXECUTABLE') or shutil.which('node')
    if not node: raise BillCollectionError('缺少系统 Node 运行时，未提交蓝橙导出')
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.parent / 'http_submission.json'
    started = time.time()
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump({'source':source,'endpoint':endpoint,'scope':params,'submission_state':'unknown',
                   'transport':'node_http','started_at':started},stream)
    temporary = output.with_suffix('.download.part')
    process = None; result = {}
    try:
        headers = dict(session.headers)
        headers.update({'Accept':'application/json, text/plain, */*',
                        'Content-Type':'application/x-www-form-urlencoded',
                        'Cookie':'Admin-Token=' + session.cookies.get('Admin-Token', '')})
        # Let the selected HTTP runtime negotiate its own supported encodings.
        headers.pop('Accept-Encoding', None)
        body = urlencode(params, doseq=True)
        if body: body += '&'
        process = subprocess.Popen([node, str(Path(__file__).with_suffix('.mjs'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        payload = {'endpoint':endpoint,'headers':headers,'body':body,'output':str(temporary.resolve())}
        process.stdin.write(json.dumps(payload).encode('utf-8')); process.stdin.close()
        payload.clear(); headers.clear()
        deadline = time.monotonic() + 210
        while process.poll() is None:
            if cancelled.wait(.2) or time.monotonic() > deadline:
                process.kill(); process.wait()
                raise BillCollectionError('蓝橙下载取消或超时，提交回执已保留')
        raw_result = process.stdout.read(65536)
        if not raw_result:
            raise BillCollectionError('蓝橙 HTTP 运行进程异常结束，文件未确认完成')
        result = json.loads(raw_result.decode('utf-8'))
        if process.returncode != 0 or result.get('ok') is not True or result.get('status') != 200:
            raise BillCollectionError('蓝橙文件传输中断，未收到完整文件')
        if not zipfile.is_zipfile(temporary): raise BillCollectionError('蓝橙返回的 Excel 文件不完整')
        with zipfile.ZipFile(temporary) as book:
            if '[Content_Types].xml' not in book.namelist() or book.testzip() is not None:
                raise BillCollectionError('蓝橙原始 Excel 文件校验失败')
        temporary.rename(output)
        with output.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        atomic_json(receipt,{'source':source,'endpoint':endpoint,'scope':params,'submission_state':'submitted',
            'transport':'node_http','started_at':started,'finished_at':time.time(),
            'bytes':output.stat().st_size,'sha256':digest})
        return output
    except Exception as exc:
        atomic_json(receipt,{'source':source,'endpoint':endpoint,'scope':params,'submission_state':'unknown',
            'transport':'node_http','started_at':started,'failed_at':time.time(),
            'downloaded_bytes':temporary.stat().st_size if temporary.is_file() else 0,
            'error_category':result.get('error_category',type(exc).__name__),'http_status':result.get('status'),
            'process_exit_code':process.returncode if process is not None else None})
        reason=str(exc) if isinstance(exc,BillCollectionError) else '蓝橙下载未确认完成'
        raise BillCollectionError(reason+'；回执已保留，不会自动重复提交') from None
    finally:
        if process is not None:
            if process.poll() is None: process.kill(); process.wait()
            if process.stdin and not process.stdin.closed: process.stdin.close()
            if process.stdout: process.stdout.close()
