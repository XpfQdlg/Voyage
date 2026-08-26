# TokenWiser 检测规则规格 v1

## 产品与原则

- 输入习惯教练：检测用户向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议
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

### 2. secret_leak 疑似敏感信息

- 检测：API key 前缀（`sk-`、`ghp_`、`AKIA`、`Bearer`）、手机号、身份证号、邮箱、高熵片段（≥ 16 字符且熵 ≥ 4.5）
- 严重度：命中即 high（安全优先，唯一无条件提示的规则）
- 代价：waste = 0（这是风险，不是 token 浪费）
- 建议："检测到疑似密钥/手机号/身份证，发送给 AI 前请脱敏。"

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
| 疑似密钥 | 任意命中 |
| 单条超 6000 token | total ≥ 6000 |

## 备注

- missing_context 与 vague_instruction 的 waste = min(total, 300)，代表"若这轮白跑最多浪费这么多"，可叠加但不会超过输入总量
- 阈值均为 v1 初值，可按实际使用调整
