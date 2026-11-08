"""Compare generated workbook content, formulas and presentation contracts."""
from pathlib import Path
from openpyxl import load_workbook


def workbook_contract(path):
    book = load_workbook(Path(path), data_only=False)
    try:
        return {'sheets': [{
            'name': sheet.title, 'state': sheet.sheet_state,
            'rows': [[{'value': cell.value, 'type': cell.data_type,
                       'number_format': cell.number_format,
                       'style': tuple(cell._style) if cell.has_style else None}
                      for cell in row] for row in sheet.iter_rows()],
            'merged': sorted(str(value) for value in sheet.merged_cells.ranges),
            'freeze': sheet.freeze_panes,
            'tables': {key: sheet.tables[key].ref for key in sheet.tables},
            'columns': {key: (value.width, value.hidden) for key, value in sheet.column_dimensions.items()},
            'row_heights': {key: (value.height, value.hidden) for key, value in sheet.row_dimensions.items()},
        } for sheet in book]}
    finally:
        book.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before'); parser.add_argument('after')
    args = parser.parse_args()
    equal = workbook_contract(args.before) == workbook_contract(args.after)
    print('MATCH' if equal else 'DIFFERENT')
    raise SystemExit(0 if equal else 1)
