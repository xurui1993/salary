"""Global city -> payment binding platform overrides.

The automatic rule is "city in Benlai signing cities -> 本来人力, otherwise
商翼".  Signing-city exports are not stable enough for that decision, so users
can pin a platform per city.  Only explicit overrides are stored; omitted
cities keep the automatic rule.
"""
import json
from pathlib import Path

from fengshen_bill import atomic_json

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / 'data' / 'binding_platforms.json'
PLATFORMS = ('本来人力', '商翼')
MAX_CITIES = 500


def normalized(platforms):
    if not isinstance(platforms, dict) or len(platforms) > MAX_CITIES:
        raise ValueError('绑定平台配置无效')
    result = {}
    for city, platform in platforms.items():
        if not isinstance(city, str) or not city.strip() or len(city.strip()) > 40:
            raise ValueError('绑定平台配置包含无效城市')
        value = str(platform or '').strip()
        if value == '天津商翼':
            value = '商翼'
        if value not in PLATFORMS:
            raise ValueError('绑定平台只能选择本来人力或天津商翼')
        result[city.strip()] = value
    return result


def load():
    try:
        payload = json.loads(PATH.read_text(encoding='utf-8'))
        values = payload.get('platforms') if isinstance(payload, dict) else payload
        return normalized(values)
    except (OSError, ValueError, TypeError):
        return {}


def save(platforms):
    value = normalized(platforms)
    atomic_json(PATH, {'platforms': value})
    return value


def for_cities(platforms, cities):
    selected = set(cities or ())
    return {city: platform for city, platform in (platforms or {}).items() if city in selected}