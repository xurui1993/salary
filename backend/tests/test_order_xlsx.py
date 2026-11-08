import datetime as dt
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import pandas as pd
from openpyxl import Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import order_sources as sources
import order_xlsx as fast
from fengshen_bill import BillCollectionError

class FastOrderXlsxTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def book(self,rows,sheets=None):
  book=Workbook();sheet=book.active;sheet.title='运单'
  for row in rows:sheet.append(row)
  if sheets:
   for name,content in sheets.items():
    target=book.create_sheet(name)
    for row in content:target.append(row)
  path=self.root/'source.xlsx';book.save(path);book.close();return path
 def original(self,path,required):
  with patch.object(fast,'read_xlsx_tables',side_effect=fast.FastXlsxUnsupported):return sources.read_table(path,required)
 def equal(self,path,required,expect_fast):
  before=path.read_bytes();original=self.original(path,required)
  with patch.object(sources,'load_workbook',wraps=sources.load_workbook) as old:
   candidate=sources.read_table(path,required)
   self.assertEqual(old.call_count==0,expect_fast)
  pd.testing.assert_frame_equal(candidate,original);self.assertEqual(path.read_bytes(),before);return candidate
 def test_dense_values_match_integers_floats_booleans_and_empty_cells(self):
  path=self.book([['编号','数值','布尔','空值'],['000123456789012345678',1,True,''],['0002',1.25,False,'']])
  self.equal(path,{'编号','数值'},True)
 def test_integer_precision_comes_from_xml_not_native_float(self):
  path=self.book([['编号','数值'],['0001',123456789012345678],['0002',1.0]])
  from zipfile import ZipFile
  with ZipFile(path) as archive:parts={name:archive.read(name) for name in archive.namelist()}
  parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'1.234567890123457e+17',b'123456789012345678')
  with ZipFile(path,'w') as archive:
   for name,data in parts.items():archive.writestr(name,data)
  data=self.equal(path,{'编号'},True);self.assertEqual(int(data['数值'].iloc[0]),123456789012345678)
 def test_shared_strings_and_whitespace_headers(self):
  import xlsxwriter
  path=self.root/'source.xlsx';book=xlsxwriter.Workbook(path);sheet=book.add_worksheet('运单')
  for index,row in enumerate([[' 编号\t','数值'],['0001','  值\t'],['0002','中文']]):sheet.write_row(index,0,row)
  book.close();self.equal(path,{'编号'},True)
 def test_excel_date_styles_fall_back(self):
  path=self.book([['编号','日期'],['0001',dt.datetime(2026,10,1,2,3)],['0002',dt.datetime(2026,10,2)]])
  self.equal(path,{'编号'},False)
 def test_formulas_and_error_cells_fall_back(self):
  for value in ('=1+1','#N/A'):
   with self.subTest(value=value):self.equal(self.book([['编号','值'],['0001',value]]),{'编号'},False)
 def test_escaped_text_falls_back(self):self.equal(self.book([['编号','值'],['0001','_x005F_escaped']]),{'编号'},False)
 def test_sparse_interior_cells_fall_back_and_keep_numeric_inference(self):
  self.equal(self.book([['编号','数值','尾列'],['0001',None,'x'],['0002',1,'x']]),{'编号'},False)
 def test_two_matching_sheets_are_rejected(self):
  path=self.book([['编号'],['0001']],{'第二张':[['编号'],['0002']]})
  with self.assertRaisesRegex(BillCollectionError,'多个'):sources.read_table(path,{'编号'})
 def test_unrelated_sheets_are_ignored(self):
  self.equal(self.book([['编号','数值'],['0001',2]],{'说明':[['说明'],['其他文字']]}),{'编号'},True)
 def test_short_rows_and_shifted_header_are_not_silently_padded(self):
  for rows in ([['编号','数值'],['0001']], [[],['编号','数值'],['0001',1]]):
   path=self.book(rows)
   with self.subTest(rows=rows),self.assertRaises(BillCollectionError):sources.read_table(path,{'编号','数值'})
 def test_stale_dimension_does_not_truncate_source_values(self):
  path=self.book([['编号','数值'],['0001',2],['0002',3]])
  from zipfile import ZipFile
  with ZipFile(path) as archive:parts={name:archive.read(name) for name in archive.namelist()}
  parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'ref="A1:B3"',b'ref="A1:A1"')
  with ZipFile(path,'w') as archive:
   for name,data in parts.items():archive.writestr(name,data)
  pd.testing.assert_frame_equal(sources.read_table(path,{'编号'}),self.original(path,{'编号'}))
 def test_rich_inline_text_uses_original_reader(self):
  path=self.book([['编号','值'],['0001','foobar']])
  from zipfile import ZipFile
  with ZipFile(path) as archive:parts={name:archive.read(name) for name in archive.namelist()}
  parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'<is><t>foobar</t></is>',b'<is><r><t>foo</t></r><r><t>bar</t></r></is>')
  with ZipFile(path,'w') as archive:
   for name,data in parts.items():archive.writestr(name,data)
  self.equal(path,{'编号'},False)
 def test_size_budget_keeps_original_reader(self):
  path=self.book([['编号'],['0001']])
  with patch.object(fast,'MAX_NATIVE_XML_BYTES',0):self.equal(path,{'编号'},False)
 def test_missing_native_dependency_keeps_original_reader(self):
  path=self.book([['编号'],['0001']])
  with patch.dict(sys.modules,{'python_calamine':None}):self.equal(path,{'编号'},False)
if __name__=='__main__':unittest.main()
