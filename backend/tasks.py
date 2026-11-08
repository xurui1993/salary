# ==========================================
# 异步任务调度与基础功能服务: tasks.py
# 本文件主要用于：
# 1. 封装 Server-Sent Events (SSE) 事件创建方法，向前端推送流式日志
# 2. 包含问题单剔除（跨表匹配剔除薪资表问题单）、蓝橙单价重刷、兼职报表汇总等功能
# 3. 异步包裹启动主薪资计算 (processor) 和发薪合并工具的执行
# ==========================================
import os
import glob
import pandas as pd
import openpyxl
from openpyxl.utils import get_column_letter
import json
import asyncio
from datetime import datetime
import re

def create_log_event(msg, level="INFO"):
    # 处理逻辑：日志输出及前端进度条回调事件生成
    return f"data: {json.dumps({'type': 'log', 'msg': msg, 'level': level})}\n\n"

def create_progress_event(value, text=""):
    # 处理逻辑：create_progress_event 的主要执行逻辑
    return f"data: {json.dumps({'type': 'progress', 'value': value, 'text': text})}\n\n"

def create_finish_event(status="success", result_msg="完成", out_file="", stats_info=None):
    # 处理逻辑：create_finish_event 的主要执行逻辑
    return f"data: {json.dumps({'type': 'finish', 'status': status, 'result_msg': result_msg, 'out_file': out_file, 'stats': stats_info})}\n\n"

def _safe_str_apply(x):
    # 处理逻辑：_safe_str_apply 的主要执行逻辑
    if pd.isna(x): return ""
    if isinstance(x, (int, float)):
        return format(x, ".0f") if float(x) == int(x) else str(x)
    return str(x).strip(' ="\t\r\n')

async def run_remove_problem_orders_gen(salary_file, problem_file):
    # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
    yield create_progress_event(0.1)
    yield create_log_event(">>> 正在解析【问题单剔除工作薄】...", "INFO")
    
    try:
        xls = pd.ExcelFile(problem_file)
        all_problem_data = []

        kw_list = ["不准时单", "物流责", "超时", "t10", "投诉", "差评", "违规虚假", "不准时", "物流", "T10"]

        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(problem_file, sheet_name=sheet_name, dtype=object)
                for c in df.columns: df[c] = df[c].apply(_safe_str_apply)
                df.columns = [str(c).strip() for c in df.columns]

                order_col = None
                if any(kw in sheet_name for kw in ["不准时单", "物流责", "超时", "t10", "不准时", "物流", "T10"]):
                    order_col = next((c for c in df.columns if "运单id" in c.lower()), None)
                elif any(kw in sheet_name for kw in ["投诉", "差评", "违规虚假"]):
                    order_col = next((c for c in df.columns if "运单号" in c), None)

                if not order_col:
                    order_col = next((c for c in df.columns if any(kw in c for kw in ["运单", "订单", "单号"])), None)

                is_remove_col = next((c for c in df.columns if "是否剔除" in c), None)
                reason_col = next((c for c in df.columns if "剔除原因" in c), None)

                if not order_col or not is_remove_col or not reason_col:
                    yield create_log_event(f"-> 跳过子表 [{sheet_name}]：缺少必要的(运单id/号)或(是否剔除/剔除原因)列。", "WARN")
                    continue

                type_name = sheet_name
                sheet_name_lower = sheet_name.lower()
                for kw in kw_list:
                    if kw.lower() in sheet_name_lower:
                        type_name = kw
                        break

                df = df[df[reason_col].notna() & (df[reason_col].str.strip() != "")]
                df = df[df[order_col].notna() & (df[order_col].str.strip() != "")]

                for _, row in df.iterrows():
                    val_id = str(row[order_col]).strip().replace(".0", "").lstrip("'")
                    val_is_rm = str(row[is_remove_col]).strip()
                    val_reason = str(row[reason_col]).strip()
                    all_problem_data.append({
                        "问题单类型": type_name, 
                        "运单号": val_id, 
                        "是否剔除": val_is_rm, 
                        "剔除原因": val_reason 
                    })
            except Exception as e:
                yield create_log_event(f"-> 解析子表 [{sheet_name}] 出错: {e}", "WARN")

        yield create_progress_event(0.3)
        if not all_problem_data:
            yield create_log_event(">>> [警告] 未在问题单工作薄中找到任何有效的剔除记录，操作终止！", "WARN")
            yield create_finish_event("error", "未找到数据")
            return

        df_combined = pd.DataFrame(all_problem_data)

        match_dict = {}
        for _, row in df_combined.iterrows():
            key = f"{row['问题单类型']}_{row['运单号']}"
            match_dict[key] = {
                "是否剔除": row["是否剔除"],
                "剔除原因": row["剔除原因"]
            }

        yield create_log_event(f"-> 成功提取并合并了 {len(match_dict)} 条有效的问题单剔除规则！", "SUCCESS")
        yield create_log_event(">>> 正在打开【工资表工作薄】执行跨表匹配剔除...", "INFO")
        yield create_progress_event(0.5)
        await asyncio.sleep(0.1)

        wb = openpyxl.load_workbook(salary_file)
        if "问题单" not in wb.sheetnames:
            yield create_log_event(">>> [错误] 工资表中未找到【问题单】子表，无法匹配！", "ERROR")
            yield create_finish_event("error", "工资表中无问题单")
            return

        ws_wtd = wb["问题单"]

        type_col_idx, order_col_idx, is_rm_col_idx, reason_col_idx, deduct_col_idx = -1, -1, -1, -1, -1
        for c in range(1, ws_wtd.max_column + 1):
            val = str(ws_wtd.cell(row=1, column=c).value or "").strip()
            if val in ["类型", "问题单类型"]: type_col_idx = c
            elif any(kw in val for kw in ["运单", "订单", "单号"]): order_col_idx = c
            elif "是否剔除" in val: is_rm_col_idx = c
            elif "剔除原因" in val: reason_col_idx = c
            elif "扣款金额" in val: deduct_col_idx = c

        if -1 in [type_col_idx, order_col_idx, is_rm_col_idx, reason_col_idx]:
            yield create_log_event(">>> [错误] 工资表【问题单】子表缺少必要的匹配列！", "ERROR")
            yield create_finish_event("error", "缺少匹配列")
            return

        update_count = 0
        for r in range(2, ws_wtd.max_row + 1):
            c_type = str(ws_wtd.cell(row=r, column=type_col_idx).value or "").strip()
            c_order = str(ws_wtd.cell(row=r, column=order_col_idx).value or "").replace('.0', '').strip().lstrip("'")

            if c_type and c_order:
                key = f"{c_type}_{c_order}"
                if key in match_dict:
                    reason_val = match_dict[key]["剔除原因"]
                    ws_wtd.cell(row=r, column=is_rm_col_idx, value=match_dict[key]["是否剔除"])
                    ws_wtd.cell(row=r, column=reason_col_idx, value=reason_val)

                    if reason_val and deduct_col_idx != -1:
                        ws_wtd.cell(row=r, column=deduct_col_idx, value=0)

                    update_count += 1

        yield create_progress_event(0.7)

        for col_idx in [type_col_idx, order_col_idx, is_rm_col_idx, reason_col_idx, deduct_col_idx]:
            if col_idx != -1:
                col_letter = get_column_letter(col_idx)
                max_len = 0
                for row_val in ws_wtd.iter_rows(min_row=1, max_row=min(ws_wtd.max_row, 300), min_col=col_idx, max_col=col_idx, values_only=True):
                    if row_val[0] is not None:
                        val_len = len(str(row_val[0]).encode('gbk', errors='ignore'))
                        if val_len > max_len: max_len = val_len
                ws_wtd.column_dimensions[col_letter].width = max(11, min(max_len + 3.5, 55))

        archive_sheet_name = "剔除源头"
        if archive_sheet_name in wb.sheetnames: del wb[archive_sheet_name]
        ws_archive = wb.create_sheet(archive_sheet_name)
        ws_archive.sheet_properties.tabColor = "FF0000"

        headers = ["问题单类型", "运单号", "是否剔除", "剔除原因"]
        ws_archive.append(headers)
        for r_data in df_combined.itertuples(index=False):
            ws_archive.append(list(r_data))

        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
        border = Border(left=Side(border_style="thin", color="000000"), right=Side(border_style="thin", color="000000"), 
                        top=Side(border_style="thin", color="000000"), bottom=Side(border_style="thin", color="000000"))
        center_align = Alignment(horizontal="center", vertical="center")
        header_fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")

        for col_idx in range(1, 5):
            col_letter = get_column_letter(col_idx)
            max_len = 0
            for row_idx in range(1, ws_archive.max_row + 1):
                cell = ws_archive.cell(row=row_idx, column=col_idx)
                cell.border = border
                cell.alignment = center_align
                if cell.row == 1:
                    cell.fill = header_fill
                    cell.font = Font(name="微软雅黑", size=10, bold=True)
                else:
                    cell.font = Font(name="微软雅黑", size=10)
                if cell.value is not None:
                    val_len = len(str(cell.value).encode('gbk', errors='ignore'))
                    if val_len > max_len: max_len = val_len
            ws_archive.column_dimensions[col_letter].width = max(12, min(max_len + 3.5, 50))
        ws_archive.freeze_panes = 'A2'

        wb.save(salary_file)
        yield create_progress_event(1.0)
        yield create_log_event(f">>> 🎉 剔除完成！成功匹配并更新了 {update_count} 条记录。", "SUCCESS")
        yield create_log_event(f"-> 源头合集已归档至【{archive_sheet_name}】子表中，列宽已全部自适应排版！", "SUCCESS")
        yield create_finish_event("success", "清理完毕", salary_file)

    except Exception as e:
        yield create_log_event(f">>> [错误] 执行问题单剔除时发生异常: {e}", "ERROR")
        yield create_finish_event("error", str(e))

