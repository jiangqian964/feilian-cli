"""SN 去重计划生成逻辑的单元测试：保留/删除选择规则。"""
from feilian_cli.dedup import collect_duplicates


def _dev(did, sn, status, updated):
    return {
        "did": did,
        "device_status": status,
        "updated_time": updated,
        "device_name": "dev",
        "os": "windows",
        "device_info": {"serial_number": sn},
    }


def test_keep_most_recent_activity():
    devs = [
        _dev("a", "SN1", 2, 1000),
        _dev("b", "SN1", 2, 2000),   # 同状态，更新更晚 -> 保留
        _dev("c", "SN1", 0, 3000),   # 失效，即使更新晚也排后
    ]
    plan = collect_duplicates(devs)
    assert plan["SN1"]["keep"]["did"] == "b"
    assert [d["did"] for d in plan["SN1"]["delete"]] == ["a", "c"]


def test_active_beats_sleeping():
    devs = [
        _dev("a", "SN2", 1, 1000),   # 活跃 -> 保留（即使更新更早）
        _dev("b", "SN2", 2, 9999),
    ]
    plan = collect_duplicates(devs)
    assert plan["SN2"]["keep"]["did"] == "a"


def test_single_did_not_duplicate():
    assert collect_duplicates([_dev("a", "SN3", 1, 1000)]) == {}


def test_missing_sn_skipped():
    assert collect_duplicates([{"did": "a", "device_info": {}}]) == {}


def test_sn_filter_limits_scope():
    devs = [
        _dev("a", "SN4", 2, 1000),
        _dev("b", "SN4", 2, 2000),
        _dev("c", "SN5", 2, 1000),
        _dev("d", "SN5", 2, 2000),
    ]
    plan = collect_duplicates(devs, sn_filter=["SN4"])
    assert set(plan) == {"SN4"}
