#!/usr/bin/env python3
"""导出飞连软件库全部软件 + 每个软件的安装终端 → 两个 CSV。

用法:
  python3 export_software_map.py [--out-dir <目录>]
                                 [--input-goods goods.json] [--input-stats stats.json]

依赖: feilian-cli 已安装且配置 AK/SK（默认路径 ~/feilian-cli/.venv/bin/feilian，
可用环境变量 FEILIAN_BIN 覆盖）；python3 >= 3.9。
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import time
from collections import defaultdict

FEILIAN = os.environ.get("FEILIAN_BIN", os.path.expanduser("~/feilian-cli/.venv/bin/feilian"))


def run_feilian(*args, retries=2):
    for attempt in range(retries + 1):
        r = subprocess.run([FEILIAN, *args], capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            return json.loads(r.stdout)
        if attempt < retries:
            time.sleep(2)
    raise RuntimeError(f"feilian {' '.join(args)} 失败: {r.stderr[:400]}")


def main():
    ap = argparse.ArgumentParser(description="导出软件库清单 + 软件×终端安装映射 CSV")
    ap.add_argument("--out-dir", default=".", help="输出目录，默认当前目录")
    ap.add_argument("--input-goods", help="复用已保存的 appstore-goods-list 结果 JSON")
    ap.add_argument("--input-stats", help="复用已保存的 stat-list 结果 JSON")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # 1. 软件库
    if args.input_goods:
        goods = json.load(open(args.input_goods)).get("items", [])
    else:
        goods = run_feilian("repo", "appstore-goods-list", "--all").get("items", [])
    print(f"软件库软件: {len(goods)} 个")

    # 2. 软件统计全量
    if args.input_stats:
        stats = json.load(open(args.input_stats)).get("items", [])
    else:
        stats = run_feilian("software", "stat-list", "--limit", "200", "--all").get("items", [])
    print(f"软件统计条目: {len(stats)} 条")

    by_name = defaultdict(list)
    for s in stats:
        by_name[(s.get("software_name") or "").lower()].append(s)

    # 3. 匹配 + 逐 sid 拉终端
    lib_rows, install_rows, unresolved, warnings = [], [], [], []
    for g in goods:
        gname = (g.get("name") or "").strip()
        lib_rows.append({"goods_id": g.get("id"), "name": gname, "category": g.get("category") or ""})
        cands = by_name.get(gname.lower(), [])
        if not cands:
            unresolved.append(gname)
            continue
        seen = {}
        for s in cands:
            if int(s.get("installed_num") or 0) <= 0:
                continue
            try:
                det = run_feilian("software", "stat-detail", "--sid", str(s["id"]), "--limit", "200", "--all")
            except Exception as e:
                warnings.append(f"{gname} sid={s['id']}: {e}")
                continue
            for dev in det.get("devices", []):
                t = dev.get("installed_time") or 0
                ts = datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else ""
                seen[(dev.get("did"), dev.get("version") or "")] = {
                    "software_name": gname,
                    "device_name": (dev.get("device_name") or "").strip(),
                    "serial_number": (dev.get("serial_number") or "").strip(),
                    "version": dev.get("version") or "",
                    "user_id": dev.get("user") or "",
                    "installed_time": ts,
                    "did": dev.get("did") or "",
                }
            print(f"  {gname}: {len(cands)} 个 sid，安装终端 {len(seen)} 台")
        install_rows.extend(seen.values())

    # 4. 写 CSV
    lib_path = os.path.join(args.out_dir, "software_library.csv")
    with open(lib_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["goods_id", "name", "category"])
        w.writeheader()
        w.writerows(lib_rows)

    map_path = os.path.join(args.out_dir, "software_install_map.csv")
    with open(map_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["software_name", "device_name", "serial_number", "version", "user_id", "installed_time", "did"])
        w.writeheader()
        w.writerows(install_rows)

    print(f"\n软件库清单 {len(lib_rows)} 行 → {lib_path}")
    print(f"软件×终端映射 {len(install_rows)} 行 → {map_path}")
    print(f"匹配到统计的软件 {len(lib_rows) - len(unresolved)} 个；未匹配: {unresolved}")
    if warnings:
        print(f"警告（跳过 {len(warnings)} 个 sid 调用）:")
        for w in warnings:
            print("  -", w)


if __name__ == "__main__":
    main()
