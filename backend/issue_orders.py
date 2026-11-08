# ==========================================
# 薪资结算合并引擎: aeolus_merge_penalty_records.py, 等整合文件
# 本文件主要用于：
# 1. Excel 文件格式化与解析（工具函数）
# 2. 爬虫引擎（SpiderEngine）抓取相关平台运单数据和违规数据
# 3. 数据清洗引擎（DataCleaner）处理不准时单、超时单、问题单、索赔等
# 4. 数据写入与文件合并操作，最后生成问题单汇总Excel
# ==========================================
from order_metrics import measured
from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment
from tqdm import tqdm
from typing import Any
import asyncio
import datetime
import glob
import json
import logging
import os
import pandas as pd
import random
import re
import requests
import sys
import time
import traceback
import warnings


# ==========================================
# 源文件: aeolus_utils.py
# ==========================================


def format_excel_file(file_path: str) -> None:
    # 处理逻辑：处理文件或目录的选择交互及路径解析
    book = load_workbook(file_path, read_only=False)
    font = Font(name="微软雅黑", size=10, bold=False)
    alignment1 = Alignment(horizontal="center", vertical="center")
    for sheet_name in book.sheetnames:
        sheet = book[sheet_name]
        for row in sheet.iter_rows():
            for cell in row:
                cell.font = font
                cell.alignment = alignment1
    book.save(file_path)

def load_json_config(file_path: str) -> dict:
    # 处理逻辑：配置数据的读取与保存，用于状态持久化
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"配置文件未找到: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"JSON 格式解析失败: {e.msg}", e.doc, e.pos)



# ==========================================
# 源文件: aeolus_spider_engine.py
# ==========================================


