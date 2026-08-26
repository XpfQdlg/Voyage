"""
TokenWiser 持久化层

把每次分析结果写入本地 SQLite 习惯库，供历史报告使用。
数据库文件: TokenWiser/data/habits.db（首次使用时自动创建）。
"""
import json
import os
import sqlite3
import time

_DB_REL = os.path.join("..", "data", "habits.db")


def db_path():
    """习惯库的绝对路径。"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), _DB_REL))


def _conn():
    """打开连接并确保表存在。"""
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            tool TEXT,
            session_id TEXT,
            input_preview TEXT,
            total_tokens INTEGER,
            waste_tokens INTEGER,
            findings_json TEXT
        )"""
    )
    return conn


def _clean(value):
    """清洗字符串：去掉孤立代理字符，避免入库时 UnicodeEncodeError。"""
    if not isinstance(value, str):
        return value
    return value.encode("utf-8", errors="replace").decode("utf-8")


def record_check(result, meta=None, tool="unknown"):
    """写入一次分析结果。meta 可带 prompt / session_id 等来源信息。"""
    meta = meta or {}
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO checks (ts, tool, session_id, input_preview, total_tokens, waste_tokens, findings_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                tool,
                _clean(meta.get("session_id", "") or ""),
                _clean((meta.get("prompt", "") or "")[:100]),
                result["total_tokens"],
                result["waste_tokens"],
                _clean(json.dumps(result["findings"], ensure_ascii=False)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_checks():
    """读取全部记录，按时间排序。无库时返回空列表。"""
    path = db_path()
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT ts, tool, total_tokens, waste_tokens, findings_json FROM checks ORDER BY ts"
        ).fetchall()
    finally:
        conn.close()
