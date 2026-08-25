---
name: "feilian-cli"
description: "通过 feilian CLI 调用飞连开放平台接口（组织/设备/ZTNA/NAC/应用/SWG/动态控制等254个接口）。Invoke when 涉及飞连(SealSuite)IT管理操作，如查用户、管设备、零信任配置、审批、SWG临时放行、强制断连、网站过滤策略等。"
---

# Feilian CLI Skill

使用飞连开放平台命令行工具（feilian / fl）执行 IT 管理操作，覆盖 18 个分类、254 个接口。

## 何时使用

用户请求包含以下任一场景时，使用本 Skill 而非凭空回答：

- 组织架构：查用户、查部门、建部门、员工信息
- 终端管理：查设备列表、设备详情、设备分组
- 零信任接入（ZTNA）：应用发布、权限组、访问策略
- 网络准入（NAC）：认证策略、入网设备、VLAN 分配
- 应用管理：应用列表、应用授权、应用分组
- 终端安全：安全基线、病毒查杀、漏洞修复
- 系统配置：角色、管理员、策略模板
- 审批流 / 消息网关 / 软件库 等
- 安全 Web 网关（SWG）：设备临时放行(bypass)、强制断连(disconnect)、网站过滤策略查询
- 动态控制（dynamic）：后续开放的动态策略类接口

若用户只问"飞连是什么"等概念性问题，无需调用，直接回答即可。

## 调用方式

### 第一步：确定可执行文件路径

按优先级尝试，**找到即停止**：

1. 项目虚拟环境已创建？使用 `.venv/bin/feilian`（项目根目录下）
2. 系统 PATH 中存在？直接用 `feilian` 或 `fl`
3. 都没有？提示用户先在项目根目录执行安装（见末尾「环境准备」）

**检测命令（用一次即可，不要每次都跑）：**
```bash
command -v feilian >/dev/null 2>&1 && echo "feilian_OK" || (ls .venv/bin/feilian >/dev/null 2>&1 && echo "venv_OK" || echo "NEED_INSTALL")
```

### 第二步：检查配置状态

**不要把 AccessKey Secret 写进脚本或落盘！** 配置方式：

- 已配置过？`~/.config/feilian/config.toml` 存在且有对应 profile
- 未配置？提示用户执行 `feilian configure` 交互式填写，或通过环境变量传入：
  ```
  FEILIAN_ENDPOINT / FEILIAN_ACCESS_KEY_ID / FEILIAN_ACCESS_KEY_SECRET
  FEILIAN_PROFILE                # 选择配置段，默认 default
  FEILIAN_TOKEN_EXPIRES_IN       # token 默认过期秒数（>=7200），可覆盖
  ```
- 临时调试：可用 `-p staging` 切换 profile，或 `--endpoint` 临时覆盖地址

### 第三步：发起调用

**统一使用 Shell 工具执行命令。** 构造命令的原则：

#### A. 优先用已封装的分类命令（推荐）

先看有哪些命令组：
```bash
feilian --help
feilian org --help              # 查某分类下的子命令
feilian org user-list --help    # 查单接口参数
feilian search <关键字>          # 按中文名/路径搜命令
```

常用示例：

```bash
# 查某部门下的用户，拉全量
feilian org user-list --department-id od_xxx --all

# 查设备列表，表格输出
feilian device search --output table

# 创建部门，JSON + 选项合并
feilian org department-create --name "新部门" --data '{"parent_id":"od_xxx"}'

# ZTNA: 查应用列表
feilian ztna app-list --all

# ========== SWG 安全 Web 网关（新增 7 个命令） ==========
# 列出当前处于临时放行(bypass)状态的设备
feilian swg devices-bypass-list --all

# 列出当前处于强制断连状态的设备
feilian swg devices-disconnect-list --all

# 获取某设备的 bypass 放行 token（供终端侧使用）
feilian swg devices-bypass-token --device-id did_xxx

# 对一批设备设置临时放行（bypass）
feilian swg devices-bypass-reconnect --data '{"device_ids":["did_xxx","did_yyy"]}'

# 强制断开一批设备的 SWG 连接
feilian swg devices-disconnect-create --data '{"device_ids":["did_xxx","did_yyy"]}'

# 恢复一批被强制断连的设备
feilian swg devices-disconnect-reconnect --data '{"device_ids":["did_xxx"]}'

# 查询 URL 网站过滤策略（支持分页，--all 拉全量）
feilian swg url-filtering-strategy-list --all --output table

# ========== Token 调试（新增 --expires-in，最短 7200 秒） ==========
# 手动获取 token，指定过期时间（单位秒，<7200 会自动夹紧）
feilian token --expires-in 14400
# 强制刷新 token
feilian token --refresh
```

#### B. 未封装/不确定？用 api 透传（兜底）

```bash
# GET
feilian api get /api/open/v1/department/list -q parent_id=od_xxx

# POST，带 body + 自动翻页
feilian api post /api/open/v1/user/list -d '{"department_id":"od_xxx"}' --all
```

#### C. 关键全局选项（按需加）

```
-p, --profile <name>        # 用哪个配置段，默认 default
-o, --output [json|table]   # json 便于解析，table 给人看，默认 json
    --lang [zh-CN|en-US]    # 返回语言
    --debug                 # 打印请求详情（token 会脱敏）
-k, --insecure              # 跳过 TLS 校验（仅内网/测试用）
```

### 第四步：解析结果

- 默认输出 JSON，直接解析即可。若响应中 `code != 0`，feilian 会以退出码 1 失败并把错误打到 stderr。
- 需要展示给用户看的列表数据，加 `-o table`。
- 分页接口加 `--all` 自动翻页聚合，不用手动循环。

## 常见错误码解读（附行动建议）

| code | 含义 | 下一步 |
|---|---|---|
| 40001 | AccessKey 无该接口权限 | 让用户在飞连管理后台-开放平台为 AK 添对应权限（SWG 接口需先开通 SWG 模块） |
| 164007 | 调用频率超限 | sleep 几秒后重试，或建议用户调大 limit 减少请求 |
| 164008 | IP 不在白名单 | 让用户把当前出口 IP 加入开放平台白名单 |
| 1001 / docId 无效 | 接口文档标识过期或占位错误 | 反馈维护者重新抓取最新 docId |
| token 相关 | 101 / 401 / 40101 / 40102 | 客户端会自动刷新一次；仍失败则 `feilian token --refresh` |

## 环境准备（仅首次需要）

项目根目录下执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/pip install -e .
```

然后：
```bash
feilian configure    # 交互式填 Endpoint + AK/SK，可选立即验证 token
```

## 安全红线

- **绝不**将 AccessKey Secret、access_token 明文写入任何临时脚本、文件或回复给用户。
- 需要传密钥时：走用户交互式输入、或环境变量、或已存在的 `config.toml`（权限 0600）。
- `--debug` 输出中 token 已被客户端脱敏，可放心查看。