class SpiderEngine:
    def __init__(self, config, base_dir=".", target_cities=None, log_cb=print):
        # 处理逻辑：类实例对象的属性及配置初始化构建
        self.config = config
        self.base_dir = base_dir
        self.session = requests.Session()
        self.log_cb = log_cb
        self._init_headers()
        
        # 接口地址
        self.switch_city_url = "https://httpizza.ele.me/lpd.meepo.session/aeolus/switchAgency" #切换城市API
        self.export_url = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.exportTracking/2.0" #运单数据导出API
        self.page_url = "https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.agencyTrackingFs.queryExportTask/2.0" #运单数据列表下载API
        self.bad_unit_url = "https://httpizza.ele.me/xtop/xtop.lpd.quality.control.violation.violationOrderAeolusCenterApi.download/1.0" #服务奖惩下载API
        
        # 处理目标城市：如果指定了则用指定的，否则从配置读取所有
        if target_cities:
            self.target_cities = target_cities
        else:
            self.target_cities = list(self.config.get('cities', {}).keys())

    def _init_headers(self):
        # 处理逻辑：类实例对象的属性及配置初始化构建
        cookie_str = self.config.get('crawler', {}).get('cookie', '')
        if not cookie_str:
            raise ValueError("配置文件中缺少 Cookie，无法启动爬虫")
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/json',
            'Cookie': cookie_str
        }
        self.session.headers.update(headers)

    def handoff_city(self, city_name):
        # 处理逻辑：handoff_city 的主要执行逻辑
        city_code = self.config['cities'].get(city_name)
        if not city_code:
            raise ValueError(f"配置文件中未找到城市: {city_name}")

        city_data = {"toAgencyId": city_code}
        try:
            res = self.session.post(self.switch_city_url, json=city_data)
            res.raise_for_status()
            self.log_cb(f"[系统] 已成功切换至城市: {city_name} (ID: {city_code})")
            return True
        except Exception as e:
            self.log_cb(f"[错误] 切换城市 {city_name} 失败: {str(e)}")
            return False

    def time_stamp(self,date_str):
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        timestamp_s = date_obj.timestamp()
        timestamp_ms = int(timestamp_s * 1000)
        return timestamp_ms
    
    def time_conversion(self, start_time, end_time):
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        start_time = start_time + " 00:00:00"
        end_time = end_time +  " 23:59:59"
        start_time = self.time_stamp(start_time)
        end_time = self.time_stamp(end_time)
        return start_time,end_time

    def all_waybill_export(self, city_name, start_time, end_time):
        # 处理逻辑：将处理完毕的数据格式化后输出写入到外部Excel或CSV文件
        if isinstance(start_time, str):
            year = start_time.split('-')[0]
            month = start_time.split('-')[1]
        else:
            year = str(start_time.year)
            month = f"{start_time.month:02d}" 
        base_dir = self.base_dir
        city_dir = os.path.join(base_dir, city_name)
        city_dir = os.path.join(city_dir, "运单数据")
        year_dir = os.path.join(city_dir, year)
        month_dir = os.path.join(year_dir, month)
        os.makedirs(month_dir, exist_ok=True)

        file_name_xlsx = f"{city_name}{start_time}至{end_time}运单数据.xlsx"
        file_path = os.path.join(month_dir, file_name_xlsx)
        
        timestamp = self.time_conversion(start_time, end_time)
        
        res_body = {
            "params": {
                "request": {
                    "trackingFinishStart": timestamp[0],
                    "trackingFinishEnd": timestamp[1],
                    "trackingFinishTimePeriodList": ["0-86400"],
                    "merchantConsumerDistanceStart": "0",
                    "merchantConsumerDistanceEnd": "999999",
                    "payAmountStart": "0",
                    "payAmountEnd": "999999",
                    "exportType": 1
                }
            }
        }
        self.log_cb(f"[导出] 正在请求 {city_name} 的运单数据...")
        export_res = self.session.post(self.export_url, json=res_body)
        export_res.raise_for_status()
        max_retries = 150
        for i in range(max_retries):
            # 防止恶意访问风险，使用随机休眠
            time.sleep(random.uniform(3.0, 5.5))
            page_res = self.session.post(self.page_url, json={"params": {"request": {"current":1,"pageSize":20}}})
            page_res.raise_for_status()
            re_data = json.loads(page_res.text)["result"]["data"]["data"][0]
            if re_data["statusDesc"] == "导出成功":
                self._download_file(re_data["id"],file_path)
                self.log_cb("[导出] 成功,处理中.........")
                return file_path
            else:
                self.log_cb("[导出] 进行中，请等待..........")
                continue 

    def _download_file(self, file_id, save_path):
        # 处理逻辑：处理文件或目录的选择交互及路径解析
        down_url = 'https://httpizza.ele.me/xtop/xtop.merchant.agencyTrackingFs.agencyTrackingFs.queryTaskUrl/2.0'
        down_data = {
        "params": 
        {"request": {"taskId": file_id}}   
        }
        down_res = self.session.post(down_url,json=down_data)
        down_data = down_res.text
        data_value = json.loads(down_data)
        download_url = data_value["result"]["data"]
        try:
            response = requests.get(download_url, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            file.write(chunk)
                self.log_cb("[下载] 运单数据下载成功")
                self.log_cb("------------"*10)
            else:
                self.log_cb(f"请求失败，状态码: {response.status_code}")
        except Exception as e:
            self.log_cb(f"下载文件时出错: {e}")

    def download_data(self,res,file_path):
        # 处理逻辑：网络请求或爬虫抓取接口，下载外部业务数据
        try:
                if res.status_code != 200:
                    logging.error(f"下载失败，状态码: {res.status_code}")
                    return False
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                    self.log_cb("[下载] 服务奖惩下载成功")
                    self.log_cb("------------"*10)
                logging.info(f"文件已成功下载到: {file_path}")
                return True
        except Exception as e:
                logging.error(f"下载出错: {e}")
                return False

    def all_bad_unit_export(self,city_name,start_time,end_time):
        # 处理逻辑：将处理完毕的数据格式化后输出写入到外部Excel或CSV文件
        if isinstance(start_time, str):
            year = start_time.split('-')[0]
            month = start_time.split('-')[1]
        else:
            year = str(start_time.year)
            month = f"{start_time.month:02d}" 
        base_dir = self.base_dir
        city_dir = os.path.join(base_dir, city_name)
        city_dir = os.path.join(city_dir, "服务奖惩")
        year_dir = os.path.join(city_dir, year)
        month_dir = os.path.join(year_dir, month)
        os.makedirs(month_dir, exist_ok=True)
        file_name_csv = f"{city_name}{start_time}至{end_time}服务奖惩.csv"
        file_name_xlsx = f"{city_name}{start_time}至{end_time}服务奖惩.xlsx"
        file_path_xlsx = os.path.join(month_dir, file_name_xlsx)
        file_path_csv = os.path.join(month_dir, file_name_csv)

        new_column = ["违规编号","日期","运单号","团队名称","骑手id","配送员姓名","违规分类","违规类型","违规原因","违规状态","申诉状态","处罚金额"]
        timestamp = self.time_conversion(start_time,end_time)

        bad_unit_data ={
            "params":
            {"request":
            {
                "violationStartTime":timestamp[0],
                "violationEndTime":timestamp[1],
                "appealStatus":[]
                }
                }}
        self.log_cb(f"[导出] 正在请求 {city_name} 服务奖惩...")
        bad_unit_text = self.session.post(self.bad_unit_url,json=bad_unit_data).text
        bad_unit_json = json.loads(bad_unit_text)

        if bad_unit_json["code"] == 200:
            bad_unit_url = bad_unit_json["result"]["data"]["fileUrl"]
            if bad_unit_url == "":
                self.log_cb("该周期无坏单数据")
                empty_df = pd.DataFrame(columns=new_column)
                empty_df.to_excel(file_path_xlsx, index=False, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}})
                return file_path_xlsx
            else:
                bad_unit_res = requests.get(bad_unit_url)
       
        self.download_data(bad_unit_res,file_path_csv)
        bad_unit_df = pd.read_csv(file_path_csv,encoding='gbk',)
        bad_unit_df = bad_unit_df.map(lambda x: x.strip() if isinstance(x, str) else x)
        bad_unit_df["违规时间"] = pd.to_datetime(bad_unit_df["违规时间"],format="%Y-%m-%d %H:%M:%S") 
        bad_unit_df["运单号"] = bad_unit_df["运单号"].astype(str)
        bad_unit_df["骑手id"] = bad_unit_df["骑手ID"]
        bad_unit_df["配送员姓名"] = bad_unit_df["骑手名称"]
        bad_unit_df["骑手id"] = pd.to_numeric(bad_unit_df["骑手id"],errors='coerce')
        bad_unit_df["团队ID"] = bad_unit_df["团队ID"]
        bad_unit_df["团队名称"] = bad_unit_df["团队名称"]
        bad_unit_df["团队ID"] = pd.to_numeric(bad_unit_df["团队ID"],errors='coerce')
        bad_unit_df["处罚金额"] = bad_unit_df["处罚"].str.replace("元","",regex=False)
        bad_unit_df.drop(["违规来源","剩余申诉时间"], axis=1, inplace=True)
        bad_unit_df["违规时间"] = pd.to_datetime(bad_unit_df["违规时间"]).dt.date
        bad_unit_df.rename(columns={'违规时间': '日期'}, inplace=True)
        bad_unit_df = bad_unit_df[new_column]
        bad_unit_df.to_excel(file_path_xlsx,index=False, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}})
        os.remove(file_path_csv)
        return file_path_xlsx

    def run(self, start_time, end_time):
        # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
        self.log_cb(f"[日期] {start_time}至{end_time}")
        if getattr(self, '_city_switched', False):
            waybill_path = self.all_waybill_export(self.target_cities, start_time, end_time)
            bad_unit_path = self.all_bad_unit_export(self.target_cities, start_time, end_time)
            return waybill_path, bad_unit_path
        elif self.handoff_city(self.target_cities):
                self._city_switched = True
                sleep_time = random.uniform(2, 5)
                self.log_cb(f"休息 {sleep_time:.2f} 秒...")
                time.sleep(sleep_time)
                waybill_path = self.all_waybill_export(self.target_cities, start_time, end_time)
                bad_unit_path = self.all_bad_unit_export(self.target_cities, start_time, end_time)
                return waybill_path,bad_unit_path
        else:
            self.log_cb(f"[跳过] {self.target_cities} 城市切换失败")
            raise RuntimeError(f"切换城市 {self.target_cities} 失败，请检查 Cookie 是否有效")