async def run_raise_price_gen(salary_file, price_file):
    # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
    from collections import defaultdict
    yield create_progress_event(0.1)
    yield create_log_event(">>> 正在解析【蓝橙价格提审】文件...", "INFO")
    
    try:
        if price_file.lower().endswith('.csv'):
            try: df_price = pd.read_csv(price_file, encoding='gbk', dtype=str)
            except: df_price = pd.read_csv(price_file, encoding='utf-8', dtype=str)
        else:
            xls = pd.ExcelFile(price_file)
            sht_name = "兼职价格档案明细" if "兼职价格档案明细" in xls.sheet_names else xls.sheet_names[0]
            df_price = pd.read_excel(price_file, sheet_name=sht_name, dtype=object)
            for c in df_price.columns: df_price[c] = df_price[c].apply(_safe_str_apply)

        for col in df_price.columns:
            df_price[col] = df_price[col].astype(str).str.replace(r'^[="\s\t]+|[="\s\t]+$', '', regex=True)

        rider_id_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['风神骑手ID', '风神骑手id', '骑手ID', '员工ID']), next((i for i, c in enumerate(df_price.columns) if '风神骑手id' in str(c).lower() or (('id' in str(c).lower() or '编号' in str(c)) and ('骑手' in str(c) or '员工' in str(c)))), None))
        rider_name_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['风神骑手姓名', '骑手姓名', '员工姓名', '姓名']), next((i for i, c in enumerate(df_price.columns) if '风神骑手姓名' in str(c) or (('名' in str(c) or '姓名' in str(c)) and ('骑手' in str(c) or '员工' in str(c)))), None))
        date_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['日期', '账单时间', '时间']), next((i for i, c in enumerate(df_price.columns) if '日期' in str(c) or '账单时间' in str(c) or '时间' in str(c)), None))
        station_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['站点名称', '团队名称']), next((i for i, c in enumerate(df_price.columns) if '站点名称' in str(c) or '团队名称' in str(c)), next((i for i, c in enumerate(df_price.columns) if ('团队' in str(c) or '站点' in str(c) or '营业部' in str(c)) and 'id' not in str(c).lower()), None)))
        idcard_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['身份证', '身份证号', '证件号码', '证件']), next((i for i, c in enumerate(df_price.columns) if '身份证' in str(c) or '证件' in str(c)), None))
        price_idx = next((i for i, c in enumerate(df_price.columns) if str(c).strip() in ['价格', '单价', '蓝橙单价', '蓝橙']), next((i for i, c in enumerate(df_price.columns) if '价格' in str(c) or '单价' in str(c) or '蓝橙' in str(c)), None))

        if rider_id_idx is None: rider_id_idx = 2
        if rider_name_idx is None: rider_name_idx = 3

        def _norm_date(val):
            # 处理逻辑：数据规范化清洗，去除空值及格式错误的数据记录
            if pd.isna(val) or val is None: return ""
            s = str(val).strip().split(' ')[0].replace('/', '-')
            try:
                parts = s.split('-')
                if len(parts) >= 3: return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            except: pass
            return s

        price_mapping_idcard = {}
        price_mapping_id = {}
        price_mapping_name = {}

        for _, r in df_price.iterrows():
            try:
                date_val = _norm_date(r.iloc[date_idx]) if date_idx is not None else (_norm_date(r.iloc[1]) if len(r) > 1 else "")
                station_val = str(r.iloc[station_idx]).replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip() if station_idx is not None else (str(r.iloc[5]).replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip() if len(r) > 5 else "")
                price_val = str(r.iloc[price_idx]).strip() if price_idx is not None else (str(r.iloc[8]).strip() if len(r) > 8 else "")
                idcard_val = str(r.iloc[idcard_idx]).strip().upper() if idcard_idx is not None else ""
                r_id = str(r.iloc[rider_id_idx]).replace('.0', '').strip() if rider_id_idx < len(r) else ""
                r_name = str(r.iloc[rider_name_idx]).strip() if rider_name_idx < len(r) else ""
                
                if idcard_val: price_mapping_idcard[f"{date_val}_{station_val}_{idcard_val}"] = price_val
                if r_id: price_mapping_id[f"{date_val}_{station_val}_{r_id}"] = price_val
                if r_name: price_mapping_name[f"{date_val}_{station_val}_{r_name}"] = price_val
            except: pass

        yield create_progress_event(0.3)
        yield create_log_event(f"-> 最新价格档案解析成功 (新主键: {len(price_mapping_idcard)} | ID规则数: {len(price_mapping_id)} | 姓名规则数: {len(price_mapping_name)})", "INFO")
        yield create_log_event(">>> 正在打开【工资表工作薄】进行单价替换...", "INFO")
        await asyncio.sleep(0.1)

        wb = openpyxl.load_workbook(salary_file)
        if "日单量" not in wb.sheetnames or "配送所得表" not in wb.sheetnames:
            yield create_log_event(">>> [错误] 目标工资表缺少必要的【日单量】或【配送所得表】子表！", "ERROR")
            yield create_finish_event("error", "工资表缺少必选子表")
            return

        ws_daily = wb["日单量"]
        
        # 寻找列索引
        header_vals = [str(ws_daily.cell(row=1, column=c).value or "").strip() for c in range(1, ws_daily.max_column + 1)]
        date_col = next((i+1 for i, c in enumerate(header_vals) if '账单' in c or '时间' in c or '列' in c and i==0), 1)
        team_col = next((i+1 for i, c in enumerate(header_vals) if '团队名称' in c), next((i+1 for i, c in enumerate(header_vals) if ('团队' in c and 'id' not in c.lower()) or ('列' in c and i==1)), 2))
        idcard_col = next((i+1 for i, c in enumerate(header_vals) if '身份证' in c or '证件' in c), None)
        id_col = next((i+1 for i, c in enumerate(header_vals) if 'id' in c.lower() or '编号' in c or '列' in c and i==2), 3)
        name_col = next((i+1 for i, c in enumerate(header_vals) if '名' in c and ('骑手' in c or '员工' in c) or '列' in c and i==3), 4)
        price_col = next((i+1 for i, c in enumerate(header_vals) if '价格' in c or '单价' in c or '蓝橙' in c), 9)

        rider_prices_dict = defaultdict(set)
        rider_price_dates_dict = defaultdict(lambda: defaultdict(list))
        no_price_records = []

        for r_idx in range(2, ws_daily.max_row + 1):
            b_date_raw = str(ws_daily.cell(row=r_idx, column=date_col).value or "").strip()
            if not b_date_raw or b_date_raw == "None": continue
            b_date = _norm_date(b_date_raw)
            team_name = str(ws_daily.cell(row=r_idx, column=team_col).value or "").replace(' ','').replace('\u3000','').replace('\xa0','').replace('\n','').replace('\t','').strip()
            r_id = str(ws_daily.cell(row=r_idx, column=id_col).value or "").replace('.0', '').strip()
            r_name = str(ws_daily.cell(row=r_idx, column=name_col).value or "").strip()
            idcard = str(ws_daily.cell(row=r_idx, column=idcard_col).value or "").strip().upper() if idcard_col else ""

            key_idcard = f"{b_date}_{team_name}_{idcard}"
            key_id = f"{b_date}_{team_name}_{r_id}"
            key_name = f"{b_date}_{team_name}_{r_name}"
            
            price = None
            if idcard: price = price_mapping_idcard.get(key_idcard)
            if not price: price = price_mapping_id.get(key_id)
            if not price: price = price_mapping_name.get(key_name)

            if price is not None and str(price).strip() != "" and str(price).lower() != "nan":
                try:
                    price_float = float(price)
                    if price_float == 0.0: price = "无单价"
                    else: price = price_float
                except ValueError: pass
            else: price = "无单价"

            if not price or str(price).strip() == "" or str(price).lower() == "nan": price = "无单价"

            ws_daily.cell(row=r_idx, column=price_col, value=price)
            rider_key = f"{team_name}_{r_id}"
            rider_prices_dict[rider_key].add(str(price))
            rider_price_dates_dict[rider_key][str(price)].append(b_date)
            if price == "无单价": no_price_records.append((b_date, team_name, r_id, r_name))

        def format_dates_streak(date_strs):
            # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
            if not date_strs: return ""
            d_objs = []
            for d in date_strs:
                try: d_objs.append(datetime.strptime(d, '%Y-%m-%d'))
                except: pass
            if not d_objs: return "；".join(date_strs)
            d_objs = sorted(list(set(d_objs)))
            streaks = []
            current_streak = [d_objs[0]]
            for i in range(1, len(d_objs)):
                if (d_objs[i] - current_streak[-1]).days == 1: current_streak.append(d_objs[i])
                else: 
                    streaks.append(current_streak)
                    current_streak = [d_objs[i]]
            streaks.append(current_streak)
            formatted = []
            for streak in streaks:
                start, end = streak[0], streak[-1]
                if start == end: formatted.append(f"{start.day}日")
                else: formatted.append(f"{start.day}日-{end.day}日")
            return "、".join(formatted)

        def to_numeric_if_possible(val_str):
            # 处理逻辑：to_numeric_if_possible 的主要执行逻辑
            if not val_str: return val_str
            try:
                f = float(val_str)
                if f.is_integer(): return int(f)
                return f
            except ValueError: return val_str

        grouped = defaultdict(list)
        for rec in no_price_records: grouped[(rec[1], rec[2], rec[3])].append(rec[0])

        noprice_lookup = {f"{k[0]}_{k[1]}": format_dates_streak(v) + "无单价" for k, v in grouped.items()}

        ws_income = wb["配送所得表"]
        remark_col_idx = -1
        leishen_price_col_idx = -1

        for r in range(1, 6):
            for c in range(1, ws_income.max_column + 1):
                cell_val = str(ws_income.cell(row=r, column=c).value or "").strip()
                if "备注" in cell_val: remark_col_idx = c
                elif "蓝橙单价" in cell_val: leishen_price_col_idx = c

        yield create_progress_event(0.5)
        for r_idx in range(4, ws_income.max_row + 1):
            team_val = str(ws_income.cell(row=r_idx, column=2).value or "").strip()
            id_val = str(ws_income.cell(row=r_idx, column=3).value or "").replace('.0', '').strip()

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

                    if "无单价" in prices_set: prices_set.remove("无单价")

                    if leishen_price_col_idx != -1:
                        if not prices_set: final_leishen_price = "无单价"
                        else:
                            prices_list = sorted(list(prices_set))
                            if len(prices_list) == 1: final_leishen_price = to_numeric_if_possible(prices_list[0])
                            else: final_leishen_price = ";".join([str(x) for x in prices_list])
                        ws_income.cell(row=r_idx, column=leishen_price_col_idx, value=final_leishen_price)
                else:
                    if leishen_price_col_idx != -1: ws_income.cell(row=r_idx, column=leishen_price_col_idx, value="无单价")

                if remark_col_idx != -1:
                    if remark_parts: ws_income.cell(row=r_idx, column=remark_col_idx, value="；".join(remark_parts))
                    else: ws_income.cell(row=r_idx, column=remark_col_idx, value="")

        yield create_progress_event(0.7)
        yield create_log_event(">>> 正在执行薪资方案比对及精准标红...", "SYSTEM")

        from openpyxl.styles import PatternFill
        red_fill = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
        no_fill = PatternFill(fill_type=None)
        
        plan_col_idx = -1
        for r in range(1, min(6, ws_income.max_row + 1)):
            for c in range(1, ws_income.max_column + 1):
                if "薪资方案" in str(ws_income.cell(row=r, column=c).value or ""):
                    plan_col_idx = c
                    break
            if plan_col_idx != -1: break

        if leishen_price_col_idx != -1 and plan_col_idx != -1:
            def is_equal(v1, v2):
                # 处理逻辑：is_equal 的主要执行逻辑
                s1 = str(v1).strip() if v1 is not None else ""
                s2 = str(v2).strip() if v2 is not None else ""
                if s1 == s2: return True
                try: return float(s1) == float(s2)
                except: return False

            for r_idx in range(4, ws_income.max_row + 1):
                cell_plan = ws_income.cell(row=r_idx, column=plan_col_idx)
                cell_plan.fill = no_fill
                
                val_lei = ws_income.cell(row=r_idx, column=leishen_price_col_idx).value
                val_plan = cell_plan.value
                
                s_lei = str(val_lei).strip() if val_lei is not None else ""
                s_plan = str(val_plan).strip() if val_plan is not None else ""
                
                if s_lei and s_plan and s_lei != "无单价" and not is_equal(val_lei, val_plan):
                    cell_plan.fill = red_fill

        yield create_log_event(">>> 🎯 薪资方案比对完成，差异项已无情标红！", "SUCCESS")
        
        wb.save(salary_file)

        yield create_progress_event(1.0)
        yield create_log_event(f">>> 🎉 蓝橙单价重刷全部完成！新文件已覆盖: {os.path.basename(salary_file)}", "SUCCESS")
        yield create_finish_event("success", "提审重刷完毕", salary_file)
    except Exception as e:
        yield create_log_event(f">>> [错误] 重刷蓝橙单价时发生异常: {e}", "ERROR")
        yield create_finish_event("error", str(e))

