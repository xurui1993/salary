# ==========================================
# 核心数据处理计算引擎
# 本文件主要用于：
# 1. 解析与清洗各平台骑手原始打卡、配送、违规报表
# 2. 基于动态配置和团队规则进行复杂的薪资计算
# 3. 计算配送费、服务奖惩、各类扣款、兼职账单明细等
# 4. 生成最终计算好的Excel合并报表
# ==========================================
import zipfile
from workbook_policy import install_zip_policy
install_zip_policy()

import copy
import re
import uuid
# /backend/processor.py
import os
import glob
import time
import random
import pandas as pd
import numpy as np
import openpyxl
from datetime import datetime

# 小象超市「站点关键字匹配」映射表
# 日维度单量所属站点(完整名) -> 价格档案站点名称(短名)
# 来源：用户提供的附件《新建 XLSX 工作表.xlsx》Sheet1（13 条）
# 用途：价格档案取价主键 {日期}_{站点}_{身份证/ID/姓名} 在「精准匹配」未命中时，
#       将日维度站点名翻译为价格档案站点名再做一次回退匹配。原有精准匹配逻辑保持不变。
XIAOXIANG_STATION_KEYWORD_MAP = {
    "小象超市-大亚湾站-HZ1004": "大亚湾站",
    "小象超市-东步站-SZ0304": "东步站",
    "小象超市-鸿业站-SZ0263": "鸿业站",
    "小象超市-江北站-HZ1014": "江北站",
    "小象超市-金平站-ST0003": "金平站",
    "小象超市-金山湖站-HZ1005": "惠州金山湖站",
    "小象超市-桔塘站-SZ0237": "桔塘站",
    "小象超市-康正站-SZ0170": "康正站",
    "小象超市-马安站-HZ1010": "马安站",
    "小象超市-荣盛站-CZ4002": "荣盛站",
    "小象超市-水口站-HZ1009": "水口站",
    "小象超市-塘尾站-SZ0109": "塘尾站",
    "小象超市-云梯站-CZ4001": "云梯站",
    "小象超市-仲恺站-HZ1015": "仲恺站",
}

def safe_read_excel(io, **kwargs):
    # 处理逻辑：safe_read_excel 的主要执行逻辑
    try:
        return pd.read_excel(io, engine="calamine", **kwargs)
    except:
        return pd.read_excel(io, **kwargs)

def safe_parse_date(s):
    # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
    if not isinstance(s, pd.Series):
        s = pd.Series(s)
    s_numeric = pd.to_numeric(s, errors='coerce')
    is_excel_date = s_numeric.notna() & (s_numeric > 30000) & (s_numeric < 60000)
    res = pd.Series(index=s.index, dtype='datetime64[ns]')
    if is_excel_date.any():
        res.loc[is_excel_date] = pd.to_datetime(s_numeric[is_excel_date], origin='1899-12-30', unit='D')
    normal_dates = ~is_excel_date
    if normal_dates.any():
        res.loc[normal_dates] = pd.to_datetime(s[normal_dates], errors='coerce')
    return res

def _norm_daily_key(date_v, rid_v, site_v):
    # 日维度单量防重拦截主键归一：日期→YYYY/MM/DD；骑手ID 去浮点 .0；站点去空格
    try:
        _p = pd.to_datetime(str(date_v).strip(), errors='coerce')
        d = _p.strftime('%Y/%m/%d') if pd.notna(_p) else str(date_v).strip()
    except Exception:
        d = str(date_v).strip()
    rid = str(rid_v).replace('.0', '').strip()
    site = str(site_v).strip()
    return (d, rid, site)

def extract_past_records(out_folder):
    # 处理逻辑：extract_past_records 的主要执行逻辑
    past_attendance_dict = {}
    past_attendance_notes = {}
    past_month_fee_deducted = {}
    try:
        import os, re
        import pandas as pd
        if os.path.exists(out_folder):
            for f in os.listdir(out_folder):
                if f.endswith(('.xls', '.xlsx')) and not f.startswith("~") and "兼职" in f:
                    m = re.search(r'\d{1,2}\.\d{1,2}-\d{1,2}\.\d{1,2}', f)
                    date_str = m.group(0) if m else os.path.splitext(f)[0]
                    p_df = None
                    for sheet_name in ["保险费", "安全基金"]:
                        try:
                            p_df = pd.read_excel(os.path.join(out_folder, f), sheet_name=sheet_name, dtype=str)
                            break
                        except:
                            continue
                    if p_df is None:
                        continue
                    p_id_col = next((c for c in p_df.columns if "骑手ID" in c), None)
                    p_days_col = next((c for c in p_df.columns if "出勤天" in c or "本期出勤" in c), None)
                    p_fee_col = next((c for c in p_df.columns if "月费" in c), None)

                    if p_id_col and p_days_col:
                        for _, prow in p_df.iterrows():
                            pid = str(prow[p_id_col]).replace('.0', '').strip()
                            pdays = prow[p_days_col]
                            if pid and pdays and str(pdays).replace('.','',1).isdigit():
                                d = int(float(pdays))
                                if d > 0:
                                    past_attendance_dict[pid] = past_attendance_dict.get(pid, 0) + d
                                    if pid not in past_attendance_notes:
                                        past_attendance_notes[pid] = []
                                    past_attendance_notes[pid].append(f"{date_str}出勤{d}天")

                    if p_id_col and p_fee_col:
                        for _, prow in p_df.iterrows():
                            pid = str(prow[p_id_col]).replace('.0', '').strip()
                            pfee = prow[p_fee_col]
                            if pd.notna(pfee) and str(pfee).strip():
                                try:
                                    if abs(float(pfee)) > 0:
                                        past_month_fee_deducted[pid] = True
                                except:
                                    pass
    except Exception as e:
        pass
    return past_attendance_dict, past_attendance_notes, past_month_fee_deducted

def _auto_fit_columns(ws, min_width=8, max_width=60, padding=2):
    """根据单元格内容自动调整列宽（中文/全角按 2 个字符宽度估算）。"""
    from openpyxl.utils import get_column_letter
    col_widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            val = str(cell.value)
            width = sum(2 if ord(ch) > 127 else 1 for ch in val) + padding
            col = cell.column
            col_widths[col] = max(col_widths.get(col, min_width), min(max_width, width))
    for col, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width

