import zipfile
from workbook_policy import install_zip_policy
install_zip_policy()

import os
import re
import time
import json
import asyncio
import calendar
import pandas as pd
from datetime import datetime
import openpyxl
import traceback

from fengshen_bill import column_width, display_width

def _standardize_columns(df):
    if df is None or df.empty:
        return df
    
    # Trim column names
    df.columns = [str(c).strip() for c in df.columns]
    
    rename_dict = {}
    for col in df.columns:
        col_norm = str(col).replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "").lower()
        
        # Match 团队名称 (Team/Station Name - precise and distinct)
        if col_norm == "团队名称":
            rename_dict[col] = "团队名称"
        # Match 骑手ID (Rider ID - precise and distinct)
        elif col_norm == "骑手id":
            rename_dict[col] = "骑手ID"
        # Match 身份证 (Rider ID Card - precise and distinct)
        elif col_norm in ["身份证", "身份证号", "身份证号码"]:
            rename_dict[col] = "身份证"
        # Match 手机号 (Rider Phone Number - precise and distinct)
        elif col_norm in ["手机号", "手机号码"]:
            rename_dict[col] = "手机号"
        # Match 姓名 (Rider Name - precise and distinct)
        elif col_norm in ["姓名", "骑手姓名"]:
            rename_dict[col] = "骑手姓名"
            
    if rename_dict:
        df = df.rename(columns=rename_dict)
    return df

def _clean_nan_strings(df):
    if df is None or df.empty:
        return df
    # 仅对 object/string 列做 fillna("")，避免向 float/int 列写入空字符串
    # 触发 pandas>=3 的 LossySetitemError（pandas 2 仅 FutureWarning）
    obj_cols = df.select_dtypes(include=["object", "string"]).columns
    if len(obj_cols) > 0:
        df[obj_cols] = df[obj_cols].fillna("")
    bad_strings = ["nan", "NaN", "NAN", "None", "none", "null", "NULL", "nan.0", "None.0"]
    df.replace(to_replace=bad_strings, value="", inplace=True)
    return df

def _build_config_mapping(df_conf):
    if df_conf is None or df_conf.empty or len(df_conf.columns) < 2:
        return {}
    
    # Trim column headers
    df_conf.columns = [str(c).strip() for c in df_conf.columns]
    
    team_col = None
    city_col = None
    
    # Try matching columns by name
    for col in df_conf.columns:
        col_norm = str(col).strip().replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")
        if col_norm == "团队名称":
            team_col = col
        elif col_norm == "城市":
            city_col = col
            
    # Fallback if not identified by header names
    if not team_col or not city_col:
        c0_norm = str(df_conf.columns[0]).strip().replace(" ", "")
        c1_norm = str(df_conf.columns[1]).strip().replace(" ", "")
        if "城" in c0_norm or c0_norm == "城市":
            city_col = df_conf.columns[0]
            team_col = df_conf.columns[1]
        elif "城" in c1_norm or c1_norm == "城市":
            city_col = df_conf.columns[1]
            team_col = df_conf.columns[0]
        else:
            team_col = df_conf.columns[0]
            city_col = df_conf.columns[1]
            
    if team_col and city_col:
        mapping = dict(zip(
            df_conf[team_col].fillna("").astype(str).str.replace(r'[\s\u200b\u200c\u200d\u2060\ufeff]+', '', regex=True).str.replace('（', '(').str.replace('）', ')'),
            df_conf[city_col].fillna("").astype(str).str.replace(r'[\s\u200b\u200c\u200d\u2060\ufeff]+', '', regex=True).str.replace('（', '(').str.replace('）', ')')
        ))
        
        # Self-map cities so if a team name is actually just a city name, it maps to itself.
        # This prevents the UI from asking to map cities like '北京', '东莞' etc.
        known_cities = set(mapping.values())
        for city in known_cities:
            if city and city not in mapping:
                mapping[city] = city
                
        return mapping
    return {}

def _save_auto_mapped_to_config(config_file, mapping):
    if not mapping:
        return
    import json
    import openpyxl
    if config_file.endswith(".json"):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
            
        for team, city in mapping.items():
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
                    first_row = data[0]
                    for k in first_row.keys():
                        if k not in ["城市", "团队名称", "团队ID"]:
                            new_row[k] = 0
                data.append(new_row)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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
        for team, city in mapping.items():
            team_exists = False
            for r in range(2, ws.max_row + 1):
                cell_val = str(ws.cell(row=r, column=col_team).value or "").strip()
                if cell_val == str(team).strip():
                    ws.cell(row=r, column=col_city, value=str(city).strip())
                    team_exists = True
                    break
            if not team_exists:
                ws.cell(row=start_row, column=col_team, value=str(team).strip())
                ws.cell(row=start_row, column=col_city, value=str(city).strip())
                start_row += 1
            
        wb.save(config_file)

def create_log_event(msg, level="INFO"):
    return f'data: {json.dumps({"type": "log", "msg": msg, "level": level})}\n\n'

def create_progress_event(value, text=""):
    return f'data: {json.dumps({"type": "progress", "value": value, "progress": value, "text": text})}\n\n'

def create_finish_event(msg, file_path, stats_data, error=None, layout=None):
    status = "error" if error else "success"
    payload = {"type": "finish", "status": status, "result_msg": msg, "out_file": file_path,
               "stats": stats_data, "error": error}
    if layout:
        payload["layout"] = layout
    return f'data: {json.dumps(payload)}\n\n'

def process_rider_detail_df(df):
    """
    针对 20万行+ 的 骑手数据明细 关键子表进行极速列提取与向量化格式转换。
    只提取指定17列，全程采用 C 扩展级别的 Pandas 向量化计算，耗时<0.2秒。
    """
    if df is None or df.empty:
        return df

    target_cols = [
        "日期", "骑手ID", "骑手姓名", "骑手手机号", "团队ID", "团队名称",
        "所属管理分组", "骑手等级", "最新入职时间", "最新离职时间", "在职状态",
        "入职时长", "活跃天数", "有效在线时长", "午高峰有效在线时长",
        "晚高峰有效在线时长", "有效完成单"
    ]
    
    # 1. 快速切片：仅保留目标列（避免多余列占据内存）
    existing_cols = [col for col in target_cols if col in df.columns]
    if not existing_cols:
        return df
    
    df = df[existing_cols]

    # 2. 日期列极速格式化：直接提取前10位(YYYY-MM-DD)或向量化转换，避免昂贵的逐行/常规 Parse
    date_cols = ["日期", "最新入职时间", "最新离职时间"]
    for dcol in date_cols:
        if dcol in df.columns:
            s = df[dcol]
            if pd.api.types.is_datetime64_any_dtype(s):
                df[dcol] = s.dt.strftime('%Y-%m-%d')
            else:
                # 字符串格式极速截取前10位 (如 "2026-07-28 00:00:00" -> "2026-07-28")
                s_str = s.astype(str).str.strip()
                df[dcol] = s_str.str.slice(0, 10)

    # 3. 数值列极致向量化转换 (基于 C 扩展，20万行仅需约 0.01s/列)
    numeric_cols = [
        "骑手ID", "骑手手机号", "团队ID", "入职时长", "活跃天数",
        "有效在线时长", "午高峰有效在线时长", "晚高峰有效在线时长", "有效完成单"
    ]
    for ncol in numeric_cols:
        if ncol in df.columns:
            df[ncol] = pd.to_numeric(df[ncol], errors='coerce')

    return df

def _read_file_fast(file_path, dtype_dict=None):
    filename = os.path.basename(file_path)
    # Default to str dtype for all columns to prevent automatic number formatting (like scientific notation or adding .0)
    dtype_val = dtype_dict if isinstance(dtype_dict, dict) else str
    try:
        if file_path.endswith('.csv'):
            try:
                df = pd.read_csv(file_path, encoding='utf-8', dtype=dtype_val, low_memory=False, keep_default_na=False)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='gbk', dtype=dtype_val, low_memory=False, keep_default_na=False)
            if "骑手数据明细" in filename or "数据明细" in filename:
                df = process_rider_detail_df(df)
            return df
        elif file_path.endswith('.json'):
            import json
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            df = pd.DataFrame(data)
            # convert all columns to string if required
            if dtype_val == str:
                df = df.astype(str)
            if "骑手数据明细" in filename or "数据明细" in filename:
                df = process_rider_detail_df(df)
            return df
        else:
            is_detail_sheet = False
            target_sheet = 0
            xls = None
            try:
                xls = pd.ExcelFile(file_path)
                for s in xls.sheet_names:
                    if "骑手数据明细" in s:
                        target_sheet = s
                        is_detail_sheet = True
                        break
                if not is_detail_sheet:
                    for s in xls.sheet_names:
                        if "数据明细" in s:
                            target_sheet = s
                            is_detail_sheet = True
                            break
            except Exception:
                pass
            finally:
                if xls is not None:
                    xls.close()

            try:
                df = pd.read_excel(file_path, sheet_name=target_sheet, engine='calamine', dtype=dtype_val, keep_default_na=False)
            except Exception:
                df = pd.read_excel(file_path, sheet_name=target_sheet, dtype=dtype_val, keep_default_na=False)

            if is_detail_sheet or "骑手数据明细" in filename or "数据明细" in filename:
                df = process_rider_detail_df(df)
            return df
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return pd.DataFrame()

