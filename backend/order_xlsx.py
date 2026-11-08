"""Fast native XLSX values with XML guards for legacy-reader equivalence.

Complex cells are deliberately delegated to the original openpyxl reader.
No formulas are evaluated and no new dependencies are required.
"""
import posixpath
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from lxml import etree
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format, is_timedelta_format
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
from fengshen_bill import BillCollectionError

class FastXlsxUnsupported(Exception):
    pass

MAX_NATIVE_XML_BYTES = 256 * 1024 * 1024
MAX_NATIVE_FILE_BYTES = 32 * 1024 * 1024

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL_ID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def _metadata(archive):
    styles = archive.read('xl/styles.xml') if 'xl/styles.xml' in archive.namelist() else None
    date_styles = set()
    style_count = 1
    if styles:
        root = ET.fromstring(styles)
        custom = {int(item.attrib['numFmtId']): item.attrib['formatCode'] for item in root.findall(MAIN+'numFmts/'+MAIN+'numFmt')}
        formats = root.find(MAIN+'cellXfs')
        if formats is not None:
            style_count = len(formats)
            for index, item in enumerate(formats):
                number = int(item.get('numFmtId','0'));code=custom.get(number,BUILTIN_FORMATS.get(number,''))
                if is_date_format(code) or is_timedelta_format(code):date_styles.add(index)
    # Rich shared strings and Excel escape encodings can differ between readers.
    for name in archive.namelist():
        if name != 'xl/sharedStrings.xml' and not (name.startswith('xl/worksheets/') and name.endswith('.xml')):
            continue
        with archive.open(name) as stream:
            previous=b''
            while True:
                block=stream.read(1024*1024)
                if not block:break
                joined=previous+block
                if b'_x' in joined or (name == 'xl/sharedStrings.xml' and (b'<r>' in joined or b'<r ' in joined)):
                    raise FastXlsxUnsupported('complex or escaped text')
                previous=joined[-32:]
    relations = {item.get('Id'):item for item in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
    sheets=[]
    for item in ET.fromstring(archive.read('xl/workbook.xml')).findall(MAIN+'sheets/'+MAIN+'sheet'):
        rel=relations[item.get(REL_ID)]
        if not rel.get('Type','').endswith('/worksheet'):continue
        target=rel.get('Target','')
        target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
        if not target.startswith('xl/worksheets/') or '..' in target.split('/'):
            raise FastXlsxUnsupported('worksheet relationship')
        sheets.append((item.get('name'),target))
    return sheets,date_styles,style_count


def _rows(archive, target, sheet, date_styles, style_count, checkpoint):
    # Only dense, ordered plain-value rows use the native path. Complex or
    # irregular structures retain the original reader as their authority.
    if sheet.start not in ((0,0),None):raise FastXlsxUnsupported('shifted used range')
    native=iter(sheet.iter_rows());native_position=0;previous_row=0;letters={}
    ns={'m':MAIN[1:-1]}
    special=etree.XPath('./m:c[not(@t) or (@t!="inlineStr" and @t!="s" and @t!="str") or m:f] | ./m:c/m:is/m:r',namespaces=ns)
    references=etree.XPath('./m:c/@r',namespaces=ns)
    with archive.open(target) as stream:
        for _,row in etree.iterparse(stream,events=('end',),tag=MAIN+'row',resolve_entities=False,no_network=True):
            if checkpoint is not None:checkpoint()
            number=int(row.get('r','0'))
            if number<=previous_row:raise FastXlsxUnsupported('row ordering')
            previous_row=number
            values=[]
            while native_position<number:
                values=list(next(native,[]));native_position+=1
            coords=references(row)
            width=len(coords)
            if width:
                if width not in letters:letters[width]=[get_column_letter(i) for i in range(1,width+1)]
                prefixes=letters[width];suffix=str(number)
                if coords != [prefix+suffix for prefix in prefixes] or len(row)!=width:
                    raise FastXlsxUnsupported('sparse or irregular row')
            while len(values)<width:values.append(None)
            values=values[:width]
            for cell in special(row):
                kind=cell.get('t','n');style=int(cell.get('s','0'))
                if cell.tag!=MAIN+'c' or style>=style_count or cell.find(MAIN+'f') is not None or kind not in ('n','b'):
                    raise FastXlsxUnsupported('complex cell')
                _,column=coordinate_to_tuple(cell.get('r'))
                if kind=='n':
                    if style in date_styles:raise FastXlsxUnsupported('Excel date serial')
                    value=cell.find(MAIN+'v');text=value.text if value is not None else None
                    values[column-1]=(None if text is None else float(text) if any(x in text for x in '.Ee') else int(text))
                else:
                    value=cell.find(MAIN+'v');values[column-1]=bool(int(value.text)) if value is not None and value.text else None
            for index,value in enumerate(values):
                if isinstance(value,str):
                    if '_x' in value:raise FastXlsxUnsupported('escaped cell text')
                    if value=='':
                        cell=row[index]
                        if cell.get('t')=='inlineStr':
                            if cell.find(MAIN+'is') is None:values[index]=None
                        elif cell.find(MAIN+'v') is None:values[index]=None
            yield values
            row.clear()
            while row.getprevious() is not None:del row.getparent()[0]


def read_xlsx_tables(path, required, reader, checkpoint=None):
    try:
        from python_calamine import CalamineWorkbook
        if path.stat().st_size > MAX_NATIVE_FILE_BYTES:raise FastXlsxUnsupported('native reader size budget')
        with ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist() if info.filename.endswith('.xml')) > MAX_NATIVE_XML_BYTES:
                raise FastXlsxUnsupported('native reader XML budget')
            sheets,date_styles,style_count=_metadata(archive)
            book=CalamineWorkbook.from_path(str(path))
            try:
                candidates=[]
                for name,target in sheets:
                    sheet=book.get_sheet_by_name(name)
                    value=reader(_rows(archive,target,sheet,date_styles,style_count,checkpoint),required,checkpoint)
                    if value is not None:candidates.append(value)
                return candidates
            finally:book.close()
    except BillCollectionError:
        raise
    except FastXlsxUnsupported:
        raise
    except Exception as exc:
        raise FastXlsxUnsupported(type(exc).__name__) from None
