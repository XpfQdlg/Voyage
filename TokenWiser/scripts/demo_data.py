#!/usr/bin/env python3
"""
TokenWiser demo data — 生成演示数据填充习惯库

用法:
    python scripts/demo_data.py --days 30 --per-day 10
    python scripts/demo_data.py --seed 42

生成约 --days × --per-day 条记录，按日期铺满最近 N 天。
每条记录构造一个"像真实输入"的示例 prompt，走 analyze_text 真实检测管线，
再经 record_check 入库（自动走加密通道），因此 token 数、浪费量、命中习惯
全部与引擎一致，不是手工拼的数字。

固定 seed 保证可复现。
"""
import argparse
import datetime
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from core import analyze_text, load_models
from store import record_check


# ---------------------------------------------------------------------------
# 各类习惯的示例 prompt 构造器（clean 表示无坏习惯）
# ---------------------------------------------------------------------------

def _clean_prompt():
    pool = [
        "请分析下面这段 Python 代码的逻辑，找出潜在问题，按 markdown 列表输出，并用中文说明每条修复建议：\n"
        "def calc(a, b):\n"
        "    return a / b\n"
        "calc(1, 0)",
        "把这段话翻译成英文，目标读者是技术团队，输出为表格格式：\n"
        "缓存命中率从 92% 降到了 71%，需要排查是否与近期发布的新版本有关。",
        "请给这个接口写单元测试，要求覆盖正常路径和异常路径，输出 pytest 风格的测试代码：\n"
        "POST /api/user {name, age}",
    ]
    return random.choice(pool)


def _log_paste_prompt():
    lines = []
    for i in range(12):
        lines.append(
            f"2026-08-{random.randint(1, 27):02d} {random.randint(0, 23):02d}:"
            f"{random.randint(0, 59):02d}:{random.randint(0, 59):02d} "
            f"{random.choice(['INFO', 'WARN', 'ERROR'])} service.py:{random.randint(10, 999)} "
            f"{random.choice(['request handled', 'retrying', 'timeout', 'connection reset', 'cache miss'])} "
            f"{random.randint(0, 99999)}"
        )
    lines.append("Traceback (most recent call last):")
    lines.append('  File "app/main.py", line 42, in <module>')
    lines.append("    handle_request(payload)")
    lines.append('  File "app/service.py", line 88, in handle_request')
    lines.append("    db_session.commit()")
    lines.append("OperationalError: (2006, 'MySQL server has gone away')")
    return "这段日志一直报错，帮我看看是什么问题：\n" + "\n".join(lines)


def _secret_prompt():
    kinds = [
        "帮我看看这个 API key 是不是过期了，sk-"
        + "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", k=40)),
        "这个接口用手机号 1" + "".join(random.choices("0123456789", k=10)) + " 登录老是验证失败",
        "我的 GitHub token 是 ghp_" + "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=32)) + "，用这个推代码",
    ]
    return random.choice(kinds)


def _oversized_prompt():
    return (
        "请帮我总结这份文档的内容，提取关键要点：\n"
        + "这是一段需要处理的示例文本，包含许多细节与要点，请逐条整理成摘要。\n" * 260
    )


def _opener_prompt():
    pool = [
        "你是一个AI助手，帮我写一个计算斐波那契数列的 Python 函数",
        "你是一个智能助手，请给我解释一下什么是量子纠缠",
        "你好，请帮我把这段话润色得更正式一些：感谢您的配合",
    ]
    return random.choice(pool)


def _missing_context_prompt():
    pool = [
        "我想把这个项目里连接数据库的代码换成连接池的方式，之前一直用单个连接感觉不太对劲",
        "这段代码跑起来总是超时，我把超时时间调大了也没用，数据量稍微大一点就不行",
        "新来的同事写了个函数处理用户上传的文件，但是空文件的时候会崩，我想加个判断",
    ]
    return random.choice(pool)


def _vague_prompt():
    pool = ["帮我改一下", "这个代码有问题", "这段逻辑不行", "帮我看看", "弄一下"]
    return random.choice(pool)


# (权重, 构造器)。clean 占比最高，贴近真实分布。
_PROMPT_POOL = [
    (4, _clean_prompt),
    (1.2, _log_paste_prompt),
    (0.8, _secret_prompt),
    (0.8, _oversized_prompt),
    (1.2, _opener_prompt),
    (1.2, _missing_context_prompt),
    (0.8, _vague_prompt),
]


def _pick_prompt(pool=None):
    """按权重取样一个 prompt 构造器。pool 缺省用模块级 _PROMPT_POOL。"""
    pool = pool if pool is not None else _PROMPT_POOL
    total = sum(w for w, _ in pool)
    r = random.uniform(0, total)
    acc = 0.0
    for w, fn in pool:
        acc += w
        if r <= acc:
            return fn()
    return pool[-1][1]()


# 模型按使用频率加权：haiku 日常、sonnet/fable 中等、opus 偶尔
_MODEL_POOL = [
    ("claude-haiku-4-5", 5),
    ("claude-sonnet-5", 3),
    ("claude-fable-5", 2),
    ("claude-opus-5", 0.5),
    ("default", 0.5),
]


def _pick_model():
    total = sum(w for _, w in _MODEL_POOL)
    r = random.uniform(0, total)
    acc = 0.0
    for name, w in _MODEL_POOL:
        acc += w
        if r <= acc:
            return name
    return _MODEL_POOL[0][0]


def main():
    ap = argparse.ArgumentParser(description="生成演示数据填充习惯库")
    ap.add_argument("--days", type=int, default=30, help="覆盖最近几天")
    ap.add_argument("--per-day", type=int, default=10, help="每天几条")
    ap.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
    ap.add_argument("--security-weight", type=float, default=0.0,
                    help="敏感信息记录占比（0-1，如 0.5），让面板安全卡片有内容")
    args = ap.parse_args()

    random.seed(args.seed)
    models = load_models()
    today = datetime.date.today()
    total = 0

    # --security-weight: 重配权重，敏感信息记录占 sw，其余按原比例占 1-sw
    pool = None
    if args.security_weight > 0:
        sw = min(max(args.security_weight, 0.0), 1.0)
        others = [(w, fn) for w, fn in _PROMPT_POOL if fn is not _secret_prompt]
        other_total = sum(w for w, _ in others)
        pool = [(w / other_total * (1 - sw), fn) for w, fn in others]
        pool.append((sw, _secret_prompt))

    # 从最远的天开始铺，日期递增
    for day_offset in range(args.days - 1, -1, -1):
        day = today - datetime.timedelta(days=day_offset)
        for i in range(args.per_day):
            prompt = _pick_prompt(pool)
            model = _pick_model()
            result = analyze_text(prompt, model=model, models=models)
            ts = day.strftime("%Y-%m-%dT") + f"{random.randint(9, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
            session = f"demo-{day_offset:02d}-{i:02d}"
            record_check(
                result,
                meta={"prompt": prompt, "session_id": session},
                tool="demo",
                ts=ts,
            )
            total += 1

    print(f"已生成 {total} 条演示记录（最近 {args.days} 天，seed={args.seed}）。")
    print("数据经 record_check 写入，敏感字段已自动加密。")


if __name__ == "__main__":
    main()