# ==========================================
# 源文件: aeolus_data_cleaner.py
# ==========================================

# 忽略所有 UserWarning 类型的警告
warnings.filterwarnings("ignore", category=UserWarning)
logger = logging.getLogger(__name__)

class DataCleaner:
    def __init__(self, waybill_path, bad_unit_path):
        # 处理逻辑：类实例对象的属性及配置初始化构建
        self.waybill_data = pd.read_excel(waybill_path,engine="openpyxl",converters={"运单id":str,"订单号":str})
        self.bad_unit_data = pd.read_excel(bad_unit_path,converters={"运单号":str})
        self.bad_unit_data["日期"] = pd.to_datetime(self.bad_unit_data["日期"]).dt.date
        self.bad_unit_data =  self.bad_unit_data.loc[
                            ( self.bad_unit_data["违规状态"]!="不成立") &
                            ( self.bad_unit_data["申诉状态"]!="申诉成功")]

    @classmethod
    def from_frames(cls, waybills, violations, *, copy=True):
        cleaner = cls.__new__(cls)
        cleaner.waybill_data = waybills.copy() if copy else waybills
        cleaner.bad_unit_data = violations.copy() if copy else violations
        cleaner.bad_unit_data["日期"] = pd.to_datetime(cleaner.bad_unit_data["日期"]).dt.date
        cleaner.bad_unit_data = cleaner.bad_unit_data.loc[
            (cleaner.bad_unit_data["违规状态"] != "不成立") &
            (cleaner.bad_unit_data["申诉状态"] != "申诉成功")]
        return cleaner

    def notpunctual_period(self,waybill_data):  ##不准时单判断逻辑 
        data = waybill_data.loc[waybill_data["运单状态"].str.contains("配送成功")].copy()
        if data.empty:
            return data
        dates = self._dates()
        finish = dates.parse(data["运单完成时间"])
        expected = data["平台期望时间"]
        if any(not isinstance(value, str) for value in expected):
            raise TypeError("平台期望时间应为文本")
        blank = expected.eq("")
        ranged = expected.str.contains("~", regex=False)
        preorder = data["运单类型"].eq("预订单")
        selected = blank & data["是否超平台期望时间"].eq("是")
        simple = ~blank & ~ranged
        normalized = expected.astype(object).copy()
        if simple.any():
            deadline = dates.parse(expected.loc[simple])
            normalized.loc[simple] = deadline.astype(object)
            strict = preorder | data["配送标品"].eq("星专送") | data["订单来源"].eq("开放平台")
            delay = (finish.loc[simple] - deadline).dt.total_seconds()
            selected.loc[simple] = delay.gt(0).where(strict.loc[simple], delay.gt(480))
        windows = preorder & ranged & ~blank
        if windows.any():
            parts = expected.loc[windows].str.split("~", expand=True)
            if parts.shape[1] != 2:
                raise ValueError("平台期望时间区间格式无效")
            dates.parse(parts[0])  # Validate the same start value as the old rule.
            deadline = dates.parse(parts[1])
            selected.loc[windows] = finish.loc[windows].gt(deadline)
        data["运单完成时间"] = finish
        data["平台期望时间"] = normalized
        return data.loc[selected]

    def _dates(self):
        from order_dates import OrderDates
        if not hasattr(self, "_date_context"):
            self._date_context = OrderDates()
        return self._date_context

    def _carrier_timeouts(self):
        if not hasattr(self, "_carrier_timeout_cache"):
            data = self.waybill_data.loc[self.waybill_data["是否超骑手T"].eq("是")].copy()
            if data.empty:
                data["超时时长"] = pd.Series(index=data.index, dtype=float)
            else:
                finish = self._dates().parse(data["运单完成时间"])
                data["超时时长"] = self._dates().window(data["骑手考核时间"], finish)
                data["运单完成时间"] = finish
            self._carrier_timeout_cache = data
        return self._carrier_timeout_cache

    def CarrierT_period(self,row):   #超时时长数据处理 骑手T
        # 处理逻辑：CarrierT_period 的主要执行逻辑
        finish_time = row["运单完成时间"]
        assess_time = row["骑手考核时间"]
        if "~" in assess_time :  #考核时间列 时间段处理
            start_time, end_time = assess_time.split("~")
            start_time = pd.to_datetime(start_time)
            end_time = pd.to_datetime(end_time)
            if start_time > finish_time:
                tp_data = (finish_time-start_time)/pd.Timedelta(1,"min")
            else:
                tp_data = (finish_time-end_time)/pd.Timedelta(1,"min")
        else:
            assess_time = pd.to_datetime(assess_time)
            tp_data = (finish_time - assess_time)/pd.Timedelta(1,"min")
        tp_data = round(tp_data,2)
        return tp_data

    def outUserT_period(self,row):   #超时时长数据处理 用户T
        # 处理逻辑：outUserT_period 的主要执行逻辑
        finish_time = row["运单完成时间"]
        assess_time = row["用户期望时间"]
        if "~" in assess_time :  #考核时间列 时间段处理
            start_time, end_time = assess_time.split("~")
            start_time = pd.to_datetime(start_time)
            end_time = pd.to_datetime(end_time)
            if start_time > finish_time:
                tp_data = (finish_time-start_time)/pd.Timedelta(1,"min")
            else:
                tp_data = (finish_time-end_time)/pd.Timedelta(1,"min")
        else:
            assess_time = pd.to_datetime(assess_time)
            tp_data = (finish_time - assess_time)/pd.Timedelta(1,"min")
        tp_data = round(tp_data,2)
        return tp_data

    def waybill(self): #运单数据，剔除欺诈单，配送失败单
        # 处理逻辑：waybill 的主要执行逻辑
        waybill_data = self.waybill_data[
            (self.waybill_data["欺诈是否成立"]=="否")&(self.waybill_data["运单状态"]=="配送成功")
                                          ]
        return waybill_data

    def fraudulent_bills(self): #欺诈单
        # 处理逻辑：fraudulent_bills 的主要执行逻辑
        fraudulent_data = self.waybill_data[self.waybill_data["欺诈是否成立"]=="是"]
        return fraudulent_data
    
    def time_outCarrierT(self):  #超时-骑手T
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        time_outCarrierT_data = self._carrier_timeouts()
        if time_outCarrierT_data.empty:
            return time_outCarrierT_data.assign(超时时长=pd.Series(dtype=float))
        time_outCarrierT_data = time_outCarrierT_data.loc[~((time_outCarrierT_data["站点名称"].str.contains("塘厦|黄江|乌沙|高步|麻涌|嘉富|大运|沙溪|会展中心|南栅|大朗|企石|石排|华强|凫山|清溪|石厦")) &
                                    ((time_outCarrierT_data["超时时长"]>=10) | (time_outCarrierT_data["超时时长"]<=-10)))]  #剔除指定站点的T10数据
        return time_outCarrierT_data

    def claim(self):#索赔
        # 处理逻辑：claim 的主要执行逻辑
        claim_data = self.bad_unit_data [self.bad_unit_data ["违规分类"]=="餐货损"]
        return claim_data

    def bad_reviews(self):   #差评
        # 处理逻辑：bad_reviews 的主要执行逻辑
        bad_reviews_data = self.bad_unit_data[self.bad_unit_data["违规分类"]=="差评"]
        return bad_reviews_data

    def complaints(self):  #投诉
        # 处理逻辑：complaints 的主要执行逻辑
        complaints_data = self.bad_unit_data.loc[(self.bad_unit_data["违规分类"]=="投诉")]
        return complaints_data
    
    def loginfo(self):#物流责
        # 处理逻辑：日志输出及前端进度条回调事件生成
        loginfo_data = self.bad_unit_data[self.bad_unit_data["违规分类"]=="取消"]
        return loginfo_data   

    def notpunctual(self):#不准时
        # 处理逻辑：notpunctual 的主要执行逻辑
        not_pun_data = self.waybill_data[(self.waybill_data["运单类型"]!="即时单") | (self.waybill_data["是否超平台期望时间"]!="否")]
        not_pun_data = not_pun_data.loc[~not_pun_data["站点名称"].str.contains("大润发")]
        not_pun_data = self.notpunctual_period(not_pun_data) #不准时单判断逻辑
        logger.info(f"notpunctual initial rows: {len(not_pun_data)}")
        if not_pun_data["站点名称"].str.contains("三亚", na=False).any():
            time_outCarrierT_data = self.waybill_data[(self.waybill_data["是否超骑手T"]=="是") & (self.waybill_data["站点名称"].str.contains("大润发"))]
            logger.info(f"Adding time_outCarrierT_data rows: {len(time_outCarrierT_data)} to notpunctual result")
            not_pun_data = pd.concat([not_pun_data,time_outCarrierT_data],ignore_index=True)
        logger.info(f"notpunctual final rows: {len(not_pun_data)}")
        return not_pun_data

    def time_outten(self): #T10
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        time_outCarrierT = self._carrier_timeouts()
        if time_outCarrierT.empty:
            return time_outCarrierT.assign(超时时长=pd.Series(dtype=float))
        try:
            t10_data = time_outCarrierT.loc[(time_outCarrierT["站点名称"].str.contains("塘厦|黄江|乌沙|高步|麻涌|嘉富|大运|沙溪|会展中心|南栅|大朗|企石|石排|华强|凫山|清溪|沃尔玛|石厦")) &
                                    ((time_outCarrierT["超时时长"]>=10) | (time_outCarrierT["超时时长"]<=-10)) ]
            return t10_data
        except:
            return  time_outCarrierT.iloc[0:0]

    def time_outUserT(self):  #超时-用户T
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        ttime_outUserT_data = self.waybill_data[self.waybill_data["是否超用户T"]=="是"].copy()
        if ttime_outUserT_data.empty:
            return ttime_outUserT_data.assign(超时时长=pd.Series(dtype=float))
        finish = self._dates().parse(ttime_outUserT_data["运单完成时间"])
        ttime_outUserT_data["超时时长"] = self._dates().window(ttime_outUserT_data["用户期望时间"], finish)
        ttime_outUserT_data["运单完成时间"] = finish
        return ttime_outUserT_data

    @measured("classification_seconds")
    def run(self,data_list):
        # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
        logger.info(f"DataCleaner.run called with: {data_list}")
        data_dict = {
            "有效运单" : self.waybill,
            "超时" : self.time_outCarrierT,
            "索赔" : self.claim,
            "差评" : self.bad_reviews,
            "投诉" : self.complaints,
            "物流责" : self.loginfo,
            "不准时单" : self.notpunctual,
            "用户T" : self.time_outUserT,
            "T10" : self.time_outten,
            "欺诈单" : self.fraudulent_bills
        }
        df_dict= {}
        for data in data_list:
            df_data = data_dict[data]()
            df_dict[data] = df_data
        return df_dict



