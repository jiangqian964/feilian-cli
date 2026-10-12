#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DLP 告警日志误报巡检脚本
========================
通过飞连开放平台「获取数据防泄漏告警日志」接口
（GET /api/open/v1/security/edlp/events/list）周期性拉取 DLP 告警，
按「文件路径 / 文件名 / 文件格式」等特征识别明显误报
（如微信本地库、数据库引擎文件、浏览器缓存、系统目录内部文件等 DLP 无需关注的对象），
生成 Markdown 摘要报告 + 结构化 JSON，写入本地 reports/ 目录。

用法:
    python scripts/dlp_false_positive.py --days 1 --output-dir reports --profile default
    python scripts/dlp_false_positive.py --days 7            # 拉最近 7 天

依赖: 项目内 feilian_cli（FeilianClient / config.load_profile），复用已有鉴权配置。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 项目根目录（本文件位于 <root>/scripts/ 下）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from feilian_cli.client import FeilianClient, ApiError          # noqa: E402
from feilian_cli.config import load_profile, ConfigError        # noqa: E402

EVENTS_PATH = "/api/open/v1/security/edlp/events/list"
PAGE_SIZE = 200

# ---------------------------------------------------------------------------
# 误报规则库
# ---------------------------------------------------------------------------
# 每条规则: id / category(类别) / priority(high=明显误报, suspect=可疑待人工) /
#           reason(命中说明) / match(event) -> bool
# 判定仅基于文件路径、文件名、文件格式（含外发途径应用名），不读取文件内容。

def _p(ev: Dict[str, Any]) -> str:
    """归一化文件路径（小写、统一分隔符），file_info 缺失时返回空串。"""
    fi = ev.get("file_info") or {}
    path = (fi.get("path") or "").lower().replace("\\", "/")
    return path


def _n(ev: Dict[str, Any]) -> str:
    """归一化文件名（小写）。"""
    fi = ev.get("file_info") or {}
    return (fi.get("name") or "").lower()


def _f(ev: Dict[str, Any]) -> str:
    """文件扩展名（小写，不含点）；file_info 缺失时返回空串。"""
    name = _n(ev)
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[1]


def _s(ev: Dict[str, Any]) -> int:
    """文件大小（Byte），缺省 0。"""
    fi = ev.get("file_info") or {}
    return int(fi.get("size") or 0)


def _app(ev: Dict[str, Any]) -> str:
    """外发途径应用名（小写）。"""
    lw = ev.get("leak_way") or {}
    return (lw.get("app_name") or "").lower()


# 聊天/AI 助手/办公软件【本地数据目录】路径模式（仅匹配文件所在位置，不匹配外发渠道）。
# 注意：文件“通过微信/飞书等渠道外发”属于真实泄漏，不能按应用名判误报；
# 这里只把位于程序安装目录/配置目录/本地消息库/缓存目录的程序内部文件判为误报。
CHAT_APP_PATH_RE = re.compile(
    # 腾讯系（微信/企业微信/QQ/TIM）：安装目录与本地配置
    r"appdata/(roaming|local|low)/tencent/(wechat|wecom|wxwork|qq|tim|nt_qq)(/|$)|"
    r"program files( \(x86\))?/tencent/(wechat|wecom|wxwork|qq|tim)(/|$)|"
    # 微信/企业微信本地消息库与内部子目录（FileStorage 等用户收发文件不判误报）
    r"wechat files/(all users|applet|xplugin)(/|$)|"
    r"wechat files/[^/]+/(msg|config|applet|xplugin|temp|cache)(/|$)|"
    r"wxwork files/[^/]+/(msg|config|applet|xplugin|temp|cache)(/|$)|"
    # 钉钉
    r"appdata/(roaming|local)/dingtalk(/|$)|program files/nail(/|$)|钉钉|aliwork|"
    # 飞书/Lark 本地缓存与数据
    r"appdata/(roaming|local)/feishu(/|$)|library/application support/(feishu|lark)(/|$)|"
    r"feishu/(cache|cachefiles|blob_storage|data|databases)(/|$)|"
    # AI 助手本地数据（豆包等桌面客户端的会话/工作区）
    r"doubao/chats(/|$)|doubao/(chat|workspace|agents|draft|documents)/|"
    # Telegram / Slack / Discord / Zoom 本地数据
    r"telegram desktop/tdata|appdata/(roaming|local)/(slack|discord|zoom)(/|$)|"
    r"library/application support/(slack|discord)(/|$)"
)