def _to_num_safe(val):
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() in ["nan", "none", "null"]:
        return None
    try:
        if val_str.isdigit():
            return int(val_str)
        # Check if it is a float representation like "12345.0"
        f_val = float(val_str)
        if f_val.is_integer():
            return int(f_val)
        return f_val
    except Exception:
        return val

def _fast_write_df_helper(writer, sheet_name, df_obj, header_format, cell_format, id_num_format, apply_style,
                          footer_format=None):
    workbook = writer.book
    worksheet = workbook.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = worksheet
    worksheet.freeze_panes(1, 0)
    
    headers = df_obj.columns.tolist()
    widths = []
    
    # Set column width and style（自适应：按表头与全部内容的最长显示宽度）
    # widths 保存的是「显示宽度」，与多城市汇总的合并口径一致；写盘时再换算 Excel 列宽。
    if apply_style and cell_format:
        for col_num, col_name in enumerate(headers):
            longest = display_width(col_name)
            for value in df_obj.iloc[:, col_num]:
                width = display_width(value)
                if width > longest:
                    longest = width
            style = id_num_format if (col_name in ["骑手ID", "收款人ID"] and id_num_format) else cell_format
            widths.append(longest)
            worksheet.set_column(col_num, col_num, column_width(longest), style)
            
    # Write header
    if apply_style and header_format:
        for col_num, header in enumerate(headers):
            worksheet.write_string(0, col_num, str(header), header_format)
    else:
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header)
            
    # Convert dataframe to a list of lists for extreme speed
    values = df_obj.values.tolist()
    
    # Pre-identify columns that must be written as string to avoid scientific notation
    str_cols = set()
    num_cols = set()
    for col_num, col_name in enumerate(headers):
        if col_name in ["骑手身份证", "收款人身份证号码", "骑手手机号", "收款人手机号码", "身份证", "手机号"]:
            str_cols.add(col_num)
        elif col_name in ["骑手ID", "收款人ID"]:
            num_cols.add(col_num)
            
    # Write values row by row
    for row_num, row_data in enumerate(values, start=1):
        footer = footer_format is not None and row_num == len(values)
        row_format = footer_format if footer else (cell_format if apply_style else None)
        for col_num, val in enumerate(row_data):
            if pd.isna(val) or val is None or val == "":
                worksheet.write_blank(row_num, col_num, None, row_format)
            else:
                if col_num in str_cols:
                    worksheet.write_string(row_num, col_num, str(val), row_format)
                elif col_num in num_cols:
                    val_num = _to_num_safe(val)
                    if val_num is None:
                        worksheet.write_blank(row_num, col_num, None, row_format)
                    else:
                        fmt = row_format if footer else (id_num_format if (apply_style and id_num_format) else row_format)
                        worksheet.write(row_num, col_num, val_num, fmt)
                else:
                    worksheet.write(row_num, col_num, val, row_format)

    return {'header': [str(header) for header in headers], 'widths': widths}

def _std_id_str(val):
    if pd.isna(val) or val is None:
        return ""
    val_str = str(val).strip()
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
    return val_str

def _filter_df_for_city(df, city, rider_id_to_city, idcard_to_city, config_mapping):
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else [])
    
    # Try filtering by Rider ID
    rid_col = None
    for col in ["骑手ID", "ID", "骑手", "收款人ID"]:
        if col in df.columns:
            rid_col = col
            break
            
    if rid_col:
        # Check if the mapped city of the rider ID matches
        mapped_cities = df[rid_col].apply(_std_id_str).map(rider_id_to_city)
        mask = mapped_cities == city
        
        # If there's also an ID card col, we can check it too as fallback
        id_col = None
        for col in ["身份证", "身份证号", "身份证号码", "证件号码", "证件号", "骑手身份证", "打款人身份证号", "代领人身份证"]:
            if col in df.columns:
                id_col = col
                break
        if id_col:
            mapped_cities_id = df[id_col].fillna("").astype(str).str.strip().str.upper().map(idcard_to_city)
            mask = mask | (mapped_cities_id == city)
            
        return df[mask].copy()
        
    # Try filtering by ID Card
    id_col = None
    for col in ["身份证", "身份证号", "身份证号码", "证件号码", "证件号", "骑手身份证", "打款人身份证号", "代领人身份证"]:
        if col in df.columns:
            id_col = col
            break
    if id_col:
        mapped_cities_id = df[id_col].fillna("").astype(str).str.strip().str.upper().map(idcard_to_city)
        return df[mapped_cities_id == city].copy()
        
    # Try filtering by Team Name
    team_col = None
    for col in ["团队名称", "团队", "部门", "网点"]:
        if col in df.columns:
            team_col = col
            break
    if team_col:
        mapped_cities_team = df[team_col].fillna("").astype(str).str.strip().replace('（', '(').str.replace('）', ')').map(config_mapping)
        return df[mapped_cities_team == city].copy()
        
    # Try filtering by a direct "城市" column if exists
    city_col = None
    for col in ["城市", "city", "地区"]:
        if col in df.columns:
            city_col = col
            break
    if city_col:
        return df[df[city_col].fillna("").astype(str).str.strip() == city].copy()
        
    return pd.DataFrame(columns=df.columns)

STATION_SUMMARY_SHEET = '站点汇总'
STATION_SUMMARY_HEADER = ['月份', '城市', '站点名称', '骑手明细周期', '有单骑手人数', '有效完成单',
                          '风神绑定人数', '发薪平台绑定人数', '完全绑定人数', '黑户代领人数', '说明']
UNASSIGNED_STATION = '未分配站点'


def _station_period(extracted_month, start=None, end=None):
    match = re.match(r'(\d{4})年(\d{1,2})月', str(extracted_month))
    if not match:
        return str(extracted_month), ''
    year, month = int(match.group(1)), int(match.group(2))
    label = f'{year:04d}-{month:02d}'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(start or '')) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(end or '')):
        return label, f'{start} 至 {end}'
    return label, f'{label}-01 至 {label}-{calendar.monthrange(year, month)[1]:02d}'


def _station_summary_df(city, extracted_month, df_city_sht1, start=None, end=None):
    """城市成品的站点汇总：口径与多城市汇总的「城市汇总」一致，按团队名称（站点）聚合。"""
    month, period = _station_period(extracted_month, start, end)
    frame = df_city_sht1 if isinstance(df_city_sht1, pd.DataFrame) else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(columns=STATION_SUMMARY_HEADER)
    station = frame['团队名称'] if '团队名称' in frame else pd.Series('', index=frame.index)
    station = station.fillna('').astype(str).str.strip()
    station = station.where(~station.isin(['', 'nan', 'None', 'NAN', 'null']), UNASSIGNED_STATION)
    orders = pd.to_numeric(frame['单量汇总'], errors='coerce').fillna(0) if '单量汇总' in frame \
        else pd.Series(0, index=frame.index)
    flags = pd.DataFrame({
        '站点名称': station,
        '有单骑手人数': 1,
        '有效完成单': orders,
        '风神绑定人数': (frame['风神绑定'] == '已绑定').astype(int) if '风神绑定' in frame else 0,
        '发薪平台绑定人数': (frame['发薪平台绑定'] == '已绑定').astype(int) if '发薪平台绑定' in frame else 0,
        '完全绑定人数': (frame['绑定情况'] == '已绑定').astype(int) if '绑定情况' in frame else 0,
        '黑户代领人数': (frame['是否黑户'] == '是').astype(int) if '是否黑户' in frame else 0,
    })
    grouped = flags.groupby('站点名称', sort=False).sum().reset_index()
    grouped = grouped.sort_values(['有效完成单', '站点名称'], ascending=[False, True], kind='stable')
    rows = [[month, city, row['站点名称'], period, int(row['有单骑手人数']), int(row['有效完成单']),
             int(row['风神绑定人数']), int(row['发薪平台绑定人数']), int(row['完全绑定人数']),
             int(row['黑户代领人数']), ''] for _, row in grouped.iterrows()]
    totals = grouped[['有单骑手人数', '有效完成单', '风神绑定人数', '发薪平台绑定人数',
                      '完全绑定人数', '黑户代领人数']].sum()
    station_count = len(grouped)
    rows.append([month, city, f'{station_count}/{station_count} 站点', period,
                 *(int(value) for value in totals), '各站点独立计数'])
    return pd.DataFrame(rows, columns=STATION_SUMMARY_HEADER)


