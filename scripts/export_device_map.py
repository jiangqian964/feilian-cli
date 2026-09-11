#!/usr/bin/env python3
"""导出飞连在线设备清单：SN / MAC / 计算机名 / 登录员工邮箱 → CSV。

用法:
  python3 export_device_map.py [--status 1] [--client-os windows]
                               [--input <search 结果 json>] [--out device_map.csv]

依赖: feilian-cli 已安装且配置 AK/SK（默认路径 ~/feilian-cli/.venv/bin/feilian，
可用环境变量 FEILIAN_BIN 覆盖）；python3 >= 3.9。
"""
import argparse
import csv
import json
import os
import subprocess
import sys

FEILIAN = os.environ.get("FEILIAN_BIN", os.path.expanduser("~/feilian-cli/.venv/bin/feilian"))


def run_feilian(*args):
    r = subprocess.run([FEILIAN, *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"feilian {' '.join(args)} 失败: {r.stderr[:400]}")
    return r.stdout


def get_user_email(user_id, cache):
    if user_id in cache:
        return cache[user_id]
    try:
        data = json.loads(run_feilian("org", "user-get", "--id", user_id))
        email = (data.get("email") or "").strip()
    except Exception as e:
        print(f"  ! user-get {user_id} 失败({e})，email 置空")
        email = ""
    cache[user_id] = email
    return email


def main():
    ap = argparse.ArgumentParser(description="导出飞连在线设备清单 CSV")
    ap.add_argument("--status", default="1", help="设备状态，0/1/2 或多值逗号分隔，默认 1（活跃）")
    ap.add_argument("--client-os", default="windows", help="客户端操作系统，默认 windows")
    ap.add_argument("--input", help="复用已保存的 device search 结果 JSON（跳过拉取）")
    ap.add_argument("--out", default="device_map.csv", help="输出 CSV 路径")
    args = ap.parse_args()

    if args.input:
        data = json.load(open(args.input))
    else:
        raw = run_feilian(
            "device", "search", "--status", args.status,
            "--client-os", args.client_os, "--limit", "200", "--all",
        )
        data = json.loads(raw)

    devices = data.get("devices", [])
    print(f"设备数（count={data.get('count')}，实际取到 {len(devices)}）")
    if data.get("count") != len(devices):
        print(f"  ! 注意：count={data.get('count')} 与实取 {len(devices)} 不一致，请检查分页")

    cache = {}
    rows = []
    for i, dev in enumerate(devices, 1):
        info = dev.get("device_info") or {}
        macs = []
        for nic in info.get("nic_detail_list") or []:
            m = (nic.get("mac_addr") or "").strip()
            if m and m not in macs:
                macs.append(m)
        uid = dev.get("user_id") or ""
        print(f"  [{i}/{len(devices)}] {dev.get('device_name','')} 取邮箱 {uid} ...", end=" ", flush=True)
        email = get_user_email(uid, cache)
        print("OK" if email else "（空）")
        rows.append({
            "did": dev.get("did", ""),
            "serial_number": (info.get("serial_number") or "").strip(),
            "mac_addrs": ";".join(macs),
            "device_name": (dev.get("device_name") or "").strip(),
            "user_id": uid,
            "email": email,
        })

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["did", "serial_number", "mac_addrs", "device_name", "user_id", "email"])
        w.writeheader()
        w.writerows(rows)

    empty = sum(1 for r in rows if not r["email"])
    print(f"\n已导出 {len(rows)} 行 → {args.out}；邮箱为空 {empty} 台")


if __name__ == "__main__":
    main()
