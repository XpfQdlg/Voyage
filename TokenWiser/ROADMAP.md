# TokenWiser 后续调整清单

状态：⬜ 待做 / 🔧 进行中 / ✅ 完成

## v1.5 已交付（2026-08-27）

- ✅ **落盘加密**：`crypto.py` AES-256-GCM 加密 input_preview/session_id；密钥 `~/.tokenwiser/tw_key`；老库自动迁移（`store.migrate()`）；未装 cryptography 时降级明文
- ✅ **实时消耗面板**：`server.py` + `dashboard/`（Flask + 本地 echarts），KPI/趋势/习惯分布/最近记录，10s 轮询
- ✅ **演示数据**：`demo_data.py` 生成近 30 天仿真记录，走真实检测管线
- ✅ store 增 `model` 列：面板成本按记录当时模型定价计算
- ✅ **底部状态栏**：`status.py` 读库自足（不依赖 stdin 协议），Claude Code 与 Gemini CLI 同款通用；Cursor/Windsurf 借扩展、Codex 待上游
- ✅ **一键安装器**：`install.py` 下载即用——自动装 skill + 配 hook + 按检测到的 agent 配状态栏，幂等可重复运行

## v2 已交付（2026-08-31，方向二 + 方向三）

- ✅ **敏感信息规则增强**：按 subtype 分类（凭据/隐私/联系）；新增银行卡（Luhn 校验）、统一社会信用代码（GB32100 校验位）、数据库连接串、PEM 私钥；邮箱降为 medium
- ✅ **敏感片段打码落库**：`core.redact_sensitive()`，预览落库前打码，分析仍用原文；`store.record_check` 统一处理
- ✅ **hook 安全动作**：`TW_SECRET_ACTION=warn/block`
- ✅ **实时显示兼容化**：hook 行内提示（`TW_HINT_INTERVAL` 控频，主机制）；`status.py` 改按日期增量聚合 + `--short`；`install.py` 用 `sys.executable`，Cursor/Windsurf/Codex 状态栏降级为可选
- ✅ **面板安全卡片**：`/api/security` + dashboard 展示命中次数与类型分布
- ✅ **演示数据 `--security-weight`**：调高敏感信息记录占比
- ✅ **自动化测试**：`scripts/test_plan.py`（17 项全过）

## 一、v1 收尾（近期）

1. ⬜ **同步 rules_spec.md 与代码阈值**
   - 开场白：代码已改为 ≥4 token，规格文档还写 ≥10
   - 缺上下文：代码已改为 <30 字，规格文档还写 <60
   - 代码已新增但规格未记录：规则抑制（密钥/日志/超长时不补报缺上下文）、日志主导排除、超 3000 token 排除
2. ⬜ **models.json 填真实价格**（当前是示例值 3/15 USD）
3. ⬜ **SKILL.md 补 token 分割渲染指令**（主动模式"彩色切片"的展示层，目前只输出 tokens 数据）
4. ⬜ **阈值实战调优**（用一周收集误报/漏报，逐条调整）

## 二、v1.5 / v2（中期）

1. ✅ **自动化测试套件**（2026-08-31：`scripts/test_plan.py`，17 项覆盖规则精度/redact/聚合/hook/status/install）
2. ⬜ **浏览器扩展适配器**（覆盖 ChatGPT / Claude.ai / Gemini / Kimi / 豆包 等网页 AI）
3. ⬜ **会话历史分析**：读 `~/.claude/projects/` 转录，直接出习惯周报（复用早期"会话审计"方向的数据源）
4. ⬜ **更多检测规则**
   - 重复提问 / 内容去重（同段文本重复出现）
   - 跨会话相似度（同一问题反复开新会话）
   - 注入放大成本检测（prompt 被注入导致成本激增）
5. ⬜ **多 tokenizer 支持**：qwen 等国产模型分词，对比中文分词差异
6. ⬜ **输出成本估算**、多模型定价表（当前只算输入成本）
7. ✅ **主动模式的 UI 化**（2026-08-27 完成：`server.py` 本地实时消耗面板 + `demo_data.py` 演示数据）

## 三、长期

1. ⬜ **从"习惯教练"演进到"agent 安全审计/取证"**（事故调查、归因报告，贴合网安方向）
2. ⬜ **独立仓库**（从 Voyage 拆出，若作品集需要独立展示）
3. ⬜ **发布到 skill 市场**、中英双语 README + 架构图
4. ⬜ **README 首屏截图**（终端报告或 Web 界面截图，用于简历/面试展示）

## 四、技术债 / 已知问题

- Windows 控制台 GBK 编码已修（stdin reconfigure + 入库清洗），但极端环境仍需实测
- hook 是同步的，每次提交增加毫秒级延迟；若明显变慢需改为后台进程写入
- `secret_leak` 邮箱已降为 medium（v2）；凭据/隐私仍为 high，实战后按真实数据继续收紧阈值
- `missing_context` 与 `vague_instruction` 的 waste=300 是估算值，非实测

## 五、规则阈值现状速查（2026-08-26）

| 规则 | 触发条件（代码实际值） | 严重度 |
|---|---|---|
| log_paste | 行数 ≥10 且日志占比 ≥50%；waste ≥200 或占比 ≥80% → high | high/medium |
| secret_leak | credential/pii → high；contact（邮箱）→ medium；银行卡须过 Luhn、信用代码须过 GB32100 校验位 | high/medium |
| oversized_request | total ≥3000；≥6000 → high | high/medium |
| redundant_opener | 开场白 ≥4 token | medium |
| missing_context | 文本 ≥30 字、total <3000、非日志主导、无格式关键词 | medium |
| vague_instruction | 文本 <40 字且命中模糊句式 | medium |
