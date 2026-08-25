"""token 缓存与刷新逻辑测试。"""
import json
import time

import pytest
import respx
import httpx

from feilian_cli import auth
from feilian_cli.config import Profile

ENDPOINT = "https://fl.example.com"


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CACHE_DIR", tmp_path)
    return Profile(name="test", endpoint=ENDPOINT,
                   access_key_id="ak", access_key_secret="sk")


def token_route(token="tok-1", expires_in=7200):
    return respx.post(f"{ENDPOINT}/api/open/v1/token").mock(
        return_value=httpx.Response(200, json={
            "code": 0, "message": "", "action": "",
            "data": {"access_token": token, "expires_in": expires_in},
        }))


@respx.mock
def test_fetch_and_cache(profile, tmp_path):
    route = token_route()
    assert auth.get_token(profile) == "tok-1"
    assert route.call_count == 1
    # 命中缓存，不再请求
    assert auth.get_token(profile) == "tok-1"
    assert route.call_count == 1
    cache = json.loads((tmp_path / "token_test.json").read_text())
    assert cache["access_token"] == "tok-1"
    assert cache["expires_at"] > time.time()


@respx.mock
def test_expired_cache_refreshes(profile, tmp_path):
    (tmp_path / "token_test.json").write_text(json.dumps({
        "access_token": "old", "expires_at": time.time() - 10,
        "endpoint": ENDPOINT, "access_key_id": "ak",
    }))
    token_route("tok-new")
    assert auth.get_token(profile) == "tok-new"


@respx.mock
def test_cache_invalidated_on_endpoint_change(profile, tmp_path):
    (tmp_path / "token_test.json").write_text(json.dumps({
        "access_token": "old", "expires_at": time.time() + 3600,
        "endpoint": "https://other.example.com", "access_key_id": "ak",
    }))
    token_route("tok-new")
    assert auth.get_token(profile) == "tok-new"


@respx.mock
def test_force_refresh(profile):
    route = token_route()
    auth.get_token(profile)
    auth.get_token(profile, force_refresh=True)
    assert route.call_count == 2


@respx.mock
def test_auth_error_on_bad_ak(profile):
    respx.post(f"{ENDPOINT}/api/open/v1/token").mock(
        return_value=httpx.Response(200, json={
            "code": 40000, "message": "invalid access key", "data": None}))
    with pytest.raises(auth.AuthError, match="40000"):
        auth.get_token(profile)
