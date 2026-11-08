"""Daily price lookup with identity-first matching and unique-name fallback."""

from decimal import Decimal, InvalidOperation


def _price_number(value):
    try:
        number = Decimal(str(value).strip())
        return number if number.is_finite() and number != 0 else None
    except (InvalidOperation, ValueError):
        return None


def price_rider_column(columns):
    labels = [str(column).strip().lower() for column in columns]
    for i, label in enumerate(labels):
        if "风神骑手id" in label:
            return i
    for i, label in enumerate(labels):
        if label in ("骑手id", "员工id"):
            return i
    return next((i for i, label in enumerate(labels)
                 if ("id" in label or "编号" in label) and ("骑手" in label or "员工" in label)), None)


def record_daily_name(groups, date, station, name, rider_id):
    site = str(station).replace(' ', '').replace('\u3000', '').replace('\xa0', '').replace('\n', '').replace('\t', '').strip()
    key = (date, site, str(name).strip())
    groups.setdefault(key, set()).add(str(rider_id).replace('.0', '').strip())


class UniqueNamePrices:
    def __init__(self):
        self.prices = {}
        self.identities = {}
        self.sequence = 0

    def add(self, key, value, identity=None):
        self.sequence += 1
        identities = self.identities.setdefault(key, set())
        identities.add(identity if identity is not None else ("unknown_row", self.sequence))
        number = _price_number(value)
        if number is None:
            return
        if key not in self.prices:
            self.prices[key] = value
        elif _price_number(self.prices[key]) != number:
            self.prices[key] = None

    def get(self, key):
        if len(self.identities.get(key, ())) != 1:
            return None
        return self.prices.get(key)


def match_daily_price(date, station, rider_id, name, idcards, by_id, by_idcard, by_name,
                      alternate_station=None, prefer_idcard=False, name_is_unique=True):
    stations = [(station, "")]
    if alternate_station and alternate_station != station:
        stations.append((alternate_station, "(关键字)"))
    cards = list(dict.fromkeys(str(card).strip().upper() for card in idcards if card))
    kinds = ("card", "id") if prefer_idcard else ("id", "card")
    for kind in (*kinds, "name"):
        if kind == "name" and not name_is_unique:
            continue
        candidates = cards if kind == "card" else [rider_id if kind == "id" else name]
        mapping = by_idcard if kind == "card" else by_id if kind == "id" else by_name
        label = {"id": "风神骑手ID", "card": "身份证", "name": "骑手姓名"}[kind]
        for candidate in candidates:
            if not candidate:
                continue
            for site, suffix in stations:
                value = mapping.get(f"{date}_{site}_{candidate}")
                if _price_number(value) is not None:
                    return value, f"【日期 + 站点名称 + {label}{suffix}】", candidate if kind == "card" else ""
    return None, "", ""
