"""HTTP 客户端封装：统一鉴权、错误处理、token 失效重试、自动翻页。"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import httpx

from . import auth
from .config import Profile

# 服务端约定错误码（见开发指南-使用限制）
CODE_NO_PERMISSION = 40001   # 无接口权限
CODE_RATE_LIMITED = 164007   # 触发限频
CODE_IP_DENIED = 164008      # IP 白名单拦截
# token 无效/过期时强制刷新重试一次的判定：HTTP 401 或以下业务码
TOKEN_INVALID_CODES = {101, 401, 40101, 40102}


class ApiError(Exception):
    def __init__(self, code: Any, message: str, http_status: int = 200):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"code={code} {message}")


class FeilianClient:
    def __init__(self, profile: Profile, lang: str = "zh-CN", debug: bool = False,
                 timeout: float = 60.0):
        self.profile = profile
        self.lang = lang
        self.debug = debug
        self._http = httpx.Client(
            base_url=profile.endpoint,
            verify=profile.verify_ssl,
            timeout=timeout,
        )

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 底层请求 ----

    def _log(self, msg: str):
        if self.debug:
            print(f"[debug] {msg}", file=sys.stderr)

    def request(self, method: str, path: str,
                query: Optional[Dict[str, Any]] = None,
                body: Optional[Dict[str, Any]] = None) -> Any:
        """发起一次开放平台请求，返回响应 data 字段；code!=0 抛 ApiError。"""
        token = auth.get_token(self.profile, client=self._http)
        resp = self._do(method, path, query, body, token)
        if self._token_invalid(resp):
            self._log("token 疑似失效，强制刷新后重试一次")
            token = auth.get_token(self.profile, force_refresh=True, client=self._http)
            resp = self._do(method, path, query, body, token)
        return self._unwrap(resp)

    def _do(self, method, path, query, body, token) -> httpx.Response:
        params = dict(query or {})
        params.setdefault("language", self.lang)
        headers = {
            "Authorization": token,
            "Content-Type": "application/json;charset=utf-8",
        }
        self._log(f"{method} {path} query={params} body={json.dumps(body, ensure_ascii=False) if body else None}")
        resp = self._http.request(method, path, params=params,
                                  json=body if body is not None else None,
                                  headers=headers)
        self._log(f"HTTP {resp.status_code} {resp.text[:500]}")
        return resp

    @staticmethod
    def _token_invalid(resp: httpx.Response) -> bool:
        if resp.status_code == 401:
            return True
        try:
            code = resp.json().get("code")
        except ValueError:
            return False
        return code in TOKEN_INVALID_CODES

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        try:
            body = resp.json()
        except ValueError:
            raise ApiError(resp.status_code, f"非 JSON 响应: {resp.text[:200]}",
                           resp.status_code)
        code = body.get("code")
        if code != 0:
            msg = body.get("message", "")
            if code == CODE_NO_PERMISSION:
                msg += "（应用缺少该接口权限，请在管理后台-开放平台为 AccessKey 添加权限）"
            elif code == CODE_RATE_LIMITED:
                msg += "（触发调用频率限制，请稍后重试）"
            elif code == CODE_IP_DENIED:
                msg += "（当前 IP 不在开放平台 IP 白名单内）"
            raise ApiError(code, msg, resp.status_code)
        return body.get("data")

    # ---- 自动翻页 ----

    def request_all(self, method: str, path: str,
                    query: Optional[Dict[str, Any]] = None,
                    body: Optional[Dict[str, Any]] = None,
                    page_size: int = 100, max_pages: int = 1000) -> Any:
        """针对 offset/limit 风格分页接口自动聚合全部页。

        返回 {list字段: [...全部元素], 其余字段: 最后一页的值}；
        若响应 data 不是含列表的对象则原样返回首页。
        """
        where = dict(query or {}) if method.upper() == "GET" else dict(body or {})
        where["limit"] = int(where.get("limit") or page_size)
        where["offset"] = int(where.get("offset") or 0)

        merged: Optional[Dict[str, Any]] = None
        list_key: Optional[str] = None
        for _ in range(max_pages):
            if method.upper() == "GET":
                data = self.request(method, path, query=where, body=body)
            else:
                data = self.request(method, path, query=query, body=where)
            if not isinstance(data, dict):
                return data
            if list_key is None:
                for k, v in data.items():
                    if isinstance(v, list):
                        list_key = k
                        break
                if list_key is None:
                    return data
            page_items = data.get(list_key) or []
            if merged is None:
                merged = dict(data)
                merged[list_key] = list(page_items)
            else:
                merged[list_key].extend(page_items)
                for k, v in data.items():
                    if k != list_key:
                        merged[k] = v
            if len(page_items) < where["limit"]:
                break
            where["offset"] += where["limit"]
        return merged
