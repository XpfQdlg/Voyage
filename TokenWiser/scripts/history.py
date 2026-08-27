#!/usr/bin/env python3
"""
TokenWiser history — 输入习惯报告

用法:
    python history.py [--weeks 4]

读取 data/habits.db，按周聚合各习惯的出现次数与浪费 token，输出报告。
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 控制台把中文显示成乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from store import fetch_checks, migrate


def main():
    ap = argparse.ArgumentParser(description="输入习惯报告")
    ap.add_argument("--weeks", type=int, default=4, help="显示最近几周")
    args = ap.parse_args()

    migrate()  # 首次升级时把历史明文行就地加密
    rows = fetch_checks()
    if not rows:
        print("习惯库暂无记录。先运行 analyze.py --record，或安装 hook 后使用。")
        return

    # week -> habit -> [出现次数, 浪费 token]
    by_week = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for ts, tool, total, waste, findings_json in rows:
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except ValueError:
            continue
        week = dt.strftime("%Y-W%W")
        try:
            findings = json.loads(findings_json or "[]")
        except Exception:
            findings = []
        for f in findings:
            habit = f.get("habit", "?")
            by_week[week][habit][0] += 1
            by_week[week][habit][1] += f.get("waste_tokens", 0) or 0

    weeks = sorted(by_week)[-args.weeks:]
    if not weeks:
        print("没有可展示的记录。")
        return

    print(f"=== 输入习惯报告（最近 {len(weeks)} 周）===")
    for week in weeks:
        habits = by_week[week]
        count = sum(v[0] for v in habits.values())
        wasted = sum(v[1] for v in habits.values())
        print(f"\n[{week}] 共 {count} 次发现，浪费约 {wasted} token")
        for habit, (c, w) in sorted(habits.items(), key=lambda x: -x[1][1]):
            print(f"  {habit}: {c} 次, 浪费 {w} token")


if __name__ == "__main__":
    main()
