# ==========================================
# 核心后端接口服务 (FastAPI)
# 本文件主要用于：
# 1. 提供前端调用的REST API接口及SSE(Server-Sent Events)流式任务输出
# 2. 调用 processor, tasks 等核心计算逻辑
# 3. 提供本地资源管理器弹窗、系统状态监控等辅助接口
# ==========================================
import zipfile
import hashlib_compat
from workbook_policy import install_zip_policy
install_zip_policy()

from fastapi import FastAPI, Request, HTTPException
from contextlib import asynccontextmanager
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fengshen_auth_routes import router as fengshen_auth_router
from download_routes import router as download_router
from binding_source_auth import AUTH as source_auth, router as binding_source_auth_router
from platform_auth_control import router as platform_auth_router
from lanorange_approvals import router as lanorange_approvals_router
from lanorange_price_export import router as lanorange_prices_router
from payroll_inputs import router as payroll_inputs_router
from workbench import router as workbench_router
from download_jobs import shutdown_manager
from legacy_download_boundary import LegacyDownloadBoundary
from typing import Optional
import asyncio
import threading
import os
import sys
import json
import subprocess
import tempfile
import uuid
try:
    import psutil
except ImportError:
    psutil = None

def _warm_city_catalog():
    try:
        from fengshen_city_catalog import refresh
        refresh()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app):
    from download_path_registry import refresh_protected_roots
    refresh_protected_roots()
    if os.environ.get('LOCAL_TEST_MODE') != '1':
        from payroll_queue import get_queue
        get_queue()
    if os.environ.get('LOCAL_TEST_MODE') != '1':
        source_auth.start_keepalive()
        from xiaoxiang_source_auth import AUTH as xiang_auth
        xiang_auth.start_keepalive()
        threading.Thread(target=_warm_city_catalog, daemon=True).start()
    try:
        yield
    finally:
        from lanorange_approvals import shutdown as shutdown_approvals
        shutdown_approvals()
        from lanorange_price_export import shutdown as shutdown_prices
        shutdown_prices()
        from payroll_queue import shutdown_queue
        shutdown_queue()
        shutdown_manager()


app = FastAPI(title="Aegis Payroll Core API", lifespan=lifespan)
app.add_middleware(LegacyDownloadBoundary)

# 配置跨域，方便本地前端(如 Vite)进行跨域调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fengshen_auth_router)
app.include_router(download_router)
app.include_router(binding_source_auth_router)
app.include_router(platform_auth_router)
app.include_router(lanorange_approvals_router)
app.include_router(lanorange_prices_router)
app.include_router(payroll_inputs_router)
app.include_router(workbench_router)
from payroll_queue import router as payroll_queue_router
app.include_router(payroll_queue_router)
from task_center import router as task_center_router
app.include_router(task_center_router)


class ConfigRequest(BaseModel):
    city: str
    cycle: Optional[str] = ""
    basePath: str = ""
    sourcePath: str
    action: str = None
    targetPath: str = None
    theme: dict = None
    enableInterceptor: bool = False
    enableCrossStationMerge: bool = False
    deductionRules: list = []
    taskQueue: list = None
    payrollSourceMode: str = "fengshen"
    payrollOnlySeparation: bool = False
    payrollExcludeSeparation: bool = True
    payrollPreparationId: str = ""
    preparationOnly: bool = False
    deductionConfigVersion: str = ""

class FileRequest(BaseModel):
    path: str
    mode: str = "fengshen"

@app.post("/api/parttime/plan")
def payroll_plan(params: FileRequest, request: Request):
    from dataclasses import asdict
    from parttime_source import inspect_source, owned_upload, source_files, SourceError
    from payroll_inputs import workspace
    try:
        from payroll_business import inspect_payroll
        folder, _ = owned_upload(params.path, workspace(request))
        plan, _, mode = inspect_payroll(folder, params.mode)
        return {'success': True, 'plan': asdict(plan), 'mode': mode}
    except SourceError as exc:
        return {'success': False, 'error': str(exc)}

CONFIG_FILE = ".aegis_config.json"

@app.get("/api/parttime/fengshen/status")
def get_fengshen_status():
    from parttime_source import configuration_status
    return configuration_status()

@app.get("/api/parttime/shangyi/status")
def get_shangyi_status():
    return {"available": True, "scope": "all", "payroll_executed": False}

