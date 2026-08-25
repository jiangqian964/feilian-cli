"""feilian CLI 入口：全局选项、configure、api 透传、search 及动态命令树。"""
from __future__ import annotations

import json
import sys

import click

from . import __version__, auth, config, registry
from .client import ApiError, FeilianClient
from .config import ConfigError
from .output import render


class State:
    """全局运行时状态，经 ctx.obj 传递给动态命令。"""

    def __init__(self, profile_name: str, endpoint: str, lang: str,
                 out_fmt: str, debug: bool, insecure: bool):
        self.profile_name = profile_name
        self.endpoint = endpoint
        self.lang = lang
        self.out_fmt = out_fmt
        self.debug = debug
        self.insecure = insecure

    def load_profile(self) -> config.Profile:
        try:
            profile = config.load_profile(self.profile_name, self.endpoint)
        except ConfigError as e:
            raise click.ClickException(str(e))
        if self.insecure:
            profile.verify_ssl = False
        return profile

    def make_client(self) -> FeilianClient:
        return FeilianClient(self.load_profile(), lang=self.lang, debug=self.debug)

    def render(self, data) -> None:
        render(data, self.out_fmt)


class FeilianCLI(click.Group):
    """错误统一落到 stderr，业务错误返回退出码 1。"""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except ApiError as e:
            click.echo(f"接口错误: code={e.code} {e.message}", err=True)
            sys.exit(1)
        except auth.AuthError as e:
            click.echo(f"认证失败: {e}", err=True)
            sys.exit(1)


@click.group(cls=FeilianCLI, context_settings={"help_option_names": ["-h", "--help"],
                                               "max_content_width": 120})
@click.version_option(__version__, prog_name="feilian")
@click.option("--profile", "-p", default="default", envvar="FEILIAN_PROFILE",
              show_default=True, help="使用的配置 profile")
@click.option("--endpoint", default=None, help="临时覆盖服务端地址")
@click.option("--lang", default="zh-CN", type=click.Choice(["zh-CN", "en-US"]),
              show_default=True, help="返回结果语言")
@click.option("--output", "-o", "out_fmt", default="json",
              type=click.Choice(["json", "table", "raw"]), show_default=True,
              help="输出格式")
@click.option("--debug", is_flag=True, help="打印请求调试信息（token 自动脱敏）")
@click.option("--insecure", "-k", is_flag=True, help="跳过 TLS 证书校验")
@click.pass_context
def cli(ctx, profile, endpoint, lang, out_fmt, debug, insecure):
    """飞连开放平台 CLI（IT 管理员用）。

    首次使用请运行: feilian configure

    命令按接口分类分组，如: feilian org / feilian device / feilian ztna；
    未封装的接口可用 feilian api 直接透传调用。
    """
    ctx.obj = State(profile, endpoint, lang, out_fmt, debug, insecure)


@cli.command()
@click.option("--profile", "profile_name", default=None,
              help="要写入的 profile 名（默认取全局 --profile）")
@click.pass_obj
def configure(state: State, profile_name):
    """交互式配置 endpoint 与 AccessKey。"""
    name = profile_name or state.profile_name
    existing = config.load_raw().get(name, {})
    endpoint = click.prompt(
        "服务端地址 (Endpoint)",
        default=existing.get("endpoint", config.DEFAULT_ENDPOINT))
    ak = click.prompt(
        "AccessKey ID",
        default=existing.get("access_key_id") or None)
    sk = click.prompt("AccessKey Secret", hide_input=True,
                      default="********" if existing.get("access_key_secret") else None)
    if sk == "********":
        sk = existing["access_key_secret"]
    verify_ssl = click.confirm("校验 TLS 证书?",
                               default=bool(existing.get("verify_ssl", True)))
    config.save_profile(name, endpoint.strip(), ak.strip(), sk.strip(), verify_ssl)
    click.echo(f"已写入 {config.CONFIG_FILE} [{name}]")

    if click.confirm("立即验证（获取 access_token）?", default=True):
        profile = config.load_profile(name)
        try:
            auth.fetch_token(profile)
            click.echo("验证成功：access_token 获取正常")
        except auth.AuthError as e:
            click.echo(f"验证失败: {e}", err=True)
            sys.exit(1)


@cli.command()
@click.option("--refresh", is_flag=True, help="强制重新获取 token")
@click.option("--show", is_flag=True, help="打印 token 明文（默认只显示前 8 位）")
@click.option("--expires-in", type=int, default=None,
              help="自定义 token 过期时间（秒），最短 7200（2小时）；仅在重新获取时生效，"
                   "也可通过环境变量 FEILIAN_TOKEN_EXPIRES_IN 设置")
@click.pass_obj
def token(state: State, refresh, show, expires_in):
    """获取/刷新 access_token（调试用）。"""
    profile = state.load_profile()
    tk = auth.get_token(profile, force_refresh=refresh, expires_in=expires_in)
    click.echo(tk if show else tk[:8] + "..." + f"（共 {len(tk)} 位，--show 查看明文）")


@cli.command("api")
@click.argument("method", type=click.Choice(["get", "post"], case_sensitive=False))
@click.argument("path")
@click.option("--query", "-q", multiple=True, metavar="KEY=VALUE",
              help="Query 参数（可重复）")
@click.option("--data", "-d", default=None,
              help="请求体 JSON：'{...}'、@file.json 或 @-（stdin）")
@click.option("--all", "fetch_all", is_flag=True, help="offset/limit 自动翻页")
@click.pass_obj
def api_passthrough(state: State, method, path, query, data, fetch_all):
    """透传调用任意开放接口（未封装/新增接口兜底）。

    示例:

      feilian api get /api/open/v1/department/list -q parent_id=od_xxx

      feilian api post /api/open/v1/department/create -d '{"name":"新部门","parent_id":"od_xxx"}'
    """
    q = {}
    for item in query:
        if "=" not in item:
            raise click.UsageError(f"--query 需要 KEY=VALUE 形式: {item}")
        k, v = item.split("=", 1)
        q[k] = v
    body = registry._read_data_arg(data) if data else None
    if not path.startswith("/"):
        path = "/" + path

    client = state.make_client()
    try:
        if fetch_all:
            result = client.request_all(method.upper(), path, query=q or None, body=body)
        else:
            result = client.request(method.upper(), path, query=q or None, body=body)
    finally:
        client.close()
    state.render(result)


@cli.command()
@click.argument("keyword")
def search(keyword):
    """按关键字搜索可用命令（匹配中文名/路径/命令名）。"""
    spec = registry.load_spec()
    kw = keyword.lower()
    hits = [a for a in spec["apis"]
            if kw in a["name"].lower() or kw in a["name_cn"].lower()
            or kw in a["path"].lower() or kw in a["category_cn"]]
    if not hits:
        click.echo("未找到匹配的接口", err=True)
        sys.exit(1)
    for a in hits:
        flag = "（废弃）" if a.get("deprecated") else ""
        click.echo(f"feilian {a['category']} {a['name']:44s} {a['name_cn']}{flag}  [{a['method']} {a['path']}]")


registry.register_commands(cli)


if __name__ == "__main__":
    cli()
