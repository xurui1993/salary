"""异常骑手跟进（生成表）组装器。

以「骑手支付绑定（生成表）」为基准，关联物资租用登记、风神骑手月度 UB 账单、
价格档案、骑手档案，组装成代码定义的 9 工作表工作簿。

当前阶段仅原样放入来源数据、不做分析：

- 主表（X月异常骑手跟进表）按代码定义生成 3 行表头与格式；行按骑手详情表
  团队名称+骑手ID 去重（跨站分行不合并），团队名称/骑手ID/骑手姓名取自骑手详情表，
  骑手身份证按骑手ID关联骑手信息表，发薪工具是否绑定按骑手身份证关联绑定情况表的
  绑定情况列（含「未绑定」记未绑定，其余记已绑定；绑定表查无该身份证也记未绑定）；
  并按身份证号原值从蓝橙员工档案补充合作类型/状态/招聘来源/
  是否寒暑假工，未匹配标注“蓝橙未入职”；
- 主表活跃天/完单量/最后出勤日按团队名称+骑手ID从骑手详情表汇总
  （仅统计有效完成单>0 的记录，日期文本转为真实日期）；
- 主表兼职无单价报备骑手：仅兼职骑手按身份证号匹配当月/当前城市价格档案，
  价格全部为0或没有记录标“是”，存在正价标“否”；其他合作类型默认“否”；
- 主表薪资方案是否绑定/扣款方案是否绑定：主表「团队名称+骑手ID」严格对应风神薪资
  方案绑定子表的「骑手所属站点名称+骑手ID」，取其基础薪资方案名称ID、扣款方案名称ID
  是否有值；同一键有多份账单时任一份缺方案即「否」，配对不上（含无账单）一律「否」；
- 主表是否异常骑手：状态为解除合作/蓝橙未入职/预解除、最后出勤日距骑手详情表
  最大日期≥3天（含当月无有效完单）、薪资方案或扣款方案未绑定，命中任一即“是”，
  异常原因列写命中项；
- 主表租车天数/住宿天数按团队名称+骑手ID 严格对应租用子表的站点名称+骑手id，
  分别累加物资类型为电动车/住宿的租用天数（月内交集口径），没有记录写 0；
- 主表合作日期按骑手身份证从蓝橙员工档案首行匹配取合作日期，文本日期转真实日期；
- 主表 W 备注：活跃天大于租车天数或住宿天数时分别写「租车天数少于出勤天数」「住宿天数
  少于出勤天数」（同时命中用「；」拼接，租车在前；未租用按 0 天计），Z 列「是否需跟进
  城市维护」按备注是否有内容填是/否；异常原因/备注列宽在全部数据写入后按内容自适应
  （上限 60、长文本换行）；
- 分析表由主表汇总生成：G 列为兼职占比（兼职骑手÷跑单骑手，百分比+红色数据条），
  城市成品按站点、多城市汇总先按拼音升序列城市块和蓝色汇总行、再列站点明细
  （均按「团队名称+骑手ID」分行计数，跨站不合并）；未维护/已维护/风神未绑仅统计
  在跑单的骑手，不再要求「是否异常骑手=是」；首跑按合作日期≥当月 1 日分行计数；涉及活动金额暂不填；
- 说明表置于工作簿首位：按主表实时统计本期概览，并列出异常判定规则/责任方、
  关键字段口径和常见口径 QA，供城市与站点直接跟进；
- 蓝橙员工档案按约定 14 列投影，按当前城市和 U+B/饿了么/淘鲜达 项目筛选，
  并按项目升序；
- 蓝橙价格档案只保留「日期」在目标月份、且城市匹配当前城市的记录；
- 电动车住宿租用只保留租用周期与目标月有交集的数据，排除撤销记录；
- 其余子表原样复制来源成品整表（表头行 + 数据行 + 合并单元格 + 列宽 + 冻结）；
  风神薪资方案绑定子表删除来源前 3 行说明，表头落在第 1 行，并按业务清单重建为 18 列；
- 模板写死的「10月」按目标月份动态替换为「X月」。
"""
from __future__ import annotations

from calendar import monthrange
import ctypes
from datetime import date, datetime, timedelta
import functools
import os
from pathlib import Path
import re

from openpyxl import load_workbook
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from generation_performance import profiled, measured, stage, capture_tables
from excel_styles import style_applier
from source_tables import source_sheet
from parttime_source import rider_bill_header_row
import price_archive
import rider_archive
from download_archive import archive_filename
from fengshen_bill import BillCollectionError, column_width, display_width

from followup_workbook import create_followup_workbook

_DATA_FONT = Font(name='微软雅黑', size=10)
_HEADER_FONT = Font(name='微软雅黑', size=10, bold=True)
_CENTER = Alignment(horizontal='center', vertical='center')
# 子表表头与模板主表第 2/3 行同色（浅橙）
_HEADER_FILL = PatternFill(fill_type='solid', fgColor='FFFBE5D6')
# 主表非空单元格的细实线边框
_THIN_BORDER = Border(left=Side(style='thin'), right=Side(style='thin'),
                      top=Side(style='thin'), bottom=Side(style='thin'))

# 主表固定列：城市取当前城市，其余按骑手详情表/骑手信息表/绑定情况表来源填充
MAIN_FIELDS = ('城市', '团队名称', '骑手ID', '骑手姓名', '骑手身份证', '发薪工具是否绑定')

# 主表从蓝橙员工档案按身份证号关联补充的列（取项目排序后的首行，同 XLOOKUP 首行匹配）
ARCHIVE_FIELDS = ('合作类型', '状态', '招聘来源', '是否寒暑假工', '合作日期')
ARCHIVE_DATE_FIELD = '合作日期'
ARCHIVE_UNJOINED = '蓝橙未入职'
PRICE_FLAG_FIELD = '兼职无单价报备骑手'
PARTTIME = '兼职'

# 主表「是否异常骑手」判定口径：命中任一条件即为「是」
ABNORMAL_STATUSES = ('解除合作', ARCHIVE_UNJOINED, '预解除')
ABSENTEE_DAYS = 3
ABNORMAL_FLAG_FIELD = '是否异常骑手'
ABNORMAL_REASON_FIELD = '异常原因'
SALARY_BINDING_FIELD = '薪资方案是否绑定'
DEDUCTION_BINDING_FIELD = '扣款方案是否绑定'
# 风神薪资方案绑定子表：来源前 3 行为提示/基础信息/方案基本信息，复制后删除，表头落在第 1 行
UB_PREAMBLE_ROWS = 3
UB_HEADER_ROWS = 1
UB_PLAN_PREFIXES = (('薪资方案', '基础薪资方案'), ('扣款方案', '扣款方案'))
# 风神子表仅保留的业务列（按清单顺序重建）；源表表头含换行，匹配时统一去空白
UB_KEEP_HEADERS = (
    '账单ID', '骑手ID', '骑手姓名', '代理商ID', '骑手所属站点ID', '骑手所属站点名称',
    '账单周期', '在职时间', '基础薪资方案名称ID', '扣款方案名称ID',
    '排班内单量', '排班外单单量', '住宿费用（只能下调）', '车辆租金（只能下调）',
    '账单状态', '非一口价单量', '一口价单量', '总单量',
)
# 主表租车天数/住宿天数 ← 电动车住宿租用子表按「站点名称+骑手id」分组、按物资类型求和
RENTAL_DAY_FIELDS = (('租车天数', '电动车'), ('住宿天数', '住宿'))

# 主表 W 备注：活跃天大于对应天数即标注缺口；Z 列按备注是否为空判定是否需跟进
ACTIVE_DAYS_FIELD = '活跃天'
NOTE_FIELD = '备注'
MAINTENANCE_FOLLOWUP_FIELD = '是否需跟进城市维护'
RENTAL_SHORTAGES = (('租车天数', '租车天数少于出勤天数'),
                    ('住宿天数', '住宿天数少于出勤天数'))

# 分析表：城市表按站点汇总，多城市汇总表按城市汇总
GUIDE_FIELD = '说明'
ANALYSIS_FIELD = '分析表'
ANALYSIS_CITY_FIELD = '城市'
ANALYSIS_TEAM_FIELD = '团队名称'
ANALYSIS_TOTAL = '合计'
ANALYSIS_GROUP_TITLES = ((3, '{month}跑单骑手类型'), (8, '异常骑手'),
                         (12, '兼职无单价报备骑手'), (13, '解除合作仍在跑单骑手'),
                         (14, '发薪工具未绑骑手数量'), (15, '{month}首跑(含兼职转全职)'))
ANALYSIS_SUB_HEADERS = ('跑单骑手', '兼职骑手', '全职骑手', '跑单未入职骑手', '兼职占比',
                        '未维护或维护天数少于出勤天', '已维护',
                        '风神未绑薪资方案/扣款方案', '涉及活动金额')
ANALYSIS_MERGES = ('A1:A2', 'B1:B2', 'C1:G1', 'H1:K1', 'L1:L2', 'M1:M2', 'N1:N2', 'O1:O2')
ANALYSIS_WIDTHS = {'A': 8.0, 'B': 36.5, 'H': 18.0, 'J': 18.0, 'K': 14.0,
                   'L': 16.0, 'M': 18.0, 'N': 16.0, 'O': 20.0}
ANALYSIS_DEFAULT_WIDTH = 12.5
# 表头与合计行配色（对齐业务模板截图）：城市/站点与异常骑手黄、骑手类型绿、右侧四列橙
ANALYSIS_HEADER_FILLS = (((1, 2), 'FFFFFF00'), ((3, 7), 'FF92D050'),
                         ((8, 11), 'FFFFFF00'), ((12, 15), 'FFFFC000'))
ANALYSIS_TOTAL_FILL = 'FF00B0F0'
# 数据列：跑单/兼职/全职/未入职/兼职占比、未维护/已维护/风神未绑/活动金额、
# 兼职无单价/解除合作仍在跑/发薪未绑/首跑（活动金额暂不填）
ANALYSIS_DATA_COLUMNS = 15
# 兼职占比列（G）写 0-1 小数，格式 0.00%，并加红色数据条
ANALYSIS_RATIO_COLUMN = 7
ANALYSIS_RATIO_FORMAT = '0.00%'

