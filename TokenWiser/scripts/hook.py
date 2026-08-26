#!/usr/bin/env python3
"""
TokenWiser hook — Claude Code UserPromptSubmit 适配器

stdin 收到 JSON:
    {"prompt": "...", "session_id": "...", "transcript_path": "...", "cwd": "...", ...}

行为:
    1. 分析 prompt
    2. 写入本地习惯库（静默）
    3. 有 high 严重度发现 → stderr 输出一行警告，exit 1（非阻塞，prompt 继续）
    4. 否则 → exit 0，stdout 留空（完全静默）

注意:
    - exit 0 时 stdout 必须为空，否则内容会被注入 Claude 上下文
    - 分析要快。若变慢，把 record_check 改为后台进程写入
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 控制台把中文显示成乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# stdin 显式按 UTF-8 读。缺省 surrogateescape 会把 GBK 等环境传来的字节
# 变成孤立代理字符，入库时抛 UnicodeEncodeError。replace 保证不崩。
if sys.stdin and hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from core import analyze_text, load_models, SEV_HIGH
from store import record_check


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # 读不到输入就不打扰用户

    prompt = data.get("prompt", "")
    if not prompt.strip():
        sys.exit(0)

    result = analyze_text(prompt, models=load_models())

    try:
        record_check(result, data, tool="claude_code")
    except Exception:
        pass  # 记录失败不影响用户（后续可考虑写入调试日志）

    highs = [f for f in result["findings"] if f["severity"] == SEV_HIGH]
    if highs:
        msgs = "；".join(f["advice"] for f in highs[:2])
        sys.stderr.write("⚠ 输入习惯提醒: " + msgs + "\n")
        sys.exit(1)  # 非阻塞警告：用户可见，prompt 继续
    sys.exit(0)  # 完全静默


if __name__ == "__main__":
    main()
