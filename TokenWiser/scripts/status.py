#!/usr/bin/env python3
"""
TokenWiser statusline — Claude Code 状态栏实时消耗

在 ~/.claude/settings.json 配置 statusLine 指向本脚本，终端底部实时显示
今日/本周的 token 消耗、成本与浪费量。

statusLine 契约（当前版本）: stdout 第一行是状态栏文本，颜色用 ANSI 转义。
stdin 里虽有会话 cost，但那是"本会话"而非"今天累计"，所以本脚本不依赖
stdin，直接读习惯库按天聚合，跨会话、跨 /clear 都累计。

要求快且稳：每次刷新独立运行，出错输出降级文本，绝不抛异常。
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 下 statusline 管道用 cp1252/cp936 导致中文乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from core import cost_rmb, effective_price, load_models
from store import fetch_records

# ANSI 颜色
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_RESET = "\033[0m"


def _fmt_tokens(n):
    """紧凑格式：>=1000 显示 12.3k，否则原数。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def main():
    try:
        models = load_models()
        rows = fetch_records()
        now = datetime.date.today()
        today_s = now.isoformat()
        monday_s = (now - datetime.timedelta(days=now.weekday())).isoformat()

        today = {"tokens": 0, "cost": 0.0, "waste": 0, "count": 0}
        week = {"tokens": 0, "cost": 0.0, "waste": 0, "count": 0}
        for rec in rows:
            _rid, ts, _tool, _sid, _prev, total, waste, _fj, model = rec
            d = ts[:10]
            cost = cost_rmb(total, effective_price(model, models, at=ts), models)
            if d >= monday_s:
                week["tokens"] += total
                week["cost"] += cost
                week["waste"] += waste
                week["count"] += 1
            if d == today_s:
                today["tokens"] += total
                today["cost"] += cost
                today["waste"] += waste
                today["count"] += 1

        # 今日浪费占比决定颜色：>80% 红，>50% 黄，否则绿
        ratio = today["waste"] / today["tokens"] if today["tokens"] else 0
        if ratio >= 0.8:
            color = _RED
        elif ratio >= 0.5:
            color = _YELLOW
        else:
            color = _GREEN

        text = (
            f"今日 {_fmt_tokens(today['tokens'])} tok "
            f"¥{today['cost']:.4f} (浪费 {_fmt_tokens(today['waste'])}) "
            f"· 本周 {_fmt_tokens(week['tokens'])} ¥{week['cost']:.4f}"
        )
        if today["count"] == 0 and week["count"] == 0:
            text = "今日无记录 · 输入后自动统计"
            color = "\033[90m"

        sys.stdout.write(f"⚡ {color}{text}{_RESET}\n")
    except Exception:
        # 任何异常都优雅降级，状态栏不崩
        sys.stdout.write("\033[31mtokenwiser 不可用\033[0m\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
