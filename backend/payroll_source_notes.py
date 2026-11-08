"""Short, safe explanations for unavailable payroll inputs, without retry state."""
from collection_errors import collection_failure
from fengshen_bill import BillCollectionError


def source_reason(value, phase='collect'):
    # Download callbacks already contain curated public errors. Recheck the
    # sensitive-message boundary rather than persisting arbitrary future text.
    error = value if isinstance(value, Exception) else BillCollectionError(str(value))
    text = str(collection_failure(error, phase))
    for suffix in ('；核算已停止', '；下载已停止'):
        text = text.removesuffix(suffix)
    return ' '.join(text.split())[:500]


def input_note(reasons):
    distinct = list(dict.fromkeys(reason for reason in reasons if reason))
    return ('；'.join(distinct)[:700] if distinct else '采集已结束，但没有取得可用文件') + '；未参与本次核算'
