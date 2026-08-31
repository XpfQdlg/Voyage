#!/usr/bin/env python3
"""
TokenWiser 验收测试（技术方案 v3 第七节）

覆盖:
    1. 敏感信息规则精度（Luhn/USCC/连接串/PEM/邮箱降级/分类）
    2. redact 打码
    3. aggregate_today_week 聚合口径
    4. status.py --short
    5. hook warn/block（子进程，隔离 HOME）
    6. install.py statusLine 命令用 sys.executable

运行:
    python scripts/test_plan.py
"""
import datetime
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, ROOT)  # install.py 在项目根

# 强制 UTF-8 输出，避免 Windows 控制台中文乱码
for _s in (sys.stdout, sys.stderr):
    if _s and hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from core import _luhn_valid, _uscc_valid, aggregate_today_week, analyze_text, redact_sensitive

import store

_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def _make_uscc(seed=3):
    """构造一个校验位合法的统一社会信用代码（用于测试）。"""
    random.seed(seed)
    pre = "91350100M0001" + "".join(random.choice(_USCC_CHARS) for _ in range(4))
    s = sum(_USCC_CHARS.index(pre[i]) * _USCC_WEIGHTS[i] for i in range(17))
    return pre + _USCC_CHARS[(31 - s % 31) % 31]


class TestRules(unittest.TestCase):
    def _leak(self, text):
        r = analyze_text(text, model="claude-haiku-4-5")
        return [f for f in r["findings"] if f["habit"] == "secret_leak"]

    def test_api_key_credential_high(self):
        f = self._leak("key=sk-" + "a" * 30)
        self.assertTrue(f)
        self.assertEqual(f[0]["severity"], "high")
        self.assertEqual(f[0]["subtype"], "credential")

    def test_luhn_card(self):
        f = self._leak("卡号 4111111111111111")
        self.assertTrue(f)
        self.assertIn("银行卡号", f[0]["detect"])

    def test_bad_number_no_false_positive(self):
        self.assertFalse(self._leak("订单号 1234567890123456"))

    def test_phone_pii(self):
        f = self._leak("手机 13812345678")
        self.assertTrue(f)
        self.assertEqual(f[0]["subtype"], "pii")

    def test_email_medium(self):
        f = self._leak("联系 a@b.com")
        self.assertTrue(f)
        self.assertEqual(f[0]["severity"], "medium")
        self.assertEqual(f[0]["subtype"], "contact")

    def test_conn_string(self):
        f = self._leak("mysql://root:p@10.0.0.5:3306/appdb")
        self.assertTrue(f)
        self.assertIn("数据库连接串", f[0]["detect"])

    def test_pem(self):
        f = self._leak("-----BEGIN RSA PRIVATE KEY-----")
        self.assertTrue(f)
        self.assertIn("私钥", f[0]["detect"])

    def test_uscc_valid(self):
        code = _make_uscc()
        self.assertTrue(_uscc_valid(code))
        f = self._leak("统一社会信用代码 " + code)
        self.assertTrue(f)
        self.assertIn("统一社会信用代码", f[0]["detect"])

    def test_uscc_tampered(self):
        code = _make_uscc()
        bad = code[:-1] + ("0" if code[-1] != "0" else "1")
        self.assertFalse(_uscc_valid(bad))
        self.assertFalse(self._leak("一段文本 " + bad))


class TestRedact(unittest.TestCase):
    def test_redact_secret(self):
        key = "sk-" + "a" * 30
        out = redact_sensitive("key=" + key + " 联系 a@b.com 卡 4111111111111111")
        self.assertNotIn(key, out)
        self.assertIn("[REDACTED:API Key]", out)
        self.assertIn("[REDACTED:邮箱]", out)
        self.assertIn("[REDACTED:银行卡号]", out)

    def test_redact_plain_unchanged(self):
        t = "正常问题，帮我写个排序函数"
        self.assertEqual(redact_sensitive(t), t)


class TestAggregate(unittest.TestCase):
    def test_aggregate_today_week(self):
        today = datetime.date.today().isoformat()
        rows = [
            (1, f"{today}T10:00:00", "claude-haiku-4-5", 1000, 100),
            (2, f"{today}T11:00:00", "claude-haiku-4-5", 2000, 0),
        ]
        agg = aggregate_today_week(rows)
        self.assertEqual(agg["today"]["count"], 2)
        self.assertEqual(agg["today"]["tokens"], 3000)
        self.assertEqual(agg["today"]["waste"], 100)
        self.assertGreater(agg["today"]["cost"], 0)
        self.assertGreater(agg["today"]["waste_cost"], 0)
        self.assertEqual(agg["week"]["tokens"], 3000)  # 本周至少含今天


class TestStatus(unittest.TestCase):
    def test_status_short(self):
        r = subprocess.run(
            [sys.executable, "status.py", "--short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=SCRIPTS,
        )
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.strip())


class TestHook(unittest.TestCase):
    """子进程跑 hook.py。临时 HOME 隔离密钥，测试后清理写入库的记录。"""

    def setUp(self):
        conn = store._conn()
        self.max_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM checks").fetchone()[0]
        conn.close()

    def tearDown(self):
        conn = store._conn()
        conn.execute("DELETE FROM checks WHERE id > ?", (self.max_id,))
        conn.commit()
        conn.close()

    def _run_hook(self, prompt, env_extra):
        env = dict(os.environ)
        env.update({
            "TW_HINT_INTERVAL": "0",
            "HOME": tempfile.mkdtemp(),
            "USERPROFILE": tempfile.mkdtemp(),
        })
        env.update(env_extra)
        payload = json.dumps({"prompt": prompt, "session_id": "test-hook"})
        return subprocess.run(
            [sys.executable, "hook.py"], input=payload,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=SCRIPTS, env=env,
        )

    def test_hook_warn_exit1_no_value(self):
        key = "sk-" + "b" * 30
        r = self._run_hook("帮我看看这个 key " + key, {"TW_SECRET_ACTION": "warn"})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn(key, r.stderr)  # 不回显敏感值

    def test_hook_block(self):
        key = "sk-" + "c" * 30
        r = self._run_hook("key " + key, {"TW_SECRET_ACTION": "block"})
        # block 语义以实测为准：支持阻断则 exit 2，否则退化为警告 exit 1
        self.assertIn(r.returncode, (1, 2))
        self.assertNotIn(key, r.stderr)

    def test_hook_clean_exit0(self):
        r = self._run_hook("你好，帮我写个排序函数", {"TW_SECRET_ACTION": "warn"})
        self.assertEqual(r.returncode, 0)


class TestInstall(unittest.TestCase):
    def test_statusline_uses_sys_executable(self):
        import install
        cfg = {}
        install.ensure_statusline(cfg, SCRIPTS)
        self.assertTrue(cfg["statusLine"]["command"].startswith(sys.executable))


if __name__ == "__main__":
    unittest.main(verbosity=2)
