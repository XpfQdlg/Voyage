---
name: tokenwiser
description: 分析用户输入习惯、token 分割与浪费量。当用户输入包含大段粘贴的日志或代码、疑似密钥或敏感信息、超长文本，或用户要求分析自己的输入、查看 token 分割、了解优化建议时，运行 scripts/analyze.py 分析输入，报告 token 分割、检测到的坏习惯和量化代价。只建议，不替换用户内容。
---

# tokenwiser · 言镜

检测用户向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议。

## 何时使用

- 用户输入明显很长、包含大量日志或代码粘贴
- 输入中疑似包含密钥、手机号、身份证、邮箱等敏感信息
- 用户主动要求分析输入、查看 token 分割、了解优化建议

## 调用方法

```bash
# 主动调用：只分析当前这条输入（推荐）
python scripts/analyze.py --text "当前输入" --clean --format text

# 从标准输入读（适合长文本）
echo "当前输入" | python scripts/analyze.py --clean --format text

# 手动指定模型定价（缺省自动探测当前模型）
python scripts/analyze.py --text "..." --model claude-fable-5 --format text

# 只看分词视图（竖线为 token 边界，纯空白 token 显示为 ␣）
echo "当前输入" | python scripts/analyze.py --clean --tokens
```

## 主动调用定位

- 主动调用**只分析用户当前给出的这段输入**，不要拉取历史会话
- 想跨对话看趋势/周报，用 `python scripts/history.py`
- `--clean` 会自动剥离系统注入（权限警告、命令消息、任务通知等）

## 输出解读

文本模式先打印所用模型与单价，再打印 token 数与代价。JSON 额外含：

- `tokens`：每个 token 的文本与字符区间，用于渲染 token 分割视图
- `findings`：检测到的习惯问题，每项含 habit / name / severity / waste_tokens / detect / advice
- `total_tokens` / `estimated_cost` / `waste_tokens` / `waste_cost`
- 定价按 `models.json`，自动探测当前模型（`ANTHROPIC_MODEL`/`CLAUDE_MODEL`/`~/.claude/settings.json`），未识别回退 default

## 规则

- 只报告，不替换用户的任何内容
- 严重度 high 才主动提示；medium 静默记录
- `secret_leak`（疑似敏感信息）命中始终为 high，优先提示
- 规则明细见 `rules_spec.md`
