"""规格驱动的命令注册：读取 spec/apis.json，动态生成 click 命令树。

- 每个分类生成一个命令组（org / device / ztna ...）
- 每个 API 生成一个子命令，顶层参数映射为 --option
- 数组类型选项可重复传递；object/嵌套结构通过 --data 传 JSON 覆盖/补充
- 通用选项：--data、--all（自动翻页）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import click

SPEC_FILE = Path(__file__).parent / "spec" / "apis.json"

# 规格类型 -> (click 类型, 是否多值)
_TYPE_MAP = {
    "string": (str, False),
    "integer": (int, False),
    "int": (int, False),
    "interger": (int, False),   # 文档中的拼写错误原样兼容
    "boolean": (bool, False),
    "bool": (bool, False),
    "number": (float, False),
    "string[]": (str, True),
    "integer[]": (int, True),
    "int[]": (int, True),
}


def load_spec() -> dict:
    with open(SPEC_FILE, encoding="utf-8") as f:
        return json.load(f)


def _read_data_arg(raw: str) -> Dict[str, Any]:
    """解析 --data：内联 JSON、@文件 或 @-（stdin）。"""
    if raw == "@-":
        raw = sys.stdin.read()
    elif raw.startswith("@"):
        raw = Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError as e:
        raise click.UsageError(f"--data 不是合法 JSON: {e}")
    if not isinstance(value, dict):
        raise click.UsageError("--data 必须是 JSON 对象")
    return value


def _opt_name(param_name: str) -> str:
    return "--" + param_name.replace("_", "-")


def _build_callback(api: dict):
    """生成子命令回调：组装 query/body 并发起请求。"""
    method = api["method"].upper()
    path = api["path"]
    top_params = [p for p in api["params"] if p["level"] == 0]

    def callback(**kwargs):
        ctx = click.get_current_context()
        state = ctx.obj  # main.py 注入的运行时状态
        data_arg = kwargs.pop("data", None)
        fetch_all = kwargs.pop("all", False)

        payload: Dict[str, Any] = {}
        for p in top_params:
            key = p["name"].replace("-", "_")
            if key not in kwargs:
                continue
            value = kwargs.pop(key)
            if value is None or value == ():
                continue
            if isinstance(value, tuple):
                value = list(value)
            if p["type"] in ("object", "object[]", "string[][]") and isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError as e:
                    raise click.UsageError(f"{_opt_name(p['name'])} 需要 JSON: {e}")
            payload[p["name"]] = value
        if data_arg:
            payload.update(_read_data_arg(data_arg))

        query = payload if method == "GET" else None
        body = payload if method != "GET" else None

        client = state.make_client()
        try:
            if fetch_all:
                result = client.request_all(method, path, query=query, body=body)
            else:
                result = client.request(method, path, query=query, body=body)
        finally:
            client.close()
        state.render(result)

    return callback


def _attach_params(cmd: click.Command, api: dict) -> None:
    top_params = [p for p in api["params"] if p["level"] == 0]
    has_pagination = {"offset", "limit"} <= {p["name"] for p in top_params}

    for p in reversed(top_params):
        ptype, multiple = _TYPE_MAP.get(p["type"], (str, False))
        desc = p["desc"] or ""
        if p["type"] in ("object", "object[]", "string[][]", "string|string[]"):
            ptype, multiple = str, False
            desc += "（传 JSON 字符串）"
        elif multiple:
            desc += "（可重复传递）"
        if p["type"] == "binary":
            ptype, multiple = str, False
            desc += "（文件路径，暂需配合 --data 使用）"
        cmd.params.append(click.Option(
            [_opt_name(p["name"])],
            type=ptype if ptype is not bool else None,
            is_flag=False,
            multiple=multiple,
            required=False,   # 必填交给服务端校验，便于配合 --data 使用
            default=None,
            help=("[必填] " if p["required"] else "") + desc,
        ))

    cmd.params.append(click.Option(
        ["--data"], default=None,
        help="额外/嵌套参数，JSON 对象：'{...}'、@file.json 或 @-（stdin），与命令行选项合并（同名覆盖）"))
    if has_pagination:
        cmd.params.append(click.Option(
            ["--all"], is_flag=True, default=False,
            help="自动翻页拉取全部数据（offset/limit 分页）"))


def _build_help(api: dict) -> str:
    lines = [f"{api['name_cn']}", ""]
    if api.get("desc"):
        lines.append(api["desc"])
        lines.append("")
    lines.append(f"{api['method']} {api['path']}")
    if api.get("deprecated"):
        lines.append("")
        lines.append("[已废弃] 官方文档标记该接口废弃，请优先使用替代接口。")
    nested = [p for p in api["params"] if p["level"] > 0]
    if nested:
        lines.append("")
        lines.append("嵌套字段（通过 --data 传入）:")
        for p in nested[:40]:
            indent = "  " * p["level"]
            req = "必填 " if p["required"] else ""
            lines.append(f"{indent}{p['name']} ({p['type']}) {req}{p['desc']}")
    if api.get("request_example"):
        lines.append("")
        lines.append("\b\n官方请求示例:")
        lines.append("\b\n" + api["request_example"])
    return "\n".join(lines)


def register_commands(cli: click.Group) -> None:
    spec = load_spec()
    groups: Dict[str, click.Group] = {}
    for cat in spec["categories"]:
        grp = click.Group(name=cat["slug"], help=f"{cat['cn']} 相关接口")
        groups[cat["slug"]] = grp
        cli.add_command(grp)

    for api in spec["apis"]:
        cmd = click.Command(
            name=api["name"],
            callback=_build_callback(api),
            help=_build_help(api),
            short_help=api["name_cn"] + ("（废弃）" if api.get("deprecated") else ""),
        )
        _attach_params(cmd, api)
        groups[api["category"]].add_command(cmd)


def find_api(spec: dict, category: str, name: str) -> dict:
    for api in spec["apis"]:
        if api["category"] == category and api["name"] == name:
            return api
    raise KeyError(f"{category}/{name}")
