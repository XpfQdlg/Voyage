# TokenWiser 技术方案（v3，定稿）

> 版本: v3（2026-08-31）｜ 目标读者: 接手实现的 Agent（在 TokenWiser 仓库内完成）
> 项目根: `D:\Desktop\Voyage\TokenWiser`（skill 经符号链接部署到 `~/.claude/skills/tokenwiser`，改动即生效）

## 一、背景与范围（本次定稿）

项目定位最终确认：**单机本地个人工具**（品牌名：言镜，AI 输入习惯教练）。不做团队模式、不做多设备统计、不做企业私有化叙事。

本次技术范围三块：

1. **方向二：敏感信息泄漏预警增强**（核心）。把现有 `rule_secret_leak` 扩成一套更准、可分类、可拦截、可打码的输入侧安全能力。这是真功能，也贴合网安专业。
2. **方向三：实时显示兼容化重构**。核心原则：**最小化依赖 agent 自身的私有功能，实现最大程度兼容**。hook 行内提示作为主机制，statusline 降级为可选增强。
3. **单机演示打磨**。面板加安全事件统计，演示数据覆盖敏感信息场景，输出文案更清晰。

以下内容为方案正文。全部改动必须保持**单机单用户模式向后兼容**。

---

## 二、现有架构速览（已核对代码，可直接引用）

| 文件 | 职责 | 关键接口 |
|---|---|---|
| `scripts/core.py` | 检测引擎，纯函数 | `analyze_text()`；`rule_secret_leak()`；`strip_system_noise()`；`_SECRET_PATTERNS` 为 `[(re.Pattern, label), ...]` |
| `scripts/store.py` | SQLite 持久化 | `record_check(result, meta, tool, ts)`；`fetch_checks()`；`fetch_records()`（全表拉取）；`migrate()`；表 `checks(...)`，`session_id/input_preview` 加密；库 `data/habits.db` |
| `scripts/hook.py` | Claude Code UserPromptSubmit 适配器 | stdin 收 `{"prompt","session_id",...}`；`analyze_text` → `record_check`；high 时 stderr 警告 + `exit 1`；否则 `exit 0` 静默 |
| `scripts/analyze.py` | 命令行入口 | `--text/--file/stdin`、`--model`、`--format json|text`、`--tokens`、`--clean`、`--record --tool`、`--cache-hit` |
| `scripts/history.py` | 个人周报 | 终端文本输出 |
| `scripts/server.py` | Flask 本地面板 | `/api/summary` `/api/timeline` `/api/habits` `/api/recent`；只监听 `127.0.0.1:8000`；前端 `scripts/dashboard/index.html` + `static/echarts.min.js`（本地无 CDN） |
| `scripts/status.py` | statusline 实时消耗 | stdout 纯文本 + ANSI；每次刷新独立进程全表扫库聚合；异常降级不崩 |
| `scripts/demo_data.py` | 演示数据生成 | `--days --per-day --seed`；真实检测管线 |
| `scripts/crypto.py` | AES-256-GCM | 密钥 `~/.tokenwiser/tw_key` |
| `scripts/install.py` | 一键安装 | 按 agent 写 hook + statusLine；Claude 写 `~/.claude/settings.json`（refreshInterval 5s）；Gemini 写 `~/.gemini/.../settings.json`（无刷新间隔）；Cursor/Windsurf 只打印第三方扩展指引；Codex 只打印内置 used-tokens 提示 |
| `models.json` | 模型定价 | `usd_to_cny`；模型键含峰谷定价 |
| `rules_spec.md` | 规则规格文档 | 需随规则变更同步更新 |

计费核心：`core.cost_rmb()`，按记录时刻与模型取价，统一人民币。本方案不新增计费逻辑。

---

## 三、方向二：敏感信息泄漏预警增强

### 3.1 规则扩充与分类（`scripts/core.py`）

把 `_SECRET_PATTERNS` 从 `(模式, 名称)` 重构为 `(模式, 名称, subtype)`。新增 `subtype` 字段，取值 `credential` / `pii` / `contact`。finding 增加可选字段 `subtype`（不改变既有字段，向后兼容）。

新增规则：

| 类别 | 模式 | 严重度 | 校验 |
|---|---|---|---|
| credential | 数据库连接串 `\b(?:mysql\|postgres(?:ql)?\|mongodb\|redis\|amqp\|jdbc\|sqlserver)://\S+` | high | 无 |
| credential | PEM 私钥块 `-----BEGIN (?:RSA \|EC \|OPENSSH )?PRIVATE KEY-----` | high | 无 |
| credential | 统一社会信用代码：18 位含字母 | medium | GB32100 校验位 `_uscc_valid()` |
| pii | 银行卡号：16-19 位数字 | high | Luhn 校验 `_luhn_valid()` |
| contact | 邮箱（现有） | **medium**（行为变更，原为 high） | 无 |