# 浏览器本地数据关键词
BROWSER_KEYS = [
    "user data", "mozilla/firefox/profiles", "microsoft/edge", "safari",
    "chromium", "bravesoftware", "opera software",
]
BROWSER_NAMES = [
    "cookies", "history", "login data", "web data", "favicons",
    "local storage", "indexeddb", "gpucache", "code cache", "cachestorage",
    "service worker", "network persistent state", "transportsecurity",
]

# 数据库引擎文件扩展名（SQLite/LevelDB/MySQL/Office 本地库等引擎内部文件）
DB_ENGINE_EXTS = {
    "db", "sqlite", "sqlite3", "sqlitedb", "ldb", "wal", "shm", "manifest",
    "frm", "myd", "myi", "dbf", "mdb", "accdb", "ndb",
}
# 程序二进制/字体/图标等不可读作业务数据的格式
BINARY_EXTS = {
    "dll", "exe", "so", "dylib", "sys", "inf", "mui", "ttf", "otf", "woff",
    "woff2", "ico", "cur", "ani", "evtx", "etl", "pak", "bin",
}
# 文本型配置文件格式（单独命中记为“可疑”，结合系统/应用目录命中升级为明显误报）
CONFIG_EXTS = {"ini", "cfg", "conf", "config", "plist", "reg", "pol", "properties"}
# 临时/缓存/锁文件
TEMP_EXTS = {"tmp", "temp", "part", "crdownload", "download", "partial",
             "lock", "swp", "swx", "lck", "pid", "thumbcache", "dmp"}

# 系统进程（其文件访问不构成用户主动外发）
SYSTEM_PROCESSES = {
    "svchost", "explorer", "finder", "windowserver", "dock", "systemuiserver",
    "coreaudiod", "launchservicesd", "ntoskrnl", "csrss", "lsass", "services",
    "runtimebroker", "searchapp", "taskhostw", "spoolsv", "rundll32",
    "kernel", "sysmond", "configd", "mds", "mds_stores", "mdworker",
}