def process_rider_data(city, selected_option, source_folder, base_path, log_callback, progress_callback,
    # 处理逻辑：对原始数据进行逐行解析、清洗、转换与规则应用
                       finish_callback, theme, enable_interceptor=False, enable_cross_station_merge=False, prompt_callback=None, **kwargs):
    from payroll_business import is_xiaoxiang_source
    if not is_xiaoxiang_source(source_folder, kwargs.get('template_file')):
        from fengshen_processor import process_rider_data as process_fengshen
        return process_fengshen(city, selected_option, source_folder, base_path,
            log_callback, progress_callback, finish_callback, theme,
            enable_interceptor=enable_interceptor, enable_cross_station_merge=enable_cross_station_merge,
            prompt_callback=prompt_callback, **kwargs)
    def log(msg, level="INFO"):
        # 处理逻辑：日志输出及前端进度条回调事件生成
        prefix = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERRO]", "SYSTEM": "[SYS ]", "SUCCESS": "[ OK ]"}.get(
            level, "[INFO]")
        log_callback(f"{prefix} {msg}\n", level)

    global_df_delivery = None

    # 扣款项列名白名单（兼容普通城市「安全基金」与小象城市「保险费」及新增费用列）
    DEDUCTION_COLS = ["安全基金", "保险费", "使用费", "循环物资使用费", "附加险", "招聘来源", "非蜂卡", "月费"]

    # 小象超市「保险费」表：展示列 → 配置表(config.json)中的扣款项源列
    # 一个配置列对应一个展示列：保险费←安全基金、循环物资使用费←非蜂卡、附加险←月费
    XIAOXIANG_FEE_DISPLAY_MAP = {
        "保险费": "安全基金",
        "循环物资使用费": "非蜂卡",
        "附加险": "月费",
    }

    def find_wb_col(columns, default_idx=None):
        # 处理逻辑：find_wb_col 的主要执行逻辑
        for c in columns:
            if str(c).strip() in ["运单号", "运单id", "运单ID", "单号", "包裹单号", "运单"]: return c
        for c in columns:
            c_str = str(c).strip()
            if "状态" not in c_str and any(kw in c_str for kw in ["运单", "单号"]): return c
        for c in columns:
            c_str = str(c).strip()
            if "状态" not in c_str and "订单" in c_str: return c
        if default_idx is not None and default_idx < len(columns): return columns[default_idx]
        return None

    def clean_wb_str(val):
        # 处理逻辑：数据规范化清洗，去除空值及格式错误的数据记录
        if pd.isna(val) or val is None or str(val).strip().lower() == 'nan':
            return ""
        s = str(val).strip().lstrip("'")
        if s.endswith('.0'):
            s = s[:-2]
        return s

    def to_numeric_if_possible(val_str):
        # 处理逻辑：to_numeric_if_possible 的主要执行逻辑
        if not val_str:
            return val_str
        try:
            f = float(val_str)
            if f.is_integer():
                return int(f)
            return f
        except ValueError:
            return val_str

    def _norm_date(val):
        # 处理逻辑：数据规范化清洗，去除空值及格式错误的数据记录
        if pd.isna(val) or val is None: return ""
        
        # Add parsing for 4xxxx numeric dates commonly found in Excel via parse_date logic
        try:
            num_val = float(val)
            if 30000 < num_val < 60000:
                dt = pd.to_datetime(num_val, origin='1899-12-30', unit='D')
                return dt.strftime('%Y-%m-%d')
        except:
            pass
            
        if isinstance(val, pd.Timestamp) or type(val).__name__ == 'datetime':
            return val.strftime('%Y-%m-%d')
            
        s = str(val).strip().split(' ')[0].replace('/', '-')
        # pad single digits
        parts = s.split('-')
        if len(parts) == 3:
            s = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        
        import re
        
        match1 = re.match(r'^(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})日?$', s)
        if match1:
            return f"{match1.group(1)}-{int(match1.group(2)):02d}-{int(match1.group(3)):02d}"
            
        match2 = re.match(r'^(\d{1,2})[-/月\.](\d{1,2})日?$', s)
        if match2:
            year = datetime.now().year
            return f"{year}-{int(match2.group(1)):02d}-{int(match2.group(2)):02d}"
            
        return s

    def get_id_name(row_series):
        # 处理逻辑：获取并返回所需的系统状态或计算数据
        r_id, r_name = "", ""
        for c in row_series.index:
            c_str = str(c)
            c_lower = c_str.lower()
            if ('id' in c_lower or '编号' in c_lower) and not any(
                    x in c_lower for x in ['运单', '订单', '站', '团队', '门店', '网点', '商户']):
                r_id = str(row_series[c])
            if c_str in ['骑手姓名', '配送员姓名', '姓名', '员工姓名', '骑手名称'] or \
                    ('姓名' in c_str and '站' not in c_str) or \
                    ('名称' in c_str and '骑手' in c_str):
                r_name = str(row_series[c])
        return r_id.replace('.0', '').strip(), r_name.replace('.0', '').strip()

    stats_info = {
        "riders": 0, "orders": 0, "penalty_orders": 0, "problem_orders": 0, "elapsed_time": 0.0, "out_folder": ""
    }

    try:
        city = str(city).strip()
        start_time = time.time()
        progress_callback(0.02, "正在初始化数据分析引擎...")
        log(f">>> {random.choice(theme['msg_start'])}", "SYSTEM")

        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
        from openpyxl.utils.dataframe import dataframe_to_rows
        from openpyxl.utils import get_column_letter

        log(f">>> {random.choice(theme['msg_awake'])}", "SYSTEM")
        progress_callback(0.05, "正在执行权限审计与环境检查...")

        keywords = ["欺诈单", "问题单", "违规", "配送费", "骑手支付绑定", "兼职价格档案", "价格档案", "骑手账单"]
        ar = ["是否剔除", "剔除原因", "扣款金额"]

        dict1 = {
            "配送费": [5, 0, 13], "问题单": [3, 1, 2, 9, 10, 11], "违规扣款": [5, 0, 13, 17, 18, 19]
        }
        
        valid_riders_dates = set()
        dictp_fraud = set()
        dict2_late = set()
        dict2_timeout = set()
        dict2_t10 = set()
        price_mapping_idcard = {}
        price_mapping_id = {}
        price_mapping_name = {}

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 尝试从 base_path 中提取 workspace_id
        import re
        import json
        wid_match = re.search(r'(u_[A-Za-z0-9]+)', str(base_path))
        if wid_match:
            wid = wid_match.group(1)
            mapping_file = os.path.join(project_root, f".aegis_mapping_{wid}.json")
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file, 'r', encoding='utf-8') as mf:
                        custom_map = json.load(mf)
                        for key, indices_list in custom_map.items():
                            if key in dict1:
                                # Ensure it's a list combining with defaults
                                custom_indices = dict1[key].copy()
                                for idx, val in enumerate(indices_list):
                                    if val is not None and str(val).isdigit():
                                        custom_indices[idx] = int(val)
                                dict1[key] = custom_indices
                    log(f"-> 🎯 成功合并从参数配置中心读取的动态字段映射字典")
                except Exception as e:
                    log(f"读取映射配置中心时出错: {e}", "WARN")

        # 从 source_folder 中读取 template 关键字模板文件的申请名单
        template_wb_path = None
        specific_template = kwargs.get('template_file')
        if specific_template:
            # Check if it's absolute or relative to source_folder
            if os.path.isabs(specific_template):
                if os.path.exists(specific_template):
                    template_wb_path = specific_template
            else:
                p = os.path.join(source_folder, specific_template)
                if os.path.exists(p):
                    template_wb_path = p

        # === 业务城市识别：以目录内是否存在「小象-template」文件为准 ===
        # 若扫描到文件名同时含「小象」与「template」的文件，则视为小象超市目录；
        # 否则按普通城市处理。不再依赖前端所选城市，避免配送费带日期后缀时误判。
        is_xiaoxiang = False
        for _root, _dirs, _files in os.walk(source_folder):
            for _file in _files:
                if ("小象" in _file) and ("template" in _file.lower()) and _file.lower().endswith(('.xls', '.xlsx')) and not _file.startswith('~$') and not _file.startswith('.'):
                    is_xiaoxiang = True
                    break
            if is_xiaoxiang:
                break

        if is_xiaoxiang:
            log(">>> 识别为【小象超市】目录（依据模板文件名含「小象」）", "SYSTEM")
        else:
            log(">>> 识别为【普通城市】目录", "SYSTEM")

        if not template_wb_path or not os.path.exists(template_wb_path):
            for root, dirs, files in os.walk(source_folder):
                for file in files:
                    if ("template" in file.lower()) and (file.endswith(".xlsx") or file.endswith(".xls")) and not file.startswith('~$') and not file.startswith('.'):
                        # 小象模式：优先加载「小象-template」模板，跳过普通 template
                        if is_xiaoxiang and ("小象" not in file):
                            continue
                        template_wb_path = os.path.join(root, file)
                        break
                if template_wb_path:
                    break
                


        if not template_wb_path or not os.path.exists(template_wb_path): 
            for fname in ["system_templates", "data"]:
                dir_path = os.path.join(os.getcwd(), fname)
                if os.path.exists(dir_path):
                    for f in sorted(os.listdir(dir_path)):
                        if (f.endswith('.xlsx') or f.endswith('.xls')) and not f.startswith('~$') and not f.startswith('.'):
                            template_wb_path = os.path.join(dir_path, f)
                            break
                if template_wb_path:
                    break
                    
        if not template_wb_path or not os.path.exists(template_wb_path): 
            raise FileNotFoundError(f"致命：未在数据目录中找到包含 template 关键字的模板文件，请将模板与数据目录一同上传。搜索根目录: {source_folder}")

        # === 动态获取业务城市 (移入后续流程进行) ===
        frontend_city = city

        def _safe_str_apply(x):
            # 处理逻辑：_safe_str_apply 的主要执行逻辑
            if pd.isna(x): return ""
            if isinstance(x, (int, float)):
                return format(x, ".0f") if float(x) == int(x) else str(x)
            return str(x).strip(' ="\t\r\n')

        def _to_num_if_pure(v):
            # 仅当单元格为「纯数值文本」时转为真正的数值(int/float)，其余保持原样：
            #   '7'   -> 7    (int)
            #   '0.03'-> 0.03 (float)
            #   '7+2' -> '7+2'(文本，非纯数字，不强行转换，避免误清空)
            #   ''/空 -> None (真正空白)
            if pd.isna(v):
                return None
            if isinstance(v, (int, float)):
                return v
            if isinstance(v, str):
                s = v.strip()
                if s == "":
                    return None
                try:
                    f = float(s)
                except ValueError:
                    return v
                return int(f) if f == int(f) else f
            return v

        def _parse_salary_cell(v):
            # 解析配送所得表「薪资方案」：'6.5+0.5' -> (合计值7, 雇佣兵单价0.5)；无'+' -> (原值, 0)
            if v is None:
                return (None, 0)
            if isinstance(v, (int, float)):
                return (v, 0)
            if isinstance(v, str):
                s = v.strip()
                if '+' in s:
                    try:
                        _a_s, _b_s = s.split('+', 1)
                        _a = float(_a_s)
                        _b = float(_b_s)
                        _total = _a + _b
                        _total = int(_total) if _total == int(_total) else _total
                        _b = int(_b) if _b == int(_b) else _b
                        return (_total, _b)
                    except ValueError:
                        return (v, 0)
                return (v, 0)
            return (v, 0)

        # 配送所得表读取兜底：优先「配送所得表」，兼容旧模板命名为「配送所得」
        # 仅做读取解析，不修改任何文件/工作表名称。
        def _resolve_delivery_sheet(wb):
            for _n in ("配送所得表", "配送所得"):
                if _n in wb.sheetnames:
                    return wb[_n]
            return None

        # 配送所得表表头定位：兼容「第2行详细表头(含月份前缀如'8月薪资方案')」与「第3行纯列名(如'薪资方案')」两种情况。
        # 在 row1~row3 中找首个表头单元格，满足 任一关键字 为其子串（strip 后）。返回列号(1-based)或 None。
        def _find_header_col(ws, keywords):
            for _r in range(1, 4):
                for _c in range(1, ws.max_column + 1):
                    _v = ws.cell(row=_r, column=_c).value
                    if _v is None:
                        continue
                    _s = str(_v).strip()
                    if any(_k in _s for _k in keywords):
                        return _c
            return None

        df_apply = pd.read_excel(template_wb_path, sheet_name="申请名单", dtype=object)
        for c in df_apply.columns:
            df_apply[c] = df_apply[c].apply(_safe_str_apply)

        # 小象申请名单：「薪资方案」「服务费率」列中的文本型数值转为真正的数值类型。
        # 仅转换可解析的纯数值文本（如 '7'、'0.03'），含 '7+2' 等非纯数字文本的行保持原样，避免误清空。
        for _cn in ("薪资方案", "服务费率"):
            if _cn in df_apply.columns:
                df_apply[_cn] = df_apply[_cn].apply(_to_num_if_pure)

        # 小象申请名单：出勤扣款/客诉/虚假点送达/违规补时/保温包/督导扣罚/刷单/完成单量
        # 装载后保留为数值类型（2026-10-21 用户要求）。此前 _safe_str_apply 会把数值全部转成文本，
        # 导致写入输出工作簿的单元格为文本型数字，配送所得表 SUMIFS 扣款公式无法求和、扣款全部丢失。
        # 转换规则与「薪资方案」「服务费率」一致：纯数值文本转 int/float，空值置空，非数值文本原样保留。
        # 仅小象目录生效，普通城市申请名单装载行为不变。
        if is_xiaoxiang:
            _xx_num_cols = ("出勤扣款", "客诉", "虚假点送达", "违规补时", "保温包", "督导扣罚", "刷单", "完成单量")
            for _cn in _xx_num_cols:
                if _cn in df_apply.columns:
                    df_apply[_cn] = df_apply[_cn].apply(_to_num_if_pure)
                    log(f"-> 🎯 小象申请名单「{_cn}」列已按数值类型装载", "INFO")

        deduction_rules = kwargs.get("deductionRules", [])
        flat_rules = []
        if deduction_rules:
            if isinstance(deduction_rules, list) and len(deduction_rules) > 0 and 'sites' in deduction_rules[0]:
                for city_data in deduction_rules:
                    for site_data in city_data.get('sites', []):
                        flat_rule = {
                            "城市": city_data.get('name', ''),
                            "团队名称": site_data.get('name', ''),
                            "团队ID": site_data.get('siteId', '')
                        }
                        for item in site_data.get('deductionItems', []):
                            item_name = item.get('name')
                            flat_rule[item_name] = item.get('amount', 0)
                            if item.get('maxDays') is not None:
                                flat_rule[f"{item_name}_maxDays"] = item.get('maxDays')
                            flat_rule[f"{item_name}_isKw"] = item.get('isKeywordBased', False)
                        flat_rules.append(flat_rule)
            else:
                flat_rules = deduction_rules
                
        if not flat_rules:
            # Fallback to local config file if UI config is empty
            config_wb_path = None
            
            # 1. 优先检查用户上传的 source_folder 里的配置文件
            for root, dirs, files in os.walk(source_folder):
                for file in files:
                    if ("config" in file.lower() or "配置" in file) and not file.startswith("~$"):
                        config_wb_path = os.path.join(root, file)
                        break
                if config_wb_path: break
            


            # 2. 如果没有，再检查应用根目录的默认模板
            if not config_wb_path:
                for fname in ["data/config.json", "../data/config.json", "data/config.xlsx", "../data/config.xlsx"]:
                    p = os.path.join(os.getcwd(), fname)
                    p2 = os.path.join(os.getcwd(), "..", fname)
                    if os.path.exists(p):
                        config_wb_path = p
                        break
                    elif os.path.exists(p2):
                        config_wb_path = p2
                        break
                
            if config_wb_path:
                try:
                    if config_wb_path.endswith('.json'):
                        import json
                        with open(config_wb_path, 'r', encoding='utf-8') as f:
                            json_data = json.load(f)
                        df_config = pd.DataFrame(json_data)
                    else:
                        df_config = pd.read_excel(config_wb_path, sheet_name=0, dtype=object)
                    for c in df_config.columns: df_config[c] = df_config[c].apply(_safe_str_apply)
                    
                    for _, row in df_config.iterrows():
                        team_name = str(row.get("团队名称", "")).strip()
                        if not team_name: continue
                        flat_rule = {
                            "城市": str(row.get("城市", "")).strip(),
                            "团队名称": team_name,
                            "团队ID": str(row.get("团队ID", "")).strip()
                        }
                        for c in df_config.columns:
                            c_name = str(c).strip()
                            if c_name not in ["城市", "团队名称", "团队ID"]:
                                val = str(row.get(c, "")).strip()
                                try:
                                    flat_rule[c_name] = float(val) if val != "" else 0
                                except:
                                    flat_rule[c_name] = 0
                                
                                # 对于常见的按次（问题单）扣款列，必须标记为 isKw = True
                                kw_cols = ["投诉", "差评", "违规虚假", "物流责", "不准时单", "超时", "T10", "提前点送达"]
                                flat_rule[f"{c_name}_isKw"] = True if any(kw in c_name for kw in kw_cols) else False
                        flat_rules.append(flat_rule)
                    log(f"-> 🎯 成功从外部配置文件 [{os.path.basename(config_wb_path)}] 解析扣款规则！", "INFO")
                except Exception as e:
                    log(f"尝试解析外部配置文件失败: {e}", "WARN")

        if flat_rules:
            df_rules = pd.DataFrame(flat_rules)
            df_rules = df_rules.rename(columns={
                "teamName": "团队名称",
                "teamId": "团队ID",
                "safeFund": "安全基金",
                "nonBeeCard": "非蜂卡",
                "monthFee": "月费"
            })
            log(f"-> 🎯 成功解析扣款项配置，提取了 {len(df_rules.columns) - 3} 个动态扣款项目")
        else:
            df_rules = pd.DataFrame(columns=["城市", "团队名称", "团队ID", "安全基金", "非蜂卡", "月费"])

        team_mapping = {}
        try:
            df_team = df_rules.copy()
            for c in df_team.columns: df_team[c] = df_team[c].apply(_safe_str_apply)
            if not df_team.empty:
                name_col = "团队名称"
                id_col = "团队ID"
                team_mapping = dict(zip(df_team[name_col].fillna("").astype(str).str.strip(),
                                        df_team[id_col].fillna("").astype(str).str.strip()))
            log(f"权限校验列表已加载，识别 {len(team_mapping)} 个有效处理组。")
        except Exception as e:
            log(f"环境依赖 [config] 解析失败 (目标索引将置空): {e}", "WARN")

        def get_col_idx(df, keywords, default_idx):
            # 处理逻辑：获取并返回所需的系统状态或计算数据
            for i, col in enumerate(df.columns):
                if any(kw in str(col) for kw in keywords):
                    return i
            if len(df.columns) > default_idx:
                return default_idx
            return 0
            
        team_idx = get_col_idx(df_apply, ["团队名称", "团队"], 0)
        rider_id_idx = get_col_idx(df_apply, ["骑手ID", "ID", "id"], 1)
        rider_name_idx = get_col_idx(df_apply, ["骑手姓名", "姓名"], 2)
        start_date_idx = get_col_idx(df_apply, ["开始日期", "开始时间", "开始"], 3)
        end_date_idx = get_col_idx(df_apply, ["结束日期", "结束时间", "结束"], 4)

        col3 = df_apply.columns[start_date_idx]
        col4 = df_apply.columns[end_date_idx]
        
        col3_data = safe_parse_date(df_apply[col3])
        col4_data = safe_parse_date(df_apply[col4])
        
        # 从配置表中稳健地读取结算类型
        settlement_type = None
        settlement_col = next((c for c in df_apply.columns if '结算' in str(c)), None)
        if settlement_col:
            first_valid = df_apply[settlement_col].dropna().astype(str).str.strip()
            first_valid = first_valid[(first_valid.str.lower() != 'nan') & (first_valid != '') & (first_valid != 'None')]
            if not first_valid.empty:
                settlement_type = first_valid.iloc[0]
        
        if not settlement_type:
            for r_idx in range(min(10, len(df_apply))):
                row_vals = df_apply.iloc[r_idx].fillna('').astype(str).str.strip()
                col_match = next((idx for idx, v in enumerate(row_vals) if '结算' in v), None)
                if col_match is not None:
                    for scan_idx in range(r_idx + 1, len(df_apply)):
                        val = str(df_apply.iloc[scan_idx, col_match]).strip()
                        if val and val.lower() not in ['nan', 'none']:
                            settlement_type = val
                            break
                    break
        
        if settlement_type:
            selected_option = settlement_type
            if selected_option.endswith('.0'):
                selected_option = selected_option[:-2]
            log(f"-> 🎯 成功从申请名单中提取周期类型(首项): {selected_option}", "INFO")

        # 从配置表中稳健地读取业务城市
        extracted_city = None
        city_col = next((c for c in df_apply.columns if '城市' in str(c)), None)
        if city_col:
            first_valid = df_apply[city_col].dropna().astype(str).str.strip()
            first_valid = first_valid[(first_valid.str.lower() != 'nan') & (first_valid != '') & (first_valid != 'none')]
            if not first_valid.empty:
                extracted_city = first_valid.iloc[0]
        
        if not extracted_city:
            for r_idx in range(min(10, len(df_apply))):
                row_vals = df_apply.iloc[r_idx].fillna('').astype(str).str.strip()
                col_match = next((idx for idx, v in enumerate(row_vals) if '城市' in v), None)
                if col_match is not None:
                    for scan_idx in range(r_idx + 1, len(df_apply)):
                        val = str(df_apply.iloc[scan_idx, col_match]).strip()
                        if val and val.lower() not in ['nan', 'none']:
                            extracted_city = val
                            break
                    break
        
        if extracted_city:
            city = extracted_city
            log(f"-> 🎯 成功从申请名单中提取业务城市: {city}", "INFO")

        # 从配置表中稳健地读取防重拦截
        extracted_interceptor = None
        interceptor_col = next((c for c in df_apply.columns if '防重拦截' in str(c) or '拦截' in str(c)), None)
        if interceptor_col:
            first_valid = df_apply[interceptor_col].dropna().astype(str).str.strip()
            first_valid = first_valid[(first_valid.str.lower() != 'nan') & (first_valid != '') & (first_valid != 'none')]
            if not first_valid.empty:
                extracted_interceptor = first_valid.iloc[0]
        
        if not extracted_interceptor:
            for r_idx in range(min(10, len(df_apply))):
                row_vals = df_apply.iloc[r_idx].fillna('').astype(str).str.strip()
                col_match = next((idx for idx, v in enumerate(row_vals) if '防重拦截' in v or '拦截' in v), None)
                if col_match is not None:
                    for scan_idx in range(r_idx + 1, len(df_apply)):
                        val = str(df_apply.iloc[scan_idx, col_match]).strip()
                        if val and val.lower() not in ['nan', 'none']:
                            extracted_interceptor = val
                            break
                    break
                    
        if extracted_interceptor:
            enable_interceptor = (extracted_interceptor == "是")
            log(f"-> 🎯 成功从申请名单中提取防重拦截配置: {'开启' if enable_interceptor else '关闭'}", "INFO")

        # 从配置表中稳健地读取跨站合并
        extracted_cross_merge = None
        cross_merge_col = next((c for c in df_apply.columns if '跨站合并' in str(c) or '合并' in str(c)), None)
        if cross_merge_col:
            first_valid = df_apply[cross_merge_col].dropna().astype(str).str.strip()
            first_valid = first_valid[(first_valid.str.lower() != 'nan') & (first_valid != '') & (first_valid != 'none')]
            if not first_valid.empty:
                extracted_cross_merge = first_valid.iloc[0]
        
        if not extracted_cross_merge:
            for r_idx in range(min(10, len(df_apply))):
                row_vals = df_apply.iloc[r_idx].fillna('').astype(str).str.strip()
                col_match = next((idx for idx, v in enumerate(row_vals) if '跨站合并' in v or '合并' in v), None)
                if col_match is not None:
                    for scan_idx in range(r_idx + 1, len(df_apply)):
                        val = str(df_apply.iloc[scan_idx, col_match]).strip()
                        if val and val.lower() not in ['nan', 'none']:
                            extracted_cross_merge = val
                            break
                    break
                    
        if extracted_cross_merge:
            enable_cross_station_merge = (extracted_cross_merge == "是")
            log(f"-> 🎯 成功从申请名单中提取跨站合并配置: {'开启' if enable_cross_station_merge else '关闭'}", "INFO")

        log(f"目标节点: [{city}], 处理模式: [{selected_option}]")
        
        # 兼容文本形式的日期和Excel导出的纯数值形式（4xxxx）日期
        # 使用assign重新赋值避免pandas inplace assignment int64的报错
        df_apply = df_apply.assign(**{col3: col3_data, col4: col4_data})
        
        first_date = df_apply[col3].min()
        last_date = df_apply[col4].max()

        for row in df_apply.itertuples(index=False):
            try:
                team_name = str(row[team_idx]).strip()
                rider_id = str(row[rider_id_idx]).replace('.0', '').strip()
                rider_name = str(row[rider_name_idx]).strip()
                date_range = pd.date_range(row[start_date_idx], row[end_date_idx])
                for d in date_range: valid_riders_dates.add(f"{rider_id}|{d.strftime('%Y-%m-%d')}")
            except:
                continue

        apply_riders_count = len(df_apply.iloc[:, rider_id_idx].dropna().unique())
        log(f"历史快照读取完毕，缓冲池包含 {apply_riders_count} 个活动实体（拦截日志记录 {len(valid_riders_dates)} 次）！")
        progress_callback(0.15, "历史快照读取完毕，缓冲池已建立...")

        # 小象：构建申请名单骑手→团队/姓名映射，用于跨站骑手按申请站点结算
        # 规则：申请哪个站点就按那个站点匹配，不回退到配送单站点判定
        # 注意：同一骑手可同时申请多个站点（申请名单多行），故同时构建「单值 map」与「多值 set」
        apply_team_map = {}
        apply_team_set = {}
        apply_rider_name_map = {}
        if is_xiaoxiang:
            for row in df_apply.itertuples(index=False):
                try:
                    _team = str(row[team_idx]).strip()
                    _rid = str(row[rider_id_idx]).replace('.0', '').strip()
                    _rname = str(row[rider_name_idx]).strip()
                    if _rid and _rid.lower() not in ('nan', 'none', ''):
                        apply_team_map[_rid] = _team
                        _team_norm = _team.replace(' ', '').replace('\u3000', '').replace('\xa0', '')
                        apply_team_set.setdefault(_rid, set()).add(_team_norm)
                        apply_rider_name_map[_rid] = _rname
                except:
                    continue
            _multi_site = sum(1 for s in apply_team_set.values() if len(s) > 1)
            log(f"-> 🎯 小象申请名单映射构建完成: {len(apply_team_map)} 个骑手→团队映射（多站点骑手 {_multi_site} 人）", "INFO")

        # 申请名单「身份证号」列 → 骑手ID 映射（用户要求：小象蓝橙单价的身份证由此提取，骑手ID 对应匹配）
        apply_rider_idcard_map = {}
        _apply_idcard_idx = get_col_idx(df_apply, ["身份证号", "身份证", "证件号码", "证件"], -1)
        if _apply_idcard_idx >= 0:
            for row in df_apply.itertuples(index=False):
                try:
                    _rid = str(row[rider_id_idx]).replace('.0', '').strip()
                    _idc = str(row[_apply_idcard_idx]).strip().upper()
                    if _rid and _idc and _rid.lower() not in ('nan', 'none', ''):
                        apply_rider_idcard_map[_rid] = _idc
                except:
                    continue
            log(f"-> 🎯 申请名单身份证映射构建完成: {len(apply_rider_idcard_map)} 个骑手→身份证映射", "INFO")
        else:
            log("-> ⚠️ 申请名单未检测到「身份证号」列，小象身份证将回退至骑手支付绑定/明细来源", "WARN")
        
        batch_id = kwargs.get('batch_id')
        task_name = kwargs.get('task_name')
        output_type = "兼职薪资"
        output_base = os.path.abspath(kwargs.get("output_root") or os.path.join(project_root, "outputs", output_type))
            
        os.makedirs(output_base, exist_ok=True)
        out_folder = os.path.join(output_base, f"{last_date.year}年", f"{last_date.month}月", city)
        stats_info["out_folder"] = out_folder
        os.makedirs(out_folder, exist_ok=True)

        existing_waybills = {"配送单": {}, "违规索赔": {}, "问题单": {}}
        # 小象「日维度单量」防重缓冲：键 (规范化日期, 骑手ID, 所属站点) -> (源文件, 日期, 骑手ID, 骑手姓名, 所属站点, 配送完成单量)
        existing_daily = {}

        def _is_delivery_sheet(name):
            """识别「配送单」相关的所有子表：主表、旧式「配送单_2」分表、新式「配送单800000」带行数分表。"""
            if name == "配送单":
                return True
            if name.startswith("配送单_"):
                return True
            if name.startswith("配送单") and name[3:].isdigit():
                return True
            return False

        if enable_interceptor:
            log(">>> 扫描本地缓冲，开启数据防重拦截策略...", "SYSTEM")
            if os.path.exists(out_folder):
                for file in glob.glob(os.path.join(out_folder, "*.xlsx")):
                    if "(重复)" in os.path.basename(file) or "~$" in os.path.basename(file): continue
                    try:
                        try:
                            xls = pd.ExcelFile(file, engine="calamine")
                        except:
                            xls = pd.ExcelFile(file, engine="openpyxl")
                        file_basename = os.path.basename(file)
                        for sht in xls.sheet_names:
                            # 支持「配送单」分表场景：配送单 / 配送单_2 / 配送单_3 ...
                            is_delivery = _is_delivery_sheet(sht)
                            if not (is_delivery or sht in ("违规索赔", "问题单", "日维度单量")):
                                continue
                            df_sht = xls.parse(sht, dtype=object)
                            for c in df_sht.columns: df_sht[c] = df_sht[c].apply(_safe_str_apply)
                            headers = list(df_sht.columns)
                            # 分表统一归并到「配送单」去重字典，避免重跑时漏拦重复运单
                            type_key = "配送单" if is_delivery else sht
                            if sht == "问题单":
                                wb_idx_name = find_wb_col(headers, 2)
                                type_idx_name = headers[0] if len(headers) > 0 else None
                                if wb_idx_name and type_idx_name:
                                    types = df_sht[type_idx_name]
                                    wbs = df_sht[wb_idx_name]
                                    for t, w in zip(types, wbs):
                                        if w and "nan" not in str(w).lower(): existing_waybills[type_key][f"{t}_{w}"] = file_basename
                            elif sht == "日维度单量":
                                # 小象专属：构建 (日期,骑手ID,所属站点) 防重键，拦截跨期重复计入的日维度单量
                                _d_idx = next((i for i, h in enumerate(headers) if str(h).strip() == "日期"), None)
                                _r_idx = next((i for i, h in enumerate(headers) if str(h).strip().lower() == "骑手id"), None)
                                _s_idx = next((i for i, h in enumerate(headers) if str(h).strip() in ("所属站点", "站点名称", "团队名称")), None)
                                if _d_idx is not None and _r_idx is not None and _s_idx is not None:
                                    _n_idx = next((i for i, h in enumerate(headers) if str(h).strip() == "骑手姓名"), None)
                                    _q_idx = next((i for i, h in enumerate(headers) if str(h).strip() == "配送完成单量"), None) \
                                             or next((i for i, h in enumerate(headers) if str(h).strip() == "推配送单量"), None)
                                    for _row in df_sht.itertuples(index=False):
                                        _k = _norm_daily_key(_row[_d_idx], _row[_r_idx], _row[_s_idx])
                                        if _k in existing_daily:
                                            continue
                                        _name = _row[_n_idx] if _n_idx is not None else ""
                                        _qty = _row[_q_idx] if _q_idx is not None else ""
                                        existing_daily[_k] = (file_basename, _k[0], _k[1], _name, _k[2], _qty)
                            else:
                                fallback_idx = 10 if sht == "违规索赔" else None
                                wb_idx_name = find_wb_col(headers, fallback_idx)
                                if wb_idx_name:
                                    wbs = df_sht[wb_idx_name]
                                    for w in wbs:
                                        if w and "nan" not in str(w).lower(): existing_waybills[type_key][w] = file_basename
                        xls.close()
                    except Exception as e:
                        log(f"重载历史缓冲区引发严重错误: {os.path.basename(file)} - {str(e)}", "WARN")

        intercept_records = []
        daily_intercept_records = []  # 日维度单量防重拦截明细：(拦截文件,日期,骑手ID,骑手姓名,所属站点,配送完成单量)

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 使用上传目录中找到的 template.xlsx 模板文件
        template_path = template_wb_path
        
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"致命：模板文件找不到了。请确保包含 template 关键字的模板文件存在。")

        log(f"开启多线程数据分发引擎: {os.path.basename(template_path)}", "SYSTEM")
        wb1 = openpyxl.load_workbook(template_path)

        # ============ 小象：商配送骑手订单明细 合并 + 文本数值转数字 + 匹配申请名单 ============
        if is_xiaoxiang:
            log("-> 🔄 开始处理【骑手订单明细】文件（含『商配送』骑手订单明细 或 仅含『骑手订单明细』关键字均命中）...", "INFO")
            _xx_order_files = []
            for _root, _dirs, _files in os.walk(source_folder):
                for _file in _files:
                    if ("骑手订单明细" in _file) and \
                       _file.lower().endswith(('.xlsx', '.xls')) and not _file.startswith('~$'):
                        _xx_order_files.append(os.path.join(_root, _file))
            if _xx_order_files:
                _xx_target_cols = ['合作商名称', '站点名称', '站点id', '业务日期', '骑手id',
                                   '骑手名称', '合作商id', '配送方', '三方结算公司id', '城市id', '城市名称', '配送单量']
                _xx_num_cols = ['站点id', '骑手id', '合作商id', '三方结算公司id', '城市id', '配送单量']
                _xx_frames = []
                for _p in _xx_order_files:
                    try:
                        _df = pd.read_excel(_p, sheet_name=0, dtype=object)
                    except Exception as _e:
                        log(f"   ⚠ 读取商配送文件失败 {os.path.basename(_p)}: {_e}", "WARN")
                        continue
                    _miss = [c for c in _xx_target_cols if c not in _df.columns]
                    if _miss:
                        log(f"   ⚠ 文件 {os.path.basename(_p)} 缺少列: {_miss}，已跳过", "WARN")
                        continue
                    _df = _df[_xx_target_cols].copy()
                    _xx_frames.append(_df)
                    log(f"   ✓ 读取 {os.path.basename(_p)}: {len(_df)} 行", "INFO")
                if _xx_frames:
                    _xx_merged = pd.concat(_xx_frames, ignore_index=True)
                    log(f"   📊 合并完成: 共 {len(_xx_merged)} 行 (来自 {len(_xx_frames)} 个文件)", "INFO")
                    # 文本数值转数字（站点id/骑手id/合作商id/三方结算公司id/城市id/配送单量）
                    for _c in _xx_num_cols:
                        _xx_merged[_c] = pd.to_numeric(_xx_merged[_c], errors='coerce')
                    # 业务日期文本解析为日期
                    # 修复：源文件「业务日期」存在两种格式混用（YYYY-MM-DD 与 YYYY/M/D），
                    # pd.to_datetime 会按首个样本推断单一格式，导致另一种格式被 coerce 为 NaT，
                    # 进而在申请名单日期窗口匹配中整段被丢弃。先统一把 '/' 替换为 '-' 再做解析。
                    _xx_merged['业务日期'] = pd.to_datetime(
                        _xx_merged['业务日期'].astype(str).str.replace('/', '-', regex=False),
                        errors='coerce')
                    # 匹配申请名单：申请名单(骑手ID+日期区间) ↔ 骑手订单明细(骑手id+业务日期)
                    _xx_matched = _xx_merged
                    _xx_apply = df_apply.dropna(how='all') if (df_apply is not None and len(df_apply) > 0) else pd.DataFrame()
                    if len(_xx_apply) > 0:
                        _xx_apply = _xx_apply.copy()
                        _xx_apply['骑手ID'] = _xx_apply['骑手ID'].astype(str).str.strip()
                        _xx_apply['开始日期'] = pd.to_datetime(_xx_apply['开始日期'], errors='coerce')
                        _xx_apply['结束日期'] = pd.to_datetime(_xx_apply['结束日期'], errors='coerce')
                        _apply_keys = set(_xx_apply['骑手ID'])
                        _xx_merged['_rid'] = _xx_merged['骑手id'].astype(str).str.strip()
                        # 修复：与上文保持一致，先统一 '/' -> '-' 再解析，避免 YYYY/M/D 被 coerce 为 NaT
                        _xx_merged['_bd'] = pd.to_datetime(
                            _xx_merged['业务日期'].astype(str).str.replace('/', '-', regex=False),
                            errors='coerce')

                        def _in_apply(r):
                            _rid = r['_rid']
                            if _rid not in _apply_keys:
                                return False
                            _b = r['_bd']
                            _sub = _xx_apply[_xx_apply['骑手ID'] == _rid]
                            for _, _ar in _sub.iterrows():
                                if pd.notna(_ar['开始日期']) and pd.notna(_ar['结束日期']) and _ar['开始日期'] <= _b <= _ar['结束日期']:
                                    return True
                            return False

                        _m = _xx_merged.apply(_in_apply, axis=1)
                        log(f"   🔗 申请名单匹配: {int(_m.sum())}/{len(_xx_merged)} 行命中", "INFO")
                        _xx_matched = _xx_merged[_m].copy()
                        # 站点过滤（与日维度单量口径一致，用户要求 2026-10-15）：
                        # 仅保留「站点名称 ∈ 申请名单中该骑手的站点集合」的行，剔除跨站支援数据（支持多站点）
                        if apply_team_set:
                            _xx_rid = _xx_matched['骑手id'].astype(str).str.replace('.0', '', regex=False).str.strip()
                            _xx_site = _xx_matched['站点名称'].astype(str).str.replace(' ', '', regex=False).str.replace('\u3000', '', regex=False).str.replace('\xa0', '', regex=False).str.strip()
                            _xx_keep = pd.Series([
                                (_r in apply_team_set) and (_s in apply_team_set[_r])
                                for _r, _s in zip(_xx_rid, _xx_site)
                            ], index=_xx_matched.index)
                            _xx_n_drop = int((~_xx_keep).sum())
                            if _xx_n_drop:
                                _xx_matched = _xx_matched[_xx_keep].copy()
                                log(f"   🎯 骑手订单明细站点过滤：剔除与申请名单站点不符的跨站行 {_xx_n_drop} 条，剩余 {len(_xx_matched)} 行", "INFO")
                    else:
                        log("   ⚠ 申请名单为空，按严格匹配规则：骑手订单明细不写入任何数据（仅保留表头）", "WARN")
                        _xx_matched = _xx_merged.iloc[0:0]
                    # 写入骑手订单明细表（清空旧数据行，保留模板表头）
                    _xx_out = _xx_matched[_xx_target_cols].copy()
                    _xx_out['业务日期'] = _xx_out['业务日期'].dt.date
                    _ws_xx = wb1['骑手订单明细']
                    _center = Alignment(horizontal='center', vertical='center')
                    if _ws_xx.max_row > 1:
                        _ws_xx.delete_rows(2, _ws_xx.max_row - 1)
                    for _i, (_ri, _row) in enumerate(_xx_out.iterrows(), start=2):
                        for _ci, _col in enumerate(_xx_target_cols, start=1):
                            _v = _row[_col]
                            if pd.isna(_v):
                                _v = None
                            _cell = _ws_xx.cell(row=_i, column=_ci, value=_v)
                            _cell.alignment = _center
                    # 表头（第1行）同步居中对齐
                    for _hc in range(1, len(_xx_target_cols) + 1):
                        _ws_xx.cell(row=1, column=_hc).alignment = _center
                    _auto_fit_columns(_ws_xx)
                    log(f"   ✅ 骑手订单明细写入完成: {len(_xx_out)} 行（单元格已居中对齐、列宽已自适应）", "INFO")
                else:
                    log("   ⚠ 未从商配送文件中解析到有效数据行", "WARN")
            else:
                log("   ℹ 上传目录未找到含【骑手订单明细】关键字文件，跳过该步骤", "INFO")

        # 小象：配送单表可能被手动改名为「日维度单量」，统一解析实际表名（兼容两种命名）
        delivery_sheet_name = "日维度单量" if (is_xiaoxiang and "日维度单量" in wb1.sheetnames) else "配送单"

        def fast_recreate_sheet(wb, sheet_name):
            # 处理逻辑：fast_recreate_sheet 的主要执行逻辑
            if sheet_name in wb.sheetnames:
                idx = wb.sheetnames.index(sheet_name)
                old_ws = wb[sheet_name]
                tab_color = old_ws.sheet_properties.tabColor
                del wb[sheet_name]
                new_ws = wb.create_sheet(title=sheet_name, index=idx)
                if tab_color:
                    try:
                        new_ws.sheet_properties.tabColor = copy.copy(tab_color)
                    except:
                        pass
                return new_ws
            return wb.create_sheet(title=sheet_name)

        # Excel 单工作表行数上限为 1,048,576 行（含表头）。
        # 「配送单」子表存放策略（按 账单时间 的「日(号)」级联拆分，子表名 = 基础名 + 该表数据行数，不含表头）：
        #   1) 总量 ≤ 1,048,576 行：直接写入单表「配送单」，表名不变。
        #   2) 总量 > 1,048,576 行：按日号切分
        #        a) 先分 2 段：1-15号 一段，15号后 一段；
        #        b) 若「1-15号」或「15号后」任一段仍 > 1,048,576 行，升级为 3 段：1-10号 / 11-20号 / 20后 各一段。
        #   注：未解析出日号的行归入「后段/20后」的补集，保证不丢数据。
        EXCEL_ROW_LIMIT = 1_048_576

        def _day_series_from(df, date_col):
            """从日期列提取「日(号)」的 pandas Series（解析失败为 NaN）。"""
            src = df[date_col] if (date_col and date_col in df.columns) else df.iloc[:, 0]
            return safe_parse_date(src).dt.day

        def split_write_sheet(wb, base_name, df, log_cb=None, date_col=None):
            """写入配送单；按 账单时间(日号) 级联拆分为多张「基础名+数据行数」子表。"""
            headers = list(df.columns)
            n = len(df)
            df_obj = df.astype(object)
            df_obj[pd.isna(df_obj)] = None
            rows = df_obj.values.tolist()

            if n == 0:
                ws = fast_recreate_sheet(wb, base_name)
                ws.append(headers)
                _auto_fit_columns(ws)
                if log_cb:
                    log_cb(f"-> 📋 子表【{base_name}】无数据，仅写入表头", "INFO")
                return

            # 1) 未超上限：单表，表名不变
            if n <= EXCEL_ROW_LIMIT:
                ws = fast_recreate_sheet(wb, base_name)
                ws.append(headers)
                for r in rows:
                    ws.append(r)
                _auto_fit_columns(ws)
                if log_cb:
                    log_cb(f"-> 📋 子表【{base_name}】写入 {n} 行", "INFO")
                return

            # 2) 超上限：按 账单时间 日号 级联拆分
            day_series = _day_series_from(df, date_col)

            mask_1_15 = day_series.between(1, 15, inclusive="both")
            mask_after15 = ~mask_1_15
            n_1_15 = int(mask_1_15.sum())
            n_after15 = int(mask_after15.sum())

            if n_1_15 > EXCEL_ROW_LIMIT or n_after15 > EXCEL_ROW_LIMIT:
                # 升级为 3 段：1-10号 / 11-20号 / 20后
                buckets = [
                    ("1-10号", day_series.between(1, 10, inclusive="both").tolist()),
                    ("11-20号", day_series.between(11, 20, inclusive="both").tolist()),
                    ("20后", (~day_series.between(1, 20, inclusive="both")).tolist()),
                ]
            else:
                # 2 段：1-15号 / 15号后
                buckets = [
                    ("1-15号", mask_1_15.tolist()),
                    ("15号后", mask_after15.tolist()),
                ]

            # 拆分模式下删除模板自带占位 base_name 表，避免与带行数后缀子表并存
            if base_name in wb.sheetnames:
                del wb[base_name]

            pages = 0
            for label, mask_list in buckets:
                sub = [rows[i] for i, m in enumerate(mask_list) if m]
                cnt = len(sub)
                if cnt == 0:
                    continue  # 该日期区间无数据，跳过空表，避免产生「配送单0」之类空表
                sheet_name = f"{base_name}{cnt}"   # 如 配送单800000（不含表头）
                ws = fast_recreate_sheet(wb, sheet_name)
                ws.append(headers)
                for r in sub:
                    ws.append(r)
                _auto_fit_columns(ws)
                pages += 1
                if log_cb:
                    log_cb(
                        f"-> 📋 子表【{sheet_name}】({label}) 写入 {cnt} 行"
                        f"（{base_name} 共 {n} 行，已按日期分 {pages} 页）",
                        "INFO",
                    )

        # import copy
        ws_apply = fast_recreate_sheet(wb1, "申请名单")

        df_apply_out = df_apply.copy()
        settlement_periods = []
        for i in range(len(df_apply_out)):
            dt_start = df_apply_out.iloc[i, start_date_idx]
            dt_end = df_apply_out.iloc[i, end_date_idx]
            if not pd.isna(dt_start) and not pd.isna(dt_end) and hasattr(dt_start, 'month') and hasattr(dt_end, 'month'):
                settlement_periods.append(f"{dt_start.month}.{dt_start.day}-{dt_end.month}.{dt_end.day}")
            else:
                settlement_periods.append("")
                
        df_apply_out['结算周期'] = settlement_periods
        col3_name = df_apply_out.columns[start_date_idx]
        col4_name = df_apply_out.columns[end_date_idx]
        df_apply_out.drop(columns=[col3_name, col4_name], inplace=True)
        
        # 将骑手ID转换为常规数值类型
        if len(df_apply_out.columns) > rider_id_idx:
            rider_id_col = df_apply_out.columns[rider_id_idx]
            try:
                df_apply_out[rider_id_col] = pd.to_numeric(df_apply_out[rider_id_col], errors='coerce')
            except Exception:
                pass

        headers_apply = list(df_apply_out.columns)
        ws_apply.append(headers_apply)
        df_apply_out = df_apply_out.astype(object)
        df_apply_out[pd.isna(df_apply_out)] = None
        for row_data in df_apply_out.values.tolist():
            ws_apply.append(row_data)
        _auto_fit_columns(ws_apply)

        progress_callback(0.25, "目标区域模板匹配与预处理完毕...")

        log(">>> 正在检索目标区域的二进制数据源...", "SYSTEM")
        files_to_process = []
        
        if is_xiaoxiang:
            date_files = []
            scanned_files = []
            # 支持：YYYY-MM-DD / YYYY/MM/DD / YYYYMMDD，允许前后缀
            # 8 位纯日期（如 20260801）必须独立成段（前后非数字），避免把带 13 位时间戳的
            # 文件名（如 价格档案_1786697869223.xlsx）尾部 8 位数字误判为日期文件。
            date_re = re.compile(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?<!\d)\d{8}(?!\d))(?=\D|$)')
            for root, dirs, files in os.walk(source_folder):
                for file_name in files:
                    if file_name.lower().startswith('~$') or file_name.lower().startswith('.'):
                        continue
                    if not file_name.lower().endswith(('.xls', '.xlsx', '.csv')):
                        continue
                    scanned_files.append(file_name)
                    # 小象骑手支付绑定文件（merchantFreelancer）：独立识别并加入处理队列
                    if "merchantfreelancer" in file_name.lower():
                        full_path = os.path.join(root, file_name)
                        if (full_path, "merchantFreelancer") not in files_to_process:
                            files_to_process.append((full_path, "merchantFreelancer"))
                        continue
                    # 文件名中包含日期片段（允许前后缀）即视为小象配送单日期文件，
                    # 如 配送费_2026-06-01.xlsx / 2026-06-01_配送单.xlsx / 20260601.xlsx
                    if date_re.search(file_name):
                        date_files.append(os.path.join(root, file_name))
                    else:
                        for kw in keywords:
                            if kw in file_name and kw != '配送费':
                                full_path = os.path.join(root, file_name)
                                if (full_path, kw) not in files_to_process:
                                    files_to_process.append((full_path, kw))
                                break

            if date_files:
                log(f">>> 发现 {len(date_files)} 个小象超市配送单日期文件，准备提取并合并...", "SYSTEM")

                def _is_blank_cell(v):
                    if v is None:
                        return True
                    try:
                        if pd.isna(v):
                            return True
                    except (TypeError, ValueError):
                        pass
                    return str(v).strip() == ""

                def _parse_file_date(fname):
                    base = os.path.splitext(os.path.basename(fname))[0]
                    m = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{8})(?=\D|$)', base)
                    date_str = m.group(1) if m else base
                    try:
                        return pd.to_datetime(date_str).strftime('%Y/%m/%d')
                    except Exception:
                        return date_str

                def _merge_title_rows(title_df):
                    n = title_df.shape[1]
                    r0 = title_df.iloc[0]
                    r1 = title_df.iloc[1] if title_df.shape[0] > 1 else None
                    merged = []
                    for i in range(n):
                        v0 = r0.iloc[i] if i < len(r0) else None
                        v1 = r1.iloc[i] if (r1 is not None and i < len(r1)) else None
                        merged.append(v1 if not _is_blank_cell(v1) else v0)
                    return merged

                def _col_label(merged, i):
                    v = merged[i] if i < len(merged) else None
                    return str(v).strip() if not _is_blank_cell(v) else f"列{i+2}"

                combined_frames = []
                first_header = None
                for df_file in date_files:
                    file_basename = os.path.splitext(os.path.basename(df_file))[0]
                    try:
                        if df_file.lower().endswith('.csv'):
                            raw = pd.read_csv(df_file, header=None, encoding='gbk', dtype=str, low_memory=False)
                        else:
                            raw = pd.read_excel(df_file, header=None, dtype=object)
                        if raw.shape[0] < 3:
                            log(f"小象组合文件 {os.path.basename(df_file)} 行数不足（需含 2 行标题 + 数据行），跳过", "WARN")
                            continue
                        merged_header = _merge_title_rows(raw.iloc[:2])
                        formatted_date = _parse_file_date(df_file)
                        data = raw.iloc[2:].copy()
                        data.columns = [f"_c{i}" for i in range(data.shape[1])]
                        for c in data.columns:
                            data[c] = data[c].apply(_safe_str_apply)
                        if first_header is None:
                            first_header = ["日期"] + [_col_label(merged_header, i) for i in range(len(merged_header))]
                        records = []
                        for _, r in data.iterrows():
                            rec = {"日期": formatted_date}
                            for j in range(1, len(first_header)):
                                src_idx = j - 1
                                rec[first_header[j]] = (r.iloc[src_idx] if src_idx < data.shape[1] else None)
                            records.append(rec)
                        combined_frames.append(pd.DataFrame(records, columns=first_header))
                    except KeyError as e:
                        log(f"读取小象组合文件 {os.path.basename(df_file)} 缺失关键列 (KeyError): {e}，跳过当前文件并继续处理队列下一个文件", "WARN")
                    except ValueError as e:
                        log(f"读取小象组合文件 {os.path.basename(df_file)} 数据格式/类型转换失败 (ValueError): {e}，跳过当前文件并继续处理队列下一个文件", "WARN")
                    except Exception as e:
                        log(f"读取小象组合文件 {os.path.basename(df_file)} 失败: {e}，跳过当前文件并继续处理队列下一个文件", "WARN")

                if combined_frames:
                    combined_df = pd.concat(combined_frames, ignore_index=True)
                    temp_combine_path = os.path.join(source_folder, "配送费_小象合并.xlsx")
                    combined_df.to_excel(temp_combine_path, index=False)
                    files_to_process.append((temp_combine_path, "配送费"))
                    log(f"小象超市配送单合并完成（按日期 + 前两行标题合并），生成缓冲文件 {os.path.basename(temp_combine_path)}，共 {len(combined_df)} 行", "INFO")
            else:
                examples = scanned_files[:5]
                log(
                    "未找到符合日期命名规则的小象配送单文件"
                    "（期望如 2026-06-01.xlsx、配送费_2026-06-01.xlsx、20260601_配送单.xlsx）。"
                    f"扫描到的文件示例：{', '.join(examples) if examples else '无'}",
                    "WARN",
                )
                for root, dirs, files in os.walk(source_folder):
                    for file_name in files:
                        if file_name.lower().startswith('~$') or file_name.lower().startswith('.'):
                            continue
                        if "merchantfreelancer" in file_name.lower():
                            full_path = os.path.join(root, file_name)
                            if (full_path, "merchantFreelancer") not in files_to_process:
                                files_to_process.append((full_path, "merchantFreelancer"))
                            continue
                        for kw in keywords:
                            if kw in file_name and file_name.lower().endswith(('.xls', '.xlsx', '.csv')):
                                full_path = os.path.join(root, file_name)
                                if (full_path, kw) not in files_to_process:
                                    files_to_process.append((full_path, kw))
                                break
        else:
            # 普通城市：按关键字扫描全部 Excel/CSV 文件
            for root, dirs, files in os.walk(source_folder):
                for file_name in files:
                    if file_name.lower().startswith('~$') or file_name.lower().startswith('.'):
                        continue
                    for kw in keywords:
                        if kw in file_name and file_name.lower().endswith(('.xls', '.xlsx', '.csv')):
                            full_path = os.path.join(root, file_name)
                            if (full_path, kw) not in files_to_process:
                                files_to_process.append((full_path, kw))
                            break
        total_files = len(files_to_process)
        log(f"目录索引构建完成，发现 {total_files} 个有效数据片段")
        
        t_before_files = time.time()
        
        has_delivery_fee = any('配送费' in kw_tuple[1] for kw_tuple in files_to_process)
        if not has_delivery_fee:
            if is_xiaoxiang:
                raise FileNotFoundError(
                    "当前数据目录下未检测到符合日期命名规则的小象配送单文件"
                    "（期望如 2026-06-01.xlsx、配送费_2026-06-01.xlsx、20260601_配送单.xlsx）。"
                    "请确保上传目录中包含日期命名的配送单明细表后再执行核算。"
                )
            raise FileNotFoundError("当前数据目录下未检测到包含【配送费】的数据表！请确保目录中含有配送单表后再执行核算。")
            
        if total_files == 0: log(random.choice(theme['msg_empty']), "WARN")

        processed_count = 0
        current_progress = 0.25
        progress_step = 0.6 / total_files if total_files > 0 else 0

        sort_priority = {
            "兼职价格档案": 0,
            "价格档案": 0,
            "欺诈单": 1,
            "问题单": 2,
            "违规": 3,
            "违规扣款": 3,
            "骑手支付绑定": 4,
            "骑手账单": 4.5,
            "配送费": 5
        }
        files_to_process.sort(key=lambda x: sort_priority.get(x[1], 99))
        
        rider_wtd_deductions = {} # { rider_id: { matched_item: amount } }

        for file_path, kw in files_to_process:
            wb_name = os.path.basename(file_path)
            try:

                if file_path.lower().endswith('.csv'):
                    try:
                        df_source = pd.read_csv(file_path, encoding='gbk', dtype=str, low_memory=False)
                        if len(df_source.columns) <= 2: df_source = pd.read_csv(file_path, encoding='gbk', sep='\t',
                                                                                dtype=str)
                    except UnicodeDecodeError:
                        df_source = pd.read_csv(file_path, encoding='utf-8', dtype=str, low_memory=False)
                        if len(df_source.columns) <= 2: df_source = pd.read_csv(file_path, encoding='utf-8', sep='\t',
                                                                                dtype=str)
                else:
                    df_source = pd.read_excel(file_path, dtype=object)

                for col in df_source.columns: 
                    # fast check if column is already numeric and doesn't need string stripping
                    col_type = df_source[col].dtype
                    if not pd.api.types.is_object_dtype(col_type):
                        pass # Keep numeric as is
                    else:
                        # Use _safe_str_apply to prevent large number scientific notation and strip strings
                        df_source[col] = df_source[col].apply(_safe_str_apply)
                
                    # Fast sample string length check
                    if pd.api.types.is_object_dtype(df_source[col]):
                        sample = df_source[col].dropna()
                        sample = sample[sample != ""]
                        if not sample.empty:
                            # only check first 1000 for length to speed up
                            max_len = sample.head(1000).str.len().max()
                            if max_len >= 15:
                                continue  # Skip numeric conversion for this column to preserve ID card precision

                    try:
                        s_replaced = df_source[col].copy()
                        if pd.api.types.is_object_dtype(s_replaced):
                            s_replaced.replace("", np.nan, inplace=True)
                        s_num = pd.to_numeric(s_replaced)
                    
                        # 自动转换为数字格式，因为需要保留常规数值类型
                        # 只需校验是否为数字
                        if not s_num.isna().any() or (pd.api.types.is_object_dtype(s_replaced) and s_replaced.isna().equals(s_num.isna())):
                            df_source[col] = s_num
                    except Exception:
                        pass

                if "兼职价格档案" in wb_name or "价格档案" in wb_name:
                    try:
                        if not file_path.lower().endswith('.csv'):
                            try:
                                df_price = pd.read_excel(file_path, sheet_name="兼职价格档案明细", dtype=object)
                            except:
                                df_price = pd.read_excel(file_path, sheet_name=0, dtype=object)
                        
                            def _safe_str(x):
                                # 处理逻辑：_safe_str 的主要执行逻辑
                                if pd.isna(x): return ""
                                if isinstance(x, (int, float)):
                                    return format(x, ".0f") if float(x) == int(x) else str(x)
                                return str(x).strip(' ="\t\r\n')
                            
                            for col in df_price.columns:
                                df_price[col] = df_price[col].apply(_safe_str)
                        else:
                            df_price = df_source.copy()
                    except Exception as e:
                        log(f"缺少外部映射依赖 [{wb_name}]，尝试使用预设参数", "WARN")
                        df_price = df_source.copy()

                    date_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['日期', '账单时间', '时间']), next((i for i, c in enumerate(df_price.columns) if '日期' in str(c) or '账单时间' in str(c) or '时间' in str(c)), None))
                    station_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['站点名称', '团队名称']), next((i for i, c in enumerate(df_price.columns) if '站点名称' in str(c) or '团队名称' in str(c)), next((i for i, c in enumerate(df_price.columns) if ('团队' in str(c) or '站点' in str(c) or '营业部' in str(c)) and 'id' not in str(c).lower()), None)))
                    idcard_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['身份证', '身份证号', '证件号码', '证件']), next((i for i, c in enumerate(df_price.columns) if '身份证' in str(c)), None))
                    price_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['价格', '单价', '蓝橙单价', '蓝橙']), next((i for i, c in enumerate(df_price.columns) if '价格' in str(c) or '单价' in str(c) or '蓝橙' in str(c)), None))
                
                    # backwards compatibility
                    rider_id_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['风神骑手ID', '风神骑手id', '骑手ID', '员工ID']), next((i for i, c in enumerate(df_price.columns) if '风神骑手id' in str(c).lower() or (('id' in str(c).lower() or '编号' in str(c)) and ('骑手' in str(c) or '员工' in str(c)))), None))
                    rider_name_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['风神骑手姓名', '骑手姓名', '员工姓名', '姓名']), next((i for i, c in enumerate(df_price.columns) if '风神骑手姓名' in str(c) or (('名' in str(c) or '姓名' in str(c)) and ('骑手' in str(c) or '员工' in str(c)))), None))
                    if rider_id_idx is None: rider_id_idx = 2
                    if rider_name_idx is None: rider_name_idx = 3

                    for r in df_price.itertuples(index=False):
                        try:
                            date_val = _norm_date(str(r[date_idx])) if date_idx is not None else (_norm_date(r[1]) if len(r) > 1 else "")
                            station_val = str(r[station_idx]).replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip() if station_idx is not None else (str(r[5]).replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip() if len(r) > 5 else "")
                            price_val = str(r[price_idx]).strip() if price_idx is not None else (str(r[8]).strip() if len(r) > 8 else "")
                        
                            idcard_val = str(r[idcard_idx]).strip().upper() if idcard_idx is not None else ""
                            r_id = str(r[rider_id_idx]).replace('.0', '').strip() if rider_id_idx is not None and rider_id_idx < len(r) else ""
                            r_name = str(r[rider_name_idx]).strip() if rider_name_idx is not None and rider_name_idx < len(r) else ""

                            if not date_val or not station_val or not price_val or price_val.lower() == 'nan':
                                continue

                            if idcard_val: price_mapping_idcard[f"{date_val}_{station_val}_{idcard_val}"] = price_val
                            if r_id: price_mapping_id[f"{date_val}_{station_val}_{r_id}"] = price_val
                            if r_name: price_mapping_name[f"{date_val}_{station_val}_{r_name}"] = price_val
                        except Exception:
                            pass

                    log(f"-> 🎯 规则权重表注入成功！(新主键 {len(price_mapping_idcard)} 个，旧主键 {len(price_mapping_id)} 个)", "INFO")
                    processed_count += 1
                    current_progress += progress_step
                    msg = random.choice(theme.get('msg_empty', ["正在处理"])) if 'theme' in locals() and 'msg_empty' in theme else "正在处理"
                    progress_callback(current_progress, f"正在清洗规则与参数映射：{wb_name[:12]} ({processed_count}/{total_files})")
                    continue

                match_key = next((k for k in dict1.keys() if k in wb_name), None)
                if match_key:
                    cols = list(dict1[match_key])
                    col_names_lower = [str(c).replace('\n', '').strip().lower() for c in df_source.columns]
                
                    def _find_col(keywords, default_idx):
                        # 处理逻辑：_find_col 的主要执行逻辑
                        for kw in keywords:
                            for i, name in enumerate(col_names_lower):
                                if kw in name: return i
                        return default_idx
                    
                    cols[0] = _find_col(["骑手id", "员工编码", "骑手编号", "骑手"], cols[0])
                    cols[1] = _find_col(["业务交易时间", "账单时间", "不准时单最新罚减时间", "扣款月份", "扣款日期", "日期", "时间"], cols[1])
                    cols[2] = _find_col(["运单号", "运单id", "关联单号", "订单号", "单号"], cols[2])
                
                    if len(cols) > 3:
                        cols[3] = _find_col(["是否剔除", "剔除状态"], cols[3])
                        cols[4] = _find_col(["剔除原因"], cols[4])
                        cols[5] = _find_col(["罚减结算金额", "明细扣款金额", "扣款金额", "扣款"], cols[5])

                    rider_col, date_col, wb_col = cols[0], cols[1], cols[2]
                    max_needed_col = max(cols)
                    while len(df_source.columns) <= max_needed_col: df_source[f"Temp_Col_{len(df_source.columns)}"] = np.nan
                    waybill_col_name = df_source.columns[wb_col]
                    df_source[waybill_col_name] = df_source[waybill_col_name].astype(str).str.lstrip("'")
                
                    # Prevent Invalid value for dtype 'int64' error by casting the rider ID column to object
                    rider_col_name = df_source.columns[rider_col]
                    df_source[rider_col_name] = df_source[rider_col_name].astype(object)

                    try:
                        r_vals = df_source.iloc[:, rider_col].values
                        d_vals = df_source.iloc[:, date_col].values
                    
                        # 极速版：列表推导式
                        rider_list = [str(x).replace('.0', '').strip() for x in r_vals]
                        date_list = [_norm_date(x)[:10] for x in d_vals]
                    
                        col_names_str = [str(c).lower() for c in df_source.columns]
                        team_col_idx = next((i for i, c in enumerate(col_names_str) if "团队" in c), -1)
                        name_col_idx = next((i for i, c in enumerate(col_names_str) if "姓名" in c or ("名称" in c and "骑手" in c)), -1)

                        combined_series = pd.Series(rider_list) + "|" + pd.Series(date_list)
                        mask_valid = combined_series.isin(valid_riders_dates)
                        df_source = df_source[mask_valid].copy()
                    except Exception as e:
                        log(f"拦截点: 数据流水线捕获错误 {str(e)}", "WARN")

                    if "问题单" in wb_name:
                        col0_str = df_source.iloc[:, 0].astype(str)
                        mask_late = col0_str.str.contains("不准时", na=False)
                        late_wbs = df_source.loc[mask_late, df_source.columns[wb_col]].apply(clean_wb_str)
                        dict2_late.update(late_wbs[late_wbs != ""].tolist())

                        mask_timeout = col0_str.str.contains("超时", na=False)
                        timeout_wbs = df_source.loc[mask_timeout, df_source.columns[wb_col]].apply(clean_wb_str)
                        dict2_timeout.update(timeout_wbs[timeout_wbs != ""].tolist())

                        mask_t10 = col0_str.str.contains("T10|t10", na=False, regex=True)
                        t10_wbs = df_source.loc[mask_t10, df_source.columns[wb_col]].apply(clean_wb_str)
                        dict2_t10.update(t10_wbs[t10_wbs != ""].tolist())

                    if match_key != "配送费":
                        col_names = list(df_source.columns)
                        for i in range(3, 6): col_names[cols[i]] = ar[i - 3]
                        df_source.columns = col_names

                if "欺诈单" in wb_name:
                    # 收集多种可能的标识列（普通城市用运单id/运单号；小象为统计型数据按骑手ID匹配）
                    for _fc in ["运单id", "运单号", "骑手ID", "骑手id", "骑手编码"]:
                        if _fc in df_source.columns:
                            _vf = df_source[_fc].apply(clean_wb_str)
                            dictp_fraud.update(_vf[_vf != ""].tolist())

                elif "配送费" in wb_name:
                    ws_sht0 = wb1[delivery_sheet_name]
                    ws_sht1 = _resolve_delivery_sheet(wb1)
                    fund_sheet_name = "保险费" if is_xiaoxiang else "安全基金"
                    ws_sht2 = wb1[fund_sheet_name]
                
                    # Make column names unique to prevent pd.Series/DataFrame nested issues
                    new_cols = []
                    seen = {}
                    for c in df_source.columns:
                        c_str = str(c)
                        if c_str in seen:
                            seen[c_str] += 1
                            new_cols.append(f"{c_str}_{seen[c_str]}")
                        else:
                            seen[c_str] = 0
                            new_cols.append(c_str)
                    df_source.columns = new_cols
                
                    if '详情' in df_source.columns:
                        df_source = df_source[df_source['详情'].astype(str).str.contains('完成单', na=False)]
                
                    # 小象：配送单为「统计型数据」，字段与普通城市运单明细不同，跳过 yellow_cols 白名单过滤，保留全部原始列
                    # 基础配送费矩阵需在 yellow_cols 白名单过滤前保存完整原始列（含 基础配送费/订单标签），避免白名单过滤丢失费率列
                    df_raw_for_matrix = df_source.copy()

                    if not is_xiaoxiang:
                        yellow_cols = ['账单时间', '团队ID', '团队名称', '骑手ID', '骑手名称', '详情', '订单号', '运单号', '业务交易时间', '订单来源', '标品', '门店ID', '门店名称', '订单标签']
                        cols_to_keep = []
                        for c_name in df_source.columns:
                            c_str = str(c_name).strip()
                            if c_str in yellow_cols:
                                cols_to_keep.append(c_name)
                        df_source = df_source.loc[:, cols_to_keep].copy()
                
                    if '运单号' in df_source.columns:
                        df_source['运单号'] = df_source['运单号'].apply(clean_wb_str)

                    # 小象是配送统计数据而非运单明细，无需生成 是否欺诈单/运单状态/状态 三列
                    if not is_xiaoxiang:
                        if '账单时间' in df_source.columns:
                            dates_parsed = safe_parse_date(df_source['账单时间'])
                            is_weekend_series = dates_parsed.dt.dayofweek.isin([5, 6])
                        else:
                            is_weekend_series = pd.Series([False] * len(df_source), index=df_source.index)

                        status_series = pd.Series(
                            np.where(is_weekend_series, "完成单-周末", "完成单-工作日"),
                            index=df_source.index
                        )

                        waybill_status_series = pd.Series("完成单", index=df_source.index)

                        if '运单号' in df_source.columns:
                            wb_series = df_source['运单号']

                            # Match "不准时" (late) from problem orders
                            mask_late_match = wb_series.isin(dict2_late) & (wb_series != "")
                            waybill_status_series[mask_late_match] = "完成单-不准时"

                            # Match "T10" from problem orders
                            mask_t10_match = wb_series.isin(dict2_t10) & (wb_series != "")
                            status_series[mask_t10_match] = "完成单-T10"

                            # Match "超时" (timeout) from problem orders
                            mask_timeout_match = wb_series.isin(dict2_timeout) & (wb_series != "")
                            status_series[mask_timeout_match] = "完成单-超时"

                            df_source["是否欺诈单"] = wb_series.apply(lambda x: "是" if x in dictp_fraud else "否")
                        else:
                            df_source["是否欺诈单"] = "否"

                        if '订单标签' in df_source.columns:
                            idx_lbl = list(df_source.columns).index('订单标签')
                            df_source.insert(idx_lbl + 1, '运单状态', waybill_status_series)
                        else:
                            df_source['运单状态'] = waybill_status_series

                        df_source["状态"] = status_series

                    wb_col_name = find_wb_col(df_source.columns)
                    if wb_col_name:
                        clean_waybills = df_source[wb_col_name].apply(clean_wb_str)
                        mask_dup = clean_waybills.isin(existing_waybills["配送单"].keys())
                        df_dups = df_source[mask_dup].copy()
                        df_source = df_source[~mask_dup].copy()
                        stats_info["orders"] += len(df_source)
                        if not df_dups.empty:
                            dup_sources = {}
                            wb_col_idx = df_dups.columns.get_loc(wb_col_name)
                            rid_idx = next((i for i, c in enumerate(df_dups.columns) if "骑手" in str(c) and ("id" in str(c).lower() or "编码" in str(c))), 2)
                            rname_idx = next((i for i, c in enumerate(df_dups.columns) if "姓名" in str(c)), 3)
                            for row in df_dups.itertuples(index=False):
                                wb_val = clean_wb_str(row[wb_col_idx])
                                src_file = existing_waybills["配送单"].get(wb_val)
                                if src_file:
                                    r_id = str(row[rid_idx]).replace('.0', '').strip() if rid_idx < len(row) else ""
                                    r_name = str(row[rname_idx]).strip() if rname_idx < len(row) else ""
                                    intercept_records.append((src_file, "配送单", wb_val, r_id, r_name))
                                    dup_sources[src_file] = dup_sources.get(src_file, 0) + 1
                            for src_file, count in dup_sources.items(): log(
                                f"💥 [红牌拦截] 发现 {count} 条【配送单】重复记录！(源自历史文件: {src_file})", "ERROR")

                    for col in df_source.columns:
                        c_str_lower = str(col).lower()
                        if ("id" in c_str_lower or "编号" in c_str_lower or "运单" in c_str_lower or "订单" in c_str_lower) and ("单" in c_str_lower or "骑手" in c_str_lower or "员工" in c_str_lower):
                            continue
                        if "团队" in c_str_lower or "网点" in c_str_lower:
                            continue
                        sample = str(df_source[col].iloc[0]) if not df_source[col].empty else ""
                        if len(sample) < 15:
                            try:
                                df_source[col] = pd.to_numeric(df_source[col])
                            except Exception:
                                pass

                    # 小象：跳过 target_delivery_cols 白名单过滤，配送单展示全部字段（与普通城市运单明细展示不同）
                    if not is_xiaoxiang:
                        target_delivery_cols = ['账单时间', '团队ID', '团队名称', '骑手ID', '骑手名称', '详情', '订单号', '运单号', '业务交易时间', '订单来源', '标品', '门店ID', '门店名称', '订单标签', '运单状态', '是否欺诈单', '状态']
                        cols_final = [c for c in target_delivery_cols if c in df_source.columns]
                        df_source = df_source[cols_final].copy()

                    # 小象：按申请名单覆盖配送单中的所属站点，确保跨站骑手归到申请站点
                    # 规则：申请哪个站点就按那个站点匹配，不回退到配送单站点
                    # 修复：仅在【跨站合并】开关开启时执行覆盖；关闭时保留 daily 原始站点
                    # 背景：apply_team_map 是 骑手ID→团队名 单值映射，会把同一骑手的多站记录
                    # 强制合并到单值站点，与『取消跨站合并』的设计意图矛盾。
                    # 与 line 1704-1706「小象超市：按用户要求取消跨站合并去重」保持一致。
                    if is_xiaoxiang and apply_team_map and enable_cross_station_merge:
                        _rid_col = next((c for c in df_source.columns if str(c).strip().lower() == "骑手id"), None)
                        _site_col = next((c for c in df_source.columns if str(c).strip() in ["所属站点", "站点名称", "团队名称"]), None)
                        if _rid_col and _site_col:
                            _rid_series = df_source[_rid_col].astype(str).str.replace('.0', '', regex=False).str.strip()
                            _apply_site = _rid_series.map(apply_team_map)
                            _mask = _apply_site.notna()
                            if _mask.any():
                                df_source.loc[_mask, _site_col] = _apply_site[_mask].values
                                log(f"-> 🎯 已按申请名单覆盖 {_mask.sum()} 行配送记录的所属站点为申请团队名称", "INFO")

                    # 小象「日维度单量」防重拦截：按 (日期+骑手ID+所属站点) 与历史核算工作簿匹配，命中即拦截
                    if is_xiaoxiang and enable_interceptor and existing_daily:
                        _d_c = next((c for c in df_source.columns if str(c).strip() == "日期"), None)
                        _r_c = next((c for c in df_source.columns if str(c).strip().lower() == "骑手id"), None)
                        _s_c = next((c for c in df_source.columns if str(c).strip() in ["所属站点", "站点名称", "团队名称"]), None)
                        if _d_c and _r_c and _s_c:
                            def _key_of_row(r):
                                return _norm_daily_key(r[_d_c], r[_r_c], r[_s_c])
                            _mask_daily_dup = df_source.apply(lambda r: _key_of_row(r) in existing_daily, axis=1)
                            _df_dups_daily = df_source[_mask_daily_dup].copy()
                            df_source = df_source[~_mask_daily_dup].copy()
                            if not _df_dups_daily.empty:
                                _dsrc = {}
                                for _row in _df_dups_daily.itertuples(index=False):
                                    _k = _key_of_row(_row)
                                    _rec = existing_daily.get(_k)
                                    if _rec:
                                        daily_intercept_records.append(_rec)
                                        _dsrc[_rec[0]] = _dsrc.get(_rec[0], 0) + 1
                                for _src, _cnt in _dsrc.items():
                                    log(f"💥 [红牌拦截] 发现 {_cnt} 条【日维度单量】重复记录！(源自历史文件: {_src})", "ERROR")

                    # 小象：日维度单量严格按申请名单团队名称过滤——仅保留「所属站点 ∈ 申请名单团队名称集合」的行（用户要求 2026-10-15）
                    # 支持同一骑手申请多个站点：申请的任一站点的数据均保留；跨站（非申请站点）与名单外数据剔除，
                    # 避免脏数据进入日维度单量/蓝橙单价报备/保险费/配送所得表。
                    if is_xiaoxiang and apply_team_set:
                        _rid_col = next((c for c in df_source.columns if str(c).strip().lower() == "骑手id"), None)
                        _site_col = next((c for c in df_source.columns if str(c).strip() in ["所属站点", "站点名称", "团队名称"]), None)
                        if _rid_col and _site_col:
                            _rid_series = df_source[_rid_col].astype(str).str.replace('.0', '', regex=False).str.strip()
                            _site_series = df_source[_site_col].astype(str).str.replace(' ', '', regex=False).str.replace('\u3000', '', regex=False).str.replace('\xa0', '', regex=False).str.strip()
                            _keep = pd.Series([
                                (_r in apply_team_set) and (_s in apply_team_set[_r])
                                for _r, _s in zip(_rid_series, _site_series)
                            ], index=df_source.index)
                            _n_drop = int((~_keep).sum())
                            if _n_drop:
                                df_source = df_source[_keep].copy()
                                log(f"-> 🎯 日维度单量站点过滤：严格按申请名单团队名称匹配（支持多站点），剔除跨站及名单外行 {_n_drop} 条，剩余 {len(df_source)} 行", "INFO")

                    # 小象：日维度单量仅保留「配送完成单量 > 0」的行（用户要求 2026-10-15）
                    # 0 单量行（含无法解析为数值的行，按 0 计）不写入子表，也不参与下游核算
                    # （花名册/出勤/蓝橙报备均以本表为数据源，过滤后全链路口径一致）
                    if is_xiaoxiang:
                        _qty_col = next((c for c in df_source.columns if str(c).strip() == "配送完成单量"), None)
                        if _qty_col:
                            _qty_num = pd.to_numeric(
                                df_source[_qty_col].astype(str).str.replace(r'[^\d.\-+eE]', '', regex=True),
                                errors='coerce'
                            ).fillna(0)
                            _n_zero = int((_qty_num <= 0).sum())
                            if _n_zero > 0:
                                df_source = df_source[_qty_num > 0].copy()
                                log(f"-> 🎯 日维度单量过滤：剔除「配送完成单量<=0」行 {_n_zero} 条，剩余 {len(df_source)} 行", "INFO")

                    # 写入「配送单」子表：按 账单时间(日号) 级联拆分，子表名 = 配送单 + 数据行数(不含表头)
                    split_write_sheet(wb1, delivery_sheet_name, df_source, log_cb=log, date_col="账单时间")

                    global_df_delivery = df_source.copy()

                    # 生成/更新【基础配送费】扩展子表（矩阵透视结构：第1列为团队名称，横向为订单标签，数值为基础配送费）
                    # 小象：配送单为统计型汇总数据，无「订单标签/基础配送费」字段，跳过生成并移除模板空表
                    if is_xiaoxiang:
                        if "基础配送费" in wb1.sheetnames:
                            del wb1["基础配送费"]
                        log("小象超市无「订单标签/基础配送费」字段，跳过【基础配送费】矩阵生成并移除空表", "INFO")
                    else:
                        try:
                            # 精准匹配列名（去掉首尾空格后必须与候选名完全一致，不做模糊子串匹配，避免错配）
                            col_team_name = next((c for c in df_raw_for_matrix.columns if str(c).strip() == "团队名称"), None)
                            col_tag = next((c for c in df_raw_for_matrix.columns if str(c).strip() == "订单标签"), None)
                            col_fee = next((c for c in df_raw_for_matrix.columns if str(c).strip() == "基础配送费"), None)

                            if col_team_name and col_tag and col_fee:
                                df_sub = df_raw_for_matrix[[col_team_name, col_tag, col_fee]].dropna(subset=[col_team_name, col_tag]).copy()
                                df_sub[col_team_name] = df_sub[col_team_name].astype(str).str.strip()
                                df_sub[col_tag] = df_sub[col_tag].astype(str).str.strip()
                                df_sub = df_sub[(df_sub[col_team_name] != "") & (df_sub[col_team_name] != "nan") & (df_sub[col_team_name] != "None") & (df_sub[col_tag] != "") & (df_sub[col_tag] != "nan") & (df_sub[col_tag] != "None")]

                                df_sub[col_fee] = pd.to_numeric(df_sub[col_fee], errors="coerce")

                                if not df_sub.empty:
                                    df_pivot = pd.pivot_table(
                                        df_sub,
                                        index=col_team_name,
                                        columns=col_tag,
                                        values=col_fee,
                                        aggfunc="first"
                                    ).reset_index()

                                    df_pivot.rename(columns={col_team_name: "团队名称"}, inplace=True)
                                    df_pivot.columns.name = None
                                    df_pivot.sort_values(by="团队名称", ascending=True, inplace=True)

                                    ws_base_fee = fast_recreate_sheet(wb1, "基础配送费")
                                    ws_base_fee.append(list(df_pivot.columns))

                                    df_pivot_obj = df_pivot.astype(object)
                                    df_pivot_obj[pd.isna(df_pivot_obj)] = None
                                    for row_data in df_pivot_obj.values.tolist():
                                        ws_base_fee.append(row_data)

                                    log(f"-> 📊 已生成【基础配送费】透视矩阵子表，涵盖 {len(df_pivot)} 个团队及 {len(df_pivot.columns)-1} 类订单标签", "INFO")
                                else:
                                    log(f"提取 [团队名称/订单标签/基础配送费] 数据过滤后为空，跳过基础配送费矩阵生成", "WARN")
                            else:
                                log(f"未找到完整的 [团队名称/订单标签/基础配送费] 匹配列，跳过基础配送费矩阵生成", "WARN")
                        except Exception as e_base_fee:
                            log(f"生成【基础配送费】扩展子表时提示: {e_base_fee}", "WARN")
                
                    # try:
                    #     val_b2 = ""
                    #     team_name_col = next((c_name for c_name in df_source.columns if "团队名称" in str(c_name)), None)
                    #     if not df_source.empty:
                    #         if team_name_col:
                    #             val_b2 = str(df_source[team_name_col].iloc[0]).strip()
                    #         elif df_source.shape[1] > 1:
                    #             val_b2 = str(df_source.iloc[0, 1]).strip()
                    #         
                    #     df_config_tmp = pd.read_excel(main_wb_path, sheet_name="config", header=None, dtype=object)
                    #     for c in df_config_tmp.columns: df_config_tmp[c] = df_config_tmp[c].apply(_safe_str_apply)
                    #     match_row = df_config_tmp[df_config_tmp.iloc[:, 2].astype(str).str.strip() == val_b2]
                    #     if not match_row.empty:
                    #         city = str(match_row.iloc[0, 0]).strip()
                    #         log(f"-> 🎯 元数据探针锁定当前处理域: {city}!!CITY!!{city}", "INFO")
                    #         if city != "未知":
                    #             new_out_folder = os.path.join(output_base, f"{last_date.month}月", city)
                    #             if os.path.exists(out_folder) and out_folder != new_out_folder:
                    #                 import shutil
                    #                 os.makedirs(os.path.join(output_base, f"{last_date.month}月"), exist_ok=True)
                    #                 if os.path.exists(new_out_folder):
                    #                     for f in os.listdir(out_folder):
                    #                         shutil.move(os.path.join(out_folder, f), new_out_folder)
                    #                     os.rmdir(out_folder)
                    #                 else:
                    #                     os.rename(out_folder, new_out_folder)
                    #             out_folder = new_out_folder
                    #             stats_info["out_folder"] = out_folder
                    #     else:
                    #         log(f"未在config.xlsx的config子表中找到对应C列值 {val_b2} 的城市匹配，尝试使用后备默认值", "WARN")
                    # except Exception as e:
                    #     log(f"探针初始化核心错误 (使用兜底域): {e}", "WARN")

                    if is_xiaoxiang and len(df_source) > 0:
                        # 精准列名匹配：团队名称/站点名称、骑手ID、骑手姓名
                        # （与普通城市一致，最终匹配键 = 日期 + 骑手ID + 站点名称）
                        team_col = next((c for c in df_source.columns if str(c).strip() in ["团队名称", "站点名称"]), None)
                        rid_col = next((c for c in df_source.columns if str(c).strip().lower() == "骑手id"), None)
                        rname_col = next((c for c in df_source.columns if str(c).strip() == "骑手姓名"), None)
                        if not (team_col and rid_col and rname_col):
                            log("小象超市未精准匹配到【团队名称/站点名称 / 骑手ID / 骑手姓名】列，骑手花名册将为空", "WARN")

                        if team_col and rid_col and rname_col:
                            df_sht2 = df_source[[team_col, rid_col, rname_col]].copy()
                            df_sht2.columns = ["团队名称", "骑手ID", "骑手姓名"]
                            # 小象：用申请名单覆盖团队名称和骑手姓名，确保以申请站点为准
                            # 多站点骑手（申请站点>1）不覆盖团队名称，保留其各站点原始数据（避免单值 map 破坏多站点）
                            if apply_team_map:
                                _sht2_rids = df_sht2["骑手ID"].astype(str).str.replace('.0', '', regex=False).str.strip()
                                _apply_team = _sht2_rids.map(apply_team_map)
                                _mask_s2 = _apply_team.notna()
                                if _mask_s2.any():
                                    _multi_mask = _sht2_rids.map(lambda rid: len(apply_team_set.get(rid, ())) > 1)
                                    _mask_s2 = _mask_s2 & ~_multi_mask
                                    if _mask_s2.any():
                                        df_sht2.loc[_mask_s2, "团队名称"] = _apply_team[_mask_s2].values
                                _apply_rname = _sht2_rids.map(apply_rider_name_map)
                                _mask_rn = _apply_rname.notna()
                                if _mask_rn.any():
                                    df_sht2.loc[_mask_rn, "骑手姓名"] = _apply_rname[_mask_rn].values
                            df_sht2.drop_duplicates(inplace=True)
                        else:
                            df_sht2 = pd.DataFrame(columns=["团队名称", "骑手ID", "骑手姓名"])
                    
                        # 小象超市：按用户要求取消跨站合并去重·归并到主站
                        # （保留骑手花名册对 [团队名称, 骑手ID] 的基础去重，但不再把同一骑手跨站点归并到单量最多的主站）
                        enable_cross_station_merge = False
                    elif False and len(df_source) > 0 and len(df_source.columns) >= 4:
                        df_sht2 = df_source.iloc[:, 1:4].copy()
                        df_sht2.columns = ["团队名称", "骑手ID", "骑手姓名"]
                    else:
                        df_sht2 = pd.DataFrame(columns=["团队名称", "骑手ID", "骑手姓名"])

                    df_sht2.replace(r'^\s*$', np.nan, regex=True, inplace=True)
                    if len(df_sht2.columns) > 1:
                        rider_id_col = df_sht2.columns[1]
                        s_id = df_sht2[rider_id_col].astype(str).str.replace('.0', '', regex=False).str.strip()
                        s_id = s_id.replace(r'^\s*$', np.nan, regex=True).replace("nan", np.nan).replace("None", np.nan)
                        s_id = s_id.replace("", np.nan)
                        df_sht2[rider_id_col] = s_id
                        df_sht2.dropna(subset=[rider_id_col], inplace=True)
                        # 确保是正常的数值格式
                        try:
                            df_sht2[rider_id_col] = pd.to_numeric(df_sht2[rider_id_col], errors='coerce')
                        except:
                            pass

                    if enable_cross_station_merge and len(df_sht2) > 0 and len(df_sht2.columns) >= 2:
                        team_col = df_sht2.columns[0]
                        rid_col = df_sht2.columns[1]
                        df_sizes = df_sht2.groupby([rid_col, team_col]).size().reset_index(name='_counts')
                        idx = df_sizes.groupby(rid_col)['_counts'].idxmax()
                        best_teams = df_sizes.loc[idx, [rid_col, team_col]]
                        df_sht2 = pd.merge(df_sht2, best_teams, on=[rid_col, team_col], how='inner')

                    df_sht2.drop_duplicates(subset=[df_sht2.columns[0], df_sht2.columns[1]], keep='first', inplace=True)
                    df_sht2.sort_values(by=df_sht2.columns[0], ascending=True, inplace=True)
                    df_sht2.reset_index(drop=True, inplace=True)
                
                    # 开始计算考勤和保险/基金扣款
                    if wb_col_name:
                        dictp_fraud_set = set(dictp_fraud)
                        wb_vals = df_source[wb_col_name].astype(str).values
                        mask_valid = np.array([x not in dictp_fraud_set for x in wb_vals])
                    else:
                        mask_valid = np.ones(len(df_source), dtype=bool)

                    df_valid_days = df_source[mask_valid].copy()
                
                    # 安全检查，防止完全重复导致DataFrame为空引发OutOfBounds
                    if df_valid_days.empty or len(df_valid_days.columns) < 3:
                        rider_attendance = pd.DataFrame(columns=['_rid', '出勤天'])
                        best_teams = pd.DataFrame(columns=['_rid', '_tid'])
                    else:
                        # 极速处理：使用Python列表推导式替代pandas的.str方法，速度提升10倍以上
                        col0_vals = df_valid_days.iloc[:, 0].values
                        col1_vals = df_valid_days.iloc[:, 1].values
                        col2_vals = df_valid_days.iloc[:, 2].values
                    
                        df_valid_days['_date'] = [str(x)[:10] for x in col0_vals]
                        df_valid_days['_tid'] = [str(x).strip() for x in col1_vals]
                        df_valid_days['_rid'] = [str(x).replace('.0', '').strip() for x in col2_vals]

                        # 小象业务城市：仅配送完成单量>0的日期才计为有效出勤；主站按配送完成单量总和判定
                        if is_xiaoxiang:
                            complete_col = next((c for c in df_valid_days.columns if str(c).strip() == '配送完成单量'), None)
                            if complete_col:
                                qty = df_valid_days[complete_col].astype(str).str.replace(r'[^\d.\-+eE]', '', regex=True)
                                qty = pd.to_numeric(qty, errors='coerce').fillna(0)
                                df_valid_days = df_valid_days[qty > 0].copy()
                                rider_team_counts = df_valid_days.groupby(['_rid', '_tid'])[complete_col].sum().reset_index(name='order_counts')
                            else:
                                rider_team_counts = df_valid_days.groupby(['_rid', '_tid']).size().reset_index(name='order_counts')
                        else:
                            # 计算每个骑手在每个站点的单量
                            rider_team_counts = df_valid_days.groupby(['_rid', '_tid']).size().reset_index(name='order_counts')
                    
                        # 骑手在所有站点的总出勤天
                        rider_attendance = df_valid_days.groupby('_rid')['_date'].nunique().reset_index(name='出勤天')
                    
                        # 找到骑手单量最多的站点
                        if not rider_team_counts.empty:
                            idx = rider_team_counts.groupby('_rid')['order_counts'].idxmax()
                            best_teams = rider_team_counts.loc[idx, ['_rid', '_tid']]
                        else:
                            best_teams = pd.DataFrame(columns=['_rid', '_tid'])

                        # 小象：用申请名单的团队映射覆盖 best_teams，确保主站=申请站点，不回退
                        if is_xiaoxiang and apply_team_map and not best_teams.empty:
                            _bt_rids = best_teams['_rid'].astype(str).str.replace('.0', '', regex=False).str.strip()
                            _apply_tid = _bt_rids.map(apply_team_map)
                            _mask_bt = _apply_tid.notna()
                            if _mask_bt.any():
                                best_teams.loc[_mask_bt, '_tid'] = _apply_tid[_mask_bt].values
                
                    # 合并总出勤天到单量最多的站点
                    attendance_counts = pd.merge(best_teams, rider_attendance, on='_rid', how='inner')
                
                    df_sht2['_tid'] = df_sht2['团队名称'].astype(str).str.strip()
                    df_sht2['_rid'] = df_sht2['骑手ID'].astype(str).str.replace('.0', '', regex=False).str.strip()
                
                    df_sht2 = pd.merge(df_sht2, attendance_counts, on=['_tid', '_rid'], how='left')
                    df_sht2['出勤天数'] = df_sht2['出勤天'].fillna(0).astype(int)
                    df_sht2['本期出勤天'] = df_sht2['出勤天数']
                
                    try:
                        first_date_val = str(df_source.iloc[0, 0]).strip().split(" ")[0]
                        first_date_parsed = safe_parse_date([first_date_val]).iloc[0]
                        days_in_month = first_date_parsed.days_in_month
                        target_month = first_date_parsed.month
                    except Exception:
                        days_in_month = 30
                        target_month = 1

                    past_attendance_dict, past_attendance_notes, past_month_fee_deducted = extract_past_records(out_folder)

                    def get_past_days(row):
                        # 处理逻辑：获取并返回所需的系统状态或计算数据
                        if row.get('出勤天数', 0) == 0:
                            return 0
                        pid = str(row['_rid']).replace('.0', '').strip()
                        return past_attendance_dict.get(pid, 0)
                
                    def get_past_notes(row):
                        # 处理逻辑：获取并返回所需的系统状态或计算数据
                        if row.get('出勤天数', 0) == 0:
                            return ""
                        pid = str(row['_rid']).replace('.0', '').strip()
                        notes = past_attendance_notes.get(pid, [])
                        if notes:
                            return "【" + "；".join(notes) + "】"
                        return ""

                    def get_past_fee_deducted(row):
                        # 处理逻辑：获取并返回所需的系统状态或计算数据
                        pid = str(row['_rid']).replace('.0', '').strip()
                        return "是" if past_month_fee_deducted.get(pid, False) else "否"

                    df_sht2['往期累计出勤天'] = df_sht2.apply(get_past_days, axis=1)
                    df_sht2['往期累计核算记录'] = df_sht2.apply(get_past_notes, axis=1)
                    df_sht2['往期月费是否已扣'] = df_sht2.apply(get_past_fee_deducted, axis=1)

                    custom_deductions = [str(c) for c in df_rules.columns if c in DEDUCTION_COLS]
                
                    cfg_team = next((c for c in df_rules.columns if "团队名称" in str(c) and "maxDays" not in str(c)), None)
                    if cfg_team:
                        df_rules_sub = df_rules.copy()
                        df_rules_sub['_cfg_team'] = df_rules_sub[cfg_team].astype(str).str.strip()
                        df_rules_sub = df_rules_sub.drop_duplicates(subset=['_cfg_team'])
                    
                        cols_to_drop = [c for c in custom_deductions if c in df_sht2.columns]
                        if cols_to_drop:
                            df_sht2 = df_sht2.drop(columns=cols_to_drop)
                    
                        overlap = [c for c in df_rules_sub.columns if c in df_sht2.columns and c != '_cfg_team']
                        if overlap:
                            df_rules_sub = df_rules_sub.drop(columns=overlap)
                        
                        def _match_cfg_team(tid):
                            tid_str = re.sub(r'_?新专送', '', str(tid).strip())
                            for c_team in df_rules_sub['_cfg_team']:
                                c_team_clean = re.sub(r'_?新专送', '', str(c_team).strip())
                                if c_team_clean == tid_str:
                                    return c_team
                            log(f"Debug: Match failed for tid='{tid_str}'. Config teams sample: {list(df_rules_sub['_cfg_team'])[:5]}...", "WARN")
                            return str(tid).strip()
                    
                        df_sht2['_mapped_tid'] = df_sht2['_tid'].apply(_match_cfg_team)
                        df_sht2 = pd.merge(df_sht2, df_rules_sub, left_on='_mapped_tid', right_on='_cfg_team', how='left')
                        df_sht2 = df_sht2.drop(columns=['_mapped_tid'])
                
                    filtered_custom_deductions = []
                    for d_col in custom_deductions:
                        if d_col in DEDUCTION_COLS:
                            if d_col in df_sht2.columns:
                                if pd.to_numeric(df_sht2[d_col], errors='coerce').fillna(0).abs().sum() == 0:
                                    df_sht2 = df_sht2.drop(columns=[d_col])
                                    continue
                            else:
                                continue
                        filtered_custom_deductions.append(d_col)
                    custom_deductions = filtered_custom_deductions

                    for d_col in custom_deductions:
                        if d_col not in df_sht2.columns:
                            df_sht2[d_col] = 0
                        df_sht2[d_col] = pd.to_numeric(df_sht2[d_col], errors='coerce').fillna(0)

                    def calc_deduction(val, att_days, past_days, max_days, cur_days_in_month=days_in_month):
                        # 处理逻辑：针对按天数/阈值扣款项（如保险费/安全基金、使用费等）执行金额计算
                        if pd.isna(val) or val == 0 or att_days == 0: return 0
                        if pd.isna(max_days) or str(max_days).strip() == "":
                            return att_days * val
                        try:
                            max_d = float(max_days)
                        except (ValueError, TypeError):
                            return att_days * val

                        total_days = att_days + past_days
                        if total_days < max_d:
                            return att_days * val
                        else:
                            if past_days >= max_d:
                                return 0
                            else:
                                # 往期＜阈值 且 当期+往期≥阈值：按整月扣除，需抵消/扣减掉往期已按天扣除的金额
                                return max(0, (cur_days_in_month - past_days) * val)

                    for d_col in custom_deductions:
                        max_col = f"{d_col}_maxDays"
                        is_kw_col = f"{d_col}_isKw"
                    
                        if d_col == '月费':
                            def apply_fee_logic(row, d_name=d_col):
                                # 处理逻辑：当出勤天数为0时，月费值需修改为0，因为主站中已扣除，辅站中无需二次扣除
                                if row.get('往期月费是否已扣') == '是':
                                    return 0
                                att_d = row.get("出勤天数", row.get("出勤天", row.get("本期出勤天", 0)))
                                try:
                                    if pd.isna(att_d) or float(att_d) == 0:
                                        return 0
                                except (ValueError, TypeError):
                                    pass
                                return row[d_name]
                            df_sht2[d_col] = df_sht2.apply(apply_fee_logic, axis=1)
                        else:
                            def row_calc(row, item_name, max_name, iskw_name):
                                # 处理逻辑：针对具体业务项（如配送费、奖罚）执行金额计算及条件判定
                                is_kw = row.get(iskw_name, False)
                                if pd.isna(is_kw):
                                    is_kw = False
                                else:
                                    is_kw = bool(is_kw)
                                val = row[item_name]
                                
                                fixed_amt = 0
                                if not (pd.isna(val) or val == 0):
                                    att_d = row.get("出勤天数", row.get("本期出勤天", 0))
                                    if abs(val - (-0.5)) < 1e-5:
                                        fixed_amt = att_d * val
                                    else:
                                        max_val = row.get(max_name, None)
                                        fixed_amt = calc_deduction(val, att_d, row.get("往期累计出勤天", 0), max_val)
                            
                                r_id = str(row.get('_rid', '')).replace('.0', '').strip()
                                has_kw_hit = r_id in rider_wtd_deductions and item_name in rider_wtd_deductions[r_id]
                            
                                if is_kw:
                                    if has_kw_hit:
                                        return rider_wtd_deductions[r_id][item_name]
                                    else:
                                        return 0
                                else:
                                    return fixed_amt

                            df_sht2[d_col] = df_sht2.apply(lambda row: row_calc(row, d_col, max_col, is_kw_col), axis=1)

                    # 小象超市「保险费」表：将配置源列映射为模板展示列（保险费←安全基金、循环物资使用费←非蜂卡、附加险←月费）
                    if is_xiaoxiang:
                        for _disp, _src in XIAOXIANG_FEE_DISPLAY_MAP.items():
                            if _src in df_sht2.columns:
                                df_sht2[_disp] = df_sht2[_src]
                        _src_cols = [c for c in XIAOXIANG_FEE_DISPLAY_MAP.values() if c in df_sht2.columns]
                        if _src_cols:
                            df_sht2 = df_sht2.drop(columns=_src_cols)
                        custom_deductions = [c for c in custom_deductions if c not in XIAOXIANG_FEE_DISPLAY_MAP.values()]

                    # We need to recreate 团队名称 and 骑手ID from _tid and _rid.
                    # First, extract them before we drop them!
                    temp_tid = df_sht2['_tid'].copy() if '_tid' in df_sht2.columns else None
                    temp_rid = df_sht2['_rid'].copy() if '_rid' in df_sht2.columns else None
                    temp_rname = df_sht2['rname'].copy() if 'rname' in df_sht2.columns else None
                
                    cols_to_drop = ['_tid', '_rid', '_cfg_team', '出勤天', '团队名称', '骑手ID', '骑手姓名', 'rname']
                    df_sht2.drop(columns=[c for c in cols_to_drop if c in df_sht2.columns], inplace=True, errors='ignore')
                    df_sht2.drop(columns=[c for c in df_sht2.columns if c.startswith('团队名称_') or c.startswith('骑手ID_') or c.startswith('骑手姓名_')], inplace=True, errors='ignore')
                
                    if temp_tid is not None: df_sht2['团队名称'] = temp_tid
                    if temp_rid is not None: df_sht2['骑手ID'] = temp_rid
                    if temp_rname is not None: df_sht2['骑手姓名'] = temp_rname
                
                    base_cols = ["团队名称", "骑手ID", "骑手姓名", "出勤天数"]
                    if is_xiaoxiang:
                        xiaoxiang_extra_cols = ["保险费", "循环物资使用费", "附加险", "招聘来源"]
                        # 招聘来源按 (团队名称+骑手ID) 从申请名单「入职来源/招聘来源」匹配填充（与配送所得表口径一致）；
                        # 未命中或申请名单留空 → 空单元格，不再整列兜底填 0。
                        _fee_src_map = {}
                        if df_apply is not None and len(df_apply) > 0:
                            _fa_team_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("团队名称", "团队"))), 0)
                            _fa_rid_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("骑手ID", "ID", "id"))), 1)
                            _fa_src_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("入职来源", "招聘来源"))), None)
                            if _fa_src_col is not None:
                                for _far in df_apply.itertuples(index=False):
                                    try:
                                        _fat = str(_far[_fa_team_col]).strip()
                                        _farid = str(_far[_fa_rid_col]).replace('.0', '').strip()
                                        if _fat and _farid and _farid.lower() not in ('nan', 'none', ''):
                                            _fav = _far[_fa_src_col]
                                            _fav = None if _fav is None or str(_fav).strip() in ('', 'nan', 'None') else str(_fav).strip()
                                            _fee_src_map[(_fat, _farid)] = _fav
                                    except Exception:
                                        continue
                        def _fee_source_of(row):
                            _fbt = str(row.get('团队名称', '')).strip()
                            _fbrid = str(row.get('骑手ID', '')).replace('.0', '').strip()
                            return _fee_src_map.get((_fbt, _fbrid))
                        df_sht2['招聘来源'] = df_sht2.apply(_fee_source_of, axis=1)
                        _fee_matched = int(df_sht2['招聘来源'].notna().sum())
                        log(f"-> 🎯 保险费表招聘来源已按申请名单(团队名称+骑手ID)匹配填入 {_fee_matched}/{len(df_sht2)} 行", "INFO")
                        for col in xiaoxiang_extra_cols:
                            if col not in df_sht2.columns:
                                df_sht2[col] = 0
                        # 小象「保险费」表仅输出模板八列：所有配置扣款项已通过映射写入对应展示列，
                        # 不再追加 custom_deductions，避免额外源列(如 非蜂卡/使用费)泄漏成多余列
                        final_cols_sht2 = base_cols + xiaoxiang_extra_cols
                    else:
                        final_cols_sht2 = base_cols + custom_deductions
                    if not is_xiaoxiang and (past_attendance_dict or past_attendance_notes or past_month_fee_deducted):
                        final_cols_sht2.extend(["往期累计出勤天"])

                    final_cols_sht2 = list(dict.fromkeys(final_cols_sht2))
                    df_sht2 = df_sht2[[c for c in final_cols_sht2 if c in df_sht2.columns]]

                    df_sht2_obj = df_sht2.astype(object)
                    df_sht2_obj[pd.isna(df_sht2_obj)] = None

                    data_list = df_sht2_obj.values.tolist()
                    headers_sht2 = df_sht2.columns.tolist()

                    for c_idx, val in enumerate(headers_sht2, 1): ws_sht2.cell(row=1, column=c_idx, value=val)
                    for r_idx, row_data in enumerate(data_list, 2):
                        for c_idx, val in enumerate(row_data, 1): ws_sht2.cell(row=r_idx, column=c_idx, value=val)

                    last_row_sht2 = len(data_list) + 1
                    num_riders = last_row_sht2 - 1
                    stats_info["riders"] = max(stats_info.get("riders", 0), num_riders)
                    log(f"-> 🎯 聚合扫描完成：侦测到 {num_riders} 个活动实体，结算 {stats_info['orders']} 个子流！", "INFO")

                    if last_row_sht2 > 2:
                        # import re
                        # import copy
                        formula_regex = re.compile(r'(?<![a-zA-Z0-9_])(\$?)([a-zA-Z]{1,3})(\$?)([1-9][0-9]{0,6})(?![a-zA-Z0-9_])')
                    
                        def fast_shift(clean_f, delta):
                            # 处理逻辑：fast_shift 的主要执行逻辑
                            if not clean_f or delta == 0: return clean_f
                            def replacer(match):
                                # 处理逻辑：replacer 的主要执行逻辑
                                c_abs, c, r_abs, r = match.groups()
                                if r_abs == '$': return match.group(0)
                                return f"{c_abs}{c}{r_abs}{int(r) + delta}"
                            return formula_regex.sub(replacer, clean_f)

                        for col_idx in range(4, ws_sht2.max_column + 1):
                            cell_template = ws_sht2.cell(row=2, column=col_idx)
                            if cell_template.value and isinstance(cell_template.value, str) and cell_template.value.startswith('='):
                                clean_f = cell_template.value
                                for row_idx in range(3, last_row_sht2 + 1):
                                    target_cell = ws_sht2.cell(row=row_idx, column=col_idx)
                                    delta = row_idx - 2
                                    try:
                                        target_cell.value = fast_shift(clean_f, delta)
                                    except Exception:
                                        target_cell.value = cell_template.value
                                    if cell_template.has_style: target_cell._style = copy.copy(cell_template._style)

                    # import copy

                    if num_riders > 0:
                        # import re
                        formula_regex = re.compile(r'(?<![a-zA-Z0-9_])(\$?)([a-zA-Z]{1,3})(\$?)([1-9][0-9]{0,6})(?![a-zA-Z0-9_])')
                        def fast_shift(clean_f, delta):
                            # 处理逻辑：fast_shift 的主要执行逻辑
                            if not clean_f or delta == 0: return clean_f
                            def replacer(match):
                                # 处理逻辑：replacer 的主要执行逻辑
                                c_abs, c, r_abs, r = match.groups()
                                if r_abs == '$': return match.group(0)
                                return f"{c_abs}{c}{r_abs}{int(r) + delta}"
                            return formula_regex.sub(replacer, clean_f)

                        try:
                            from openpyxl.worksheet.formula import ArrayFormula
                        except ImportError:
                            try:
                                from openpyxl.formula.array import ArrayFormula
                            except ImportError:
                                ArrayFormula = None

                        m_ranges = list(ws_sht1.merged_cells.ranges)
                        for m_range in m_ranges:
                            if m_range.min_row >= 4: ws_sht1.unmerge_cells(m_range.coord)

                        if num_riders > 1:
                            try:
                                ws_sht1.insert_rows(5, amount=num_riders - 1)
                            except:
                                pass

                        max_col_sht1 = ws_sht1.max_column
                        template_row_info = []
                        for c_idx in range(1, max_col_sht1 + 1):
                            cell = ws_sht1.cell(row=4, column=c_idx)
                            _cell_val = cell.value
                            # ArrayFormula 对象无法被当前公式翻译逻辑处理，且会导致行号不偏移、Excel 提示恢复。
                            if ArrayFormula is not None and isinstance(_cell_val, ArrayFormula):
                                _cell_val = _cell_val.text
                            if isinstance(_cell_val, str) and _cell_val.startswith('=') and \
                               'LOOKUP(9^9,FIND({"SZ","HZ","CZ","ST"},' in _cell_val:
                                _cell_val = '=IF(ISNUMBER(FIND("SZ",B4)),"深圳",IF(ISNUMBER(FIND("HZ",B4)),"惠州",IF(ISNUMBER(FIND("CZ",B4)),"潮州",IF(ISNUMBER(FIND("ST",B4)),"汕头",""))))'
                            template_row_info.append({
                                'val': _cell_val, 'style': copy.copy(cell._style) if cell.has_style else None,
                                'col_letter': get_column_letter(c_idx)
                            })

                        for i in range(num_riders):
                            t_row = i + 4
                            for c_idx, t_item in enumerate(template_row_info, 1):
                                target_cell = ws_sht1.cell(row=t_row, column=c_idx)
                                if t_row > 4 and t_item['style']: target_cell._style = t_item['style']

                                if c_idx in [2, 3, 4]:
                                    val_idx = c_idx - 2
                                    target_cell.value = ws_sht2.cell(row=i + 2, column=val_idx + 1).value
                                else:
                                    formula_val = t_item['val']
                                    if isinstance(formula_val, str) and formula_val.startswith('='):
                                        clean_f = formula_val.replace("{", "").replace("}", "").strip()
                                        delta = t_row - 4
                                        try:
                                            translated_f = fast_shift(clean_f, delta)
                                            if (c_idx == 1 or c_idx == 20) and formula_val.startswith("{"):
                                                target_cell.value = ArrayFormula(target_cell.coordinate, translated_f) if ArrayFormula else translated_f
                                            else:
                                                target_cell.value = translated_f
                                        except:
                                            target_cell.value = clean_f
                                    else:
                                        if t_row > 4: target_cell.value = t_item['val']

                        f_row = max(5, 4 + num_riders)
                    
                        try:
                            ws_sht1.merge_cells(start_row=f_row, start_column=1, end_row=f_row, end_column=4)
                            cell_total = ws_sht1.cell(row=f_row, column=1)
                            cell_total.value = "合计"
                            from openpyxl.styles import Alignment
                            cell_total.alignment = Alignment(horizontal='center', vertical='center')
                        except Exception:
                            pass
                    
                        # Removed the block that attempts to format f_row since we are keeping the template's footer row, which is already correctly formatted.
                        pass

                elif "违规" in wb_name:
                    cols_to_drop = [1, 2, 3, 15, 16]
                    cols_to_drop = [c for c in cols_to_drop if c < len(df_source.columns)]
                    keep_cols = [c for c in range(len(df_source.columns)) if c not in cols_to_drop]
                    df_source = df_source.iloc[:, keep_cols].copy()

                    data_arr = df_source.values.tolist()
                    headers = df_source.columns.tolist()

                    for row in data_arr:
                        while len(row) < 15: row.append("")
                        # 普通城市（含泉州）违规索赔统一取全额，不再按违规类型做 −50/−20 调整
                        row[14] = float(row[4] or 0)
                        if "欺诈单" in str(row[6]): row[12], row[13], row[14] = "是", "欺诈单不考核", 0

                    if not getattr(wb1, 'has_cleared_wg', False):
                        ws_wg = fast_recreate_sheet(wb1, "违规索赔")
                        wb1.has_cleared_wg = True
                        start_row = 1
                    else:
                        ws_wg = wb1["违规索赔"]
                        start_row = 2 

                    if start_row == 1:
                        ws_wg.append(headers)

                    added_penalty_count = 0
                    bg_col_name = find_wb_col(headers, 10)
                    wb_idx = headers.index(bg_col_name) if bg_col_name in headers else 10

                    id_idx, name_idx = -1, -1
                    for i, c in enumerate(headers):
                        c_str = str(c)
                        c_lower = c_str.lower()
                        if ('id' in c_lower or '编号' in c_lower) and not any(
                                x in c_lower for x in ['运单', '订单', '站', '团队']): id_idx = i
                        if c_str in ['骑手姓名', '配送员姓名', '姓名', '员工姓名', '骑手名称'] or ('姓名' in c_str and '站' not in c_str) or (
                                '名称' in c_str and '骑手' in c_str): name_idx = i

                    if wb_idx is not None and wb_idx < len(headers):
                        dup_sources = {}
                        for row in data_arr:
                            wb_val = clean_wb_str(row[wb_idx]) if wb_idx < len(row) else ""
                            if wb_val and wb_val != "-" and wb_val in existing_waybills["违规索赔"]:
                                src_file = existing_waybills["违规索赔"][wb_val]
                                r_id = str(row[id_idx]).replace('.0', '').strip() if id_idx != -1 else ""
                                r_name = str(row[name_idx]).strip() if name_idx != -1 else ""
                                intercept_records.append((src_file, "索赔扣款", wb_val, r_id, r_name))
                                dup_sources[src_file] = dup_sources.get(src_file, 0) + 1
                            else:
                                ws_wg.append(row)
                                added_penalty_count += 1
                        for src_file, count in dup_sources.items(): log(
                            f"💥 [红牌拦截] 发现 {count} 条【违规索赔】重复记录！(源自历史文件: {src_file})", "ERROR")
                    else:
                        for row in data_arr:
                            ws_wg.append(row)
                            added_penalty_count += 1

                    stats_info["penalty_orders"] += added_penalty_count

                elif "问题单" in wb_name:
                    while len(df_source.columns) < 13: df_source[f"Temp_Col_{len(df_source.columns)}"] = ""
                    col_names = list(df_source.columns)
                    col_names[12] = "是否欺诈单"
                    df_source.columns = col_names

                    cols_to_drop = [c for c in df_source.columns if "Unnamed" in str(c)]
                    if cols_to_drop: df_source.drop(columns=cols_to_drop, inplace=True)

                    try:
                        col1 = df_source.columns[1]
                        col1_parsed = safe_parse_date(df_source[col1]).dt.strftime('%Y-%m-%d').fillna("")
                        df_source[col1] = col1_parsed.astype(object)
                    except Exception:
                        pass

                    rules_headers = [str(c).strip() for c in df_rules.columns.tolist()]
                    rules_data = df_rules.values.tolist()
                
                    # 构建问题单关键字映射
                    global_kw_to_header = {}
                    keyword_amount_map = {}
                    d_rules = kwargs.get("deductionRules", [])
                    if isinstance(d_rules, list) and len(d_rules) > 0 and 'sites' in d_rules[0]:
                        for city_data in d_rules:
                            for site_data in city_data.get('sites', []):
                                site_name = str(site_data.get('name', '')).strip()
                                for item in site_data.get('deductionItems', []):
                                    if item.get('isKeywordBased'):
                                        h_name = item.get('name')
                                        kw_amounts = item.get('keywordAmounts', [])
                                        if kw_amounts:
                                            for ka in kw_amounts:
                                                kw = str(ka.get('keyword', '')).strip()
                                                amt = ka.get('amount')
                                                if kw:
                                                    global_kw_to_header[kw] = h_name
                                                    if amt is not None and str(amt).strip() != '':
                                                        keyword_amount_map[(site_name, kw)] = float(amt)
                                    
                                        # Legacy fallback for old keywords string
                                        kws_str = item.get('keywords', '')
                                        if kws_str:
                                            for k in str(kws_str).split(','):
                                                k = k.strip()
                                                if k: global_kw_to_header[k] = h_name
                    else:
                        for _, row in df_rules.iterrows():
                            site_name = str(row.get('团队名称', '')).strip()
                            for c in df_rules.columns:
                                c_str = str(c)
                                if c_str.endswith('_isKw') and row.get(c_str):
                                    h_name = c_str.replace('_isKw', '')
                                    amt = row.get(h_name, 0)
                                    global_kw_to_header[h_name] = h_name
                                    keyword_amount_map[(site_name, h_name)] = float(amt)

                    team_name_idx = next((i for i, c in enumerate(rules_headers) if "团队名称" in str(c)), 2)

                    # Dynamically find columns in df_source (问题单)
                    source_headers = [str(c).strip() for c in df_source.columns]
                
                    # Find Team Name column
                    wtd_team_idx = next((i for i, c in enumerate(source_headers) if "团队名称" in c or "团队" in c or "站点" in c), 5)
                    # Find Reason/Remark column (usually 判责原因, 备注)
                    wtd_reason_idx = next((i for i, c in enumerate(source_headers) if "判责原因" in c or "原因" in c or "备注" in c), 6)
                
                    if wtd_team_idx >= len(source_headers): wtd_team_idx = 5
                    if wtd_reason_idx >= len(source_headers): wtd_reason_idx = 6

                    is_fraud_info = df_source.iloc[:, 2].astype(str).isin(dictp_fraud).map({True: "是", False: "否"}).tolist()
                    col0_list = df_source.iloc[:, 0].tolist()
                    col5_list = df_source.iloc[:, wtd_team_idx].astype(str).tolist() if len(df_source.columns) > wtd_team_idx else [""] * len(col0_list)
                    col6_list = df_source.iloc[:, wtd_reason_idx].astype(str).tolist() if len(df_source.columns) > wtd_reason_idx else [""] * len(col0_list)
                
                    fast_vals = []
                    matched_headers_list = []
                    memo_wtd = {}
                    for r0, r5, fraud, r6 in zip(col0_list, col5_list, is_fraud_info, col6_list):
                        val = np.nan
                        r0_clean = str(r0).strip() if pd.notna(r0) else str(r0)
                        r6_clean = str(r6).strip() if pd.notna(r6) else ""
                        r5_clean = str(r5).strip() if pd.notna(r5) else ""
                        matched_header = None
                        if fraud == "是":
                            val = 0
                        else:
                            base_header = None
                            if r0_clean in rules_headers:
                                base_header = r0_clean
                            else:
                                for h_name in rules_headers:
                                    if h_name in r0_clean or r0_clean in h_name:
                                        base_header = h_name
                                        break
                                    
                            matched_kw = None
                            if base_header:
                                is_kw_based = any(h == base_header for _, h in global_kw_to_header.items())
                                if is_kw_based and r6_clean:
                                    for kw, h_name in global_kw_to_header.items():
                                        if h_name == base_header and kw in r6_clean:
                                            matched_header = h_name
                                            matched_kw = kw
                                            break
                                    if not matched_header:
                                        matched_header = base_header
                                else:
                                    matched_header = base_header
                            else:
                                if r6_clean:
                                    for kw, h_name in global_kw_to_header.items():
                                        if kw in r6_clean:
                                            matched_header = h_name
                                            matched_kw = kw
                                            break

                            if matched_header:
                                cache_key = (matched_header, r5_clean, matched_kw)
                                if cache_key in memo_wtd:
                                    val = memo_wtd[cache_key]
                                else:
                                    specific_amount = None
                                    for (s_name, k_kw), amt in keyword_amount_map.items():
                                        if k_kw == matched_kw and s_name == r5_clean:
                                            specific_amount = amt
                                            break
                                        
                                    if specific_amount is not None:
                                        val = specific_amount
                                    else:
                                        # Fallback to rules_data
                                        wtd_idx = rules_headers.index(matched_header)
                                        matched_in_rule_row = False
                                        for rule_row in rules_data:
                                            rt_name = str(rule_row[team_name_idx]).strip() if pd.notna(rule_row[team_name_idx]) else ""
                                            if rt_name and rt_name == r5_clean:
                                                val = rule_row[wtd_idx]
                                                matched_in_rule_row = True
                                                break
                                        if not matched_in_rule_row and r5_clean:
                                            log(f"Debug WTD: '{r5_clean}' not found in rules. Sample: {[str(r[team_name_idx]).strip() for r in rules_data[:5]]}", "WARN")
                                    memo_wtd[cache_key] = val
                        fast_vals.append(val)
                        matched_headers_list.append(matched_header)
                
                    df_source["是否欺诈单"] = is_fraud_info
                    col_koukuan = next((c for c in df_source.columns if "扣款金额" in str(c)), df_source.columns[11] if len(df_source.columns) > 11 else None)
                    if col_koukuan:
                        df_source[col_koukuan] = fast_vals
                    else:
                        df_source["扣款金额"] = fast_vals
                
                    df_source["_matched_item"] = matched_headers_list

                    cols_to_drop_late = [c for c in df_source.columns if "处罚金额" in str(c)]
                    if cols_to_drop_late: df_source.drop(columns=cols_to_drop_late, inplace=True)


                    wb_col_name = find_wb_col(df_source.columns, 2)
                    wb_col_idx = df_source.columns.get_loc(wb_col_name) if wb_col_name else 2
                
                    ws_wtd = wb1["问题单"]
                    clean_problem_waybills = df_source.iloc[:, wb_col_idx].apply(clean_wb_str)
                    type_col = 0
                    combined_keys = df_source.iloc[:, type_col].astype(str).str.strip() + "_" + clean_problem_waybills
                    mask_dup = combined_keys.isin(existing_waybills["问题单"].keys())

                    df_dups = df_source[mask_dup].copy()
                    df_source = df_source[~mask_dup].copy()
                    stats_info["problem_orders"] += len(df_source)

                    if not df_dups.empty:
                        dup_sources = {}
                        rid_idx = next((i for i, c in enumerate(df_dups.columns) if "骑手" in str(c) and ("id" in str(c).lower() or "编码" in str(c))), 2)
                        rname_idx = next((i for i, c in enumerate(df_dups.columns) if "姓名" in str(c)), 3)
                        for row in df_dups.itertuples(index=False):
                            col0_val = str(row[type_col]).strip() if len(row) > type_col else ""
                            wb_val = clean_wb_str(row[wb_col_idx]) if len(row) > wb_col_idx else ""
                            key = f"{col0_val}_{wb_val}"
                            src_file = existing_waybills["问题单"].get(key)
                            if src_file:
                                val_type = col0_val if col0_val else "未知问题"
                                r_id = str(row[rid_idx]).replace('.0', '').strip() if rid_idx < len(row) else ""
                                r_name = str(row[rname_idx]).strip() if rname_idx < len(row) else ""
                                intercept_records.append((src_file, val_type, wb_val, r_id, r_name))
                                dup_sources[src_file] = dup_sources.get(src_file, 0) + 1
                        for src_file, count in dup_sources.items(): log(
                            f"💥 [红牌拦截] 发现 {count} 条【扣款凭证】重复记录！(源自历史文件: {src_file})", "ERROR")

                    # Aggregate keyword deductions per rider before dropping columns
                    if not df_source.empty:
                        agg_rid_col = next((c for c in df_source.columns if "骑手" in str(c) and ("id" in str(c).lower() or "编码" in str(c))), df_source.columns[2])
                        kk_col = col_koukuan if col_koukuan else "扣款金额"
                        df_source['_amount_num'] = pd.to_numeric(df_source[kk_col], errors='coerce').fillna(0)
                        for _, row in df_source.iterrows():
                            r_id_val = str(row.get(agg_rid_col, '')).replace('.0', '').strip()
                            m_item = row.get('_matched_item', None)
                            m_amt = row.get('_amount_num', 0)
                            if m_item and r_id_val:
                                if r_id_val not in rider_wtd_deductions:
                                    rider_wtd_deductions[r_id_val] = {}
                                if m_item not in rider_wtd_deductions[r_id_val]:
                                    rider_wtd_deductions[r_id_val][m_item] = 0
                                rider_wtd_deductions[r_id_val][m_item] += m_amt
                            
                    temp_cols = [c for c in df_source.columns if str(c).startswith("Temp_Col_")]
                    if temp_cols:
                        df_source.drop(columns=temp_cols, inplace=True)
                    df_source.drop(columns=['_matched_item', '_amount_num'], inplace=True, errors='ignore')

                    headers_wtd = list(df_source.columns)
                    ws_wtd = fast_recreate_sheet(wb1, "问题单")
                    ws_wtd.append(headers_wtd)
                    for row_data in df_source.values.tolist():
                        ws_wtd.append(row_data)

                elif "支付绑定" in wb_name:
                    try:
                        xls = pd.ExcelFile(file_path)
                        target_sheet = None
                        for sheet in xls.sheet_names:
                            if "绑定情况" in sheet or "绑定" in sheet:
                                target_sheet = sheet
                                break
                        if not target_sheet:
                            for sheet in xls.sheet_names:
                                df_temp = pd.read_excel(file_path, sheet_name=sheet, nrows=5)
                                if any("绑定" in str(c) for c in df_temp.columns):
                                    target_sheet = sheet
                                    break
                        if not target_sheet: target_sheet = xls.sheet_names[0]

                        df_bind_status = pd.read_excel(file_path, sheet_name=target_sheet, dtype=object)
                        for c in df_bind_status.columns: df_bind_status[c] = df_bind_status[c].apply(_safe_str_apply)
                                
                        df_bind_status_obj = df_bind_status.astype(object)
                        df_bind_status_obj[pd.isna(df_bind_status_obj)] = None
                        df_bind_status = df_bind_status_obj
                        log(f"-> 🎯 源数据寻址定标成功，锁定特征区：【{target_sheet}】！", "INFO")
                    except Exception as e:
                        log(f"尝试读取【绑定情况】表失败，回退使用默认表: {e}", "WARN")
                        df_bind_status = df_source.copy()

                    city_col_candidates = [c for c in df_bind_status.columns if any(k in str(c) for k in ["城市", "业务城市", "站点", "团队"])]
                
                    target_city_col = None
                    valid_mask = None
                    for col in city_col_candidates:
                        mask = df_bind_status[col].astype(str).apply(lambda x: city in x or x in city if pd.notna(x) and x != "nan" else False)
                        if mask.any():
                            target_city_col = col
                            valid_mask = mask
                            break

                    if target_city_col is not None:
                        df_source_filtered = df_bind_status[valid_mask]
                    elif len(df_bind_status.columns) > 0 and city in df_bind_status.iloc[:, 0].astype(str).unique():
                        df_source_filtered = df_bind_status[df_bind_status.iloc[:, 0] == city]
                    else:
                        # Return empty if no matches found for the city to prevent full data leak
                        df_source_filtered = pd.DataFrame(columns=df_bind_status.columns)

                    ws_bind = fast_recreate_sheet(wb1, "骑手支付绑定")
                    headers_bind = list(df_source_filtered.columns)
                    ws_bind.append(headers_bind)
                
                    id_col_idx = next((i for i, c in enumerate(headers_bind) if "id" in str(c).lower() and "风神" not in str(c).lower() and "身份证" not in str(c)), None)
                
                    for row_data in df_source_filtered.values.tolist():
                        new_row = list(row_data)
                    
                        if id_col_idx is not None and new_row[id_col_idx]:
                            try:
                                val_str = str(new_row[id_col_idx]).replace('.0', '').strip()
                                if val_str.isdigit():
                                    new_row[id_col_idx] = int(val_str)
                            except:
                                pass
                        ws_bind.append(new_row)

                elif "骑手账单" in wb_name or kw == "骑手账单":
                    try:
                        log(f"-> 正在解析风神骑手账单：[{wb_name}]...", "INFO")
                        
                        if file_path.lower().endswith('.csv'):
                            try:
                                df_bill_raw = pd.read_csv(file_path, encoding='gbk', header=None, dtype=object)
                                if len(df_bill_raw.columns) <= 2:
                                    df_bill_raw = pd.read_csv(file_path, encoding='gbk', sep='\t', header=None, dtype=object)
                            except UnicodeDecodeError:
                                df_bill_raw = pd.read_csv(file_path, encoding='utf-8', header=None, dtype=object)
                                if len(df_bill_raw.columns) <= 2:
                                    df_bill_raw = pd.read_csv(file_path, encoding='utf-8', sep='\t', header=None, dtype=object)
                        else:
                            try:
                                df_bill_raw = pd.read_excel(file_path, header=None, dtype=object)
                            except Exception:
                                df_bill_raw = pd.read_excel(file_path, header=None, engine='openpyxl', dtype=object)

                        if df_bill_raw is not None and not df_bill_raw.empty:
                            if "风神账单" not in wb1.sheetnames:
                                ws_fengshen = fast_recreate_sheet(wb1, "风神账单")
                            else:
                                ws_fengshen = wb1["风神账单"]
                                if ws_fengshen.max_row == 1 and (ws_fengshen.cell(row=1, column=1).value is None or str(ws_fengshen.cell(row=1, column=1).value).strip() == ''):
                                    ws_fengshen = fast_recreate_sheet(wb1, "风神账单")

                            headers_fengshen = []
                            header_row_idx = None

                            # Scan top rows to locate the header row containing "账单ID" or "骑手ID"
                            for r_idx in range(min(10, len(df_bill_raw))):
                                row_str_vals = [str(v or '').strip() for v in df_bill_raw.iloc[r_idx].values]
                                if any("账单ID" in v or "账单id" in v.lower() or "骑手ID" in v or "骑手id" in v.lower() for v in row_str_vals):
                                    header_row_idx = r_idx
                                    break

                            if header_row_idx is None:
                                if len(df_bill_raw) >= 4:
                                    header_row_idx = 3  # 0-indexed index 3 = Row 4 in Excel
                                else:
                                    header_row_idx = 0

                            if header_row_idx < len(df_bill_raw):
                                h_row = df_bill_raw.iloc[header_row_idx]
                                headers_fengshen = [str(c).strip() if pd.notna(c) and str(c).strip() not in ['', 'nan', 'None'] else f"列{i+1}" for i, c in enumerate(h_row)]
                            else:
                                headers_fengshen = [f"列{i+1}" for i in range(df_bill_raw.shape[1])]

                            # Write header row directly to row 1 if ws_fengshen is newly created/empty
                            has_header = False
                            if ws_fengshen.max_row >= 1:
                                val_a1 = ws_fengshen.cell(row=1, column=1).value
                                if val_a1 is not None and str(val_a1).strip() != '':
                                    has_header = True

                            if not has_header:
                                for c_idx, val in enumerate(headers_fengshen, 1):
                                    ws_fengshen.cell(row=1, column=c_idx, value=val)

                            # Extract rows starting right after the header row
                            data_df_bill = df_bill_raw.iloc[header_row_idx + 1:] if len(df_bill_raw) > header_row_idx + 1 else pd.DataFrame()

                            def _clean_fengshen_cell(val, col_title):
                                col_str = str(col_title or '').strip()
                                # 账单周期列和在职时间列无需转化，需保留原有格式
                                if "账单周期" in col_str or "在职时间" in col_str:
                                    if pd.isna(val) or val is None or str(val).strip().lower() == 'nan':
                                        return ""
                                    return str(val).strip()
                                
                                # 其它列：将提取中的文本数值转化为数值格式
                                if pd.isna(val) or val is None:
                                    return None
                                
                                if isinstance(val, (int, float)):
                                    return val
                                
                                s_val = str(val).strip()
                                if not s_val or s_val.lower() == 'nan':
                                    return None
                                
                                clean_s = s_val.replace(',', '')
                                try:
                                    if '.' in clean_s:
                                        return float(clean_s)
                                    else:
                                        return int(clean_s)
                                except (ValueError, TypeError):
                                    return s_val

                            bill_rows_added = 0
                            for r_i in range(len(data_df_bill)):
                                r_vals = data_df_bill.iloc[r_i].values
                                if all(pd.isna(v) or str(v).strip() in ['', 'nan', 'None'] for v in r_vals):
                                    continue
                                
                                processed_row = []
                                for c_i in range(len(r_vals)):
                                    col_hdr = headers_fengshen[c_i] if c_i < len(headers_fengshen) else f"列{c_i+1}"
                                    processed_row.append(_clean_fengshen_cell(r_vals[c_i], col_hdr))
                                
                                if all(v is None or str(v).strip() in ['', 'nan', 'None'] for v in processed_row):
                                    continue

                                ws_fengshen.append(processed_row)
                                bill_rows_added += 1

                            log(f"-> 成功提取【{wb_name}】风神账单数据 {bill_rows_added} 行，写入【风神账单】表", "SUCCESS")
                    except Exception as e:
                        log(f"提取风神账单 [{wb_name}] 遭遇异常: {e}", "WARN")

                elif "merchantfreelancer" in wb_name.lower():
                    try:
                        # 小象骑手支付绑定文件：仅保留「小组名称」为「小象超市」的行，写入既有「骑手支付绑定」表（覆盖模板空表）
                        df_mf = df_source.copy()
                        group_col = None
                        for c in df_mf.columns:
                            if str(c).strip() == "小组名称":
                                group_col = c
                                break
                        if group_col is None and len(df_mf.columns) > 5:
                            group_col = df_mf.columns[5]
                        if group_col is not None:
                            df_mf[group_col] = df_mf[group_col].apply(
                                lambda x: str(x).strip() if pd.notna(x) else ""
                            )
                            df_mf = df_mf[df_mf[group_col] == "小象超市"]
                            log(f"-> 🎯 merchantFreelancer 过滤：仅保留小组名称=小象超市，剩余 {len(df_mf)} 行", "INFO")
                        else:
                            log("-> ⚠️ 未找到「小组名称」列(第F列)，merchantFreelancer 原样写入", "WARN")
                        ws_mf = fast_recreate_sheet(wb1, "骑手支付绑定")
                        headers_mf = list(df_mf.columns)
                        ws_mf.append(headers_mf)
                        for row_data in df_mf.values.tolist():
                            ws_mf.append(row_data)
                        log(f"-> 成功将 merchantFreelancer 数据写入【骑手支付绑定】表，共 {len(df_mf)} 行", "SUCCESS")
                    except Exception as e:
                        log(f"处理 merchantFreelancer 文件 [{wb_name}] 失败: {e}", "WARN")

                log(random.choice(theme['msg_success']).format(wb_name=wb_name))
                processed_count += 1
                current_progress += progress_step
                progress_msg = random.choice(theme['msg_process']).format(wb_name=f"{wb_name[:12]} ({processed_count}/{total_files})")
                progress_callback(current_progress, f"清洗解析并注入管线：{wb_name[:12]} ({processed_count}/{total_files})")

            except KeyError as e:
                log(f"-> ⚠️ [ Key/列名缺失 (KeyError) ] 处理表格文件 [{wb_name}] 失败: 缺失必要列 {e}。算薪引擎已自动隔离异常，跳过此文件后续核算，继续处理队列中下一个文件。", "WARN")
                processed_count += 1
                current_progress += progress_step
                progress_callback(min(1.0, current_progress), f"跳过缺失列文件：{wb_name[:12]}")
                continue
            except ValueError as e:
                log(f"-> ⚠️ [ 数据类型转换失败 (ValueError) ] 处理表格文件 [{wb_name}] 失败: {e}。算薪引擎已自动隔离异常，跳过此文件后续核算，继续处理队列中下一个文件。", "WARN")
                processed_count += 1
                current_progress += progress_step
                progress_callback(min(1.0, current_progress), f"跳过类型转换失败文件：{wb_name[:12]}")
                continue
            except Exception as e:
                log(f"-> ⚠️ [ 表格核算异常 ({type(e).__name__}) ] 处理表格文件 [{wb_name}] 失败: {e}。算薪引擎已自动隔离异常，跳过此文件后续核算，继续处理队列中下一个文件。", "WARN")
                processed_count += 1
                current_progress += progress_step
                progress_callback(min(1.0, current_progress), f"跳过异常文件：{wb_name[:12]}")
                continue
        t_after_files = time.time()
        log(f"-> 节点资源扫描与加载周期消耗此时钟: {t_after_files - t_before_files:.2f}s", "SYSTEM")

        log(">>> 正在建立聚合内存管线，启动高层架构抽象逻辑...", "SYSTEM")
        progress_callback(0.85, "已建立聚合内存管线，运行业务架构关联逻辑...")

        rider_idcard_map = {}
        if "骑手支付绑定" in wb1.sheetnames:
            ws_bind_temp = wb1["骑手支付绑定"]
            bind_id_col = -1
            bind_idcard_col = -1
            for c in range(1, min(30, ws_bind_temp.max_column + 1)):
                h_val = str(ws_bind_temp.cell(row=1, column=c).value or "").strip()
                h_val_lower = h_val.lower()
                if ("id" in h_val_lower or "编号" in h_val_lower) and ("骑手" in h_val or "员工" in h_val) and bind_id_col == -1:
                    bind_id_col = c
                if "身份证" in h_val and bind_idcard_col == -1:
                    bind_idcard_col = c
            
            if bind_id_col != -1 and bind_idcard_col != -1:
                for r_idx in range(2, ws_bind_temp.max_row + 1):
                    rid = str(ws_bind_temp.cell(row=r_idx, column=bind_id_col).value or "").replace('.0', '').strip()
                    idcard = str(ws_bind_temp.cell(row=r_idx, column=bind_idcard_col).value or "").strip()
                    if rid and idcard:
                        rider_idcard_map[rid] = idcard

        daily_summary = {}
        if is_xiaoxiang:
            headers_abcd = ["A列", "B列", "C列", "D列", "日维度总单量", "蓝橙单价", "骑手身份证", "匹配策略"]
        else:
            headers_abcd = ["A列", "B列", "C列", "D列", "日单量", "完成单", "不准时单", "欺诈单(完成单)", "完成单(不准时单)", "蓝橙单价", "骑手身份证", "匹配策略"]
        sorted_keys = []

        if global_df_delivery is not None and not global_df_delivery.empty:
            headers = list(global_df_delivery.columns)
            
            c0_col = next((c for c in headers if "账单时间" in str(c) or "时间" in str(c) or "日期" in str(c)), headers[0])
            # 小象配送单无"团队名称"列, 站点列名为"所属站点"; 兼容 站点名称/站点, 普通城市有"团队名称"不受影响
            c1_col = next((c for c in headers if "团队名称" in str(c)),
                       next((c for c in headers if "团队" in str(c) and "id" not in str(c).lower()),
                         next((c for c in headers if "所属站点" in str(c) or "站点名称" in str(c) or "站点" in str(c)),
                           headers[1] if len(headers) > 1 else None)))
            c2_col = next((c for c in headers if "骑手id" in str(c).lower() or ("id" in str(c).lower() and "骑手" in str(c))), headers[2] if len(headers) > 2 else None)
            c3_col = next((c for c in headers if "骑手名称" in str(c) or "姓名" in str(c)), headers[3] if len(headers) > 3 else None)
            c4_col = next((c for c in headers if "身份证" in str(c) or "证件" in str(c)), None)
            
            first_4_headers = [str(x) if x is not None else "" for x in [c0_col, c1_col, c2_col, c3_col]]
            if is_xiaoxiang:
                headers_abcd = first_4_headers + ["日维度总单量", "蓝橙单价", "骑手身份证", "匹配策略"]
            else:
                headers_abcd = first_4_headers + ["日单量", "完成单", "不准时单", "欺诈单(完成单)", "完成单(不准时单)", "蓝橙单价", "骑手身份证", "匹配策略"]
            
            status_col = "状态" if "状态" in headers else None
            waybill_status_col = "运单状态" if "运单状态" in headers else None
            fraud_col = "是否欺诈单" if "是否欺诈单" in headers else None
            
            _sel_cols = [c for c in [c0_col, c1_col, c2_col, c3_col, c4_col] if c is not None]
            _seen = set()
            cols_to_keep = []
            for c in _sel_cols:
                if c not in _seen:
                    _seen.add(c)
                    cols_to_keep.append(c)
            if status_col: cols_to_keep.append(status_col)
            if waybill_status_col: cols_to_keep.append(waybill_status_col)
            if fraud_col and fraud_col in headers: cols_to_keep.append(fraud_col)

            gdf = global_df_delivery[cols_to_keep].copy()
            # 去重列名，避免重复标签（如小象合成状态列）导致 gdf[col] 返回 DataFrame
            _gc, _gseen = [], {}
            for c in gdf.columns:
                if c in _gseen:
                    _gseen[c] += 1
                    _gc.append(f"{c}_{_gseen[c]}")
                else:
                    _gseen[c] = 0
                    _gc.append(c)
            gdf.columns = _gc
            for col in gdf.columns:
                gdf[col] = gdf[col].fillna("").astype(str).str.strip()
            
            gdf = gdf[gdf[c0_col] != ""]
            
            is_late_series = pd.Series(False, index=gdf.index)
            is_comp_series = pd.Series(False, index=gdf.index)
            
            if status_col:
                status_str = gdf[status_col].astype(str).str.strip()
                is_late_series |= status_str.isin(["完成单-不准时", "完成单-超时", "完成单-T10"])
                is_comp_series |= status_str.str.startswith("完成单")
                
            if waybill_status_col:
                waybill_status_str = gdf[waybill_status_col].astype(str).str.strip()
                is_late_series |= waybill_status_str.isin(["完成单-不准时"])
                is_comp_series |= waybill_status_str.str.startswith("完成单")
                
            gdf["_is_late"] = is_late_series.astype(int)
            gdf["_is_comp"] = is_comp_series.astype(int)
                
            if fraud_col:
                gdf["_is_fraud_comp"] = ((gdf[fraud_col].astype(str).str.strip() == "是") & gdf["_is_comp"]).astype(int)
                gdf["_is_fraud_late"] = ((gdf[fraud_col].astype(str).str.strip() == "是") & gdf["_is_late"]).astype(int)
            else:
                gdf["_is_fraud_comp"] = 0
                gdf["_is_fraud_late"] = 0
                
            group_cols = [c for c in [c0_col, c1_col, c2_col, c3_col, c4_col] if c is not None]
            _gseen = set()
            group_cols = [c for c in group_cols if not (c in _gseen or _gseen.add(c))]
            grouped = gdf.groupby(group_cols).agg(
                total=(c0_col, "size"),
                completed=("_is_comp", "sum"),
                late=("_is_late", "sum"),
                fraud_comp=("_is_fraud_comp", "sum"),
                fraud_late=("_is_fraud_late", "sum")
            ).reset_index()
            
            for row in grouped.itertuples(index=False):
                key = (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
                daily_summary[key] = {
                    "total": int(row.total),
                    "completed": int(row.completed),
                    "late": int(row.late),
                    "fraud_comp": int(row.fraud_comp),
                    "fraud_late": int(row.fraud_late),
                    "idcard": str(row[4]) if c4_col else ""
                }

        sorted_keys = sorted(daily_summary.keys(), key=lambda x: str(x[1]))

        # 小象：构建「日维度单量」查询表 (所属站点, 日期, 骑手ID) -> 配送完成单量（日维度总单量）
        # 用途：蓝橙单价报备表「日维度总单量」列从此表取数，而非配送明细计数。
        # 取数口径：以「配送完成单量」为准（实际完成量），不再用「推配送单量」（派单量，含未完成单）。
        # 修复：重复键(同站点+日期+骑手ID 出现多行，如一日被拆成两行)必须累加而非覆盖，否则会丢失单量。
        daily_qty_map = {}
        if is_xiaoxiang and delivery_sheet_name in wb1.sheetnames:
            _ws_dq = wb1[delivery_sheet_name]
            _dq_rows = list(_ws_dq.iter_rows(values_only=True))
            if _dq_rows:
                _dq_headers = [str(h).strip().strip("'\"") if h is not None else "" for h in _dq_rows[0]]
                _dq_date_idx = next((i for i, h in enumerate(_dq_headers) if h in ("日期", "账单时间", "时间")), 0)
                _dq_rid_idx = next((i for i, h in enumerate(_dq_headers) if h == "骑手ID"), 1)
                _dq_site_idx = next((i for i, h in enumerate(_dq_headers) if h in ("所属站点", "站点名称", "站点")), 3)
                # 严格按优先级精确匹配（注意：不可用 `h in (多个候选)`，否则会命中排在前面的推配送单量）
                _dq_qty_idx = next((i for i, h in enumerate(_dq_headers) if h == "配送完成单量"), None) \
                    or next((i for i, h in enumerate(_dq_headers) if h == "完成单量"), None) \
                    or next((i for i, h in enumerate(_dq_headers) if h == "推配送单量"), None) \
                    or next((i for i, h in enumerate(_dq_headers) if h == "配送总单量"), None) \
                    or next((i for i, h in enumerate(_dq_headers) if h == "总单量"), None)
                if _dq_qty_idx is None:
                    _dq_qty_idx = next((i for i, h in enumerate(_dq_headers) if "单量" in h), None)
                for _r in _dq_rows[1:]:
                    if _dq_rid_idx >= len(_r) or _r[_dq_rid_idx] in (None, ""):
                        continue
                    _dq_rid = str(_r[_dq_rid_idx]).replace('.0', '').strip()
                    _dq_site = str(_r[_dq_site_idx]).strip() if _dq_site_idx < len(_r) and _r[_dq_site_idx] is not None else ""
                    _dq_date = _norm_date(_r[_dq_date_idx]) if _dq_date_idx < len(_r) else ""
                    _dq_qty_raw = _r[_dq_qty_idx] if (_dq_qty_idx is not None and _dq_qty_idx < len(_r)) else None
                    try:
                        _dq_qty = int(float(str(_dq_qty_raw).replace(',', ''))) if _dq_qty_raw not in (None, "") else 0
                    except (ValueError, TypeError):
                        _dq_qty = 0
                    # 累加而非覆盖，确保被拆分到多行的同一骑手日单量不丢失
                    daily_qty_map[(_dq_site, _dq_date, _dq_rid)] = daily_qty_map.get((_dq_site, _dq_date, _dq_rid), 0) + _dq_qty

        # 小象：蓝橙单价报备表「骑手信息 + 单量」全面以「日维度单量」表为权威数据源。
        # 行（日期 / 所属站点 / 骑手ID / 骑手姓名）与日维度总单量（配送完成单量）均取自该表，
        # 不再依赖商配送明细聚合；考勤等其他逻辑仍沿用商配送聚合（不影响）。
        daily_summary_xiao = {}
        if is_xiaoxiang and delivery_sheet_name in wb1.sheetnames:
            _ws_dqx = wb1[delivery_sheet_name]
            _dqx_rows = list(_ws_dqx.iter_rows(values_only=True))
            if _dqx_rows:
                _dqx_headers = [str(h).strip().strip("'\"") if h is not None else "" for h in _dqx_rows[0]]
                _dqx_date_idx = next((i for i, h in enumerate(_dqx_headers) if h in ("日期", "账单时间", "时间")), 0)
                _dqx_rid_idx = next((i for i, h in enumerate(_dqx_headers) if h == "骑手ID"), 1)
                _dqx_name_idx = next((i for i, h in enumerate(_dqx_headers) if h in ("骑手姓名", "姓名")), 2)
                _dqx_site_idx = next((i for i, h in enumerate(_dqx_headers) if h in ("所属站点", "站点名称", "站点")), 3)
                # 严格按优先级精确匹配（注意：不可用 `h in (多个候选)`，否则会命中排在前面的推配送单量）
                _dqx_qty_idx = next((i for i, h in enumerate(_dqx_headers) if h == "配送完成单量"), None) \
                    or next((i for i, h in enumerate(_dqx_headers) if h == "完成单量"), None) \
                    or next((i for i, h in enumerate(_dqx_headers) if h == "推配送单量"), None) \
                    or next((i for i, h in enumerate(_dqx_headers) if h == "配送总单量"), None) \
                    or next((i for i, h in enumerate(_dqx_headers) if h == "总单量"), None)
                if _dqx_qty_idx is None:
                    _dqx_qty_idx = next((i for i, h in enumerate(_dqx_headers) if "单量" in h), None)
                for _r in _dqx_rows[1:]:
                    if _dqx_rid_idx >= len(_r) or _r[_dqx_rid_idx] in (None, ""):
                        continue
                    _dqx_rid = str(_r[_dqx_rid_idx]).replace('.0', '').strip()
                    _dqx_site = str(_r[_dqx_site_idx]).strip() if _dqx_site_idx < len(_r) and _r[_dqx_site_idx] is not None else ""
                    _dqx_date = _norm_date(_r[_dqx_date_idx]) if _dqx_date_idx < len(_r) else ""
                    _dqx_name = str(_r[_dqx_name_idx]).strip() if _dqx_name_idx < len(_r) and _r[_dqx_name_idx] is not None else ""
                    _dqx_qty_raw = _r[_dqx_qty_idx] if (_dqx_qty_idx is not None and _dqx_qty_idx < len(_r)) else None
                    try:
                        _dqx_qty = int(float(str(_dqx_qty_raw).replace(',', ''))) if _dqx_qty_raw not in (None, "") else 0
                    except (ValueError, TypeError):
                        _dqx_qty = 0
                    _key = (_dqx_date, _dqx_site, _dqx_rid, _dqx_name)
                    if _key in daily_summary_xiao:
                        daily_summary_xiao[_key]["total"] += _dqx_qty
                    else:
                        daily_summary_xiao[_key] = {"total": _dqx_qty, "completed": 0, "late": 0, "fraud_comp": 0, "fraud_late": 0, "idcard": ""}

        # 小象：蓝橙单价报备表以独立 sheet「蓝橙单价报备」承载。原因：
        # ① 原「日单量」sheet 在收尾阶段会被删除（见文件末尾 is_xiaoxiang 分支），不能复用；
        # ② 避免与「配送所得表/日维度单量」耦合，保持该表结构独立、可审计。
        if is_xiaoxiang:
            _daily_sheet_name = "蓝橙单价报备"
            if _daily_sheet_name in wb1.sheetnames:
                ws_daily = fast_recreate_sheet(wb1, _daily_sheet_name)
            else:
                _idx = wb1.sheetnames.index(delivery_sheet_name) + 1 if delivery_sheet_name in wb1.sheetnames else 2
                ws_daily = wb1.create_sheet(title=_daily_sheet_name, index=_idx)
        elif "日单量" in wb1.sheetnames:
            ws_daily = fast_recreate_sheet(wb1, "日单量")
        else:
            _ds = _resolve_delivery_sheet(wb1)
            target_idx_daily = wb1.sheetnames.index(_ds.title) + 1 if _ds is not None else 2
            ws_daily = wb1.create_sheet(title="日单量", index=target_idx_daily)

        # 表头：小象与非小象均写入（蓝橙单价报备表含 身份证号码/蓝橙单价/匹配策略 三列）
        ws_daily.append(headers_abcd)

        no_price_records = []
        from collections import defaultdict
        rider_prices_dict = defaultdict(set)
        rider_price_dates_dict = defaultdict(lambda: defaultdict(list))

        # 小象：蓝橙单价报备行与单量源自「日维度单量」；其余城市沿用商配送聚合（daily_summary）
        _xb_keys = sorted(daily_summary_xiao.keys(), key=lambda x: str(x[1])) if is_xiaoxiang else sorted_keys
        _xb_ds = daily_summary_xiao if is_xiaoxiang else daily_summary
        for row_data in _xb_keys:
            summary = _xb_ds[row_data]
            count_total = summary["total"]
            count_comp = summary["completed"]
            count_late = summary["late"]
            count_fraud_comp = summary["fraud_comp"]
            count_fraud_late = summary["fraud_late"]
            idcard_from_daily = summary.get("idcard", "").strip().upper()

            b_date = _norm_date(row_data[0])
            team_name = str(row_data[1]).replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip()
            r_id = str(row_data[2]).replace('.0', '').strip()
            r_name = str(row_data[3]).strip()

            # 日维度总单量：优先取自「日维度单量」表（按 所属站点 + 日期 + 骑手ID 匹配）；未命中则回退配送明细计数
            if is_xiaoxiang:
                daily_total_qty = daily_qty_map.get((team_name, b_date, r_id))
                if daily_total_qty is None:
                    daily_total_qty = count_total
            else:
                daily_total_qty = count_total

            key_id = f"{b_date}_{team_name}_{r_id}"
            key_name = f"{b_date}_{team_name}_{r_name}"

            idcard_from_bind = rider_idcard_map.get(r_id, "")
            idcard_from_apply = apply_rider_idcard_map.get(r_id, "")
            # 身份证来源优先级：日维度明细自带 > 申请名单(骑手ID对应) > 骑手支付绑定
            idcard = idcard_from_daily if idcard_from_daily else (idcard_from_apply if idcard_from_apply else idcard_from_bind)
            idcard = str(idcard).strip().upper()
            
            key_idcard = f"{b_date}_{team_name}_{idcard}"

            # 小象站点「关键字匹配」：日维度站点(小象超市-XX站-CODE) -> 价格档案站点(XX站)
            # 原有精准匹配仍保留；仅当精准匹配未命中时，按关键字映射表回退再匹配一次。
            team_name_kw = XIAOXIANG_STATION_KEYWORD_MAP.get(team_name, team_name)

            price = None
            match_type = ""
            if idcard:
                price = price_mapping_idcard.get(key_idcard)
                if price: match_type = "【日期 + 站点名称 + 身份证】"
            # 关键字匹配回退（身份证）
            if not price and idcard and team_name_kw != team_name:
                price = price_mapping_idcard.get(f"{b_date}_{team_name_kw}_{idcard}")
                if price: match_type = "【日期 + 站点名称 + 身份证(关键字)】"

            if not price and r_id: 
                price = price_mapping_id.get(key_id)
                if price: match_type = "【日期 + 站点名称 + 风神骑手ID】"
            # 关键字匹配回退（风神骑手ID）
            if not price and r_id and team_name_kw != team_name:
                price = price_mapping_id.get(f"{b_date}_{team_name_kw}_{r_id}")
                if price: match_type = "【日期 + 站点名称 + 风神骑手ID(关键字)】"

            if not price: 
                price = price_mapping_name.get(key_name)
                if price: match_type = "【日期 + 站点名称 + 骑手姓名】"
            # 关键字匹配回退（骑手姓名）
            if not price and team_name_kw != team_name:
                price = price_mapping_name.get(f"{b_date}_{team_name_kw}_{r_name}")
                if price: match_type = "【日期 + 站点名称 + 骑手姓名(关键字)】"

            if price is not None and str(price).strip() != "":
                try:
                    price_float = float(price)
                    if price_float == 0.0:
                        price = "无单价"
                        match_type = ""
                    else:
                        price = price_float
                except ValueError:
                    pass

            if not price or str(price).strip() == "": 
                price = "无单价"
                match_type = ""

            full_row = list(row_data) + [daily_total_qty, price, idcard, match_type]
            try:
                full_row[2] = to_numeric_if_possible(full_row[2])
            except:
                pass
            if price == "无单价": no_price_records.append(full_row)

            rider_key = f"{team_name}_{r_id}"
            rider_prices_dict[rider_key].add(str(price))
            rider_price_dates_dict[rider_key][str(price)].append(b_date)

            # 小象：蓝橙单价报备表同样写入（身份证取自申请名单·骑手ID匹配，蓝橙单价走六层取价）
            ws_daily.append(full_row)

        def format_dates_streak(date_strs):
            # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
            # 连续日期合并区间：同月内输出「1-4日」（仅末尾带"日"）；跨月/跨年时显示月份避免歧义（"7月30日-8月2日"）
            # 鲁棒输入：支持 str / datetime / pd.Timestamp / 数值时间戳 / 带时间部分字符串 / None 等
            if not date_strs:
                return ""
            d_objs = []
            for d in date_strs:
                if d is None or d == "":
                    continue
                parsed = None
                try:
                    # 数值戳（unix 秒或毫秒）
                    if isinstance(d, (int, float)) or (isinstance(d, str) and d.replace('.', '', 1).isdigit()):
                        num = float(d)
                        if num > 1e11:        # 毫秒级
                            parsed = datetime.utcfromtimestamp(num / 1000.0)
                        elif num > 1e9:      # 秒级
                            parsed = datetime.utcfromtimestamp(num)
                        elif 30000 < num < 60000:  # Excel 序列日期
                            from datetime import timedelta as _td
                            parsed = (datetime(1899, 12, 30) + _td(days=num))
                except Exception:
                    parsed = None
                # datetime / Timestamp
                if parsed is None and hasattr(d, 'strftime') and not isinstance(d, str):
                    try:
                        parsed = d if isinstance(d, datetime) else d.to_pydatetime() if hasattr(d, 'to_pydatetime') else None
                    except Exception:
                        parsed = None
                # 字符串解析
                if parsed is None and isinstance(d, str):
                    s = d.strip()
                    # 截断到日期部分（处理带时间的字符串，如 "2026-08-03 00:00:00"）
                    if ' ' in s:
                        s = s.split(' ')[0]
                    # 截断到 / 或 T 之后
                    for sep in ['/', 'T']:
                        if sep in s:
                            s = s.split(sep)[0]
                    # 多格式兜底
                    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d', '%Y年%m月%d日'):
                        try:
                            parsed = datetime.strptime(s, fmt)
                            break
                        except ValueError:
                            continue
                if parsed is not None:
                    d_objs.append(parsed)
            if not d_objs:
                # 兜底：原样拼接（仍带分隔符，但保留可读性）
                return "；".join(str(x) for x in date_strs if x not in (None, ""))
            d_objs = sorted(list({d.date() for d in d_objs}))
            # 转回 datetime 便于 .day / .month / .year 访问
            d_objs = [datetime.combine(d, datetime.min.time()) for d in d_objs]
            streaks = []
            current_streak = [d_objs[0]]
            for i in range(1, len(d_objs)):
                if (d_objs[i] - current_streak[-1]).days == 1:
                    current_streak.append(d_objs[i])
                else:
                    streaks.append(current_streak)
                    current_streak = [d_objs[i]]
            streaks.append(current_streak)
            # 整体是否跨月/跨年，决定是否在日期前标注月份
            cross_month = len({d.month for d in d_objs}) > 1 or len({d.year for d in d_objs}) > 1
            formatted = []
            for streak in streaks:
                start, end = streak[0], streak[-1]
                if cross_month:
                    s = f"{start.month}月{start.day}日"
                    e = f"{end.month}月{end.day}日"
                    formatted.append(s if start == end else f"{s}-{e}")
                else:
                    if start == end:
                        formatted.append(f"{start.day}日")
                    else:
                        formatted.append(f"{start.day}-{end.day}日")
            return "；".join(formatted)

        grouped = defaultdict(list)
        if no_price_records:
            log(f">>> 🚨 捕获游走态意外节点！正在留存状态快照至【无特征溯源池】...", "WARN")
            if "蓝橙无单价明细" in wb1.sheetnames:
                ws_noprice = fast_recreate_sheet(wb1, "蓝橙无单价明细")
                current_idx = wb1.index(ws_noprice)
                if current_idx != 0: wb1.move_sheet(ws_noprice, offset=-current_idx)
            else:
                ws_noprice = wb1.create_sheet(title="蓝橙无单价明细", index=0)

            if "蓝橙无单价" in wb1.sheetnames:
                ws_old = fast_recreate_sheet(wb1, "蓝橙无单价")
                ws_old.sheet_state = 'hidden'

            ws_noprice.sheet_properties.tabColor = "FF9900"
            headers_noprice = ["团队名称", "骑手ID", "骑手姓名", "蓝橙无单价日期"]
            ws_noprice.append(headers_noprice)

            for rec in no_price_records:
                b_date = _norm_date(rec[0])
                team = str(rec[1]).strip()
                r_id = str(rec[2]).replace('.0', '').strip()
                r_name = str(rec[3]).strip()
                key = (team, r_id, r_name)
                grouped[key].append(b_date)

            for key, dates in grouped.items():
                date_str = format_dates_streak(dates) + "无单价"
                row_vals = [key[0], key[1], key[2], date_str]
                ws_noprice.append(row_vals)


        # 开始基于日维度单量数据计算考勤和保险/基金扣款
        fund_sheet_name = "保险费" if is_xiaoxiang else "安全基金"
        if fund_sheet_name in wb1.sheetnames and _resolve_delivery_sheet(wb1) is not None and daily_summary:
            ws_sht2 = wb1[fund_sheet_name]
            ws_sht1 = _resolve_delivery_sheet(wb1)

            # 小象：从「配送单」工作表按 D列所属站点、B列骑手ID、C列骑手姓名提取正确身份
            # （聚合管线在小象下因缺少账单时间/团队名称会回退错位，导致保险费 A/B/C 列错填）
            rider_site_map = {}
            rider_name_map = {}
            if is_xiaoxiang and delivery_sheet_name in wb1.sheetnames:
                ws_delivery = wb1[delivery_sheet_name]
                delivery_rows = list(ws_delivery.iter_rows(values_only=True))
                if delivery_rows:
                    headers = [str(h).strip() if h is not None else "" for h in delivery_rows[0]]
                    # 优先按列名定位，列名缺失时回退到 B/C/D 位置
                    rid_idx = next((i for i, h in enumerate(headers) if h == "骑手ID"), 1)
                    rname_idx = next((i for i, h in enumerate(headers) if h == "骑手姓名"), 2)
                    site_idx = next((i for i, h in enumerate(headers) if h == "所属站点"), 3)
                    site_counter = {}
                    for r in delivery_rows[1:]:
                        rid_val = str(r[rid_idx]).replace('.0', '').strip() if rid_idx < len(r) and r[rid_idx] is not None else ""
                        if not rid_val or rid_val.lower() == 'nan':
                            continue
                        rname_val = str(r[rname_idx]).strip() if rname_idx < len(r) and r[rname_idx] is not None else ""
                        site_val = str(r[site_idx]).strip() if site_idx < len(r) and r[site_idx] is not None else ""
                        if rid_val not in rider_name_map:
                            rider_name_map[rid_val] = rname_val
                        if site_val:
                            site_counter[(rid_val, site_val)] = site_counter.get((rid_val, site_val), 0) + 1
                    for (rid_val, site_val), cnt in site_counter.items():
                        if rid_val not in rider_site_map or cnt > rider_site_map[rid_val][1]:
                            rider_site_map[rid_val] = (site_val, cnt)
                    rider_site_map = {k: v[0] for k, v in rider_site_map.items()}

            # 小象：仅当「跨站合并」开启时，才用申请名单团队映射覆盖 rider_site_map；
            # 关闭时保留配送单原始站点，确保跨站骑手各站点独立计薪。
            if is_xiaoxiang and apply_team_map and enable_cross_station_merge:
                for _rid_val, _apply_team in apply_team_map.items():
                    rider_site_map[_rid_val] = _apply_team

            att_records = []
            for row_data in sorted_keys:
                b_date, team, rid, rname = row_data
                summ = daily_summary[row_data]
                has_fraud = (summ.get("fraud_comp", 0) > 0 or summ.get("fraud_late", 0) > 0)
                if has_fraud:
                    real_comp = summ.get("completed", 0) - summ.get("fraud_comp", 0)
                    real_late = summ.get("late", 0) - summ.get("fraud_late", 0)
                    is_valid = 0 if (real_comp <= 0 and real_late <= 0) else 1
                else:
                    is_valid = 1
                rid_clean = str(rid).replace('.0', '').strip()
                team_clean = str(team).replace('.0', '').strip()
                if not rid_clean or rid_clean.lower() == 'nan': continue
                # 小象：跨站合并开启时强制归并到申请站点；关闭时保留配送单原始站点（每站点独立工资条）
                if is_xiaoxiang:
                    if enable_cross_station_merge:
                        _team = apply_team_map.get(rid_clean, rider_site_map.get(rid_clean, team_clean))
                    else:
                        _team = team_clean
                    _rid = rid_clean
                    _rname = apply_rider_name_map.get(rid_clean, rider_name_map.get(rid_clean, str(rname).strip()))
                else:
                    _team = str(team).strip()
                    _rid = rid_clean
                    _rname = str(rname).strip()
                att_records.append({
                    "_date": b_date,
                    "_tid": _team,
                    "_rid": _rid,
                    "rname": _rname,
                    "is_valid": is_valid,
                    "order_count": summ["total"]
                })
            
            # import pandas as pd
            df_att = pd.DataFrame(att_records)
            if is_xiaoxiang:
                # 小象模板展示列（保险费/循环物资使用费/附加险/招聘来源），不预先声明配置源列，
                # 以便下方的 merge 能把 config 中的「安全基金/非峰卡/月费」正确合并并参与计算
                df_sht2 = pd.DataFrame(columns=["团队名称", "骑手ID", "骑手姓名", "出勤天", "保险费", "循环物资使用费", "附加险", "招聘来源"])
            else:
                df_sht2 = pd.DataFrame(columns=["团队名称", "骑手ID", "骑手姓名", "出勤天", "安全基金", "非蜂卡", "月费"])
            
            if not df_att.empty:
                # 小象超市：仅「配送完成单量>0」的 (日期,骑手) 才计为有效出勤；主站按配送完成单量总和最多判定
                best_teams = None
                if is_xiaoxiang and global_df_delivery is not None and not global_df_delivery.empty and '配送完成单量' in global_df_delivery.columns:
                    gd = global_df_delivery.copy()
                    gd['_qty'] = pd.to_numeric(gd['配送完成单量'].astype(str).str.replace(r'[^\d.\-+eE]', '', regex=True), errors='coerce').fillna(0)
                    gd['_d'] = gd['日期'].astype(str).str.strip().str[:10]
                    gd['_r'] = gd['骑手ID'].astype(str).str.replace('.0', '', regex=False).str.strip()
                    gd['_t'] = gd['所属站点'].astype(str).str.strip()
                    valid_keys = set(zip(
                        gd.loc[gd['_qty'] > 0, '_d'].tolist(),
                        gd.loc[gd['_qty'] > 0, '_r'].tolist()
                    ))
                    team_qty = gd.groupby(['_r', '_t'])['_qty'].sum().reset_index(name='_qty_sum')
                    if not team_qty.empty:
                        _ix = team_qty.groupby('_r')['_qty_sum'].idxmax()
                        best_teams = team_qty.loc[_ix, ['_r', '_t']].rename(columns={'_r': '_rid', '_t': '_tid'})
                    df_att['_valid'] = df_att.apply(
                        lambda x: (str(x['_date'])[:10], str(x['_rid']).replace('.0', '').strip()) in valid_keys,
                        axis=1
                    )
                    df_valid_days = df_att[(df_att["is_valid"] == 1) & (df_att["_valid"])]
                else:
                    df_valid_days = df_att[df_att["is_valid"] == 1]

                # 跨站骑手出勤天规则（小象 & 跨站合并关闭）：
                #   1) 总出勤天 = 跨所有站点的「不重复有效日期」数（同一天跨站跑单不重叠，计 1 天）；
                #   2) 总出勤天写入「总单量(配送完成单量)最多的站点」，其余站点出勤天 = 0；
                #   3) 仍保留各 (骑手, 站点) 独立工资条。
                if is_xiaoxiang and not enable_cross_station_merge:
                    if not df_valid_days.empty:
                        # 总出勤天：跨所有站点的不重复有效日期（同日跨站计 1 天，不重叠）
                        rider_total_days = df_valid_days.groupby('_rid')['_date'].nunique().reset_index(name='总出勤天')
                        # 主站 = 总单量(配送完成单量)最多的站点
                        if 'team_qty' in locals() and team_qty is not None and not team_qty.empty:
                            _pq = team_qty.rename(columns={'_r': '_rid', '_t': '_tid'})[['_rid', '_tid', '_qty_sum']]
                        else:
                            _pq = df_valid_days.groupby(['_rid', '_tid'])['order_count'].sum().reset_index(name='_qty_sum')
                        _prim_idx = _pq.groupby('_rid')['_qty_sum'].idxmax()
                        primary_teams = _pq.loc[_prim_idx, ['_rid', '_tid']]
                        # best_teams：保留全部 (骑手, 站点) 组合 → 各站点独立工资条
                        best_teams = df_valid_days[['_rid', '_tid']].drop_duplicates().reset_index(drop=True)
                        # attendance_counts：默认 0，仅主站填总出勤天
                        attendance_counts = best_teams.merge(rider_total_days, on='_rid', how='left')
                        _prim_set = set(
                            (str(_pr).replace('.0', '').strip(), str(_pt).replace('.0', '').strip())
                            for _pr, _pt in zip(primary_teams['_rid'].astype(str), primary_teams['_tid'].astype(str))
                        )
                        attendance_counts['出勤天'] = [
                            0 if (str(r).replace('.0', '').strip(), str(t).replace('.0', '').strip()) not in _prim_set
                            else int(d)
                            for r, t, d in zip(
                                attendance_counts['_rid'], attendance_counts['_tid'], attendance_counts['总出勤天'].fillna(0)
                            )
                        ]
                        attendance_counts = attendance_counts[['_rid', '_tid', '出勤天']]
                    else:
                        rider_total_days = pd.DataFrame(columns=['_rid', '总出勤天'])
                        best_teams = pd.DataFrame(columns=['_rid', '_tid'])
                        attendance_counts = pd.DataFrame(columns=['_rid', '_tid', '出勤天'])
                else:
                    if not df_valid_days.empty:
                        rider_attendance = df_valid_days.groupby('_rid')['_date'].nunique().reset_index(name='出勤天')
                    else:
                        rider_attendance = pd.DataFrame(columns=['_rid', '出勤天'])
                    if best_teams is None:
                        rider_team_counts = df_att.groupby(['_rid', '_tid']).agg(total_orders=('order_count', 'sum')).reset_index()
                        idx = rider_team_counts.groupby('_rid')['total_orders'].idxmax()
                        best_teams = rider_team_counts.loc[idx, ['_rid', '_tid']]
                    # 小象：仅当「跨站合并」开启时，才用申请名单团队映射覆盖 best_teams 主站；关闭时保留各站点独立
                    if is_xiaoxiang and apply_team_map and enable_cross_station_merge and best_teams is not None and not best_teams.empty:
                        _bt_rids = best_teams['_rid'].astype(str).str.replace('.0', '', regex=False).str.strip()
                        _apply_tid = _bt_rids.map(apply_team_map)
                        _mask_bt = _apply_tid.notna()
                        if _mask_bt.any():
                            best_teams.loc[_mask_bt, '_tid'] = _apply_tid[_mask_bt].values
                    attendance_counts = pd.merge(best_teams, rider_attendance, on='_rid', how='left')
                    attendance_counts['出勤天'] = attendance_counts['出勤天'].fillna(0).astype(int)
                
                # 提取所有出现的去重的团队和骑手信息
                df_all = df_att[['_tid', '_rid', 'rname']].drop_duplicates()
                df_sht2 = pd.merge(df_all, attendance_counts, on=['_tid', '_rid'], how='left')
                df_sht2['出勤天数'] = df_sht2['出勤天'].fillna(0).astype(int)
                df_sht2['本期出勤天'] = df_sht2['出勤天数']
                
                try:
                    days_in_month = pd.Timestamp(last_date).days_in_month
                except:
                    days_in_month = 30
                    
                past_attendance_dict, past_attendance_notes, past_month_fee_deducted = extract_past_records(out_folder)

                def get_past_days(row):
                    # 处理逻辑：获取并返回所需的系统状态或计算数据
                    if row.get('出勤天数', 0) == 0:
                        return 0
                    pid = str(row['_rid']).replace('.0', '').strip()
                    return past_attendance_dict.get(pid, 0)
                
                def get_past_notes(row):
                    # 处理逻辑：获取并返回所需的系统状态或计算数据
                    if row.get('出勤天数', 0) == 0:
                        return ""
                    pid = str(row['_rid']).replace('.0', '').strip()
                    notes = past_attendance_notes.get(pid, [])
                    if notes:
                        return "【" + "；".join(notes) + "】"
                    return ""

                def get_past_fee_deducted(row):
                    # 处理逻辑：获取并返回所需的系统状态或计算数据
                    pid = str(row['_rid']).replace('.0', '').strip()
                    return "是" if past_month_fee_deducted.get(pid, False) else "否"
                
                # 小象业务城市不展示往期累计列
                if not is_xiaoxiang:
                    df_sht2['往期累计出勤天'] = df_sht2.apply(get_past_days, axis=1)
                    df_sht2['往期累计核算记录'] = df_sht2.apply(get_past_notes, axis=1)
                    df_sht2['往期月费是否已扣'] = df_sht2.apply(get_past_fee_deducted, axis=1)

                custom_deductions = [str(c) for c in df_rules.columns if c in DEDUCTION_COLS]
                
                cfg_team = next((c for c in df_rules.columns if "团队名称" in str(c) and "maxDays" not in str(c)), None)
                if cfg_team:
                    df_rules_sub = df_rules.copy()
                    df_rules_sub['_cfg_team'] = df_rules_sub[cfg_team].astype(str).str.strip()
                    df_rules_sub = df_rules_sub.drop_duplicates(subset=['_cfg_team'])
                    
                    cols_to_drop = [c for c in custom_deductions if c in df_sht2.columns]
                    if cols_to_drop:
                        df_sht2 = df_sht2.drop(columns=cols_to_drop)
                    
                    overlap = [c for c in df_rules_sub.columns if c in df_sht2.columns and c != '_cfg_team']
                    if overlap:
                        df_rules_sub = df_rules_sub.drop(columns=overlap)

                    def _match_cfg_team(tid):
                        tid_str = re.sub(r'_?新专送', '', str(tid).strip())
                        for c_team in df_rules_sub['_cfg_team']:
                            c_team_clean = re.sub(r'_?新专送', '', str(c_team).strip())
                            if c_team_clean == tid_str:
                                return c_team
                        log(f"Debug2: Match failed for tid='{tid_str}'. Config teams sample: {list(df_rules_sub['_cfg_team'])[:5]}...", "WARN")
                        return str(tid).strip()

                    df_sht2['_mapped_tid'] = df_sht2['_tid'].apply(_match_cfg_team)
                    df_sht2 = pd.merge(df_sht2, df_rules_sub, left_on='_mapped_tid', right_on='_cfg_team', how='left')
                    df_sht2 = df_sht2.drop(columns=['_mapped_tid'])
                
                filtered_custom_deductions = []
                for d_col in custom_deductions:
                    if d_col in DEDUCTION_COLS:
                        if d_col in df_sht2.columns:
                            if pd.to_numeric(df_sht2[d_col], errors='coerce').fillna(0).abs().sum() == 0:
                                df_sht2 = df_sht2.drop(columns=[d_col])
                                continue
                        else:
                            continue
                    filtered_custom_deductions.append(d_col)
                custom_deductions = filtered_custom_deductions

                for d_col in custom_deductions:
                    if d_col not in df_sht2.columns:
                        df_sht2[d_col] = 0
                    df_sht2[d_col] = pd.to_numeric(df_sht2[d_col], errors='coerce').fillna(0)

                def calc_deduction(val, att_days, past_days, max_days, cur_days_in_month=days_in_month):
                    # 处理逻辑：针对按天数/阈值扣款项（如保险费/安全基金、使用费等）执行金额计算
                    if pd.isna(val) or val == 0 or att_days == 0: return 0
                    if pd.isna(max_days) or str(max_days).strip() == "":
                        return att_days * val
                    try:
                        max_d = float(max_days)
                    except (ValueError, TypeError):
                        return att_days * val

                    total_days = att_days + past_days
                    if total_days < max_d:
                        return att_days * val
                    else:
                        if past_days >= max_d:
                            return 0
                        else:
                            # 往期＜阈值 且 当期+往期≥阈值：按整月扣除，需抵消/扣减掉往期已按天扣除的金额
                            return max(0, (cur_days_in_month - past_days) * val)

                for d_col in custom_deductions:
                    max_col = f"{d_col}_maxDays"
                    is_kw_col = f"{d_col}_isKw"
                    
                    if d_col == '月费':
                        def apply_fee_logic(row, d_name=d_col):
                            # 处理逻辑：当出勤天数为0时，月费值需修改为0，因为主站中已扣除，辅站中无需二次扣除
                            if row.get('往期月费是否已扣') == '是':
                                return 0
                            att_d = row.get("出勤天数", row.get("出勤天", row.get("本期出勤天", 0)))
                            try:
                                if pd.isna(att_d) or float(att_d) == 0:
                                    return 0
                            except (ValueError, TypeError):
                                pass
                            return row[d_name]
                        df_sht2[d_col] = df_sht2.apply(apply_fee_logic, axis=1)
                    else:
                        def row_calc(row, item_name, max_name, iskw_name):
                            # 处理逻辑：针对具体业务项（如配送费、奖罚）执行金额计算及条件判定
                            is_kw = row.get(iskw_name, False)
                            if pd.isna(is_kw):
                                is_kw = False
                            else:
                                is_kw = bool(is_kw)
                            val = row[item_name]
                                
                            fixed_amt = 0
                            if not (pd.isna(val) or val == 0):
                                att_d = row.get("出勤天数", row.get("本期出勤天", 0))
                                if abs(val - (-0.5)) < 1e-5:
                                    fixed_amt = att_d * val
                                else:
                                    max_val = row.get(max_name, None)
                                    fixed_amt = calc_deduction(val, att_d, row.get("往期累计出勤天", 0), max_val)
                            
                            r_id = str(row.get('_rid', '')).replace('.0', '').strip()
                            has_kw_hit = r_id in rider_wtd_deductions and item_name in rider_wtd_deductions[r_id]
                            
                            if is_kw:
                                if has_kw_hit:
                                    return rider_wtd_deductions[r_id][item_name]
                                else:
                                    return 0
                            else:
                                return fixed_amt

                        df_sht2[d_col] = df_sht2.apply(lambda row: row_calc(row, d_col, max_col, is_kw_col), axis=1)

                # 小象超市「保险费」表：将配置源列映射为模板展示列（保险费←安全基金、循环物资使用费←非蜂卡、附加险←月费）
                if is_xiaoxiang:
                    for _disp, _src in XIAOXIANG_FEE_DISPLAY_MAP.items():
                        if _src in df_sht2.columns:
                            df_sht2[_disp] = df_sht2[_src]
                    _src_cols = [c for c in XIAOXIANG_FEE_DISPLAY_MAP.values() if c in df_sht2.columns]
                    if _src_cols:
                        df_sht2 = df_sht2.drop(columns=_src_cols)
                    custom_deductions = [c for c in custom_deductions if c not in XIAOXIANG_FEE_DISPLAY_MAP.values()]

                temp_tid = df_sht2['_tid'].copy() if '_tid' in df_sht2.columns else None
                temp_rid = df_sht2['_rid'].copy() if '_rid' in df_sht2.columns else None
                temp_rname = df_sht2['rname'].copy() if 'rname' in df_sht2.columns else None
                
                cols_to_drop = ['_tid', '_rid', '_cfg_team', '出勤天', '团队名称', '骑手ID', '骑手姓名', 'rname']
                df_sht2.drop(columns=[c for c in cols_to_drop if c in df_sht2.columns], inplace=True, errors='ignore')
                df_sht2.drop(columns=[c for c in df_sht2.columns if c.startswith('团队名称_') or c.startswith('骑手ID_') or c.startswith('骑手姓名_')], inplace=True, errors='ignore')
                
                if temp_tid is not None: df_sht2['团队名称'] = temp_tid
                if temp_rid is not None: df_sht2['骑手ID'] = temp_rid
                if temp_rname is not None: df_sht2['骑手姓名'] = temp_rname
                
                base_cols = ["团队名称", "骑手ID", "骑手姓名", "出勤天数"]
                if is_xiaoxiang:
                    # 小象模板在出勤天数后固定展示保险费、循环物资使用费、附加险、招聘来源
                    xiaoxiang_extra_cols = ["保险费", "循环物资使用费", "附加险", "招聘来源"]
                    # 招聘来源按 (团队名称+骑手ID) 从申请名单「入职来源/招聘来源」匹配填充（与配送所得表口径一致）；
                    # 未命中或申请名单留空 → 空单元格，不再整列兜底填 0。
                    _fee_src_map = {}
                    if df_apply is not None and len(df_apply) > 0:
                        _fa_team_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("团队名称", "团队"))), 0)
                        _fa_rid_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("骑手ID", "ID", "id"))), 1)
                        _fa_src_col = next((i for i, c in enumerate(df_apply.columns) if any(k in str(c) for k in ("入职来源", "招聘来源"))), None)
                        if _fa_src_col is not None:
                            for _far in df_apply.itertuples(index=False):
                                try:
                                    _fat = str(_far[_fa_team_col]).strip()
                                    _farid = str(_far[_fa_rid_col]).replace('.0', '').strip()
                                    if _fat and _farid and _farid.lower() not in ('nan', 'none', ''):
                                        _fav = _far[_fa_src_col]
                                        _fav = None if _fav is None or str(_fav).strip() in ('', 'nan', 'None') else str(_fav).strip()
                                        _fee_src_map[(_fat, _farid)] = _fav
                                except Exception:
                                    continue
                    def _fee_source_of(row):
                        _fbt = str(row.get('团队名称', '')).strip()
                        _fbrid = str(row.get('骑手ID', '')).replace('.0', '').strip()
                        return _fee_src_map.get((_fbt, _fbrid))
                    df_sht2['招聘来源'] = df_sht2.apply(_fee_source_of, axis=1)
                    _fee_matched = int(df_sht2['招聘来源'].notna().sum())
                    log(f"-> 🎯 保险费表招聘来源已按申请名单(团队名称+骑手ID)匹配填入 {_fee_matched}/{len(df_sht2)} 行", "INFO")
                    for col in xiaoxiang_extra_cols:
                        if col not in df_sht2.columns:
                            df_sht2[col] = 0
                    # 小象「保险费」表仅输出模板八列：所有配置扣款项已通过映射写入对应展示列，
                    # 不再追加 custom_deductions，避免额外源列(如 非蜂卡/使用费)泄漏成多余列
                    final_cols_sht2 = base_cols + xiaoxiang_extra_cols
                else:
                    final_cols_sht2 = base_cols + custom_deductions
                final_cols_sht2 = list(dict.fromkeys(final_cols_sht2))
                df_sht2 = df_sht2[[c for c in final_cols_sht2 if c in df_sht2.columns]]

                df_sht2.sort_values(by=["团队名称", "骑手ID"], ascending=[True, True], inplace=True)
                
                try:
                    df_sht2["骑手ID"] = pd.to_numeric(df_sht2["骑手ID"])
                except:
                    pass

            # import numpy as np
            df_sht2_obj = df_sht2.astype(object)
            df_sht2_obj[pd.isna(df_sht2_obj)] = None

            data_list = df_sht2_obj.values.tolist()
            
            # Clear old rows in ws_sht2
            try:
                ws_sht2.delete_rows(2, ws_sht2.max_row)
            except:
                pass

            headers_sht2 = list(df_sht2.columns)
            for c_idx, val in enumerate(headers_sht2, 1): ws_sht2.cell(row=1, column=c_idx, value=val)
            for r_idx, row_data_iter in enumerate(data_list, 2):
                for c_idx, val in enumerate(row_data_iter, 1): ws_sht2.cell(row=r_idx, column=c_idx, value=val)

            last_row_sht2 = len(data_list) + 1
            num_riders = last_row_sht2 - 1
            stats_info["riders"] = max(stats_info.get("riders", 0), num_riders)
            log(f"-> 🎯 聚合扫描完成（新逻辑）：侦测到 {num_riders} 个活动实体！", "INFO")

            if last_row_sht2 > 2:
                # import re
                # import copy
                formula_regex = re.compile(r'(?<![a-zA-Z0-9_])(\!?\$??)([a-zA-Z]{1,3})(\!?\$??)([1-9][0-9]{0,6})(?![a-zA-Z0-9_])')
                
                def fast_shift(clean_f, delta):
                    # 处理逻辑：fast_shift 的主要执行逻辑
                    if not clean_f or delta == 0: return clean_f
                    def replacer(match):
                        # 处理逻辑：replacer 的主要执行逻辑
                        c_abs, c, r_abs, r = match.groups()
                        if '$' in r_abs: return match.group(0)
                        return f"{c_abs}{c}{r_abs}{int(r) + delta}"
                    return formula_regex.sub(replacer, clean_f)

                for col_idx in range(4, ws_sht2.max_column + 1):
                    cell_template = ws_sht2.cell(row=2, column=col_idx)
                    if cell_template.value and isinstance(cell_template.value, str) and cell_template.value.startswith('='):
                        clean_f = cell_template.value
                        for row_idx in range(3, last_row_sht2 + 1):
                            target_cell = ws_sht2.cell(row=row_idx, column=col_idx)
                            delta = row_idx - 2
                            try:
                                target_cell.value = fast_shift(clean_f, delta)
                            except Exception:
                                target_cell.value = cell_template.value
                            if cell_template.has_style: target_cell._style = copy.copy(cell_template._style)

            # import copy

            if num_riders > 0:
                # import re
                try:
                    from openpyxl.worksheet.formula import ArrayFormula
                except ImportError:
                    try:
                        from openpyxl.formula.array import ArrayFormula
                    except ImportError:
                        ArrayFormula = None

                m_ranges = list(ws_sht1.merged_cells.ranges)
                for m_range in m_ranges:
                    if m_range.min_row >= 4: ws_sht1.unmerge_cells(m_range.coord)
                    
                # Clear template empty rows up to old max riders - DONT delete so we keep template formatting
                # try:
                #     ws_sht1.delete_rows(5, ws_sht1.max_row - 4)
                # except:
                #     pass

                if num_riders > 1:
                    try:
                        ws_sht1.insert_rows(5, amount=num_riders - 1)
                    except:
                        pass


                max_col_sht1 = ws_sht1.max_column
                template_row_info = []
                from openpyxl.utils import get_column_letter
                for c_idx in range(1, max_col_sht1 + 1):
                    cell = ws_sht1.cell(row=4, column=c_idx)
                    _cell_val = cell.value
                    # ArrayFormula 对象无法被当前公式翻译逻辑处理，且会导致行号不偏移、Excel 提示恢复。
                    # 这里将其转字符串；如果是易碎的 LOOKUP 数组公式，替换为等价的嵌套 IF。
                    if ArrayFormula is not None and isinstance(_cell_val, ArrayFormula):
                        _cell_val = _cell_val.text
                    if isinstance(_cell_val, str) and _cell_val.startswith('=') and \
                       'LOOKUP(9^9,FIND({"SZ","HZ","CZ","ST"},' in _cell_val:
                        # 将 LOOKUP 数组公式替换为等价嵌套 IF（非数组公式，openpyxl 可正确位移）
                        _cell_val = '=IF(ISNUMBER(FIND("SZ",B4)),"深圳",IF(ISNUMBER(FIND("HZ",B4)),"惠州",IF(ISNUMBER(FIND("CZ",B4)),"潮州",IF(ISNUMBER(FIND("ST",B4)),"汕头",""))))'
                    template_row_info.append({
                        'val': _cell_val, 'style': copy.copy(cell._style) if cell.has_style else None,
                        'col_letter': get_column_letter(c_idx)
                    })

                for i in range(num_riders):
                    t_row = i + 4
                    for c_idx, t_item in enumerate(template_row_info, 1):
                        target_cell = ws_sht1.cell(row=t_row, column=c_idx)
                        if t_row > 4 and t_item['style']: target_cell._style = t_item['style']

                        if c_idx in [2, 3, 4]:
                            val_idx = c_idx - 2
                            target_cell.value = ws_sht2.cell(row=i + 2, column=val_idx + 1).value
                        else:
                            formula_val = t_item['val']
                            if isinstance(formula_val, str) and formula_val.startswith('='):
                                clean_f = formula_val.replace("{", "").replace("}", "").strip()
                                delta = t_row - 4
                                try:
                                    translated_f = fast_shift(clean_f, delta)
                                    if (c_idx == 1 or c_idx == 20) and formula_val.startswith("{"):
                                        target_cell.value = ArrayFormula(target_cell.coordinate, translated_f) if ArrayFormula else translated_f
                                    else:
                                        target_cell.value = translated_f
                                except:
                                    target_cell.value = clean_f
                            else:
                                if t_row > 4: target_cell.value = t_item['val']

                f_row = max(5, 4 + num_riders)
                
                try:
                    ws_sht1.merge_cells(start_row=f_row, start_column=1, end_row=f_row, end_column=4)
                    cell_total = ws_sht1.cell(row=f_row, column=1)
                    cell_total.value = "合计"
                    from openpyxl.styles import Alignment
                    cell_total.alignment = Alignment(horizontal='center', vertical='center')
                except Exception:
                    pass
                
                # Removed the block that attempts to format f_row since we are keeping the template's footer row, which is already correctly formatted.
                pass

        try:
            if _resolve_delivery_sheet(wb1) is not None:
                ws_income_target = _resolve_delivery_sheet(wb1)
                remark_col_idx = -1
                leishen_price_col_idx = -1

                for r in range(1, 6):
                    for c in range(1, ws_income_target.max_column + 1):
                        cell_val = str(ws_income_target.cell(row=r, column=c).value or "").strip()
                        if "备注" in cell_val:
                            remark_col_idx = c
                        elif "蓝橙单价" in cell_val:
                            leishen_price_col_idx = c

                noprice_lookup = {f"{k[0]}_{k[1]}": format_dates_streak(v) + "无单价" for k, v in grouped.items()}

                for row in ws_income_target.iter_rows(min_row=4):
                    team_val = str(row[1].value or "").strip()
                    id_val = str(row[2].value or "").replace('.0', '').strip()

                    if team_val or id_val:
                        lookup_key = f"{team_val}_{id_val}"
                        remark_parts = []
                        if lookup_key in noprice_lookup: remark_parts.append(noprice_lookup[lookup_key])

                        if lookup_key in rider_prices_dict:
                            prices_set = rider_prices_dict[lookup_key]
                            if len(prices_set) > 1:
                                multi_price_remarks = []
                                for p, d_list in rider_price_dates_dict[lookup_key].items():
                                    if p == "无单价": continue
                                    streak_str = format_dates_streak(d_list)
                                    multi_price_remarks.append(f"{streak_str}单价{p}元")
                                if multi_price_remarks: remark_parts.append("；".join(multi_price_remarks))

                            if leishen_price_col_idx != -1:
                                # 口径：价格集合含「无单价」（即备注中存在无单价日期段）→ 蓝橙单价一律显示「无单价」；
                                # 仅当全部日期均有单价时才显示单价（单一价格→数值；多价格→";"拼接）
                                if "无单价" in prices_set:
                                    final_leishen_price = "无单价"
                                else:
                                    prices_list = sorted(list(prices_set))
                                    if len(prices_list) == 1:
                                        final_leishen_price = to_numeric_if_possible(prices_list[0])
                                    else:
                                        final_leishen_price = ";".join(prices_list)
                                row[leishen_price_col_idx - 1].value = final_leishen_price

                        if remark_col_idx != -1:
                            if remark_parts:
                                row[remark_col_idx - 1].value = "；".join(remark_parts)
                            else:
                                row[remark_col_idx - 1].value = ""  # 确保清空旧备注

                if remark_col_idx != -1:
                    pass

        except Exception as e:
            log(f"处理动态反写和高级备注合并时遭遇暗流: {e}", "WARN")

        if intercept_records:
            log(">>> 正在合成系统级拦截与安全分析日志...", "SYSTEM")
            ws_intercept = wb1.create_sheet(title="拦截溯源")
            ws_intercept.sheet_properties.tabColor = "FF0000"
            ws_intercept.append(["拦截工作薄名称", "拦截类型", "运单号", "骑手ID", "骑手名称"])
            for rec in intercept_records:
                if len(rec) >= 5:
                    ws_intercept.append([rec[0], rec[1], rec[2], rec[3], rec[4]])
                else:
                    ws_intercept.append([rec[0], rec[1], rec[2], "", ""])

        if daily_intercept_records:
            log(">>> 正在合成日维度单量防重拦截溯源...", "SYSTEM")
            ws_daily_intercept = wb1.create_sheet(title="日维度单量拦截")
            ws_daily_intercept.sheet_properties.tabColor = "FF9900"
            ws_daily_intercept.append(["拦截文件", "日期", "骑手ID", "骑手姓名", "所属站点", "配送完成单量"])
            for rec in daily_intercept_records:
                ws_daily_intercept.append(list(rec))

        log(">>> 即将执行 GC (垃圾回收) 释放缓存页资源...", "SYSTEM")
        progress_callback(0.90, "执行内存碎片回收与冗余空闲清退...")
        from openpyxl.utils import get_column_letter
        for ws in wb1.worksheets:
            if ws.title == "基础配送费":
                for col_idx in range(1, ws.max_column + 1):
                    ws.column_dimensions[get_column_letter(col_idx)].hidden = False
                continue
            for col_idx in range(ws.max_column, 0, -1):
                col_val = str(ws.cell(row=1, column=col_idx).value or "")
                if col_val.startswith("Temp_Col_"):
                    ws.column_dimensions[get_column_letter(col_idx)].hidden = True
                elif not (ws.title == "基础配送费" or _is_delivery_sheet(ws.title)) and col_val in ["捡货补贴", "国补采集补贴", "国补机收补贴", "主站大网", "开放大网指派"]:
                    ws.column_dimensions[get_column_letter(col_idx)].hidden = True

        for ws in wb1.worksheets:
            is_apply_sheet = (ws.title == "申请名单")
            if is_apply_sheet or ws.title != "配送所得表":
                ws.freeze_panes = 'A2'

        ws_income = _resolve_delivery_sheet(wb1)

        date_str = f"{first_date.strftime('%m.%d')}-{last_date.strftime('%m.%d')}"
        opt_str = str(selected_option).replace(' 00:00:00', '')
        file_prefix_base = f"{city}{date_str}{opt_str}兼职"
            
        import re
        file_prefix_base = re.sub(r'[\\/:*?"<>|\r\n]', '-', file_prefix_base)
        
        now_date_str = datetime.now().strftime('%m%d')
        file_prefix = f"{file_prefix_base}{now_date_str}"

        ws_income["A1"] = file_prefix

        for i, ws in enumerate(wb1.worksheets):
            try:
                if hasattr(ws, 'sheet_view'):
                    ws.sheet_view.tabSelected = (i == 0)
                elif hasattr(ws, 'views') and getattr(ws.views, 'sheetView', None):
                    ws.views.sheetView[0].tabSelected = (i == 0)
            except Exception:
                pass

        wb1.active = 0

        # 小象「配送所得表」收款人身份证号码 / 收款人手机号码 / 商翼绑定 三列联动填充
        # 【位置说明】本块须在「发薪工具未绑名单」生成之前执行：未绑名单直接读取本块填充后的
        # 「商翼绑定」列做筛选，故从原 wb1.save 前移至收尾段之前。
        # ① 收款人身份证/手机：按 申请名单表 (骑手ID 优先，关键字身份证/手机回退) 匹配填入；
        #    首选 配送所得表已有值（不覆盖），次选 申请名单表 身份证号/电话号。
        # ② 商翼绑定：按 骑手支付绑定.状态，用 身份证号 = 配送所得表.收款人身份证号码 匹配填入。
        try:
            if is_xiaoxiang:
                _ws_inc4 = _resolve_delivery_sheet(wb1)
                if _ws_inc4 is not None and df_apply is not None:
                    def _norm_id(v):
                        if v is None:
                            return ""
                        s = str(v).strip().strip("'\"").strip().upper()
                        # 兼容 Excel 数字串被读成浮点(如 311629.0) 与文本型(311629) 不一致
                        if s.endswith(".0"):
                            s = s[:-2]
                        return s

                    # ---- 申请名单: 骑手ID / 身份证号 / 电话号 索引与映射 ----
                    _a_rid = get_col_idx(df_apply, ["骑手ID", "ID", "id"], 1)
                    _a_idc = get_col_idx(df_apply, ["身份证号", "身份证", "证件号码", "证件"], -1)
                    _a_ph = get_col_idx(df_apply, ["电话号", "手机号", "手机", "联系电话", "电话"], -1)
                    _apply_by_rid = {}
                    _apply_by_idc = {}
                    _apply_by_ph = {}
                    if _a_idc >= 0 or _a_ph >= 0:
                        for _ar in df_apply.itertuples(index=False):
                            _rid = _norm_id(_ar[_a_rid])
                            _idc = _norm_id(_ar[_a_idc]) if _a_idc >= 0 else ""
                            _ph = _norm_id(_ar[_a_ph]) if _a_ph >= 0 else ""
                            if not (_idc or _ph):
                                continue
                            _rec = (_idc, _ph)
                            if _rid:
                                _apply_by_rid[_rid] = _rec
                            if _idc:
                                _apply_by_idc[_idc] = _rec
                            if _ph:
                                _apply_by_ph[_ph] = _rec

                    # ---- 骑手支付绑定: 身份证号 -> 状态 ----
                    _bind_status = {}
                    if "骑手支付绑定" in wb1.sheetnames:
                        _ws_bind = wb1["骑手支付绑定"]
                        _b_idc = _b_st = -1
                        for _c in range(1, min(20, _ws_bind.max_column + 1)):
                            _h = str(_ws_bind.cell(row=1, column=_c).value or "").strip().lower()
                            if "身份证" in _h and _b_idc == -1:
                                _b_idc = _c
                            elif ("状态" in _h or "绑定" in _h) and _b_st == -1:
                                _b_st = _c
                        if _b_idc != -1 and _b_st != -1:
                            for _r in range(2, _ws_bind.max_row + 1):
                                _idc = _norm_id(_ws_bind.cell(row=_r, column=_b_idc).value)
                                _st = str(_ws_bind.cell(row=_r, column=_b_st).value or "").strip()
                                if _idc and _idc not in _bind_status:
                                    _bind_status[_idc] = _st

                    # ---- 定位配送所得表目标列(row3 精确列名优先, 回退 row1~3 子串匹配, 最后按列号) ----
                    _c_idc = _c_ph = _c_bind = None
                    for _c in range(1, _ws_inc4.max_column + 1):
                        _h = str(_ws_inc4.cell(row=3, column=_c).value or "").strip()
                        if _h == "收款人身份证号码":
                            _c_idc = _c
                        elif _h == "收款人手机号码":
                            _c_ph = _c
                        elif _h == "商翼绑定":
                            _c_bind = _c
                    if _c_idc is None:
                        _c_idc = _find_header_col(_ws_inc4, ["收款人身份证号码", "收款人身份证"]) or 40
                    if _c_ph is None:
                        _c_ph = _find_header_col(_ws_inc4, ["收款人手机号码", "收款人手机"]) or 41
                    if _c_bind is None:
                        _c_bind = _find_header_col(_ws_inc4, ["商翼绑定"]) or 42

                    # ---- 逐行填充 ----
                    _n_id = _n_ph = _n_bind = 0
                    for _r in range(4, _ws_inc4.max_row + 1):
                        _rid = _norm_id(_ws_inc4.cell(row=_r, column=3).value)
                        _e_idc_raw = _ws_inc4.cell(row=_r, column=_c_idc).value
                        _e_ph_raw = _ws_inc4.cell(row=_r, column=_c_ph).value
                        _e_idc = _norm_id(_e_idc_raw)
                        _e_ph = _norm_id(_e_ph_raw)
                        # 模板列可能预置 XLOOKUP 公式(非人工录入值)，按空处理，改用申请名单静态填充
                        if isinstance(_e_idc_raw, str) and _e_idc_raw.startswith("="):
                            _e_idc = ""
                        if isinstance(_e_ph_raw, str) and _e_ph_raw.startswith("="):
                            _e_ph = ""

                        # 解析申请名单记录: 先 骑手ID 精确匹配；否则 关键字(身份证/手机) 回退
                        _rec = _apply_by_rid.get(_rid)
                        if _rec is None:
                            for _cand in (_e_idc, _e_ph):
                                if _cand:
                                    _m = _apply_by_idc.get(_cand) or _apply_by_ph.get(_cand)
                                    if _m:
                                        _rec = _m
                                        break
                        if _rec is None and _e_idc and len(_e_idc) >= 15:
                            for _k, _m in _apply_by_idc.items():
                                if len(_k) >= 15 and (_k in _e_idc or _e_idc in _k):
                                    _rec = _m
                                    break

                        # 首选 配送所得表已有值(非公式的人工录入), 次选 申请名单
                        _new_idc = _e_idc or (_rec[0] if _rec else "")
                        _new_ph = _e_ph or (_rec[1] if _rec else "")

                        if _new_idc != _e_idc:
                            _ws_inc4.cell(row=_r, column=_c_idc).value = _new_idc
                            _n_id += 1
                        if _new_ph != _e_ph:
                            _ws_inc4.cell(row=_r, column=_c_ph).value = _new_ph
                            _n_ph += 1

                        # 商翼绑定: 骑手支付绑定.状态, 按 身份证号 匹配；未匹配到(含无身份证号)则填 "未绑定"
                        # 仅处理有效数据行(有 骑手ID/身份证/手机 任一)，跳过空白行以免污染表格
                        if _c_bind is not None and (_rid or _new_idc or _new_ph):
                            _st = _bind_status.get(_new_idc, "") if _new_idc else ""
                            _new_bind = _st if _st else "未绑定"
                            _cur = str(_ws_inc4.cell(row=_r, column=_c_bind).value or "").strip()
                            if _cur != _new_bind:
                                _ws_inc4.cell(row=_r, column=_c_bind).value = _new_bind
                                _n_bind += 1
                    log(f">>> 📌 配送所得表 收款人身份证={_n_id} 手机={_n_ph} 行已按申请名单(骑手ID/关键字)填充；商翼绑定={_n_bind} 行已按骑手支付绑定(状态)填充(未匹配填'未绑定')", "INFO")
        except Exception as e:
            log(f"收款人身份证/手机/商翼绑定匹配失败(不影响其余功能): {e}", "WARN")

        # =========================================================
        # 收尾：剥离专属表格，分别保存
        # =========================================================
        wb_special = openpyxl.Workbook()
        ws_default = wb_special.active
        has_special_data = False

        if "蓝橙无单价明细" in wb1.sheetnames:
            log(">>> 剥离失效状态流，启动安全隔离封存...", "SYSTEM")
            ws_noprice_old = wb1["蓝橙无单价明细"]
            ws_special_1 = ws_default
            ws_special_1.title = "蓝橙无单价明细"
            ws_special_1.sheet_properties.tabColor = "FF9900"
            has_special_data = True

            for row_idx, row in enumerate(ws_noprice_old.iter_rows(values_only=True), 1):
                new_row = list(row)
                if row_idx != 1 and len(new_row) >= 2:
                    val_str = str(new_row[1] or "").strip()
                    if val_str.isdigit(): new_row[1] = int(val_str)
                ws_special_1.append(new_row)

            for col_letter, col_dim in ws_noprice_old.column_dimensions.items(): ws_special_1.column_dimensions[
                col_letter].width = col_dim.width
            ws_special_1.freeze_panes = 'A2'
            del wb1["蓝橙无单价明细"]

        unbound_records = []
        if is_xiaoxiang:
            # 小象口径：直接取「配送所得表」商翼绑定列（上文三列联动块已填充），
            # 筛商翼绑定值不含「已签约」的行入未绑名单；绑定情况列=商翼绑定列实际值。
            _ws_ub = _resolve_delivery_sheet(wb1)
            _ub_col = None
            if _ws_ub is not None:
                for _c in range(1, _ws_ub.max_column + 1):
                    if str(_ws_ub.cell(row=3, column=_c).value or "").strip() == "商翼绑定":
                        _ub_col = _c
                        break
                if _ub_col is None:
                    _ub_col = _find_header_col(_ws_ub, ["商翼绑定"])
            if _ub_col is not None:
                for _r in range(4, _ws_ub.max_row + 1):
                    _ub_team = str(_ws_ub.cell(row=_r, column=2).value or "").strip()
                    _ub_id = str(_ws_ub.cell(row=_r, column=3).value or "").replace('.0', '').strip()
                    _ub_name = str(_ws_ub.cell(row=_r, column=4).value or "").strip()
                    _ub_status = str(_ws_ub.cell(row=_r, column=_ub_col).value or "").strip()
                    if not _ub_id:
                        continue
                    if "已签约" not in _ub_status:
                        unbound_records.append([_ub_team, _ub_id, _ub_name, _ub_status or "未绑定"])
            else:
                log("⚠ 配送所得表未定位到「商翼绑定」列，发薪工具未绑名单输出为空", "WARN")
        else:
            # 非小象口径（保留原逻辑）：安全基金表 比对 骑手支付绑定名单
            fund_sheet_name = "安全基金"
            if fund_sheet_name in wb1.sheetnames and "骑手支付绑定" in wb1.sheetnames:
                ws_fund = wb1[fund_sheet_name]
                ws_bind = wb1["骑手支付绑定"]

                b_team_col, b_id_col, b_name_col, b_status_col = 2, 3, 4, 9
                for c in range(1, min(20, ws_bind.max_column + 1)):
                    h_val = str(ws_bind.cell(row=1, column=c).value or "").strip()
                    if "团队名称" in h_val:
                        b_team_col = c
                    elif "id" in h_val.lower() or "编号" in h_val:
                        b_id_col = c
                    elif "姓名" in h_val or "名称" in h_val:
                        b_name_col = c
                    elif "绑" in h_val or "状态" in h_val:
                        b_status_col = c

                bind_map = {}
                for row in ws_bind.iter_rows(min_row=2, max_col=max(b_team_col, b_id_col, b_name_col, b_status_col), values_only=True):
                    b_id = str(row[b_id_col-1] or "").replace('.0', '').strip()
                    if b_id:
                        b_team = str(row[b_team_col-1] or "").strip()
                        b_name = str(row[b_name_col-1] or "").strip()
                        b_status = str(row[b_status_col-1] or "").replace(" ", "").strip()
                        bind_map[b_id] = [b_team, b_id, b_name, b_status]

                for row in ws_fund.iter_rows(min_row=2, max_col=3, values_only=True):
                    f_team = str(row[0] or "").strip()
                    f_id = str(row[1] or "").replace('.0', '').strip()
                    f_name = str(row[2] or "").strip()

                    if f_id:
                        if f_id in bind_map:
                            match_data = bind_map[f_id]
                            status_val = match_data[3]
                            if "未" in status_val or "否" in status_val or "失败" in status_val or status_val == "": unbound_records.append(
                                match_data)
                        else:
                            unbound_records.append([f_team, f_id, f_name, "不在支付绑定名单中"])

        log(f">>> 全局鉴权拦截完毕，共计隔离 {len(unbound_records)} 个未注册非活跃凭证！", "SYSTEM")

        if has_special_data:
            ws_special_2 = wb_special.create_sheet("发薪工具未绑名单")
        else:
            ws_special_2 = ws_default
            has_special_data = True

        ws_special_2.title = "发薪工具未绑名单"
        ws_special_2.sheet_properties.tabColor = "FF0000"

        write_row = 1
        headers_special2 = ["团队名称", "骑手ID", "骑手姓名", "绑定情况"]
        for c_idx, val in enumerate(headers_special2, 1): ws_special_2.cell(row=write_row, column=c_idx, value=val)
        for rec in unbound_records:
            new_rec = list(rec)
            if len(new_rec) >= 2:
                val_str = str(new_rec[1]).strip()
                if val_str.isdigit():
                    new_rec[1] = int(val_str)
            ws_special_2.append(new_rec)

        ws_special_2.freeze_panes = 'A2'

        task_name = kwargs.get('task_name', '')
        # Get file prefix early or construct it here
        date_str = f"{first_date.strftime('%m.%d')}-{last_date.strftime('%m.%d')}"
        opt_str = str(selected_option).replace(' 00:00:00', '')
        file_prefix_base = f"{city}{date_str}{opt_str}兼职"
        import re
        file_prefix_base = re.sub(r'[\\/:*?"<>|\r\n]', '-', file_prefix_base)

        now_date_str = datetime.now().strftime('%m%d')
        file_prefix = f"{file_prefix_base}{now_date_str}"

        if has_special_data:
            if "Sheet" in wb_special.sheetnames and len(wb_special.sheetnames) > 1: del wb_special["Sheet"]
            # 蓝橙无单价&未绑名单工作簿 全局样式：微软雅黑10号、居中；表头淡橙(F8CBAD，与主簿一致)；
            # 首行冻结；列宽按内容自适应（中文 2.15 权重，上限 55）
            from openpyxl.styles import Font as _SpFont, Alignment as _SpAlign, PatternFill as _SpFill
            from openpyxl.utils import get_column_letter as _SpGCL
            _sp_font = _SpFont(name='微软雅黑', size=10)
            _sp_align = _SpAlign(horizontal='center', vertical='center')
            _sp_hfill = _SpFill(start_color="F8CBAD", end_color="F8CBAD", fill_type="solid")
            for _sp_ws in wb_special.worksheets:
                _sp_ws.freeze_panes = 'A2'
                for _sp_row in _sp_ws.iter_rows():
                    for _sp_cell in _sp_row:
                        _sp_cell.font = _sp_font
                        _sp_cell.alignment = _sp_align
                for _sp_cell in _sp_ws[1]:
                    if _sp_cell.value is not None:
                        _sp_cell.fill = _sp_hfill
                for _sp_c in range(1, _sp_ws.max_column + 1):
                    _sp_max = 0
                    for _sp_r in range(1, min(_sp_ws.max_row, 5000) + 1):
                        _sp_v = _sp_ws.cell(row=_sp_r, column=_sp_c).value
                        if _sp_v is not None:
                            for _sp_ln in str(_sp_v).split('\n'):
                                _sp_w = sum(2.15 if ord(ch) > 255 else 1.1 for ch in _sp_ln)
                                if _sp_w > _sp_max:
                                    _sp_max = _sp_w
                    _sp_wadj = min(_sp_max + 2.5, 55)
                    if _sp_wadj > 2:
                        _sp_ws.column_dimensions[_SpGCL(_sp_c)].width = _sp_wadj
            special_save_name = f"{file_prefix_base}_蓝橙无单价&未绑名单{now_date_str}.xlsx"
            special_save_path = os.path.join(out_folder, special_save_name)
            wb_special.save(special_save_path)

        save_name = f"{file_prefix}.xlsx"
        final_save_path = os.path.join(out_folder, save_name)

        progress_callback(0.97, "正在应用视觉排版美化与全局样式修正...")
        try:
            from openpyxl.styles import Alignment
            from openpyxl.utils import get_column_letter

            exclude_format_sheets = ["配送所得表", "配送所得"]
            center_alignment = Alignment(horizontal='center', vertical='center')
            from openpyxl.styles import PatternFill
            header_fill = PatternFill(start_color="F8CBAD", end_color="F8CBAD", fill_type="solid")

            for sheet_name in wb1.sheetnames:
                sheet = wb1[sheet_name]
                if sheet_name not in ("配送所得表", "配送所得"):
                    for cell in sheet[1]:
                        if cell.value is not None:
                            cell.fill = header_fill

                if sheet_name not in exclude_format_sheets and (not _is_delivery_sheet(sheet_name) or (is_xiaoxiang and sheet_name.startswith("配送单"))):
                    ws_to_format = wb1[sheet_name]
                    
                    # 避免对行数过多的表执行过于耗时的宽度计算
                    max_scan_rows = 5000 
                    
                    # 遍历并设置所有非空单元格居中
                    for row in ws_to_format.iter_rows():
                        for cell in row:
                            if cell.value is not None:
                                cell.alignment = center_alignment
                                
                    # 自适应列宽（小象超市业务城市默认取消所有子表自动调整列宽，保留模板默认列宽；
                    # 但「蓝橙单价报备」为程序生成表，需按内容自动适配列宽）
                    if (not is_xiaoxiang) or (sheet_name == "蓝橙单价报备"):
                        for col_idx in range(1, ws_to_format.max_column + 1):
                            max_length = 0
                            col_letter = get_column_letter(col_idx)
                            for r_idx in range(1, min(ws_to_format.max_row, max_scan_rows) + 1):
                                cell_val = ws_to_format.cell(row=r_idx, column=col_idx).value
                                if cell_val is not None:
                                    try:
                                        cell_str = str(cell_val)
                                        # 处理包含换行的情况，按最长的一行计算宽度
                                        lines = cell_str.split('\n')
                                        for line in lines:
                                            # 中文或全角字符给予2.15倍的权重，普通字符给予1.1倍的权重
                                            line_len = sum(2.15 if ord(c) > 255 else 1.1 for c in line)
                                            if line_len > max_length:
                                                max_length = line_len
                                    except:
                                        val_len = len(str(cell_val))
                                        if val_len > max_length:
                                            max_length = val_len
                            adjusted_width = min(max_length + 2.5, 55)  # 最大宽度限制适度放大，预留边距
                            if adjusted_width > 2:
                                ws_to_format.column_dimensions[col_letter].width = adjusted_width
            
            # 全局移除科学计数法: 确保长数值以常规数值格式显示
            for sheet in wb1.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, (int, float)) and cell.value >= 1e10:
                            cell.number_format = '0'

            log(">>> ✨ 排版美化完成：已自动应用全局居中与列宽适配", "SUCCESS")
        except Exception as e:
            log(f"排版美化过程发生错误: {str(e)}", "WARN")

        if is_xiaoxiang and "日单量" in wb1.sheetnames:
            del wb1["日单量"]

        progress_callback(0.98, "数据沙盒封装成功并对齐校验，安全下盘磁盘文件...")
        # 强制工作簿为自动计算 + 打开时完整重算，避免用户本机 Excel 处于手动计算模式时
        # 公式结果不显示、需按 F9 才刷新的问题。
        wb1.calculation.calcMode = "auto"
        wb1.calculation.fullCalcOnLoad = True

        # 小象「配送所得表」A列(业务城市)改为静态计算值：按 B列(站点名称)中的城市编码
        # 预计算出城市文本并直接写入，彻底摆脱对 Excel 自动计算的依赖。
        # 原因：部分用户本机 Excel 处于「手动计算」模式，即使文件已设 fullCalcOnLoad，
        # 个别 Excel 版本打开时仍不重算该列，需手动按 F9 才显示。静态化后打开即显示。
        try:
            _ws_inc = _resolve_delivery_sheet(wb1)
            if _ws_inc is not None:
                def _city_of(site):
                    if not site:
                        return ""
                    s = str(site)
                    for _code, _name in (("SZ", "深圳"), ("HZ", "惠州"), ("CZ", "潮州"), ("ST", "汕头")):
                        if _code in s:
                            return _name
                    return ""
                _maxr = _ws_inc.max_row
                for _r in range(4, _maxr + 1):
                    _ws_inc.cell(row=_r, column=1).value = _city_of(_ws_inc.cell(row=_r, column=2).value)
                log(">>> 📌 配送所得表业务城市(A列)已按站点名称静态计算写入，打开即显示，无需F9", "INFO")
        except Exception as e:
            log(f"业务城市静态化失败(不影响其余功能): {e}", "WARN")

        # 小象「配送所得表」薪资方案列(AI) 按 申请名单表 的 (团队名称+骑手ID) 匹配填入。
        # 匹配键：配送所得表 B列(团队名称)+C列(骑手ID) ↔ 申请名单 团队名称+骑手ID
        # 仅覆盖命中行；未命中行保留其原有值（模板默认/手工值），不破坏现有数据。
        try:
            if is_xiaoxiang and df_apply is not None and '薪资方案' in list(df_apply.columns):
                _ws_inc2 = _resolve_delivery_sheet(wb1)
                if _ws_inc2 is not None:
                    _a_team_col = get_col_idx(df_apply, ["团队名称", "团队"], 0)
                    _a_rid_col = get_col_idx(df_apply, ["骑手ID", "ID", "id"], 1)
                    _a_sal_col = get_col_idx(df_apply, ["薪资方案"], None)
                    _apply_sal_map = {}
                    if _a_sal_col is not None:
                        for _ar in df_apply.itertuples(index=False):
                            try:
                                _at = str(_ar[_a_team_col]).strip()
                                _arid = str(_ar[_a_rid_col]).replace('.0', '').strip()
                                _asal = _ar[_a_sal_col]
                                if _at and _arid and _arid.lower() not in ('nan', 'none', ''):
                                    _apply_sal_map[(_at, _arid)] = _asal
                            except Exception:
                                continue
                        # 在配送所得表表头(兼容 row2 月份前缀 / row3 纯列名)定位薪资方案列
                        _sal_col_idx = _find_header_col(_ws_inc2, ["薪资方案"])
                        if _sal_col_idx is not None:
                            _m_cnt = 0
                            for _r in range(4, _ws_inc2.max_row + 1):
                                _bt = str(_ws_inc2.cell(row=_r, column=2).value or '').strip()
                                _brid = str(_ws_inc2.cell(row=_r, column=3).value or '').replace('.0', '').strip()
                                if (_bt, _brid) in _apply_sal_map:
                                    _val = _apply_sal_map[(_bt, _brid)]
                                    try:
                                        if _val is not None and str(_val).strip() not in ('', 'nan', 'None'):
                                            _val = float(_val)
                                            if _val == int(_val):
                                                _val = int(_val)
                                    except Exception:
                                        pass
                                    _ws_inc2.cell(row=_r, column=_sal_col_idx).value = _val
                                    _m_cnt += 1
                            log(f">>> 📌 配送所得表薪资方案(AI列)已按申请名单(团队名称+骑手ID)匹配填入 {_m_cnt} 行", "INFO")
        except Exception as e:
            log(f"薪资方案匹配失败(不影响其余功能): {e}", "WARN")

        # 小象「配送所得表」薪资方案解析：含 '+' 的拆分为「基础价+雇佣兵单价」
        #   例 '6.5+0.5' -> 薪资方案=7(数值), 雇佣兵单价=0.5(数值)
        #   例 '7+2'     -> 薪资方案=9(数值), 雇佣兵单价=2(数值)
        #   无 '+' 的行 -> 雇佣兵单价=0（数值）
        # 说明：薪资方案列参与「配送所得」公式、雇佣兵单价列参与「蛇头管理费」公式，
        #       原先 '6+0.5' 这类文本会导致公式返回 #VALUE!，解析为数值后方可正常计算。
        try:
            if is_xiaoxiang:
                _ws_sal = _resolve_delivery_sheet(wb1)
                if _ws_sal is not None:
                    _sal_idx = _find_header_col(_ws_sal, ["薪资方案"])
                    _hyb_idx = _find_header_col(_ws_sal, ["雇佣兵单价"])
                    if _sal_idx is not None and _hyb_idx is not None:
                        _n_parse = 0
                        for _r in range(4, _ws_sal.max_row + 1):
                            _v = _ws_sal.cell(row=_r, column=_sal_idx).value
                            _new_sal, _hyb = _parse_salary_cell(_v)
                            if _new_sal != _v:
                                _ws_sal.cell(row=_r, column=_sal_idx).value = _new_sal
                                _n_parse += 1
                            if _ws_sal.cell(row=_r, column=_hyb_idx).value != _hyb:
                                _ws_sal.cell(row=_r, column=_hyb_idx).value = _hyb
                        log(f">>> 📌 配送所得表薪资方案已解析拆分：{_n_parse} 行写入合计值，雇佣兵单价已按规则填充", "INFO")
        except Exception as e:
            log(f"薪资方案解析拆分失败(不影响其余功能): {e}", "WARN")

        # 小象「配送所得表」服务费率列 按 申请名单表 的 骑手ID 匹配填入。
        # 匹配键：配送所得表 C列(骑手ID) ↔ 申请名单 骑手ID/ID/id
        # 仅覆盖命中行；未命中行保留其原有值（模板默认/手工值），不破坏现有数据。
        try:
            if is_xiaoxiang and df_apply is not None and '服务费率' in list(df_apply.columns):
                _ws_inc4 = _resolve_delivery_sheet(wb1)
                if _ws_inc4 is not None:
                    _a_rid_col = get_col_idx(df_apply, ["骑手ID", "ID", "id"], 1)
                    _a_svc_col = get_col_idx(df_apply, ["服务费率"], None)
                    _apply_svc_map = {}
                    if _a_svc_col is not None:
                        for _ar in df_apply.itertuples(index=False):
                            try:
                                _arid = str(_ar[_a_rid_col]).replace('.0', '').strip()
                                _asvc = _ar[_a_svc_col]
                                if _arid and _arid.lower() not in ('nan', 'none', ''):
                                    _apply_svc_map[_arid] = _asvc
                            except Exception:
                                continue
                        # 在配送所得表表头(兼容 row2 月份前缀 / row3 纯列名)定位服务费率列
                        _svc_col_idx = _find_header_col(_ws_inc4, ["服务费率"])
                        if _svc_col_idx is not None:
                            _m_cnt = 0
                            for _r in range(4, _ws_inc4.max_row + 1):
                                _brid = str(_ws_inc4.cell(row=_r, column=3).value or '').replace('.0', '').strip()
                                if _brid in _apply_svc_map:
                                    _val = _apply_svc_map[_brid]
                                    try:
                                        if _val is not None and str(_val).strip() not in ('', 'nan', 'None'):
                                            _val = float(_val)
                                            if _val == int(_val):
                                                _val = int(_val)
                                    except Exception:
                                        pass
                                    _ws_inc4.cell(row=_r, column=_svc_col_idx).value = _val
                                    _m_cnt += 1
                            log(f">>> 📌 配送所得表服务费率列已按申请名单(骑手ID)匹配填入 {_m_cnt} 行", "INFO")
        except Exception as e:
            log(f"服务费率匹配失败(不影响其余功能): {e}", "WARN")

        # 小象「配送所得表」招聘来源/入职来源列 按 申请名单表 的 (团队名称+骑手ID) 匹配填入。
        # 申请名单表侧列名兼容：入职来源 / 招聘来源；配送所得表侧表头(row3)兼容：入职来源 / 招聘来源。
        # 匹配键：配送所得表 B列(团队名称)+C列(骑手ID) ↔ 申请名单 团队名称+骑手ID
        # 仅覆盖命中行；未命中行保留其原有值（模板默认/手工值），不破坏现有数据。
        try:
            if is_xiaoxiang and df_apply is not None and any(_k in list(df_apply.columns) for _k in ('入职来源', '招聘来源')):
                _ws_inc3 = _resolve_delivery_sheet(wb1)
                if _ws_inc3 is not None:
                    _a_team_col = get_col_idx(df_apply, ["团队名称", "团队"], 0)
                    _a_rid_col = get_col_idx(df_apply, ["骑手ID", "ID", "id"], 1)
                    _a_src_col = get_col_idx(df_apply, ["入职来源", "招聘来源"], None)
                    if _a_src_col is not None:
                        _apply_src_map = {}
                        for _ar in df_apply.itertuples(index=False):
                            try:
                                _at = str(_ar[_a_team_col]).strip()
                                _arid = str(_ar[_a_rid_col]).replace('.0', '').strip()
                                _asrc = _ar[_a_src_col]
                                if _at and _arid and _arid.lower() not in ('nan', 'none', ''):
                                    _apply_src_map[(_at, _arid)] = _asrc
                            except Exception:
                                continue
                        _src_col_idx = None
                        for _c in range(1, _ws_inc3.max_column + 1):
                            _hv = str(_ws_inc3.cell(row=3, column=_c).value or '').strip()
                            if _hv in ('入职来源', '招聘来源'):
                                _src_col_idx = _c
                                break
                        if _src_col_idx is not None:
                            _m_cnt = 0
                            for _r in range(4, _ws_inc3.max_row + 1):
                                _bt = str(_ws_inc3.cell(row=_r, column=2).value or '').strip()
                                _brid = str(_ws_inc3.cell(row=_r, column=3).value or '').replace('.0', '').strip()
                                if (_bt, _brid) in _apply_src_map:
                                    _val = _apply_src_map[(_bt, _brid)]
                                    if _val is None or str(_val).strip() in ('', 'nan', 'None'):
                                        _val = ''
                                    _ws_inc3.cell(row=_r, column=_src_col_idx).value = _val
                                    _m_cnt += 1
                            log(f">>> 📌 配送所得表招聘来源列已按申请名单(团队名称+骑手ID)匹配填入 {_m_cnt} 行", "INFO")
                        else:
                            log(">>> ⚠️ 配送所得表未找到 入职来源/招聘来源 列，招聘来源匹配跳过", "WARN")
            elif is_xiaoxiang:
                log(">>> ⚠️ 申请名单表未找到 入职来源/招聘来源 列，招聘来源匹配跳过（请在申请名单表补充该列）", "WARN")
        except Exception as e:
            log(f"招聘来源匹配失败(不影响其余功能): {e}", "WARN")

        # 小象「管理费」表：将配送所得表 团队名称/骑手ID/骑手姓名/入职来源(招聘来源) 按顺序静态复制到对应列。
        # 替代原 =保险费!A2 行引用公式与 =XLOOKUP 招聘来源公式，保证管理费表人员清单与配送所得表同序一致；
        # 复制后清空管理费表左侧区域(A~J)剩余旧公式行，避免残留保险费表错位数据（不整行删除，保护 M~T 列蛇头档案区）。
        try:
            if is_xiaoxiang and "管理费" in wb1.sheetnames:
                _ws_mg = wb1["管理费"]
                _ws_ps = _resolve_delivery_sheet(wb1)
                if _ws_ps is not None:
                    # 配送所得表侧：入职来源/招聘来源 列定位(row3 精确 -> row1~3 子串回退)
                    _ps_src = None
                    for _c in range(1, _ws_ps.max_column + 1):
                        if str(_ws_ps.cell(row=3, column=_c).value or "").strip() in ("入职来源", "招聘来源"):
                            _ps_src = _c
                            break
                    if _ps_src is None:
                        _ps_src = _find_header_col(_ws_ps, ["入职来源", "招聘来源"])
                    # 管理费表侧：目标 A/B/C 固定；入职来源对应列按 row1 表头定位，兜底第10列(J)
                    _mg_src = None
                    for _c in range(1, _ws_mg.max_column + 1):
                        if str(_ws_mg.cell(row=1, column=_c).value or "").strip() in ("入职来源", "招聘来源"):
                            _mg_src = _c
                            break
                    if _mg_src is None:
                        _mg_src = 10
                    from openpyxl.formula.translate import Translator as _MgTr
                    _n_mg = 0
                    _mg_row = 2
                    for _r in range(4, _ws_ps.max_row + 1):
                        _mg_id = str(_ws_ps.cell(row=_r, column=3).value or "").replace('.0', '').strip()
                        if not _mg_id:
                            continue
                        _ws_mg.cell(row=_mg_row, column=1).value = str(_ws_ps.cell(row=_r, column=2).value or "").strip()
                        _ws_mg.cell(row=_mg_row, column=2).value = int(_mg_id) if _mg_id.isdigit() else _mg_id
                        _ws_mg.cell(row=_mg_row, column=3).value = str(_ws_ps.cell(row=_r, column=4).value or "").strip()
                        _ws_mg.cell(row=_mg_row, column=_mg_src).value = (str(_ws_ps.cell(row=_r, column=_ps_src).value or "").strip() if _ps_src else "")
                        # D~I 列取数公式逐行补齐：超级表「计算列自动填充」对 openpyxl 写入不生效，
                        # 模板(表1 仅 A1:J2)只有 row2 有公式，须按行显式平移写入
                        for _cc in range(4, 10):
                            _cur = _ws_mg.cell(row=_mg_row, column=_cc).value
                            if isinstance(_cur, str) and _cur.startswith("="):
                                continue
                            _fsrc = _ws_mg.cell(row=2, column=_cc).value
                            _forg = 2
                            if not (isinstance(_fsrc, str) and _fsrc.startswith("=")):
                                _fsrc = _ws_mg.cell(row=_mg_row - 1, column=_cc).value
                                _forg = _mg_row - 1
                            if isinstance(_fsrc, str) and _fsrc.startswith("="):
                                _ws_mg.cell(row=_mg_row, column=_cc).value = _MgTr(
                                    _fsrc, origin=_ws_mg.cell(row=_forg, column=_cc).coordinate
                                ).translate_formula(_ws_mg.cell(row=_mg_row, column=_cc).coordinate)
                        _mg_row += 1
                        _n_mg += 1
                    # 清空左侧区域剩余旧公式行(A~J)，避免残留错位数据
                    for _r2 in range(_mg_row, _ws_mg.max_row + 1):
                        for _cc in set([1, 2, 3, 4, 5, 6, 7, 8, 9, _mg_src]):
                            _ws_mg.cell(row=_r2, column=_cc).value = None
                    # 扩展超级表(如「表1」)数据区域至实际末行，使其样式/筛选覆盖新写入的行
                    try:
                        _tbls = getattr(_ws_mg, "tables", None) or {}
                        for _tn in list(_tbls.keys()):
                            _tb = _tbls[_tn]
                            _ref = str(getattr(_tb, "ref", "") or "")
                            if _ref.upper().startswith("A1:"):
                                _end_col = ''.join(ch for ch in _ref.split(":")[-1] if ch.isalpha()) or "J"
                                _new_ref = f"A1:{_end_col}{max(2, _mg_row - 1)}"
                                _tb.ref = _new_ref
                                if getattr(_tb, "autoFilter", None) is not None:
                                    _tb.autoFilter.ref = _new_ref
                    except Exception as _te:
                        log(f"管理费超级表区域扩展失败(不影响其余功能): {_te}", "WARN")
                    log(f">>> 📌 管理费表 团队名称/骑手ID/骑手姓名/入职来源 已按配送所得表顺序复制 {_n_mg} 行，D~I 取数公式已逐行补齐", "INFO")
        except Exception as e:
            log(f"管理费表四列复制失败(不影响其余功能): {e}", "WARN")

        wb1.save(final_save_path)
        
        log(">>> 🎯 核心指纹MD5与本地源验证匹配，数据链路干净！", "SUCCESS")

        if intercept_records or daily_intercept_records:
            _ic_total = len(intercept_records) + len(daily_intercept_records)
            log(f">>> 🚨 重放攻击警告：防洪坝成功阻挡 {_ic_total} 次重复特征侵入！(配送单类 {len(intercept_records)} + 日维度单量 {len(daily_intercept_records)})", "ERROR")

        elapsed_time = time.time() - start_time
        stats_info["elapsed_time"] = round(elapsed_time, 2)
        stats_info["intercepted"] = (len(intercept_records) if 'intercept_records' in locals() else 0) + (len(daily_intercept_records) if 'daily_intercept_records' in locals() else 0)
        stats_info["unbound"] = len(unbound_records) if 'unbound_records' in locals() else 0
        stats_info["no_price"] = len(no_price_records) if 'no_price_records' in locals() else 0
        
        log(f">>> {random.choice(theme['msg_end'])}", "SYSTEM")
        log(f"事件总循环驻留时长: {elapsed_time:.2f} 秒")
        log(f"本地二进制对象封包构建输出位于: {out_folder}", "INFO")
        progress_callback(1.00, "周期月结数据分析架构全部收尾完毕！")
        finish_callback("success", out_folder, stats_info)
    except Exception as e:
        import traceback
        log(f"执行错误退出: {str(e)}\n{traceback.format_exc()}", "ERROR")
        progress_callback(0, "数据核心管线错误崩溃 (SIGKILL)")
        finish_callback("error", str(e), None)
