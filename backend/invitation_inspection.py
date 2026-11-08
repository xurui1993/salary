"""只读查看邀请记录接口的完整字段结构；仅查询第一页，不提交任何导出。"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fengshen_auth import SessionVault
from fengshen_bill import PROJECT_ROOT, atomic_json
from fengshen_http import AGENCIES_URL, TEAMS_URL, FengshenHttpClient
from fengshen_merchant_exports import merchant_teams, number
from fengshen_merchant_protocol import INVITE_AUTH, INVITE_TEAMS, INVITE_QUERY


def shape(value):
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(item) for item in value[:3]]
    return type(value).__name__


def gift_sample(value):
    if not isinstance(value, list):
        return shape(value)
    return value[:3]


def main():
    state = SessionVault().load()
    if state is None:
        raise SystemExit("请先在薪酬系统完成风神登录")
    run = PROJECT_ROOT / "outputs" / "invitation_inspection" / uuid.uuid4().hex
    run.mkdir(parents=True)
    client = FengshenHttpClient(state)
    report = {}
    try:
        agencies = client.request_json("GET", AGENCIES_URL).get("data") or []
        cities = [(str(row.get("agencyName") or ""), str(row.get("agencyId"))) for row in agencies]
        current_id = str(client.identity().get("agencyId"))
        cities.sort(key=lambda item: item[1] != current_id)
        print("可访问城市数:", len(cities), "| 当前城市:", current_id)
        for name, aid in cities:
            entry = {"city": name}
            try:
                client.select_city(aid)
                client.request_json("GET", INVITE_AUTH)
                teams = client.request_json("GET", INVITE_TEAMS).get("data")
                if not isinstance(teams, list) or not teams:
                    report[aid] = {**entry, "note": "无可邀请站点"}
                    continue
                visible_ids = [number(row["id"]) for row in teams]
                current = merchant_teams(client.request_json("POST", TEAMS_URL, body={}), aid)
                ids = [key for key in visible_ids if key in current]
                entry["stations"] = len(ids)
                if not ids:
                    report[aid] = {**entry, "note": "无归属当前商家的站点"}
                    continue
                params = {"activityType": 26, "stationIds": json.dumps([int(v) for v in ids],
                                                                      separators=(",", ":")), "pageSize": 20}
                data = client.request_json("GET", INVITE_QUERY, params={**params, "pageNum": 1}).get("data")
                records = data.get("value") if isinstance(data, dict) else None
                entry["total"] = data.get("totalItems") if isinstance(data, dict) else None
                if isinstance(records, list) and records:
                    union = {}
                    for record in records:
                        if isinstance(record, dict):
                            union.update(shape(record))
                    entry["record_fields"] = union
                    entry["gift_sample"] = gift_sample(records[0].get("itemVOList"))
                    entry["sample_keys_values"] = {
                        key: (value if isinstance(value, (int, float, bool)) or value is None else
                              ("文本" if isinstance(value, str) else shape(value)))
                        for key, value in records[0].items()
                    }
                report[aid] = entry
                print(f"{name}({aid}): total={entry['total']} stations={entry['stations']}"
                      f" fields={len(entry.get('record_fields') or {})}")
                if entry.get("record_fields"):
                    print("  字段:", list(entry["record_fields"].keys()))
                    atomic_json(run / "capture.json", {"report": report})
                    break
            except Exception as error:
                report[aid] = {**entry, "error": str(error)[:160]}
                print(f"{name}({aid}): error {str(error)[:100]}")
    finally:
        client.close()
    atomic_json(run / "capture.json", {"report": report})
    print("saved:", run)


if __name__ == "__main__":
    main()