@app.post("/api/parttime/fengshen/plan")
def get_fengshen_plan(params: FileRequest, request: Request):
    from dataclasses import asdict
    from parttime_source import inspect_source, owned_upload, validate_collection_window, SourceError
    try:
        folder, _ = owned_upload(params.path, request.headers.get("x-workspace-id"))
        plan, _, _ = inspect_source(folder)
        validate_collection_window(plan)
        return {"success": True, "plan": asdict(plan)}
    except SourceError as exc:
        return {"success": False, "error": str(exc)}

@app.post("/api/parttime/fengshen/rider-sources/plan")
def get_rider_sources_plan(params: FileRequest, request: Request):
    from dataclasses import asdict
    from fengshen_auth_routes import local_owner
    from parttime_source import owned_upload, SourceError
    from rider_sources import inspect_template
    owner = local_owner(request)
    try:
        folder, _ = owned_upload(params.path, owner)
        return {"success": True, "plan": asdict(inspect_template(folder)), "payroll_executed": False}
    except SourceError as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/config")
def get_config():
    # 处理逻辑：配置数据的读取与保存，用于状态持久化
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

@app.post("/api/config")
def save_config(params: dict):
    # 处理逻辑：配置数据的读取与保存，用于状态持久化
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

class DialogRequest(BaseModel):
    title: str = "选择"

@app.post("/api/dialog/folder")
def select_folder(req: DialogRequest):
    # 处理逻辑：处理文件或目录的选择交互及路径解析
    title = req.title
    try:
        tmp_path = os.path.join(tempfile.gettempdir(), f"path_folder_{uuid.uuid4().hex}.txt").replace('\\', '/')
        # 使用 subprocess 在主线程运行 tkinter，避免 FastAPI 线程池冲突
        code = f'''
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askdirectory(title={title!r})
with open(r"{tmp_path}", "w", encoding="utf-8") as f:
    f.write(path)
'''
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        path = ""
        if os.path.exists(tmp_path):
            with open(tmp_path, "r", encoding="utf-8") as f:
                path = f.read().strip()
            os.remove(tmp_path)
        return {"path": path, "error": ""}
    except Exception as e:
        return {"path": "", "error": str(e)}

class SmartSourceRequest(BaseModel):
    basePath: str = ""

@app.post("/api/dialog/smart_source")
def check_smart_source(req: SmartSourceRequest, request: Request):
    from pathlib import Path
    from download_routes import workspace_owner
    from parttime_source import ROOT, owned_upload, source_files, SourceError
    wid = workspace_owner(request)
    owner = (Path(ROOT) / 'uploads' / wid).resolve()
    candidates = [Path(req.basePath)] if req.basePath else []
    if owner.is_dir():
        candidates.extend(sorted(owner.glob('upload_*'), key=lambda p: p.stat().st_mtime, reverse=True))
    for candidate in candidates:
        try:
            folder, _ = owned_upload(candidate, wid, root=ROOT)
            if source_files(folder):
                return {'path': str(folder), 'error': '', 'smart': True}
        except (SourceError, OSError):
            continue
    return {'path': '', 'error': '请先上传本工作区资料', 'smart': False}

@app.post("/api/dialog/file")
def select_file(req: DialogRequest):
    # 处理逻辑：处理文件或目录的选择交互及路径解析
    title = req.title
    try:
        tmp_path = os.path.join(tempfile.gettempdir(), f"path_file_{uuid.uuid4().hex}.txt").replace('\\', '/')
        code = f'''
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = filedialog.askopenfilename(title={title!r})
with open(r"{tmp_path}", "w", encoding="utf-8") as f:
    f.write(path)
'''
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        path = ""
        if os.path.exists(tmp_path):
            with open(tmp_path, "r", encoding="utf-8") as f:
                path = f.read().strip()
            os.remove(tmp_path)
        return {"path": path, "error": ""}
    except Exception as e:
        return {"path": "", "error": str(e)}

@app.get("/api/default_paths")
def get_default_paths():
    # 处理逻辑：获取并返回所需的系统状态或计算数据
    return {"configPath": "./data/config.json", "dataPath": "./uploads"}

class ConfigDataRequest(BaseModel):
    configPath: str = None

