#!/usr/bin/env python3
"""
TokenWiser dashboard — 本地实时消耗面板

用法:
    python scripts/server.py --port 8000

起一个只监听 127.0.0.1 的 Flask 本地服务，自动打开浏览器。
前端每 10 秒轮询一次 API，hook 每次提交写库后面板自动更新。

API:
    GET /api/summary     今日/本周/累计 token、成本、浪费
    GET /api/timeline    近 N 天每日消耗（柱状 token + 折线成本）
    GET /api/habits      各习惯出现次数与浪费汇总
    GET /api/recent      最近记录（输入预览打码，不泄露明文）
"""
import argparse
import datetime
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8 输出，避免 Windows 控制台中文乱码
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request, send_from_directory

import crypto
from core import _is_peak_time, cost_rmb, effective_price, load_models
from store import fetch_records, migrate

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DASH_DIR = os.path.join(_BASE_DIR, "dashboard")

app = Flask(__name__, static_folder=None)

# 启动时加载一次价格表（models.json + 环境变量覆盖）
models = load_models()


def _cost(tokens, model, at=None):
    """按记录当时的模型与时刻算输入成本（人民币）。

    峰谷模型（如 DeepSeek）按 at 记录时刻判断高峰/低谷取价；CNY 模型不再乘汇率。
    """
    return cost_rmb(tokens, effective_price(model, models, at=at), models)


def _records():
    """读库并补齐结构（老库无 model 列时由 fetch_records 依赖的 _conn 处理）。"""
    return fetch_records()


def _mask_preview(enc_preview):
    """把密文预览打码成'前 30%（至少 10 字）'。明文只在服务端出现，不出网。

    变长显示：短输入能看到大半，长输入按比例截取加'……'，方便对上哪条对话。
    超过存储上限（store._PREVIEW_CHARS）的记录显示已存部分的 30%。
    """
    if not enc_preview or not crypto.is_encrypted(enc_preview):
        return "……"
    try:
        plain = crypto.decrypt_value(enc_preview)
    except Exception:
        return "（密钥不符，无法解密）"
    show = max(10, math.ceil(len(plain) * 0.3))
    if len(plain) <= show:
        return plain
    return plain[:show] + "……"


# ---------------------------------------------------------------------------
# 页面与静态资源
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(_DASH_DIR, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(_DASH_DIR, "static"), filename)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/summary")
def api_summary():
    rows = _records()
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    today_s = today.isoformat()
    week_start_s = monday.isoformat()

    agg = {
        "today": {"count": 0, "tokens": 0, "cost": 0.0, "waste": 0, "waste_cost": 0.0},
        "week": {"count": 0, "tokens": 0, "cost": 0.0, "waste": 0, "waste_cost": 0.0},
        "all": {"count": 0, "tokens": 0, "cost": 0.0, "waste": 0, "waste_cost": 0.0},
    }
    for rec in rows:
        _rid, ts, _tool, _sid, _prev, total, waste, _findings, model = rec
        d = ts[:10]
        cost = _cost(total, model, at=ts)
        waste_cost = _cost(waste, model, at=ts)
        agg["all"]["count"] += 1
        agg["all"]["tokens"] += total
        agg["all"]["cost"] += cost
        agg["all"]["waste"] += waste
        agg["all"]["waste_cost"] += waste_cost
        if d == today_s:
            for k in ("today",):
                agg[k]["count"] += 1
                agg[k]["tokens"] += total
                agg[k]["cost"] += cost
                agg[k]["waste"] += waste
                agg[k]["waste_cost"] += waste_cost
        if d >= week_start_s:
            agg["week"]["count"] += 1
            agg["week"]["tokens"] += total
            agg["week"]["cost"] += cost
            agg["week"]["waste"] += waste
            agg["week"]["waste_cost"] += waste_cost

    for scope in agg.values():
        scope["cost"] = round(scope["cost"], 6)
        scope["waste_cost"] = round(scope["waste_cost"], 6)
    agg["peak"] = _is_peak_time()  # 当前是否为 DeepSeek 高峰时段（北京时间）
    return jsonify(agg)


@app.route("/api/timeline")
def api_timeline():
    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))
    rows = _records()
    per_day = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "waste": 0})
    for rec in rows:
        _rid, ts, _tool, _sid, _prev, total, waste, _findings, model = rec
        key = ts[:10]
        per_day[key]["tokens"] += total
        per_day[key]["cost"] += _cost(total, model, at=ts)
        per_day[key]["waste"] += waste

    start = datetime.date.today() - datetime.timedelta(days=days - 1)
    dates, tokens, costs, waste = [], [], [], []
    for i in range(days):
        d = (start + datetime.timedelta(days=i)).isoformat()
        dates.append(d)
        tokens.append(per_day.get(d, {}).get("tokens", 0))
        costs.append(round(per_day.get(d, {}).get("cost", 0.0), 6))
        waste.append(per_day.get(d, {}).get("waste", 0))
    return jsonify({"dates": dates, "tokens": tokens, "costs": costs, "waste": waste})