# 说明子表：异常判定规则、字段口径与跟进建议（供城市/站点直接使用）
GUIDE_RULES = (
    ('状态解除合作', '主表「状态」为解除合作', '骑手信息表 / 蓝橙员工档案',
     '核实是否已离职；仍在跑单的确认是否转站或转项目', '城市/站点'),
    ('状态蓝橙未入职', '主表「状态」为蓝橙未入职（档案未按身份证匹配）', '蓝橙员工档案',
     '核对身份证与站点，补录蓝橙档案', '城市'),
    ('状态预解除', '主表「状态」为预解除', '骑手信息表 / 蓝橙员工档案',
     '确认离职日期，提前安排运力', '城市/站点'),
    ('3天以上未出勤', '最后出勤日距本期详情表最大日期≥3天', '骑手详情表',
     '电话回访确认返岗或离职，及时更新状态', '站点'),
    ('当月无有效完单', '当月没有有效完成单记录', '骑手详情表',
     '核实是否新入职未开单或已离职', '站点'),
    ('薪资方案未绑定', '风神账单按「站点名称+骑手ID」严格配对，任一账单缺基础薪资方案或没有账单',
     '风神薪资方案绑定', '联系薪资组补方案；跨站骑手逐站点核对', '薪资组/城市'),
    ('扣款方案未绑定', '同上，扣款方案名称ID 为空', '风神薪资方案绑定',
     '联系薪资组补方案；跨站骑手逐站点核对', '薪资组/城市'),
)
GUIDE_FIELDS = (
    ('异常骑手', 'O 列', '命中任一异常条件填「是」，否则「否」'),
    ('异常原因', 'P 列', '按规则顺序记录命中项，多项用「；」拼接；未命中为空'),
    ('发薪工具是否绑定', 'K 列',
     '按骑手身份证匹配绑定情况表「绑定情况」：含「未绑定」记未绑定，其余（含代发）记已绑定；'
     '绑定表查无该身份证也记未绑定'),
    ('租车天数 / 住宿天数', 'U / V 列', '按「站点名称+骑手ID」累加当月租用天数，无记录填 0'),
    ('备注（租用缺口）', 'W 列',
     '活跃天>租车天数写「租车天数少于出勤天数」；活跃天>住宿天数写「住宿天数少于出勤天数」；'
     '同时命中用「；」拼接，租车在前，0 天也标'),
    ('是否需跟进城市维护', 'Z 列', 'W 有内容填「是」，W 为空填「否」'),
    ('合作日期', 'AE 列', '按身份证从蓝橙员工档案首行匹配；未匹配显示「蓝橙未入职」'),
    ('分析表维护与方案三列', 'H / I / J 列', '未维护/已维护/风神未绑仅要求「活跃天>0」，不按是否异常骑手筛选'),
    ('首跑（含兼职转全职）', '分析表 O 列',
     '合作日期≥当月1日，按「站点+骑手ID」分行计数（与 COUNTIFS 一致）'),
    ('涉及活动金额', '分析表 K 列', '暂不填'),
)
GUIDE_QA = (
    ('为什么租车、住宿都是 0 也会标备注？', '按字面口径，活跃天>0 即判定为天数缺口，0 天同样标注。'),
    ('为什么商翼已绑定但发薪工具显示未绑定？',
     'K 列取绑定情况表的「绑定情况」而非仅商翼：风神或商翼任一未绑定即记未绑定。'),
    ('为什么同一骑手会有多行？',
     '主表与分析表均按「团队名称+骑手ID」分行，跨站骑手分别计数，不合并。'),
    ('为什么显示「蓝橙未入职」？', '蓝橙员工档案未按身份证匹配到，并不代表实际未入职，请城市核对档案。'),
    ('为什么风神未绑人数比实际少？', '分析表J列统计所有活跃天>0且薪资或扣款方案未绑定的骑手，不限是否异常；未跑单的不计入。'),
    ('W 备注和 P 异常原因是什么关系？', 'W 是租车/住宿天数缺口，不参与异常判定；P 是异常判定结果，两者独立。'),
)

# 主表标题/表头中的月份占位（模板固定为「10月」）
_TEMPLATE_MONTH = '10月'


