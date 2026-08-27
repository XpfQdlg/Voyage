# TokenWiser

检测你向 AI 输入中的不良习惯，量化 token 与成本代价，给出建议。只建议，不替换。

## 文档

- [使用说明 USAGE.md](USAGE.md) — 面向用户，跨平台（Claude Code / 其他 agent / 命令行）
- [检测规则规格 rules_spec.md](rules_spec.md) — 每条规则的检测逻辑与阈值
- [后续调整清单 ROADMAP.md](ROADMAP.md) — 待办与技术债

## 它解决什么

- 你经常整段贴日志、开场白冗余、指令模糊、不给输出格式？
- 每次多花几百 token，累计就是一笔不小的成本，还拉低回复质量
- TokenWiser 在背后记录，严重时提醒你，定期给你习惯报告

## 交互模式

- 被动：严重度 high 时主动提示（不打断你的输入），其余静默记录
- 主动：调用 skill 或命令行，查看某段输入的 token 分割、坏习惯与量化代价

## 快速开始

```bash
echo "你的输入" | python scripts/analyze.py --format text
```

```bash
python scripts/analyze.py --text "你好，请帮我优化一下这个" --format text
```

## 实时消耗面板

本地 Web 面板，实时展示 token 消耗、成本、习惯分布，每 10 秒自动刷新：

```bash
python scripts/server.py
# 浏览器自动打开 http://127.0.0.1:8000
```

面板数据来自本地 `data/habits.db`。首次展示内容少时，可先生成演示数据：

```bash
python scripts/demo_data.py          # 生成近 30 天约 300 条演示记录
```

## 目录结构

```
TokenWiser/
├── SKILL.md            # 给任何 agent 的指令（放入 .claude/skills/ 即可用）
├── USAGE.md            # 使用说明（跨平台）
├── rules_spec.md       # 检测规则规格
├── ROADMAP.md          # 后续调整清单
├── models.json         # 定价表（可改）
└── scripts/
    ├── core.py         # 核心引擎（纯函数，零工具依赖）
    ├── analyze.py      # 便携命令行入口（stdin/--text → JSON）
    ├── hook.py         # Claude Code hook 适配器（自动触发）
    ├── history.py      # 输入习惯周报
    ├── store.py        # SQLite 习惯库
    ├── crypto.py       # 敏感字段 AES-256-GCM 加密（密钥在项目外 ~/.tokenwiser/）
    ├── server.py       # 本地实时消耗面板（Flask）
    ├── demo_data.py    # 演示数据生成器
    └── dashboard/      # 面板前端（index.html + 本地 echarts）
```

## 安装为 Claude Code skill

将 `TokenWiser/` 目录放入 `~/.claude/skills/`（或项目 `.claude/skills/`）。
需要自动触发时，把 `scripts/hook.py` 配为 UserPromptSubmit hook。

## 隐私

- 分析全部本地完成，零上传
- 输入预览（前 100 字）与 session 落盘前经 **AES-256-GCM 加密**，密钥存 `~/.tokenwiser/tw_key`（项目目录之外）
- 删除密钥 = 历史数据无法解密，请勿随意删除

## 可选依赖

- tiktoken：精确 token 分割（`pip install tiktoken`）。不装也能跑，用字符估算。
- cryptography：敏感字段加密（`pip install cryptography`）。已安装时自动启用，未安装时降级为明文写入。
- flask：实时消耗面板（`pip install flask`）。
