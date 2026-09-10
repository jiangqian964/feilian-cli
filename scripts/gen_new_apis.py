#!/usr/bin/env python3
"""将抓取的飞连新接口合并进 apis.json（规格驱动）。

输入：/tmp/feilian_new_apis/true_new_items.json（path/method/desc/params/title）
输出：更新 src/feilian_cli/spec/apis.json
"""
import json
import re
from collections import Counter

SPEC = "/Users/bytedance/feilian-cli/src/feilian_cli/spec/apis.json"
SRC = "/tmp/feilian_new_apis/true_new_items.json"

CATEGORY_CN = {
    "auth": "身份认证", "org": "组织架构", "app": "应用管理", "device": "终端管理",
    "software": "软件管理", "repo": "软件库", "mdm": "MDM管控", "security": "终端安全",
    "control": "终端管控", "nac": "网络准入", "ztna": "零信任接入", "approval": "审批",
    "admin": "管理员", "it": "IT管理", "system": "系统配置", "msg": "消息网关",
    "swg": "安全 Web 网关", "dynamic": "动态控制",
}


def category_of(path: str) -> str:
    if "/ztna/" in path or "/vpn/" in path:
        return "ztna"
    if "/swg/" in path:
        return "swg"
    if "/user/" in path or "/department/" in path or "/role/" in path:
        return "org"
    if "/device/" in path:
        return "device"
    if "/software/" in path:
        return "software"
    if "/dlp/" in path:
        return "security"
    if "/wifi/" in path:
        return "nac"
    if "/admin/" in path:
        return "admin"
    if "/addr/" in path or "/resource/" in path or "/network_area/" in path or "/config/" in path:
        return "system"
    return "system"


def make_name(path: str) -> str:
    """path → name：去 /api/open/v{n}/ 前缀及分类段，/→-，下划线→横线，v2 追加 -v2。

    分类段前缀与现有命名风格一致：
    - ztna/swg/device/software 分类：path 含分类段，去之（如 swg/url_filtering/... → url-filtering-...）
    - 其余（org/nac/security/system/admin）保留 path 原段。
    """
    p = re.sub(r"^/api/open/v\d+/", "", path)
    for seg in ("ztna/", "swg/", "device/", "software/"):
        if p.startswith(seg):
            p = p[len(seg):]
            break
    name = p.replace("/", "-").replace("_", "-")
    if re.search(r"^/api/open/v2/", path):
        name += "-v2"
    return name


def main() -> None:
    data = json.load(open(SPEC))
    new_items = json.load(open(SRC))
    existing_names = {a["name"] for a in data["apis"]}
    existing_paths = {a["path"] for a in data["apis"]}

    added = []
    skipped = []
    for title, item in new_items.items():
        path = item["path"].strip()
        if path in existing_paths:
            skipped.append((title, "path exists"))
            continue
        cat = category_of(path)
        name = make_name(path)
        if name in existing_names:
            # 冲突则加路径尾段消歧
            name = make_name(path).replace("-", "-", 0)  # no-op 占位
        params = []
        for p in item.get("params", []):
            if p.get("in") == "header":
                continue
            if p["name"].startswith("∟"):
                # 嵌套字段（body 子对象）不暴露为 CLI 顶层选项
                continue
            params.append({
                "name": p["name"],
                "type": p.get("type", "string"),
                "required": p.get("required") == "是",
                "desc": (p.get("desc") or "").strip(),
                "in": p.get("in", "query"),
                "level": 0,
            })
        entry = {
            "category": cat,
            "category_cn": CATEGORY_CN.get(cat, cat),
            "name": name,
            "name_cn": title,
            "path": path,
            "method": item["method"],
            "desc": (item.get("desc") or "").strip(),
            "params": params,
        }
        added.append(entry)
        existing_names.add(name)
        existing_paths.add(path)

    data["apis"].extend(added)
    data["version"] = "2026-09-10T00:00:00.000Z"
    json.dump(data, open(SPEC, "w"), ensure_ascii=False, indent=1)

    print(f"新增 {len(added)} 个接口，跳过 {len(skipped)} 个")
    for e in added:
        print(f"  [{e['category']}] {e['name']} | {e['method']} {e['path']}")
    if skipped:
        print("跳过:")
        for t, why in skipped:
            print("  -", t, why)
    # 分类统计
    c = Counter(e["category"] for e in added)
    print("新增分类统计:", dict(c))


if __name__ == "__main__":
    main()