def _checkpoint(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise BillCollectionError('异常骑手跟进生成已取消')


def _find_sheet(book, suffix):
    """按名称尾缀定位 sheet；返回 None 表示未找到。"""
    for ws in book.worksheets:
        if ws.title.endswith(suffix):
            return ws
    return None


def _source_sheet(source_book, suffix):
    """从来源成品定位 sheet：suffix 为 None 时取第一个非 options 辅助 sheet。"""
    if suffix is None:
        for ws in source_book.worksheets:
            if ws.title.startswith('options'):
                continue
            return ws
        raise BillCollectionError('来源成品无可用工作表')
    for ws in source_book.worksheets:
        if ws.title.endswith(suffix):
            return ws
    raise BillCollectionError(f'来源成品缺少工作表：{suffix}')


def _center_columns(ws, count=None):
    for column in range(1, (count or ws.max_column) + 1):
        ws.column_dimensions[get_column_letter(column)].alignment = _CENTER


def _center_sheet(ws):
    """居中表内已有单元格；空白单元格由列默认样式覆盖。"""
    for cell in ws._cells.values():
        cell.alignment = _CENTER
    _center_columns(ws)


def _center_header_rows(ws, rows):
    """表头整行居中，包含合并区域内的空白占位单元格。"""
    for row in range(1, rows + 1):
        for column in range(1, ws.max_column + 1):
            ws.cell(row=row, column=column).alignment = _CENTER


@measured('copy_source_sheets')
def _copy_sheet(src_ws, dst_ws, header_rows=1):
    """把来源 sheet 的值、合并单元格、列宽、行高复制到目标 sheet，并全表居中。"""
    header_style = style_applier(dst_ws, font=_HEADER_FONT, alignment=_CENTER)
    data_style = style_applier(dst_ws, font=_DATA_FONT, alignment=_CENTER)
    # 清空目标（模板子表为空，此处兜底）
    if dst_ws.max_row > 0:
        dst_ws.delete_rows(1, dst_ws.max_row)
    for rng in src_ws.merged_cells.ranges:
        dst_ws.merge_cells(str(rng))
    for col, dim in src_ws.column_dimensions.items():
        if dim.width is not None:
            dst_ws.column_dimensions[col].width = dim.width
    for row, dim in src_ws.row_dimensions.items():
        if dim.height is not None:
            dst_ws.row_dimensions[row].height = dim.height
    # 统一冻结到表头下一行，不继承来源成品的任意冻结位置
    dst_ws.freeze_panes = f'A{header_rows + 1}'
    for src_row in src_ws.iter_rows():
        for src_cell in src_row:
            if src_cell.value is None:
                continue
            dst_cell = dst_ws.cell(row=src_cell.row, column=src_cell.column, value=src_cell.value)
            (header_style if src_cell.row <= header_rows else data_style)(dst_cell)
    _center_header_rows(dst_ws, header_rows)
    for row in range(1, header_rows + 1):
        for column in range(1, src_ws.max_column + 1):
            dst_ws.cell(row=row, column=column).fill = _HEADER_FILL
    _center_columns(dst_ws, src_ws.max_column)


_DETAIL_DATE = re.compile(r'(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})')
_TEAM_SPACE = re.compile(r'[\s\u200b\u200c\u200d\u2060\ufeff]+')
_ACTIVITY_FIELDS = {'days': '活跃天', 'orders': '完单量', 'last': '最后出勤日'}


def _team_key(value):
    """统一团队名称的全/半角括号与空白，避免主表清洗后与详情表原值不相等。"""
    text = '' if value is None else str(value)
    return _TEAM_SPACE.sub('', text).replace('（', '(').replace('）', ')')


def _rider_key(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return '' if value is None else str(value).strip()


_ZH_COMPARE = None


def _zh_compare(left, right):
    """简体中文拼音比较（Windows 排序规则）；非 Windows 回退逐字符比较。"""
    global _ZH_COMPARE
    if os.name != 'nt':
        return (left > right) - (left < right)
    if _ZH_COMPARE is None:
        compare = ctypes.WinDLL('kernel32').CompareStringW
        compare.argtypes = (ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_wchar_p, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int)
        compare.restype = ctypes.c_int
        _ZH_COMPARE = compare
    # LCID 0x0804 = zh-CN；返回 1/2/3 对应小于/等于/大于
    return _ZH_COMPARE(0x0804, 0, left, -1, right, -1) - 2


_zh_sort_key = functools.cmp_to_key(_zh_compare)


def _numeric_rider_id(value):
    """纯数字且≤15位（无前导零）的骑手ID转数值写入，超长或有前导零时保持文本。"""
    if isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip() if value is not None else ''
    if len(text) <= 15 and text.isdigit() and not (len(text) > 1 and text[0] == '0'):
        return int(text)
    return value


def _order_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _detail_day(value):
    """把详情表日期（文本、日期或 Excel 序列号）转为 date；无法识别返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    match = _DETAIL_DATE.search(str(value or ''))
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _activity_summary(detail):
    """按团队名称+骑手ID聚合有效完成单>0的记录。"""
    if hasattr(detail, '_followup_analysis'):
        data = detail._followup_analysis
        return data['activity'], data['invalid']
    rows = detail.iter_rows()
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('骑手详情表缺少表头')
    positions = {}
    for index, cell in enumerate(header):
        text = str(cell.value).strip() if cell is not None and cell.value is not None else ''
        if text and text not in positions:
            positions[text] = index
    missing = [name for name in ('日期', '骑手ID', '团队名称', '有效完成单')
               if name not in positions]
    if missing:
        raise BillCollectionError('骑手详情表缺少字段：' + '、'.join(missing))
    date_col, rider_col = positions['日期'], positions['骑手ID']
    team_col, order_col = positions['团队名称'], positions['有效完成单']
    summary = {}
    invalid_dates = 0
    for row in rows:
        values = [cell.value for cell in row]
        if not any(value is not None for value in values):
            continue
        orders = _order_value(values[order_col] if order_col < len(values) else None)
        if orders is None or orders <= 0:
            continue
        rider = _rider_key(values[rider_col] if rider_col < len(values) else None)
        if not rider:
            continue
        key = (_team_key(values[team_col] if team_col < len(values) else None), rider)
        entry = summary.setdefault(key, [0, 0, None])
        entry[0] += 1
        entry[1] += orders
        day = _detail_day(values[date_col] if date_col < len(values) else None)
        if day is None:
            invalid_dates += 1
        elif entry[2] is None or day > entry[2]:
            entry[2] = day
    return summary, invalid_dates


@measured('fill_activity')
def _fill_activity(main_ws, binding_book):
    """主表按团队名称+骑手ID从骑手详情表汇总活跃天、完单量和最后出勤日。"""
    summary, invalid_dates = _activity_summary(_source_sheet(binding_book, '骑手详情表'))
    header = {}
    for column in range(1, main_ws.max_column + 1):
        value = main_ws.cell(row=3, column=column).value
        if value is not None and str(value).strip() not in header:
            header[str(value).strip()] = column
    missing = [name for name in ('团队名称', '骑手ID') if name not in header]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    columns = {}
    for key, suffix in _ACTIVITY_FIELDS.items():
        columns[key] = next((column for name, column in header.items()
                             if name.endswith(suffix)), None)
    missing = [suffix for key, suffix in _ACTIVITY_FIELDS.items() if columns[key] is None]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    matched = 0
    for row_index in range(4, main_ws.max_row + 1):
        team = main_ws.cell(row=row_index, column=header['团队名称']).value
        rider = _rider_key(main_ws.cell(row=row_index, column=header['骑手ID']).value)
        entry = summary.get((_team_key(team), rider)) if rider else None
        if entry is not None:
            matched += 1
        days, orders, last = entry if entry is not None else (0, 0, None)
        if isinstance(orders, float) and orders.is_integer():
            orders = int(orders)
        for key, value in (('days', int(days)), ('orders', orders)):
            cell = main_ws.cell(row=row_index, column=columns[key], value=value)
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
        cell = main_ws.cell(row=row_index, column=columns['last'])
        cell.value = datetime.combine(last, datetime.min.time()) if last is not None else None
        cell.number_format = 'yyyy-mm-dd'
        cell.font = _DATA_FONT
        cell.alignment = _CENTER
    return matched, len(summary), invalid_dates


def _header_positions(rows, required):
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('来源表缺少表头')
    positions = {}
    for index, cell in enumerate(header):
        text = str(cell.value).strip() if cell is not None and cell.value is not None else ''
        if text and text not in positions:
            positions[text] = index
    missing = [name for name in required if name not in positions]
    if missing:
        raise BillCollectionError('来源表缺少字段：' + '、'.join(missing))
    return positions


@measured('analyze_detail_once')
def _prepare_detail_analysis(sheet):
    rows = sheet.iter_rows()
    positions = _header_positions(rows, ('团队名称', '骑手ID', '骑手姓名', '日期', '有效完成单'))
    members, activity = {}, {}
    latest, invalid = None, 0
    for row in rows:
        values = [cell.value for cell in row]
        if not any(value is not None for value in values):
            continue
        def get(field):
            index = positions[field]
            return values[index] if index < len(values) else None
        day = _detail_day(get('日期'))
        if day is not None and (latest is None or day > latest):
            latest = day
        rider = _rider_key(get('骑手ID'))
        if not rider:
            continue
        team, name = get('团队名称'), get('骑手姓名')
        if name is not None and not str(name).strip():
            name = None
        key = (_team_key(team), rider)
        if key not in members:
            members[key] = [team, rider, name]
        elif members[key][2] is None and name is not None:
            members[key][2] = name
        orders = _order_value(get('有效完成单'))
        if orders is None or orders <= 0:
            continue
        entry = activity.setdefault(key, [0, 0, None])
        entry[0] += 1; entry[1] += orders
        if day is None:
            invalid += 1
        elif entry[2] is None or day > entry[2]:
            entry[2] = day
    sheet._followup_analysis = {'members': list(members.values()), 'activity': activity,
                               'invalid': invalid, 'latest': latest}
    return sheet._followup_analysis


def _detail_members(detail_ws):
    """主表行源：骑手详情表按出现顺序取团队名称+骑手ID组合，跨站分行不合并。"""
    if hasattr(detail_ws, '_followup_analysis'):
        return detail_ws._followup_analysis['members']
    positions = _header_positions(detail_ws.iter_rows(), ('团队名称', '骑手ID', '骑手姓名'))
    team_col, rider_col, name_col = positions['团队名称'], positions['骑手ID'], positions['骑手姓名']
    members = {}
    for row in detail_ws.iter_rows(min_row=2):
        values = [cell.value for cell in row]
        if not any(value is not None for value in values):
            continue
        rider = _rider_key(values[rider_col] if rider_col < len(values) else None)
        if not rider:
            continue
        team = values[team_col] if team_col < len(values) else None
        name = values[name_col] if name_col < len(values) else None
        if name is not None and not str(name).strip():
            name = None
        key = (_team_key(team), rider)
        if key in members:
            if members[key][2] is None and name is not None:
                members[key][2] = name
            continue
        members[key] = [team, rider, name]
    return list(members.values())


def _rider_lookup(ws, value_name):
    """按骑手ID建关联索引（保留首次出现值），用于补充主表列。"""
    positions = _header_positions(ws.iter_rows(), ('骑手ID', value_name))
    rider_col, value_col = positions['骑手ID'], positions[value_name]
    lookup = {}
    for row in ws.iter_rows(min_row=2):
        values = [cell.value for cell in row]
        if not any(value is not None for value in values):
            continue
        rider = _rider_key(values[rider_col] if rider_col < len(values) else None)
        if rider and rider not in lookup:
            lookup[rider] = values[value_col] if value_col < len(values) else None
    return lookup


def _binding_statuses(sheet):
    """身份证 → 绑定情况（保留首条匹配，对应 XLOOKUP 默认行为）。"""
    rows = sheet.iter_rows()
    positions = _header_positions(rows, ('骑手身份证', '绑定情况'))
    card_col, status_col = positions['骑手身份证'], positions['绑定情况']
    statuses = {}
    for row in rows:
        values = [cell.value for cell in row]
        card = values[card_col] if card_col < len(values) else None
        if card is None:
            continue
        # 不做 trim/大写：与 XLOOKUP 精确匹配保持同一口径
        card = str(card)
        if card in statuses:
            continue
        status = values[status_col] if status_col < len(values) else None
        statuses[card] = '' if status is None else str(status)
    return statuses


def _pay_binding_value(statuses, card):
    """等价于 =IF(ISERR(SEARCH("未绑定",XLOOKUP(...))),"已绑定","未绑定")。

    绑定表查无该身份证时按业务约定记未绑定（公式会返回 #N/A，业务上不接受）。
    """
    if card is None or str(card).strip() == '':
        return '未绑定'
    status = statuses.get(str(card))
    if status is None:
        return '未绑定'
    return '未绑定' if '未绑定' in status else '已绑定'


@measured('fill_main')
def _fill_main(main_ws, binding_book, month, city):
    """主表：替换月份、清空样例数据，行按骑手详情表生成并关联信息/绑定表补列。"""
    m = str(int(month[5:7]))
    month_label = f'{m}月'
    # 1) 替换标题与表头中的月份
    for row in range(1, 4):
        for col in range(1, main_ws.max_column + 1):
            cell = main_ws.cell(row=row, column=col)
            if isinstance(cell.value, str) and _TEMPLATE_MONTH in cell.value:
                cell.value = cell.value.replace(_TEMPLATE_MONTH, month_label)
    # 2) 清空样例数据行（保留前 3 行表头）
    if main_ws.max_row > 3:
        main_ws.delete_rows(4, main_ws.max_row - 3)
    # 3) 定位主表目标列（第 3 行表头）
    main_header = {}
    for col in range(1, main_ws.max_column + 1):
        value = main_ws.cell(row=3, column=col).value
        if value is not None:
            main_header[str(value).strip()] = col
    missing = [field for field in MAIN_FIELDS if field not in main_header]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    # 4) 行源与关联：详情表取团队/ID/姓名，信息表补身份证，绑定表按身份证补发薪绑定
    members = _detail_members(_source_sheet(binding_book, '骑手详情表'))
    identity = _rider_lookup(_source_sheet(binding_book, '骑手信息表'), '身份证')
    bindings = _binding_statuses(_source_sheet(binding_book, month_label + '骑手绑定情况'))
    # 5) 逐行写主表
    row_idx = 4
    for team, rider, name in members:
        card = identity.get(rider)
        for field, value in (('城市', city), ('团队名称', team), ('骑手ID', _numeric_rider_id(rider)),
                             ('骑手姓名', name), ('骑手身份证', card),
                             ('发薪工具是否绑定', _pay_binding_value(bindings, card))):
            if value is None:
                continue
            cell = main_ws.cell(row=row_idx, column=main_header[field], value=value)
            if field == '骑手ID' and type(value) is int:
                cell.number_format = '0'
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
        row_idx += 1
    _center_header_rows(main_ws, 3)
    _center_columns(main_ws)
    main_ws.freeze_panes = 'A4'
    return len(members)


@measured('style_main')
def _border_main(main_ws):
    """数据行统一细实线边框（空单元格也加框）；表头仅补非空单元格，避免合并标题内部出现线条。"""
    apply_border = style_applier(main_ws, border=_THIN_BORDER)
    for row in main_ws.iter_rows(min_row=4):
        for cell in row:
            apply_border(cell)
    for row in main_ws.iter_rows(min_row=1, max_row=3):
        for cell in row:
            if cell.value not in (None, ''):
                apply_border(cell)


def _copy_sub_sheet(book, dst_suffix, src_path, src_suffix, header_rows, log=None):
    """加载单个来源成品并把指定 sheet 复制进模板子表，用完即关闭来源。"""
    if log is not None:
        log(f'[异常骑手跟进] 复制子表「{dst_suffix}」…')
    dst_ws = _find_sheet(book, dst_suffix)
    if dst_ws is None:
        raise BillCollectionError(f'生成结构缺少子表：{dst_suffix}')
    src_book = load_workbook(src_path, data_only=False)
    try:
        src_ws = _source_sheet(src_book, src_suffix)
        _copy_sheet(src_ws, dst_ws, header_rows)
        if log is not None:
            log(f'[异常骑手跟进] 子表「{dst_suffix}」已复制（{src_ws.max_row} 行）')
    finally:
        src_book.close()


def _drop_ub_preamble(book, rows=UB_PREAMBLE_ROWS):
    """删除风神子表前置说明行，表头（账单ID…）落到第 1 行。"""
    dst_ws = _find_sheet(book, '风神薪资方案绑定')
    if dst_ws is None:
        raise BillCollectionError('生成结构缺少子表：风神薪资方案绑定')
    dst_ws.delete_rows(1, rows)
    dst_ws.freeze_panes = f'A{UB_HEADER_ROWS + 1}'


def _header_key(value):
    """表头匹配键：忽略空白/换行以及全角、半角括号差异。"""
    text = _TEAM_SPACE.sub('', '' if value is None else str(value))
    return text.replace('(', '（').replace(')', '）')


def _ub_cell_width(value):
    """多行表头按最长一行计宽，避免换行符把列撑得过宽。"""
    return max(display_width(line) for line in (str(value).splitlines() or ['']))


def _prune_ub_sheet(book):
    """风神子表按业务清单重建为 18 列，保留值、类型与数字格式。"""
    ws = _find_sheet(book, '风神薪资方案绑定')
    if ws is None:
        raise BillCollectionError('生成结构缺少子表：风神薪资方案绑定')
    header = {}
    for column, cell in enumerate(ws[UB_HEADER_ROWS], 1):
        key = _header_key(cell.value)
        if key and key not in header:
            header[key] = column
    missing = [name for name in UB_KEEP_HEADERS if _header_key(name) not in header]
    if missing:
        raise BillCollectionError('风神薪资方案绑定缺少字段：' + '、'.join(missing))
    source_columns = [header[_header_key(name)] for name in UB_KEEP_HEADERS]
    titles = [ws.cell(row=UB_HEADER_ROWS, column=column).value for column in source_columns]
    rows = []
    for row_index in range(UB_HEADER_ROWS + 1, ws.max_row + 1):
        cells = [ws.cell(row=row_index, column=column) for column in source_columns]
        if all(cell.value is None for cell in cells):
            continue
        rows.append([(cell.value, cell.data_type, cell.number_format) for cell in cells])
    index = book.worksheets.index(ws)
    title = ws.title
    book.remove(ws)
    dst_ws = book.create_sheet(title, index)
    for column, value in enumerate(titles, 1):
        cell = dst_ws.cell(row=1, column=column, value=value)
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.fill = _HEADER_FILL
    for row_index, values in enumerate(rows, 2):
        for column, (value, data_type, number_format) in enumerate(values, 1):
            cell = dst_ws.cell(row=row_index, column=column)
            if value is not None:
                cell.value = value
                cell.data_type = data_type
                if number_format:
                    cell.number_format = number_format
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    for column, value in enumerate(titles, 1):
        longest = _ub_cell_width(value)
        for values in rows:
            text = values[column - 1][0]
            if text is not None:
                longest = max(longest, _ub_cell_width(text))
        dst_ws.column_dimensions[get_column_letter(column)].width = min(
            max(longest + 2, 10), 60)
    dst_ws.row_dimensions[1].height = 30
    dst_ws.freeze_panes = f'A{UB_HEADER_ROWS + 1}'
    _center_columns(dst_ws, len(UB_KEEP_HEADERS))


def _archive_lookup(rows):
    """按身份证号原值建立主表补充字段索引；重复时保留排序后的第一条。"""
    positions = {name: rider_archive.COLUMNS.index(name) for name in
                 ('身份证号',) + ARCHIVE_FIELDS}
    lookup = {}
    for row in rows:
        identity = row[positions['身份证号']]
        identity = identity.value if identity is not None else None
        if identity is None:
            continue
        try:
            hash(identity)
        except TypeError:
            continue
        values = tuple(row[positions[name]].value if row[positions[name]] is not None else None
                       for name in ARCHIVE_FIELDS)
        lookup.setdefault(identity, values)
    return lookup


@measured('fill_archive')
def _fill_archive_fields(main_ws, lookup):
    """主表按「骑手身份证」原值匹配蓝橙员工档案，未匹配统一标注“蓝橙未入职”。"""
    header = {}
    for column in range(1, main_ws.max_column + 1):
        value = main_ws.cell(row=3, column=column).value
        if value is not None and str(value).strip() not in header:
            header[str(value).strip()] = column
    missing = [name for name in ('骑手身份证',) + ARCHIVE_FIELDS if name not in header]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    identity_column = header['骑手身份证']
    matched = unmatched = 0
    for row_index in range(4, main_ws.max_row + 1):
        identity = main_ws.cell(row=row_index, column=identity_column).value
        values = lookup.get(identity)
        if values is None:
            unmatched += 1
            values = (ARCHIVE_UNJOINED,) * len(ARCHIVE_FIELDS)
        else:
            matched += 1
        for name, value in zip(ARCHIVE_FIELDS, values):
            cell = main_ws.cell(row=row_index, column=header[name], value=value)
            if name == ARCHIVE_DATE_FIELD:
                day = _detail_day(value)
                if day is not None:
                    cell.value = datetime.combine(day, datetime.min.time())
                cell.number_format = 'yyyy-mm-dd'
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    return matched, unmatched


def _positive_price_ids(price_ws):
    """从按月/城市筛选后的价格档案中找出存在价格>0的身份证号（原值严格匹配）。"""
    rows = price_ws.iter_rows()
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('蓝橙价格档案缺少表头')
    positions = {}
    for index, cell in enumerate(header):
        text = str(cell.value).strip() if cell is not None and cell.value is not None else ''
        if text and text not in positions:
            positions[text] = index
    missing = [name for name in ('身份证号', '价格') if name not in positions]
    if missing:
        raise BillCollectionError('蓝橙价格档案缺少字段：' + '、'.join(missing))
    id_col, price_col = positions['身份证号'], positions['价格']
    result = set()
    for row in rows:
        values = [cell.value for cell in row]
        price = _order_value(values[price_col] if price_col < len(values) else None)
        if price is None or price <= 0:
            continue
        identity = values[id_col] if id_col < len(values) else None
        if identity is None:
            continue
        try:
            result.add(identity)
        except TypeError:
            continue
    return result


@measured('fill_price')
def _fill_price_flag(main_ws, price_ws):
    """兼职骑手按身份证号匹配价格档案：全部为0或无记录标“是”，存在正价标“否”。"""
    positive = _positive_price_ids(price_ws)
    header = {}
    for column in range(1, main_ws.max_column + 1):
        value = main_ws.cell(row=3, column=column).value
        if value is not None and str(value).strip() not in header:
            header[str(value).strip()] = column
    missing = [name for name in ('骑手身份证', '合作类型', PRICE_FLAG_FIELD)
               if name not in header]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    parttime = yes_count = 0
    for row_index in range(4, main_ws.max_row + 1):
        identity = main_ws.cell(row=row_index, column=header['骑手身份证']).value
        cooperation = main_ws.cell(row=row_index, column=header['合作类型']).value
        if str(cooperation).strip() == PARTTIME:
            parttime += 1
            try:
                value = '否' if identity in positive else '是'
            except TypeError:
                value = '是'
            if value == '是':
                yes_count += 1
        else:
            value = '否'
        cell = main_ws.cell(row=row_index, column=header[PRICE_FLAG_FIELD], value=value)
        cell.font = _DATA_FONT
        cell.alignment = _CENTER
    return parttime, yes_count


def _main_header(main_ws):
    """主表第 3 行表头名 → 列号（重名列保留首次出现的列）。"""
    header = {}
    for column in range(1, main_ws.max_column + 1):
        value = main_ws.cell(row=3, column=column).value
        if value is not None and str(value).strip() not in header:
            header[str(value).strip()] = column
    return header


def _detail_max_day(detail_ws):
    """骑手详情表日期列的最大日期（文本或真实日期均可识别）。"""
    rows = detail_ws.iter_rows()
    header = next(rows, None)
    if header is None:
        raise BillCollectionError('骑手详情表缺少表头')
    index = None
    for position, cell in enumerate(header):
        text = str(cell.value).strip() if cell is not None and cell.value is not None else ''
        if text == '日期':
            index = position
            break
    if index is None:
        raise BillCollectionError('骑手详情表缺少字段：日期')
    latest = None
    for row in rows:
        day = _detail_day(row[index].value if index < len(row) else None)
        if day is not None and (latest is None or day > latest):
            latest = day
    return latest


def _fengshen_bindings(ub_ws):
    """风神薪资方案绑定子表（第 1 行表头）：按站点名称+骑手ID 汇总薪资/扣款方案是否维护。

    同一站点+骑手出现多份账单时按「任一缺方案即未维护」合并。
    """
    header = {}
    for column, cell in enumerate(ub_ws[UB_HEADER_ROWS], 1):
        text = str(cell.value).strip() if cell.value is not None else ''
        if text and text not in header:
            header[text] = column
    rider_column = header.get('骑手ID')
    team_column = header.get('骑手所属站点名称')
    plans = {}
    for kind, prefix in UB_PLAN_PREFIXES:
        plans[kind] = next((column for name, column in header.items()
                            if name.startswith(prefix)), None)
    missing = [kind for kind, column in plans.items() if column is None]
    if rider_column is None or team_column is None or missing:
        raise BillCollectionError('风神薪资方案绑定缺少字段：骑手ID、骑手所属站点名称/'
                                  + '、'.join(missing))
    pairs = {}
    for row in ub_ws.iter_rows(min_row=UB_HEADER_ROWS + 1, values_only=True):
        rider = _rider_key(row[rider_column - 1] if rider_column - 1 < len(row) else None)
        if not rider:
            continue
        team = _team_key(row[team_column - 1] if team_column - 1 < len(row) else None)
        flags = {}
        for kind, column in plans.items():
            value = row[column - 1] if column - 1 < len(row) else None
            flags[kind] = bool(str(value).strip()) if value is not None else False
        entry = pairs.setdefault((team, rider), dict.fromkeys(flags, True))
        for kind, bound in flags.items():
            entry[kind] = entry[kind] and bound
    return pairs


@measured('fill_abnormal')
def _fill_abnormal_flag(main_ws, detail_ws, ub_ws, *, latest_day=...):
    """主表自动判定薪资/扣款方案绑定，并按四条口径写「是否异常骑手」「异常原因」。"""
    header = _main_header(main_ws)
    last_day_column = next((column for name, column in header.items()
                            if name.endswith('最后出勤日')), None)
    columns = {'团队名称': header.get('团队名称'), '骑手ID': header.get('骑手ID'),
               '状态': header.get('状态'), '最后出勤日': last_day_column,
               SALARY_BINDING_FIELD: header.get(SALARY_BINDING_FIELD),
               DEDUCTION_BINDING_FIELD: header.get(DEDUCTION_BINDING_FIELD),
               ABNORMAL_FLAG_FIELD: header.get(ABNORMAL_FLAG_FIELD),
               ABNORMAL_REASON_FIELD: header.get(ABNORMAL_REASON_FIELD)}
    missing = [name for name, column in columns.items() if column is None]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    latest = _detail_max_day(detail_ws) if latest_day is ... else latest_day
    pairs = _fengshen_bindings(ub_ws)
    stats = {'abnormal': 0, 'status': 0, 'absentee': 0, 'salary': 0, 'deduction': 0,
             'matched': 0, 'unmatched': 0}
    for row_index in range(4, main_ws.max_row + 1):
        team = main_ws.cell(row=row_index, column=columns['团队名称']).value
        rider = _rider_key(main_ws.cell(row=row_index, column=columns['骑手ID']).value)
        flags = pairs.get((_team_key(team), rider))
        if flags is None:
            stats['unmatched'] += 1
        else:
            stats['matched'] += 1
        reasons = []
        status = str(main_ws.cell(row=row_index, column=columns['状态']).value or '').strip()
        if status in ABNORMAL_STATUSES:
            reasons.append(f'状态{status}')
            stats['status'] += 1
        day = _detail_day(main_ws.cell(row=row_index, column=columns['最后出勤日']).value)
        if day is None:
            reasons.append('当月无有效完单')
            stats['absentee'] += 1
        elif latest is not None and (latest - day).days >= ABSENTEE_DAYS:
            reasons.append(f'{ABSENTEE_DAYS}天以上未出勤')
            stats['absentee'] += 1
        for kind, name in (('薪资方案', SALARY_BINDING_FIELD), ('扣款方案', DEDUCTION_BINDING_FIELD)):
            value = '是' if flags and flags.get(kind) else '否'
            if value == '否':
                reasons.append(f'{kind}未绑定')
                stats['salary' if kind == '薪资方案' else 'deduction'] += 1
            cell = main_ws.cell(row=row_index, column=columns[name], value=value)
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
        value = '是' if reasons else '否'
        if reasons:
            stats['abnormal'] += 1
        for column, text in ((columns[ABNORMAL_FLAG_FIELD], value),
                             (columns[ABNORMAL_REASON_FIELD], '；'.join(reasons))):
            cell = main_ws.cell(row=row_index, column=column, value=text)
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    return stats


@measured('read_archive')
def _copy_archive_sheet(book, src_path, city, log=None, cancelled=None):
    """蓝橙员工档案只保留约定 14 列，按城市/项目筛选后按项目升序写入。"""
    if log is not None:
        log('[异常骑手跟进] 复制子表「蓝橙员工档案」…')
    dst_ws = _find_sheet(book, '蓝橙员工档案')
    if dst_ws is None:
        raise BillCollectionError('生成结构缺少子表：蓝橙员工档案')
    with source_sheet(src_path, '骑手档案', _source_sheet, cancelled) as src_ws:
        rows, widths = rider_archive.read_archive(
            src_ws, cancelled, city=rider_archive.normalize_city(city),
            projects=rider_archive.PROJECTS)
        rider_archive.write_sheet(dst_ws, rows, widths)
        for column in range(1, dst_ws.max_column + 1):
            dst_ws.cell(row=1, column=column).fill = _HEADER_FILL
        if log is not None:
            log(f'[异常骑手跟进] 子表「蓝橙员工档案」：{len(rows)} 行'
                f'（{city}，项目 {"、".join(rider_archive.PROJECTS)}）')
        return _archive_lookup(rows)


@measured('read_price')
def _copy_price_sheet(book, src_path, city, month, log=None, cancelled=None):
    """蓝橙价格档案按目标月份和当前城市筛选，原始平台文件保持不变。"""
    if log is not None:
        log('[异常骑手跟进] 复制子表「蓝橙价格档案」…')
    dst_ws = _find_sheet(book, '蓝橙价格档案')
    if dst_ws is None:
        raise BillCollectionError('生成结构缺少子表：蓝橙价格档案')
    with source_sheet(src_path, price_archive.SHEET_SUFFIX, _source_sheet, cancelled) as src_ws:
        stats = price_archive.write_filtered_sheet(dst_ws, src_ws, [month], city,
                                                   cancelled=cancelled)
        for column in range(1, dst_ws.max_column + 1):
            dst_ws.cell(row=1, column=column).fill = _HEADER_FILL
        if log is not None:
            detail = (f'[异常骑手跟进] 子表「蓝橙价格档案」：{stats["before"]} → '
                      f'{stats["after"]} 行（{city}，{month}；排除其他月份 {stats["month"]} 行、'
                      f'其他城市 {stats["city"]} 行')
            if stats['invalid']:
                detail += f'、无法识别日期 {stats["invalid"]} 行'
            log(detail + '）')


_PERIOD = re.compile(r'(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})')


def _period_range(value):
    """解析「YYYY-MM-DD至YYYY-MM-DD」；无法识别返回 None。"""
    if isinstance(value, datetime):
        return value.date(), value.date()
    if isinstance(value, date):
        return value, value
    matches = _PERIOD.findall(str(value or ''))
    if len(matches) < 2:
        return None
    try:
        first = date(*(int(part) for part in matches[0]))
        last = date(*(int(part) for part in matches[1]))
    except ValueError:
        return None
    return (first, last) if first <= last else (last, first)


@measured('read_rental')
def _copy_rental_sheet(book, src_path, month, log=None):
    """电动车住宿租用：保留租用周期与目标月有交集的数据，排除撤销记录；
    在租用时间后新增租用天数（两端按目标月收敛，含首尾），并按站点+骑手ID汇总天数。"""
    if log is not None:
        log('[异常骑手跟进] 复制子表「电动车住宿租用」…')
    dst_ws = _find_sheet(book, '电动车住宿租用')
    if dst_ws is None:
        raise BillCollectionError('生成结构缺少子表：电动车住宿租用')
    with source_sheet(src_path, None, _source_sheet, None) as src_ws:
        rows = src_ws.iter_rows()
        header_cells = next(rows, None)
        if header_cells is None:
            raise BillCollectionError('电动车住宿租用缺少表头')
        header = [cell.value for cell in header_cells]
        columns = {}
        for index, value in enumerate(header):
            text = str(value).strip() if value is not None else ''
            if text and text not in columns:
                columns[text] = index
        lower = {text.lower(): index for text, index in columns.items()}
        missing = [name for name in ('租用时间', '状态') if name not in columns]
        if missing:
            raise BillCollectionError('电动车住宿租用缺少字段：' + '、'.join(missing))
        period_col, status_col = columns['租用时间'], columns['状态']
        team_col = lower.get('站点名称')
        rider_col = lower.get('骑手id')
        type_col = lower.get('物资类型')
        missing = [name for name, index in (('站点名称', team_col), ('骑手id', rider_col),
                                           ('物资类型', type_col)) if index is None]
        if missing:
            raise BillCollectionError('电动车住宿租用缺少字段：' + '、'.join(missing)
                                      + '（主表租车/住宿天数需要按站点+骑手ID配对）')
        year, mon = (int(part) for part in str(month).split('-'))
        first = date(year, mon, 1)
        last = date(year, mon, monthrange(year, mon)[1])
        kept, before, invalid, revoked = [], 0, 0, 0
        for row in rows:
            values = [cell.value for cell in row]
            if not any(value is not None for value in values):
                continue
            before += 1
            status = values[status_col] if status_col < len(values) else None
            if str(status).strip() == '撤销':
                revoked += 1
                continue
            value = values[period_col] if period_col < len(values) else None
            period = _period_range(value)
            if period is None:
                invalid += 1
                continue
            if period[0] > last or period[1] < first:
                continue
            kept.append(row)
        if dst_ws.max_row > 0:
            dst_ws.delete_rows(1, dst_ws.max_row)
        totals = {}
        # 租用天数插在租用时间之后：两端超出目标月的部分按月初/月末收敛，含首尾
        day_index = period_col + 1
        days_column = day_index + 1
        new_header = header[:period_col + 1] + ['租用天数'] + header[period_col + 1:]
        widths = [display_width(value) for value in new_header]
        for column, value in enumerate(new_header, 1):
            cell = dst_ws.cell(row=1, column=column, value=value)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _CENTER
        for row_index, row in enumerate(kept, 2):
            originals = list(row)[:len(header)]
            values = [cell.value for cell in originals]
            if len(values) < len(header):
                values += [None] * (len(header) - len(values))
            period = _period_range(values[period_col])
            days = (min(period[1], last) - max(period[0], first)).days + 1
            kind = str(values[type_col]).strip() if values[type_col] is not None else ''
            rider = _rider_key(values[rider_col])
            if kind and rider:
                entry = totals.setdefault((_team_key(values[team_col]), rider), {})
                entry[kind] = entry.get(kind, 0) + days
            values.insert(day_index, days)
            for column, value in enumerate(values, 1):
                cell = dst_ws.cell(row=row_index, column=column, value=value)
                if value is not None:
                    if column != days_column:
                        source_index = column - 1 - (1 if column > days_column else 0)
                        if source_index < len(originals):
                            source = originals[source_index]
                            cell.data_type = source.data_type
                            if source.number_format is not None:
                                cell.number_format = source.number_format
                cell.font = _DATA_FONT
                cell.alignment = _CENTER
                width = display_width(value)
                if width > widths[column - 1]:
                    widths[column - 1] = width
        for column, width in enumerate(widths, 1):
            dimension = dst_ws.column_dimensions[get_column_letter(column)]
            dimension.width = column_width(width)
            dimension.alignment = _CENTER
        dst_ws.freeze_panes = 'A2'
        if log is not None:
            log(f'[异常骑手跟进] 子表「电动车住宿租用」：{before} → {len(kept)} 行'
                f'（{month} 月内生效，排除撤销 {revoked} 行）')
            if invalid:
                log(f'[异常骑手跟进] 电动车住宿租用：{invalid} 行租用时间无法识别，已跳过')
        return totals


def _fill_rental_days(main_ws, totals):
    """主表租车天数/住宿天数：按团队名称+骑手ID 严格配对累加租用天数，无记录写 0。"""
    header = _main_header(main_ws)
    required = {'团队名称': header.get('团队名称'), '骑手ID': header.get('骑手ID')}
    required.update({name: header.get(name) for name, _ in RENTAL_DAY_FIELDS})
    missing = [name for name, column in required.items() if column is None]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    riders_with_days = 0
    for row_index in range(4, main_ws.max_row + 1):
        team = main_ws.cell(row=row_index, column=required['团队名称']).value
        rider = _rider_key(main_ws.cell(row=row_index, column=required['骑手ID']).value)
        entry = totals.get((_team_key(team), rider)) if rider else None
        if entry:
            riders_with_days += 1
        for name, kind in RENTAL_DAY_FIELDS:
            cell = main_ws.cell(row=row_index, column=required[name],
                                value=(entry or {}).get(kind, 0))
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    return riders_with_days


@measured('fill_maintenance')
def _fill_maintenance_notes(main_ws):
    """主表 W 备注：活跃天大于租车/住宿天数时标注缺口；Z 列按备注是否有内容判定。"""
    header = _main_header(main_ws)
    active_column = next((column for name, column in header.items()
                          if name.endswith(ACTIVE_DAYS_FIELD)), None)
    columns = {name: header.get(name) for name in
               ('租车天数', '住宿天数', NOTE_FIELD, MAINTENANCE_FOLLOWUP_FIELD)}
    columns[ACTIVE_DAYS_FIELD] = active_column
    missing = [name for name, column in columns.items() if column is None]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    noted = 0
    for row_index in range(4, main_ws.max_row + 1):
        active = _order_value(main_ws.cell(row=row_index, column=active_column).value) or 0
        reasons = []
        for name, text in RENTAL_SHORTAGES:
            days = _order_value(main_ws.cell(row=row_index, column=columns[name]).value) or 0
            if active > days:
                reasons.append(text)
        note = '；'.join(reasons)
        if note:
            noted += 1
        for field, value in ((NOTE_FIELD, note or None),
                             (MAINTENANCE_FOLLOWUP_FIELD, '是' if note else '否')):
            cell = main_ws.cell(row=row_index, column=columns[field], value=value)
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    return noted


def _autofit_columns(ws, names, minimum=10, cap=60):
    """全部数据写入后按内容自适应列宽（CJK 计 2），长文本开启换行。"""
    header = _main_header(ws)
    for name in names:
        column = header.get(name)
        if column is None:
            continue
        longest = display_width(ws.cell(3, column).value)
        for row_index in range(4, ws.max_row + 1):
            cell = ws.cell(row=row_index, column=column)
            if cell.value is None:
                continue
            longest = max(longest, display_width(cell.value))
            cell.alignment = Alignment(horizontal='center', vertical='center',
                                       wrap_text=True)
        ws.column_dimensions[get_column_letter(column)].width = min(
            max(longest + 2, minimum), cap)


def _analysis_entries(main_ws, month):
    """主表逐行提取分析表口径；H/I/J按在跑单骑手统计，与是否异常骑手独立。"""
    header = _main_header(main_ws)
    active_column = next((column for name, column in header.items()
                          if name.endswith(ACTIVE_DAYS_FIELD)), None)
    required = (ANALYSIS_CITY_FIELD, ANALYSIS_TEAM_FIELD, '骑手ID', '合作类型', '状态',
                '是否寒暑假工', NOTE_FIELD, SALARY_BINDING_FIELD, DEDUCTION_BINDING_FIELD,
                PRICE_FLAG_FIELD, '发薪工具是否绑定', ABNORMAL_FLAG_FIELD, '合作日期')
    columns = {name: header.get(name) for name in required}
    columns[ACTIVE_DAYS_FIELD] = active_column
    missing = [name for name, column in columns.items() if column is None]
    if missing:
        raise BillCollectionError('主表缺少字段：' + '、'.join(missing))
    first_day = date(int(str(month)[:4]), int(str(month)[5:7]), 1)
    entries = []
    for row_index in range(4, main_ws.max_row + 1):
        raw = {name: main_ws.cell(row=row_index, column=column).value
               for name, column in columns.items()}
        rider = _rider_key(raw['骑手ID'])
        if not rider:
            continue
        text = {name: str(value or '').strip() for name, value in raw.items()}
        running = (_order_value(raw[ACTIVE_DAYS_FIELD]) or 0) > 0
        flagged = text[ABNORMAL_FLAG_FIELD] == '是'
        abnormal = running and flagged
        noted = running and bool(text[NOTE_FIELD])
        joined = _detail_day(raw['合作日期'])
        entries.append({
            'city': text[ANALYSIS_CITY_FIELD],
            'team': text[ANALYSIS_TEAM_FIELD],
            'rider': rider,
            'running': running,
            'flagged': flagged,
            'abnormal': abnormal,
            'parttime': running and text['合作类型'] == PARTTIME,
            'fulltime': running and text['合作类型'] == '全职',
            'unjoined': running and text['状态'] == ARCHIVE_UNJOINED,
            'noted': noted,
            'maintained': running and not noted,
            'plans': running and '否' in (text[SALARY_BINDING_FIELD],
                                           text[DEDUCTION_BINDING_FIELD]),
            'price_yes': running and text[PRICE_FLAG_FIELD] == '是',
            'left_running': running and text['状态'] == '解除合作',
            'pay_unbound': running and '未绑' in text['发薪工具是否绑定'],
            'first_run': joined is not None and joined >= first_day,
        })
    return entries


_ANALYSIS_KEYS = ('running', 'parttime', 'fulltime', 'unjoined', 'noted',
                  'maintained', 'plans', 'price_yes', 'left_running', 'pay_unbound',
                  'first_run')


def _analysis_groups(entries, group_by_city):
    """按站点（城市表）或城市（汇总表）聚合，按「站点+骑手ID」分行计数，跨站不合并。"""
    groups = {}
    for entry in entries:
        key = (entry['city'],) if group_by_city else (entry['city'], entry['team'])
        bucket = groups.setdefault(key, {name: set() for name in _ANALYSIS_KEYS})
        for name in _ANALYSIS_KEYS:
            if entry[name]:
                bucket[name].add((entry['city'], entry['team'], entry['rider']))
    rows = []
    for key, bucket in groups.items():
        running = len(bucket['running'])
        rows.append({
            'city': key[0],
            'team': '' if group_by_city else key[1],
            # 涉及活动金额暂不填，保持空列；兼职占比由写入方按 G 列格式输出
            'counts': [running, len(bucket['parttime']),
                       len(bucket['fulltime']), len(bucket['unjoined']), None,
                       len(bucket['noted']), len(bucket['maintained']), len(bucket['plans']), None,
                       len(bucket['price_yes']), len(bucket['left_running']),
                       len(bucket['pay_unbound']), len(bucket['first_run'])],
            'ratio': len(bucket['parttime']) / running if running else None,
        })
    return rows


def _write_analysis_sheet(ws, main_ws, month, summary=False):
    """按截图口径重写分析表：两行表头 + 分组合并。

    summary=False（单城市）：站点明细 + 末尾合计行；
    summary=True（多城市汇总）：拼音升序的城市块 + 蓝色「汇总」行 + 站点明细（无合计）。
    """
    month = str(month)
    month_label = f'{int(month[5:7])}月'
    entries = _analysis_entries(main_ws, month)
    city_rows = sorted(_analysis_groups(entries, True), key=lambda row: _zh_sort_key(row['city']))
    station_rows = sorted(_analysis_groups(entries, False),
                          key=lambda row: (_zh_sort_key(row['city']), _zh_sort_key(row['team'] or '')))
    totals = [0] * (ANALYSIS_DATA_COLUMNS - 2)
    for row in station_rows:
        for offset, value in enumerate(row['counts']):
            if value is not None and offset != ANALYSIS_RATIO_COLUMN - 3:
                totals[offset] += value
    total_counts = list(totals)
    total_counts[ANALYSIS_RATIO_COLUMN - 3] = None
    total_counts[8] = None  # 涉及活动金额暂不填，合计行同样留空
    total_ratio = totals[1] / totals[0] if totals[0] else None
    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))
    if ws.max_row > 0:
        ws.delete_rows(1, ws.max_row)
    header_font = Font(name='微软雅黑', size=10, bold=True)
    data_font = Font(name='微软雅黑', size=10)
    header_fills = {}
    for (first, last), color in ANALYSIS_HEADER_FILLS:
        for column in range(first, last + 1):
            header_fills[column] = PatternFill(fill_type='solid', fgColor=color)
    total_fill = PatternFill(fill_type='solid', fgColor=ANALYSIS_TOTAL_FILL)
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    data_align = Alignment(horizontal='center', vertical='center')
    ws.cell(1, 1, ANALYSIS_CITY_FIELD)
    ws.cell(1, 2, '站点')
    for column, text in ANALYSIS_GROUP_TITLES:
        ws.cell(1, column, text.replace('{month}', month_label))
    for offset, text in enumerate(ANALYSIS_SUB_HEADERS):
        ws.cell(2, 3 + offset, text)
    for rng in ANALYSIS_MERGES:
        ws.merge_cells(rng)

    def write_data(row_index, row, team):
        ws.cell(row_index, 1, row['city'])
        # 城市块 B 列按截图重复填城市名；站点明细填站点
        if team:
            ws.cell(row_index, 2, team)
        for offset, value in enumerate(row['counts']):
            if value is not None:
                ws.cell(row_index, 3 + offset, value)
        if row['ratio'] is not None:
            cell = ws.cell(row_index, ANALYSIS_RATIO_COLUMN, row['ratio'])
            cell.number_format = ANALYSIS_RATIO_FORMAT

    def write_total(row_index, label, label_column):
        ws.cell(row_index, label_column, label)
        for offset, value in enumerate(total_counts):
            if value is not None:
                ws.cell(row_index, 3 + offset, value)
        if total_ratio is not None:
            cell = ws.cell(row_index, ANALYSIS_RATIO_COLUMN, total_ratio)
            cell.number_format = ANALYSIS_RATIO_FORMAT

    row_index = 3
    total_index = None
    if summary:
        for row in city_rows:
            write_data(row_index, row, row['city'])
            row_index += 1
        total_index = row_index
        write_total(total_index, '汇总', 1)
        row_index += 1
        for row in station_rows:
            write_data(row_index, row, row['team'])
            row_index += 1
    else:
        for row in station_rows:
            write_data(row_index, row, row['team'])
            row_index += 1
        total_index = row_index
        write_total(total_index, ANALYSIS_TOTAL, 2)
        row_index += 1
    last_row = row_index - 1
    for row_index in range(1, last_row + 1):
        is_header = row_index <= 2
        is_total = row_index == total_index
        for column in range(1, ANALYSIS_DATA_COLUMNS + 1):
            cell = ws.cell(row_index, column)
            cell.border = _THIN_BORDER
            cell.font = header_font if is_header or is_total else data_font
            cell.alignment = header_align if is_header else data_align
            if is_header:
                cell.fill = header_fills[column]
            elif is_total:
                cell.fill = total_fill
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 32
    for column in range(1, ANALYSIS_DATA_COLUMNS + 1):
        letter = get_column_letter(column)
        dimension = ws.column_dimensions[letter]
        dimension.width = ANALYSIS_WIDTHS.get(letter, ANALYSIS_DEFAULT_WIDTH)
        dimension.alignment = data_align
    if last_row >= 3:
        ws.conditional_formatting.add(
            f'G3:G{last_row}',
            DataBarRule(start_type='num', start_value=0, end_type='num', end_value=1,
                        color='FFFF7C80', showValue=True))
    ws.freeze_panes = 'A3'
    return len(city_rows) + len(station_rows) if summary else len(station_rows)


def _write_guide_sheet(ws, main_ws, city, month):
    """生成说明子表：本期概览、异常规则与责任方、字段口径、常见 QA。"""
    month = str(month)
    year, mon = int(month[:4]), int(month[5:7])
    month_label = f'{mon}月'
    entries = _analysis_entries(main_ws, month)

    def riders_of(key):
        return {(entry['city'], entry['team'], entry['rider'])
                for entry in entries if entry[key]}

    all_riders = {(entry['city'], entry['team'], entry['rider']) for entry in entries}
    running = riders_of('running')
    flagged = riders_of('flagged')
    abnormal = riders_of('abnormal')
    unmaintained = riders_of('noted')
    maintained = riders_of('maintained')
    first_run = riders_of('first_run')
    stats = (
        ('城市', city),
        ('数据周期', f'{month}-01 至 {month}-{monthrange(year, mon)[1]:02d}'),
        ('骑手人数（按站点分行）', f'{len(all_riders)}'),
        ('明细行数', f'{len(entries)}'),
        ('跑单骑手', f'{len(running)}'),
        ('异常骑手', f'{len(flagged)}（在跑单 {len(abnormal)}）'),
        ('未维护 / 已维护', f'{len(unmaintained)} / {len(maintained)}'),
        ('首跑（含兼职转全职）', f'{len(first_run)}'),
    )

    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))
    if ws.max_row > 0:
        ws.delete_rows(1, ws.max_row)

    base_font = Font(name='微软雅黑', size=10)
    bold_font = Font(name='微软雅黑', size=10, bold=True)
    section_font = Font(name='微软雅黑', size=11, bold=True)
    title_font = Font(name='微软雅黑', size=15, bold=True, color='FFFFFFFF')
    left = Alignment(horizontal='left', vertical='center', wrap_text=True)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    label_fill = PatternFill(fill_type='solid', fgColor='FFF2F2F2')

    def paint(row, columns, fill=None, border=True):
        for column in columns:
            cell = ws.cell(row, column)
            if fill is not None:
                cell.fill = fill
            if border:
                cell.border = _THIN_BORDER

    def section(row, text):
        paint(row, range(1, 6), _HEADER_FILL)
        cell = ws.cell(row, 1, text)
        cell.font = section_font
        cell.alignment = left
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 24

    def table_header(row, values, merges=()):
        for column, text in enumerate(values, 1):
            cell = ws.cell(row, column, text)
            cell.font = bold_font
            cell.alignment = center
        paint(row, range(1, 6), label_fill)
        for first, last in merges:
            ws.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
        ws.row_dimensions[row].height = 24

    def data_row(row, values, merges=(), height=30):
        for column, text in enumerate(values, 1):
            cell = ws.cell(row, column, text)
            cell.font = base_font
            cell.alignment = left
        paint(row, range(1, 6))
        for first, last in merges:
            ws.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
        ws.row_dimensions[row].height = height

    paint(1, range(1, 6), PatternFill(fill_type='solid', fgColor='FF00B0F0'))
    title = ws.cell(1, 1, f'{city} · {month_label}异常骑手跟进说明')
    title.font = title_font
    title.alignment = center
    ws.merge_cells('A1:E1')
    ws.row_dimensions[1].height = 30

    row = 3
    section(row, '一、本期数据概览')
    row += 1
    for label, value in stats:
        label_cell = ws.cell(row, 1, label)
        label_cell.font = bold_font
        label_cell.alignment = left
        value_cell = ws.cell(row, 2, value)
        value_cell.font = base_font
        value_cell.alignment = left
        paint(row, range(1, 6))
        ws.cell(row, 1).fill = label_fill
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
        ws.row_dimensions[row].height = 20
        row += 1

    row += 1
    section(row, '二、异常判定规则（命中任一即为异常；异常原因按下列顺序用「；」拼接）')
    row += 1
    table_header(row, ('异常原因', '判定逻辑', '数据来源', '建议跟进动作', '责任方'))
    row += 1
    for rule in GUIDE_RULES:
        data_row(row, rule, height=46)
        row += 1

    row += 1
    section(row, '三、关键字段口径')
    row += 1
    table_header(row, ('字段 / 位置', '口径说明'), merges=((2, 5),))
    row += 1
    for name, position, description in GUIDE_FIELDS:
        data_row(row, (f'{name}（{position}）', description), merges=((2, 5),), height=28)
        row += 1

    row += 1
    section(row, '四、常见口径 QA')
    row += 1
    table_header(row, ('问题', '说明'), merges=((2, 5),))
    row += 1
    for question, answer in GUIDE_QA:
        data_row(row, (question, answer), merges=((2, 5),), height=30)
        row += 1

    for letter, width in (('A', 26.0), ('B', 46.0), ('C', 26.0), ('D', 46.0), ('E', 15.0)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = 'A2'
    ws.page_setup.orientation = 'landscape'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    return stats


@profiled('abnormal_followup', 7, 'output_dir')
def generate_abnormal_followup(binding_file, ub_file, price_file, archive_file, goods_file,
                               city, month, output_dir, log=None, cancelled=None, stamp=None):
    """组装异常骑手跟进工作簿，返回成品文件 Path。

    参数：
        binding_file: 骑手支付绑定（生成表）成品 xlsx
        ub_file: 风神骑手月度 UB 账单成品 xlsx
        price_file: 价格档案成品 xlsx
        archive_file: 骑手档案成品 xlsx
        goods_file: 物资租用登记成品 xlsx
        city: 城市名
        month: 'YYYY-MM'
        output_dir: 成品输出目录
    """
    month = str(month)
    m = str(int(month[5:7]))
    month_label = f'{m}月'
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(message):
        if log is not None:
            log(message)

    book = None
    target = None
    try:
        _checkpoint(cancelled)
        book = create_followup_workbook(month)
        # 1) 月份替换：所有 sheet 名
        for ws in book.worksheets:
            if _TEMPLATE_MONTH in ws.title:
                ws.title = ws.title.replace(_TEMPLATE_MONTH, month_label)
        # 2) 主表填充 + 支付绑定 3 个子表（加载 binding 一次）
        progress(f'[异常骑手跟进] 城市 {city} · {month}：加载支付绑定成品')
        main_ws = _find_sheet(book, '异常骑手跟进表')
        if main_ws is None:
            raise BillCollectionError('生成结构缺少主表「X月异常骑手跟进表」')
        from binding_tables import verified_book
        with stage('read_binding'):
            binding_book = verified_book(capture_tables(), binding_file)
            if binding_book is None:
                binding_book = load_workbook(binding_file, data_only=False)
        detail_analysis = _prepare_detail_analysis(_source_sheet(binding_book, '骑手详情表'))
        try:
            _checkpoint(cancelled)
            main_rows = _fill_main(main_ws, binding_book, month, city)
            progress(f'[异常骑手跟进] 主表已生成 {main_rows} 行'
                     f'（团队名称/骑手ID/骑手姓名来自骑手详情表，跨站分行）')
            matched_activity, detail_keys, invalid_dates = _fill_activity(main_ws, binding_book)
            detail = (f'[异常骑手跟进] 主表活跃天/完单量/最后出勤日：匹配 {matched_activity} 行'
                      f'（详情有效骑手 {detail_keys} 人')
            if invalid_dates:
                detail += f'，{invalid_dates} 行日期无法识别'
            progress(detail + '）')
            for suffix, src_suffix, header_rows in (
                    ('骑手绑定情况', month_label + '骑手绑定情况', 1),
                    ('骑手详情表', '骑手详情表', 1),
                    ('骑手信息表', '骑手信息表', 1)):
                _checkpoint(cancelled)
                dst_ws = _find_sheet(book, suffix)
                if dst_ws is None:
                    raise BillCollectionError(f'生成结构缺少子表：{suffix}')
                _copy_sheet(_source_sheet(binding_book, src_suffix), dst_ws, header_rows)
                progress(f'[异常骑手跟进] 子表「{suffix}」已复制')
        finally:
            binding_book.close()
        # 3) 其余子表逐个加载来源、用完即释放
        # 平台原始导出表头在第 4 行（前置 3 行说明）；重排成品表头已在第 1 行。
        preamble = rider_bill_header_row(ub_file) - 1
        _copy_sub_sheet(book, '风神薪资方案绑定', ub_file, None, preamble + 1, log=progress)
        if preamble:
            _drop_ub_preamble(book, preamble)
        _prune_ub_sheet(book)
        progress('[异常骑手跟进] 子表「风神薪资方案绑定」'
                 + (f'已删除前 {preamble} 行说明，' if preamble else '按重排成品直接复制，')
                 + f'并精简为 {len(UB_KEEP_HEADERS)} 列')
        _checkpoint(cancelled)
        _copy_price_sheet(book, price_file, city, month, log=progress, cancelled=cancelled)
        _checkpoint(cancelled)
        archive_lookup = _copy_archive_sheet(book, archive_file, city, log=progress,
                                             cancelled=cancelled)
        matched, unmatched = _fill_archive_fields(main_ws, archive_lookup)
        progress(f'[异常骑手跟进] 主表蓝橙字段：匹配 {matched} 行，'
                 f'未匹配 {unmatched} 行（显示蓝橙未入职）')
        price_ws = _find_sheet(book, '蓝橙价格档案')
        if price_ws is None:
            raise BillCollectionError('生成结构缺少子表：蓝橙价格档案')
        parttime, price_yes = _fill_price_flag(main_ws, price_ws)
        progress(f'[异常骑手跟进] 主表兼职无单价报备：兼职 {parttime} 人，'
                 f'是 {price_yes} 人、否 {parttime - price_yes} 人；其他合作类型默认否')
        detail_ws = _find_sheet(book, '骑手详情表')
        ub_ws = _find_sheet(book, '风神薪资方案绑定')
        if ub_ws is None:
            raise BillCollectionError('生成结构缺少子表：风神薪资方案绑定')
        stats = _fill_abnormal_flag(main_ws, detail_ws, ub_ws, latest_day=detail_analysis['latest'])
        progress(f'[异常骑手跟进] 主表是否异常骑手：是 {stats["abnormal"]} 行、否 '
                 f'{main_ws.max_row - 3 - stats["abnormal"]} 行（状态命中 {stats["status"]}、'
                 f'出勤间隔≥{ABSENTEE_DAYS}天或无完单 {stats["absentee"]}、'
                 f'薪资方案未绑定 {stats["salary"]}、扣款方案未绑定 {stats["deduction"]}；'
                 f'风神方案配对命中 {stats["matched"]} 行、未命中 {stats["unmatched"]} 行判否）')
        _checkpoint(cancelled)
        rental_totals = _copy_rental_sheet(book, goods_file, month, log=progress)
        rental_days = _fill_rental_days(main_ws, rental_totals)
        progress(f'[异常骑手跟进] 主表租车/住宿天数：按站点+骑手ID 配对到租用记录 '
                 f'{rental_days} 行，其余写 0')
        noted = _fill_maintenance_notes(main_ws)
        progress(f'[异常骑手跟进] 主表备注：租车/住宿天数少于出勤天数 {noted} 行；'
                 f'是否需跟进城市维护按备注是否为空判定')
        _autofit_columns(main_ws, (ABNORMAL_REASON_FIELD, NOTE_FIELD))
        _border_main(main_ws)
        progress('[异常骑手跟进] 主表数据行已统一加细实线边框，异常原因/备注列宽已自适应')
        # 4) 模板中未改写的辅助表同样居中
        for ws in book.worksheets:
            if _sheet_suffix(ws.title) not in _SUB_SUFFIXES:
                _center_sheet(ws)
        analysis_ws = _find_sheet(book, ANALYSIS_FIELD)
        if analysis_ws is None:
            raise BillCollectionError('生成结构缺少子表：分析表')
        analysis_rows = _write_analysis_sheet(analysis_ws, main_ws, month)
        progress(f'[异常骑手跟进] 分析表已生成：{analysis_rows} 个站点（按站点汇总）')
        guide_ws = _find_sheet(book, GUIDE_FIELD)
        if guide_ws is None:
            raise BillCollectionError('生成结构缺少子表：说明')
        _write_guide_sheet(guide_ws, main_ws, city, month)
        progress('[异常骑手跟进] 说明表已生成：本期概览/异常规则/字段口径/常见 QA')
        year, mon = (int(part) for part in month.split('-'))
        target = output_dir / archive_filename(
            city, 'abnormal_followup', f'{month}-01', f'{month}-{monthrange(year, mon)[1]:02d}',
            suffix='.xlsx', stamp=stamp)
        with stage('save_workbook'):
            book.save(target)
        progress(f'[异常骑手跟进] 成品已生成：{target.name}')
        return target
    finally:
        if book is not None:
            book.close()


# 汇总时各 sheet 的表头行数（数据从表头之后开始）
_SUMMARY_HEADER_ROWS = {
    '异常骑手跟进表': 3,
    '风神薪资方案绑定': UB_HEADER_ROWS,
}
# 价格档案按城市筛选后各城市内容不同，汇总时需逐城市合并
_SHARED_SHEETS = ()

_SUB_SUFFIXES = ('异常骑手跟进表', '骑手绑定情况', '骑手详情表', '骑手信息表',
                 '风神薪资方案绑定', '蓝橙价格档案', '蓝橙员工档案', '电动车住宿租用')


def _sheet_suffix(title):
    for suffix in _SUB_SUFFIXES:
        if title.endswith(suffix):
            return suffix
    return title


def _append_rows(dst_ws, src_ws, header_rows):
    """把来源 sheet 表头之后的数据行追加到目标 sheet 末尾，并保留数字/日期格式。"""
    from itertools import islice
    target_row = dst_ws.max_row + 1
    for source_row in islice(src_ws.iter_rows(), header_rows, None):
        if not any(cell.value is not None for cell in source_row):
            continue
        for column, source in enumerate(source_row, 1):
            cell = dst_ws.cell(row=target_row, column=column, value=source.value)
            if source.value is not None:
                cell.data_type = source.data_type
                if source.number_format is not None:
                    cell.number_format = source.number_format
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
        target_row += 1
    _center_columns(dst_ws)


def _sort_archive_sheet(ws):
    """多城市合并后按「项目」升序重排，空项目置后。"""
    rows = [list(row) for row in ws.iter_rows(min_row=2, values_only=True)
            if any(value is not None for value in row)]
    rows.sort(key=lambda row: rider_archive.project_sort_key(row[0] if row else None))
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    start = ws.max_row + 1
    for values in rows:
        ws.append(values)
    for row in ws.iter_rows(min_row=start, max_row=ws.max_row):
        for cell in row:
            cell.font = _DATA_FONT
            cell.alignment = _CENTER
    _center_columns(ws)


def build_followup_summaries(root, config, files, items, cancelled):
    """多城市异常骑手跟进汇总：按月合并各城市成品，返回汇总文件条目。"""
    import hashlib
    if 'abnormal_followup' not in config.get('datasets', ()) or len(config.get('cities', ())) < 2:
        return []
    root = Path(root).resolve()
    wanted = [value for value in items if value.get('dataset') == 'abnormal_followup']
    results = []
    for month in sorted({value['start'][:7] for value in wanted}):
        selected = [value for value in wanted if value['start'][:7] == month]
        successful = {value['city'] for value in selected if value['status'] == 'success'}
        sources = [value for value in files if value.get('dataset') == 'abnormal_followup'
                   and value.get('artifact_role') != 'summary'
                   and value.get('start', '')[:7] == month and value.get('city') in successful]
        if len(sources) < 2:
            continue
        sources = sorted(sources, key=lambda value: value['city'])
        source_paths = []
        for info in sources:
            path = (root / info['relative_path']).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise BillCollectionError('异常骑手跟进汇总来源文件无效')
            source_paths.append((info['city'], path))
        base = load_workbook(source_paths[0][1], data_only=False)
        try:
            for city, path in source_paths[1:]:
                _checkpoint(cancelled)
                other = load_workbook(path, data_only=False, read_only=True)
                try:
                    for ws in base.worksheets:
                        suffix = _sheet_suffix(ws.title)
                        if suffix in _SHARED_SHEETS or suffix in (ANALYSIS_FIELD, GUIDE_FIELD):
                            continue
                        other_ws = _find_sheet(other, suffix)
                        if other_ws is None:
                            raise BillCollectionError(f'汇总来源缺少子表：{suffix}')
                        _append_rows(ws, other_ws, _SUMMARY_HEADER_ROWS.get(suffix, 1))
                finally:
                    other.close()
            archive_ws = _find_sheet(base, '蓝橙员工档案')
            if archive_ws is not None:
                _sort_archive_sheet(archive_ws)
            main_summary = _find_sheet(base, '异常骑手跟进表')
            if main_summary is not None:
                _autofit_columns(main_summary, (ABNORMAL_REASON_FIELD, NOTE_FIELD))
                _border_main(main_summary)
                main_summary.freeze_panes = 'A4'
            analysis_ws = _find_sheet(base, ANALYSIS_FIELD)
            if analysis_ws is not None and main_summary is not None:
                _write_analysis_sheet(analysis_ws, main_summary, month, summary=True)
            guide_ws = _find_sheet(base, GUIDE_FIELD)
            if guide_ws is not None and main_summary is not None:
                _write_guide_sheet(guide_ws, main_summary, '多城市汇总', month)
            target = root / archive_filename(
                '多城市汇总', 'abnormal_followup', sources[0]['start'], sources[0]['end'],
                suffix='.xlsx', stamp=config.get('archive_created_at'))
            base.save(target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            results.append({
                'city': '多城市汇总', 'dataset': 'abnormal_followup', 'artifact_role': 'summary',
                'start': sources[0]['start'], 'end': sources[0]['end'], 'name': target.name,
                'relative_path': target.name, 'bytes': target.stat().st_size, 'sha256': digest})
        finally:
            base.close()
    return results
