"""HTTP API for persistent Fengshen download jobs; no request owns a worker."""

import importlib
import os
import re
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from download_accounts import require_account, audit_event
from download_single_instance import DownloadInstanceBusy

from download_jobs import (DownloadManagerClosed, DownloadNotFound, DownloadResumeError, DownloadRootError, DownloadArchiveError,
                           DownloadSummaryError, DownloadSummaryPending, DownloadRequestConflict, configured_output_root, get_manager)


router = APIRouter(prefix="/api/fengshen-downloads")


@router.get('/delivery-download')
def payroll_delivery_download(request: Request, batch_id: str='', path: str=''):
    """Only a current workspace's registered payroll delivery, never arbitrary paths."""
    from pathlib import Path
    from payroll_inputs import load, workspace, publish_result, delivery_store
    from delivery_store import delivery_bundle
    from parttime_source import ROOT, SourceError
    user=require_account(request);wid=workspace(request)
    if not batch_id:
        for manifest in (Path(ROOT)/'uploads'/wid).glob('payroll_*/manifest.json'):
            import json
            try:
                state=json.loads(manifest.read_text(encoding='utf-8'))
                if path and Path(state.get('result',{}).get('output') or '').resolve()==Path(path).resolve():
                    batch_id=state['id'];break
            except (OSError,ValueError,KeyError):continue
    try:
        folder,state=load(wid,batch_id,user['owner'])
        if state['status']!='calculated':raise SourceError('核算尚未完成')
        publish_result(wid,folder,state)
        file,name=delivery_bundle(delivery_store(),'payroll:'+wid+':'+batch_id)
    except (SourceError,OSError,ValueError):
        raise HTTPException(404,'本工作区核算结果不存在或校验失败') from None
    return FileResponse(file,filename=name,media_type='application/zip',background=BackgroundTask(file.unlink,missing_ok=True))


def workspace_owner(request):
    try:
        owner = unquote(request.headers.get("x-workspace-id", ""), errors="strict")
    except (UnicodeError, ValueError):
        raise HTTPException(400, "缺少有效工作区标识") from None
    if not owner or len(owner) > 128 or any(char not in "_-" and not char.isalnum() for char in owner):
        raise HTTPException(400, "缺少有效工作区标识")
    return owner


async def _json(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "下载请求必须使用 JSON")
    try:
        data = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "下载参数必须是有效 JSON 对象") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "下载参数必须是 JSON 对象")
    return data


def _call(method, *args):
    try:
        return method(*args)
    except DownloadNotFound:
        raise HTTPException(404, "下载任务或文件不存在") from None
    except DownloadManagerClosed:
        raise HTTPException(503, "下载服务已停止，请重启服务后重试") from None
    except DownloadResumeError as exc:
        raise HTTPException(409, str(exc)) from None
    except DownloadSummaryPending as exc:
        raise HTTPException(409, str(exc)) from None
    except DownloadRequestConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except DownloadInstanceBusy as exc:
        raise HTTPException(503, str(exc)) from None
    except (DownloadSummaryError, DownloadRootError, DownloadArchiveError) as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(500, "下载任务服务暂时不可用，请稍后重试") from None


def _authorized(request, run_id):
    user = require_account(request)
    owner = _call(lambda: get_manager().run_owner(run_id)) if user["role"] == "admin" else user["owner"]
    return user, owner


def _request_id(payload):
    value = payload.get("request_id")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise HTTPException(400, "缺少有效提交标识，请刷新页面后重试")
    return value


@router.get("/options")
def options(request: Request):
    require_account(request)
    try:
        service = importlib.import_module("download_service")
        refresh = getattr(service, "refresh_cities", None)
        if refresh and os.environ.get('LOCAL_TEST_MODE') != '1' and request.query_params.get('cached') != '1':
            refresh(force=request.query_params.get("refresh") == "1")
        return {**service.get_options(), "archive_root": str(configured_output_root()), "archive_naming_version": 1}
    except DownloadRootError as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(503, "下载配置暂时不可用，请检查采集依赖") from None


@router.get("/runs")
def runs(request: Request):
    user = require_account(request)
    owner = None if user["role"] == "admin" else user["owner"]
    try:
        return {"runs": _call(lambda: get_manager().list_runs(owner))}
    except HTTPException as exc:
        if exc.status_code >= 500:
            return {"runs": []}
        raise
    except Exception:
        return {"runs": []}


@router.get('/records')
def records(request: Request):
    from download_records import list_records
    user = require_account(request)
    owner = None if user['role'] == 'admin' else user['owner']
    return {'records': _call(lambda: list_records(get_manager(), owner))}


