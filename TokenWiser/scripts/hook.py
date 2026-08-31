#!/usr/bin/env python3
"""
TokenWiser hook — Claude Code UserPromptSubmit 适配器

stdin 收到 JSON:
    {"prompt": "...", "session_id": "...", "transcript_path": "...", "cwd": "...", ...}

行为:
    1. 分析 prompt
    2. 写入本地习惯库（敏感片段按 TW_SANITIZE_ON_SECRET 打码）
    3. 有 high 严重度发现 → stderr 输出一行警告，exit 1（非阻塞，prompt 继续）
       TW_SECRET_ACTION=block 时，secret_leak 命中改为 exit 2（意图阻断，语义以实测为准）
    4. 行内提示：TW_HINT_INTERVAL 控频输出今日聚合（默认 1800 秒，0=关闭）
    5. 否则 → exit 0，stdout 留空（完全静默）

注意:
    - exit 0 时 stdout 必须为空，否则内容会被注入 Claude 上下文
    - stderr 输出仅用户可见（exit 0 时是否注入上下文需实测；若注入可设
      TW_HINT_INTERVAL=0 关闭行内提示）
    - 分析要快。若变慢，把 record_check 改为后台进程写入
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 控制台把中文显示成乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# stdin 显式按 UTF-8 读。缺省 surrogateescape 会把 GBK 等环境传来的字节
# 变成孤立代理字符，入库时抛 UnicodeEncodeError。replace 保证不崩。
if sys.stdin and hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from core import (
    SEV_HIGH,
    aggregate_today_week,
    analyze_text,
    detect_model,
    load_models,
    strip_system_noise,
)
from store import fetch_records_since, record_check

_HINT_FILE = os.path.join(os.path.expanduser("~"), ".tokenwiser", "last_hint")


def _env_int(name, default):
    """读环境变量整数；缺省或非法回退默认值。"""
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _fmt_tokens(n):
    """紧凑格式：>=1000 显示 12.3k，否则原数。与 status.py 保持一致。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _maybe_hint(interval):
    """按控频输出今日聚合提示（方向三）。写 last_hint 时间戳去重。

    失败一律静默，不影响主流程。今日无记录时不提示。
    """
    try:
        now = time.time()
        try:
            with open(_HINT_FILE, encoding="utf-8") as f:
                last = float(f.read().strip() or "0")
        except Exception:
            last = 0.0
        if now - last < interval:
            return
        monday = (
            datetime.date.today()
            - datetime.timedelta(days=datetime.date.today().weekday())
        ).isoformat()
        agg = aggregate_today_week(fetch_records_since(monday))
        t = agg["today"]
        if t["count"] == 0:
            return
        ratio = (t["waste"] / t["tokens"]) if t["tokens"] else 0
        sys.stderr.write(
            f"⚡ 今日 {_fmt_tokens(t['tokens'])} tok / ¥{t['cost']:.4f}（浪费 {ratio:.0%}）\n"
        )
        try:
            os.makedirs(os.path.dirname(_HINT_FILE), exist_ok=True)
            with open(_HINT_FILE, "w", encoding="utf-8") as f:
                f.write(str(now))
        except Exception:
            pass
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # 读不到输入就不打扰用户

    prompt = strip_system_noise(data.get("prompt", ""))
    if not prompt.strip():
        sys.exit(0)  # 纯系统注入（权限警告/命令消息/任务通知等）不入库、不提示

    models = load_models()
    result = analyze_text(prompt, model=detect_model() or "default", models=models)

    # 落库。preview 打码由 store.record_check 统一处理（命中敏感信息且未关闭时）。
    try:
        record_check(result, data, tool="claude_code")
    except Exception:
        pass  # 记录失败不影响用户（后续可考虑写入调试日志）

    # 方向三：行内提示（控频，默认每 1800 秒最多一次）
    hint_interval = _env_int("TW_HINT_INTERVAL", 1800)
    if hint_interval > 0:
        _maybe_hint(hint_interval)

    # 敏感信息优先处理：block 则阻断，warn 则警告（exit 1）
    secret_highs = [
        f for f in result["findings"]
        if f.get("habit") == "secret_leak" and f["severity"] == SEV_HIGH
    ]
    if secret_highs:
        action = os.environ.get("TW_SECRET_ACTION", "warn").strip().lower()
        msgs = "；".join(f["advice"] for f in secret_highs[:2])
        if action == "block":
            # exit 2 的阻断语义以实测为准；若当前版本不支持，退化为普通警告
            sys.stderr.write("🚫 检测到敏感信息，已阻断发送: " + msgs + "\n")
            sys.exit(2)
        sys.stderr.write("⚠ 输入习惯提醒: " + msgs + "\n")
        sys.exit(1)

    # 其他 high（日志粘贴/超长等），保持原行为
    highs = [
        f for f in result["findings"]
        if f["severity"] == SEV_HIGH and f.get("habit") != "secret_leak"
    ]
    if highs:
        msgs = "；".join(f["advice"] for f in highs[:2])
        sys.stderr.write("⚠ 输入习惯提醒: " + msgs + "\n")
        sys.exit(1)
    sys.exit(0)  # 完全静默


if __name__ == "__main__":
    main()