def _write_city_wb_worker(city, extracted_month, today_str, output_dir, sht1_name, sht2_name, df_city_sht1, df_city_sht2, df_city_dailing, start=None, end=None):
    city_wb_name = f"{city}{extracted_month}骑手支付绑定{today_str}.xlsx"
    city_output_file = os.path.join(output_dir, city_wb_name)
    
    try:
        folder_month = extracted_month.replace("年", "").replace("月", "")[-2:]
        month_only = f"{int(folder_month)}月"
    except Exception:
        month_only = "当月"
        
    options = {'strings_to_urls': False, 'strings_to_formulas': False}
    with pd.ExcelWriter(city_output_file, engine='xlsxwriter', engine_kwargs={'options': options}) as writer:
        workbook = writer.book
        
        header_format = workbook.add_format({
            'bg_color': '#F8CBAD',
            'font_name': '微软雅黑',
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        cell_format = workbook.add_format({
            'font_name': '微软雅黑',
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter'
        })
        id_num_format = workbook.add_format({
            'font_name': '微软雅黑',
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter',
            'num_format': '0'
        })
        
        sheets_to_write = [
            (STATION_SUMMARY_SHEET, _station_summary_df(city, extracted_month, df_city_sht1, start, end), True),
            (sht1_name, df_city_sht1, True),
            (sht2_name, df_city_sht2, True),
            (f"{month_only}黑户代领明细", df_city_dailing, True)
        ]
        
        for sheet_name, df_obj, apply_style in sheets_to_write:
            _fast_write_df_helper(
                writer, 
                sheet_name, 
                df_obj, 
                header_format if apply_style else None, 
                cell_format if apply_style else None, 
                id_num_format if apply_style else None, 
                apply_style,
                header_format if sheet_name == STATION_SUMMARY_SHEET and apply_style else None
            )
    return city_wb_name

async def run_salary_bind_gen(source_path, target_path=None, base_path=None, deductionRules=None, verified_scope=None, *, prepared_inputs=None, table_sink=None):
    start_time = time.time()
    try:
        yield create_log_event(f"[{time.time()-start_time:.2f}s] >>> 正在启动发薪工具绑定任务...", "INFO")
        await asyncio.sleep(0.01)
        
        import re
        import glob
        folder_name = os.path.basename(source_path)
        
        # Get list of files first to extract month from file names if possible
        files = glob.glob(os.path.join(source_path, "*"))
        files = [f for f in files if os.path.isfile(f) and not os.path.basename(f).startswith(".")]
        
        if prepared_inputs is not None:
            if not verified_scope:
                raise ValueError('内存资料必须提供已核验的城市和月份范围')
            files = [os.path.join(source_path, name) for name in prepared_inputs]

        extracted_month = None
        # Try to locate the file containing "骑手数据明细" (or "数据明细")
        target_file = None
        for file in files:
            fname = os.path.basename(file)
            if "骑手数据明细" in fname:
                target_file = file
                break
        if not target_file:
            for file in files:
                fname = os.path.basename(file)
                if "数据明细" in fname:
                    target_file = file
                    break
                    
        if target_file and not verified_scope:
            try:
                # Read cell A2 (row index 1, col index 0 when header=None) to extract month
                df_temp = None
                if target_file.endswith('.csv'):
                    for enc in ['utf-8-sig', 'gbk', 'gb18030', 'utf-8']:
                        try:
                            df_temp = pd.read_csv(target_file, header=None, nrows=2, encoding=enc)
                            if df_temp is not None and not df_temp.empty:
                                break
                        except Exception:
                            continue
                else:
                    df_temp = pd.read_excel(target_file, header=None, nrows=2)
                
                if df_temp is not None and df_temp.shape[0] >= 2 and df_temp.shape[1] >= 1:
                    date_val = df_temp.iloc[1, 0]
                    if pd.notna(date_val):
                        # Try to parse via pandas first
                        try:
                            dt = pd.to_datetime(date_val)
                            if pd.notna(dt):
                                extracted_month = f"{dt.year}年{dt.month:02d}月"
                        except Exception:
                            pass
                            
                        if not extracted_month:
                            date_str = str(date_val).strip()
                            m_zh = re.search(r'(\d{4})年(\d{1,2})月', date_str)
                            if m_zh:
                                year, month = m_zh.groups()
                                extracted_month = f"{year}年{int(month):02d}月"
                                
                            if not extracted_month:
                                m_date = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
                                if m_date:
                                    year, month, _ = m_date.groups()
                                    extracted_month = f"{year}年{int(month):02d}月"
                                    
                            if not extracted_month:
                                m_short = re.search(r'(\d{4})[-/\.](\d{1,2})', date_str)
                                if m_short:
                                    year, month = m_short.groups()
                                    extracted_month = f"{year}年{int(month):02d}月"
                                    
                            if not extracted_month:
                                m_num = re.search(r'\b(\d{4})(\d{2})(\d{2})?\b', date_str)
                                if m_num:
                                    year, month = m_num.group(1), m_num.group(2)
                                    extracted_month = f"{year}年{int(month):02d}月"
            except Exception as e:
                print(f"Error extracting month from A2 in {target_file}: {e}")

        if verified_scope:
            year, month = verified_scope['month'].split('-')
            extracted_month = f"{year}年{month}月"
        period_start = (verified_scope or {}).get('start')
        period_end = (verified_scope or {}).get('end')

        # Fallback to older patterns if not yet extracted from "骑手数据明细"
        if not extracted_month:
            # 1. Try to find \d{4}年\d{1,2}月 in file names first because they usually contain the month name
            for file in files:
                fname = os.path.basename(file)
                m = re.search(r'(\d{4}年\d{1,2}月)', fname)
                if m:
                    extracted_month = m.group(1)
                    break
                    
        # 2. Try folder_name
        if not extracted_month:
            m = re.search(r'(\d{4}年\d{1,2}月)', folder_name)
            if m:
                extracted_month = m.group(1)
                
        # 3. Try source_path
        if not extracted_month:
            m = re.search(r'(\d{4}年\d{1,2}月)', source_path)
            if m:
                extracted_month = m.group(1)
                
        # 4. Fallback to 2024年07月
        if not extracted_month:
            extracted_month = "2024年07月"
            
        # Normalize to 2-digit month (e.g., 2024年7月 -> 2024年07月)
        m_norm = re.match(r'(\d{4})年(\d{1,2})月', extracted_month)
        if m_norm:
            year, month = m_norm.groups()
            extracted_month = f"{year}年{int(month):02d}月"
            
        folder_month = extracted_month.replace("年", "").replace("月", "")[-2:]
        
        loop = asyncio.get_running_loop()

        df_detail_list = []
        df_info_list = []
        df_shangyi_list = []
        df_fengshen_list = []
        df_dailing_list = []
        
        total_files = len(files)
        # 并行载入全部文件，极速载入
        yield create_log_event(f"[{time.time()-start_time:.2f}s] 📂 正在启动多线程并行读取文件 ({total_files}个文件)...", "INFO")
        await asyncio.sleep(0.01)
        
        from concurrent.futures import ThreadPoolExecutor
        loaded_results = []
        if prepared_inputs is not None:
            loaded_results = [(os.path.join(source_path, name), frame) for name, frame in prepared_inputs.items()]
            yield create_progress_event(.5, '复用已校验的内存资料')
        else:
            # Bound nested reader concurrency and release it on failure/cancellation too.
            with ThreadPoolExecutor(max_workers=min(3, max(1, total_files))) as read_executor:
                async def _load_file_task(f):
                    df = await loop.run_in_executor(read_executor, _read_file_fast, f)
                    return f, df
                load_tasks = [_load_file_task(f) for f in files]
                for idx, future in enumerate(asyncio.as_completed(load_tasks)):
                    f, df = await future
                    loaded_results.append((f, df))
                    fname = os.path.basename(f)
                    yield create_log_event(f"[{time.time()-start_time:.2f}s] ✔️ 已载入文件: {fname}", "INFO")
                    yield create_progress_event(0.1 + ((idx + 1) / max(1,total_files)) * 0.4, f"已读取 {idx+1}/{total_files} 个文件")
                    await asyncio.sleep(0.001)

        # 按照原来的逻辑对载入的数据进行归类
        for file, df in loaded_results:
            fname = os.path.basename(file)
            fname_lower = fname.lower()
            matched = False
            
            if "骑手绑定" in fname_lower or "收薪账户" in fname_lower:
                df_fengshen_list.append(_standardize_columns(df))
                matched = True
            elif "merchantfreelancer" in fname_lower:
                df_shangyi_list.append(_standardize_columns(df))
                matched = True
            elif "发薪" in fname_lower or "商翼" in fname_lower or "绑定" in fname_lower:
                df_shangyi_list.append(_standardize_columns(df))
                matched = True
            elif "代领" in fname_lower:
                df_dailing_list.append(_standardize_columns(df))
                matched = True
            elif "详情" in fname_lower or "明细" in fname_lower or "账单" in fname_lower or "出勤" in fname_lower or "数据" in fname_lower or "结果" in fname_lower or "汇总" in fname_lower:
                df_detail_list.append(_standardize_columns(df))
                matched = True
            elif "信息" in fname_lower or "名单" in fname_lower or "骑手" in fname_lower:
                df_info_list.append(_standardize_columns(df))
                matched = True
                
            if not matched:
                if not df.empty:
                    df_std = _standardize_columns(df)
                    cols_set = set(df_std.columns)
                    
                    if any(c in cols_set for c in ["代领人身份证", "打款人身份证号", "代领人"]):
                        df_dailing_list.append(df_std)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] 💡 自动识别 {fname} 为 [代领] 表", "INFO")
                    elif any(c in cols_set for c in ["单量", "单量汇总", "单数", "有效单量", "配送单量"]):
                        df_detail_list.append(df_std)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] 💡 自动识别 {fname} 为 [详情/明细] 表", "INFO")
                    elif any(c in cols_set for c in ["骑手ID", "团队名称", "城市"]):
                        df_detail_list.append(df_std)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] 💡 自动识别 {fname} 为 [详情/明细] 表", "INFO")
                    elif "骑手姓名" in cols_set or "身份证" in cols_set:
                        df_info_list.append(df_std)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] 💡 自动识别 {fname} 为 [信息/名单] 表", "INFO")
                    else:
                        df_detail_list.append(df_std)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] ⚠️ 无法从文件名识别 {fname} 类型，默认作为 [详情/明细] 表载入", "WARN")

        df_detail = pd.concat(df_detail_list, ignore_index=True) if df_detail_list else pd.DataFrame()
        df_info = pd.concat(df_info_list, ignore_index=True) if df_info_list else pd.DataFrame()
        
        # Fallback if there are no details file but there is info file
        if df_detail.empty and not df_info.empty:
            df_detail = df_info.copy()

        df_shangyi = pd.concat(df_shangyi_list, ignore_index=True) if df_shangyi_list else pd.DataFrame()
        df_fengshen = pd.concat(df_fengshen_list, ignore_index=True) if df_fengshen_list else pd.DataFrame()
        df_dailing = pd.concat(df_dailing_list, ignore_index=True) if df_dailing_list else pd.DataFrame()

        # 1. 查找包含"骑手数据明细"或"数据明细"的工作薄，精准匹配"有效完成单"列获取总单量
        rider_orders_map = {}
        target_detail_df = pd.DataFrame()
        found_target_name = None
        
        for file, df in loaded_results:
            fname = os.path.basename(file)
            if "骑手数据明细" in fname:
                target_detail_df = df
                found_target_name = fname
                break
                
        if target_detail_df.empty:
            for file, df in loaded_results:
                fname = os.path.basename(file)
                if "数据明细" in fname:
                    target_detail_df = df
                    found_target_name = fname
                    break
                    
        if not target_detail_df.empty:
            temp_df = target_detail_df.copy()
            rid_col = None
            for col in ["骑手ID", "ID", "骑手"]:
                if col in temp_df.columns:
                    rid_col = col
                    break
            
            if rid_col and "有效完成单" in temp_df.columns:
                temp_df[rid_col] = temp_df[rid_col].fillna("").astype(str).str.strip()
                # 过滤无效ID
                temp_df = temp_df[
                    (temp_df[rid_col] != "") & 
                    (temp_df[rid_col].str.lower() != "nan") & 
                    (temp_df[rid_col].str.lower() != "none")
                ]
                # 转为数值，无效值填充为0
                temp_df["有效完成单"] = pd.to_numeric(temp_df["有效完成单"], errors='coerce').fillna(0)
                # 聚合求和
                rider_orders_map = temp_df.groupby(rid_col)["有效完成单"].sum().to_dict()
                yield create_log_event(f"[{time.time()-start_time:.2f}s] 📊 成功在工作簿 [{found_target_name}] 中，精准匹配 '有效完成单' 列，获取到 {len(rider_orders_map)} 个骑手的总单量！", "INFO")
                
        # 2. 如果未能从上述特定工作薄获取到单量，尝试从 df_detail 所有的列中做回退匹配
        if not rider_orders_map and not df_detail.empty:
            temp_df = df_detail.copy()
            rid_col = None
            for col in ["骑手ID", "ID", "骑手"]:
                if col in temp_df.columns:
                    rid_col = col
                    break
            if rid_col:
                temp_df[rid_col] = temp_df[rid_col].fillna("").astype(str).str.strip()
                col_to_sum = None
                for col in ["有效完成单", "单量", "单量汇总", "订单量", "总单量"]:
                    if col in temp_df.columns:
                        col_to_sum = col
                        break
                if col_to_sum:
                    temp_df[col_to_sum] = pd.to_numeric(temp_df[col_to_sum], errors='coerce').fillna(0)
                    rider_orders_map = temp_df.groupby(rid_col)[col_to_sum].sum().to_dict()
                    yield create_log_event(f"[{time.time()-start_time:.2f}s] ⚠️ 已通过回退列 [{col_to_sum}] 提取到 {len(rider_orders_map)} 个骑手的单量汇总", "WARN")

        # 3. 构造并去重 df_sht1，确保一个骑手仅保留一条记录
        df_sht1 = df_detail.copy()
        if not df_sht1.empty:
            rid_col = None
            for col in ["骑手ID", "ID", "骑手"]:
                if col in df_sht1.columns:
                    rid_col = col
                    break
            if rid_col:
                df_sht1[rid_col] = df_sht1[rid_col].fillna("").astype(str).str.strip()
                # 过滤无效ID
                df_sht1 = df_sht1[
                    (df_sht1[rid_col] != "") & 
                    (df_sht1[rid_col].str.lower() != "nan") & 
                    (df_sht1[rid_col].str.lower() != "none")
                ]
                # 去重，保留第一行（代表骑手基础属性，其每日明细属性相同）
                df_sht1 = df_sht1.drop_duplicates(subset=[rid_col], keep="first")

        today_str = datetime.now().strftime('%m%d')
        month_dir_name = f"(汇总){extracted_month}骑手支付绑定{today_str}"

        if not target_path:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            root_dir = os.path.abspath(os.path.join(project_root, "outputs", "骑手支付绑定"))
            output_dir = os.path.join(root_dir, month_dir_name)
        else:
            if not target_path.endswith(month_dir_name):
                root_dir = target_path
                output_dir = os.path.join(target_path, month_dir_name)
            else:
                root_dir = os.path.dirname(target_path)
                output_dir = target_path
        os.makedirs(root_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        try:
            folder_month = extracted_month.replace("年", "").replace("月", "")[-2:]
            month_only = f"{int(folder_month)}月"
        except Exception:
            month_only = "当月"

        output_file = os.path.join(output_dir, f"{extracted_month}骑手支付绑定汇总{today_str}.xlsx")
        sht1_name = f"{month_only}骑手绑定情况"
        sht2_name = f"{month_only}未绑名单"
        
        if not df_sht1.empty:
            # 填充单量汇总
            rid_col = None
            for col in ["骑手ID", "ID", "骑手"]:
                if col in df_sht1.columns:
                    rid_col = col
                    break
            if rid_col and rider_orders_map:
                df_sht1["单量汇总"] = df_sht1[rid_col].map(rider_orders_map).fillna(0)
            else:
                df_sht1["单量汇总"] = 0
                
            project_root_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.basename(project_root_dir) == 'backend':
                project_root_dir = os.path.dirname(project_root_dir)
            
            config_mapping = {}
            config_file = None
            for fname in ["config.json", "config.xlsx", "配置.json", "配置.xlsx"]:
                for base_p in [os.path.join(project_root_dir, "data"), os.path.join(project_root_dir, "app", "data")]:
                    p = os.path.join(base_p, fname)
                    if os.path.exists(p):
                        config_file = p
                        break
                if config_file:
                    break

                    
            if config_file:
                try:
                    df_conf = _read_file_fast(config_file)
                    config_mapping = _build_config_mapping(df_conf)
                    yield create_log_event(f"Loaded config from {config_file}, mapping size: {len(config_mapping)}", "INFO")
                except Exception as e:
                    yield create_log_event(f"Error loading config: {str(e)}", "ERROR")
                    pass

            dailing_idcard_col = None
            dailing_rid_set = set()
            dailing_idcard_map = {}
            dailing_name_map = {}
            dailing_status_map = {}
            
            if not df_dailing.empty:
                # ---- 代领月份筛选：仅保留代领月份等于提取月份的记录 ----
                # 避免非当月代领名单进入 dailing_rid_set，从而污染「是否黑户」标记
                _month_col = None
                for _cand in ["代领月份", "代发月份", "代领月", "代发月", "月份"]:
                    if _cand in df_dailing.columns:
                        _month_col = _cand
                        break
                if _month_col:
                    def _norm_dm(v):
                        s = "" if v is None else str(v).strip()
                        if not s or s.lower() in ("nan", "none"):
                            return ""
                        _m = re.search(r'(\d{4})\D+(\d{1,2})', s)
                        return f"{_m.group(1)}年{int(_m.group(2)):02d}月" if _m else ""
                    df_dailing = df_dailing.copy()
                    df_dailing["_norm_month"] = df_dailing[_month_col].map(_norm_dm)
                    _before = len(df_dailing)
                    # 保留当月记录；无法解析的保守保留（仅剔除可明确判定为非当月的）
                    df_dailing = df_dailing[
                        (df_dailing["_norm_month"] == extracted_month) | (df_dailing["_norm_month"] == "")
                    ].copy()
                    df_dailing.drop(columns=["_norm_month"], inplace=True)
                    _dropped = _before - len(df_dailing)
                    yield create_log_event(
                        f"[{time.time()-start_time:.2f}s] 💡 按代领月份筛选（{_month_col}={extracted_month}），剔除 {_dropped} 条非当月/未解析记录，保留 {len(df_dailing)} 条",
                        "INFO"
                    )
                else:
                    yield create_log_event(
                        f"[{time.time()-start_time:.2f}s] ⚠️ 代领表中未发现『代领月份』列，跳过月份筛选（可能混入非当月代领名单，建议补充该列）",
                        "WARN"
                    )

                if not df_dailing.empty:
                    if "代领人身份证" in df_dailing.columns and "流程状态" in df_dailing.columns:
                        id_series = df_dailing["代领人身份证"].fillna("").astype(str).str.strip()
                        status_series = df_dailing["流程状态"].fillna("").astype(str).str.strip()
                        
                        valid_mask = (
                            (id_series != "") &
                            (id_series.str.lower() != "nan") &
                            (id_series.str.lower() != "none") &
                            (status_series != "") &
                            (status_series.str.lower() != "nan") &
                            (status_series.str.lower() != "none") &
                            (status_series != "审核拒绝")
                        )
                        df_dailing_valid = df_dailing[valid_mask].copy()
                        
                        rider_id_col = None
                        for col in ["打款人身份证号", "身份证", "身份证号", "骑手身份证", "证件号码"]:
                            if col in df_dailing_valid.columns and col != "代领人身份证":
                                rider_id_col = col
                                break
                        
                        if rider_id_col:
                            dailing_idcard_col = rider_id_col
                            df_dailing_valid["_rider_id_clean"] = df_dailing_valid[rider_id_col].fillna("").astype(str).str.strip().str.upper()
                            df_dailing_map_df = df_dailing_valid[df_dailing_valid["_rider_id_clean"] != ""].drop_duplicates(subset=["_rider_id_clean"], keep="first")
                            
                            dailing_rid_set = set(df_dailing_map_df["_rider_id_clean"])
                            dailing_idcard_map = dict(zip(df_dailing_map_df["_rider_id_clean"], df_dailing_map_df["代领人身份证"].fillna("").astype(str).str.strip()))
                            
                            proxy_name_col = None
                            for col in ["代领人姓名", "代领人", "打款人姓名", "收款人"]:
                                if col in df_dailing_valid.columns:
                                    proxy_name_col = col
                                    break
                            if proxy_name_col:
                                dailing_name_map = dict(zip(df_dailing_map_df["_rider_id_clean"], df_dailing_map_df[proxy_name_col].fillna("").astype(str).str.strip()))
                            
                            dailing_status_map = dict(zip(df_dailing_map_df["_rider_id_clean"], df_dailing_map_df["流程状态"].fillna("").astype(str).str.strip()))
                            yield create_log_event(f"[{time.time()-start_time:.2f}s] 💡 成功识别并提取 {len(dailing_rid_set)} 条有效的代领骑手记录", "INFO")
                        else:
                            yield create_log_event(f"[{time.time()-start_time:.2f}s] ⚠️ 代领表中未发现存储被代领骑手身份证标识的列", "WARN")
                    else:
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] ⚠️ 代领表中缺少 '代领人身份证' 或 '流程状态' 列", "WARN")

            sy_bound_set = set()
            if not df_shangyi.empty:
                # Find the status column
                status_col = None
                for col in df_shangyi.columns:
                    col_clean = str(col).strip().replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")
                    if col_clean in ["状态", "绑定状态", "签约状态", "状态列", "status"]:
                        status_col = col
                        break
                
                # Filter by status if status column exists
                if status_col is not None:
                    # Precise matching for '已签约'
                    df_shangyi_filtered = df_shangyi[df_shangyi[status_col].astype(str).str.strip() == "已签约"]
                else:
                    df_shangyi_filtered = df_shangyi
                
                # Find ID card column
                id_col = None
                for col in ["身份证", "身份证号", "身份证号码", "证件号码", "证件号"]:
                    if col in df_shangyi_filtered.columns:
                        id_col = col
                        break
                
                if id_col is not None:
                    sy_bound_set = set(df_shangyi_filtered[id_col].dropna().astype(str).str.strip().str.upper())
                    if verified_scope:
                        sy_bound_set = {value for value in sy_bound_set if re.fullmatch(r'\d{17}[\dX]', value)}

            fs_bound_set = set()
            if not df_fengshen.empty:
                # 3、使用骑手ID列精准匹配
                if "骑手ID" in df_fengshen.columns:
                    df_fs_filtered = df_fengshen
                    
                    # 1、并且收款账户列值不为空才算有效绑定
                    if "收款账户" in df_fs_filtered.columns:
                        shoukuan_vals = df_fs_filtered["收款账户"].astype(str).str.strip()
                        df_fs_filtered = df_fs_filtered[
                            df_fs_filtered["收款账户"].notna() &
                            (shoukuan_vals != "") &
                            (shoukuan_vals.str.lower() != "nan") &
                            (shoukuan_vals.str.lower() != "none")
                        ]
                    
                    # 1、修改为转化为数值格式，并整理去重为一个已绑定风神的骑手 ID 集合，使用精准匹配
                    numeric_ids = pd.to_numeric(df_fs_filtered["骑手ID"], errors='coerce')
                    fs_bound_set = set(numeric_ids.dropna())
                        
            info_idcard_map = {}
            info_phone_map = {}
            if not df_info.empty and "骑手ID" in df_info.columns:
                # Clean df_info's "骑手ID" so we ignore empty or nan entries
                df_info_clean = df_info.copy()
                df_info_clean["骑手ID"] = df_info_clean["骑手ID"].fillna("").astype(str).str.strip()
                df_info_clean = df_info_clean[
                    (df_info_clean["骑手ID"] != "") & 
                    (df_info_clean["骑手ID"].str.lower() != "nan") & 
                    (df_info_clean["骑手ID"].str.lower() != "none")
                ]
                
                idcard_col = None
                for col in ["证件号码", "身份证", "身份证号", "身份证号码"]:
                    if col in df_info_clean.columns:
                        idcard_col = col
                        break
                if idcard_col:
                    info_idcard_map = dict(zip(df_info_clean["骑手ID"], df_info_clean[idcard_col].fillna("").astype(str).str.strip()))
                
                phone_col = None
                for col in ["联系电话", "手机号", "手机号码", "电话"]:
                    if col in df_info_clean.columns:
                        phone_col = col
                        break
                if phone_col:
                    info_phone_map = dict(zip(df_info_clean["骑手ID"], df_info_clean[phone_col].fillna("").astype(str).str.strip()))
                    
            if "团队名称" not in df_sht1.columns:
                df_sht1["团队名称"] = ""
            else:
                df_sht1["团队名称"] = df_sht1["团队名称"].fillna("").astype(str).str.replace(r'[\s\u200b\u200c\u200d\u2060\ufeff]+', '', regex=True).str.replace('（', '(').str.replace('）', ')').replace({"nan": "", "None": "", "NAN": "", "null": ""})
                
            if "骑手ID" not in df_sht1.columns:
                df_sht1["骑手ID"] = ""
            else:
                df_sht1["骑手ID"] = df_sht1["骑手ID"].fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "NAN": "", "null": ""})
            
            # Map cities from team names using config_mapping
            if "城市" in df_sht1.columns:
                original_city = df_sht1["城市"].copy().fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "NAN": "", "null": ""})
            else:
                original_city = pd.Series([""] * len(df_sht1), index=df_sht1.index)
            
            if "团队名称" in df_sht1.columns:
                df_sht1["团队名称"] = df_sht1["团队名称"].fillna("").astype(str).str.replace(r'[\s\u200b\u200c\u200d\u2060\ufeff]+', '', regex=True).str.replace('（', '(').str.replace('）', ')').replace({"nan": "", "None": "", "NAN": "", "null": ""})

            if verified_scope:
                config_mapping.update(verified_scope['team_cities'])
            mapped_city = df_sht1["团队名称"].map(config_mapping)
            
            # Use mapped city first, fallback to original city if mapped is nan/null, and finally to '未知'
            df_sht1["城市"] = mapped_city.fillna(original_city)
            df_sht1["城市"] = df_sht1["城市"].replace({"": "未知", "nan": "未知"}).fillna("未知")
            
            # If team name is empty, then city should be empty too!
            df_sht1.loc[df_sht1["团队名称"] == "", "城市"] = ""
            
            # Apply keyword auto-matching logic for teams with "未知" city.
            known_cities_list = sorted(
                [str(c).strip() for c in set(config_mapping.values()) if c and str(c).strip() not in ["", "未知", "nan", "None"]],
                key=len,
                reverse=True
            )
            
            unk_teams = df_sht1[df_sht1["城市"] == "未知"]["团队名称"].dropna().unique().tolist()
            unk_teams = [str(t).strip() for t in unk_teams if str(t).strip() != "" and str(t).strip() != "nan"]
            
            auto_mapped = {}
            for t in unk_teams:
                for city_name in known_cities_list:
                    if city_name in t:
                        auto_mapped[t] = city_name
                        break
                        
            if auto_mapped:
                auto_mapped_str = ", ".join([f"'{t}'->'{c}'" for t, c in auto_mapped.items()])
                yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 发现团队名称包含城市关键字，自动分配归属: {auto_mapped_str}", "INFO")
                
                # Update config_mapping
                config_mapping.update(auto_mapped)
                
                # Re-evaluate
                mapped_city = df_sht1["团队名称"].map(config_mapping)
                df_sht1["城市"] = mapped_city.fillna(original_city)
                df_sht1["城市"] = df_sht1["城市"].replace({"": "未知", "nan": "未知"}).fillna("未知")
                df_sht1.loc[df_sht1["团队名称"] == "", "城市"] = ""
                
                # Save auto mapped config back
                if config_file:
                    try:
                        _save_auto_mapped_to_config(config_file, auto_mapped)
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 自动匹配的城市映射已持久化至配置文件", "SUCCESS")
                    except Exception as ex:
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 保存自动城市匹配映射失败: {str(ex)}", "WARN")
            
            missing_teams = df_sht1[df_sht1["城市"] == "未知"]["团队名称"].dropna().unique().tolist()
            missing_teams = [str(t).strip() for t in missing_teams if str(t).strip() != "" and str(t).strip() != "nan"]
            
            # Additional safety: filter out known cities from missing_teams 
            # (in case original_city was empty but the team name was actually a city)
            known_cities = set(config_mapping.values())
            missing_teams = [t for t in missing_teams if t not in known_cities]
            
            if missing_teams:
                # Trigger a pause and wait popup mapping flow!
                import uuid
                import sys
                import threading
                
                uid = str(uuid.uuid4())
                
                # Make sure tasks module is in sys.modules
                try:
                    import tasks
                except Exception:
                    pass
                
                tasks_mod = sys.modules.get('tasks')
                if tasks_mod:
                    global_resume_events = getattr(tasks_mod, 'GLOBAL_RESUME_EVENTS', {})
                    if not hasattr(tasks_mod, 'GLOBAL_RESUME_EVENTS'):
                        setattr(tasks_mod, 'GLOBAL_RESUME_EVENTS', global_resume_events)
                        
                    event = threading.Event()
                    global_resume_events[uid] = {'event': event, 'result': False}
                    
                    yield f'data: {json.dumps({"type": "missing_city", "teams": missing_teams, "uuid": uid})}\n\n'
                    yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 发现未匹配城市的团队 {len(missing_teams)} 个，已弹出选择界面，等待手动指定对应城市及确认...", "WARN")
                    
                    # Await user response by running the blocking event.wait() in a background thread executor
                    await asyncio.get_running_loop().run_in_executor(None, event.wait)
                    
                    user_confirmed = global_resume_events[uid]['result']
                    
                    # Cleanup
                    if uid in global_resume_events:
                        del global_resume_events[uid]
                        
                    if user_confirmed:
                        # Re-read configuration mapping so we have the newly added entries from config.json!
                        if config_file:
                            try:
                                df_conf = _read_file_fast(config_file)
                                config_mapping = _build_config_mapping(df_conf)
                                yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 重新载入团队和城市映射成功，当前城市映射总数: {len(config_mapping)}", "INFO")
                            except Exception as e:
                                yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 重新载入城市映射配置出错: {str(e)}", "ERROR")
                        
                        # Re-evaluate df_sht1["城市"] using updated config_mapping
                        mapped_city = df_sht1["团队名称"].map(config_mapping)
                        df_sht1["城市"] = mapped_city.fillna(original_city)
                        df_sht1["城市"] = df_sht1["城市"].replace({"": "未知", "nan": "未知"}).fillna("未知")
                        df_sht1.loc[df_sht1["团队名称"] == "", "城市"] = ""
                        
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 新映射已应用！当前仍未匹配城市的团队数量为: {len(df_sht1[df_sht1['城市'] == '未知']['团队名称'].dropna().unique().tolist())}", "SUCCESS")
                    else:
                        yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 手动映射被取消。团队仍归类为 '未知' 并继续处理...", "WARN")
                else:
                    yield create_log_event(f"[{time.time()-start_time:.2f}s] -> 警告: 发现未匹配城市的团队 {len(missing_teams)} 个: {', '.join(missing_teams)}，将默认归类为'未知'城市并继续处理。", "WARN")
            
            # 直接应用极速字典映射，彻底省去了多余字典转换循环
            if "骑手姓名" not in df_sht1.columns:
                df_sht1["骑手姓名"] = ""
            df_sht1["骑手身份证"] = df_sht1["骑手ID"].map(info_idcard_map).fillna("")
            df_sht1["骑手手机号"] = df_sht1["骑手ID"].map(info_phone_map).fillna("")
            # If rider ID is empty, they should be empty too!
            df_sht1.loc[df_sht1["骑手ID"] == "", "骑手身份证"] = ""
            df_sht1.loc[df_sht1["骑手ID"] == "", "骑手手机号"] = ""
            
            # 风神和发薪平台绑定状态
            # Convert sht1 "骑手ID" to numeric first to perform exact numeric matching with fs_bound_set
            sht1_rid_numeric = pd.to_numeric(df_sht1["骑手ID"], errors='coerce')
            df_sht1["风神绑定"] = sht1_rid_numeric.isin(fs_bound_set).map({True: "已绑定", False: "未绑定"})
            df_sht1.loc[df_sht1["骑手ID"] == "", "风神绑定"] = "未绑定"
            
            upper_idcard = df_sht1["骑手身份证"].str.strip().str.upper()
            df_sht1["发薪平台绑定"] = upper_idcard.isin(sy_bound_set).map({True: "已绑定", False: "未绑定"})
            df_sht1.loc[df_sht1["骑手身份证"] == "", "发薪平台绑定"] = "未绑定"
            
            # 绑定情况 (通过 numpy 极其高能的向量化条件选择)
            import numpy as np
            fs_bind = df_sht1["风神绑定"] == "已绑定"
            sy_bind = df_sht1["发薪平台绑定"] == "已绑定"
            conds = [
                fs_bind & sy_bind,
                fs_bind & (~sy_bind),
                (~fs_bind) & sy_bind
            ]
            choices = [
                "已绑定",
                "天津商翼未绑定",
                "风神未绑定"
            ]
            df_sht1["绑定情况"] = np.select(conds, choices, default="风神，天津商翼均未绑定")
            
            # 是否黑户
            df_sht1["是否黑户"] = upper_idcard.isin(dailing_rid_set).map({True: "是", False: "否"})
            df_sht1.loc[df_sht1["骑手身份证"] == "", "是否黑户"] = "否"
            
            # 收款人信息 (默认填充骑手自身信息)
            df_sht1["收款人ID"] = df_sht1["骑手ID"]
            df_sht1["收款人姓名"] = df_sht1["骑手姓名"]
            df_sht1["收款人身份证号码"] = df_sht1["骑手身份证"]
            df_sht1["收款人手机号码"] = df_sht1["骑手手机号"]
            
            # 如果匹配到是黑户代领
            df_temp_uniq = df_sht1.drop_duplicates(subset=["骑手身份证"], keep="first")
            idcard_to_phone_sht1 = dict(zip(
                df_temp_uniq["骑手身份证"].str.strip().str.upper(),
                df_temp_uniq["骑手手机号"].astype(str).str.strip()
            ))
            idcard_to_id_sht1 = dict(zip(
                df_temp_uniq["骑手身份证"].str.strip().str.upper(),
                df_temp_uniq["骑手ID"].astype(str).str.strip()
            ))

            info_idcard_to_rid = {}
            info_idcard_to_name = {}
            info_idcard_to_phone = {}
            if not df_info.empty:
                df_info_clean = df_info.copy()
                for id_col in ["身份证", "身份证号", "身份证号码"]:
                    if id_col in df_info_clean.columns:
                        df_info_clean[id_col] = df_info_clean[id_col].fillna("").astype(str).str.strip().str.upper()
                        df_info_clean = df_info_clean[
                            (df_info_clean[id_col] != "") & 
                            (df_info_clean[id_col].str.lower() != "nan") & 
                            (df_info_clean[id_col].str.lower() != "none")
                        ]
                        df_info_uniq = df_info_clean.drop_duplicates(subset=[id_col], keep="first")
                        
                        rid_col = "骑手ID" if "骑手ID" in df_info_uniq.columns else None
                        if not rid_col:
                            for c in ["骑手ID", "ID", "骑手"]:
                                if c in df_info_uniq.columns:
                                    rid_col = c
                                    break
                        if rid_col:
                            info_idcard_to_rid = dict(zip(df_info_uniq[id_col], df_info_uniq[rid_col].fillna("").astype(str).str.strip()))
                            
                        name_col = "骑手姓名" if "骑手姓名" in df_info_uniq.columns else None
                        if not name_col:
                            for c in ["骑手姓名", "姓名"]:
                                if c in df_info_uniq.columns:
                                    name_col = c
                                    break
                        if name_col:
                            info_idcard_to_name = dict(zip(df_info_uniq[id_col], df_info_uniq[name_col].fillna("").astype(str).str.strip()))
                            
                        phone_col = "手机号" if "手机号" in df_info_uniq.columns else None
                        if not phone_col:
                            for c in ["手机号", "手机号码", "联系电话", "电话"]:
                                if c in df_info_uniq.columns:
                                    phone_col = c
                                    break
                        if phone_col:
                            info_idcard_to_phone = dict(zip(df_info_uniq[id_col], df_info_uniq[phone_col].fillna("").astype(str).str.strip()))
                        break

            dailing_mask = (df_sht1["是否黑户"] == "是") & (df_sht1["骑手身份证"] != "")
            
            if dailing_mask.any():
                # 1. 代领人身份证列匹配到骑手绑定情况表收款人身份证号码列中
                mapped_payee_idcards = upper_idcard[dailing_mask].map(dailing_idcard_map).fillna("")
                df_sht1.loc[dailing_mask, "收款人身份证号码"] = mapped_payee_idcards
                
                # 2. 收款人姓名在骑手信息表中匹配对应姓名
                mapped_payee_names = upper_idcard[dailing_mask].map(dailing_name_map).fillna("")
                payee_idcard_upper = mapped_payee_idcards.str.strip().str.upper()
                df_sht1.loc[dailing_mask, "收款人姓名"] = payee_idcard_upper.map(info_idcard_to_name).fillna(mapped_payee_names).fillna("")
                
                # 3. 骑手绑定情况表中的收款人手机号码使用收款人身份证号码在骑手信息表中匹配手机号列
                df_sht1.loc[dailing_mask, "收款人手机号码"] = payee_idcard_upper.map(info_idcard_to_phone).fillna(payee_idcard_upper.map(idcard_to_phone_sht1)).fillna("")
                
                # 4. 骑手绑定情况表中的收款人ID使用收款人身份证号码在骑手信息表中匹配骑手ID列
                df_sht1.loc[dailing_mask, "收款人ID"] = payee_idcard_upper.map(info_idcard_to_rid).fillna(payee_idcard_upper.map(idcard_to_id_sht1)).fillna("")
                
                # 5. 并且绑定情况列内容为 【流程状态列值】代发（代领人姓名ID：收款人ID）, id为空时为【流程状态列值】代发（代领人姓名）
                df_dailing_only = df_sht1[dailing_mask].copy()
                dailing_upper_cards = df_dailing_only["骑手身份证"].str.strip().str.upper()
                
                status_vals = dailing_upper_cards.map(dailing_status_map).fillna("")
                proxy_names = dailing_upper_cards.map(dailing_name_map).fillna("")
                rec_ids = df_dailing_only["收款人ID"].fillna("").astype(str).str.strip()
                
                dailing_bind_status_series = [
                    f"【{status_val}】代发（{proxy_name}ID：{rec_id_str}）" if (rec_id_str and rec_id_str.lower() not in ["nan", "none", ""]) else f"【{status_val}】代发（{proxy_name}）"
                    for status_val, proxy_name, rec_id_str in zip(status_vals, proxy_names, rec_ids)
                ]
                df_sht1.loc[dailing_mask, "绑定情况"] = dailing_bind_status_series
            
            # 列顺序重新定义确保字段无缝对齐
            cols = ["城市", "团队名称", "骑手ID", "骑手姓名", "骑手身份证", "骑手手机号", "风神绑定", "发薪平台绑定", "绑定情况", "收款人ID", "收款人姓名", "收款人身份证号码", "收款人手机号码", "单量汇总", "是否黑户"]
            df_sht1 = df_sht1.reindex(columns=cols)
        else:
            df_sht1 = pd.DataFrame(columns=["城市", "团队名称", "骑手ID", "骑手姓名", "骑手身份证", "骑手手机号", "风神绑定", "发薪平台绑定", "绑定情况", "收款人ID", "收款人姓名", "收款人身份证号码", "收款人手机号码", "单量汇总", "是否黑户"])
            
        # 筛选: 未绑定且单量汇总大于0
        if not df_sht1.empty:
            df_sht2 = df_sht1[(df_sht1["绑定情况"] != "已绑定") & (pd.to_numeric(df_sht1["单量汇总"], errors="coerce").fillna(0) > 0)].copy()
        else:
            df_sht2 = pd.DataFrame()

        # Build rider to city mapping for filtering raw sheets
        rider_id_to_city = {}
        idcard_to_city = {}
        if not df_sht1.empty:
            df_sht1_clean = df_sht1.copy()
            df_sht1_clean["_rid_str"] = df_sht1_clean["骑手ID"].apply(_std_id_str)
            df_sht1_clean["_idcard_str"] = df_sht1_clean["骑手身份证"].fillna("").astype(str).str.strip().str.upper()
            
            rider_id_to_city = dict(zip(df_sht1_clean["_rid_str"], df_sht1_clean["城市"]))
            idcard_to_city = dict(zip(df_sht1_clean["_idcard_str"], df_sht1_clean["城市"]))
 
        # 在进入写盘操作前，在内存中提前进行所有必要的数据格式化和类型转换，避免在 IO 块中消耗 CPU
        dfs_to_clean = [df_sht1, df_sht2, df_fengshen, df_shangyi, df_info, df_detail, df_dailing]
        for c_df in dfs_to_clean:
            if c_df is not None and not c_df.empty:
                _clean_nan_strings(c_df)
                
        # Handle numeric conversion for "单量汇总" to write actual numbers to Excel
        if not df_sht1.empty and "单量汇总" in df_sht1.columns:
            df_sht1["单量汇总"] = pd.to_numeric(df_sht1["单量汇总"], errors="coerce").fillna(0).astype(int)
        if not df_sht2.empty and "单量汇总" in df_sht2.columns:
            df_sht2["单量汇总"] = pd.to_numeric(df_sht2["单量汇总"], errors="coerce").fillna(0).astype(int)
            
        # Handle numeric conversion for "骑手ID" and "收款人ID" to write actual numbers to Excel
        if not df_sht1.empty:
            if "骑手ID" in df_sht1.columns:
                df_sht1["骑手ID"] = pd.to_numeric(df_sht1["骑手ID"], errors="coerce").astype("Int64", errors="ignore")
            if "收款人ID" in df_sht1.columns:
                df_sht1["收款人ID"] = pd.to_numeric(df_sht1["收款人ID"], errors="coerce").astype("Int64", errors="ignore")
        if not df_sht2.empty:
            if "骑手ID" in df_sht2.columns:
                df_sht2["骑手ID"] = pd.to_numeric(df_sht2["骑手ID"], errors="coerce").astype("Int64", errors="ignore")
            if "收款人ID" in df_sht2.columns:
                df_sht2["收款人ID"] = pd.to_numeric(df_sht2["收款人ID"], errors="coerce").astype("Int64", errors="ignore")
        yield create_progress_event(0.7, "准备生成工作簿")
        await asyncio.sleep(0.01)
        yield create_log_event(f"[{time.time()-start_time:.2f}s] " + f"-> 开始写入并生成汇总工作薄 (极速模式): {output_file}", "INFO")
        await asyncio.sleep(0.01)

        # 单城市生成时本工作簿即该城市成品（下载中心按城市归档），
        # 需与城市分表一致，首表为按站点汇总，且不再重复写一份城市工作簿。
        scope_cities = {str(value).strip() for value in (verified_scope or {}).get('team_cities', {}).values()
                        if str(value).strip()}
        single_scope_city = next(iter(scope_cities)) if len(scope_cities) == 1 else None

        def _write_main_wb():
            # 智能内存管理：如果总数据行数适中，不开启 constant_memory（row-by-row flush），
            # 这样 xlsxwriter 就可以利用全内存压缩，写盘速度最高可提升一倍以上！
            # 且避免在 constant_memory 下写头部样式导致后续单元格变为空值 (NaN)
            options = {'strings_to_urls': False, 'strings_to_formulas': False, 'constant_memory': False}
            engine_kwargs = {'options': options}
            
            with pd.ExcelWriter(output_file, engine='xlsxwriter', engine_kwargs=engine_kwargs) as writer:
                workbook = writer.book
                
                # 3. 样式配置
                header_format = workbook.add_format({
                    'bg_color': '#F8CBAD',
                    'font_name': '微软雅黑',
                    'font_size': 10,
                    'align': 'center',
                    'valign': 'vcenter',
                    'border': 1
                })
                
                cell_format = workbook.add_format({
                    'font_name': '微软雅黑',
                    'font_size': 10,
                    'align': 'center',
                    'valign': 'vcenter'
                })
                
                id_num_format = workbook.add_format({
                    'font_name': '微软雅黑',
                    'font_size': 10,
                    'align': 'center',
                    'valign': 'vcenter',
                    'num_format': '0'
                })
                
                # 全部子表统一套用城市版式（微软雅黑10号居中、表头淡橙、ID 列 '0'、列宽自适应）
                sheets_to_write = [
                    (sht1_name, df_sht1, True),
                    (sht2_name, df_sht2, True),
                    (f"{month_only}黑户代领明细", df_dailing, True),
                    ("风神绑定表", df_fengshen, True),
                    ("商翼绑定表", df_shangyi, True),
                    ("骑手详情表", df_detail, True),
                    ("骑手信息表", df_info, True)
                ]
                # 单城市生成时主工作簿即该城市成品，首表按站点汇总。
                if single_scope_city is not None:
                    sheets_to_write.insert(0, (
                        STATION_SUMMARY_SHEET,
                        _station_summary_df(single_scope_city, extracted_month, df_sht1,
                                            period_start, period_end), True))
                
                # 2. 写入数据表：全部改用极速 to_numpy().tolist() 写入，完全替代 Pandas 慢速 to_excel，提速 10 倍以上且极度节省内存
                layout = {}
                for sheet_name, df_obj, apply_style in sheets_to_write:
                    layout[sheet_name] = _fast_write_df_helper(
                        writer, 
                        sheet_name, 
                        df_obj, 
                        header_format if apply_style else None, 
                        cell_format if apply_style else None, 
                        id_num_format if apply_style else None, 
                        apply_style,
                        header_format if sheet_name == STATION_SUMMARY_SHEET and apply_style else None
                    )
                                
            if table_sink is not None:
                from binding_tables import capture_binding_tables
                table_sink.update(capture_binding_tables(output_file, sheets_to_write, layout,
                                                       max_bytes=getattr(table_sink, 'available_bytes', 64 * 1024 * 1024)))
            return layout

        # 在线程中无阻塞写文件，大幅提升UI响应
        # 【极致优化】将汇总表和各个城市拆分表的写盘操作完全并行化，最高可节省一半的写盘时间（约60-80秒）
        from contextvars import copy_context
        from generation_performance import measured
        main_wb_task = loop.run_in_executor(None, copy_context().run, measured('write_workbook')(_write_main_wb))
        
        today_str = datetime.now().strftime('%m%d')
        
        if not df_sht1.empty and single_scope_city is None:
            valid_cities = [c for c in df_sht1["城市"].dropna().unique() if str(c).strip() != ""]
            
            # 建立身份证到城市的映射，用于给 df_dailing 拆分城市
            if not df_dailing.empty and dailing_idcard_col:
                idcard_to_city = dict(zip(df_sht1["骑手身份证"].str.strip().str.upper(), df_sht1["城市"]))
                # 从打款人身份证获取城市，如果没有，尝试从骑手身份证获取
                df_dailing["城市"] = df_dailing[dailing_idcard_col].astype(str).str.strip().str.upper().map(idcard_to_city).fillna("未知")
            
            # 在轻量云容器（通常 1~2 核）下，多进程会导致严重的 CPU 调度冲突与内存拷贝/Pickle 序列化损耗；
            # 改用 ThreadPoolExecutor 具有零进程开销、零对象复制、共享内存的优势，性能可成倍提高，完美契合容器环境。
            # 改用 ProcessPoolExecutor 绕过 GIL 限制，并发写盘
            
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                tasks = []
                for city in valid_cities:
                    df_city_sht1 = df_sht1[df_sht1["城市"] == city].copy()
                    df_city_sht2 = df_sht2[df_sht2["城市"] == city].copy()
                    df_city_dailing = df_dailing[df_dailing.get("城市") == city].copy() if not df_dailing.empty and "城市" in df_dailing.columns else pd.DataFrame()
                    
                    tasks.append(
                        loop.run_in_executor(
                            executor,
                            _write_city_wb_worker,
                            city,
                            extracted_month,
                            today_str,
                            output_dir,
                            sht1_name,
                            sht2_name,
                            df_city_sht1,
                            df_city_sht2,
                            df_city_dailing,
                            period_start,
                            period_end
                        )
                    )
                
                # 并发等待汇总工作薄和所有城市工作薄全部完成
                results = await asyncio.gather(main_wb_task, *tasks)
                layout = results[0]
                city_results = results[1:]
                yield create_log_event(f"[{time.time()-start_time:.2f}s] " + "-> 汇总工作薄及各城市表并发写入完成！", "INFO")
                
            for cw in city_results:
                yield create_log_event(f"[{time.time()-start_time:.2f}s] " + f"  -> 成功极速生成: {cw}", "SUCCESS")
        else:
            layout = await main_wb_task
            message = ("-> 单城市成品工作薄写入完成（已跳过重复城市分表）！" if single_scope_city
                       else "-> 汇总工作薄写入完成！")
            yield create_log_event(f"[{time.time()-start_time:.2f}s] " + message, "INFO")

        # 计算看板统计数据
        df_stats_base = df_sht1
        
        stats_data = {}
        if not df_stats_base.empty:
            overall_stats = {
                "total_riders": len(df_stats_base),
                "total_orders": int(pd.to_numeric(df_stats_base["单量汇总"], errors='coerce').fillna(0).sum()),
                "fengshen_bind_count": len(df_stats_base[df_stats_base["风神绑定"] == "已绑定"]),
                "shangyi_bind_count": len(df_stats_base[df_stats_base["发薪平台绑定"] == "已绑定"]),
                "fully_bound_count": len(df_stats_base[df_stats_base["绑定情况"] == "已绑定"]),
                "black_count": len(df_stats_base[df_stats_base["是否黑户"] == "是"])
            }
            overall_stats["fengshen_bind_rate"] = f"{(overall_stats['fengshen_bind_count'] / overall_stats['total_riders'] * 100):.2f}%" if overall_stats["total_riders"] > 0 else "0.00%"
            overall_stats["shangyi_bind_rate"] = f"{(overall_stats['shangyi_bind_count'] / overall_stats['total_riders'] * 100):.2f}%" if overall_stats["total_riders"] > 0 else "0.00%"

            city_stats = {}
            for city in df_stats_base["城市"].unique():
                temp_city = str(city).strip()
                if temp_city in ("", "nan", "未知"): continue
                city_df = df_stats_base[df_stats_base["城市"] == city]
                
                stations = []
                if not city_df.empty:
                    # 使用极其高能的 Pandas 向量化 groupby + agg 一次性聚合出所有站点的指标，彻底消除 nested Python for 循环
                    city_df_calc = city_df.copy()
                    city_df_calc["is_fs_bind"] = city_df_calc["风神绑定"] == "已绑定"
                    city_df_calc["is_sy_bind"] = city_df_calc["发薪平台绑定"] == "已绑定"
                    city_df_calc["is_fully_bound"] = city_df_calc["绑定情况"] == "已绑定"
                    city_df_calc["is_black"] = city_df_calc["是否黑户"] == "是"
                    city_df_calc["orders"] = pd.to_numeric(city_df_calc["单量汇总"], errors='coerce').fillna(0)
                    
                    df_grp = city_df_calc.groupby("团队名称").agg(
                        total_riders=("骑手ID", "size"),
                        fs_bind_count=("is_fs_bind", "sum"),
                        sy_bind_count=("is_sy_bind", "sum"),
                        fully_bound_count=("is_fully_bound", "sum"),
                        black_count=("is_black", "sum"),
                        total_orders=("orders", "sum")
                    ).reset_index()
                    
                    for _, row in df_grp.iterrows():
                        t_total = int(row["total_riders"])
                        if t_total == 0: continue
                        t_fs = int(row["fs_bind_count"])
                        t_sy = int(row["sy_bind_count"])
                        t_black = int(row["black_count"])
                        t_orders = int(row["total_orders"])
                        t_fully = int(row["fully_bound_count"])
                        stations.append({
                            "station_name": str(row["团队名称"]),
                            "total_riders": t_total,
                            "total_orders": t_orders,
                            "fengshen_bind_rate": f"{(t_fs / t_total * 100):.2f}%",
                            "shangyi_bind_rate": f"{(t_sy / t_total * 100):.2f}%",
                            "fully_bound_count": t_fully,
                            "black_count": t_black
                        })
                
                c_total = len(city_df)
                c_fs = len(city_df[city_df["风神绑定"] == "已绑定"])
                c_sy = len(city_df[city_df["发薪平台绑定"] == "已绑定"])
                c_fully = len(city_df[city_df["绑定情况"] == "已绑定"])
                c_black = len(city_df[city_df["是否黑户"] == "是"])
                c_orders = int(pd.to_numeric(city_df["单量汇总"], errors='coerce').fillna(0).sum())
                city_stats[temp_city] = {
                    "total_riders": c_total,
                    "total_orders": c_orders,
                    "fengshen_bind_count": c_fs,
                    "shangyi_bind_count": c_sy,
                    "fengshen_bind_rate": f"{(c_fs / c_total * 100):.2f}%" if c_total > 0 else "0.00%",
                    "shangyi_bind_rate": f"{(c_sy / c_total * 100):.2f}%" if c_total > 0 else "0.00%",
                    "fully_bound_count": c_fully,
                    "black_count": c_black,
                    "stations": stations
                }

            # Extract min and max date from Column A of 骑手数据明细
            min_date_str = ""
            max_date_str = ""
            date_df = target_detail_df if 'target_detail_df' in locals() and not target_detail_df.empty else (df_detail if 'df_detail' in locals() else pd.DataFrame())
            if not date_df.empty:
                date_col = None
                if "日期" in date_df.columns:
                    date_col = "日期"
                elif len(date_df.columns) > 0:
                    date_col = date_df.columns[0]
                
                if date_col:
                    try:
                        parsed_dates = pd.to_datetime(date_df[date_col], errors='coerce')
                        valid_dates = parsed_dates.dropna()
                        if not valid_dates.empty:
                            min_dt = valid_dates.min()
                            max_dt = valid_dates.max()
                            min_date_str = f"{min_dt.year}年{min_dt.month}月{min_dt.day}日"
                            max_date_str = f"{max_dt.year}年{max_dt.month}月{max_dt.day}日"
                    except Exception:
                        pass

            stats_data = {
                "overall": overall_stats,
                "cities": city_stats,
                "month": extracted_month
            }
            if min_date_str and max_date_str:
                stats_data["date_range"] = {
                    "min_date": min_date_str,
                    "max_date": max_date_str
                }
            
            # Save to json file
            try:
                stats_file = os.path.join(root_dir, f"stats_{extracted_month}.json")
                with open(stats_file, 'w', encoding='utf-8') as f:
                    json.dump(stats_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                pass
                
        elapsed_time = time.time() - start_time
        yield create_progress_event(1.0, "任务执行完成")
        await asyncio.sleep(0.01)
        yield create_log_event(f"[{time.time()-start_time:.2f}s] " + f">>> 🎉 发薪工具绑定任务执行完成！(全部耗时: {elapsed_time:.2f} s)", "SUCCESS")
        await asyncio.sleep(0.01)
        yield create_finish_event("发薪工具绑定任务执行完成。休眠中...", output_file, stats_data, layout=layout)
        
    except Exception as e:
        import traceback
        err_msg = str(e) + "\n" + traceback.format_exc()
        yield create_log_event(f"发生致命错误: {err_msg}", "ERROR")
        yield create_finish_event("任务异常终止", "", {}, error=err_msg)
