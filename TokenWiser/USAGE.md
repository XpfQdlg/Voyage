# TokenWiser 使用说明

面向使用者的配置与使用指南。TokenWiser 是平台无关的，不绑定任何特定 AI 工具。

## TokenWiser 是什么

检测你向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议。

覆盖的习惯：
- 大段粘贴日志/代码（只留报错那几行就够了）
- 输入中带敏感信息：密钥/Token/私钥/连接串（凭据类）、身份证/手机号/银行卡（隐私类）、邮箱（联系方式）
- 单条输入过长（该拆成小步）
- 冗余开场白（"你是一个AI助手"这类废话）
- 缺上下文/输出格式
- 指令模糊（"帮我改一下"没说改什么）

核心原则：**只建议，不替换**。工具从不改写你的内容。

## 两种使用模式

| 模式 | 触发 | 效果 |
|---|---|---|
| 被动 | 自动（接 hook 后） | 输入严重时才提示，不打断你 |
| 主动 | 你调用 | 分析**当前这条输入**的分词、坏习惯、量化代价；跨对话趋势看 `history.py` 周报 |

## 环境要求

- Python 3.9+
- 可选：tiktoken（精确分词，`pip install tiktoken`）。不装也能跑，用字符估算

## 快速开始（命令行，30 秒）

```bash
echo "你的输入" | python scripts/analyze.py --clean --format text
```

```bash
python scripts/analyze.py --text "你好，请帮我看看这个报错" --clean --format text
```

输出：所用模型与单价、token 数、预计成本、检测到的习惯、建议。`--clean` 剥离系统注入（权限警告/命令消息/任务通知），只分析你的真实输入。

## 在各平台使用

### 1. Claude Code（skill + hook，全自动）

**一键安装（推荐）**：下载整个文件夹后运行 `python install.py`，自动完成
skill 安装、hook 配置、状态栏配置，幂等可重复运行。

**手动安装**：
1. 把 `tokenwiser/` 整个文件夹放进 `~/.claude/skills/`
2. 在 `~/.claude/settings.json` 里加 UserPromptSubmit hook（配置见下文）
3. 在 `~/.claude/settings.json` 里加 statusLine（配置见"底部状态栏"）
4. 重启 Claude Code

**使用**：
- 主动：对 Claude 说"帮我分析这段输入的 token 分割"，或输入 `/tokenwiser`
- 被动：输入含密钥或超长日志时自动提示

### 2. 其他 agent（Cursor / Windsurf / Codex / 任意能跑 Python 的 agent）

把 `tokenwiser/` 文件夹放入该 agent 的规则或技能目录，让它读 `SKILL.md`。

可移植性来自引擎契约，不依赖任何 agent 的私有格式：

```bash
echo "用户输入" | python scripts/analyze.py
```

输出标准 JSON，任何 agent 都能解析并渲染给用户。

### 3. 命令行 / 脚本（任何环境）

```bash
# 传入文本
python scripts/analyze.py --text "..."

# 从 stdin 读（适合长文本）
echo "..." | python scripts/analyze.py

# 从文件读
python scripts/analyze.py --file input.txt

# 记录到习惯库（供周报使用）
python scripts/analyze.py --text "..." --record

# 看习惯周报
python scripts/history.py

# 实时消耗面板（浏览器打开，每 10 秒自动刷新）
python scripts/server.py

# 面板内容少时，先生成演示数据（近 30 天约 300 条）
python scripts/demo_data.py
```

### 3.5 实时消耗面板

`python scripts/server.py` 启动本地 Web 面板，默认 `http://127.0.0.1:8000`：

- KPI 卡：今日 / 本周 / 累计的 token 消耗、成本、浪费
- 近 30 天消耗趋势图（柱：token，线：成本）
- 习惯分布饼图、最近记录表（按会话分组，预览显示前 30%）
- 安全事件卡片：近 30 天敏感信息命中次数与类型分布（方向二）
- hook 每次提交写库后，面板在 10 秒内自动更新

依赖 `flask` 与 `cryptography`（本机已装）。只监听 `127.0.0.1`，不上网。

### 3.6 底部状态栏（可选增强）

在终端底部一行实时显示今日/本周消耗，颜色随浪费占比变化（绿/黄/红）。
**注意：状态栏是可选增强。核心实时显示走 hook 行内提示与本地面板，二者不依赖 agent 私有能力。**
`install.py` 自动按检测到的 agent 配置：

