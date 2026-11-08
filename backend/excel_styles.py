"""Reuse immutable openpyxl style arrays instead of rebuilding them per cell."""
from copy import copy
from openpyxl.styles.cell_style import StyleArray
from openpyxl.cell.cell import Cell


def style_applier(sheet, *, font=None, alignment=None, border=None):
    book = sheet.parent
    changes = {}
    if font is not None:
        changes['fontId'] = book._fonts.add(font)
    if alignment is not None:
        changes['alignmentId'] = book._alignments.add(alignment)
    if border is not None:
        changes['borderId'] = book._borders.add(border)
    cache = {}

    def apply(cell):
        original = cell._style
        key = tuple(original) if original is not None else ()
        if key not in cache:
            value = copy(original) if original is not None else StyleArray()
            for name, identifier in changes.items():
                setattr(value, name, identifier)
            cache[key] = value
        # 赋共享缓存会被后续 cell.fill/font 等 setter 就地改写，必须再拷贝一份。
        cell._style = copy(cache[key])
    return apply


def prepared_write_only_rows(sheet):
    """Fast path for already prepared Cells on code-owned write-only sheets.

    openpyxl's generic converter first tries to bind each Cell as a scalar and
    catches ValueError. These sheets supply actual Cells, so avoid one exception
    and one redundant Cell allocation per styled output cell. Ordinary values
    and unrecognized library versions retain the original converter.
    """
    original = getattr(sheet, '_values_to_row', None)
    if not callable(original):
        return

    def convert(values, row_index):
        if not isinstance(values, (list, tuple)) or not all(isinstance(cell, Cell) for cell in values):
            yield from original(values, row_index)
            return
        for column, cell in enumerate(values, 1):
            cell.column, cell.row = column, row_index
            if cell.hyperlink is not None:
                cell.hyperlink.ref = cell.coordinate
            yield cell

    sheet._values_to_row = convert
