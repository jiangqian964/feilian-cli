"""客户端错误处理、token 失效重试、自动翻页测试。"""
import json
import time

import pytest
import respx
import httpx

from feilian_cli import auth
from feilian_cli.client import ApiError, FeilianClient
from feilian_cli.config import Profile

ENDPOINT = "https://fl.example.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CACHE_DIR", tmp_path)
    # 预置有效 token 缓存，避免额外 token 请求
    (tmp_path / "token_test.json").write_text(json.dumps({
        "access_token": "cached-token", "expires_at": time.time() + 3600,
        "endpoint": ENDPOINT, "access_key_id": "ak",
    }))
    profile = Profile(name="test", endpoint=ENDPOINT,
                      access_key_id="ak", access_key_secret="sk")
    c = FeilianClient(profile)
    yield c
    c.close()


def mock_token(token="fresh-token"):
    return respx.post(f"{ENDPOINT}/api/open/v1/token").mock(
        return_value=httpx.Response(200, json={
            "code": 0, "data": {"access_token": token, "expires_in": 7200}}))


@respx.mock
def test_request_success_returns_data(client):
    route = respx.get(f"{ENDPOINT}/api/open/v1/user/list").mock(
        return_value=httpx.Response(200, json={
            "code": 0, "message": "", "data": {"users": [{"id": 1}]}}))
    data = client.request("GET", "/api/open/v1/user/list",
                          query={"department_id": "od_x"})
    assert data == {"users": [{"id": 1}]}
    req = route.calls[0].request
    assert req.headers["Authorization"] == "cached-token"
    assert "department_id=od_x" in str(req.url)
    assert "language=zh-CN" in str(req.url)


@respx.mock
def test_business_error_raises(client):
    respx.get(f"{ENDPOINT}/api/open/v1/x").mock(
        return_value=httpx.Response(200, json={
            "code": 40001, "message": "no permission", "data": None}))
    with pytest.raises(ApiError) as ei:
        client.request("GET", "/api/open/v1/x")
    assert ei.value.code == 40001
    assert "权限" in ei.value.message


@respx.mock
def test_token_invalid_retries_once(client):
    mock_token()
    route = respx.get(f"{ENDPOINT}/api/open/v1/x")
    route.side_effect = [
        httpx.Response(401, json={"code": 401, "message": "expired"}),
        httpx.Response(200, json={"code": 0, "data": {"ok": True}}),
    ]
    data = client.request("GET", "/api/open/v1/x")
    assert data == {"ok": True}
    assert route.call_count == 2
    assert route.calls[1].request.headers["Authorization"] == "fresh-token"


@respx.mock
def test_request_all_paginates_get(client):
    route = respx.get(f"{ENDPOINT}/api/open/v1/user/list")
    route.side_effect = [
        httpx.Response(200, json={"code": 0, "data": {
            "total": 3, "users": [{"id": 1}, {"id": 2}]}}),
        httpx.Response(200, json={"code": 0, "data": {
            "total": 3, "users": [{"id": 3}]}}),
    ]
    data = client.request_all("GET", "/api/open/v1/user/list",
                              query={"department_id": "od_x"}, page_size=2)
    assert [u["id"] for u in data["users"]] == [1, 2, 3]
    assert route.call_count == 2
    url2 = str(route.calls[1].request.url)
    assert "offset=2" in url2 and "limit=2" in url2


@respx.mock
def test_request_all_paginates_post_body(client):
    route = respx.post(f"{ENDPOINT}/api/open/v1/device/list")
    route.side_effect = [
        httpx.Response(200, json={"code": 0, "data": {
            "devices": [{"id": i} for i in range(2)]}}),
        httpx.Response(200, json={"code": 0, "data": {"devices": []}}),
    ]
    data = client.request_all("POST", "/api/open/v1/device/list",
                              body={}, page_size=2)
    assert len(data["devices"]) == 2
    body2 = json.loads(route.calls[1].request.content)
    assert body2["offset"] == 2