@app.post("/api/config_excel_data")
def get_config_excel_data(req: ConfigDataRequest):
    try:
        import sys
        import json
        import pandas as pd
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            project_root = os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() in ['dist', 'build'] else exe_dir
        else:
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_file_dir) if os.path.basename(current_file_dir) == 'backend' else current_file_dir
            
        config_path = req.configPath or os.path.join(project_root, "data/config.json")
        if config_path.endswith("config.xlsx"):
            config_path = config_path.replace("config.xlsx", "config.json")
            
        if not os.path.exists(config_path):
            config_path = os.path.join(project_root, "config.json")
            
        if not os.path.exists(config_path):
            xlsx_path = os.path.join(project_root, "data/config.xlsx")
            if not os.path.exists(xlsx_path):
                xlsx_path = os.path.join(project_root, "config.xlsx")
            if os.path.exists(xlsx_path):
                config_path = xlsx_path
            
        if not os.path.exists(config_path):
            return {"success": False, "error": "config file not found"}
            
        if config_path.endswith('.json'):
            with open(config_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            df = pd.DataFrame(json_data).astype(str)
        else:
            df = pd.read_excel(config_path, sheet_name=0, dtype=str)
            
        cities = {}
        for index, row in df.iterrows():
            city = str(row.get('城市', '')).strip()
            station = str(row.get('团队名称', '')).strip()
            if city and city.lower() != 'nan':
                if city not in cities:
                    cities[city] = []
                if station and station.lower() != 'nan' and station not in cities[city]:
                    cities[city].append(station)
                    
        return {"success": True, "data": {"cities": cities}}
    except Exception as e:
        return {"success": False, "error": str(e)}

class UpdateCitiesRequest(BaseModel):
    mapping: dict

@app.post("/api/update_config_cities")
def update_config_cities(req: UpdateCitiesRequest):
    try:
        import sys
        import openpyxl
        import json
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            project_root = os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() in ['dist', 'build'] else exe_dir
        else:
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_file_dir) if os.path.basename(current_file_dir) == 'backend' else current_file_dir
            
        config_file = os.path.join(project_root, "data/config.json")
        if not os.path.exists(config_file):
            config_file = os.path.join(project_root, "config.json")
        if not os.path.exists(config_file):
            config_file = os.path.join(project_root, "data/config.xlsx")
        if not os.path.exists(config_file):
            config_file = os.path.join(project_root, "config.xlsx")
            
        if not os.path.exists(config_file):
            return {"success": False, "error": "配置文件不存在"}
            
        if config_file.endswith(".json"):
            with open(config_file, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = []
            
            # Merge with mapping
            for team, city in req.mapping.items():
                if not team or not city:
                    continue
                found = False
                for row in data:
                    if str(row.get("团队名称", "")).strip() == str(team).strip():
                        row["城市"] = str(city).strip()
                        found = True
                        break
                if not found:
                    new_row = {
                        "城市": str(city).strip(),
                        "团队名称": str(team).strip(),
                        "团队ID": ""
                    }
                    if len(data) > 0:
                        # Copy headers from first row and fill with 0
                        first_row = data[0]
                        for k in first_row.keys():
                            if k not in ["城市", "团队名称", "团队ID"]:
                                new_row[k] = 0
                    data.append(new_row)
                    
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {"success": True}
        else:
            wb = openpyxl.load_workbook(config_file)
            ws = wb.worksheets[0]
            
            col_team = 1
            col_city = 2
            for col in range(1, ws.max_column + 1):
                val = str(ws.cell(row=1, column=col).value or "").strip()
                if val == "团队名称" or val == "团队":
                    col_team = col
                elif val == "城市":
                    col_city = col
                    
            start_row = ws.max_row + 1
            for team, city in req.mapping.items():
                if not team or not city:
                    continue
                ws.cell(row=start_row, column=col_team, value=str(team).strip())
                ws.cell(row=start_row, column=col_city, value=str(city).strip())
                start_row += 1
                
            wb.save(config_file)
            return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/open/config")
def open_config(req: FileRequest):
    # 处理逻辑：配置数据的读取与保存，用于状态持久化
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        project_root = os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() in ['dist', 'build'] else exe_dir
    else:
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_file_dir) if os.path.basename(current_file_dir) == 'backend' else current_file_dir
        
    config_file = os.path.join(project_root, "data/config.json")
    if not os.path.exists(config_file):
        config_file = os.path.join(project_root, "config.json")
    if not os.path.exists(config_file):
        config_file = os.path.join(project_root, "data/config.xlsx")
    if not os.path.exists(config_file):
        config_file = os.path.join(project_root, "config.xlsx")

    if os.path.exists(config_file):
        try:
            import platform
            if platform.system() == 'Windows':
                os.startfile(config_file)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', config_file])
            else:
                subprocess.run(['xdg-open', config_file])
            return {"success": True, "msg": f"正在打开: {config_file}", "exists": True}
        except Exception as e:
            return {"success": False, "msg": str(e), "exists": True}
    else:
        return {"success": False, "msg": "未找到配置文件", "exists": False}