| Agent | 支持 | 配置方式 |
|---|---|---|
| Claude Code | ✅ | `~/.claude/settings.json` 加 statusLine，自动 |
| Gemini / Antigravity CLI | ✅ | `~/.gemini/antigravity-cli/settings.json` 加 statusLine，自动 |
| Cursor / Windsurf | ⚠️ 可选 | 需装 `leo-zhao.custom-status-bar` 扩展，`shell` 指向 `scripts/status.py`；不装不影响核心功能 |
| Codex CLI | ⚠️ 可选 | 不支持自定义 status 命令，只可用内置 `used-tokens` 段；自定义待 [#20043](https://github.com/openai/codex/issues/20043) |

状态栏脚本 `scripts/status.py` 读习惯库自己算，不依赖各家 agent 传给 stdin 的
字段，所以同一份脚本在支持命令式状态栏的 agent 上通用。

### 4. 浏览器 AI（规划中）

浏览器扩展适配器在规划中，将覆盖 ChatGPT / Claude.ai / Gemini / Kimi / 豆包 等网页 AI，复用同一个引擎。

## 配置

### 定价（models.json）

每个模型一条定价，按官方货币标价：美元模型（Claude/OpenAI/Gemini）标 `currency: USD`，成本与显示金额乘汇率 `usd_to_cny` 换算成**人民币（¥）**；人民币模型（DeepSeek/阿里云/智谱）标 `currency: CNY`，直接按 ¥ 计价不再乘汇率。可选 `cache_hit_per_million` 为缓存命中输入价：

```json
{
  "usd_to_cny": 7.10,
  "claude-fable-5": { "input_per_million": 10.0, "output_per_million": 50.0, "currency": "USD", "cache_hit_per_million": 1.0 },
  "deepseek-v4-flash": {
    "input_per_million": 3.0, "output_per_million": 9.0, "currency": "CNY",
    "peak":    { "cache_hit_per_million": 0.1, "cache_miss_per_million": 3.0, "output_per_million": 9.0 },
    "off_peak": { "cache_hit_per_million": 0.05, "cache_miss_per_million": 1.5, "output_per_million": 4.5 }
  },
  "default": { "input_per_million": 3.0, "output_per_million": 15.0, "currency": "USD" }
}
```

**峰谷定价**（DeepSeek）：有 `peak`/`off_peak` 结构的模型按**北京时间**判断时段取价。高峰为工作日 9-12 点与 14-18 点，周末全天低谷。面板头部与 `analyze.py` 会标注当前时段。

**自动定价**：缺省按 `ANTHROPIC_MODEL` → `CLAUDE_MODEL` → `~/.claude/settings.json` 的 `model` 探测当前模型，前缀匹配价格表（如 `deepseek-v4-flash[1m]` 命中 `deepseek-v4-flash`）；未识别回退 `default`。也可用 `--model` 手动指定。默认按缓存未命中价计费，需按命中价算加 `--cache-hit`。

模型单价随官方调整时改文件里的数值即可。汇率改 `usd_to_cny`，或用环境变量覆盖：

```bash
export TW_USD_TO_CNY=7.2        # 覆盖人民币汇率
export PROMPT_HABITS_MODELS='{"default":{"input_per_million":2,"output_per_million":10}}'   # 整体覆盖模型单价（仍按美元）
```

> 口径说明：成本只按你的**输入** token 估算（工具定位是量输入习惯），不含 AI 回复的**输出** token；官网账单是输入+输出合计，因此本工具数字通常低于官网总花费。

**分词器跟随模型**：`models.json` 每个模型带 `tokenizer` 字段，`analyze.py` 缺省 `--tokenizer auto`，按模型自动选。OpenAI GPT-5.x 用 `o200k_base`（精确）；Claude 用 `cl100k_base`（Anthropic 未公开 tiktoken 编码，此为最接近的代理）；DeepSeek/Qwen/Gemini 暂无 tiktoken 官方编码，用 `o200k_base` 代理。需要时可用 `--tokenizer cl100k_base` 等手动覆盖，或直接改 `models.json` 里对应模型的 `tokenizer` 字段。注意不同分词器对中文计数差异可达 1.5-2 倍，跨分词器比较数字没有意义。

### 检测阈值

所有检测阈值在 `scripts/core.py` 中，规则明细与默认值见 `rules_spec.md`。

### hook 配置示例（Claude Code）

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /path/to/tokenwiser/scripts/hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### 行为开关

- 被动提示只在严重度 high 时触发（凭据/隐私、日志超标、超长）。默认静默记录
- 敏感信息动作：`TW_SECRET_ACTION=block` 时，命中凭据/隐私改为阻断（exit 2，语义以实测为准）；默认 `warn` 只警告
- 敏感片段打码：`TW_SANITIZE_ON_SECRET=0` 关闭落库前打码（默认开启）
- hook 行内提示：`TW_HINT_INTERVAL` 控频（默认 1800 秒），设 0 关闭
- 想改触发严格程度，调 `core.py` 里的严重度阈值

## 数据与隐私

- **零上传**：分析全部本地完成，不调用任何 API，输入不会发给任何服务器
- **本地存储**：每次分析记录存本地 SQLite `data/habits.db`
  - 只存输入前 1000 字预览 + 检测结果（习惯类型、严重度、浪费 token）；面板按前 30% 变长显示
  - 检测到的密钥只记类型（如 "API Key"），不存密钥本身
  - 命中敏感信息时，预览里的敏感片段在落库前打码为 `[REDACTED:类型]`（`TW_SANITIZE_ON_SECRET=0` 关闭）
- **落盘加密**：输入预览与 session 经 AES-256-GCM 加密后写入，密文格式 `enc:v1:...`
  - 密钥文件在 `~/.tokenwiser/tw_key`（项目目录之外，`.gitignore` 不会触碰）
  - 需要 `cryptography`（`pip install cryptography`）。未安装时降级为明文写入
  - 老库的明文历史在首次运行 `history.py` 或 `server.py` 时自动就地加密（幂等）
  - **删除 `~/.tokenwiser/tw_key` = 历史数据无法解密**，请勿随意删除
- **删除数据**：删掉 `data/habits.db` 即清空历史
- `data/` 已在 `.gitignore` 中，不会进入版本库

## 常见问题

| 问题 | 解决 |
|---|---|
| Windows 下中文乱码 | 已内置 UTF-8 处理；仍乱码时终端执行 `chcp 65001` |
| 分词不准 | 装 tiktoken：`pip install tiktoken` |
| hook 不触发 | `/hooks` 检查配置、确认 settings.json 语法、重启 Claude Code |
| 记录失败 | 不影响使用，hook 静默忽略记录错误 |
| 觉得提示烦 | `/hooks` 里临时禁用，或调高触发阈值 |