@app.route("/api/habits")
def api_habits():
    rows = _records()
    stats = defaultdict(lambda: {"count": 0, "waste": 0})
    for rec in rows:
        _rid, _ts, _tool, _sid, _prev, _total, _waste, findings_json, _model = rec
        try:
            findings = json.loads(findings_json or "[]")
        except Exception:
            findings = []
        for f in findings:
            h = f.get("habit", "?")
            stats[h]["count"] += 1
            stats[h]["waste"] += f.get("waste_tokens", 0) or 0
    habits = [
        {"habit": h, "count": v["count"], "waste": v["waste"]}
        for h, v in sorted(stats.items(), key=lambda kv: -kv[1]["count"])
    ]
    return jsonify({"habits": habits})


@app.route("/api/security")
def api_security():
    """近 N 天敏感信息命中统计（方向二）：每日命中数 + 类型分布。"""
    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))
    rows = _records()
    start = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    per_day = defaultdict(int)
    by_type = defaultdict(int)
    for rec in rows:
        _rid, ts, _tool, _sid, _prev, _total, _waste, findings_json, _model = rec
        if ts[:10] < start:
            continue
        try:
            findings = json.loads(findings_json or "[]")
        except Exception:
            findings = []
        for f in findings:
            if f.get("habit") == "secret_leak":
                per_day[ts[:10]] += 1
                by_type[f.get("subtype", "unknown")] += 1
    dates, hits = [], []
    for i in range(days):
        d = (datetime.date.today() - datetime.timedelta(days=days - 1 - i)).isoformat()
        dates.append(d)
        hits.append(per_day.get(d, 0))
    return jsonify({
        "days": days,
        "dates": dates,
        "hits": hits,
        "total": sum(hits),
        "by_type": dict(by_type),
    })


@app.route("/api/recent")
def api_recent():
    """最近记录，按会话（session_id）分组返回。

    同一会话的多条输入归一组，带会话编号、条数、时间范围、session 短标识，
    便于定位'哪一次对话'。session_id 为空（CLI/演示单条）的记录各自成组。
    limit 表示返回几组（按最新记录倒序），默认 12 组。
    """
    limit = request.args.get("limit", 12, type=int)
    limit = max(1, min(limit, 100))
    rows = _records()

    groups_map = {}
    order = []
    for rec in rows:
        rid, ts, tool, enc_sid, prev, total, waste, findings_json, model = rec
        try:
            findings = json.loads(findings_json or "[]")
        except Exception:
            findings = []
        plain_sid = ""
        if enc_sid and crypto.is_encrypted(enc_sid):
            try:
                plain_sid = crypto.decrypt_value(enc_sid) or ""
            except Exception:
                plain_sid = "?"
        key = plain_sid or f"@row-{rid}"  # 无 session 的每条自成一组
        if key not in groups_map:
            groups_map[key] = {"sid": plain_sid, "count": 0, "records": []}
            order.append(key)
        g = groups_map[key]
        g["count"] += 1
        g["records"].append({
            "ts": ts,
            "tool": tool,
            "total": total,
            "waste": waste,
            "cost": round(_cost(total, model, at=ts), 6),
            "model": model,
            "habits": [f.get("habit") for f in findings],
            "preview": _mask_preview(prev),
        })

    groups = [groups_map[k] for k in order]
    groups.sort(key=lambda g: g["records"][-1]["ts"], reverse=True)  # 最新组在前
    groups = groups[:limit]
    for i, g in enumerate(groups, 1):
        g["label"] = f"会话 {i}"
        g["first"] = g["records"][0]["ts"].replace("T", " ")[:16]
        g["last"] = g["records"][-1]["ts"].replace("T", " ")[:16]
        sid = g["sid"]
        g["sid_short"] = sid if len(sid) <= 12 else sid[:12] + "…"
    return jsonify({"groups": groups})


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="TokenWiser 实时消耗面板")
    ap.add_argument("--port", type=int, default=8000, help="监听端口")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    migrate()  # 启动时迁移历史明文行（幂等）
    url = f"http://127.0.0.1:{args.port}"
    print(f"TokenWiser 面板已启动: {url}  (Ctrl+C 停止)")
    print("数据来源: data/habits.db（敏感字段 AES-256-GCM 加密存储）")
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
