"""Template-free collection shared by the independent download center.

Only explicitly selected deliverables are published. Raw dependencies stay in
the run directory for diagnostics. This service never invokes payroll code.
"""
from contextlib import contextmanager
from functools import partial
import datetime as dt
import hashlib
import hashlib_compat
import json
import os
from pathlib import Path
import re
from generation_performance import profiled, transition, shared_cache, generation_context, TableExchange
import shutil
from types import SimpleNamespace
import uuid

from collection_errors import CollectionFailure, collection_failure
from download_archive import archive_component, archive_filename
from download_rider_sources import (format_rider_detail_csv, merge_rider_detail_csv,
                                    same_day_rider_info_snapshot)
import fengshen_city_catalog as city_catalog
from fengshen_bill import (BILL_URL, RIDER_BILL_URL, WAYBILL_URL, BillCollectionError,
                           BillRequest, MonthlyBillRequest, BillPageCollector,
                           MonthlyBillPageCollector, atomic_json, validate_profile)
from fengshen_orders import OrderPageCollector, date_batches, validate_order_profile, SHANGHAI
from order_sources import prepare_order_files
from lanorange_catalog import DATASETS as LANORANGE_DATASETS, ALL_CITIES, city_scoped, source_key, source_directory, platform_months, months_contiguous
from parttime_source import (COLLECTION_LOCK, unpack_daily, validate_daily,
                             clean_rider_bill, format_rider_monthly_workbook)
import separation_filter
import price_archive
import rider_archive
from fengshen_merchant_protocol import KINDS as MERCHANT_DATASETS,MERCHANT,INVITATIONS,ATTENDANCE,LABELS as MERCHANT_LABELS

BAIZE_DATASET = "baize_employees"
RIDER_DAILY_DATASET = "rider_daily"
DETAIL_ORDERS_DATASET = "detail_orders"
DETAIL_KESU_DATASET = "detail_kesu"
DETAIL_REVIEWS_DATASET = "detail_reviews"
DETAIL_DATASETS = (DETAIL_ORDERS_DATASET, DETAIL_KESU_DATASET, DETAIL_REVIEWS_DATASET)
RIDER_ARCHIVE_DATASET = "rider_archive"
RIDER_ORDER_DETAIL_DATASET = "rider_order_detail"
XIAOXIANG_ATTENDANCE_DATASET = "xiaoxiang_attendance_detail"
XIAOXIANG_DATASETS = (RIDER_DAILY_DATASET,) + DETAIL_DATASETS
XIAOXIANG_SELECTION = XIAOXIANG_DATASETS + (RIDER_ARCHIVE_DATASET,
                                            RIDER_ORDER_DETAIL_DATASET, XIAOXIANG_ATTENDANCE_DATASET)
DATASETS = {
    **MERCHANT_LABELS,
    BAIZE_DATASET: "白泽员工资料（全量）",
    RIDER_DAILY_DATASET: "日维度骑手分析（小象灯塔）",
    RIDER_ARCHIVE_DATASET: "骑手档案（小象灯塔）",
    RIDER_ORDER_DETAIL_DATASET: "骑手订单明细（小象灯塔）",
    XIAOXIANG_ATTENDANCE_DATASET: "骑手出勤明细（小象灯塔）",
    DETAIL_ORDERS_DATASET: "配送订单明细（小象灯塔）",
    DETAIL_KESU_DATASET: "配送客诉明细（小象灯塔）",
    DETAIL_REVIEWS_DATASET: "配送评价明细（小象灯塔）",
    "delivery_fee": "配送费", "penalty": "违规扣款", "rider_monthly": "风神骑手月度 UB 账单",
    "fraud": "欺诈单", "problem": "问题单", "delivery_waybill": "运单数据",
    "receive_account": "骑手风神绑定", "rider_detail": "骑手数据明细", "rider_info": "骑手信息导出",
    "payment_binding": "骑手支付绑定（生成表）", "goods_rent": "物资租用登记",
    "abnormal_followup": "异常骑手跟进（生成表）",
    "abnormal_riders": "异常骑手整理（生成表）",
    **{key: '蓝橙' + value[0] for key, value in LANORANGE_DATASETS.items()},
}
MONTHLY_DATASETS = frozenset({"rider_monthly", "receive_account"})
SNAPSHOT_DATASETS = frozenset({"rider_info", "goods_rent"})
# 异常骑手跟进（生成表）自动关联的来源资料，勾选该项时随任务一并采集。
FOLLOWUP_DEPENDENCIES = ('payment_binding', 'rider_monthly', 'goods_rent',
                         'lanorange_part_price', 'lanorange_rider_archive')
# 异常骑手整理（生成表）只依赖蓝橙资料，按「全部城市」全量交付生成一份工作簿。
ABNORMAL_RIDERS_DEPENDENCIES = ('lanorange_batch_quit', 'lanorange_rider_quit',
                                'lanorange_rider_report', 'lanorange_rider_leave',
                                'lanorange_rider_archive')
GENERATOR_DEPENDENCIES = {'abnormal_followup': FOLLOWUP_DEPENDENCIES,
                          'abnormal_riders': ABNORMAL_RIDERS_DEPENDENCIES}


def expand_followup_datasets(datasets):
    """生成表自动关联来源资料，返回扩展后的资料列表（幂等）。"""
    values = list(datasets)
    for generator, dependencies in GENERATOR_DEPENDENCIES.items():
        if generator in values:
            for dependency in dependencies:
                if dependency not in values:
                    values.append(dependency)
    return values
PHASES = frozenset({"queued", "preparing", "waiting_collection", "waiting_login", "waiting_manual",
                    "submitting", "waiting_export", "downloading", "validating", "generating", "publishing", "completed", "failed"})
SUBMISSION_STATES = frozenset({"not_submitted", "submitted", "unknown"})
PROFILES = {
    "agency_daily": "fengshen_bill.profile.json", "rider_monthly": "fengshen_rider_bill.profile.json",
    "issue_orders": "fengshen_orders.profile.json",
}


class ValidationError(ValueError):
    pass


class DownloadCancelled(BillCollectionError):
    pass


def _failure(exc, phase, dataset=""):
    safe = collection_failure(exc, phase, dataset)
    for field, allowed in (("failure_phase", PHASES), ("submission_state", SUBMISSION_STATES)):
        value = getattr(exc, "download_" + field, None)
        if isinstance(value, str) and value in allowed:
            safe.diagnostics[field] = value
    return CollectionFailure(str(safe).replace("核算已停止", "下载已停止"), safe.diagnostics)


def cities():
    try:
        return city_catalog.all_cities()
    except city_catalog.CityCatalogError as exc:
        raise ValidationError(str(exc)) from None


def refresh_cities(force=False):
    """从风神刷新城市清单；失败时静默保留缓存，不阻断下载中心打开。"""
    try:
        return city_catalog.refresh(force=force)
    except Exception:
        return city_catalog.snapshot()


def get_options():
    from task_catalog import generators
    snapshot = city_catalog.snapshot()
    return {"cities": [{"name": name, "id": code,
                        **({"disabled": True, "note": "已下架"} if name in city_catalog.OFF_SHELF_CITIES else {})}
                       for name, code in snapshot["cities"].items()],
            "cities_source": snapshot["source"], "cities_updated_at": snapshot["updated_at"],
            "datasets": [{"id": key, "label": LANORANGE_DATASETS[key][0] if key in LANORANGE_DATASETS else label,
                          "group": 'baize' if key == BAIZE_DATASET else 'xiaoxiang' if key in XIAOXIANG_SELECTION else 'lanorange' if key in LANORANGE_DATASETS or key == 'abnormal_riders' else 'fengshen',
                          "scope": 'all' if key == BAIZE_DATASET or key in XIAOXIANG_SELECTION or key in LANORANGE_DATASETS or key == 'abnormal_riders' else 'city'}
                         for key, label in DATASETS.items()],
            "generators": generators(), "timezone": "Asia/Shanghai", "order_window_days": 60}