现有规则归类：

- `credential`：sk-、ghp_、AKIA、Bearer、连接串、PEM 私钥、高熵片段。
- `pii`：手机号、身份证、银行卡。
- `contact`：邮箱。

实现要求：

- `_luhn_valid()` 与 `_uscc_valid()` 为纯函数，带 docstring 与校验原理注释。
- 校验不过的不算命中，避免把普通长数字误报成卡号/信用代码。
- **行为变更**：邮箱由 high 降为 medium，避免把日常贴邮箱当高危。必须在 `rules_spec.md` 与 hook 顶部注释标注。

### 3.2 hook 动作：警告 / 阻断（`scripts/hook.py`）

环境变量 `TW_SECRET_ACTION`：

- `warn`（默认）：findings 含 high 级 `secret_leak` 时 stderr 提示 + `exit 1`，非阻塞。
- `block`：`exit 2`，意图阻断 prompt 发送。

**实现约束**：exit code 语义以实测为准。先在本地跑小实验，确认 UserPromptSubmit 下 `exit 2` 是否阻断、`exit 1` 是否仅警告。实测结论写进 hook.py 顶部注释。若当前版本不支持阻断，block 退化为"更醒目的警告"，并在 `rules_spec.md` 记录。

提示规则：stderr 只输出命中**类型**（如"检测到 API Key、身份证号"），**绝不回显敏感值本身**。

### 3.3 敏感片段打码后落库（`core.py` + `store.py` 调用方）

- `core.py` 新增 `redact_sensitive(text) -> str`：复用 `_SECRET_PATTERNS`，把命中片段替换为 `[REDACTED:<label>]`。
- `hook.py` / `analyze.py` 在调 `record_check` 前判断：findings 含 `secret_leak` 且 `TW_SANITIZE_ON_SECRET`（默认 true）时，把 `meta["prompt"]` 替换为 `redact_sensitive(prompt)` 再传。
- 分析本身始终用原文（`analyze_text` 输入不变），打码只影响落库的 input_preview。
- `findings_json` 不存敏感原文（现只存类型），确认 `detect/advice` 不拼命中值。

---

## 四、方向三：实时显示兼容化重构

### 4.1 目标与原则

**核心原则**：最小化依赖 agent 自身的私有功能，实现最大程度兼容。

现状问题（已审查确认）：

- statusline 是 agent 的地盘，每种 agent 配置格式不同，刷新间隔由 agent 决定。
- Claude Code 原生支持且能设 5s 刷新；Gemini 原生支持但刷新不可控；Cursor/Windsurf 需第三方扩展；Codex 不支持自定义 status 命令（我们的数据显示不出来）。
- 附带问题：`status.py` 每次刷新全表扫库，数据量大时变慢；`install.py` 写死 `python`，Windows 上 python 不在 PATH 时挂。

方案：把实时反馈拆成三层。**第 1 层为主机制，零新增 agent 依赖；第 2、3 层降级为可选。**

### 4.2 第 1 层（主机制）：hook 行内提示（`scripts/hook.py`）

hook 是 agent 生态里最通用的输入触发机制，比 statusline 普及得多（Claude / Gemini / Cursor 均支持 hook），不依赖私有状态栏能力。

实现：

- `hook.py` 在 `record_check` 之后，读今日聚合，向 stderr 追加一行：
  `今日 12.3k tok / ¥0.86（浪费 32%）`
- **控频**：写 `~/.tokenwiser/last_hint` 存上次提示时间戳，环境变量 `TW_HINT_INTERVAL`（默认 1800 秒）内不重复提示；设 0 关闭。
- 不破坏现有 high 警告逻辑。high 警告与行内提示是两件事，各自独立输出。
- 聚合计算复用 `status.py` 的按天聚合逻辑，抽成公共函数（见 4.4）。

### 4.3 第 2 层（完整视图）：server.py 面板（保持现状，打磨）

- 面板已零 agent 依赖（本地 Flask + 浏览器 10s 轮询），是"兼容性最强的实时显示"。
- 本方案只打磨：加安全事件卡片（见 5.1），不做结构性改动。

### 4.4 第 3 层（可选增强）：statusline 降级

