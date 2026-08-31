#!/usr/bin/env python3
"""
TokenWiser statusline — 状态栏实时消耗（可选增强）

在支持 statusLine 的 agent（Claude Code / Gemini CLI）配置指向本脚本，
终端底部实时显示今日/本周的 token 消耗、成本与浪费量。

定位说明（方向三）：状态栏属于"可选增强"，不是主机制。
主机制是 hook 行内提示 + 本地面板，二者不依赖 agent 私有能力。
本脚本只对原生支持 statusLine 的 agent 自动配置。

用法:
    python scripts/status.py          # 完整文本（今日 + 本周）
    python scripts/status.py --short  # 单行短格式（供 shell prompt 等）

性能：只查本周一起的记录（fetch_records_since + aggregate_today_week），
不再全表扫描。聚合口径与 hook 行内提示完全一致。

契约: stdout 第一行是状态栏文本，颜色用 ANSI 转义。快速稳定，出错降级。
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 下 statusline 管道用 cp1252/cp936 导致中文乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from core import aggregate_today_week, load_models
from store import fetch_records_since

# ANSI 颜色
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_GRAY = "\033[90m"
_RESET = "\033[0m"


def _fmt_tokens(n):
    """紧凑格式：>=1000 显示 12.3k，否则原数。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def main():
    try:
        models = load_models()
        monday = (
            datetime.date.today()
            - datetime.timedelta(days=datetime.date.today().weekday())
        ).isoformat()
        agg = aggregate_today_week(fetch_records_since(monday), models)
        today = agg["today"]
        week = agg["week"]

        # 今日浪费占比决定颜色：>80% 红，>50% 黄，否则绿
        ratio = today["waste"] / today["tokens"] if today["tokens"] else 0
        if ratio >= 0.8:
            color = _RED
        elif ratio >= 0.5:
            color = _YELLOW
        else:
            color = _GREEN

        if "--short" in sys.argv:
            # 单行短格式：供 shell prompt 等场景（只显示今日）
            if today["count"] == 0 and week["count"] == 0:
                text = "⚡ 今日无记录"
                color = _GRAY
            else:
                text = f"⚡ {_fmt_tokens(today['tokens'])}tok ¥{today['cost']:.2f}"
            sys.stdout.write(f"{color}{text}{_RESET}\n")
            sys.stdout.flush()
            return

        text = (
            f"今日 {_fmt_tokens(today['tokens'])} tok "
            f"¥{today['cost']:.4f} (浪费 {_fmt_tokens(today['waste'])}) "
            f"· 本周 {_fmt_tokens(week['tokens'])} ¥{week['cost']:.4f}"
        )
        if today["count"] == 0 and week["count"] == 0:
            text = "今日无记录 · 输入后自动统计"
            color = _GRAY

        sys.stdout.write(f"⚡ {color}{text}{_RESET}\n")
    except Exception:
        # 任何异常都优雅降级，状态栏不崩
        sys.stdout.write("\033[31mtokenwiser 不可用\033[0m\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
