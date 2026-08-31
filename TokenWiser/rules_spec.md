# TokenWiser 检测规则规格 v1

## 产品与原则

- 言镜（TokenWiser）：检测用户向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议
- 只建议，不替换。工具永不改写用户内容
- 本地检测，零 API 调用。tiktoken 是唯一可选依赖，不装则降级为字符估算

## 交互模式

- 被动模式：严重度 high 时主动提示（不打断输入）；medium/low 静默记录
- 主动模式：用户调用 skill，查看 token 分割、检测到的习惯、量化代价

## 严重度定义

| 级别 | 行为 |
|---|---|
| high | 主动提示（stderr 警告 / 输入框提示） |
| medium | 静默记录，不主动提示 |
| low | 预留，暂未启用 |

## 代价算法

```
cost_input = total_tokens × input_per_million / 1,000,000
waste_cost = waste_tokens × input_per_million / 1,000,000
```

- 价格表在 `models.json`，放示例值，可修改；也可用环境变量 `PROMPT_HABITS_MODELS` 覆盖
- v1 只算输入成本；输出成本留待以后

## 规则清单

### 1. log_paste 大段日志/代码粘贴

- 检测：总行数 ≥ 10，且日志特征行占比 ≥ 50%。日志特征行 = 含时间戳、`ERROR|WARN|INFO|DEBUG|TRACE`、`Traceback`、`File "...", line N`、`at 0x...` 等
- 严重度：waste ≥ 200 token 或占比 ≥ 80% → high；否则 medium
- 代价：waste_tokens = 所有日志行的 token 数
- 建议："只保留报错/关键那几行，别贴整个日志，一般 5-10 行就够。"

### 2. secret_leak 疑似敏感信息（v2 增强，按 subtype 分类）

- 检测分类：
  - **credential（凭据）**：`sk-`、`ghp_`、`AKIA`、`Bearer`、PEM 私钥块、数据库连接串（mysql/postgres(ql)/mongodb/redis/amqp/jdbc/sqlserver://）、统一社会信用代码（须过 GB32100 校验位）、高熵片段（≥16 字符且熵 ≥4.5）
  - **pii（个人隐私）**：手机号、身份证号、银行卡号（16-19 位数字且须过 Luhn 校验）
  - **contact（联系方式）**：邮箱
- 严重度：credential/pii → high；仅 contact（邮箱）→ **medium**。v2 行为变更：邮箱原为无条件 high，降为 medium，避免把日常贴邮箱当高危事件
- 校验：银行卡过 Luhn、信用代码过 GB32100 校验位，普通长数字不会误报（订单号等）
- 代价：waste = 0（这是风险，不是 token 浪费）
- 建议（按 subtype）：
  - credential："检测到疑似密钥/凭据（API Key、Token、私钥、连接串等），发送给 AI 前请脱敏，避免凭据外泄。"
  - pii："检测到个人隐私信息（身份证/手机号/银行卡等），发送给 AI 前请脱敏，保护个人隐私。"
  - contact："检测到邮箱地址，若为个人联系方式请注意脱敏。"
- finding 附加字段：`subtype`（credential/pii/contact），向后兼容（旧数据无此字段）

### 3. oversized_request 单条输入过大

- 检测：total_tokens ≥ 3000
- 严重度：≥ 6000 → high；3000-5999 → medium
- 代价：waste = total − 3000
- 建议："建议拆成小步，每步一个目标，避免截断和降质。"

### 4. redundant_opener 冗余开场白

- 检测：开头匹配"你是一个AI助手""你好""您好"等模板，且开场白部分 ≥ 4 token
- 严重度：medium
- 代价：waste = 开场白的 token 数
- 建议："开场白不提供信息，直接进主题。"

### 5. missing_context 上下文/输出格式缺失

