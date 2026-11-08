"""Stream records into an artifact-authored OOXML layout without extra runtime deps."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape,quoteattr
import zipfile

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
TEMPLATE=Path(__file__).with_name('assets')/'daily_prices_template.xlsx'
HEADERS=['结算模式','日期','城市名称','片区名称','站点名称','骑手姓名','身份证号','价格']


def package_xml(root):
    namespace,name=root.tag[1:].split('}',1)
    children=''.join('<'+item.tag.rsplit('}',1)[-1]+' '+ ' '.join(key+'='+quoteattr(value) for key,value in item.attrib.items())+'/>' for item in root)
    return ('<?xml version="1.0" encoding="UTF-8"?><'+name+' xmlns='+quoteattr(namespace)+'>'+children+'</'+name+'>').encode('utf-8')


def text(value):
    value=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))
    if len(value)>32767:raise ValueError('Excel文本过长，不能无提示截断')
    return escape(value)


def cell(column,row,value,style='0'):
    ref=f'{chr(65+column)}{row}';attributes=f'r="{ref}" s="{style}"'
    if value is None:return f'<c {attributes}/>'
    if isinstance(value,date):value=(value-date(1899,12,30)).days
    if isinstance(value,(int,Decimal)):
        if isinstance(value,Decimal) and not value.is_finite():raise ValueError('价格不是有限数字')
        return f'<c {attributes}><v>{value}</v></c>'
    return f'<c {attributes} t="inlineStr"><is><t xml:space="preserve">{text(value)}</t></is></c>'


def sheet_layout(data,header_rows,prototype_row,max_columns=None):
    root=ET.fromstring(data);sheet=root.find('{'+NS+'}sheetData')
    if max_columns is not None:
        for row in sheet:
            for item in list(row):
                name=re.sub(r'\d','',item.attrib.get('r',''))
                if len(name)>1 or name>chr(64+max_columns):row.remove(item)
    headers=[ET.tostring(row,encoding='unicode') for row in sheet if int(row.attrib['r'])<=header_rows]
    prototype=next(row for row in sheet if int(row.attrib['r'])==prototype_row)
    styles={re.sub(r'\d','',c.attrib['r']):c.attrib.get('s','0') for c in prototype}
    cols=root.find('{'+NS+'}cols')
    return headers,styles,ET.tostring(cols,encoding='unicode') if cols is not None else ''


class WorkbookStream:
    def __init__(self,path,query,*,row_limit=1048576,style_transform=None):
        self.path=Path(path);self.query=query;self.row_limit=row_limit;self.names=[];self.stream=None;self.count=0;self.sheet_rows=0
        self.style_transform=style_transform
    def __enter__(self):
        self.template=zipfile.ZipFile(TEMPLATE);self.output=zipfile.ZipFile(self.path,'w',zipfile.ZIP_DEFLATED,allowZip64=True)
        self.header,self.styles,self.cols=sheet_layout(self.template.read('xl/worksheets/sheet1.xml'),1,2,8)
        self.audit_header,self.audit_styles,self.audit_cols=sheet_layout(self.template.read('xl/worksheets/sheet2.xml'),4,5)
        for name in self.template.namelist():
            if name.startswith('xl/worksheets/') or name in ('xl/workbook.xml','xl/_rels/workbook.xml.rels','[Content_Types].xml','docProps/app.xml'):continue
            data=self.template.read(name)
            if name=='xl/styles.xml' and self.style_transform is not None:data=self.style_transform(data)
            self.output.writestr(name,data)
        self._open_main();return self
    def _open(self,name,headers,cols,freeze):
        self.names.append(name);index=len(self.names);self.stream=self.output.open(f'xl/worksheets/sheet{index}.xml','w',force_zip64=True)
        gridlines='' if getattr(self,'show_gridlines',False) else ' showGridLines="0"'
        self.stream.write((f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}"><sheetViews><sheetView{gridlines} workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze+1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="{getattr(self,"default_row_height",36)}"/>'+cols+'<sheetData>'+''.join(headers)).encode('utf8'))
        self.sheet_rows=freeze
    def _close(self,columns=8,filter_start=1):
        self.stream.write((f'</sheetData><autoFilter ref="A{filter_start}:{chr(64+columns)}{self.sheet_rows}"/></worksheet>').encode());self.stream.close();self.stream=None
    def _open_main(self):self._open('每日价格' if not self.names else '每日价格'+str(len(self.names)+1),self.header,self.cols,1)
    def append(self,values):
        if self.sheet_rows>=self.row_limit:self._close();self._open_main()
        self.sheet_rows+=1;self.count+=1
        self.stream.write((f'<row r="{self.sheet_rows}" ht="36" customHeight="1">'+''.join(cell(i,self.sheet_rows,value,self.styles.get(chr(65+i),'0')) for i,value in enumerate(values))+'</row>').encode('utf8'))
    def finish(self,receipts):
        self._close();headers=list(self.audit_header)
        # Replace only the scope cell; the source URL and layout remain intact.
        row=ET.fromstring(headers[1]);target=next((c for c in row if c.attrib.get('r')=='B2'),None)
        if target is not None:
            for child in list(target):target.remove(child)
            target.set('t','inlineStr');ET.SubElement(ET.SubElement(target,'{'+NS+'}is'),'{'+NS+'}t').text=self.query
        headers[1]=ET.tostring(row,encoding='unicode');self._open('采集记录',headers,self.audit_cols,4)
        for receipt in receipts:
            self.sheet_rows+=1
            values=[receipt.get(key,'') for key in ('business_id','city','station','period','version','status','row_count','result','message')]
            self.stream.write((f'<row r="{self.sheet_rows}" ht="48" customHeight="1">'+''.join(cell(i,self.sheet_rows,value,self.audit_styles.get(chr(65+i),'0')) for i,value in enumerate(values))+'</row>').encode('utf8'))
        self._close(9,4)
        workbook=ET.fromstring(self.template.read('xl/workbook.xml'));sheets=workbook.find('{'+NS+'}sheets');sheets.clear()
        relationships=ET.fromstring(self.template.read('xl/_rels/workbook.xml.rels'));sheet_type=REL+'/worksheet'
        for item in list(relationships):
            if item.attrib.get('Type')==sheet_type:relationships.remove(item)
        used={r.attrib['Id'] for r in relationships};index=1
        types=ET.fromstring(self.template.read('[Content_Types].xml'))
        for item in list(types):
            if item.attrib.get('PartName','').startswith('/xl/worksheets/'):types.remove(item)
        for number,name in enumerate(self.names,1):
            while f'rId{index}' in used:index+=1
            rid=f'rId{index}';used.add(rid)
            ET.SubElement(sheets,'{'+NS+'}sheet',{'name':name,'sheetId':str(number),'{'+REL+'}id':rid})
            ET.SubElement(relationships,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',{'Id':rid,'Type':sheet_type,'Target':f'worksheets/sheet{number}.xml'})
            ET.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',{'PartName':f'/xl/worksheets/sheet{number}.xml','ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
        self.output.writestr('xl/workbook.xml',ET.tostring(workbook,encoding='utf-8',xml_declaration=True))
        for name,root in [('xl/_rels/workbook.xml.rels',relationships),('[Content_Types].xml',types)]:self.output.writestr(name,package_xml(root))
        if 'docProps/app.xml' in self.template.namelist():
            app=ET.fromstring(self.template.read('docProps/app.xml'));ext='http://schemas.openxmlformats.org/officeDocument/2006/extended-properties';vt='http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
            titles=app.find('{'+ext+'}TitlesOfParts')
            if titles is not None:
                vector=titles.find('{'+vt+'}vector')
                if vector is not None:
                    vector.clear();vector.set('size',str(len(self.names)));vector.set('baseType','lpstr')
                    for name in self.names:ET.SubElement(vector,'{'+vt+'}lpstr').text=name
            count=app.find('.//{'+vt+'}i4')
            if count is not None:count.text=str(len(self.names))
            self.output.writestr('docProps/app.xml',ET.tostring(app,encoding='utf-8',xml_declaration=True))
    def __exit__(self,*args):
        if self.stream is not None:self.stream.close()
        self.output.close();self.template.close()
