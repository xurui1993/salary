"""Code-owned workbook schema for abnormal-rider follow-up; no Excel template I/O."""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

SHEETS = ('说明',
 '分析表',
 '10月异常骑手跟进表',
 '10月骑手绑定情况',
 '10月骑手详情表',
 '10月骑手信息表',
 '10月风神薪资方案绑定',
 '10月蓝橙价格档案',
 '10月蓝橙员工档案',
 '10月电动车住宿租用')

HEADERS = ('城市',
 '团队名称',
 '骑手ID',
 '骑手姓名',
 '骑手身份证',
 '合作类型',
 '状态',
 '招聘来源',
 '是否寒暑假工',
 '兼职无单价报备骑手',
 '发薪工具是否绑定',
 '10月活跃天',
 '10月完单量',
 '10月最后出勤日',
 '是否异常骑手',
 '异常原因',
 '内推已发',
 '地推已发',
 '新人奖已发',
 '兼转全已发',
 '租车天数',
 '住宿天数',
 '备注',
 '薪资方案是否绑定',
 '扣款方案是否绑定',
 '是否需跟进城市维护',
 '备注',
 '城市是否维护',
 '维护日期',
 '备注',
 '合作日期')

GROUPS = (('A1', '“新专送”10月异常骑手跟进表'),
 ('A2', '骑手信息'),
 ('Q2', '已发奖励 （仅展示未满足考核需要扣回的金额）'),
 ('U2', '风神扣款天数维护'),
 ('X2', '风神扣款维护'),
 ('Z2', '跟进动作（薪资组）'),
 ('AB2', '闭环动作（城市操作，薪资组登记记录）'))

MERGES = ('U2:W2', 'Z2:AA2', 'X2:Y2', 'Q2:T2', 'A1:AD1', 'A2:P2')

WIDTHS = {'A': 4.75,
 'B': 36.5,
 'C': 12.875,
 'D': 19.0,
 'E': 20.5,
 'F': 9.625,
 'H': 15.875,
 'I': 11.375,
 'J': 16.75,
 'K': 30.75,
 'L': 10.0,
 'N': 13.625,
 'O': 11.375,
 'P': 12.125,
 'Q': 8.0,
 'S': 9.625,
 'U': 8.0,
 'W': 25.75,
 'X': 15.0,
 'Z': 9.625,
 'AA': 22.25,
 'AB': 33.0,
 'AC': 8.0,
 'AD': 4.75,
 'AE': 11.125}

HEADER_STYLES = {'A1': ('FF00B0F0', 'FFFFFFFF', 18.0, True, False, 'General'),
 'A2': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'Q2': ('FFDAE3F3', 'FF000000', 10.0, False, False, 'General'),
 'U2': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'X2': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'Z2': ('FFFFD966', 'FF000000', 10.0, False, False, 'General'),
 'AB2': ('FF00B0F0', 'FFFFFFFF', 10.0, False, False, 'General'),
 'A3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'B3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'C3': ('FFFBE5D6', 'FF000000', 10.0, False, False, '0'),
 'D3': ('FFFBE5D6', 'FF000000', 10.0, False, False, '0'),
 'E3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'F3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'G3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'H3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'I3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'J3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'K3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'L3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'M3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'N3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'mm-dd-yy'),
 'O3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'P3': ('FFFBE5D6', 'FF000000', 10.0, False, False, 'General'),
 'Q3': ('FFDAE3F3', 'FF000000', 10.0, False, False, 'General'),
 'R3': ('FFDAE3F3', 'FF000000', 10.0, False, False, 'General'),
 'S3': ('FFDAE3F3', 'FF000000', 10.0, False, False, 'General'),
 'T3': ('FFDAE3F3', 'FF000000', 10.0, False, False, 'General'),
 'U3': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'V3': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'W3': ('FFFFD966', 'FF000000', 10.0, False, False, 'General'),
 'X3': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'Y3': ('FFE2F0D9', 'FF000000', 10.0, False, False, 'General'),
 'Z3': ('FFFFD966', 'FF000000', 10.0, False, True, 'General'),
 'AA3': ('FFFFD966', 'FF000000', 10.0, False, False, 'General'),
 'AB3': ('FF00B0F0', 'FFFFFFFF', 10.0, False, False, 'General'),
 'AC3': ('FF00B0F0', 'FFFFFFFF', 10.0, False, False, 'General'),
 'AD3': ('FF00B0F0', 'FFFFFFFF', 10.0, False, False, 'General'),
 'AE3': ('FFFFFF00', 'FFFF0000', 10.0, True, False, 'mm-dd-yy')}

def create_followup_workbook(month):
    """Keep the established sheet order, 31 columns and three header rows."""
    label = f'{int(str(month).split("-")[1])}月'
    book = Workbook()
    book.remove(book.active)
    for title in SHEETS:
        book.create_sheet(title.replace('10月', label))
    main = next(ws for ws in book.worksheets if ws.title.endswith('异常骑手跟进表'))
    for address, value in GROUPS:
        main[address] = value.replace('10月', label)
    for column, value in enumerate(HEADERS, 1):
        main.cell(3, column, value.replace('10月', label))
    border = Border(**{edge: Side(style='thin') for edge in ('left', 'right', 'top', 'bottom')})
    for address, (fill, color, size, bold, wrap, number_format) in HEADER_STYLES.items():
        cell = main[address]
        cell.fill = PatternFill('solid', fgColor=fill)
        cell.font = Font(name='微软雅黑', size=size, bold=bold, color=color)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=wrap)
        cell.border = border
        cell.number_format = number_format
    for merged in MERGES:
        main.merge_cells(merged)
    for column, width in WIDTHS.items():
        main.column_dimensions[column].width = width
    for row, height in ((1, 24.75), (2, 16.5), (3, 33)):
        main.row_dimensions[row].height = height
    main.freeze_panes = 'A4'
    return book