# ==========================================
# 源文件: aeolus_db_writer.py
# ==========================================


class DBWriter:
    def __init__(self, city_name, start_time,end_time, base_dir="."):
        # 处理逻辑：类实例对象的属性及配置初始化构建
        self.city_name = city_name
        self.start_time = start_time
        self.end_time = end_time
        self.base_dir = base_dir

    def file_path(self,path_type):
        # 处理逻辑：处理文件或目录的选择交互及路径解析
        if isinstance(self.start_time, str):
            year = self.start_time.split('-')[0]
            month = self.start_time.split('-')[1]
        else:
            year = str(self.start_time.year)
            month = f"{self.start_time.month:02d}" 
        base_dir = self.base_dir
        city_dir = os.path.join(base_dir, self.city_name)
        city_dir = os.path.join(city_dir, path_type)
        year_dir = os.path.join(city_dir, year)
        month_dir = os.path.join(year_dir, month)
        os.makedirs(month_dir, exist_ok=True)
        file_name_xlsx = f"{self.city_name}{self.start_time}至{self.end_time}{path_type}.xlsx"
        file_path = os.path.join(month_dir, file_name_xlsx)    
        return file_path
    
    def excel_save(self,type_name,data):
        # 处理逻辑：将处理完毕的数据格式化后输出写入到外部Excel或CSV文件
        data_path = self.file_path(type_name)
        data.to_excel(data_path,index=False, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}})

    def run(self,df_dict):
        # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
        for key,value in df_dict.items():
            self.excel_save(key,value)