@app.post("/api/resume_task")
async def resume_task(req: Request):
    # 处理逻辑：resume_task 的主要执行逻辑
    data = await req.json()
    uid = data.get("uuid")
    action = data.get("action", False)
    
    import sys
    # Try importing tasks if not already
    import tasks
    global_events = getattr(sys.modules['tasks'], 'GLOBAL_RESUME_EVENTS', {})
    
    if uid in global_events:
        global_events[uid]['result'] = action
        global_events[uid]['event'].set()
        return {"success": True}
    return {"success": False, "error": "Task wait event not found or expired."}

@app.post("/api/open/explorer")
def open_explorer(req: FileRequest):
    # 处理逻辑：open_explorer 的主要执行逻辑
    path = req.path
    # 打印非乱码日志
    print(f"INFO:     唤起本地资源管理器 -> {path}")
    if os.path.exists(path):
        if os.path.isfile(path):
            path = os.path.dirname(path)
        try:
            import platform
            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
            return {"success": True, "error": ""}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {"success": False, "error": "目录不存在"}

@app.post("/api/files/tree")
def list_files_tree(req: FileRequest):
    path = req.path
    if path:
        applet_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.abspath(os.path.join(applet_dir, path))
    if not path or not os.path.exists(path):
        return {"tree": []}
    
    if os.path.isfile(path):
        path = os.path.dirname(path)

    def build_tree(current_path, depth=0):
        if depth > 4:  # limit depth to prevent massive payloads
            return []
        items = []
        try:
            for f in os.listdir(current_path):
                if not LegacyDownloadBoundary(None).allowed_path(os.path.join(current_path, f)):
                    continue
                if f.startswith("~") or f.startswith("."):
                    continue
                f_path = os.path.join(current_path, f)
                is_dir = os.path.isdir(f_path)
                if is_dir:
                    items.append({
                        "name": f,
                        "path": f_path,
                        "is_dir": True,
                        "children": build_tree(f_path, depth + 1)
                    })
                else:
                    items.append({
                        "name": f,
                        "path": f_path,
                        "is_dir": False,
                        "size": os.path.getsize(f_path)
                    })
            items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        except Exception:
            pass
        return items

    return {"tree": build_tree(path)}

@app.post("/api/files")
def list_files(req: FileRequest, request: Request):
    # 处理逻辑：处理文件或目录的选择交互及路径解析
    path = req.path
    wid = request.headers.get("x-workspace-id")
    if not path or not os.path.exists(path):
        return {"files": []}
    
    # 手动打印一次清晰的日志
    print(f"INFO:     正在获取系统文件列表 -> {path}")
    
    if os.path.isfile(path):
        path = os.path.dirname(path)

    try:
        items = []
        for f in os.listdir(path):
            if not LegacyDownloadBoundary(None).allowed_path(os.path.join(path, f)):
                continue
            if not f.startswith("~") and not f.startswith("."):
                f_path = os.path.join(path, f)
                is_dir = os.path.isdir(f_path)
                items.append({
                    "name": f,
                    "path": f_path,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else os.path.getsize(f_path)
                })
        # 优先排列目录，然后按字母顺序排列
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return {"files": items}
    except Exception as e:
        return {"files": []}