- 检测：total > 8、非纯跟进句、非单条 URL/路径、文本 ≥ 30 字、total < 3000、非日志主导，且不含目标/格式/约束关键词（格式、JSON、列表、要求、约束、用于、步骤 等）
- **多轮对话防误报**：`total ≤ 8` 的短句直接跳过；纯确认/跟进句（ok、好、可以、同步、推送、这样吧 等）视为"上一轮已有上下文"，跳过；整条就是一个 URL/本地路径的，跳过
- 严重度：medium
- 代价：waste = min(total, 300)。waste 不超过输入自身，避免多条命中时虚高
- 建议："开头一句话给目标，结尾指定输出格式（如 JSON/表格/列表），能省 1-2 轮往返。"

### 6. vague_instruction 指令模糊

- 检测：文本 < 40 字，且命中模糊句式（"帮我改一下""这个有问题""优化一下" 等）
- 严重度：medium
- 代价：waste = min(total, 300)。waste 不超过输入自身
- 建议："说清动作 + 对象 + 期望结果。例如'把 login.py 的登录逻辑改为 JWT 校验'。"

## 多命中的处理

- 全部记录进习惯库
- 被动提示最多显示前 2 条 high，避免刷屏
- **规则抑制**：已有具体严重问题（secret_leak / log_paste / oversized_request）时，不再补报泛化的 missing_context，避免噪音

## 系统注入剥离（hook / CLI）

hook 分析前调用 `strip_system_noise()` 剥掉注入的系统内容，避免把非用户输入记入习惯库：

- 逐块剥离：嵌入正文的 XML 块（command/task/system-reminder 标签对）、`Permission allow rule` 行、skill 加载头行
- 残渣判空：去掉所有 `<标签>` 后只剩空白，说明整条就是系统注入，判空跳过（不入库、不提示）
- 只剥标签不误伤正文：如 `<task-notification>...</task-notification>` 标签后的真实用户提问会保留
- CLI 可用 `--clean` 复用同一逻辑

## 被动提示触发汇总

| 触发场景 | 条件 |
|---|---|
| 日志粘贴超标 | waste ≥ 200 或占比 ≥ 80% |
| 敏感信息（凭据/隐私） | credential/pii 命中（high）；contact 邮箱仅 medium，不主动提示 |
| 单条超 6000 token | total ≥ 6000 |

## 敏感信息打码落库（v2）

命中 secret_leak 且 `TW_SANITIZE_ON_SECRET`（默认 1）开启时，落库的 input_preview
在加密前把敏感片段替换为 `[REDACTED:<类型>]`（`core.redact_sensitive()`）。
分析仍用原文；打码只影响存储的预览。stderr 提示、findings_json、面板均不出现敏感值本身。

## 实时显示（方向三）

主机制不依赖 agent 私有能力：

- **hook 行内提示（主机制）**：每次输入后按 `TW_HINT_INTERVAL`（默认 1800 秒，0=关闭）控频，
  在 stderr 输出"今日 X tok / ¥Y（浪费 Z%）"。口径与 status.py 一致（`core.aggregate_today_week`）。
- **状态栏 `status.py`（可选增强）**：仅原生支持 statusLine 的 agent（Claude Code / Gemini）自动配置；
  Cursor/Windsurf/Codex 不再强制。`--short` 输出单行短文本供 shell prompt。
- **面板 `server.py`（零 agent 依赖）**：浏览器 10s 轮询；新增 `GET /api/security` 安全事件统计。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TW_SECRET_ACTION` | warn | secret_leak 命中 high 时的动作：warn（exit 1 警告）或 block（exit 2 意图阻断，语义以实测为准） |
| `TW_SANITIZE_ON_SECRET` | 1 | 命中敏感信息时落库 preview 打码 |
| `TW_HINT_INTERVAL` | 1800 | hook 行内提示控频（秒），0=关闭 |

## 备注

- missing_context 与 vague_instruction 的 waste = min(total, 300)，代表"若这轮白跑最多浪费这么多"，可叠加但不会超过输入总量
- 阈值均为 v1 初值，可按实际使用调整