def covered_months(start, end):
    year, month = start.year, start.month
    result = []
    while True:
        result.append(f"{year:04d}-{month:02d}")
        if (year, month) == (end.year, end.month):
            return result
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def validate_request(payload, today=None):
    from task_catalog import intent
    try:
        task_intent = intent(payload) if isinstance(payload, dict) else {}
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    if not isinstance(payload, dict):
        raise ValidationError("下载参数必须为对象")
    if "refresh_history" in payload and type(payload["refresh_history"]) is not bool:
        raise ValidationError("历史数据刷新选项必须为布尔值")
    if "waybill_all_city_send" in payload and type(payload["waybill_all_city_send"]) is not bool:
        raise ValidationError("运单全城送筛选选项必须为布尔值")
    if "lanorange_months" in payload:
        from lanorange_catalog import clean_months
        try:
            payload = {**payload, "lanorange_months": clean_months(payload["lanorange_months"])}
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
    if "refresh_rider_info" in payload and type(payload["refresh_rider_info"]) is not bool:
        raise ValidationError("骑手信息快照刷新选项必须为布尔值")
    selected_cities, selected = payload.get("cities"), payload.get("datasets")
    if payload.get("waybill_all_city_send") is True and not (
            isinstance(selected, list) and "delivery_waybill" in selected):
        raise ValidationError("仅运单数据支持全城送筛选")
    if 'merchant_by_city' in payload and type(payload['merchant_by_city']) is not bool:raise ValidationError('城市商家选项必须为布尔值')
    if isinstance(selected,list) and selected and all(isinstance(kind,str) and kind in MERCHANT_DATASETS for kind in selected):
        if not selected or any(not isinstance(kind,str) or kind not in MERCHANT_DATASETS for kind in selected) or task_intent.get('task_kind','download')!='download':raise ValidationError('商家资料请单独下载，可同时选择邀请记录和出勤明细')
        legacy=selected_cities in (None,[],[MERCHANT]) and not payload.get('merchant_by_city')
        if not legacy:
            try:allowed=city_catalog.selectable_cities()
            except city_catalog.CityCatalogError as error:raise ValidationError(str(error)) from None
            if not isinstance(selected_cities,list) or not selected_cities or any(not isinstance(city,str) or city not in allowed for city in selected_cities):raise ValidationError('请选择配置列表中的一个或多个城市商家')
        today=today or dt.datetime.now(SHANGHAI).date()
        if ATTENDANCE in selected:
            try:
                if any(not isinstance(payload.get(k),str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',payload[k]) for k in ('start','end')):raise ValueError()
                first,last=dt.date.fromisoformat(payload['start']),dt.date.fromisoformat(payload['end'])
                if first>last or first<today-dt.timedelta(days=90) or last>=today:raise ValueError()
            except ValueError:raise ValidationError('出勤明细须选择最近90天内、早于今天的有效起止日期') from None
        else:first=last=today
        return {**task_intent,'cities':[MERCHANT] if legacy else list(dict.fromkeys(selected_cities)),**({} if legacy else {'merchant_by_city':True}),'datasets':[k for k in DATASETS if k in selected],'start':first.isoformat(),'end':last.isoformat(),'months':covered_months(first,last)}
    if isinstance(selected, list) and any(key in XIAOXIANG_SELECTION for key in selected):
        if (task_intent.get('task_kind', 'download') != 'download'
                or not all(isinstance(key, str) and key in XIAOXIANG_SELECTION for key in selected)):
            raise ValidationError('小象灯塔资料请单独下载，不能与风神或蓝橙资料混合')
        keys = [key for key in DATASETS if key in selected]
        today = today or dt.datetime.now(SHANGHAI).date()
        dated = [key for key in keys if key != RIDER_ARCHIVE_DATASET]
        if not dated:
            # 骑手档案是导出时刻的当前快照，不按日期筛选。
            return {**task_intent, 'cities': [ALL_CITIES], 'datasets': keys,
                    'start': today.isoformat(), 'end': today.isoformat(),
                    'months': [today.strftime('%Y-%m')]}
        label = DATASETS[dated[0]] if len(dated) == 1 else '小象灯塔资料'
        last = today - dt.timedelta(days=1)
        if payload.get('start') is None and payload.get('end') is None:
            first = last
        else:
            try:
                if any(not isinstance(payload.get(field), str)
                       or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', payload[field]) for field in ('start', 'end')):
                    raise ValueError()
                first, last = dt.date.fromisoformat(payload['start']), dt.date.fromisoformat(payload['end'])
            except ValueError:
                raise ValidationError('请选择有效的开始和结束日期') from None
            if first > last:
                raise ValidationError('开始日期不能晚于结束日期')
            if last > today - dt.timedelta(days=1):
                raise ValidationError('{}只能选择昨天及更早的日期'.format(label))
            if (last - first).days + 1 > 31:
                raise ValidationError('{}日期区间最长31天'.format(label))
        return {**task_intent, 'cities': [ALL_CITIES], 'datasets': keys,
                'start': first.isoformat(), 'end': last.isoformat(), 'months': covered_months(first, last)}
    if isinstance(selected, list) and BAIZE_DATASET in selected:
        if selected != [BAIZE_DATASET] or task_intent.get('task_kind', 'download') != 'download':
            raise ValidationError('白泽员工资料仅支持独立下载，请单独选择白泽资料')
        today = today or dt.datetime.now(SHANGHAI).date()
        return {**task_intent, 'cities': [ALL_CITIES], 'datasets': [BAIZE_DATASET],
                'start': today.isoformat(), 'end': today.isoformat(), 'months': [today.strftime('%Y-%m')]}
    global_only = isinstance(selected, list) and bool(selected) and all(
        isinstance(key, str) and (key in LANORANGE_DATASETS or key == 'abnormal_riders') for key in selected)
    selected_months = payload.get("lanorange_months") or []
    if selected_months and not (global_only and 'lanorange_part_price' in selected):
        raise ValidationError("蓝橙价格档案月份筛选仅适用于纯蓝橙价格档案下载")
    if global_only:
        today = today or dt.datetime.now(SHANGHAI).date()
        chosen = payload.get('cities') if isinstance(payload.get('cities'), list) else []
        chosen = [city for city in chosen if city not in (ALL_CITIES, '全部城市')]
        chosen = list(dict.fromkeys(
            city.removesuffix('市') if isinstance(city, str) else city for city in chosen))
        if chosen:
            from lanorange_catalog import SELECTABLE_CITIES
            if any(not isinstance(city, str) or city not in SELECTABLE_CITIES for city in chosen):
                raise ValidationError('蓝橙城市不在可选范围，请从配置的城市列表中选择')
            return {**task_intent, 'cities': chosen, 'lanorange_by_city': True,
                    'datasets': [key for key in DATASETS if key in selected],
                    'start': today.isoformat(), 'end': today.isoformat(),
                    'months': selected_months or covered_months(today, today),
                    **({'lanorange_months': selected_months} if selected_months else {})}
        return {**task_intent, 'cities': [ALL_CITIES], 'lanorange_full_delivery': True,
                'datasets': [key for key in DATASETS if key in selected],
                'start': today.isoformat(), 'end': today.isoformat(),
                'months': selected_months or covered_months(today, today),
                **({'lanorange_months': selected_months} if selected_months else {})}
    try:
        allowed = city_catalog.selectable_cities()
    except city_catalog.CityCatalogError as exc:
        raise ValidationError(str(exc)) from None
    if isinstance(selected_cities, list):
        off_shelf = [city for city in selected_cities
                     if isinstance(city, str) and city in city_catalog.OFF_SHELF_CITIES]
        if off_shelf:
            raise ValidationError("、".join(dict.fromkeys(off_shelf)) + " 已下架，不能新建下载任务")
    if not isinstance(selected_cities, list) or not selected_cities or any(
        not isinstance(city, str) or city not in allowed for city in selected_cities
    ):
        raise ValidationError("请选择配置列表中的一个或多个城市")
    if not isinstance(selected, list) or not selected or any(
        not isinstance(kind, str) or kind not in DATASETS for kind in selected
    ):
        raise ValidationError("请选择一种或多种下载资料")
    try:
        for field in ("start", "end"):
            if not isinstance(payload.get(field), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload[field]):
                raise ValueError()
        first, last = dt.date.fromisoformat(payload["start"]), dt.date.fromisoformat(payload["end"])
    except ValueError:
        raise ValidationError("请选择有效的开始和结束日期") from None
    if first > last:
        raise ValidationError("开始日期不能晚于结束日期")
    today = today or dt.datetime.now(SHANGHAI).date()
    if ATTENDANCE in selected and (first < today-dt.timedelta(days=90) or last >= today):
        raise ValidationError('出勤明细须选择最近90天内、早于今天的有效起止日期')
    if any(kind not in MONTHLY_DATASETS | SNAPSHOT_DATASETS for kind in selected) and last > today:
        raise ValidationError("周期资料不能选择未来日期")
    if MONTHLY_DATASETS.intersection(selected) and (last.year, last.month) > (today.year, today.month):
        raise ValidationError("月度资料不能选择未来月份")
    if set(selected) & {"fraud", "problem", "delivery_waybill"}:
        try:
            date_batches(first.isoformat(), last.isoformat(), today=today)
        except BillCollectionError as exc:
            raise ValidationError(str(exc).replace("核算已停止", "下载未启动")) from None
    if any(key in payload and type(payload[key]) is not bool for key in ('include_separation', 'exclude_separation')):
        raise ValidationError("取分离站点选项必须为布尔值")
    return {**task_intent, "cities": list(dict.fromkeys(selected_cities)),
            **({'merchant_by_city': True} if set(selected) & MERCHANT_DATASETS else {}),
            **({'lanorange_full_delivery': True} if set(selected) & LANORANGE_DATASETS.keys() else {}),
            "datasets": [key for key in DATASETS if key in selected],
            "start": first.isoformat(), "end": last.isoformat(),
            "months": covered_months(first, last),
            **({"exclude_separation": payload['exclude_separation']} if 'exclude_separation' in payload
               else {"include_separation": True} if payload.get("include_separation") else {}),
            **({"refresh_history": True} if payload.get("refresh_history") else {}),
            **({"waybill_all_city_send": True} if payload.get("waybill_all_city_send") else {}),
            **({"refresh_rider_info": True} if payload.get("refresh_rider_info") else {})}


def _checkpoint(cancelled):
    if cancelled.is_set():
        raise DownloadCancelled("下载任务已取消")


def _load_profile(dataset, agency_id):
    try:
        profile = json.loads(Path(__file__).with_name(PROFILES[dataset]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BillCollectionError("所选资料的风神页面配置不可用，请联系管理员") from None
    if not isinstance(profile, dict):
        raise BillCollectionError("风神页面配置格式无效")
    profile["expected_agency_id"] = agency_id
    (validate_order_profile if dataset == "issue_orders" else validate_profile)(profile)
    if profile.get("dataset") != dataset or profile.get("selection_mode") != "target_city":
        raise BillCollectionError("风神页面配置不支持当前城市范围")
    return profile


class BrowserRunner:
    def __init__(self, page, auth, log, cancelled):
        self.page, self.auth, self.log, self.cancelled = page, auth, log, cancelled

    def _navigate(self, url, profile):
        _checkpoint(self.cancelled)
        try:
            self.auth.navigate(url)
        except Exception as exc:
            raise _failure(exc, "navigation", profile["dataset"]) from None
        try:
            self.auth.ensure(url, profile)
        except Exception as exc:
            raise _failure(exc, "auth_check", profile["dataset"]) from None

    def _profile(self, dataset, agency_id):
        # Profile validation is entirely local and precedes every browser or
        # export operation. Preserve that proof so a repaired configuration can
        # safely retry only this unfinished item.
        try:
            return _load_profile(dataset, agency_id)
        except Exception as exc:
            failure = _failure(exc, "input_validation", dataset)
            failure.diagnostics.update(failure_phase="preparing", submission_state="not_submitted")
            raise failure from None

    def daily(self, plan, raw, selected):
        profile = self._profile("agency_daily", plan.agency_id)
        self._navigate(BILL_URL, profile)
        request = BillRequest(plan.start, plan.end, False, False, plan.agency_id,
                              sub_bill_types=tuple(kind for kind, key in ((1, "delivery_fee"), (2, "penalty")) if key in selected))
        return BillPageCollector(self.page, profile, raw, log=self.log,
                                 auth=lambda force=False: self.auth.ensure(BILL_URL, profile, force)).collect(request)

    def monthly(self, plan, raw):
        profile = self._profile("rider_monthly", plan.agency_id)
        self._navigate(RIDER_BILL_URL, profile)
        return MonthlyBillPageCollector(self.page, profile, raw, log=self.log,
                                        auth=lambda force=False: self.auth.ensure(RIDER_BILL_URL, profile, force)).collect(MonthlyBillRequest(plan.month))

    def orders(self, plan, raw, selected):
        profile = self._profile("issue_orders", plan.agency_id)
        self._navigate(WAYBILL_URL, profile)
        return OrderPageCollector(self.page, profile, raw, log=self.log,
                                  auth=lambda force=False: self.auth.ensure(WAYBILL_URL, profile, force)).collect_batches(
                                      plan.start, plan.end, self.cancelled, include_violations="problem" in selected)

    def rider_source(self, plan, raw, kind):
        from download_rider_sources import collect_rider_source
        from fengshen_auth import reveal_edge, conceal_edge
        try:
            return collect_rider_source(self.page, self.auth, plan, raw, kind, self.log, self.cancelled,
                                        reveal=reveal_edge, conceal=conceal_edge)
        except Exception as exc:
            raise _failure(exc, "collect", kind) from None

    def resume_detail(self, plan, raw, source_dir):
        from download_rider_recovery import recover_rider_detail
        from fengshen_auth import reveal_edge, conceal_edge
        try:
            return recover_rider_detail(self.page, self.auth, plan, raw, source_dir, self.log, self.cancelled,
                                        reveal=reveal_edge, conceal=conceal_edge)
        except Exception as exc:
            raise _failure(exc, "collect", "rider_detail") from None


@contextmanager
def _open_runner(config, log, cancelled, notify):
    from fengshen_auth import BROKER
    from fengshen_http import FengshenHttpClient
    from fengshen_http_auth import HTTPAuth
    from fengshen_http_daily import DailyHttpCollector
    from fengshen_http_reports import ReportHttpCollector
    from fengshen_http_riders import RiderHttpCollector
    _checkpoint(cancelled)
    waiting_logged = False
    while not COLLECTION_LOCK.acquire(timeout=0.25):
        _checkpoint(cancelled)
        if not waiting_logged:
            notify({"state": "waiting_collection"})
            log("正在等待其他采集任务结束")
            waiting_logged = True
    try:
        _checkpoint(cancelled)
        while BROKER.status(config["owner"])["busy"]:
            _checkpoint(cancelled)
            notify({"state": "waiting_login"})
            if not waiting_logged:
                log("正在等待当前登录操作结束")
                waiting_logged = True
            cancelled.wait(0.25)
        with BROKER.operation(config["owner"], cancelled, notify, transport="http"):
            client = None
            try:
                client = FengshenHttpClient(BROKER.vault.load(), cancelled=cancelled)
                auth = HTTPAuth(client, BROKER, cancelled, log, wait_export_indefinitely=config.get('task_kind')=='payroll_source')
                auth.ensure()
                client.auth_handler = lambda: auth.ensure(force=True)
                daily = DailyHttpCollector(client, log=log)
                reports = ReportHttpCollector(client, log=log)
                riders = RiderHttpCollector(client, log=log, cancelled=cancelled, auth=auth)
                from fengshen_merchant_exports import MerchantCollector
                merchant=MerchantCollector(client,log=log)

                class HTTPRunner:
                    def merchant_source(self,kind,raw,start,end,resume=None,**scope):return merchant.collect(kind,raw,start,end,resume,**scope)
                    def daily(self, plan, raw, selected):
                        return daily.daily(plan, raw, selected)

                    def resume_daily(self, plan, raw, selected, source_dir):
                        return daily.resume_daily(plan, raw, selected, source_dir)

                    def monthly(self, plan, raw):
                        return reports.monthly(plan, raw)

                    def orders(self, plan, raw, selected):
                        return reports.orders(plan, raw, selected)

                    def waybills_created(self, plan, raw, *, all_city_send=False):
                        client.select_city(plan.agency_id)
                        return reports.waybills_created(plan, raw, all_city_send=all_city_send)

                    def orders_batch(self, plan, raw, selected):
                        return reports.orders(plan, raw, selected, allow_existing_batches=True)

                    def resume_orders(self, plan, raw, selected, source_dir):
                        return reports.resume_orders(plan, raw, selected, source_dir)

                    def rider_source(self, plan, raw, kind):
                        client.select_city(plan.agency_id)
                        return riders.rider_source(plan, raw, kind)

                    def goods_rent(self, plan, raw):
                        client.select_city(plan.agency_id)
                        return riders.goods_rent(plan, raw)

                    def resume_detail(self, plan, raw, source_dir):
                        client.select_city(plan.agency_id)
                        return riders.resume_detail(plan, raw, source_dir)

                yield HTTPRunner()
            except Exception as exc:
                failure = _failure(exc, "collect")
                BROKER.update("signed_out" if cancelled.is_set() else "error", str(failure))
                raise failure from None
            finally:
                if client is not None:
                    client.close()
    finally:
        COLLECTION_LOCK.release()


def _download_file(manifest, raw, dataset, plan):
    if not isinstance(manifest, dict) or manifest.get("status") != "success" or manifest.get("dataset") != dataset:
        raise BillCollectionError("平台下载未成功，未发布文件")
    request = MonthlyBillRequest(plan.month) if dataset == "rider_monthly" else plan
    if (manifest.get("agency_id") != plan.agency_id or manifest.get("start") != request.start
            or manifest.get("end") != request.end):
        raise BillCollectionError("下载结果的城市或日期范围不一致")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise BillCollectionError("平台返回的下载文件数量异常")
    info = files[0]
    base = Path(raw).resolve()
    if not isinstance(info.get("path"), str):
        raise BillCollectionError("下载文件路径无效")
    file = (base / info["path"]).resolve()
    if not file.is_relative_to(base) or not file.is_file():
        raise BillCollectionError("下载文件不属于本次任务")
    if info.get("bytes") != file.stat().st_size or info.get("sha256") != _hash(file):
        raise BillCollectionError("下载文件完整性校验失败")
    return file


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _rider_source_file(info, raw, kind, plan):
    """Require the adapter's exact city/period and validated file receipt."""
    if (not isinstance(info, dict) or info.get("dataset") != kind
            or info.get("status") not in ("validated", "empty") or info.get("scope") != "target_city"
            or info.get("agency_id") != plan.agency_id or info.get("city") != plan.city
            or info.get("start") != plan.start or info.get("end") != plan.end
            or (kind == "receive_account" and info.get("month") != plan.month)):
        raise BillCollectionError("骑手资料的城市、日期或校验状态不一致，未发布文件")
    name = info.get("path")
    if not isinstance(name, str):
        raise BillCollectionError("骑手资料文件路径无效")
    relative = Path(name)
    base = Path(raw).resolve()
    candidate = base / relative
    source = candidate.resolve()
    if (relative.is_absolute() or relative.drive or ".." in relative.parts or candidate.is_symlink()
            or not source.is_relative_to(base) or not source.is_file()
            or source.suffix.lower() not in (".csv", ".xlsx")):
        raise BillCollectionError("骑手资料文件归属或格式无效")
    if (type(info.get("rows")) is not int or info["rows"] < 0
            or (info["status"] == "empty") != (info["rows"] == 0)
            or info.get("bytes") != source.stat().st_size or info.get("sha256") != _hash(source)):
        raise BillCollectionError("骑手资料未通过完整性校验，未发布文件")
    return source


def _item_key(value):
    return tuple(value.get(key) for key in ("city", "dataset", "start", "end"))


def _requested_items(config):
    items = [{"city": ALL_CITIES, "dataset": kind, "start": config['start'], "end": config['end']}
             for kind in config['datasets']
             if (kind in LANORANGE_DATASETS or kind == 'abnormal_riders') and not city_scoped(config, kind)]
    for city in config["cities"]:
        for kind in config["datasets"]:
            if kind in LANORANGE_DATASETS and not city_scoped(config, kind): continue
            if kind == 'abnormal_riders': continue
            periods = [(config["start"], config["end"])]
            if kind in MONTHLY_DATASETS:
                periods = [(MonthlyBillRequest(month).start, MonthlyBillRequest(month).end) for month in config["months"]]
            elif kind in ('payment_binding', 'abnormal_followup'):
                from binding_download import month_periods
                periods = [(first, last) for _, first, last in month_periods(config['start'], config['end'])]
            items.extend({"city": city, "dataset": kind, "start": first, "end": last} for first, last in periods)
    retries = config.get("retry_items")
    if not retries:
        # 未指定分项重试范围（None 或空列表）时执行全部请求项。
        return items
    allowed = {_item_key(value) for value in items}
    if (not isinstance(retries, list) or not retries
            or any(not isinstance(value, dict) or set(value) != {"city", "dataset", "start", "end"}
                   or any(not isinstance(part, str) for part in value.values()) for value in retries)):
        raise BillCollectionError("分项重试范围无效，未提交导出")
    keys = [_item_key(value) for value in retries]
    if len(keys) != len(set(keys)) or not set(keys).issubset(allowed):
        raise BillCollectionError("分项重试城市、资料或业务周期不符，未提交导出")
    selected = [value for value in items if _item_key(value) in set(keys)]
    # 生成表重试时自动补回来源资料，避免只有生成项而无依赖。
    chosen = {_item_key(value) for value in selected}
    for generator, dependencies in GENERATOR_DEPENDENCIES.items():
        if any(value['dataset'] == generator for value in selected):
            selected.extend(value for value in items
                            if value['dataset'] in dependencies and _item_key(value) not in chosen)
            chosen = {_item_key(value) for value in selected}
    return selected


@profiled('download_task', 1, 'run_dir')
def execute_downloads(config, run_dir, log, cancelled, update_item, runner_factory=None):
    """Execute selected city/data pairs; a failed pair never publishes files."""
    if config.get('payroll_unified') and config.get('task_kind')=='payroll_source':
        from payroll_unified_download import execute
        return execute(config,run_dir,log,cancelled,update_item,runner_factory)
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    snapshot_roots = [path for path in dict.fromkeys((root.parent, root.parent.parent)) if path.is_dir()]
    config = dict(config)
    config['datasets'] = expand_followup_datasets(config.get('datasets', ()))
    selected = set(config['datasets'])
    mapping = cities() if config.get('merchant_by_city') or any(kind not in LANORANGE_DATASETS and kind not in MERCHANT_DATASETS and kind not in ('abnormal_riders', BAIZE_DATASET, RIDER_DAILY_DATASET, RIDER_ARCHIVE_DATASET, RIDER_ORDER_DETAIL_DATASET, XIAOXIANG_ATTENDANCE_DATASET)
                              for kind in selected) else {}
    requested = _requested_items(config)
    if config.get('payroll_agencies'):
        if config.get('task_kind') != 'payroll_source':
            raise ValidationError('合作商范围只能用于核算资料任务')
        from deduction_stations import _fengshen_client
        from fengshen_http import AGENCIES_URL
        client = _fengshen_client()
        try:
            authorized = client.request_json('GET', AGENCIES_URL)['data']
        finally:
            client.close()
        for city, agency in config['payroll_agencies'].items():
            if city not in config['cities'] or not any(str(r.get('agencyId')) == str(agency) and r.get('agencyCityName') == city and r.get('agencySubTypeName') in ('物流服务商','物流合作商') for r in authorized):
                raise ValidationError('取分离合作商不属于当前账号及本次城市')
            mapping[city] = str(agency)
    baize_only = selected == {BAIZE_DATASET}
    blue_only = all(value['dataset'] in LANORANGE_DATASETS or value['dataset'] == 'abnormal_riders'
                    for value in requested)
    requested_keys = {_item_key(value) for value in requested}
    resume_from = config.get("resume_detail_from")
    resume_source = config.get("resume_detail_source_dir")
    resume_sources = config.get("resume_detail_sources", {})
    resume_daily_sources = config.get("resume_daily_sources", {})
    resume_order_sources = config.get("resume_order_sources", {})
    resume_waybill_sources = config.get("resume_waybill_sources", {})
    if resume_from is not None and (not isinstance(resume_from, str) or not re.fullmatch(r"[0-9a-f]{32}", resume_from)
                                   or selected != {"rider_detail"} or len(config["cities"]) != 1):
        raise BillCollectionError("原明细任务恢复范围无效，未重新提交导出")
    if resume_source is not None and (not isinstance(resume_source, str) or not Path(resume_source).is_absolute()
                                     or selected != {"rider_detail"} or len(config["cities"]) != 1):
        raise BillCollectionError("原明细任务恢复路径或范围无效，未重新提交导出")
    if (not isinstance(resume_sources, dict)
            or any(not isinstance(city, str) or not isinstance(path, str) or not Path(path).is_absolute()
                   or not any(value["city"] == city and value["dataset"] == "rider_detail" for value in requested)
                   for city, path in resume_sources.items())):
        raise BillCollectionError("原明细分城市恢复范围无效，未重新提交导出")
    if (not isinstance(resume_daily_sources, dict)
            or any(not isinstance(city, str) or not isinstance(path, str) or not Path(path).is_absolute()
                   or not any(value["city"] == city and value["dataset"] in ("delivery_fee", "penalty")
                              for value in requested)
                   for city, path in resume_daily_sources.items())):
        raise BillCollectionError("原日账单分城市恢复范围无效，未重新提交导出")
    if (not isinstance(resume_order_sources, dict)
            or any(not isinstance(city, str) or not isinstance(path, str) or not Path(path).is_absolute()
                   or not any(value["city"] == city and value["dataset"] in ("fraud", "problem") for value in requested)
                   for city, path in resume_order_sources.items())):
        raise BillCollectionError("原运单分城市恢复范围无效，未重新提交导出")
    if (not isinstance(resume_waybill_sources, dict)
            or any(not isinstance(city, str) or not isinstance(path, str) or not Path(path).is_absolute()
                   or not any(value["city"] == city and value["dataset"] == "delivery_waybill"
                              for value in requested)
                   for city, path in resume_waybill_sources.items())):
        raise BillCollectionError("原运单原始资料恢复范围无效，未重新提交导出")
    files, results, active, step_created = [], [], [], []
    phases, context = {}, {}
    current_phase = "preparing"
    run_phase_state = None

    def item(city, kind, first=None, last=None):
        return {"city": city, "dataset": kind, "start": first or config["start"], "end": last or config["end"]}

    def entries(items, status, error=None, phase=None, staged=None, **extra):
        values = []
        for value in items:
            entry = {**value, "status": status, "phase": phase or current_phase, **extra}
            if error:
                entry["error"] = error
            if staged is not None:
                entry["files"] = [info for info in staged if _item_key(info) == _item_key(value)]
            values.append(entry)
        return values

    def send(values, record=True):
        for entry in values:
            phases[_item_key(entry)] = (entry["phase"], entry["status"])
            if record and entry["status"] in ("success", "error", "cancelled"):
                results.append(entry)
            update_item(entry)

    def update(items, status, error=None, phase=None, **extra):
        send(entries(items, status, error, phase, **extra))

    def pending():
        finished = {_item_key(value) for value in results}
        return [value for value in requested if _item_key(value) not in finished]

    def set_phase(phase, status="running"):
        nonlocal current_phase, run_phase_state
        transition(phase)
        current_phase = phase
        if not active:
            if run_phase_state != (phase, status):
                update_item({"status": status, "phase": phase, "_run_event": True})
                run_phase_state = (phase, status)
            return
        targets = active
        changed = [value for value in targets if phases.get(_item_key(value)) != (phase, status)]
        if changed:
            update(changed, status, phase=phase)

    def progress_log(message, *args, **kwargs):
        if isinstance(message, str):
            if message.startswith('[等待登录]'):
                set_phase('waiting_login', 'waiting_login')
            elif message.startswith('[下载]'):
                set_phase('downloading')
            elif message.startswith(("[等待验证]", "[验证未通过]", "[等待页面]")):
                set_phase("waiting_manual", "waiting_login")
            elif message.startswith("[等待权限]"):
                set_phase("waiting_login", "waiting_login")
            elif message.startswith(("[异步导出]", "[导出]", "[恢复列表]", "[恢复]")):
                set_phase("waiting_export")
            elif message.startswith("[下载]"):
                set_phase("downloading")
            elif message.startswith(("[完成]", "[校验]")):
                set_phase("validating")
            elif message.startswith("[账单]") and "提交导出" in message:
                set_phase("submitting")
        log(message, *args, **kwargs)

    def checkpoint_manifest(next_results=None, next_files=None):
        atomic_json(root / "manifest.json", {
            "config": {key: value for key, value in config.items()
                       if key not in ("owner", "resume_detail_source_dir", "resume_detail_sources", "resume_daily_sources", "resume_order_sources", "resume_waybill_sources", "resume_binding_materials", "resume_lanorange_sources",'resume_merchant_sources')},
            "items": results if next_results is None else next_results,
            "files": files if next_files is None else next_files, "payroll_executed": False})

    def failure_context(exc):
        detail = {"failure_phase": current_phase, "submission_state": "unknown"}
        if context.get('kind') == RIDER_DAILY_DATASET or context.get('kind') == RIDER_ARCHIVE_DATASET \
                or context.get('kind') in (RIDER_ORDER_DETAIL_DATASET, XIAOXIANG_ATTENDANCE_DATASET):
            # Board analytics is a read-only query followed by local XLSX
            # generation, never an asynchronous platform export submission.
            detail['submission_state'] = 'not_submitted'
        if context.get('kind')==INVITATIONS:detail['submission_state']='not_submitted'
        diagnostics = getattr(exc, "diagnostics", {})
        if isinstance(diagnostics, dict):
            if diagnostics.get("phase") in ("browser_launch", "session_restore", "page_create", "window_conceal", "navigation", "auth_check"):
                detail["submission_state"] = "not_submitted"
            for field, allowed in (("failure_phase", PHASES), ("submission_state", SUBMISSION_STATES)):
                if isinstance(diagnostics.get(field), str) and diagnostics[field] in allowed:
                    detail[field] = diagnostics[field]
        for field, allowed in (("failure_phase", PHASES), ("submission_state", SUBMISSION_STATES)):
            value = getattr(exc, "download_" + field, None)
            if isinstance(value, str) and value in allowed:
                detail[field] = value
        raw = context.get("raw")
        if isinstance(raw, Path) and context.get('kind') == BAIZE_DATASET:
            receipt = raw / 'http_submission.json'
            if receipt.exists():
                try:
                    proof = json.loads(receipt.read_text(encoding='utf-8'))
                    detail['submission_state'] = proof.get('submission_state') if proof.get('submission_state') in SUBMISSION_STATES else 'unknown'
                except (OSError, ValueError, AttributeError):
                    detail['submission_state'] = 'unknown'
            else:
                detail['submission_state'] = 'not_submitted'
        if isinstance(raw, Path):
            failure = raw / "source_failure.json"
            try:
                if failure.is_symlink() or not failure.resolve().is_relative_to(root) or not 0 < failure.stat().st_size <= 128 * 1024:
                    raise ValueError()
                proof = json.loads(failure.read_text(encoding="utf-8"))
                if proof.get("kind") != context.get("kind"):
                    raise ValueError()
                for field, allowed in (("failure_phase", PHASES), ("submission_state", SUBMISSION_STATES)):
                    if isinstance(proof.get(field), str) and proof[field] in allowed:
                        detail[field] = proof[field]
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        if context.get("resuming") and detail["submission_state"] == "not_submitted":
            detail["submission_state"] = "unknown"
        return detail

    def publish(path, directory, description):
        set_phase("publishing")
        path = Path(path).resolve()
        name = archive_filename(description["city"], description["dataset"], description["start"],
                                description["end"], suffix=path.suffix,
                                stamp=config.get("archive_created_at"),
                                variant="系统合并" if description.get('delivery_kind') == 'system_merged' else None,
                                months=platform_months(config, description['dataset']))
        if config.get('result_layout') == 2:
            from task_catalog import GENERATORS
            category = '来源' if config.get('task_kind') == 'generate' and description['dataset'] not in GENERATORS else '结果'
            directory = root / category / archive_component(description['city'])
        target = (Path(directory) / name).resolve()
        if not path.is_relative_to(root) or not target.is_relative_to(root) or not path.is_file():
            raise BillCollectionError("输出文件路径无效")
        # 与 download_jobs._file_entry 共用范围/周期口径，规则漂移在发布时即失败。
        from download_jobs import delivery_scope_error
        scope_error = delivery_scope_error(description, config, target.suffix)
        if scope_error:
            raise BillCollectionError(scope_error)
        _checkpoint(cancelled)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise BillCollectionError("同名归档文件已存在，未覆盖原文件")
        separation = None
        projection = None
        price_filter = None
        derived = None
        include = separation_filter.filter_direction(config)
        pre_formatted = bool(description.get('pre_formatted'))
        if (description['dataset'] in separation_filter.COLUMNS and include is not None
                and not pre_formatted):
            # 新选项仅在勾选排除时过滤；不勾选保留全量。历史任务沿用原方向。
            if path == target:
                raise BillCollectionError("取分离过滤不能就地覆盖原文件")
            path, separation = separation_filter.filter_table(
                path, description['dataset'], include, path.parent)
            derived = path
            progress_log(f"[过滤] {description['city']} {description['dataset']} 取分离站点过滤"
                         f"（{'仅保留' if include else '排除'}）："
                         f"{separation['rows_before']} → {separation['rows_after']} 行")
        if (description['dataset'] == 'lanorange_rider_archive'
                and description.get('delivery_kind') in ('platform_original', 'system_merged')):
            # 仅全量交付成品统一 14 列并按项目升序；城市批次原表保持原样。
            if path == target:
                raise BillCollectionError("蓝橙骑手档案格式化不能就地覆盖原文件")
            from download_pipeline import reserve_local_work
            reserve_local_work()
            path, projection = rider_archive.format_full_workbook(path, path.parent, cancelled)
            if derived is not None and derived != path:
                derived.unlink(missing_ok=True)
            derived = path
            progress_log(f"[格式化] 蓝橙骑手档案：{projection['rows']} 行，14 列，按项目升序")
        if (description['dataset'] == 'lanorange_part_price'
                and description.get('delivery_kind') in ('platform_original', 'system_merged')
                and (not blue_only or (platform_months(config, description['dataset'])
                                       and not months_contiguous(platform_months(config, description['dataset']))))):
            # 混合任务保留按月份裁剪；纯蓝橙仅在所选月份不连续时裁掉中间月份。
            if path == target:
                raise BillCollectionError("蓝橙价格档案筛选不能就地覆盖原文件")
            path, price_filter = price_archive.filter_workbook(
                path, path.parent, config.get('months') or [], cancelled=cancelled)
            if derived is not None and derived != path:
                derived.unlink(missing_ok=True)
            derived = path
            progress_log(f"[筛选] 蓝橙价格档案：{price_filter['before']} → "
                         f"{price_filter['after']} 行（{'、'.join(price_filter['months'])}）")
        if description['dataset'] == 'rider_detail' and not pre_formatted:
            # 成品按业务口径保留 17 列并统一日期格式；原始资料保留平台全列。
            if path == target:
                raise BillCollectionError("骑手数据明细格式化不能就地覆盖原文件")
            from download_pipeline import reserve_local_work
            reserve_local_work()
            path = format_rider_detail_csv(
                path, path.parent / ('.格式化_' + uuid.uuid4().hex + '.csv'))
            if derived is not None and derived != path:
                derived.unlink(missing_ok=True)
            derived = path
            progress_log(f"[格式化] {description['city']} 骑手数据明细："
                         "保留 17 列并统一日期格式")
        if description['dataset'] == 'rider_monthly':
            # 取分离过滤会重写副本并丢失样式；格式化必须在过滤之后执行。
            if path == target:
                raise BillCollectionError("骑手月度账单格式化不能就地覆盖原文件")
            from download_pipeline import reserve_local_work
            reserve_local_work()
            path = format_rider_monthly_workbook(
                path, path.parent / ('.格式化_' + uuid.uuid4().hex + '.xlsx'))
            if derived is not None and derived != path:
                derived.unlink(missing_ok=True)
            derived = path
            progress_log(f"[格式化] {description['city']} 骑手月度账单："
                         "删除前置说明行并统一成品样式")
        source_size, source_hash = path.stat().st_size, _hash(path)
        try:
            if path != target:
                step_created.append(target)
                if config.get('result_layout') == 3 and description['dataset'] in ('payment_binding','abnormal_followup','abnormal_riders','lanorange_summary','invitation_summary'):
                    os.replace(path,target)
                else:
                    shutil.copy2(path, target)
            target_hash = _hash(target)
            if target.stat().st_size != source_size or target_hash != source_hash:
                raise BillCollectionError("归档成品与已校验原文件不一致，未发布文件")
        finally:
            if derived is not None and derived != target:
                derived.unlink(missing_ok=True)
        return {**description, "name": target.name, "relative_path": str(target.relative_to(root)),
                "bytes": source_size, "sha256": target_hash,
                **({"separation_filter": separation} if separation else {}),
                **({"archive_projection": projection} if projection else {}),
                **({"price_filter": price_filter} if price_filter else {})}

    def auth_status(status):
        state = status.get("state")
        if state == "waiting_collection":
            set_phase("waiting_collection")
        elif state in ("waiting_login", "login_required", "sms_sent"):
            set_phase("waiting_login", "waiting_login")
        elif state in ("manual_required", "waiting_manual"):
            set_phase("waiting_manual", "waiting_login")
        elif state == "ready":
            set_phase("preparing")

    def run_step(items, operation):
        active[:] = items
        step_created.clear()
        context.clear()
        _checkpoint(cancelled)
        set_phase("preparing")
        committed = False
        try:
            staged = operation()
            _checkpoint(cancelled)
            if (not isinstance(staged, list) or len(staged) != len(items)
                    or sorted(_item_key(value) for value in staged) != sorted(_item_key(value) for value in items)):
                raise BillCollectionError("分项文件清单与本次业务范围不一致，未发布文件")
            completed = entries(items, "success", phase="completed", staged=staged,
                                **({"submission_state": "submitted"} if context.get("resuming") else {}))
            # This durable checkpoint precedes every success/file callback.
            checkpoint_manifest(results + completed, files + staged)
            files.extend(staged)
            committed = True
            try:
                send(completed)
            except Exception as exc:
                # Published files and the checkpoint are already durable. Keep
                # the in-memory success ledger complete so later checkpoints do
                # not drop the rest of this group, and continue other steps.
                recorded = {_item_key(entry) for entry in results}
                results.extend(entry for entry in completed if _item_key(entry) not in recorded)
                try:
                    log("已发布文件的状态回写未完成（" + type(exc).__name__ + "），文件已按清单保留")
                except Exception:
                    pass
        except Exception as exc:
            if committed:
                # Unexpected post-publication failures stay recoverable from the
                # manifest; status callbacks are already handled above.
                raise
            for created in step_created:
                try:
                    created.unlink(missing_ok=True)
                except OSError:
                    pass
            if cancelled.is_set():
                update(items, "cancelled", phase="failed", **failure_context(exc))
                raise DownloadCancelled("下载任务已取消") from None
            message = str(_failure(exc, "collect"))
            log(message)
            update(items, "error", message, phase="failed", **failure_context(exc))
        finally:
            active.clear()
            if not committed:
                checkpoint_manifest()

    def run_prepare(items, operation):
        # 与 run_step 相同的分项失败语义，但只采集资料不发布文件，
        # 供生成阶段移交后台并行执行。
        active[:] = items
        step_created.clear()
        context.clear()
        _checkpoint(cancelled)
        set_phase("preparing")
        try:
            operation()
            _checkpoint(cancelled)
        except Exception as exc:
            for created in step_created:
                try:
                    created.unlink(missing_ok=True)
                except OSError:
                    pass
            if cancelled.is_set():
                update(items, "cancelled", phase="failed", **failure_context(exc))
                raise DownloadCancelled("下载任务已取消") from None
            message = str(_failure(exc, "collect"))
            log(message)
            update(items, "error", message, phase="failed", **failure_context(exc))
            checkpoint_manifest()
        finally:
            active.clear()

    @contextmanager
    def managed_runner():
        if baize_only:
            yield None
            return
        if all(value['dataset'] in LANORANGE_DATASETS or value['dataset'] == 'abnormal_riders'
               for value in requested):
            yield None
            return
        if requested and all(value['dataset'] == 'payment_binding' and
                             config.get('resume_binding_materials', {}).get(value['city'] + '|' + value['start'][:7])
                             for value in requested):
            yield None
            return
        entered = False
        try:
            with (runner_factory or _open_runner)(config, progress_log, cancelled, auth_status) as runner:
                entered = True
                yield runner
        except Exception as exc:
            if not entered:
                update(pending(), "cancelled" if cancelled.is_set() else "error", str(_failure(exc, "collect")),
                       phase="failed", failure_phase=current_phase, submission_state="not_submitted")
                checkpoint_manifest()
            if not cancelled.is_set() or not entered:
                raise
            # A cancellation after earlier steps retains their validated files.

    if baize_only:
        from binding_sources_http import BindingSources
        while not COLLECTION_LOCK.acquire(timeout=0.25):
            _checkpoint(cancelled)
            set_phase('waiting_collection')
        try:
            for description in requested:
                def baize_download(description=description):
                    raw = root / 'baize_source'
                    context.update(raw=raw / 'baize', kind=BAIZE_DATASET)
                    source = BindingSources(raw, progress_log, cancelled).employees()
                    return [publish(source, root, description)]
                run_step([description], baize_download)
        finally:
            COLLECTION_LOCK.release()
        return files

    if selected and selected <= {RIDER_DAILY_DATASET, *DETAIL_DATASETS, RIDER_ARCHIVE_DATASET,
                                 RIDER_ORDER_DETAIL_DATASET, XIAOXIANG_ATTENDANCE_DATASET}:
        while not COLLECTION_LOCK.acquire(timeout=0.25):
            _checkpoint(cancelled)
            set_phase('waiting_collection')
        try:
            for description in requested:
                def rider_daily_download(description=description):
                    directory = root / '小象灯塔来源'
                    directory.mkdir(parents=True, exist_ok=True)
                    context.update(raw=directory, kind=description['dataset'])
                    from xiaoxiang_board import (generate_rider_daily, generate_rider_daily_range,
                                                 generate_detail)
                    if description['dataset'] == RIDER_DAILY_DATASET:
                        if description['start'] == description['end']:
                            workbook = generate_rider_daily(description['start'], directory,
                                                            log=progress_log, cancelled=cancelled)
                        else:
                            workbook = generate_rider_daily_range(description['start'], description['end'], directory,
                                                                  log=progress_log, cancelled=cancelled)
                    elif description['dataset'] == RIDER_ARCHIVE_DATASET:
                        from xiaoxiang_rider_archive import generate_rider_archive
                        workbook = generate_rider_archive(directory, log=progress_log, cancelled=cancelled)
                    elif description['dataset'] in (RIDER_ORDER_DETAIL_DATASET, XIAOXIANG_ATTENDANCE_DATASET):
                        from xiaoxiang_notice_data import generate_notice_merge
                        workbook = generate_notice_merge(description['dataset'], description['start'],
                                                         description['end'], directory,
                                                         log=progress_log, cancelled=cancelled)
                    else:
                        workbook = generate_detail(description['dataset'], description['start'], description['end'],
                                                   directory, log=progress_log, cancelled=cancelled)
                    return [publish(workbook, root, description)]
                run_step([description], rider_daily_download)
        finally:
            COLLECTION_LOCK.release()
        return files

    blue_sources = []
    if selected and selected<=MERCHANT_DATASETS:
        from fengshen_merchant_exports import source_directory as merchant_source_directory,source_key as merchant_source_key
        merchant_outputs=[]
        with managed_runner() as runner:
            for description in requested:
                def merchant_download(description=description):
                    city=description['city'];directory=merchant_source_directory(root,description['dataset'],city);context.update(raw=directory,kind=description['dataset'])
                    source=(config.get('resume_merchant_sources') or {}).get(merchant_source_key(city,description['dataset']))
                    scope={} if city==MERCHANT else {'city':city,'agency_id':mapping[city]}
                    path=runner.merchant_source(description['dataset'],directory,description['start'],description['end'],source,**scope)
                    merchant_outputs.append((description,path))
                    return [publish(path,root,description)]
                run_step([description],merchant_download)
        invitation_sources=[(description,path) for description,path in merchant_outputs
                            if description['dataset']==INVITATIONS]
        if config.get('merchant_by_city') and len(config['cities'])>1 and len(invitation_sources)>1:
            from invitation_summary import merge_invitation_workbooks
            from download_pipeline import reserve_local_work
            reserve_local_work()
            progress_log(f"[汇总] 正在生成多城市邀请记录汇总：{len(invitation_sources)} 个城市")
            summary=root/'merchant_sources'/'invitation_summary.xlsx'
            summary.parent.mkdir(parents=True,exist_ok=True)
            proof=merge_invitation_workbooks([path for _,path in invitation_sources],summary,
                                             {'商家编号':'多个城市','站点范围':'全部可见站点',
                                              '日期范围':'不按日期筛选'})
            summary_item={**invitation_sources[0][0],'city':'多城市','dataset':'invitation_summary',
                          'artifact_role':'summary'}
            entry=publish(summary,root,summary_item)
            files.append(entry)
            checkpoint_manifest()
            progress_log(f"[汇总] 邀请记录汇总已生成：{proof['rows']} 行")
        return files
    blue_city_map = None
    directory_session_version = None
    if 'abnormal_riders' in selected:
        from lanorange_approvals import current_version
        directory_session_version = current_version()
    for description in requested:
        if description['dataset'] not in LANORANGE_DATASETS: continue
        def blue_download():
            nonlocal blue_city_map
            from lanorange_download import collect, load_cities
            kind = description['dataset']
            city = description['city']
            resume = config.get('resume_lanorange_sources', {}).get(source_key(city, kind))
            if not resume and city != ALL_CITIES and blue_city_map is None:
                blue_city_map = load_cities(progress_log, cancelled)
            directory = source_directory(root, city, kind)
            context.update(raw=directory, kind=kind)
            months = platform_months(config, kind)
            if config.get('lanorange_full_delivery'):
                from lanorange_full import collect_full
                source=collect_full(kind,directory,progress_log,cancelled,resume,months=months)
                proof=json.loads((directory/'source_receipt.json').read_text(encoding='utf-8'))
                description['delivery_kind']=proof['delivery_kind']
            else:
                # 按城市直接导出：平台原表即本城市原始资料，成品仍需格式化/按月裁剪。
                if city != ALL_CITIES:
                    description['delivery_kind']='platform_original'
                source = collect(kind, directory, progress_log, cancelled,
                                 resume, months=months,
                                 **({'city': city, 'city_id': (blue_city_map or {}).get(city)} if city != ALL_CITIES else {}))
            blue_sources.append((description, source))
            return [publish(source, root, description)]
        run_step([description], blue_download)
    if config.get('lanorange_by_city') and len(config['cities']) > 1 and blue_sources:
        from lanorange_summary import build_summary
        from download_pipeline import reserve_local_work
        reserve_local_work()
        summary = build_summary(root, blue_sources, results, cancelled)
        summary_item = {**blue_sources[0][0], 'city': '多城市汇总', 'dataset': 'lanorange_summary',
                        'artifact_role': 'summary'}
        entry = publish(summary, root, summary_item)
        files.append(entry)
        checkpoint_manifest()
    # 异常骑手整理（生成表）只依赖蓝橙成品，在进入风神采集前生成，
    # 纯蓝橙任务因此无需风神登录。
    for description in requested:
        if description['dataset'] != 'abnormal_riders':
            continue
        def abnormal_riders_generate(description=description):
            def find(dataset, optional=False):
                fallback = None
                for entry in files:
                    if entry.get('dataset') != dataset:
                        continue
                    candidate = (root / entry['relative_path']).resolve()
                    if not candidate.is_file():
                        continue
                    if entry.get('city') == ALL_CITIES:
                        return candidate
                    fallback = fallback or candidate
                if fallback is not None:
                    return fallback
                if optional:
                    return None
                raise BillCollectionError(
                    f"异常骑手整理缺少来源资料：{DATASETS.get(dataset, dataset)}")
            from abnormal_riders import generate_abnormal_riders
            if blue_only:
                # All platform requests and source publication have finished.
                # This tail never opens a browser or performs another export.
                from download_pipeline import release_collection_for_local_work
                release_collection_for_local_work()
            generated_dir = source_directory(root, ALL_CITIES, 'abnormal_riders')
            generated_dir.mkdir(parents=True, exist_ok=True)
            context.update(raw=generated_dir, kind='abnormal_riders')
            set_phase("generating")
            from station_city_resolution import read_directory
            try:
                station_directory = read_directory(expected_version=directory_session_version)
            except Exception:
                station_directory = {}
                progress_log('站点目录暂未获取：保留人工映射和来源资料中的城市，无法确认的归属标为待核对')
            generated = generate_abnormal_riders(
                find("lanorange_batch_quit"), find("lanorange_rider_quit"),
                find("lanorange_rider_report"), find("lanorange_rider_leave"),
                find("lanorange_rider_archive"), generated_dir,
                log=progress_log, cancelled=cancelled,
                detail_file=find("rider_detail", optional=True),
                info_file=find("rider_info", optional=True), station_directory=station_directory)
            return [publish(generated, root, description)]
        run_step([description], abnormal_riders_generate)
    if all(value['dataset'] in LANORANGE_DATASETS or value['dataset'] == 'abnormal_riders'
           for value in requested):
        return files
    with managed_runner() as runner:
        binding_sources = None
        binding_jobs = []
        binding_tables = {}
        binding_pool = None
        binding_count = sum(1 for value in requested if value['dataset'] == 'payment_binding')
        if binding_count > 1:
            from concurrent.futures import ThreadPoolExecutor
            # 生成阶段 CPU 密集且各城市互不依赖；采集仍串行共用风神会话。
            binding_pool = ThreadPoolExecutor(max_workers=min(2, binding_count),
                                              thread_name_prefix='binding-gen')
        try:
            def local_binding(source_paths, employees, proxies, plan, directory, logger, event, cache, exchange):
                from binding_download import generate_binding
                with generation_context(cache, exchange):
                    return generate_binding(source_paths, employees, proxies, plan, directory, logger, event)

            def finalize_binding_jobs(city=None, month=None):
                jobs = [job for job in binding_jobs if city is None or (job['description']['city'] == city and job['description']['start'][:7] == month)]
                binding_jobs[:] = [job for job in binding_jobs if job not in jobs]
                for job in jobs:
                    def finalize(job=job):
                        context.update(raw=job['directory'], kind='payment_binding')
                        # 先等待后台生成结束（此后日志不再追加），再按序回放缓冲日志。
                        set_phase('generating')
                        file, _ = job['generate']()
                        if job['logs'] is not None:
                            for message, args, kwargs in job['logs']:
                                progress_log(message, *args, **kwargs)
                            job['logs'].clear()
                        return [publish(file, job['output'], job['description'])]
                    run_step([job['description']], finalize)
            for city in config["cities"]:
                _checkpoint(cancelled)
                city_selected = {value["dataset"] for value in requested if value["city"] == city}
                city_selected.difference_update(LANORANGE_DATASETS)
                if not city_selected:
                    continue
                plan = SimpleNamespace(city=city, agency_id=mapping[city], start=config["start"], end=config["end"])
                city_name = archive_component(city)
                raw, output = root / "原始资料" / city_name, root
                raw.mkdir(parents=True)
                output.mkdir(exist_ok=True)
                for kind in sorted(city_selected & MERCHANT_DATASETS):
                    description = item(city, kind)
                    def city_bill(kind=kind, description=description):
                        from fengshen_merchant_exports import source_directory, source_key
                        directory = source_directory(root, kind, city)
                        context.update(raw=directory, kind=kind)
                        source = config.get('resume_merchant_sources', {}).get(source_key(city, kind))
                        path = runner.merchant_source(kind, directory, description['start'], description['end'], source,
                                                      city=city, agency_id=mapping[city])
                        return [publish(path, root, description)]
                    run_step([description], city_bill)
                if 'payment_binding' in city_selected:
                    from binding_download import month_periods, generate_binding
                    from binding_sources_http import BindingSources
                    if binding_sources is None:
                        binding_sources = BindingSources(root / '原始资料' / '支付绑定公共来源', progress_log, cancelled)
                    for month, first, last in month_periods(config['start'], config['end']):
                        description = item(city, 'payment_binding', first, last)
                        if _item_key(description) not in requested_keys:
                            continue
                        def prepare():
                            directory = raw / 'payment_binding' / month
                            directory.mkdir(parents=True)
                            context.update(raw=directory, kind='payment_binding')
                            binding_plan = SimpleNamespace(city=city, agency_id=plan.agency_id,
                                                           start=first, end=last, month=month)
                            # Authenticate external dependencies before submitting Fengshen exports.
                            materials = config.get('resume_binding_materials', {}).get(city + '|' + month)
                            if materials:
                                from binding_recovery import copy_materials
                                source_paths = copy_materials(materials, directory / 'recovered')
                                employees, proxies = source_paths.pop('employees'), source_paths.pop('proxies')
                                atomic_json(directory / 'recovery_proof.json', {'original_run': config.get('retry_of'),
                                            'materials': materials, 'exports_submitted': False})
                                progress_log('[恢复] 五类原始资料完整性校验通过，仅恢复生成，不重新导出')
                            else:
                                source_paths = {}
                                if config.get('task_kind') != 'payroll_source':
                                    employees = binding_sources.employees()
                                    proxies = binding_sources.proxies(month)
                            kinds = ('rider_info', 'rider_detail', 'receive_account') if config.get('task_kind') == 'payroll_source' else ('rider_detail', 'receive_account', 'rider_info')
                            for kind in (() if materials else kinds):
                                _checkpoint(cancelled)
                                if kind == 'receive_account':
                                    calendar = MonthlyBillRequest(month)
                                    source_plan = SimpleNamespace(city=city, agency_id=plan.agency_id, month=month,
                                                                  start=calendar.start, end=calendar.end)
                                else:
                                    source_plan = binding_plan
                                source_raw = directory / kind
                                info = None
                                if kind == 'rider_info' and not config.get('refresh_rider_info'):
                                    info = same_day_rider_info_snapshot(
                                        snapshot_roots, source_plan, source_raw, progress_log, exclude_dir=root)
                                if info is None:
                                    info = runner.rider_source(source_plan, source_raw, kind)
                                source_paths[kind] = _rider_source_file(info, source_raw, kind, source_plan)
                            if not materials and config.get('task_kind') == 'payroll_source':
                                employees = binding_sources.employees()
                                proxies = binding_sources.proxies(month)
                            set_phase('validating')
                            # 与账单使用同一范围；全量模式不预先丢弃取分离骑手。
                            include = separation_filter.filter_direction(config)
                            for kind in source_paths:
                                if kind in separation_filter.COLUMNS and include is not None:
                                    filtered, proof = separation_filter.filter_table(
                                        source_paths[kind], kind, include, directory)
                                    source_paths[kind] = filtered
                                    progress_log(f"[过滤] {DATASETS.get(kind, kind)} 取分离站点过滤"
                                                 f"（{'仅保留' if include else '排除'}）："
                                                 f"{proof['rows_before']} → {proof['rows_after']} 行")
                            exchange = TableExchange(shared_cache()) if 'abnormal_followup' in city_selected else None
                            binding_tables[(city, month)] = exchange
                            if binding_pool is None:
                                generate = partial(local_binding, source_paths, employees, proxies, binding_plan,
                                                   directory, progress_log, cancelled, shared_cache(), exchange)
                                logs = None
                            else:
                                logs = []
                                def buffered(message, *args, **kwargs):
                                    logs.append((message, args, kwargs))
                                future = binding_pool.submit(local_binding, source_paths, employees, proxies,
                                                             binding_plan, directory, buffered, cancelled, shared_cache(), exchange)
                                generate = future.result
                            binding_jobs.append({'description': description, 'output': output, 'directory': directory,
                                                 'generate': generate, 'logs': logs})
                        run_prepare([description], prepare)
                daily_selected = [key for key in ("delivery_fee", "penalty") if key in city_selected]
                if daily_selected:
                    def daily():
                        directory = raw / "agency_daily"
                        source_dir = resume_daily_sources.get(city)
                        context.update(raw=directory, kind="agency_daily", resuming=source_dir is not None)
                        if source_dir is not None:
                            source_dir = Path(source_dir).resolve()
                            if source_dir.is_relative_to(root) or not source_dir.is_dir():
                                raise BillCollectionError("原日账单恢复目录无效")
                            progress_log("[恢复] 仅查询原日账单任务并下载，不重新提交导出")
                            manifest = runner.resume_daily(plan, directory, set(daily_selected), source_dir)
                        else:
                            manifest = runner.daily(plan, directory, set(daily_selected))
                        set_phase("validating")
                        source = _download_file(manifest, directory, "agency_daily", plan)
                        unpacked = unpack_daily(source, raw / "daily_unpacked", expected_kinds={DATASETS[k] for k in daily_selected})
                        staged = []
                        for kind in daily_selected:
                            validate_daily(unpacked[DATASETS[kind]], plan)
                        for kind in daily_selected:
                            source = unpacked[DATASETS[kind]]
                            staged.append(publish(source, output, item(city, kind)))
                        return staged
                    run_step([item(city, key) for key in daily_selected], daily)
                if "rider_monthly" in city_selected:
                    for month in config["months"]:
                        request = MonthlyBillRequest(month)
                        if _item_key(item(city, "rider_monthly", request.start, request.end)) not in requested_keys:
                            continue
                        monthly_plan = SimpleNamespace(**vars(plan), month=month)
                        def monthly():
                            directory = raw / "rider_monthly" / month
                            context.update(raw=directory, kind="rider_monthly")
                            manifest = runner.monthly(monthly_plan, directory)
                            set_phase("validating")
                            source = _download_file(manifest, directory, "rider_monthly", monthly_plan)
                            clean_rider_bill(source, directory / "validated.csv", monthly_plan)
                            return [publish(source, output,
                                            item(city, "rider_monthly", request.start, request.end))]
                        run_step([item(city, "rider_monthly", request.start, request.end)], monthly)
                order_selected = [key for key in ("fraud", "problem") if key in city_selected]
                if order_selected:
                    def orders():
                        batches = date_batches(plan.start, plan.end)
                        source_dir = resume_order_sources.get(city)
                        context.update(raw=raw / "issue_orders", kind="issue_orders", resuming=source_dir is not None)
                        pipeline, prepared = None, None
                        if source_dir is not None:
                            source_dir = Path(source_dir).resolve()
                            if source_dir.is_relative_to(root) or not source_dir.is_dir():
                                raise BillCollectionError("原运单恢复目录无效")
                            progress_log("[恢复] 复用原运单与报告文件，不重新提交导出")
                            downloads = runner.resume_orders(plan, raw / "issue_orders", set(order_selected), source_dir)
                        elif hasattr(runner, "orders_batch"):
                            from order_pipeline import OrderPipeline
                            owner_key = hashlib.sha256(config["owner"].encode()).hexdigest()[:24]
                            cache_path = Path(__file__).parent / ".local_downloads" / "order_cache" / owner_key / "sources.sqlite3"
                            def progress(value):
                                update_item({"status": "running", "phase": current_phase, "_run_event": True,
                                             "order_progress": value})
                            pipeline = OrderPipeline(raw, plan, set(order_selected), cache_path, cancelled, progress,
                                                     refresh=config.get("refresh_history", False))
                            downloads, prepared, batches = pipeline.collect(runner)
                        else:
                            downloads = runner.orders(plan, raw / "issue_orders", set(order_selected))
                        set_phase("validating")
                        generated = raw / "order_processed"
                        generated.mkdir(exist_ok=pipeline is not None)
                        from order_metrics import measurements
                        timings = pipeline.metrics.setdefault("timings", {}) if pipeline is not None else {}
                        with measurements(timings):
                            prepare_order_files(downloads, raw, generated, plan, batches,
                                                selected_kinds={DATASETS[k] for k in order_selected},
                                                **({"prepared_slices": prepared} if prepared is not None else {}))
                        if pipeline is not None:
                            pipeline.complete()
                        staged = []
                        for kind in order_selected:
                            source = generated / (city + "-" + DATASETS[kind] + "_auto.csv")
                            staged.append(publish(source, output, item(city, kind)))
                        return staged
                    run_step([item(city, key) for key in order_selected], orders)
                if "delivery_waybill" in city_selected:
                    def waybill():
                        from waybill_workbook import merge_waybill_workbooks, write_waybill_workbook
                        directory = raw / "delivery_waybill"
                        context.update(raw=directory, kind="delivery_waybill")
                        directory.mkdir(parents=True, exist_ok=True)
                        source_dir = resume_waybill_sources.get(city)
                        if source_dir is not None:
                            source_dir = Path(source_dir).resolve()
                            if source_dir.is_relative_to(root) or not source_dir.is_dir():
                                raise BillCollectionError("原运单恢复目录无效")
                            progress_log("[恢复] 复用已下载的运单原始文件，不重新提交导出")
                            sources = []
                            for first, last in date_batches(plan.start, plan.end,
                                                            today=dt.date.fromisoformat(plan.end)):
                                batch_dir = source_dir / (first + "_" + last)
                                manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
                                for entry in manifest["files"]:
                                    sources.append(batch_dir / entry["path"])
                            set_phase("validating")
                        else:
                            downloads = runner.waybills_created(
                                plan, directory, all_city_send=bool(config.get("waybill_all_city_send")))
                            set_phase("validating")
                            sources = []
                            for manifest in downloads:
                                batch_fields = dict(vars(plan))
                                batch_fields.update(start=manifest["start"], end=manifest["end"])
                                batch_plan = SimpleNamespace(**batch_fields)
                                sources.append(_download_file(
                                    manifest, directory / (manifest["start"] + "_" + manifest["end"]),
                                    "delivery_waybill", batch_plan))
                        from download_pipeline import reserve_local_work
                        reserve_local_work()
                        tmp = directory / ('.成品_' + uuid.uuid4().hex + '.xlsx')
                        try:
                            progress_log(f"[生成] 正在生成运单成品：{len(sources)} 批原始文件")
                            if len(sources) == 1:
                                generated = write_waybill_workbook(sources[0], tmp, lambda: _checkpoint(cancelled))
                            else:
                                generated = merge_waybill_workbooks(sources, tmp, lambda: _checkpoint(cancelled))
                            progress_log(f"[生成] 运单成品已生成：{generated['rows']} 行")
                            return [publish(tmp, output, item(city, "delivery_waybill"))]
                        finally:
                            tmp.unlink(missing_ok=True)
                    run_step([item(city, "delivery_waybill")], waybill)
                if "receive_account" in city_selected:
                    for month in config["months"]:
                        request = MonthlyBillRequest(month)
                        if _item_key(item(city, "receive_account", request.start, request.end)) not in requested_keys:
                            continue
                        account_plan = SimpleNamespace(city=city, agency_id=plan.agency_id,
                                                       start=request.start, end=request.end, month=month)
                        def receive_account():
                            directory = raw / "receive_account" / month
                            context.update(raw=directory, kind="receive_account")
                            info = runner.rider_source(account_plan, directory, "receive_account")
                            set_phase("validating")
                            source = _rider_source_file(info, directory, "receive_account", account_plan)
                            return [publish(source, output,
                                            item(city, "receive_account", request.start, request.end))]
                        run_step([item(city, "receive_account", request.start, request.end)], receive_account)
                if "rider_info" in city_selected:
                    info_plan = SimpleNamespace(**vars(plan), month=plan.start[:7])
                    def rider_info():
                        directory = raw / "rider_info"
                        context.update(raw=directory, kind="rider_info")
                        info = None
                        if not config.get('refresh_rider_info'):
                            info = same_day_rider_info_snapshot(
                                snapshot_roots, info_plan, directory, progress_log, exclude_dir=root)
                        if info is None:
                            info = runner.rider_source(info_plan, directory, "rider_info")
                        set_phase("validating")
                        source = _rider_source_file(info, directory, "rider_info", info_plan)
                        return [publish(source, output, item(city, "rider_info"))]
                    run_step([item(city, "rider_info")], rider_info)
                if "goods_rent" in city_selected:
                    rent_plan = SimpleNamespace(**vars(plan), month=plan.start[:7],
                                                **{key: config[key] for key in ('include_separation', 'exclude_separation') if key in config})
                    def goods_rent():
                        directory = raw / "goods_rent"
                        context.update(raw=directory, kind="goods_rent")
                        info = runner.goods_rent(rent_plan, directory)
                        set_phase("validating")
                        source = _rider_source_file(info, directory, "goods_rent", rent_plan)
                        return [publish(source, output, item(city, "goods_rent"))]
                    run_step([item(city, "goods_rent")], goods_rent)
                if "rider_detail" in city_selected:
                    detail_plan = SimpleNamespace(**vars(plan), month=plan.start[:7])
                    def rider_detail():
                        directory = raw / "rider_detail"
                        city_source = resume_sources.get(city, resume_source)
                        context.update(raw=directory, kind="rider_detail", resuming=city_source is not None or bool(resume_from))
                        if city_source is not None or resume_from:
                            if city_source is not None:
                                # Only the task manager creates this trusted path;
                                # the original run may be in another archive month.
                                source_dir = Path(city_source).resolve()
                                if source_dir.is_relative_to(root) or not source_dir.is_dir():
                                    raise BillCollectionError("原明细任务恢复目录无效")
                            else:
                                # Compatibility for existing direct service callers.
                                previous = (root.parent / resume_from).resolve()
                                source_dir = (previous / plan.agency_id / "raw" / "rider_detail").resolve()
                                if previous == root or not previous.is_relative_to(root.parent) or not source_dir.is_relative_to(previous):
                                    raise BillCollectionError("原明细任务恢复路径无效")
                            progress_log("[恢复] 仅查询原平台导出任务并下载，不重新提交导出")
                            info = runner.resume_detail(detail_plan, directory, source_dir)
                        else:
                            info = runner.rider_source(detail_plan, directory, "rider_detail")
                        set_phase("validating")
                        source = _rider_source_file(info, directory, "rider_detail", detail_plan)
                        return [publish(source, output,
                                        item(city, "rider_detail"))]
                    run_step([item(city, "rider_detail")], rider_detail)
                if "abnormal_followup" in city_selected:
                    # 跟进表要读本任务的支付绑定成品，必须先把后台生成发布完。
                    from binding_download import month_periods as _followup_month_periods
                    from abnormal_followup import generate_abnormal_followup
                    for month, first, last in _followup_month_periods(config['start'], config['end']):
                        finalize_binding_jobs(city, month)
                        if _item_key(item(city, "abnormal_followup", first, last)) not in requested_keys:
                            continue
                        def abnormal():
                            def find(dataset):
                                for entry in files:
                                    if entry.get('dataset') != dataset:
                                        continue
                                    if entry.get('city') not in (city, ALL_CITIES):
                                        continue
                                    if dataset in ("payment_binding", "rider_monthly") \
                                            and entry.get('start', '')[:7] != month:
                                        continue
                                    source = (root / entry['relative_path']).resolve()
                                    if source.is_file():
                                        return source
                                raise BillCollectionError(
                                    f"异常骑手跟进缺少来源资料：{DATASETS.get(dataset, dataset)}")
                            binding_file = find("payment_binding")
                            ub_file = find("rider_monthly")
                            goods_file = find("goods_rent")
                            price_file = find("lanorange_part_price")
                            archive_file = find("lanorange_rider_archive")
                            generated_dir = raw / "abnormal_followup"
                            generated_dir.mkdir(parents=True, exist_ok=True)
                            context.update(raw=generated_dir, kind="abnormal_followup")
                            set_phase("generating")
                            exchange = binding_tables.pop((city, month), None)
                            try:
                                with generation_context(shared_cache(), exchange):
                                    generated = generate_abnormal_followup(
                                        binding_file, ub_file, price_file, archive_file, goods_file,
                                        city, month, generated_dir, log=progress_log, cancelled=cancelled,
                                        stamp=config.get('archive_created_at'))
                            finally:
                                if exchange is not None:
                                    exchange.clear()
                            return [publish(generated, output, item(city, "abnormal_followup", first, last))]
                        run_step([item(city, "abnormal_followup", first, last)], abnormal)
            detail_cities = {value["city"] for value in requested if value["dataset"] == "rider_detail"}
            detail_files = {entry.get("city"): entry for entry in files if entry.get("dataset") == "rider_detail"}
            detail_items = [value for value in requested if value["dataset"] == "rider_detail"]
            if len(detail_cities) > 1 and detail_cities <= set(detail_files):
                def merge_rider_details():
                    pairs = [(value["city"], root / detail_files[value["city"]]["relative_path"])
                             for value in detail_items]
                    merged_dir = root / "原始资料" / "骑手数据明细合并"
                    merged_dir.mkdir(parents=True, exist_ok=True)
                    from download_pipeline import reserve_local_work
                    reserve_local_work()
                    tmp = merged_dir / ('.合并_' + uuid.uuid4().hex + '.csv')
                    merge_rider_detail_csv(pairs, tmp)
                    set_phase("publishing")
                    merged = publish(tmp, root, {**detail_items[0], "city": "多城市",
                                                 "pre_formatted": True})
                    files.append(merged)
                    checkpoint_manifest()
                    progress_log(f"[合并] 骑手数据明细：{len(pairs)} 个城市合并为一份成品")
                merge_rider_details()
            waybill_cities = {value["city"] for value in requested if value["dataset"] == "delivery_waybill"}
            waybill_files = {entry.get("city"): entry for entry in files if entry.get("dataset") == "delivery_waybill"}
            waybill_items = [value for value in requested if value["dataset"] == "delivery_waybill"]
            if len(waybill_cities) > 1 and waybill_cities <= set(waybill_files):
                def merge_waybills():
                    from waybill_workbook import merge_waybill_workbooks
                    sources = [root / waybill_files[value["city"]]["relative_path"]
                               for value in waybill_items]
                    merged_dir = root / "原始资料" / "运单数据合并"
                    merged_dir.mkdir(parents=True, exist_ok=True)
                    from download_pipeline import reserve_local_work
                    reserve_local_work()
                    tmp = merged_dir / ('.合并_' + uuid.uuid4().hex + '.xlsx')
                    try:
                        merge_waybill_workbooks(sources, tmp, lambda: _checkpoint(cancelled))
                        merged = publish(tmp, root, {**waybill_items[0], "city": "多城市",
                                                     "pre_formatted": True})
                        files.append(merged)
                        checkpoint_manifest()
                        progress_log(f"[合并] 运单数据：{len(sources)} 个城市合并为一份成品")
                    finally:
                        tmp.unlink(missing_ok=True)
                merge_waybills()
            finalize_binding_jobs()
        finally:
            if binding_pool is not None:
                binding_pool.shutdown(wait=True, cancel_futures=True)
            for exchange in binding_tables.values():
                if exchange is not None:
                    exchange.clear()
    return files
