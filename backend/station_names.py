"""Station name compatibility shared by payroll engines and deduction matching."""
import re

CITY_PREFIXES = (
    "惠州", "惠州市", "汕头", "汕头市", "潮州", "潮州市", "深圳", "深圳市",
    "广州", "广州市", "东莞", "东莞市", "宁波", "宁波市", "上海", "上海市",
    "北京", "北京市", "天津", "天津市", "台州", "台州市", "韶关", "韶关市",
    "大连", "大连市", "保定", "保定市", "泉州", "泉州市", "三亚", "三亚市",
)


def station_clean(name):
    value = str("" if name is None else name)
    for char in (" ", "\u3000", "\xa0", "\n", "\t", "\r"):
        value = value.replace(char, "")
    value = value.replace("店", "站")
    if value.startswith("小象超市"):
        rest = value[len("小象超市"):].lstrip("-_－")
        if len(rest) >= 2:
            value = rest
    for prefix in CITY_PREFIXES:
        if value.startswith(prefix):
            rest = value[len(prefix):].lstrip("-_－")
            if len(rest) >= 3:
                value = rest
            break
    value = re.sub(r"[（(].*?[)）]", "", value)
    value = re.sub(r"[-_－](?:UB|新专送|取分离).*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[-_－][A-Za-z]{1,5}\d{2,}.*$", "", value)
    return value.strip("-_－ ")


def station_code(name):
    match = re.search(r"([A-Za-z]{1,5}\d{2,})(?:\D|$)", str("" if name is None else name))
    return match.group(1).upper() if match else ""


def station_core(name):
    return station_clean(name)


def station_key(name):
    return station_code(name) or station_core(name)


def station_match(left, right):
    left_code, right_code = station_code(left), station_code(right)
    if left_code and right_code:
        return left_code == right_code
    left_core, right_core = station_core(left), station_core(right)
    return bool(left_core) and left_core == right_core