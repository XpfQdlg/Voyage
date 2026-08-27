"""
TokenWiser 持久化层

把每次分析结果写入本地 SQLite 习惯库，供历史报告与实时面板使用。
数据库文件: TokenWiser/data/habits.db（首次使用时自动创建）。

隐私: input_preview / session_id 属敏感字段，落盘前经 crypto.encrypt_value()
做 AES-256-GCM 加密。findings_json 只含习惯类型等元数据，不加密。
"""
import json
import os
import sqlite3
import time

import crypto

_DB_REL = os.path.join("..", "data", "habits.db")


def db_path():
    """习惯库的绝对路径。"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), _DB_REL))


def _conn():
    """打开连接并确保表结构存在。"""
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
            findings_json TEXT,
            model TEXT
        )"""
    )
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    """老库补齐新列（model）。新库建表时已含，此函数只对老库生效。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(checks)")]
    if "model" not in cols:
        conn.execute("ALTER TABLE checks ADD COLUMN model TEXT")
        conn.commit()


def _clean(value):
    """清洗字符串：去掉孤立代理字符，避免入库时 UnicodeEncodeError。"""
    if not isinstance(value, str):
        return value
    return value.encode("utf-8", errors="replace").decode("utf-8")


def record_check(result, meta=None, tool="unknown", ts=None):
    """写入一次分析结果。meta 可带 prompt / session_id 等来源信息。

    敏感字段（prompt 预览 / session_id）加密后入库；ts 可自定义（演示数据用）。
    """
    meta = meta or {}
    if ts is None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO checks (ts, tool, session_id, input_preview, total_tokens, waste_tokens, findings_json, model) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                ts,
                tool,
                crypto.encrypt_value(_clean(meta.get("session_id", "") or "")),
                crypto.encrypt_value(_clean((meta.get("prompt", "") or "")[:100])),
                result["total_tokens"],
                result["waste_tokens"],
                _clean(json.dumps(result["findings"], ensure_ascii=False)),
                result.get("model", ""),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def migrate():
    """把历史明文行就地加密。幂等：已加密或为空的行跳过。

    升级到 v1.5 后首次运行（history / server 启动时）调用。
    """
    conn = _conn()
    try:
        rows = conn.execute("SELECT id, session_id, input_preview FROM checks").fetchall()
        changed = False
        for row_id, sid, prev in rows:
            new_sid = crypto.encrypt_value(sid or "") if (sid and not crypto.is_encrypted(sid)) else None
            new_prev = crypto.encrypt_value(prev or "") if (prev and not crypto.is_encrypted(prev)) else None
            if new_sid is None and new_prev is None:
                continue
            conn.execute(
                "UPDATE checks SET session_id=?, input_preview=? WHERE id=?",
                (
                    new_sid if new_sid is not None else sid,
                    new_prev if new_prev is not None else prev,
                    row_id,
                ),
            )
            changed = True
        if changed:
            conn.commit()
    finally:
        conn.close()


def fetch_checks():
    """读取记录供周报聚合。无库时返回空列表。

    注意: 返回的 input_preview 是密文，周报不使用它，不回解密。
    """
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


def fetch_records():
    """读取全部记录（含 model 与密文预览），供面板使用。无库时返回空列表。"""
    if not os.path.exists(db_path()):
        return []
    conn = _conn()  # _conn 会确保 model 列存在
    try:
        return conn.execute(
            "SELECT id, ts, tool, session_id, input_preview, total_tokens, waste_tokens, findings_json, model "
            "FROM checks ORDER BY ts"
        ).fetchall()
    finally:
        conn.close()
