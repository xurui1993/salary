"""Narrow, documented correction of six legacy placeholder cells.

The captured JSON remains immutable. This is not a general NaN normalizer:
money, identifiers, named fields and actual output are never rewritten.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def expected_with_blank_placeholders(original, source_files, reference_bytes):
    from openpyxl import load_workbook
    notes=json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/xiaoxiang_blank_reference_notes.json').read_text('utf-8'))
    if hashlib.sha256(reference_bytes).hexdigest() != notes['historical_reference_sha256'] or len(source_files) != 2:
        raise AssertionError('Historical reference or source set changed: re-audit blank reference notes')
    # Source daily exports have four real columns; N is generated padding.
    for file in source_files:
        book=load_workbook(file,read_only=True,data_only=False)
        try:
            if book.active.max_column != 4:
                raise AssertionError('Synthetic source structure changed: re-audit blank reference notes')
        finally:
            book.close()
    result=deepcopy(original)
    sheet=result['payroll']['配送单']
    if sheet['rows'][0][13] != 'Temp_Col_13' or len(sheet['rows']) != 7:
        raise AssertionError('Legacy placeholder locations changed: re-audit reference notes')
    for row in range(1,7):
        if sheet['rows'][row][13] != 'nan':
            raise AssertionError('Legacy placeholder was changed without updating its audit record')
        sheet['rows'][row][13]=None
    return result