async def run_summary_parttime_gen(folder, city):
    import glob
    import re
    import shutil
    import openpyxl
    import pandas as pd
    import datetime

    yield create_progress_event(0.1)
    yield create_log_event(f">>> 📊 正在拼装【{city}兼职已发汇总】卷轴...", "SYSTEM")

    try:
        inc_records = []
        fun_records = []

        yield create_progress_event(0.2)
        yield create_log_event(">>> 正在提取目录下已有工作簿进行极速合并...", "SYSTEM")

        files = glob.glob(os.path.join(folder, "*.xlsx"))
        yield create_log_event(f"已发现 {len(files)} 个待处理工作簿，开始合并...", "INFO")
        await asyncio.sleep(0.1)

        def extract_month_from_filenames(file_list):
            for f in file_list:
                fname = os.path.basename(f)
                if "~$" in fname or "兼职已发汇总" in fname:
                    continue

                # 1. 匹配如 06.01-06.15, 6.1-6.15, 2024.06.01
                m1 = re.search(r'(?:20\d{2}[\.\-\/]?)?(\d{1,2})[\.\-\/]\d{1,2}(?:\s*-\s*(?:20\d{2}[\.\-\/]?)?(\d{1,2})[\.\-\/]\d{1,2})?', fname)
                if m1:
                    month_num = int(m1.group(1))
                    if 1 <= month_num <= 12:
                        return f"{month_num}月"

                # 2. 匹配如 06月, 6月, 2024年6月
                m2 = re.search(r'(\d{1,2})\s*月', fname)
                if m2:
                    month_num = int(m2.group(1))
                    if 1 <= month_num <= 12:
                        return f"{month_num}月"

                # 3. 匹配如 0601-0615
                m3 = re.search(r'(?<!\d)(\d{2})\d{2}\s*-\s*\d{4}(?!\d)', fname)
                if m3:
                    month_num = int(m3.group(1))
                    if 1 <= month_num <= 12:
                        return f"{month_num}月"

            now = datetime.datetime.now()
            return f"{now.month}月"

        extracted_month = extract_month_from_filenames(files)

        def get_clean_headers(raw_headers):
            headers = []
            seen = {}
            for i, h in enumerate(raw_headers):
                if h is None:
                    h_str = f"Unnamed_{i}"
                else:
                    h_str = str(h).strip()
                    h_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', h_str)
                    if not h_str:
                        h_str = f"Unnamed_{i}"

                if h_str in seen:
                    seen[h_str] += 1
                    headers.append(f"{h_str}_{seen[h_str]}")
                else:
                    seen[h_str] = 0
                    headers.append(h_str)
            return headers

        for i, f_path in enumerate(files):
            yield create_progress_event(0.2 + 0.6 * ((i + 1) / max(1, len(files))))
            f_name = os.path.basename(f_path)
            if "~$" in f_name or "(重复)" in f_name or "蓝橙无单价" in f_name or "兼职已发汇总" in f_name:
                continue

            wb_name_no_ext = os.path.splitext(f_name)[0]

            try:
                wb = openpyxl.load_workbook(f_path, data_only=True, read_only=True)
            except Exception as e:
                yield create_log_event(f"跳过不可读文件: {f_name} - {str(e)}", "WARN")
                continue

            # 1. 安全基金
            try:
                if "安全基金" in wb.sheetnames:
                    ws_fun = wb["安全基金"]
                    rows = list(ws_fun.iter_rows(values_only=True))
                    if len(rows) >= 1:
                        h_row_idx = 0
                        for r_idx in range(min(3, len(rows))):
                            if any(x is not None and str(x).strip() for x in rows[r_idx]):
                                h_row_idx = r_idx
                                break

                        raw_headers = rows[h_row_idx]
                        clean_headers = get_clean_headers(raw_headers)

                        for row_data in rows[h_row_idx + 1:]:
                            if any(x is not None and str(x).strip() not in ["", "0", "None", "nan", "NaN"] for x in row_data):
                                rec = {"工作薄名称": wb_name_no_ext}
                                for col_name, val in zip(clean_headers, row_data):
                                    rec[col_name] = val
                                fun_records.append(rec)
            except Exception as err:
                yield create_log_event(f"读取【安全基金】暂存失败 ({f_name}): {err}", "WARN")

            # 2. 配送所得表
            try:
                if "配送所得表" in wb.sheetnames:
                    ws_inc = wb["配送所得表"]
                    rows = list(ws_inc.iter_rows(values_only=True))
                    if len(rows) >= 1:
                        h_row_idx = 2 if len(rows) >= 3 else 0
                        best_score = -1
                        for r_idx in range(min(5, len(rows))):
                            str_count = sum(1 for x in rows[r_idx] if x is not None and isinstance(x, str) and str(x).strip())
                            if str_count > best_score:
                                best_score = str_count
                                h_row_idx = r_idx

                        raw_headers = rows[h_row_idx]
                        clean_headers = get_clean_headers(raw_headers)

                        # 收集所有非空数据行（源表 配送所得表 末尾通常带"合计"汇总行）
                        data_rows = []
                        for row_data in rows[h_row_idx + 1:]:
                            if any(x is not None and str(x).strip() not in ["", "0", "None", "nan", "NaN"] for x in row_data):
                                data_rows.append(row_data)

                        # 排除最后一个"汇总/合计"行：该合计行属于各源表自身的统计行，
                        # 合并为兼职已发汇总时不应参与拼接，以免重复统计。
                        if data_rows:
                            last_row = data_rows[-1]
                            is_summary = any(
                                x is not None and any(kw in str(x) for kw in ("合计", "总计", "汇总", "小计"))
                                for x in last_row
                            )
                            if is_summary:
                                yield create_log_event(f"已跳过【配送所得表】末尾汇总行（合计）: {f_name}", "INFO")
                                data_rows = data_rows[:-1]

                        for row_data in data_rows:
                            rec = {"工作薄名称": wb_name_no_ext}
                            for col_name, val in zip(clean_headers, row_data):
                                rec[col_name] = val
                            inc_records.append(rec)
            except Exception as err:
                yield create_log_event(f"读取【配送所得表】暂存失败 ({f_name}): {err}", "WARN")

            try: wb.close()
            except Exception: pass

        yield create_progress_event(0.8)

        if inc_records or fun_records:
            target_city = city
            if not target_city or target_city in ["默认城市", "", "None"]:
                folder_name = os.path.basename(folder.rstrip("/\\"))
                if folder_name and folder_name not in ["uploads", "outputs", "data", "mock"]:
                    target_city = folder_name
                else:
                    target_city = "全国"

            merged_filename = f"{target_city}兼职已发汇总.xlsx"
            merged_filename = re.sub(r'[\\/:*?"<>|\r\n]', '-', merged_filename)
            merged_filepath = os.path.join(folder, merged_filename)

            def build_and_clean_df(records):
                if not records:
                    return pd.DataFrame()

                # 按字典列表构造 DataFrame，自动实现按表头对齐追加与新增表头
                df = pd.DataFrame(records)

                # 保持"工作薄名称"为首列，其后按照出现的列名顺序排列
                cols = ["工作薄名称"] + [c for c in df.columns if c != "工作薄名称"]
                df = df[cols]

                # 保留来源表全部列（含本批次里恰好全为 0 / 空的列），
                # 不再以"列全空"为由剔除，确保汇总表列结构与源表一致、不缺失。
                # 对于兼职已发汇总这类合并场景，空列表示"该批次无此项数据"，应保留而非删掉。
                valid_cols = list(df.columns)
                df = df[valid_cols]

                # 逐单元格数据格式清洗与规范转换
                cleaned_rows = []
                for idx, row in df.iterrows():
                    new_row = []
                    for col in df.columns:
                        val = row[col]
                        if val is None or pd.isna(val):
                            new_row.append("")
                            continue
                        if hasattr(val, 'strftime'):
                            try: val = val.strftime("%Y-%m-%d %H:%M:%S")
                            except: val = str(val)

                        val_str = str(val).strip()
                        val_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', val_str)

                        if val_str.startswith('='): val_str = "'" + val_str
                        if val_str.endswith('.0'): val_str = val_str[:-2]
                        if val_str.lower() in ['nan', 'none', 'inf', '-inf', 'nat']:
                            new_row.append("")
                            continue

                        if not val_str:
                            new_row.append("")
                        elif val_str.isdigit():
                            if len(val_str) < 15:
                                new_row.append(int(val_str))
                            else:
                                new_row.append(str(val_str))
                        else:
                            try:
                                f_val = float(val_str)
                                new_row.append(f_val)
                            except ValueError:
                                new_row.append(val_str)
                    cleaned_rows.append(new_row)

                return pd.DataFrame(cleaned_rows, columns=df.columns)

            yield create_progress_event(0.9)
            yield create_log_event("整理并固化合并数据中...", "INFO")
            await asyncio.sleep(0.1)

            df_inc = build_and_clean_df(inc_records)
            df_fun = build_and_clean_df(fun_records)

            with pd.ExcelWriter(merged_filepath, engine='openpyxl') as writer:
                if not df_inc.empty:
                    df_inc.to_excel(writer, sheet_name="配送所得表", index=False)
                if not df_fun.empty:
                    df_fun.to_excel(writer, sheet_name="安全基金", index=False)

                from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
                from openpyxl.utils import get_column_letter

                border_style = Side(border_style="thin", color="000000")
                border = Border(left=border_style, right=border_style, top=border_style, bottom=border_style)
                font_style = Font(name="微软雅黑", size=10)
                center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
                header_fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")

                for sheet_name in writer.sheets:
                    ws = writer.sheets[sheet_name]
                    max_r = ws.max_row
                    max_c = ws.max_column

                    ws.freeze_panes = 'A2'
                    if getattr(ws, 'sheet_format', None):
                        ws.sheet_format.defaultRowHeight = 19.5
                        ws.sheet_format.customHeight = True

                    for row in ws.iter_rows(min_row=1, max_row=max_r, min_col=1, max_col=max_c):
                        for cell in row:
                            cell.alignment = center_align
                            cell.border = border
                            cell.font = font_style

                            if cell.row == 1:
                                cell.fill = header_fill
                            else:
                                if sheet_name == "配送所得表":
                                    val_str = str(cell.value).strip() if cell.value is not None else ""
                                    if val_str.isdigit() and len(val_str) >= 10: cell.number_format = '0'
                                    elif isinstance(cell.value, (int, float)) and cell.value > 1000000000: cell.number_format = '0'
                                    else: cell.number_format = 'General'
                                else:
                                    if type(cell.value) is int: cell.number_format = '0'
                                    elif type(cell.value) is float: cell.number_format = '0.00'
                                    elif type(cell.value) is str and str(cell.value).isdigit() and len(str(cell.value)) >= 15: cell.number_format = '@'

                    for col_idx in range(1, max_c + 1):
                        col_letter = get_column_letter(col_idx)
                        max_length = 0
                        for row_val in ws.iter_rows(min_row=1, max_row=min(500, max_r), min_col=col_idx, max_col=col_idx, values_only=True):
                            val = row_val[0]
                            if val is not None:
                                val_str = str(val)
                                val_len = len(val_str.encode('gbk', errors='ignore'))
                                if val_len > max_length: max_length = val_len
                        ws.column_dimensions[col_letter].width = max(11, min(max_length + 3.5, 55))

            # 同步保存至 outputs/兼职已发汇总/动态月份值/城市/文件名
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            output_dir = os.path.abspath(os.path.join(project_root, "outputs", "兼职已发汇总", extracted_month, target_city))
            os.makedirs(output_dir, exist_ok=True)
            output_filepath = os.path.join(output_dir, merged_filename)
            try:
                shutil.copy2(merged_filepath, output_filepath)
                yield create_log_event(f">>> 📁 汇总文件已成功同步至任务下载模块: outputs/兼职已发汇总/{extracted_month}/{target_city}/{merged_filename}", "SUCCESS")
            except Exception as copy_err:
                yield create_log_event(f">>> ⚠️ 同步至任务下载目录提示: {copy_err}", "WARN")

            yield create_progress_event(1.0)
            yield create_log_event(f">>> 🎉 成功合并文件，并完成金装美化，存至: {merged_filepath}", "SUCCESS")
            yield create_finish_event("success", f"{target_city}兼职已发汇总已生成", output_filepath)
        else:
            yield create_log_event(">>> 所选目录为空或只有无关文件，未生成合并总表~", "WARN")
            yield create_finish_event("error", "所选目录为空")

    except Exception as e:
        yield create_log_event(f"合并报表时出现意外: {e}", "ERROR")
        yield create_finish_event("error", str(e))

