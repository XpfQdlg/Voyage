#!/usr/bin/env python3
"""
TokenWiser analyze — 便携命令行入口（任何 agent 均可调用）

用法:
    echo "文本" | python analyze.py
    python analyze.py --text "文本"
    python analyze.py --file 输入.txt
    python analyze.py --model default --tokenizer o200k_base
    python analyze.py --format text          # 人类可读（默认 JSON）
    python analyze.py --tokens               # 只看分词可视化视图
    python analyze.py --record --tool cli    # 同时写入习惯库
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 控制台把中文显示成乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# stdin 显式按 UTF-8 读。缺省 surrogateescape 会把 GBK 等环境传来的字节
# 变成孤立代理字符，后续 encode 抛 UnicodeEncodeError。replace 保证不崩。
if sys.stdin and hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

from core import _price_for, analyze_text, detect_model, load_models, strip_system_noise
from store import record_check


def visualize_tokens(tokens, width=80):
    """把 token 列表渲染成可视化视图：竖线为 token 边界，纯空白 token 用 ␣ 标出。"""
    cells = []
    for t in tokens:
        text = t["text"]
        if text.strip() == "":
            text = "␣" * max(1, len(text))  # 纯空白 token → ␣
        cells.append(text)
    lines, cur = [], ""
    for c in cells:
        if cur and len(cur) + len(c) + 1 > width:
            lines.append(cur)
            cur = ""
        cur += "|" + c
    if cur:
        lines.append(cur)
    return "\n".join(line + "|" for line in lines)


def print_text(result, models, model):
    """人类可读输出。"""
    price = _price_for(model, models)
    print("模型: {} | {}/{} {}/M (in/out)".format(
        model,
        price.get("input_per_million", "?"),
        price.get("output_per_million", "?"),
        price.get("currency", ""),
    ))
    print(f"输入: {result['total_tokens']} token, 约 {result['estimated_cost']:.4f} {result['currency']}")
    print(f"浪费: {result['waste_tokens']} token, 约 {result['waste_cost']:.4f} {result['currency']}")
    if not result["findings"]:
        print("未发现不良输入习惯。")
        return
    for f in result["findings"]:
        print(f"\n[{f['severity']}] {f['name']}")
        print(f"  检测: {f['detect']}")
        print(f"  建议: {f['advice']}")


def main():
    ap = argparse.ArgumentParser(description="输入习惯分析与 token 分割")
    ap.add_argument("--text", default=None, help="直接传文本")
    ap.add_argument("--file", default=None, help="从文件读")
    ap.add_argument("--model", default=None, help="定价模型名（对应 models.json 的键）。缺省自动探测当前模型")
    ap.add_argument("--tokenizer", default="o200k_base", help="tiktoken 编码名")
    ap.add_argument("--format", choices=["json", "text"], default="json")
    ap.add_argument("--tokens", action="store_true", help="只输出分词可视化视图（竖线为 token 边界）")
    ap.add_argument("--clean", action="store_true", help="先剥离系统注入内容（权限警告/命令消息等）再分析")
    ap.add_argument("--record", action="store_true", help="分析结果写入习惯库")
    ap.add_argument("--tool", default="cli", help="记录时的来源标记")
    args = ap.parse_args()

    if args.text is not None:
        text = args.text
    elif args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if args.clean:
        text = strip_system_noise(text)
    if not text.strip():
        print("无输入。", file=sys.stderr)
        sys.exit(1)

    models = load_models()
    model = args.model or detect_model() or "default"
    result = analyze_text(text, model=model, models=models, encoding_name=args.tokenizer)
    if args.record:
        record_check(result, {"prompt": text, "session_id": "", "model": model}, tool=args.tool)

    if args.tokens:
        print(visualize_tokens(result["tokens"]))
        print(f"\n共 {result['total_tokens']} token")
        return

    if args.format == "text":
        print_text(result, models, model)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