- 从 `status.py` 抽出按天/按周聚合的纯函数（如 `aggregate_today_week(rows)` 或按日期 SQL 查询），hook 行内提示与 status.py 共用，保证口径一致。
- `status.py` 性能优化：改为按日期 SQL 聚合（`WHERE ts >= 本周一`），不再全表拉取后 Python 聚合。
- 可选新增 `--short`：输出单行短文本（`今日 12.3k tok ¥0.86`），供用户配进 shell prompt（powerline / PS1），与 agent 完全解耦。
- `install.py` 调整：
  - Claude Code / Gemini 原生支持：继续自动配置（现状保留）。
  - Cursor / Windsurf / Codex：**不再折腾**。只打印"可选增强"指引，明确标注非必需，不引导用户装第三方扩展。
  - 写 statusLine 命令时用 `sys.executable` 拼绝对 python 路径，不用裸 `python`。

### 4.5 明确的不做（方向三内）

- 不实现浏览器扩展、系统托盘、桌面通知等新载体（依赖额外安装，违背"最小化依赖"）。
- 不实现多设备同步（本方案整体范围外）。

---

## 五、单机演示打磨

1. **面板安全事件统计**：
   - `server.py` 新增 `GET /api/security?days=30` → 近 N 天 `secret_leak` 命中次数与类型分布。
   - `scripts/dashboard/index.html` 加"安全事件"卡片：命中次数 + 类型占比。
2. **演示数据**（`demo_data.py`）：现有 `_secret_prompt()` 已能造敏感记录。可选加 `--security-weight` 提高占比，让安全卡片有内容。不做多用户改造。
3. **输出文案**：`analyze.py --format text` 对 `subtype=credential` 强调"发送前脱敏，避免凭据外泄"；`subtype=pii` 强调"涉及个人隐私"。不改 JSON 结构。

---

## 六、明确不做（本次范围外）

以下内容在早期方案中存在，本次定稿**全部移除**，不要实现：

- 团队模式：`user_id` / `team_id` 列、身份注入（`config.py`）、团队聚合报告（`report.py`）、面板团队视图。
- 多设备统计、多设备同步。
- 企业私有化部署、收集器模式、HTTP 上报。
- 面向企业审计的合规报告。

若接手 Agent 在代码里发现以上相关残留（如旧 plan 引用），忽略即可，不实现。

---

## 七、验收测试（完成后必须逐条跑）

新增 `scripts/test_plan.py`，覆盖：

1. **规则精度**：
   - 正例：Luhn 合法的银行卡号、标准 PEM 私钥块、`mysql://user:pass@host:3306/db` 连接串、校验位正确的信用代码。
   - 反例：18 位普通数字不报卡号、校验位不符的信用代码不报、版本号/哈希串不误报。
   - 邮箱命中为 medium，其余分类正确。
2. **redact 打码**：含 `sk-` 的文本经 `redact_sensitive()` 后不再出现原值，`[REDACTED:` 占位出现；不含敏感信息的文本原样返回。
3. **hook 行为**：
   - `TW_SECRET_ACTION=warn` 时含密钥输入 → exit 1 且 stderr 无敏感值；`block` 时按实测结论断言。
   - 行内提示：同 `TW_HINT_INTERVAL` 内第二次输入不重复提示；设 0 关闭；无库时不提示。
4. **status.py 优化**：SQL 聚合结果与旧全表扫聚合一致（可对同一库断言数值相等）；`--short` 输出单行。
5. **install.py**：生成的 statusLine 命令含绝对 python 路径；Cursor/Windsurf/Codex 分支只打印指引、不写配置、不报错。
6. **面板**：`/api/security` 返回正常，页面 `127.0.0.1:8000` 打开无 JS 报错。
7. **回归**：`demo_data.py --days 30 --per-day 10 --seed 42` 生成的库，面板个人视图与改造前一致；`analyze_text` 输出结构未变。

---

## 八、文档同步

- `rules_spec.md`：新增规则（含 subtype、严重度）、邮箱降级行为变更、block 模式、打码策略。
- `README.md`：补敏感信息预警、`TW_SECRET_ACTION` / `TW_SANITIZE_ON_SECRET` / `TW_HINT_INTERVAL`、实时显示三层说明。
- `USAGE.md`：同步环境变量与安全特性、statusline 标注"可选增强"。
- `ROADMAP.md`：更新待办，删除团队模式相关条目。
- 版本号建议升到 v2。

---

## 九、红线（务必遵守）

- **不得破坏单机单用户模式**。所有新功能默认关闭或默认行为等于现状。
- **计费逻辑单一来源**：成本一律走 `core.effective_price` + `core.cost_rmb`，本方案不新增计费代码。
- **敏感值不落盘、不回显**：stderr、findings_json、面板、报告均只出现类型，不出现值。
- **实时显示不依赖 agent 私有能力**：主机制（hook 行内提示）与完整视图（面板）必须零新增 agent 依赖；statusline 只作为可选增强。
- **前端不引 CDN**，离线可用。
- 命名一律 snake_case。
- 改完跑通"安装 → 生成演示数据 → 面板 → 安全卡片 → hook 行内提示"全链路，再交付。
