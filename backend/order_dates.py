"""Task-local date normalization, shared by validation and business rules."""
import pandas as pd


class OrderDates:
    def __init__(self):
        self.timestamps = {}

    def parse(self, values):
        if values.nunique() > 10000:
            # High-cardinality finish timestamps belong in a compact datetime
            # array; retaining one Python Timestamp per value wastes memory.
            return pd.to_datetime(values, format="mixed", errors="raise")
        missing = [value for value in pd.unique(values) if value not in self.timestamps]
        if missing:
            parsed = pd.to_datetime(pd.Series(missing), format="mixed", errors="raise")
            self.timestamps.update(zip(missing, parsed))
        return pd.to_datetime(values.map(self.timestamps))

    def window(self, values, finish):
        """Preserve the legacy before-start/after-end choice and rounding."""
        if any(not isinstance(value, str) for value in values):
            raise TypeError("考核时间应为文本")
        parts = values.str.split("~", expand=True)
        if parts.shape[1] > 2:
            raise ValueError("考核时间区间格式无效")
        start = self.parse(parts[0])
        end = self.parse(parts[1].fillna(parts[0])) if parts.shape[1] == 2 else start
        reference = end.where(start.le(finish), start)
        minutes = (finish - reference) / pd.Timedelta(1, "min")
        # Python round is retained at half-cent boundaries used by old rules.
        return minutes.map(lambda value: round(float(value), 2))


def natural_dates(values):
    """Match parse_date's accepted textual shape without a Python call per row."""
    from parttime_source import SourceError
    if values.empty:
        return pd.Series(index=values.index, dtype=object)
    text = values.astype(str).str.strip()
    shape = r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
    if not text.str.fullmatch(shape).all():
        raise SourceError("日期缺失或格式错误，应包含完整年月日")
    parts = text.str.extract("^" + shape + "$")
    key = parts[0] + "-" + parts[1].str.zfill(2) + "-" + parts[2].str.zfill(2)
    unique = pd.Series(pd.unique(key))
    try:
        parsed = pd.to_datetime(unique, format="%Y-%m-%d", errors="raise").dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        raise SourceError("日期缺失或格式错误，应包含完整年月日") from None
    return key.map(dict(zip(unique, parsed)))