# ==========================================
# 源文件: aeolus_merger_files.py
# ==========================================


class MergerFiles:
    def __init__(self,city_name,date, base_dir="."):
        # 处理逻辑：类实例对象的属性及配置初始化构建
        self.city_name = city_name
        if isinstance(date, str):
            self.year = date.split('-')[0]
            self.month = date.split('-')[1]
        else:
           self.year = str(date.year)
           self.month = f"{date.month:02d}" 
        self.files_path = os.path.join(base_dir, self.city_name)

    def merge_files(self,folder_name, log_cb=print):
        # 处理逻辑：处理文件或目录的选择交互及路径解析
        files_path = os.path.join(self.files_path, folder_name, self.year, self.month)
        output_filename = os.path.join(files_path, f"{self.year[2:]}年{self.month}月{folder_name}.xlsx")
        
        pattern = os.path.join(files_path, "*.xlsx")
        files = glob.glob(pattern)
        if output_filename in files:
            os.remove(output_filename)
        log_cb(f"找到 {len(files)} 个文件，开始合并...", "INFO")
        
        df_list = []
        for file in files:
            try:
                if folder_name in ["不准时单","超时","T10","用户T","欺诈单"]:
                    df = pd.read_excel(file,engine="openpyxl",converters={"运单id":str,"订单号":str})
                else:
                    df = pd.read_excel(file,engine="openpyxl",converters={"运单号":str})
                df_list.append(df)
            except Exception as e:
                log_cb(f"读取文件 {os.path.basename(file)} 失败: {e}", "ERROR")

        if not df_list:
            log_cb("没有成功读取到任何数据。", "WARNING")
            return

        merged_df = pd.concat(df_list, ignore_index=True)
        merged_df.to_excel(output_filename, index=False, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}})
        log_cb(f"合并完成！结果已保存至: {output_filename}", "INFO")
        log_cb(f"共合并 {len(merged_df)} 行数据。", "INFO")
        return merged_df

    def run(self,type_list, log_cb=print):
        # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
        data_dcit = {}
        for type in type_list:
            data = self.merge_files(type, log_cb=log_cb)
            data_dcit[type] = data  
        return data_dcit



