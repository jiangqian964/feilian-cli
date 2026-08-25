"""配置管理：~/.config/feilian/config.toml，支持多 profile。

文件格式：
    [default]
    endpoint = "https://flzdyth.sensetime.com:10443"
    access_key_id = "xxx"
    access_key_secret = "xxx"

    [staging]
    endpoint = "..."

环境变量覆盖（优先级最高）：
    FEILIAN_ENDPOINT / FEILIAN_ACCESS_KEY_ID / FEILIAN_ACCESS_KEY_SECRET
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

DEFAULT_ENDPOINT = "https://flzdyth.sensetime.com:10443"

CONFIG_DIR = Path(os.environ.get("FEILIAN_CONFIG_DIR", "~/.config/feilian")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"
CACHE_DIR = Path(os.environ.get("FEILIAN_CACHE_DIR", "~/.cache/feilian")).expanduser()


class ConfigError(Exception):
    pass


@dataclass
class Profile:
    name: str
    endpoint: str
    access_key_id: str
    access_key_secret: str
    verify_ssl: bool = True


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def load_raw() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def save_profile(name: str, endpoint: str, access_key_id: str,
                 access_key_secret: str, verify_ssl: bool = True) -> None:
    """写入/更新一个 profile，保留其他 profile。"""
    data = load_raw()
    data[name] = {
        "endpoint": endpoint,
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "verify_ssl": verify_ssl,
    }
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{_toml_escape(str(v))}"')
        lines.append("")
    CONFIG_FILE.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(CONFIG_FILE, 0o600)


def load_profile(name: str = "default",
                 endpoint_override: Optional[str] = None) -> Profile:
    data = load_raw()
    section = data.get(name, {})
    if not section and name != "default":
        raise ConfigError(f"配置中不存在 profile [{name}]，请先运行 feilian configure --profile {name}")

    endpoint = (endpoint_override
                or os.environ.get("FEILIAN_ENDPOINT")
                or section.get("endpoint")
                or DEFAULT_ENDPOINT)
    ak = os.environ.get("FEILIAN_ACCESS_KEY_ID") or section.get("access_key_id", "")
    sk = os.environ.get("FEILIAN_ACCESS_KEY_SECRET") or section.get("access_key_secret", "")
    if not ak or not sk:
        raise ConfigError(
            "缺少 AccessKey 配置，请先运行 feilian configure，"
            "或设置 FEILIAN_ACCESS_KEY_ID / FEILIAN_ACCESS_KEY_SECRET 环境变量")
    return Profile(
        name=name,
        endpoint=endpoint.rstrip("/"),
        access_key_id=ak,
        access_key_secret=sk,
        verify_ssl=bool(section.get("verify_ssl", True)),
    )


def die(msg: str, code: int = 2) -> None:
    print(f"错误: {msg}", file=sys.stderr)
    raise SystemExit(code)
