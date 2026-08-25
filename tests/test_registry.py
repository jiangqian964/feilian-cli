"""规格加载与动态命令生成测试。"""
import json
import time

import httpx
import respx
from click.testing import CliRunner

from feilian_cli import auth, registry
from feilian_cli.main import cli

ENDPOINT = "https://fl.example.com"


def test_spec_loads_and_is_complete():
    spec = registry.load_spec()
    assert len(spec["apis"]) >= 240
    slugs = {c["slug"] for c in spec["categories"]}
    assert {"org", "device", "ztna", "nac", "security", "system"} <= slugs
    for api in spec["apis"]:
        assert api["path"].startswith("/api/open/")
        assert api["method"] in ("GET", "POST")
        assert api["name"]
        assert api["category"] in slugs
    # 同分类内命令名唯一
    keys = [(a["category"], a["name"]) for a in spec["apis"]]
    assert len(keys) == len(set(keys))


def test_all_groups_registered():
    spec = registry.load_spec()
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cat in spec["categories"]:
        assert cat["slug"] in result.output


def test_leaf_command_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["org", "user-list", "--help"])
    assert result.exit_code == 0
    assert "--department-id" in result.output
    assert "--all" in result.output


def _prepare_env(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CACHE_DIR", tmp_path)
    (tmp_path / "token_default.json").write_text(json.dumps({
        "access_token": "tok", "expires_at": time.time() + 3600,
        "endpoint": ENDPOINT, "access_key_id": "ak",
    }))
    monkeypatch.setenv("FEILIAN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("FEILIAN_ACCESS_KEY_SECRET", "sk")
    monkeypatch.setenv("FEILIAN_ENDPOINT", ENDPOINT)


@respx.mock
def test_dynamic_command_invocation(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    route = respx.get(f"{ENDPOINT}/api/open/v1/user/list").mock(
        return_value=httpx.Response(200, json={
            "code": 0, "data": {"users": [{"open_id": "ou_1", "name": "张三"}]}}))
    runner = CliRunner()
    result = runner.invoke(cli, ["org", "user-list", "--department-id", "od_x"])
    assert result.exit_code == 0, result.output
    assert "ou_1" in result.output
    assert "department_id=od_x" in str(route.calls[0].request.url)


@respx.mock
def test_dynamic_command_with_data_merge(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    route = respx.post(f"{ENDPOINT}/api/open/v1/department/create").mock(
        return_value=httpx.Response(200, json={
            "code": 0, "data": {"department_id": "od_new"}}))
    runner = CliRunner()
    result = runner.invoke(cli, [
        "org", "department-create", "--name", "测试部门",
        "--data", '{"parent_id": "od_root", "type": 2}'])
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls[0].request.content)
    assert body == {"name": "测试部门", "parent_id": "od_root", "type": 2}


@respx.mock
def test_api_passthrough(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    respx.post(f"{ENDPOINT}/api/open/v1/anything").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"ok": 1}}))
    runner = CliRunner()
    result = runner.invoke(cli, ["api", "post", "/api/open/v1/anything",
                                 "-d", '{"a": 1}'])
    assert result.exit_code == 0, result.output
    assert '"ok": 1' in result.output


@respx.mock
def test_business_error_exit_code(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    respx.get(f"{ENDPOINT}/api/open/v1/user/list").mock(
        return_value=httpx.Response(200, json={
            "code": 40001, "message": "no permission"}))
    runner = CliRunner()
    result = runner.invoke(cli, ["org", "user-list", "--department-id", "od_x"])
    assert result.exit_code == 1
    assert "40001" in result.output


def test_search_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "access_token"])
    assert result.exit_code == 0
    assert "/api/open/v1/token" in result.output