def classify(ev: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """
    对单条告警做误报判定。

    返回 (verdict, rule_id, category, reason):
      verdict: fp_high(明显误报) / fp_suspect(可疑待人工) / normal(正常告警)
               / no_file(非文件外发，不参与文件类误报判定)
    """
    fi = ev.get("file_info") or {}
    has_file = bool(fi) and bool((fi.get("name") or "").strip() or (fi.get("path") or "").strip())
    if not has_file:
        return "no_file", "no_file", "非文件外发", "无有效 file_info（剪贴板/代码仓库/命令行等外发），不按文件特征判定"
    path, name, ext, size, app = _p(ev), _n(ev), _f(ev), _s(ev), _app(ev)

    # 1) 系统进程触发的文件访问
    if app in SYSTEM_PROCESSES:
        return "fp_high", "system_process", "系统进程", f"外发途径应用为系统进程「{app}」，非用户主动外发"

    # 2) 系统/程序目录内部文件
    # Windows：windows / program files / programdata / 用户 AppData；
    # macOS：根级 /System、/Library 以及 ~/Library 下程序内部子目录
    # （caches/logs/preferences/webkit 等；CloudStorage、Mobile Documents 属用户云盘文件，不判误报）
    if re.search(
        r"(^|/)windows(/|$)|(^|/)program files( \(x86\))?(/|$)|"
        r"(^|/)programdata(/|$)|(^|/)users/[^/]+/appdata(/|$)|"
        r"(^|/)system(/|$)|(^/)library(/|$)|"  # 根 /System 与顶层 /Library
        r"(^|/)usr/(lib|bin|share)(/|$)|(^|/)etc(/|$)|(^|/)var(/|$)|(^|/)opt(/|$)|"
        r"library/(caches|logs|logfiles|preferences|webkit|saved application state|"
        r"launchagents|launchdaemons|keychains|startupitems|frameworks|fonts)(/|$)",
        path,
    ):
        return "fp_high", "system_dir", "系统/程序目录", "文件位于系统或程序安装目录内部"

    # 3) 聊天/AI 助手/办公软件本地数据目录（程序内部文件）
    if CHAT_APP_PATH_RE.search(path):
        return "fp_high", "chat_app_local", "聊天/AI 助手/办公软件本地库", \
            "文件位于聊天/AI 助手/办公软件本地数据目录，属程序内部数据"

    # 4) 浏览器本地数据
    if any(k in path for k in BROWSER_KEYS) or any(
            re.search(rf"(^|/){re.escape(k)}(/|$)|(^|_){re.escape(k)}(_|\.|$)", name)
            for k in BROWSER_NAMES):
        return "fp_high", "browser_local", "浏览器本地数据", "浏览器本地缓存/存储文件，非用户主动外发的文档"

    # 5) 数据库引擎文件
    if ext in DB_ENGINE_EXTS:
        if size <= 5 * 1024 * 1024:  # <=5MB 多为应用本地小型库（配置/缓存库）
            return "fp_high", "db_engine", "数据库引擎文件", \
                f"数据库引擎内部文件（.{ext}，{size}B），非业务数据外发"
        return "fp_suspect", "db_engine_large", "数据库文件(大)", \
            f"数据库文件（.{ext}，{size}B），体积较大，请人工确认是否为有意导出的数据"

    # 6) 开发/构建工具内部产物
    if re.search(
        r"node_modules|__pycache__|(^|/)\.venv(/|$)|(^|/)venv(/|$)|"
        r"\.gradle|\.m2(/|$)|\.npm|\.cargo|\.idea|\.vscode|"
        r"(^|/)pods(/|$)|deriveddata|(^|/)target(/|$)|(^|/)build(/|$)|"
        r"(^|/)\.git(/|$)|__macosx|(^|/)out(/|$)|\.terraform",
        path,
    ):
        return "fp_high", "dev_build", "开发/构建工具内部", "开发/构建工具内部产物目录"

    # 7) 临时/缓存/锁文件
    if ext in TEMP_EXTS or name.startswith("~$") or name in {
            "thumbs.db", ".ds_store", "desktop.ini"} or \
            re.search(r"(^|/)(temp|tmp|cache)(/|$)", path):
        return "fp_high", "temp_cache", "临时/缓存/锁文件", \
            f"临时/缓存/锁文件（.{ext or name}）"

    # 8) 程序二进制/字体/图标
    if ext in BINARY_EXTS:
        return "fp_high", "binary", "程序二进制/字体/图标", \
            f"程序二进制或素材格式（.{ext}），非业务数据"

    # 9) 文本型配置文件：位于系统/应用目录 → 明显误报；仅凭扩展名 → 可疑
    if ext in CONFIG_EXTS:
        if re.search(r"appdata|library/(preferences|application support|webkit|containers)|program files|windows|/etc/|/opt/|/usr/", path):
            return "fp_high", "config_in_appdir", "程序配置文件", \
                f"程序配置文件（.{ext}），位于程序/系统目录"
        return "fp_suspect", "config_standalone", "程序配置文件(待确认)", \
            f"配置文件（.{ext}），请人工确认是否含业务敏感信息"

    # 10) 日志文件：位于日志目录 → 明显误报；仅凭扩展名 → 可疑
    if ext == "log":
        if re.search(r"(^|/)(logs|logfiles)(/|$)|appdata.*logs|library.*logs", path):
            return "fp_high", "app_log", "应用日志", "应用日志文件"
        return "fp_suspect", "log_standalone", "日志文件(待确认)", \
            "日志文件（.log），请人工确认是否含敏感信息"

    return "normal", "none", "正常告警", "未命中误报规则，请按告警正常处理"


# ---------------------------------------------------------------------------
# 数据拉取
# ---------------------------------------------------------------------------

def fetch_events(client: FeilianClient, start: int, end: int,
                 limit: int = PAGE_SIZE) -> List[Dict[str, Any]]:
    """按 offset 翻页拉取告警事件列表。"""
    items: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = client.request("GET", EVENTS_PATH, query={
            "start_time": start,
            "end_time": end,
            "limit": limit,
            "offset": offset,
        })
        page = (data or {}).get("items") or []
        if isinstance(page, dict):
            page = page.get("items") or []
        items.extend(page)
        if len(page) < limit:
            break
        offset += limit
        if offset > 20000:  # 防呆
            break
    return items


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def build_report(events: List[Dict[str, Any]], start: int, end: int) -> Dict[str, Any]:
    verdicts = []
    for ev in events:
        v, rid, cat, reason = classify(ev)
        fi = ev.get("file_info") or {}
        lw = ev.get("leak_way") or {}
        ui = ev.get("user_info") or {}
        verdicts.append({
            "event_id": ev.get("event_id"),
            "event_time": datetime.fromtimestamp(ev.get("event_unix_time") or 0)
            .strftime("%Y-%m-%d %H:%M:%S"),
            "user": ui.get("full_name") or ui.get("id") or "",
            "department": (ui.get("department_path") or "").split("/")[-1] or "",
            "device": ev.get("device_name") or ev.get("device_hostname") or "",
            "strategy": ev.get("strategy_name") or "",
            "event_type": ev.get("event_type") or "",
            "action_desc": ev.get("action_desc") or "",
            "app": lw.get("app_name") or "",
            "file_name": fi.get("name") or "",
            "file_path": fi.get("path") or "",
            "file_ext": (fi.get("name") or "").rsplit(".", 1)[-1] if "." in (fi.get("name") or "") else "",
            "file_size": fi.get("size") or 0,
            "verdict": v,
            "rule_id": rid,
            "category": cat,
            "reason": reason,
        })

    counter = {"fp_high": 0, "fp_suspect": 0, "normal": 0, "no_file": 0}
    for x in verdicts:
        counter[x["verdict"]] += 1

    rule_stats: Dict[str, int] = {}
    for x in verdicts:
        if x["verdict"] in ("fp_high", "fp_suspect"):
            rule_stats[x["rule_id"]] = rule_stats.get(x["rule_id"], 0) + 1

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window": {
            "start": datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S"),
            "end": datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "total": len(events),
        "summary": counter,
        "rule_stats": rule_stats,
        "items": verdicts,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# DLP 告警日志误报巡检报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 统计窗口：{report['window']['start']} ~ {report['window']['end']}",
        f"- 告警总数：**{report['total']}** 条",
        f"- 明显误报：**{s['fp_high']}** 条 ｜ 可疑待人工：**{s['fp_suspect']}** 条 "
        f"｜ 正常告警：**{s['normal']}** 条 ｜ 非文件外发：**{s['no_file']}** 条",
        "",
        "## 一、明显误报清单",
        "",
    ]
    highs = [x for x in report["items"] if x["verdict"] == "fp_high"]
    if not highs:
        lines.append("（无）")
    else:
        lines.append("| 时间 | 用户 | 设备 | 文件 | 类别 | 判定依据 |")
        lines.append("|---|---|---|---|---|---|")
        for x in highs:
            fname = x["file_name"] or "—"
            fpath = x["file_path"] or "—"
            lines.append(
                f"| {x['event_time']} | {x['user']} | {x['device']} | "
                f"{fname}<br><small>{fpath}</small> | {x['category']} | {x['reason']} |"
            )
    lines += ["", "## 二、可疑待人工清单", ""]
    sus = [x for x in report["items"] if x["verdict"] == "fp_suspect"]
    if not sus:
        lines.append("（无）")
    else:
        lines.append("| 时间 | 用户 | 设备 | 文件 | 类别 | 建议 |")
        lines.append("|---|---|---|---|---|---|")
        for x in sus:
            lines.append(
                f"| {x['event_time']} | {x['user']} | {x['device']} | "
                f"{x['file_name'] or '—'}<br><small>{x['file_path'] or '—'}</small> | "
                f"{x['category']} | {x['reason']} |"
            )
    lines += ["", "## 三、非文件外发事件", ""]
    nof = [x for x in report["items"] if x["verdict"] == "no_file"]
    lines.append(f"共 {len(nof)} 条（剪贴板/代码仓库/命令行等，无文件特征，未参与误报判定）：")
    for x in nof[:30]:
        lines.append(f"- {x['event_time']} | {x['user']} | {x['event_type']} | {x['action_desc']}")
    if len(nof) > 30:
        lines.append(f"- ……共 {len(nof)} 条")
    lines += ["", "## 四、正常告警（未命中误报规则）", ""]
    nrm = [x for x in report["items"] if x["verdict"] == "normal"]
    lines.append(f"共 {len(nrm)} 条，请按策略正常处置。")
    for x in nrm[:20]:
        lines.append(
            f"- {x['event_time']} | {x['user']} | {x['file_name'] or '—'} | {x['event_type']}"
        )
    if len(nrm) > 20:
        lines.append(f"- ……共 {len(nrm)} 条")
    lines += ["", "## 五、误报规则命中统计", ""]
    if report["rule_stats"]:
        lines.append("| 规则 | 命中数 |")
        lines.append("|---|---|")
        for rid, cnt in sorted(report["rule_stats"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {rid} | {cnt} |")
    else:
        lines.append("（无）")
    lines += ["", "## 六、建议", ""]
    lines += [
        "- 对持续高频出现的误报路径/应用，可在飞连后台创建「文件外发阻断白名单」策略，降低人工复核成本。",
        "- 本报告的判定仅基于文件路径、文件名、文件格式特征；需要确认真实内容时可调用取证文件接口核对。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="DLP 告警日志误报巡检")
    ap.add_argument("--days", type=int, default=1, help="拉取最近 N 天（默认 1）")
    ap.add_argument("--profile", default="default", help="CLI 配置 profile（默认 default）")
    ap.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"),
                    help="报告输出目录（默认 <项目>/reports）")
    ap.add_argument("--json-only", action="store_true", help="仅输出 JSON 不打印摘要")
    args = ap.parse_args()

    now = int(time.time())
    start = int(time.time()) - args.days * 86400

    try:
        profile = load_profile(args.profile)
    except ConfigError as e:
        print(f"错误: {e}\n请先运行 feilian configure 配置 endpoint 与 AccessKey。", file=sys.stderr)
        return 1

    try:
        with FeilianClient(profile) as client:
            events = fetch_events(client, start, now)
    except ApiError as e:
        print(f"拉取失败: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"拉取异常: {e}", file=sys.stderr)
        return 2

    report = build_report(events, start, now)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    md_path = out_dir / f"dlp_false_positive_{date_tag}.md"
    json_path = out_dir / f"dlp_false_positive_{date_tag}.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False))
    else:
        s = report["summary"]
        print(f"DLP 误报巡检完成（{report['window']['start']} ~ {report['window']['end']}）")
        print(f"  告警总数 {report['total']} ｜ 明显误报 {s['fp_high']} ｜ "
              f"可疑 {s['fp_suspect']} ｜ 正常 {s['normal']} ｜ 非文件外发 {s['no_file']}")
        print(f"  Markdown: {md_path}")
        print(f"  JSON    : {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
