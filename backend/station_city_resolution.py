"""Resolve report cities from a task directory snapshot and retained manual mappings."""
import copy


def read_directory(expected_version=None):
    from lanorange_approval_client import OfficialApprovalClient
    from lanorange_price_options import load_directory
    from lanorange_approvals import current_version
    from platform_auth_control import operation
    with operation('lanorange'):
        before = current_version()
        if expected_version is not None and before != expected_version:
            raise ValueError('来源采集后账号变化，未套用另一账号的目录')
        with OfficialApprovalClient() as api:
            result = load_directory(api)
        if before != current_version():
            raise ValueError('目录读取期间账号变化')
        return copy.deepcopy(result)


def resolver(directory, overrides):
    candidates = {}
    for station in directory.get('stations', []):
        candidates.setdefault(station['name'].strip(), set()).add(station['city'])
    issues = {}

    def resolve(team):
        team = str(team or '').strip()
        manual = overrides.get(team, '')
        cities = candidates.get(team, set())
        if manual:
            if cities and cities != {manual}:
                issues[team] = (team, manual, '、'.join(sorted(cities)), '保留人工配置；后台归属不同，请核对')
            return manual
        if len(cities) == 1:
            return next(iter(cities))
        issues[team] = (team, '', '、'.join(sorted(cities)), '同名站点跨城市，待核对' if cities else '目录未匹配，待核对')
        return ''

    return resolve, issues