@router.get('/records/{record_id}/bundle')
def download_record_bundle(record_id: str, request: Request, city: str | None = None, purpose: str = 'results'):
    from download_records import record_bundle
    user = require_account(request)
    owner = None if user['role'] == 'admin' else user['owner']
    path, filename = _call(lambda: record_bundle(get_manager(), owner, record_id, city, purpose))
    try:
        audit_event(user, 'download.record_bundle', record_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(path, filename=filename, media_type='application/zip', headers={'Cache-Control': 'no-store'},
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.post("/runs")
async def create(request: Request):
    user = require_account(request)
    owner = user["owner"]
    payload = await _json(request)
    request_id = _request_id(payload)
    try:
        service = importlib.import_module("download_service")
    except Exception:
        raise HTTPException(503, "下载组件暂时不可用，请检查采集依赖") from None
    try:
        config = service.validate_request(payload)
    except Exception as exc:
        validation_error = getattr(service, "ValidationError", None)
        if isinstance(validation_error, type) and isinstance(exc, validation_error):
            raise HTTPException(400, str(exc)) from None
        if isinstance(exc, (TypeError, ValueError)):
            raise HTTPException(400, "下载参数无效，请检查城市、资料类型和日期") from None
        raise HTTPException(500, "下载参数校验未完成，请稍后重试") from None
    from auth_preflight import gate_datasets
    gate_datasets(config['datasets'])
    result = _call(lambda: get_manager().create(owner, config, request_id=request_id))
    audit_event(user, "download.create", result["id"])
    return {"run": result}


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request):
    _, owner = _authorized(request, run_id)
    return {"run": _call(lambda: get_manager().get_run(owner, run_id))}


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, request: Request):
    user, owner = _authorized(request, run_id)
    await _json(request)
    result = _call(lambda: get_manager().cancel(owner, run_id))
    audit_event(user, "download.cancel", run_id)
    return {"run": result}


@router.post("/runs/{run_id}/resume-detail")
async def resume_detail(run_id: str, request: Request):
    user, owner = _authorized(request, run_id)
    payload = await _json(request)
    if payload:
        raise HTTPException(400, "恢复请求不接受自定义参数，请从原任务发起")
    original = _call(lambda: get_manager().get_run(owner, run_id))
    from auth_preflight import ensure_ready
    ensure_ready({'fengshen'})
    items = [{key: item[key] for key in ("city", "dataset", "start", "end")} for item in original["items"]
             if item["dataset"] == "rider_detail" and item["status"] in ("error", "cancelled", "interrupted")]
    result = _call(lambda: get_manager().retry(owner, run_id, items, "resume_" + run_id, actor_owner=user["owner"],
                                              allow_shared_result=user["role"] == "admin", existing_only=True))
    audit_event(user, "download.resume", result["id"])
    return {"run": result}


@router.post("/runs/{run_id}/retry")
async def retry(run_id: str, request: Request):
    user, owner = _authorized(request, run_id)
    payload = await _json(request)
    if set(payload) != {"items", "request_id"}:
        raise HTTPException(400, "恢复请求仅接受原任务子项和提交标识")
    request_id = _request_id(payload)
    original = _call(lambda: get_manager().get_run(owner, run_id))
    from auth_preflight import gate_datasets
    gate_datasets(original['datasets'])
    result = _call(lambda: get_manager().retry(owner, run_id, payload["items"], request_id, actor_owner=user["owner"],
                                              allow_shared_result=user["role"] == "admin"))
    audit_event(user, "download.retry", result["id"])
    return {"run": result}


@router.get("/runs/{run_id}/files/{file_id}")
def file(run_id: str, file_id: str, request: Request):
    user, owner = _authorized(request, run_id)
    manager=get_manager()
    run=_call(lambda:manager.get_run(owner,run_id))
    if run.get('result_layout')==3 and run['status'] in ('success','partial','error','cancelled','interrupted'):
        try:_call(lambda:manager.publish_delivery(owner,run_id))
        except HTTPException as error:
            if error.status_code!=404:raise
    path, filename = _call(lambda: get_manager().get_file(owner, run_id, file_id))
    audit_event(user, "download.file", run_id)
    return FileResponse(path, filename=filename, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})


@router.get("/runs/{run_id}/summary")
def summary(run_id: str, request: Request):
    user, owner = _authorized(request, run_id)
    path, filename = _call(lambda: get_manager().get_summary(owner, run_id))
    audit_event(user, "download.summary", run_id)
    return FileResponse(path, filename=filename, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.get("/runs/{run_id}/bundle")
def bundle(run_id: str, request: Request, city: str | None = None):
    user, owner = _authorized(request, run_id)
    path, filename = _call(lambda: get_manager().get_bundle(owner, run_id, city))
    try:
        audit_event(user, "download.bundle", run_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(path, filename=filename, media_type="application/zip", headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.get('/runs/{run_id}/raw-bundle')
def raw_bundle(run_id: str, request: Request):
    user,owner=_authorized(request,run_id)
    path,filename=_call(lambda:get_manager().get_raw_bundle(owner,run_id))
    try:audit_event(user,'download.raw_bundle',run_id)
    except Exception:
        path.unlink(missing_ok=True);raise
    return FileResponse(path,filename=filename,media_type='application/zip',headers={'Cache-Control':'no-store'},
                        background=BackgroundTask(path.unlink,missing_ok=True))