# ==========================================
# 源文件: aeolus_merge_penalty_records.py
# ==========================================


class MergePenaltyRecords:
    def __init__(self, city_name: str, date: str, base_dir=".") -> None:
        # 处理逻辑：类实例对象的属性及配置初始化构建
        self.city_name = city_name
        self.year = date.split('-')[0]
        self.month = date.split('-')[1]
        city_dir = os.path.join(base_dir, city_name)
        city_dir = os.path.join(city_dir, "汇总")
        year_dir = os.path.join(city_dir, self.year)
        month_dir = os.path.join(year_dir, self.month)
        os.makedirs(month_dir, exist_ok=True)
        self.output_path = os.path.join(month_dir, f"{self.city_name}{self.year[2:]}年{self.month}月问题单.xlsx")
        self.output_path_sum = os.path.join(month_dir, f"{self.city_name}{self.year[2:]}年{self.month}月问题单(汇总).xlsx")

    def format_duration(self, duration):
        # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
        hours, minutes, seconds = map(int, duration.split(':'))
        formatted_time = ""
        if hours > 0:
            formatted_time += f"{hours}小时"
        if minutes > 0:
            formatted_time += f"{minutes}分钟"
        if seconds > 0 or (hours == 0 and minutes == 0):
            formatted_time += f"{seconds}秒"
        return "超平台T"+formatted_time

    def save_dict_to_xlsx(self, sheet_dict, index: bool = False) -> str:
        # 处理逻辑：将处理完毕的数据格式化后输出写入到外部Excel或CSV文件
        if not isinstance(sheet_dict, dict):
            raise TypeError("sheet_dict must be a dict of sheet_name -> DataFrame-like")

        fraud_waybil = sheet_dict.get("欺诈单")
        if isinstance(fraud_waybil, pd.DataFrame):
            fraud_ids = fraud_waybil.get("运单id")
        else:
            fraud_ids = None

        written = 0
        with pd.ExcelWriter(self.output_path, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}}) as writer:
            for sheet_name, data in sheet_dict.items():
                if sheet_name == "欺诈单":
                    continue
                if not isinstance(data, pd.DataFrame):
                    data = pd.DataFrame(data)
                if fraud_ids is not None and not fraud_ids.empty:
                    if "运单号" in data.columns:
                        take_data = data["运单号"].isin(fraud_ids)
                    elif "运单id" in data.columns:
                        take_data = data["运单id"].isin(fraud_ids)
                    else:
                        take_data = pd.Series(False, index=data.index)
                else:
                    take_data = pd.Series(False, index=data.index)
                data = data.loc[~take_data]
                data.to_excel(writer, index=index, sheet_name=sheet_name)
                written += 1
            if written == 0:
                pd.DataFrame().to_excel(writer, index=False, sheet_name="Sheet1")
        format_excel_file(self.output_path)
        return self.output_path

    @measured("summary_seconds")
    def build_sum_data(self, sheet_dict):
        """Project each category before concatenation; keep original scalar rounding."""
        columns = ["类型", "日期", "运单号", "骑手id", "配送员姓名", "团队名称", "事件原因", "处罚金额"]
        pieces = []
        for name, source in sheet_dict.items():
            if name == "欺诈单":
                continue
            # Only output columns are copied, never the entire wide source table.
            data = source.reindex(columns=columns).copy()
            data["类型"] = name
            data["处罚金额"] = source["处罚金额"].fillna(0) if "处罚金额" in source else 0
            if name in ("不准时单", "超时", "T10", "用户T"):
                data["日期"] = pd.to_datetime(source["运单完成时间"], format="%Y-%m-%d %H:%M:%S")
                data["配送员姓名"] = source["骑手名称"]
                data["团队名称"] = source["站点名称"]
                data["运单号"] = source["运单id"]
                if name == "不准时单":
                    values = source["超平台期望送达时长"]
                    reasons = {value: self.format_duration(value if "-" not in value else value[1:])
                               for value in pd.unique(values)}
                    data["事件原因"] = values.map(reasons)
                else:
                    values = source["超时时长"]
                    # Python round and the +/- one minute boundary are contractual.
                    reasons = {}
                    for value in pd.unique(values):
                        rounded = 1 if 0 < value < 1 else -1 if -1 < value < 0 else round(value)
                        reasons[value] = (f"超时{rounded}分钟" if rounded >= 1 else f"提前{abs(rounded)}分钟")
                    data["事件原因"] = values.map(reasons)
            elif name == "物流责":
                data["事件原因"] = source["违规原因"]
            else:
                data["事件原因"] = source.get("违规类型", source.get("违规原因", ""))
            pieces.append(data)
        result = pd.concat(pieces) if pieces else pd.DataFrame(columns=columns)
        fraud = sheet_dict.get("欺诈单")
        if isinstance(fraud, pd.DataFrame) and not fraud.empty:
            result = result.loc[~result["运单号"].isin(set(fraud.get("运单id", [])))]
        return result

    def save_sum_data(self, sheet_dict):
        sum_data = self.build_sum_data(sheet_dict)
        sum_data.to_excel(self.output_path_sum,index=False, engine='xlsxwriter', engine_kwargs={'options': {'constant_memory': True}})
        format_excel_file(self.output_path_sum)



