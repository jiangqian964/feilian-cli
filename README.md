# feilian-cli · 飞连开放平台 CLI

> 面向 IT 管理员的**飞连（SealSuite）开放平台命令行工具**。基于规格驱动的动态命令架构，将飞连 334 个开放 API 封装为统一的 CLI 子命令，配合环境变量 / 配置文件双模式鉴权、自动 token 刷新、分页聚合与 AI Agent 原生集成。

| 维度 | 值 |
|---|---|
| 📦 版本 | `0.1.3` |
| 🐍 Python | `>= 3.9`（3.9 / 3.10 / 3.11 / 3.12 均测试通过） |
| 🧩 命令别名 | `feilian` 或 `fl` |
| 📂 API 覆盖 | **18 个分类 · 334 个接口**（GET 143 · POST 191） |
| ✅ 测试 | [![pytest 23/23](https://img.shields.io/badge/pytest-23%2F23-brightgreen)](tests/) `0.21s` |
| 🔐 Token 默认过期 | **最短 7200 秒（2 小时）**，可通过 `--expires-in` / 环境变量覆盖 |

---

## ✨ 特性亮点

- **📐 规格驱动（Spec-Driven）**：全部命令与参数由 `src/feilian_cli/spec/apis.json` 动态生成，飞连官方文档更新后**只需维护一份 JSON 规格，零代码新增命令**（`registry.py` 自动构造 Click 命令树 + 中文帮助 + 参数校验）。
- **🧭 18 个命名分组，覆盖全产品线**：组织架构 / 终端管理 / ZTNA 零信任 / NAC 准入 / 应用 / 审批 / SWG 安全 Web 网关 / 动态控制 … 内置关键字搜索引擎 `feilian search <中文>`。
- **🔄 自动 Token 管理**：AccessKey ↔ access_token 自动换取，缓存于 `~/.cache/feilian/token_<profile>.json`（`0600`）；过期前 60 秒自动续期；遇到 401 类错误自动刷新并重试一次。
- **⏱️ 强制最短过期 7200 秒**：Token 接口的 `expires_in` 参数与文档保持一致，低于 2 小时的请求会被客户端自动夹紧（clamp），避免意外生成短时效 token。
- **📄 分页一键拉全量**：所有 offset/limit 风格接口支持 `--all` 标志，自动循环翻页聚合返回；无需手动写循环。
- **🔧 环境变量 & 多 Profile**：`FEILIAN_ENDPOINT / FEILIAN_ACCESS_KEY_* / FEILIAN_PROFILE / FEILIAN_TOKEN_EXPIRES_IN` 全部可覆盖；多 profile 并行管理生产 / 预发布 / 演示环境。
- **🔎 兜底透传 + JSON 合并**：未在规格中的新接口可用 `feilian api <method> <path>` 直连；复杂 Body 支持 `--data '{}'`、`@file.json`、`@-` 管道三种写法并与命令行选项合并。
- **🤖 AI Agent 原生集成**：随项目附带 [Trae Skill](.trae/skills/feilian-cli/SKILL.md)，在 Trae / TraeWork 中打开本目录即可直接以自然语言驱动 CLI（"帮我列出 SWG 临时放行设备"、"查惊涛骇浪的笔记本装了哪些软件" 等）。
- **🧪 18 个单元测试全绿**：覆盖 token 缓存 / 过期刷新 / 端点变更失效 / 业务错误码 / 401 自动重试 / GET+POST 翻页 / 命令树动态生成 / search 命令。

---

## 🚀 2 分钟快速上手

```bash
# 1. 克隆 & 安装（开发模式，支持热改）
git clone git@github.com:jiangqian964/feilian-cli.git && cd feilian-cli
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e '.[dev]'   # .[dev] 附带 pytest / respx

# 2. 交互式配置 Endpoint + AK/SK（Secret 输入不回显）
.venv/bin/feilian configure
#   Endpoint: https://your-company.feilian.cn       （不要尾部 /）
#   Access Key ID: FL_AK_xxxxxxxxxxxxxxxx
#   Access Key Secret: <粘贴不显示内容，直接回车>
#   Verify token now? [y/N] y

# 3. 跑第一条命令
.venv/bin/feilian org department-list --all --output table
```

安装后可执行文件路径：
- 项目内：`.venv/bin/feilian`（推荐，避免污染全局）
- 若 `pip install` 到全局：`feilian` / `fl`（`entry_points` 同时注册了两个别名）

---

## 🔐 配置

### 配置向导（推荐）

```bash
feilian configure
```

交互式写入 `~/.config/feilian/config.toml`（权限 `0600`），支持多 profile。典型文件内容：

```toml
[default]
endpoint         = "https://your-company.feilian.cn"
access_key_id     = "FL_AK_xxxxxxxxxxxxxxxxxxxx"
access_key_secret = "xxxxxxxxxxxxxxxxxxxxxxxxxx"

[staging]
endpoint         = "https://staging-feilian.example.com"
access_key_id     = "FL_AK_xxxxxxxxxxxxxxxxxxxx"
access_key_secret = "xxxxxxxxxxxxxxxxxxxxxxxxxx"
```

切换 profile：`feilian -p staging org department-list`

### 环境变量覆盖（适合 CI / Secret 不落盘）

| 变量名 | 说明 | 默认值 |
|---|---|---|
| `FEILIAN_ENDPOINT` | 飞连服务端地址（覆盖配置文件） | — |
| `FEILIAN_ACCESS_KEY_ID` | AccessKey ID | — |
| `FEILIAN_ACCESS_KEY_SECRET` | AccessKey Secret | — |
| `FEILIAN_PROFILE` | 选择使用的配置段 | `default` |
| `FEILIAN_TOKEN_EXPIRES_IN` | token 默认过期秒数，**< 7200 会自动夹紧到 7200** | 文档服务端默认 |
| `FEILIAN_CONFIG_DIR` | 自定义配置文件目录（替代 `~/.config/feilian`） | `~/.config/feilian` |
| `FEILIAN_CACHE_DIR` | 自定义 token 缓存目录（替代 `~/.cache/feilian`） | `~/.cache/feilian` |

> ⚠️ **安全红线**：不要在脚本、crontab、git 仓库中明文写入 `FEILIAN_ACCESS_KEY_SECRET`。推荐通过 Vault / Secrets Manager / Shell Profile 导出，或直接走交互式配置。

---

## 🗂️ 命令分组（18 分类 · 334 接口）

18 个顶级分类对应 18 组 Click 子命令，接口数量与中文名对应关系如下：

| Slug | 中文分类 | 接口数 | | Slug | 中文分类 | 接口数 |
|---|---|---:|---|---|---|---:|
| `org`      | 组织架构 | **41** | | `software` | 软件管理 | 19 |
| `ztna`     | 零信任接入 | **67** | | `admin`    | 管理员 | 10 |
| `nac`      | 网络准入 | **31** | | `control`  | 终端管控 | 8 |
| `app`      | 应用管理 | **24** | | `swg`      | **安全 Web 网关** | **14** ⭐ |
| `device`   | 终端管理 | **35** | | `approval` | 审批 | 2 |
| `security` | 终端安全 | 27 | | `auth`     | 身份认证 | 2 |
| `system`   | 系统配置 | 37 | | `msg`      | 消息网关 | 2 |
| `repo`     | 软件库 | 13 | | `it`       | IT 管理 | 1 |
| | | | | `mdm`      | MDM 管控 | 1 |
| | | | | `dynamic`  | 动态控制 | 0（占位·下期开放） |

### 通用探索命令

```bash
feilian --help                 # 查看全部 18 个分组 + 内置命令
feilian org --help             # 单分组下的所有子命令（中文描述 + Path/Method）
feilian org user-list --help   # 单接口帮助：中文名、参数列表（必填带 *）、官方示例 URL
feilian search 网站过滤        # 按中文关键字 / 路径 / 命令名模糊搜索
```

---

## 💼 典型场景速查

### 1. 组织架构 / 员工信息

```bash
# 拉全量一级部门，表格输出
feilian org department-list --all -o table

# 查某部门下员工（--all 自动翻页，避免手动 offset 循环）
feilian org user-list --department-id od_xxxxxxxx --all

# 建部门：命令行选项 + JSON Body 合并（命令行优先覆盖 JSON 同名字段）
feilian org department-create --name "安全审计组" \
    --data '{"parent_id":"od_xxxxxxxx","order":10}'
```

### 2. 终端管理 / 软件清单

```bash
# 按关键字 "TUF" 模糊搜索设备名 / SN，查看基本信息
feilian device search --device-name TUF

# 查指定 did 设备的硬件详情（CPU/硬盘/网卡/TPM/电池）
feilian device search --did 6a8556394d0c3978e7d01b0bd96ebd4a

# 🔍 查单台设备装了哪些软件（56 款全量表格输出）
feilian device software-list --did 6a8556394d0c3978e7d01b0bd96ebd4a \
    --all -o table

# 查全网软件变更（最近一周新装/卸载）
feilian device software-recently-update --all
```

### 3. 🆕 安全 Web 网关（SWG · v0.1.0 新增 7 个命令）

```bash
# ============== 临时放行（Bypass） ==============
feilian swg devices-bypass-list --all -o table                  # 列所有临时放行设备
feilian swg devices-bypass-token --device-id did_xxx            # 获取某设备的 bypass token
feilian swg devices-bypass-reconnect \                          # 对一批设备下发临时放行
    --data '{"device_ids":["did_a","did_b","did_c"]}'

# ============== 强制断连（Disconnect） ==============
feilian swg devices-disconnect-list --all -o table              # 列所有被强制断连设备
feilian swg devices-disconnect-create \                         # 对一批设备强制断连
    --data '{"device_ids":["did_a","did_b"]}'
feilian swg devices-disconnect-reconnect \                      # 恢复一批被断连的设备
    --data '{"device_ids":["did_a"]}'

# ============== 网站过滤策略 ==============
feilian swg url-filtering-strategy-list --all -o table          # 查询 URL 网站过滤策略全量
```

### 4. Token 调试（新增 `--expires-in`）

```bash
feilian token                   # 打印当前缓存的 token 摘要（不回显明文）
feilian token --show            # 显示完整 40 位 access_token
feilian token --refresh         # 强制丢弃缓存并立即换新 token
feilian token --expires-in 14400   # ⭐ 新：请求 4 小时有效期（<7200 会自动夹紧为 7200）
```

> 另外，环境变量 `FEILIAN_TOKEN_EXPIRES_IN=21600` 可以让后续所有接口自动带 6 小时有效期。

### 5. ZTNA 零信任接入

```bash
feilian ztna app-list --all -o table                            # 查所有发布的应用
feilian ztna app-detail --app-id app_xxx                        # 单应用详情
feilian ztna policy-list --all                                  # 访问策略（用于审计权限一致性）
```

### 6. 未封装接口兜底透传（新增接口临时调用）

```bash
# GET：Query 参数用 -q key=value，多个 -q 可叠加
feilian api get /api/open/v1/department/list -q parent_id=od_xxx -q limit=100

# POST：Body 用 -d 传 JSON 字符串 / @文件 / @- 管道
echo '{"name":"新部门"}' | feilian api post /api/open/v1/department/create -d @-
```

### 7. 🧹 设备去重（SN 重复清理 · v0.1.1 新增）

同一序列号注册了多个 did（重复注册/重装客户端/克隆模板）时，一键保留最近活跃设备并清理其余：

```bash
# 1. 预览去重计划（默认不执行，安全）
feilian device-dedup --dry-run

# 2. 只处理指定 SN
feilian device-dedup --sn <SERIAL> --dry-run

# 3. 确认无误后执行（先批量置失效，再批量清理）
feilian device-dedup --yes
```

- 判定规则：按设备状态（活跃 > 休眠 > 失效）+ 最近在线时间，每组保留 1 台；
- 底层走两个原生接口：`device status-batch-update`（置失效）+ `device invalid-batch-delete`（清理，含分组/软件统计等关联数据）；
- 均按 did 精确定位，克隆模板导致的 MAC/SN 相同设备也能逐台处理；
- 删除不可逆，必须显式 `--yes` 才执行。

### 8. 📤 导出在线设备清单（SN / MAC / 计算机名 / 邮箱 → CSV · v0.1.3 新增）

拉取指定系统（如 Windows）在线设备，导出 `device_map.csv`（设备 SN、MAC、计算机名、当前登录员工邮箱）：

```bash
# 一键导出（默认：状态=活跃、系统=windows、输出 device_map.csv）
python3 scripts/export_device_map.py

# 自定义：休眠设备 / macOS / 指定输出路径
python3 scripts/export_device_map.py --status 2 --client-os mac --out mac_map.csv

# 复用已保存的 device search 结果（跳过重新拉取）
python3 scripts/export_device_map.py --input /tmp/win.json --out device_map.csv
```

- 数据链路：`device search`（按状态+OS 筛选，`--all` 全量）→ `org user-get`（按 user_id 关联登录员工邮箱，去重缓存）→ CSV；
- 表头：`did, serial_number, mac_addrs, device_name, user_id, email`；多网卡 MAC 以 `;` 合并；
- CSV 为 UTF-8 带 BOM，Excel 直接打开中文不乱码；
- 个别账号未配置邮箱（手机号注册/测试号）`email` 留空，属正常。

---

## 🧭 全局选项

所有命令（含分类子命令、api 透传、token、search）共享：

```
-p, --profile <NAME>           选择配置段 [默认: default]
    --endpoint <URL>           一次性覆盖服务端地址（不写回配置）
    --lang [zh-CN|en-US]       响应语言 [默认: zh-CN]
-o, --output [json|table|raw]  json: 管道/脚本友好；table: 人工可读 [默认: json]
    --debug                    打印请求方法、路径、响应 code；token 自动脱敏
-k, --insecure                 跳过 TLS 证书校验（仅限内网/自签名环境）
```

---

## 🚨 常见错误码与行动建议

| code | 含义 | 下一步 |
|---|---|---|
| **40001** | AccessKey 无该接口权限 | 在飞连后台「开放平台 → 应用管理 → API 权限」为对应 AK 勾选分类；SWG 接口需同时开通「安全 Web 网关」模块授权 |
| **164007** | 调用频率超限 | sleep 2~5 秒后重试；或将 `--limit` 放大（默认 20，最大 200）减少请求数 |
| **164008** | 来源 IP 不在白名单 | 后台「开放平台 → 应用管理 → 安全设置 → IP 白名单」追加出口公网 IP |
| **1001** / docId 无效 | 规格中接口文档 ID 过期或占位 | 贴出具体命令和错误到 Issue，重新抓取官方文档的最新 `docId=` 更新 `apis.json` |
| **101 / 401 / 40101 / 40102** | token 失效或签名错误 | 客户端自动刷新 1 次；仍失败则 `feilian token --refresh`；检查系统时间是否偏离 UTC 超过 5 分钟 |
| **连接超时 / `context deadline exceeded`** | 网络或 Endpoint 错误 | 确认 Endpoint 不包含多余路径、企业 VPN / 代理是否开启；或追加 `--insecure` 排查 TLS 链问题 |

---

## 🤖 AI Agent 集成（Trae / TraeWork）

项目根目录下 `.trae/skills/feilian-cli/SKILL.md` 已包含 Agent 行为规范（含 334 接口覆盖描述、SWG 示例、环境变量说明）。

**在 Trae 中打开本项目后，直接用自然语言即可驱动 CLI**，例如：

| 你说的话 | AI 实际执行的命令 |
|---|---|
| "帮我列出所有一级部门" | `feilian org department-list --all -o table` |
| "惊涛骇浪的笔记本装了哪些软件？" | `feilian device search --did …` → `feilian device software-list --did …` |
| "把 did_a did_b 临时放行 SWG 1 小时" | `feilian swg devices-bypass-reconnect --data '{"device_ids":[...]}'` |
| "生成一个 6 小时有效期的 token" | `feilian token --expires-in 21600 --show` |
| "搜一下和『漏洞修复』相关的命令" | `feilian search 漏洞修复` |

---

## 🧪 开发与测试

```bash
# 安装开发依赖（pytest + respx）
.venv/bin/pip install -e '.[dev]'

# 运行全部测试（18 case，0.28s）
.venv/bin/pytest tests/ -v

# 只跑 registry 相关（验证 apis.json 修改后的命令树）
.venv/bin/pytest tests/test_registry.py -v
```

### 项目结构

```
├── pyproject.toml                      # 打包元数据：name=feilian-cli、Python>=3.9、依赖 click/httpx/rich/tomli(<3.11)
├── setup.cfg                           # egg_info 配置
├── README.md                           # 本文档
├── .trae/
│   └── skills/feilian-cli/SKILL.md     # 🤖 AI Agent 调用规范（Trae 自动识别）
├── src/feilian_cli/
│   ├── main.py                         # CLI 根入口：全局选项 + configure/token/search/api 内置命令
│   ├── config.py                       # config.toml 读写 + 多 profile + 环境变量覆盖 + 0600 权限
│   ├── auth.py                         # access_token 获取 / 缓存 / 过期刷新 / expires_in 夹紧 7200
│   ├── client.py                       # httpx.Client 封装：统一错误 / 401 重试 / offset-limit 翻页（--all）
│   ├── output.py                       # json / table / raw 三种输出格式 + Rich 渲染
│   ├── registry.py                     # 规格驱动核心：读 apis.json → 动态构造 Click 命令树 + 参数校验 + search 索引
│   └── spec/apis.json                  # ⭐ 334 接口规格（version=2026-09-10T00:00:00.000Z）
└── tests/
    ├── test_auth.py      (5 case)  token 缓存 / 过期刷新 / 端点变更失效 / 强制刷新 / 鉴权失败
    ├── test_client.py    (5 case)  成功返回 / 业务错误 / 401 自动重试 / GET 翻页 / POST 翻页
    └── test_registry.py  (8 case)  规格加载 / 分组注册 / leaf help / 动态命令调用 / data 合并 / api 透传 / 错误退出码 / search
```

---

## 🧩 规格驱动工作原理（给贡献者）

`src/feilian_cli/spec/apis.json` 是整个工具的"单一真实来源（SSOT）"，结构如下：

```jsonc
{
  "version": "2026-08-25T09:38:27.327Z",   // 最后同步文档的时间戳
  "categories": [
    {"slug": "swg", "name": "安全 Web 网关", "description": "…"}
  ],
  "apis": [
    {
      "name": "devices-bypass-list",       // 命令名 → feilian swg devices-bypass-list
      "title": "获取临时放行设备列表",      // 中文描述（--help、search 索引用）
      "category": "swg", "method": "GET",  // 归组 + HTTP 方法
      "path": "/api/open/v1/swg/devices/bypass/list",
      "docId": "6a62d7aa1222100509042921", // 官方文档锚点（用于 404 时定位源头）
      "query": [ /* 列表参数：name/type/required/description */ ],
      "body":  [ /* 对于 POST 接口，Body 参数定义（支持嵌套结构） */ ]
    }
  ]
}
```

当飞连官方发布新接口时，**无需改动 Python 代码**，只需在 `apis.json` 的 `apis` 数组中追加一条记录、如涉及新分类同步追加到 `categories`，再用 `pytest tests/test_registry.py -v` 验证命令树生成即可。

---

## 📝 Release Notes

### 🎉 v0.1.3（2026-09-11）

- 🧰 新增 `scripts/export_device_map.py`：一键导出在线设备清单 CSV（SN / MAC / 计算机名 / 登录员工邮箱），支持按状态、操作系统筛选；配套新增 README 场景「导出在线设备清单」。
- 🧩 新增 Agent Skill `feilian-device-map`（`workspace/.user_skills/`）：固化"拉设备 → 关联邮箱 → 导出 CSV"工作流与接口踩坑。

### 🎉 v0.1.2（2026-09-10）

- 🆕 **新增 78 个接口**（256 → 334）：
  - **零信任接入-代理访问管理（28 个）**：代理节点 / 代理应用 / 应用标签 / 引流策略 / ACL 策略 / 规则模板 / 进程规则 / 在线连接（`feilian ztna server-* / app-tag-* / application-* / traffic-policy-* / acl-policy-* / rule-template-list / process-rule-list / connection-list`）；
  - **安全 Web 网关-网站过滤（7 个）**：策略详情 / 生效对象 / 状态 / 分类范围 / 优先级 / 搜索 / 删除（`feilian swg url-filtering-strategy-*`）；
  - **终端管理-可信设备（9 个）**：状态更新 + 策略增删改查 / 启停 / 生效对象（`feilian device trusted-device-*`）；
  - **软件管理（8 个）**：软件安装管控 / 进程运行管控策略（`feilian software install-control-* / process-control-*`）；
  - **终端安全-外设管控（4 个）**：策略 + 生效对象（`feilian security dlp-peripheral-*`）；
  - **网络准入-访客账号（3 个）**：创建 / 编辑 / 删除（`feilian nac wifi-guest-*`）；
  - **零信任接入-访问资源 V2（4 个）**：`feilian ztna vpn-acl-resource-*-v2`；
  - **系统配置（14 个）**：地址资源标签更新/删除、自定义分类域名、标签库资源标签、网络区域；
  - **组织架构（1 个）**：获取用户增量更新列表（`feilian org user-incremental-list`）。
- 🧩 新增 `scripts/gen_new_apis.py`：把文档站抓取的新接口 JSON 一键合入 `apis.json`（幂等，按 path 去重）。

### 🎉 v0.1.1（2026-09-10）

- 🧹 **新增 `device-dedup` 去重命令**：同一 SN 多 did 自动保留最近活跃一台，其余置失效并清理；默认仅预览，`--yes` 才执行。
- 🆕 **新增 2 个终端管理接口**（254 → 256）：
  - `device status-batch-update`：按 did 批量更新设备状态（置失效）；
  - `device invalid-batch-delete`：批量清理失效设备及关联数据（`clean_range` 传 `[0]`）。
- 🧪 **单测 18 → 23**：新增 `tests/test_dedup.py` 覆盖保留/删除选择规则（状态优先级 + 最近在线）。

### 🎉 首次正式发布 · `0.1.0`

- ✨ **基础框架落成**：规格驱动架构，从 apis.json 生成 254 条 Click 子命令，参数与文档保持一致。
- 🆕 **新增 `swg` 安全 Web 网关分类**：7 条全新接口 — 临时放行(bypass)×3、强制断连(disconnect)×3、网站过滤策略×1。
- 🆕 **新增 `dynamic` 动态控制分类**：占位分类（随飞连后续版本开放接口）。
- 🔐 **Token `expires_in` 支持**：
  - `feilian token --expires-in <seconds>` 命令行选项；
  - 环境变量 `FEILIAN_TOKEN_EXPIRES_IN` 全局默认；
  - **强制夹紧最短 7200 秒**，防止生成过短时效 token。
- 🗺️ **3 个已有接口 docId 更新**：Token 获取、发送验证码、校验验证码 — 全部与最新开放平台文档对齐（新格式 `6a62d7aa122210050904xxxx`）。
- 🧪 **单测覆盖率**：18 条 pytest case，0.28s 全绿通过，覆盖 auth / client / registry 三大核心模块。
- 🤖 **Trae Skill 1.0**：`.trae/skills/feilian-cli/SKILL.md` v1，描述 18 分类 / 254 接口调用规范，支持 AI 自动识别路径、配置状态检查与错误码解读。

---

## 📄 License

本项目采用 **MIT License** — 允许商用、修改、分发、私有使用，仅需保留版权声明与许可声明。详见 [LICENSE](LICENSE) 文件。

```
Copyright (c) 2026 jiangqian964
Released under the MIT License
```

## 🙏 致谢

- [飞连（SealSuite）开放平台文档](https://www.feilian.cn/docs/)：提供 254 个接口的规范定义与参数说明。
- 项目维护者：[@jiangqian964](https://github.com/jiangqian964)
