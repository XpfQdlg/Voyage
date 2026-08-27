# TokenWiser 使用说明

面向使用者的配置与使用指南。TokenWiser 是平台无关的，不绑定任何特定 AI 工具。

## TokenWiser 是什么

检测你向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议。

覆盖的习惯：
- 大段粘贴日志/代码（只留报错那几行就够了）
- 输入中带疑似密钥、手机号、身份证
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

**安装**：
1. 把 `tokenwiser/` 整个文件夹放进 `~/.claude/skills/`
2. 在 `~/.claude/settings.json` 里加 UserPromptSubmit hook（配置见下文）
3. 重启 Claude Code

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
- 习惯分布饼图、最近记录表（输入预览已打码为"前 2 字 + ……"）
- hook 每次提交写库后，面板在 10 秒内自动更新

依赖 `flask` 与 `cryptography`（本机已装）。只监听 `127.0.0.1`，不上网。

### 4. 浏览器 AI（规划中）

浏览器扩展适配器在规划中，将覆盖 ChatGPT / Claude.ai / Gemini / Kimi / 豆包 等网页 AI，复用同一个引擎。

## 配置

### 定价（models.json）

单位：每 1,000,000 token 的货币数。`models.json` 已预置常见 Claude 模型（fable-5 / opus-5 / sonnet-5 / haiku-4-5），按模型自动计费：

```json
{
  "claude-fable-5": { "input_per_million": 10.0, "output_per_million": 50.0, "currency": "USD" },
  "claude-opus-5":   { "input_per_million": 5.0,  "output_per_million": 25.0, "currency": "USD" },
  "claude-sonnet-5": { "input_per_million": 3.0,  "output_per_million": 15.0, "currency": "USD" },
  "claude-haiku-4-5":{ "input_per_million": 1.0,  "output_per_million": 5.0,  "currency": "USD" },
  "default":         { "input_per_million": 3.0,  "output_per_million": 15.0, "currency": "USD" }
}
```

**自动定价**：缺省按 `ANTHROPIC_MODEL` → `CLAUDE_MODEL` → `~/.claude/settings.json` 的 `model` 探测当前模型，匹配价格表；未识别回退 `default`。也可用 `--model` 手动指定。

价格会随官方调整，改文件里的数值即可。也可用环境变量整体覆盖：

```bash
export PROMPT_HABITS_MODELS='{"default":{"input_per_million":2,"output_per_million":10,"currency":"CNY"}}'
```

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

- 被动提示只在严重度 high 时触发（密钥、日志超标、超长）。默认静默记录
- 想改触发严格程度，调 `core.py` 里的严重度阈值

## 数据与隐私

- **零上传**：分析全部本地完成，不调用任何 API，输入不会发给任何服务器
- **本地存储**：每次分析记录存本地 SQLite `data/habits.db`
  - 只存输入前 100 字预览 + 检测结果（习惯类型、严重度、浪费 token）
  - 检测到的密钥只记类型（如 "API Key"），不存密钥本身
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
