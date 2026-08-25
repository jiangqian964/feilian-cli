"""access_token 获取与本地缓存。

token 通过 POST /api/open/v1/token 用 AK/SK 换取，默认有效期 7200 秒，
可通过 expires_in 参数自定义过期时间（最短 2 小时）。
缓存于 ~/.cache/feilian/token_<profile>.json（0600），提前 60 秒视为过期。
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx

from .config import CACHE_DIR, Profile

TOKEN_PATH = "/api/open/v1/token"
EXPIRY_MARGIN = 60  # 秒
MIN_EXPIRES_IN = 7200  # 最短过期时间：2 小时


class AuthError(Exception):
    pass


def _cache_file(profile: Profile):
    return CACHE_DIR / f"token_{profile.name}.json"


def _load_cached(profile: Profile) -> Optional[str]:
    f = _cache_file(profile)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    # endpoint 或 AK 变化时缓存失效
    if data.get("endpoint") != profile.endpoint or \
            data.get("access_key_id") != profile.access_key_id:
        return None
    if data.get("expires_at", 0) <= time.time() + EXPIRY_MARGIN:
        return None
    return data.get("access_token")


def _save_cached(profile: Profile, token: str, expires_in: int) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = _cache_file(profile)
    f.write_text(json.dumps({
        "access_token": token,
        "expires_at": time.time() + expires_in,
        "endpoint": profile.endpoint,
        "access_key_id": profile.access_key_id,
    }), encoding="utf-8")
    os.chmod(f, 0o600)


def fetch_token(profile: Profile, client: Optional[httpx.Client] = None,
                 expires_in: Optional[int] = None) -> str:
    """向服务端换取新 token 并写入缓存。

    Args:
        profile: 配置 profile
        client: 可选的 httpx 客户端
        expires_in: 自定义过期时间（秒），最短 7200 秒（2 小时），
                    也可通过环境变量 FEILIAN_TOKEN_EXPIRES_IN 设置
    """
    close = False
    if client is None:
        client = httpx.Client(verify=profile.verify_ssl, timeout=30)
        close = True
    # 组装请求体：AK/SK + 可选 expires_in
    req_body = {
        "access_key_id": profile.access_key_id,
        "access_key_secret": profile.access_key_secret,
    }
    if expires_in is None:
        env_val = os.environ.get("FEILIAN_TOKEN_EXPIRES_IN")
        if env_val is not None:
            try:
                expires_in = int(env_val)
            except ValueError:
                expires_in = None
    if expires_in is not None:
        if expires_in < MIN_EXPIRES_IN:
            expires_in = MIN_EXPIRES_IN
        req_body["expires_in"] = expires_in
    try:
        resp = client.post(
            profile.endpoint + TOKEN_PATH,
            json=req_body,
            headers={"Content-Type": "application/json;charset=utf-8"},
        )
        try:
            body = resp.json()
        except ValueError:
            raise AuthError(f"获取 access_token 失败：HTTP {resp.status_code} 非 JSON 响应")
        if body.get("code") != 0:
            raise AuthError(
                f"获取 access_token 失败：code={body.get('code')} {body.get('message', '')}")
        data = body.get("data") or {}
        token = data.get("access_token")
        if not token:
            raise AuthError("获取 access_token 失败：响应中缺少 access_token")
        _save_cached(profile, token, int(data.get("expires_in", 7200)))
        return token
    finally:
        if close:
            client.close()


def get_token(profile: Profile, force_refresh: bool = False,
              client: Optional[httpx.Client] = None,
              expires_in: Optional[int] = None) -> str:
    """返回可用 token：优先缓存，过期/强制时重新获取。

    Args:
        profile: 配置 profile
        force_refresh: 是否强制刷新（忽略缓存）
        client: 可选的 httpx 客户端
        expires_in: 自定义过期时间（秒），仅在重新获取 token 时生效
    """
    if not force_refresh:
        cached = _load_cached(profile)
        if cached:
            return cached
    return fetch_token(profile, client=client, expires_in=expires_in)


def clear_cache(profile: Profile) -> None:
    f = _cache_file(profile)
    if f.exists():
        f.unlink()