@app.get("/api/system/stats")
def get_system_stats():
    # 处理逻辑：获取并返回所需的系统状态或计算数据
    if psutil is None:
        return {"success": False, "error": "psutil not installed"}
    try:
        cpu = psutil.cpu_percent(interval=None) 
        mem = psutil.virtual_memory()
        
        process = psutil.Process()
        proc_cpu = process.cpu_percent(interval=0.1)
        proc_mem = process.memory_info().rss / (1024 * 1024) # MB
        
        return {
            "success": True,
            "sysCpu": cpu,
            "sysMemRatio": mem.percent,
            "procCpu": proc_cpu,
            "procMem": round(proc_mem, 2)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/run")
async def run_calculation(config: ConfigRequest, request: Request):
    """
    接收来自前端的运算指令
    """
    wid = request.headers.get("x-workspace-id")
    if config.action in ('download_rider_sources', 'download_shangyi_employees'):
        from fengshen_auth_routes import local_owner
        wid = local_owner(request)
    if wid and config.sourcePath and wid not in config.sourcePath:
       # For security
       pass 

    async def event_generator():
        # 处理逻辑：event_generator 的主要执行逻辑
        try:
            import tasks

            if config.action == 'download_rider_sources':
                from rider_sources import run_rider_sources
                async for event in run_rider_sources(config, wid):
                    yield event
                return

            elif config.action == 'download_shangyi_employees':
                from shangyi_sources import run_shangyi_sources
                async for event in run_shangyi_sources(config, wid):
                    yield event
                return

            elif config.action == 'remove_problem_orders':
                async for event in tasks.run_remove_problem_orders_gen(config.sourcePath, config.targetPath):
                    yield event
                return
                
            elif config.action == 'raise_price':
                async for event in tasks.run_raise_price_gen(config.sourcePath, config.targetPath):
                    yield event
                return

            elif config.action == 'summary_parttime':
                async for event in tasks.run_summary_parttime_gen(config.sourcePath, config.city):
                    yield event
                return

            else:
                if config.payrollSourceMode not in ("manual", "fengshen", "xiaoxiang"):
                    raise ValueError("未知兼职数据来源")
                from payroll_inputs import run_payroll
                async for event in run_payroll(config, request):
                    yield event
                return
        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'msg': f'致命内部错误: {str(e)}', 'level': 'ERROR'})}\n\n"
            message = '任务已结束，详情见执行日志' if config.action=='core' and config.payrollSourceMode=='fengshen' else str(e)
            yield f"data: {json.dumps({'type': 'finish', 'status': 'error', 'result_msg': message})}\n\n"

    from auth_preflight import ensure_ready
    if config.action == 'download_rider_sources':
        required = {'fengshen'}
    elif config.action == 'download_shangyi_employees':
        required = {'baize'}
    elif config.action in ('remove_problem_orders', 'raise_price', 'summary_parttime'):
        required = set()
    else:
        # 手传资料（manual/xiaoxiang）不需要平台登录，仅自动采集模式设闸门。
        required = {'fengshen', 'lanorange', 'baize'} if config.payrollSourceMode == 'fengshen' else set()
    if required:
        await asyncio.to_thread(ensure_ready, required)
    from workbench import detached_events
    return StreamingResponse(detached_events(event_generator()), media_type="text/event-stream")

@app.post("/api/action_file")
async def action_file(request: Request):
    # 处理逻辑：处理文件或目录的选择交互及路径解析
    data = await request.json()
    action = data.get("action")
    path = data.get("path")
    import shutil
    try:
        if action == "delete":
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"success": True}
        elif action == "create_dir":
            os.makedirs(path, exist_ok=True)
            return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Unknown action"}

from fastapi.responses import FileResponse

def get_project_root():
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() in ['dist', 'build'] else exe_dir
    else:
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(current_file_dir) if os.path.basename(current_file_dir) == 'backend' else current_file_dir

@app.get("/api/templates/list")
async def list_templates():
    from template_library import listing
    return await asyncio.to_thread(listing, get_project_root())


@app.get("/api/download/template")
async def download_template(file: str = ""):
    from template_library import template_path, inspect_template, TemplateError
    try:
        target = template_path(get_project_root(), file)
        await asyncio.to_thread(inspect_template, target)
    except TemplateError as error:
        raise HTTPException(error.status, str(error)) from None
    return FileResponse(target, filename=file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/download/config")
async def download_config():
    import sys
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        project_root = os.path.dirname(exe_dir) if os.path.basename(exe_dir).lower() in ['dist', 'build'] else exe_dir
    else:
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_file_dir) if os.path.basename(current_file_dir) == 'backend' else current_file_dir

    config_path = os.path.abspath(os.path.join(project_root, "data", "config.xlsx"))
    if not os.path.exists(config_path):
        json_path = os.path.abspath(os.path.join(project_root, "data", "config.json"))
        if not os.path.exists(json_path):
            json_path = os.path.abspath(os.path.join(project_root, "config.json"))
        if os.path.exists(json_path):
            try:
                import json, pandas as pd
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                df.to_excel(config_path, index=False)
            except Exception as e:
                print("Failed to convert json to config.xlsx:", e)

    if not os.path.exists(config_path):
        return {"success": False, "error": "Config file not found"}
    return FileResponse(config_path, filename="config.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

