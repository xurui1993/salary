"""Streaming tabular exports using the existing artifact-authored workbook styles."""
from datetime import date,datetime
from decimal import Decimal
import math
import xml.etree.ElementTree as ET
from price_export_workbook import WorkbookStream,NS,text


def letter(index):
    result='';index+=1
    while index:index,value=divmod(index-1,26);result=chr(65+value)+result
    return result


def value_cell(column,row,value,style):
    ref=f'{letter(column)}{row}';attributes=f'r="{ref}" s="{style}"'
    if value is None:return f'<c {attributes}/>'
    if isinstance(value,datetime):value=value.isoformat(sep=' ')
    if isinstance(value,bool):return f'<c {attributes} t="b"><v>{int(value)}</v></c>'
    if isinstance(value,date):value=value.isoformat()
    if isinstance(value,(int,float,Decimal)):
        if not math.isfinite(value):raise ValueError('来源包含非有限数字')
        return f'<c {attributes}><v>{value}</v></c>'
    return f'<c {attributes} t="inlineStr"><is><t xml:space="preserve">{text(value)}</t></is></c>'


class TabularWorkbook(WorkbookStream):
    """numeric_columns 输出0.00；指定 header_fill 时按参考成品克隆样式：雅黑10黑字、
    不加粗、居中、指定表头底色（header_q_fill 单独标记新增列）、行高/网格线/筛选器可控。"""

    def __init__(self,path,headers,name,scope,widths=None,source_url='https://aero-rush.ele.me/team-invite/index.html',numeric_columns=(),header_fill=None,header_q_fill=None,row_height=36,default_row_height=36,show_gridlines=False,auto_filter=True,**kwargs):
        self.titles=list(headers);self.title=name;self.widths=widths;self.source_url=source_url
        self.numeric_columns=tuple(numeric_columns);self.numeric_styles={}
        self.header_fill=header_fill;self.header_q_fill=header_q_fill
        self.row_height=row_height;self.default_row_height=default_row_height
        self.show_gridlines=show_gridlines;self.auto_filter=auto_filter
        self.header_style=None;self.header_q_style=None;self.data_style=None
        super().__init__(path,scope,**kwargs)
        if header_fill is not None:self.style_transform=self._build_transform()
        if not self.titles or len(self.titles)>512:raise ValueError('导出字段数量无效')
    def _build_transform(self):
        tag='{'+NS+'}'
        def transform(data):
            root=ET.fromstring(data.decode('utf-8'))
            fonts=root.find(tag+'fonts')
            font=ET.SubElement(fonts,tag+'font')
            ET.SubElement(font,tag+'sz').set('val','10')
            ET.SubElement(font,tag+'color').set('theme','1')
            ET.SubElement(font,tag+'name').set('val','微软雅黑')
            ET.SubElement(font,tag+'family').set('val','2')
            ET.SubElement(font,tag+'charset').set('val','134')
            font_id=str(len(fonts)-1);fonts.set('count',str(len(fonts)))
            fills=root.find(tag+'fills')
            def add_fill(rgb):
                fill=ET.SubElement(fills,tag+'fill');pattern=ET.SubElement(fill,tag+'patternFill')
                pattern.set('patternType','solid');ET.SubElement(pattern,tag+'fgColor').set('rgb','FF'+rgb)
                ET.SubElement(pattern,tag+'bgColor').set('indexed','64')
                return str(len(fills)-1)
            header_fill_id=add_fill(self.header_fill)
            header_q_fill_id=header_fill_id if self.header_q_fill is None else add_fill(self.header_q_fill)
            fills.set('count',str(len(fills)))
            xfs=root.find(tag+'cellXfs')
            def add_xf(fill_id,num_fmt='0'):
                xf=ET.SubElement(xfs,tag+'xf')
                xf.set('numFmtId',num_fmt);xf.set('fontId',font_id);xf.set('fillId',fill_id);xf.set('borderId','0');xf.set('xfId','0')
                xf.set('applyNumberFormat','1');xf.set('applyFont','1');xf.set('applyAlignment','1')
                if fill_id!='0':xf.set('applyFill','1')
                alignment=ET.SubElement(xf,tag+'alignment');alignment.set('horizontal','center');alignment.set('vertical','center')
                return str(len(xfs)-1)
            self.data_style=add_xf('0')
            self.header_style=add_xf(header_fill_id)
            self.header_q_style=self.header_style if self.header_q_fill is None else add_xf(header_q_fill_id)
            for column in self.numeric_columns:self.numeric_styles[column]=add_xf('0','202')
            xfs.set('count',str(len(xfs)))
            return ET.tostring(root,encoding='utf-8',xml_declaration=True)
        return transform
    def __enter__(self):
        super().__enter__()
        for index,replacements in ((0,{'B1':self.source_url}),(3,dict(zip(('A4','B4','C4','D4','E4','F4','G4','H4','I4'),('商家编号','范围','站点','日期范围','分段','资料','数据行数','处理结果','说明'))))):
            row=ET.fromstring(self.audit_header[index])
            for target in row:
                if target.attrib.get('r') not in replacements:continue
                for child in list(target):target.remove(child)
                target.set('t','inlineStr');ET.SubElement(ET.SubElement(target,'{'+NS+'}is'),'{'+NS+'}t').text=replacements[target.attrib['r']]
            self.audit_header[index]=ET.tostring(row,encoding='unicode')
        return self
    def _open_main(self):
        prototype=ET.fromstring(self.header[0])
        header_style=self.header_style if self.header_style is not None else next(iter(prototype)).attrib.get('s','0')
        header_q_style=self.header_q_style if self.header_q_style is not None else header_style
        height='' if self.row_height is None else f' ht="{self.row_height}" customHeight="1"'
        row='<row r="1"'+height+'>'+''.join(value_cell(i,1,title,header_q_style if i in self.numeric_columns else header_style) for i,title in enumerate(self.titles))+'</row>'
        widths=self.widths or [38 if '站点' in h or '团队' in h else 26 if '证' in h or 'ID' in h or '时间' in h else 20 for h in self.titles]
        widths=(list(widths)+[20]*len(self.titles))[:len(self.titles)]
        cols='<cols>'+''.join(f'<col min="{i+1}" max="{i+1}" width="{width}" customWidth="1"/>' for i,width in enumerate(widths))+'</cols>'
        self._open(self.title if not self.names else self.title+str(len(self.names)+1),[row],cols,1)
    def _close(self,columns=None,filter_start=1):
        columns=columns or len(self.titles)
        filter_xml=f'<autoFilter ref="A{filter_start}:{letter(columns-1)}{self.sheet_rows}"/>' if self.auto_filter else ''
        self.stream.write(('</sheetData>'+filter_xml+'</worksheet>').encode('utf-8'));self.stream.close();self.stream=None
    def append(self,values):
        if len(values)!=len(self.titles):raise ValueError('明细列数与表头不一致，未静默截断')
        if self.sheet_rows>=self.row_limit:self._close();self._open_main()
        self.sheet_rows+=1;self.count+=1
        if self.row_height is None:height=''
        else:
            lines=max((str(value).count('\n')+1 for value in values if value is not None),default=1)
            height=f' ht="{min(160,max(self.row_height,18*lines))}" customHeight="1"'
        default=self.data_style if self.data_style is not None else self.styles.get('A','0')
        cells=''.join(value_cell(i,self.sheet_rows,value,str(self.numeric_styles.get(i,default))) for i,value in enumerate(values))
        self.stream.write((f'<row r="{self.sheet_rows}"{height}>'+cells+'</row>').encode('utf-8'))