async def run_main_calculation_gen(city, selected_option, source_folder, base_path, theme, enable_interceptor=False, enable_cross_station_merge=False, deductionRules=None, taskQueue=None, strict_inputs=False, manual_template_only=False, force_no_price=False, skip_binding_check=False, input_snapshot=None, prepared_plan=None, verified_inputs=None, output_root=None, cancelled=None):
    # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
    import sys
    import os
    import threading
    import asyncio
    
    try:
        from processor import process_rider_data
    except ImportError as e:
        yield create_log_event(f"Failed to import process_rider_data: {e}", "ERROR")
        yield create_finish_event("error", str(e))
        return

    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    from payroll_control import checkpoint, PayrollStopped
    
    def log_cb(msg, level="INFO"):
        checkpoint(cancelled)
        # 处理逻辑：日志输出及前端进度条回调事件生成
        loop.call_soon_threadsafe(queue.put_nowait, create_log_event(msg, level))
        
    def progress_cb(value, text):
        checkpoint(cancelled)
        # 处理逻辑：日志输出及前端进度条回调事件生成
        loop.call_soon_threadsafe(queue.put_nowait, create_progress_event(value, text))
        
    def finish_cb(status, result_msg, stats_info=None):
        if status != 'cancelled':
            checkpoint(cancelled)
        # 处理逻辑：日志输出及前端进度条回调事件生成
        from payroll_performance import current_session
        session = current_session()
        if session is not None:
            session.status = status
            loop.call_soon_threadsafe(queue.put_nowait, 'data: ' + json.dumps({'type': 'payroll_performance', 'performance': session.public()}, ensure_ascii=False) + '\n\n')
        out_file = result_msg if status == 'success' else ''
        loop.call_soon_threadsafe(queue.put_nowait, create_finish_event(status, result_msg, out_file, stats_info))
        loop.call_soon_threadsafe(queue.put_nowait, None)

    import uuid
    import threading
    global_resume_events = getattr(sys.modules[__name__], 'GLOBAL_RESUME_EVENTS', {})
    setattr(sys.modules[__name__], 'GLOBAL_RESUME_EVENTS', global_resume_events)
    
    def prompt_cb(title, message):
        # 处理逻辑：日志输出及前端进度条回调事件生成
        uid = str(uuid.uuid4())
        event = threading.Event()
        global_resume_events[uid] = {'event': event, 'result': False}
        prompt_event_str = f"data: {json.dumps({'type': 'prompt', 'uuid': uid, 'title': title, 'message': message})}\n\n"
        loop.call_soon_threadsafe(queue.put_nowait, prompt_event_str)
        try:
            while not event.wait(0.25):
                checkpoint(cancelled)
            checkpoint(cancelled)
            return global_resume_events[uid]['result']
        finally:
            global_resume_events.pop(uid, None)
        
    def worker():
        # 处理逻辑：worker 的主要执行逻辑
        import time
        import os
        start_time = time.time()
        try:
            items = os.listdir(source_folder)
            
            tasks_to_run = []
            
            # Helper to extract city from template file
            def get_city_from_template(template_path):
                if prepared_plan and os.path.basename(template_path) == os.path.basename(prepared_plan.get('template', '')):
                    return prepared_plan['city']
                try:
                    import pandas as pd
                    df = pd.read_excel(template_path, sheet_name="申请名单", nrows=15)
                    city_col = next((c for c in df.columns if "城市" in str(c)), None)
                    if city_col is not None:
                        for val in df[city_col].dropna():
                            val_str = str(val).strip()
                            if val_str and val_str.lower() not in ['nan', 'none']:
                                return val_str
                except Exception as e:
                    pass
                return None

            if taskQueue is not None and len(taskQueue) > 0:
                for d in taskQueue:
                    t_path = os.path.join(source_folder, d)
                    if manual_template_only and (not os.path.isfile(t_path) or "template" not in os.path.basename(t_path).lower() or not t_path.lower().endswith((".xlsx", ".xls")) or os.path.basename(t_path).startswith(("~$", "."))):
                        raise ValueError("手动兼职核算必须上传 template 模板（.xlsx / .xls），其他资料可选")
                    if os.path.exists(t_path):
                        task_dir = os.path.dirname(t_path)
                        t_file = os.path.basename(t_path)
                        city_name = get_city_from_template(t_path) or os.path.basename(task_dir)
                        tasks_to_run.append({
                            "task_dir": task_dir,
                            "template_file": t_file,
                            "city_name": city_name,
                            "queue_id": d
                        })
            else:
                # Discover recursively
                for root, dirs, files in os.walk(source_folder):
                    for file in files:
                        if ("template" in file.lower()) and file.lower().endswith((".xlsx", ".xls")) and not file.startswith('~$') and not file.startswith('.'):
                            t_path = os.path.join(root, file)
                            task_dir = root
                            city_name = get_city_from_template(t_path) or os.path.basename(task_dir)
                            tasks_to_run.append({
                                "task_dir": task_dir,
                                "template_file": file,
                                "city_name": city_name,
                                "queue_id": os.path.relpath(t_path, source_folder)
                            })
                            
            if manual_template_only and not tasks_to_run:
                raise ValueError("手动兼职核算必须上传 template 模板（.xlsx / .xls），其他资料可选")

            if len(tasks_to_run) == 0:
                # Fallback to subdirectories if no templates found
                for d in items:
                    subdir_path = os.path.join(source_folder, d)
                    if os.path.isdir(subdir_path) and not d.startswith('__'):
                        tasks_to_run.append({
                            "task_dir": subdir_path,
                            "template_file": None,
                            "city_name": d,
                            "queue_id": d
                        })
            
            if len(tasks_to_run) > 0:
                log_cb(f">>> 📦 检测到批量任务队列，共有 {len(tasks_to_run)} 个核算任务待执行...", "INFO")
                all_stats = {}
                task_outs = []
                out_folder_final = ""
                
                import datetime
                batch_id = f"批量任务_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                
                for idx, task in enumerate(tasks_to_run):
                    task_dir = task["task_dir"]
                    t_file = task["template_file"]
                    city_name = task["city_name"]
                    queue_id = task["queue_id"]
                    
                    log_cb(f"\n>>> 🚀 开始执行子任务 [{idx+1}/{len(tasks_to_run)}]: {queue_id}", "INFO")
                    
                    task_stats = None
                    task_out = ""
                    task_error = None
                    
                    def batch_finish_cb(status, result_msg, stats_info=None):
                        nonlocal task_stats, task_out, task_error
                        if status == 'error':
                            task_error = result_msg
                        else:
                            task_out = result_msg
                            task_stats = stats_info

                    try:
                        process_rider_data(
                            city_name,
                            selected_option,
                            task_dir,
                            base_path,
                            log_cb,
                            progress_cb,
                            batch_finish_cb,
                            theme,
                            enable_interceptor=enable_interceptor,
                            enable_cross_station_merge=enable_cross_station_merge,
                            prompt_callback=prompt_cb,
                            deductionRules=deductionRules,
                            task_name=city_name,
                            batch_id=batch_id,
                            template_file=t_file,
                            strict_inputs=strict_inputs,
                            manual_template_only=manual_template_only,
                            force_no_price=force_no_price,
                            skip_binding_check=skip_binding_check,
                            input_snapshot=input_snapshot,
                            relaxed_optional_inputs=bool(input_snapshot and input_snapshot.get('input_policy')=='readable_delivery_v1'),
                            **({'output_root': output_root} if output_root else {}),
                        )
                    except KeyError as e:
                        task_error = f"[KeyError 缺失关键列]: {e}"
                    except ValueError as e:
                        task_error = f"[ValueError 数据转换失败]: {e}"
                    except Exception as e:
                        task_error = f"[{type(e).__name__}]: {str(e)}"
                        
                    if task_error:
                        if strict_inputs:
                            finish_cb("error", f"核算已停止：{task_error}")
                            return
                        log_cb(f">>> ⚠️ [异常隔离] 子任务 {queue_id} 执行失败: {task_error}，已跳过当前任务，继续执行队列中的下一个文件...", "WARN")
                    else:
                        if task_stats:
                            all_stats[queue_id] = task_stats
                        if task_out:
                            task_outs.append(task_out)
                        log_cb(f">>> ✅ 子任务 {queue_id} 执行成功 | OUT:{task_out}", "SUCCESS")
                        
                if task_outs:
                    out_folder_final = os.path.commonpath(task_outs)
                
                elapsed = time.time() - start_time
                log_cb(f"\n>>> ⏳ 批量任务全部执行完毕，共计耗时: {elapsed:.2f} 秒", "SUCCESS")
                finish_cb("success", out_folder_final or source_folder, {"batch_stats": all_stats})
            else:
                process_rider_data(city, selected_option, source_folder, base_path, log_cb, progress_cb, finish_cb, theme, enable_interceptor=enable_interceptor, enable_cross_station_merge=enable_cross_station_merge, prompt_callback=prompt_cb, deductionRules=deductionRules, strict_inputs=strict_inputs, force_no_price=force_no_price, skip_binding_check=skip_binding_check)
                elapsed = time.time() - start_time
                log_cb(f">>> ⏳ 程序执行完毕，共计耗时: {elapsed:.2f} 秒", "SUCCESS")
        except Exception as e:
            elapsed = time.time() - start_time
            log_cb(f">>> ⏳ 程序异常终止，共计耗时: {elapsed:.2f} 秒", "ERROR")
            finish_cb("error", str(e))

    yield create_log_event('正在开始薪资核算…', 'INFO')
    
    def measured_worker():
        from pathlib import Path
        from payroll_performance import calculation_context
        directory = Path(source_folder).parent if prepared_plan else Path(__file__).resolve().parents[1] / 'runtime' / 'payroll_sessions' / uuid.uuid4().hex
        def stage(label):
            loop.call_soon_threadsafe(queue.put_nowait, 'data: ' + json.dumps({'type': 'payroll_stage', 'text': label}, ensure_ascii=False) + '\n\n')
        try:
            checkpoint(cancelled)
            with calculation_context(directory, (input_snapshot or {}).get('id', ''), stage, verified_inputs):
                worker()
        except PayrollStopped:
            finish_cb('cancelled', '任务已停止，原始资料及已生成文件保留')
        except Exception as exc:
            finish_cb('error', str(exc))
    thread = threading.Thread(target=measured_worker, daemon=True)
    thread.start()
    
    pending_finish = None
    while True:
        event = await queue.get()
        if event is None:
            await asyncio.to_thread(thread.join)
            break
        if cancelled is not None and cancelled.is_set():
            continue
        if event.startswith('data: ') and json.loads(event[6:]).get('type') == 'finish':
            pending_finish = event
            continue
        yield event
    checkpoint(cancelled)
    if pending_finish:
        yield pending_finish

