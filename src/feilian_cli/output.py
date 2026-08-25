"""输出格式化：json（默认）/ table / raw。"""
from __future__ import annotations

import json
import sys
from typing import Any


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def print_raw(data: Any) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str))
    else:
        print(data if data is not None else "")


def _find_rows(data: Any):
    """定位可制表的行列表：data 本身是 list，或 data 中第一个 list 字段。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return None


def print_table(data: Any) -> None:
    rows = _find_rows(data)
    if not rows or not all(isinstance(r, dict) for r in rows):
        # 无法制表时退回 json
        print_json(data)
        return

    from rich.console import Console
    from rich.table import Table

    # 列取所有行 key 的并集（保持首行顺序优先）
    columns = list(rows[0].keys())
    for r in rows[1:]:
        for k in r.keys():
            if k not in columns:
                columns.append(k)

    table = Table(show_lines=False, header_style="bold")
    for c in columns:
        table.add_column(str(c), overflow="fold")
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            cells.append("" if v is None else str(v))
        table.add_row(*cells)
    Console().print(table)

    if isinstance(data, dict):
        extras = {k: v for k, v in data.items() if not isinstance(v, list)}
        if extras:
            print(json.dumps(extras, ensure_ascii=False), file=sys.stderr)


def render(data: Any, fmt: str) -> None:
    if fmt == "table":
        print_table(data)
    elif fmt == "raw":
        print_raw(data)
    else:
        print_json(data)
