"""SN 去重工作流命令：同一序列号存在多个 did 时，保留最近活跃的一台，其余置失效并清理。

工作流（两步，均为开放平台原生接口）：
1. POST /api/open/v1/device/batch/status/update  将待删除设备置为失效（status=0）
2. POST /api/open/v1/device/batch/invalid/delete 清理失效设备及其关联数据（clean_range=[0]）

安全设计：默认只打印计划，必须显式 --yes 才执行；--dry-run 仅预览。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import click

from .client import FeilianClient

STATUS_CN = {0: "失效", 1: "活跃", 2: "休眠"}
# 活跃度权重：活跃 > 休眠 > 失效；同状态按最近在线时间（updated_time）降序
_STATUS_ORDER = {1: 0, 2: 1, 0: 2}


def _ts(ts: Any) -> str:
    """Unix 时间戳转可读时间；空值显示 -。"""
    if not ts:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return str(ts)


def _activity_key(dev: dict) -> tuple:
    status = dev.get("device_status")
    order = _STATUS_ORDER.get(status, 3)
    return (order, -(dev.get("updated_time") or 0))


def collect_duplicates(devices: List[dict],
                       sn_filter: Optional[List[str]] = None) -> Dict[str, dict]:
    """按 SN 分组，返回 {sn: {"keep": dev, "delete": [dev, ...]}}。

    同一 SN 出现多个不同 did 才视为重复；无 SN 的设备跳过。
    """
    groups: Dict[str, List[dict]] = {}
    for dev in devices:
        sn = ((dev.get("device_info") or {}).get("serial_number") or "").strip()
        if not sn:
            continue
        if sn_filter and sn not in sn_filter:
            continue
        groups.setdefault(sn, []).append(dev)

    plan: Dict[str, dict] = {}
    for sn, devs in groups.items():
        if len({d["did"] for d in devs}) <= 1:
            continue
        # 升序取第一个：order 小（活跃优先）在前，同 order 时 -updated 小（即更新晚）在前
        ordered = sorted(devs, key=_activity_key)
        plan[sn] = {"keep": ordered[0], "delete": ordered[1:]}
    return plan


def _short(did: str, n: int = 16) -> str:
    return did[:n] + "…" if len(did) > n else did


def _print_plan(plan: Dict[str, dict]) -> None:
    total_del = sum(len(v["delete"]) for v in plan.values())
    click.echo(f"发现 {len(plan)} 组 SN 重复设备，将保留 {len(plan)} 台、删除 {total_del} 台：\n")
    for sn, item in plan.items():
        keep = item["keep"]
        keep_line = (f"  保留 {_short(keep['did'])} | {keep.get('device_name','')} | "
                     f"{keep.get('os','')} | 状态={STATUS_CN.get(keep.get('device_status'), '?')} | "
                     f"最近在线={_ts(keep.get('updated_time'))}")
        click.echo(f"[SN] {sn}")
        click.echo(keep_line)
        for dev in item["delete"]:
            click.echo(f"  删除 {_short(dev['did'])} | {dev.get('device_name','')} | "
                       f"{dev.get('os','')} | 状态={STATUS_CN.get(dev.get('device_status'), '?')} | "
                       f"最近在线={_ts(dev.get('updated_time'))}")
        click.echo("")


def _do_dedup(client: FeilianClient, plan: Dict[str, dict]) -> Dict[str, Any]:
    """执行去重：每组先批量置失效，再批量清理。返回汇总。"""
    summary: Dict[str, Any] = {"groups": 0, "deleted": 0, "results": []}
    for sn, item in plan.items():
        dids = [d["did"] for d in item["delete"]]
        if not dids:
            continue
        # 第一步：置为失效
        try:
            client.request("POST", "/api/open/v1/device/batch/status/update",
                           body={"dids": dids, "status": 0})
            step1 = "ok"
        except Exception as e:  # noqa: BLE001 - 逐组报告，不中断整体
            step1 = f"failed: {e}"
        # 第二步：清理失效设备
        try:
            resp = client.request("POST", "/api/open/v1/device/batch/invalid/delete",
                                  body={"dids": dids, "clean_range": [0]})
            if isinstance(resp, dict):
                ok = (resp.get("success") or {}).get("device_ids") or []
                step2 = f"ok，删除 {len(ok)} 台，清理分组关联 {resp.get('clean_group_members', 0)} 条"
            else:
                step2 = f"ok: {resp}"
        except Exception as e:  # noqa: BLE001
            step2 = f"failed: {e}"
        summary["groups"] += 1
        summary["deleted"] += len(dids)
        summary["results"].append({"sn": sn, "deleted_dids": dids,
                                   "status_update": step1, "invalid_delete": step2})
        click.echo(f"[SN] {sn}: 置失效={step1}，清理={step2}")
    return summary


@click.command("device-dedup")
@click.option("--sn", multiple=True, metavar="SN",
              help="只处理指定序列号（可重复，默认处理全部）")
@click.option("--dry-run", is_flag=True, help="仅预览保留/删除计划，不执行")
@click.option("--yes", is_flag=True, help="跳过确认直接执行（删除不可逆）")
@click.pass_obj
def dedup_command(state, sn, dry_run, yes):
    """同一 SN 多 did 去重：保留最近活跃设备，其余置失效并清理。

    规则：按设备状态（活跃 > 休眠 > 失效）与最近在线时间排序，每组保留 1 台。
    调用 status-batch-update（置失效）与 invalid-batch-delete（清理）两步接口。
    """
    sn_filter = list(sn) or None
    client = state.make_client()
    try:
        data = client.request_all("GET", "/api/open/v1/device/search",
                                  query={"status": "0,1,2"})
    finally:
        client.close()

    devices = data.get("devices", []) if isinstance(data, dict) else []
    plan = collect_duplicates(devices, sn_filter)
    if not plan:
        click.echo("未发现 SN 相同的重复设备" + (f"（SN={sn_filter}）" if sn_filter else ""))
        return

    _print_plan(plan)
    if dry_run:
        click.echo("预览模式：未执行任何删除（去掉 --dry-run 后使用 --yes 执行）")
        return
    if not yes:
        click.echo("未执行：删除不可逆，确认请追加 --yes（仅预览请用 --dry-run）")
        return

    click.echo("开始执行：")
    summary = _do_dedup(client, plan)
    click.echo(f"\n完成：处理 {summary['groups']} 组，共删除 {summary['deleted']} 台设备")