# ==========================================
# 源文件: aeolus_task.py
# ==========================================


def issue_types(city_name):
    if city_name == "东莞":
        return ["差评", "投诉", "物流责", "超时", "T10", "欺诈单"]
    if city_name in ["安宁", "香格里拉", "宜良", "嵩明", "维西"]:
        return ["差评", "投诉", "物流责", "用户T", "索赔", "欺诈单"]
    if city_name == "茂南":
        return ["差评", "投诉", "物流责", "超时", "索赔", "欺诈单"]
    return ["差评", "投诉", "物流责", "不准时单", "欺诈单"]


def generate_dates_between(start_date, end_date):
    # 处理逻辑：处理时间戳、日期字符串格式转换与周期计算
    start_date_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    if start_date_obj > end_date_obj:
        start_date_obj, end_date_obj = end_date_obj, start_date_obj
    current_day = start_date_obj
    dates = []
    while current_day <= end_date_obj:
        dates.append(current_day.strftime("%Y-%m-%d"))
        current_day += datetime.timedelta(days=1)
    return dates

async def run_issue_orders_task(config, base_path, log_cb, progress_cb, finish_cb):
    # 处理逻辑：作为核心异步任务入口，负责启动具体的业务流程计算
    import time
    start_time_total = time.time()
    try:
        from tasks import create_log_event, create_progress_event, create_finish_event
    except ImportError:
        pass
        
    try:
        # config is a dict with crawler.cookie and cities
        run_cfg = config.get('run', {})
        target_cities = run_cfg.get('target_cities', [])
        start_time = run_cfg.get('start_time', "")
        end_time = run_cfg.get('end_time', "")
        
        log_cb("==================================================", "INFO")
        log_cb("🚀 [系统启动] 问题单自动汇集与决策分析引擎启动中...", "INFO")
        log_cb("==================================================", "INFO")
        log_cb(f"📅 [统计范围] 目标数据周期: {start_time} 至 {end_time}", "INFO")
        log_cb(f"📍 [覆盖节点] 目标计算城市数: {len(target_cities)} 个 ({', '.join(target_cities)})", "INFO")
        log_cb("--------------------------------------------------", "INFO")
        
        dates = generate_dates_between(start_time, end_time)
        total_steps = len(target_cities)
        
        for city_idx, city_name in enumerate(target_cities):
            progress_cb(city_idx / total_steps, f"正在处理 {city_name}")
            log_cb(f"▶️ [城市任务] 正在处理城市: 【{city_name}】({city_idx + 1}/{len(target_cities)})", "INFO")
            
            type_list = issue_types(city_name)
            
            mun = 5
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            actual_base_dir = os.path.abspath(os.path.join(project_root, "outputs", "问题单生成"))
            os.makedirs(actual_base_dir, exist_ok=True)
            
            engine = SpiderEngine(config, base_dir=actual_base_dir, target_cities=city_name, log_cb=lambda msg: log_cb(f"   [采集驱动] {msg}", "INFO"))
            
            # Dictionary to collect all chunk DataFrames in memory
            merged_results = {t: [] for t in type_list}
            
            if len(dates) > mun:
                for i in range(0, len(dates), mun): 
                    await asyncio.sleep(0.1) # Yield
                    end_idx = min(i + mun - 1, len(dates) - 1)
                    
                    # Compute progress
                    chunk_ratio = i / len(dates)
                    progress_val = (city_idx + chunk_ratio * 0.7) / total_steps
                    progress_cb(progress_val, f"正在采集 {city_name} 数据 ({dates[i]} - {dates[end_idx]})")
                    
                    log_cb(f"📥 [网络数据] 正在采集 【{city_name}】 的周期段 [{dates[i]} 至 {dates[end_idx]}] 数据...", "INFO")
                    
                    waybill_path, bad_unit_path = engine.run(dates[i], dates[end_idx])
                    if waybill_path is None or bad_unit_path is None:
                        log_cb(f"⚠️ [网络异常] 周期段 [{dates[i]} 至 {dates[end_idx]}] 抓取失败，跳过", "WARN")
                        continue
                        
                    progress_cb((city_idx + (chunk_ratio + mun/len(dates)) * 0.7) / total_steps, f"正在清洗 {city_name} 数据...")
                    log_cb(f"🧹 [数据清洗] 正在执行对 【{city_name}】 已采集切片的数据清洗...", "INFO")
                    cleaner = DataCleaner(waybill_path, bad_unit_path)
                    df_dict = cleaner.run(type_list)
                    
                    # Store in memory instead of writing to disk immediately to save huge I/O time
                    for t in type_list:
                        if t in df_dict and not df_dict[t].empty:
                            merged_results[t].append(df_dict[t])
            else:
                progress_cb((city_idx + 0.2) / total_steps, f"正在采集 {city_name} 周期数据...")
                log_cb(f"📥 [网络数据] 正在采集 【{city_name}】 周期数据段 [{start_time} 至 {end_time}]...", "INFO")
                waybill_path, bad_unit_path = engine.run(start_time, end_time)
                if waybill_path is not None and bad_unit_path is not None:
                    progress_cb((city_idx + 0.6) / total_steps, f"正在清洗 {city_name} 数据...")
                    log_cb(f"🧹 [数据清洗] 正在清洗 【{city_name}】 已采集切片的数据...", "INFO")
                    cleaner = DataCleaner(waybill_path, bad_unit_path)
                    df_dict = cleaner.run(type_list)
                    for t in type_list:
                        if t in df_dict and not df_dict[t].empty:
                            merged_results[t].append(df_dict[t])

            progress_cb((city_idx + 0.8) / total_steps, f"正在合并并生成 {city_name} 汇总文件...")
            log_cb(f"🔄 [数据重构] 正在执行城市级 【{city_name}】 全量差评、超时、投诉、欺诈多维对齐与合并...", "INFO")
            
            type_dict = {}
            for t in type_list:
                if merged_results[t]:
                    type_dict[t] = pd.concat(merged_results[t], ignore_index=True)
                else:
                    type_dict[t] = pd.DataFrame()
            
            progress_cb((city_idx + 0.9) / total_steps, f"正在写盘并建立 Excel 表单...")
            log_cb(f"💾 [生成报表] 正在写入 Excel 工作表并建立本地高速索引表...", "INFO")
            merge_penalty = MergePenaltyRecords(city_name, start_time, base_dir=actual_base_dir)
            merge_penalty.save_dict_to_xlsx(type_dict)
            merge_penalty.save_sum_data(type_dict)
            
            log_cb(f"✅ [本地存储] 汇总分析报告已安全写盘: {merge_penalty.output_path_sum}", "SUCCESS")
            log_cb(f"🎉 [城市完成] 城市 【{city_name}】 的数据流全链处理完毕！", "SUCCESS")
            log_cb("--------------------------------------------------", "INFO")
            
        progress_cb(1.0, "全部处理完成")
        elapsed_time = time.time() - start_time_total
        log_cb("==================================================", "SUCCESS")
        log_cb("🎉 [任务圆满结束] 所有城市问题单自动汇集及汇总生成任务已执行完毕！", "SUCCESS")
        log_cb(f"⏱️ [运行效率] 引擎计算累计耗时: {elapsed_time:.2f} 秒", "SUCCESS")
        log_cb("==================================================", "SUCCESS")
        stats_info = {"elapsed_time": round(elapsed_time, 2)}
        finish_cb("success", "问题单生成完毕", stats_info)
        
    except Exception as e:
        log_cb(f"执行时发生错误: {str(e)}", "ERROR")
        log_cb(traceback.format_exc(), "ERROR")
        finish_cb("error", str(e))
