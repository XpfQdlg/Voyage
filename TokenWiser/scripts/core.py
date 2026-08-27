"""
TokenWiser 核心引擎

输入习惯检测 + token 分割 + 代价量化。
纯 Python 实现，不依赖任何 agent 工具 SDK，可被任意 agent 调用。
唯一可选依赖：tiktoken（用于精确 token 分割；未安装时自动降级为字符估算）。

本模块是纯函数，无文件副作用。持久化见 store.py。
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re

# ---------------------------------------------------------------------------
# 常量与严重度
# ---------------------------------------------------------------------------

SEV_LOW = "low"
SEV_MEDIUM = "medium"
SEV_HIGH = "high"

# 人民币汇率（USD→CNY）默认值。models.json 的 usd_to_cny 可覆盖，环境变量 TW_USD_TO_CNY 再覆盖。
DEFAULT_USD_TO_CNY = 7.10

DEFAULT_MODELS = {
    "default": {
        "input_per_million": 3.0,
        "output_per_million": 15.0,
        "currency": "USD",
        "note": "示例价格（每 1,000,000 token）。请按实际使用模型修改 models.json。",
    }
}


def usd_to_cny_rate(models=None):
    """人民币汇率（USD→CNY）。

    来源优先级：环境变量 TW_USD_TO_CNY > models.json 的 usd_to_cny > 默认 7.10。
    模型单价仍按美元存储，所有成本与显示金额统一乘此汇率换算成人民币。
    """
    env = os.environ.get("TW_USD_TO_CNY")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    if models:
        try:
            return float(models.get("usd_to_cny", DEFAULT_USD_TO_CNY))
        except (TypeError, ValueError):
            pass
    return DEFAULT_USD_TO_CNY


def _is_peak_time(at=None):
    """DeepSeek 峰谷判断（北京时间）。高峰 9-12 点与 14-18 点，周末全天低谷。

    at 可为 datetime 或 ISO 字符串（记录时刻）；缺省取当前北京时间。
    无峰谷配置的模型不受影响，此函数只服务于 peak/off_peak 定价。
    """
    if at is None:
        at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    elif isinstance(at, str):
        try:
            at = datetime.datetime.fromisoformat(at)
        except ValueError:
            return False
    if at.weekday() >= 5:  # 周六/周日
        return False
    hour = at.hour
    return 9 <= hour < 12 or 14 <= hour < 18


def effective_price(model, models, cache_hit=False, at=None):
    """计费用价格字典：按北京时间峰谷 + 缓存命中/未命中取价。

    有 peak/off_peak 结构的模型（如 DeepSeek）按时段取价；
    其余模型直接用 input/output_per_million，仅 cache_hit=True 且有
    cache_hit_per_million 时改用缓存命中价。
    """
    price = _price_for(model, models)
    peak, off = price.get("peak"), price.get("off_peak")
    if peak and off:
        cfg = peak if _is_peak_time(at) else off
        out = dict(price)
        key = "cache_hit_per_million" if cache_hit else "cache_miss_per_million"
        out["input_per_million"] = cfg.get(key, price.get("input_per_million"))
        out["output_per_million"] = cfg.get("output_per_million", price.get("output_per_million"))
        return out
    if cache_hit and "cache_hit_per_million" in price:
        out = dict(price)
        out["input_per_million"] = price["cache_hit_per_million"]
        return out
    return price


def cost_rmb(tokens, price, models):
    """按价格字典算 tokens 对应的人民币成本。currency=CNY 的模型不再乘汇率。"""
    rate = usd_to_cny_rate(models)
    per_million = price.get("input_per_million", 0)
    if price.get("currency", "USD").upper() != "CNY":
        per_million = per_million * rate
    return tokens * per_million / 1_000_000


def per_million_rmb(price, models, field):
    """把单价字段换算成人民币显示值。CNY 模型原样返回。"""
    value = price.get(field, 0)
    if price.get("currency", "USD").upper() != "CNY":
        value = value * usd_to_cny_rate(models)
    return round(value, 4)


# ---------------------------------------------------------------------------
# Token 分割
# ---------------------------------------------------------------------------

def _load_encoding(name="o200k_base"):
    """加载 tiktoken 编码；不可用时返回 None（走字符估算）。"""
    try:
        import tiktoken
        return tiktoken.get_encoding(name)
    except Exception:
        return None


def tokenize(text, encoding=None):
    """
    返回 (tokens, total)。
    tokens: [{"text": str, "range": [起始字符, 结束字符]}]
    有 encoding 时用真实 BPE 分词；否则字符估算。
    """
    if encoding is not None:
        return _tokenize_bpe(text, encoding)
    return _tokenize_estimate(text)


def _tokenize_bpe(text, encoding):
    """按 BPE 分词，并还原每个 token 的原文与字符区间。"""
    data = text.encode("utf-8")
    ids = encoding.encode_ordinary(text)
    tokens = []
    pos = 0  # 字节偏移
    for tid in ids:
        token_bytes = encoding.decode_single_token_bytes(tid)
        idx = data.find(token_bytes, pos)
        if idx < 0:
            continue
        start_char = len(data[:idx].decode("utf-8", errors="replace"))
        end_char = len(data[: idx + len(token_bytes)].decode("utf-8", errors="replace"))
        tokens.append({
            "text": token_bytes.decode("utf-8", errors="replace"),
            "range": [start_char, end_char],
        })
        pos = idx + len(token_bytes)
    return tokens, len(ids)


def _tokenize_estimate(text):
    """无 tiktoken 时的粗略估算：CJK 每字约 1 token，ASCII 连续段每 4 字符约 1 token。"""
    cjk = re.compile(r"[一-鿿　-〿＀-￯]")
    tokens = []
    total = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if cjk.match(ch):
            tokens.append({"text": ch, "range": [i, i + 1]})
            total += 1
            i += 1
        else:
            j = i
            while j < n and not cjk.match(text[j]):
                j += 1
            seg = text[i:j]
            seg_tokens = max(1, math.ceil(len(seg) / 4))
            tokens.append({"text": seg, "range": [i, j]})
            total += seg_tokens
            i = j
    return tokens, total


# ---------------------------------------------------------------------------
# 检测规则
# ---------------------------------------------------------------------------

def _finding(habit, name, severity, waste, detect, advice):
    """构造一条发现记录。"""
    return {
        "habit": habit,
        "name": name,
        "severity": severity,
        "waste_tokens": int(waste),
        "detect": detect,
        "advice": advice,
    }


# --- 1. 大段日志/代码粘贴 ------------------------------------------------

_LOG_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?", re.I),
    re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}(\.\d+)?(\]\s*)?", re.I),
    re.compile(r"^\s*(ERROR|WARN|WARNING|INFO|DEBUG|TRACE)\b", re.I),
    re.compile(r"Traceback \(most recent call last\)", re.I),
    re.compile(r'^\s*File "[^"]+", line \d+', re.I),
    re.compile(r"^\s+at [\w.$]+(\(.*\))?\s*$"),
    re.compile(r"at 0x[0-9a-fA-F]+"),
    re.compile(r"\[\d{2}:\d{2}:\d{2}\]"),
]


def _is_log_line(line):
    """判断一行是否像日志行。"""
    s = line.strip()
    if not s:
        return False
    return any(p.search(s) for p in _LOG_PATTERNS)


def _log_ratio(text):
    """日志特征行占全部行的比例。"""
    lines = text.splitlines()
    if not lines:
        return 0.0
    return sum(1 for ln in lines if _is_log_line(ln)) / len(lines)


def rule_log_paste(text, tokens, total, encoding):
    lines = text.splitlines()
    if len(lines) < 10:
        return None
    log_lines = [ln for ln in lines if _is_log_line(ln)]
    ratio = _log_ratio(text)
    if ratio < 0.5:
        return None
    waste = tokenize("\n".join(log_lines), encoding)[1]
    severity = SEV_HIGH if (waste >= 200 or ratio >= 0.8) else SEV_MEDIUM
    return _finding(
        "log_paste", "大段日志/代码粘贴", severity, waste,
        f"日志类行 {len(log_lines)}/{len(lines)} 行，占比 {ratio:.0%}",
        "只保留报错/关键那几行，别贴整个日志，一般 5-10 行就够。",
    )


# --- 2. 疑似敏感信息 ------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "API Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"Bearer [A-Za-z0-9._-]{20,}", re.I), "Bearer Token"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
    (re.compile(r"\d{17}[\dXx](?!\d)"), "身份证号"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"), "邮箱"),
]


def _entropy(s):
    """计算字符串的信息熵（比特/字符），用于识别高熵的疑似密钥。"""
    if not s:
        return 0.0
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def rule_secret_leak(text, tokens, total, encoding):
    hits = []
    for pat, label in _SECRET_PATTERNS:
        if pat.search(text):
            hits.append(label)
    # 高熵片段：长且信息熵高，可能是随机生成的密钥。
    # 只对不含中文字符的片段检测——中文句子天然高熵，跳过可避免误报。
    cjk = re.compile(r"[一-鿿　-〿＀-￯]")
    for piece in re.split(r"\s+", text):
        if len(piece) >= 16 and not cjk.search(piece) and _entropy(piece) >= 4.5:
            hits.append("高熵片段")
            break
    if not hits:
        return None
    return _finding(
        "secret_leak", "疑似敏感信息", SEV_HIGH, 0,
        "、".join(sorted(set(hits))),
        "检测到疑似密钥/手机号/身份证，发送给 AI 前请脱敏。",
    )


# --- 3. 单条输入过大 -----------------------------------------------------

def rule_oversized_request(text, tokens, total, encoding):
    if total < 3000:
        return None
    severity = SEV_HIGH if total >= 6000 else SEV_MEDIUM
    return _finding(
        "oversized_request", "单条输入过大", severity, max(0, total - 3000),
        f"总 token {total}",
        "建议拆成小步，每步一个目标，避免截断和降质。",
    )


# --- 4. 冗余开场白 -------------------------------------------------------

_OPENER_RE = re.compile(
    r"^(?:你是一个(?:AI|人工智能|智能)(?:助手|助理)?"
    r"|你是(?:AI|人工智能|智能)(?:助手|助理)?"
    r"|你好|您好|哈喽|嗨|hello|hi)[，,。!！\s]+",
    re.I,
)


def rule_redundant_opener(text, tokens, total, encoding):
    m = _OPENER_RE.match(text)
    if not m:
        return None
    waste = tokenize(m.group(0), encoding)[1]
    if waste < 4:
        return None
    return _finding(
        "redundant_opener", "冗余开场白", SEV_MEDIUM, waste,
        f"开场白 {waste} token",
        "开场白不提供信息，直接进主题。",
    )


# --- 5. 上下文/输出格式缺失 ---------------------------------------------

_CONTEXT_KEYWORDS = [
    "格式", "JSON", "markdown", "列表", "表格", "表", "清单", "输出", "返回",
    "要求", "约束", "限制", "长度", "字以内", "语言", "中文", "英文", "步骤",
    "目标", "用途", "用于", "场景", "风格", "示例",
]

# 多轮对话中的纯跟进/确认词。命中即认为"上一轮刚给过上下文"，不再苛求格式。
_CONFIRM_WORDS = {
    "ok", "好", "好的", "可以", "行", "行吧", "嗯", "嗯嗯", "是的", "没错",
    "对", "没问题", "同步", "推送", "上传", "继续", "收到", "明白", "了解",
    "这样", "那样", "就这样",
}
_CONFIRM_SUFFIXES = ("吧", "了", "先", "就行")
# 单条输入就是一个 URL/本地路径：自带明确对象，不算缺上下文。
_URL_ONLY_RE = re.compile(r"^['\"]?(?:https?://\S+|(?:[A-Za-z]:)?[\\/][^\s'\"<>]+)['\"]?$")


def _is_confirm_followup(text):
    """判断是否为纯确认/跟进句（无新增信息量）。"""
    words = re.findall(r"[A-Za-z0-9]+|[一-鿿]+", text)
    if not words:
        return True
    core = []
    for w in words:
        for suf in _CONFIRM_SUFFIXES:
            if w.endswith(suf):
                w = w[: -len(suf)]
                break
        if w:
            core.append(w)
    return (
        bool(core)
        and all(c.lower() in _CONFIRM_WORDS for c in core)
        and sum(len(c) for c in core) <= 6
    )


def rule_missing_context(text, tokens, total, encoding):
    # 短句与纯跟进句：多轮对话的自然追问，不是独立请求，跳过
    if total <= 8:
        return None
    if _is_confirm_followup(text):
        return None
    if _URL_ONLY_RE.match(text.strip()):
        return None
    if len(text) < 30:
        return None
    if total >= 3000:
        return None
    if _log_ratio(text) >= 0.5:
        return None
    if any(kw in text for kw in _CONTEXT_KEYWORDS):
        return None
    # waste = 输入自身的 token 数（缺上下文最坏是白跑这一轮），上限 300。
    # 不再用固定 300，避免多条命中时 waste 虚高到超过输入总量。
    waste = min(total, 300)
    return _finding(
        "missing_context", "上下文/输出格式缺失", SEV_MEDIUM, waste,
        "未提到目标、约束或输出格式",
        "开头一句话给目标，结尾指定输出格式（如 JSON/表格/列表），能省 1-2 轮往返。",
    )


# --- 6. 指令模糊 ---------------------------------------------------------

_VAGUE_RE = re.compile(
    r"^(?:帮我|请|麻烦)(?:改一下|优化一下|处理一下|弄一下|看一下|修一下|调整|完善|搞定|看看)[。]?$"
    r"|^(?:这个|这个东西|这段|这个代码|这边)?(?:有问题|出问题了|不行|坏了|不好使|报错了|挂了)[。]?$",
    re.I,
)


def rule_vague_instruction(text, tokens, total, encoding):
    if len(text) >= 40:
        return None
    if not _VAGUE_RE.search(text):
        return None
    return _finding(
        "vague_instruction", "指令模糊", SEV_MEDIUM, min(total, 300),
        "未说明具体动作/对象/期望",
        "说清动作 + 对象 + 期望结果。例如'把 login.py 的登录逻辑改为 JWT 校验'。",
    )


# --- 7. 系统注入噪音剥离 -------------------------------------------------

# 嵌入正文中的 XML 注入块（逐块剥离）
_SYSTEM_NOISE_PATTERNS = [
    re.compile(r"<command-message>.*?</command-message>", re.S),
    re.compile(r"<command-name>.*?</command-name>", re.S),
    re.compile(r"<task-notification>.*?</task-notification>", re.S),
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"Permission allow rule[^\n]*", re.I),
    re.compile(r"Base directory for this skill:[^\n]*", re.I),
]


def strip_system_noise(text):
    """剥离注入的系统内容（权限警告、命令消息、任务通知、skill 加载头）。

    仅处理已知注入结构，不碰用户正文。剥离后为空 → 调用方应跳过本次分析。
    """
    if not text:
        return ""
    for pat in _SYSTEM_NOISE_PATTERNS:
        text = pat.sub("", text)
    # 去掉所有 <标签> 后若只剩空白，说明整条就是系统注入标签壳，判空
    residue = re.sub(r"<[^>]+>", "", text).strip()
    if not residue:
        return ""
    return text.strip()


_RULES = [
    rule_log_paste,
    rule_secret_leak,
    rule_oversized_request,
    rule_redundant_opener,
    rule_missing_context,
    rule_vague_instruction,
]


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def analyze_text(text, model="default", models=None, encoding_name="auto", cache_hit=False):
    """
    核心入口：输入文本 → 结构化结果。

    cache_hit: 输入是否按缓存命中价计费（默认 False 按未命中价）。
    峰谷模型（如 DeepSeek）按当前北京时间判断高峰/低谷取价。
    encoding_name: 分词器名；"auto"（默认）按模型的 tokenizer 字段自动选。

    返回:
      {
        "tokens": [{"text", "range"}, ...],
        "findings": [{"habit", "name", "severity", "waste_tokens", "detect", "advice"}, ...],
        "total_tokens": int,
        "estimated_cost": float,      # 人民币
        "waste_tokens": int,
        "waste_cost": float,          # 人民币
        "model": str,
        "currency": str,              # 恒为 "CNY"
      }
    """
    models = models or load_models()  # 统一加载一次，保证价格/汇率/分词器取同一份配置
    if encoding_name in (None, "", "auto"):
        encoding_name = _model_tokenizer(model, models)
    encoding = _load_encoding(encoding_name)
    tokens, total = tokenize(text, encoding)

    findings = []
    for rule in _RULES:
        try:
            finding = rule(text, tokens, total, encoding)
        except Exception:
            finding = None
        if finding:
            findings.append(finding)

    # 规则抑制：已有具体的严重问题（密钥/日志/超长）时，不再补报泛化的"缺上下文"
    specific = {"secret_leak", "log_paste", "oversized_request"}
    if any(f["habit"] in specific for f in findings):
        findings = [f for f in findings if f["habit"] != "missing_context"]

    waste = sum(f["waste_tokens"] for f in findings)
    price = effective_price(model, models, cache_hit=cache_hit)
    cost_input = cost_rmb(total, price, models)
    waste_cost = cost_rmb(waste, price, models)

    return {
        "tokens": tokens,
        "findings": findings,
        "total_tokens": total,
        "estimated_cost": round(cost_input, 6),
        "waste_tokens": waste,
        "waste_cost": round(waste_cost, 6),
        "model": model,
        "currency": "CNY",
    }


def load_models(path=None):
    """
    加载价格表：默认值 + models.json 覆盖 + 环境变量 PROMPT_HABITS_MODELS 覆盖。
    """
    models = json.loads(json.dumps(DEFAULT_MODELS))
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models.json")
    path = os.path.abspath(path)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                models.update(json.load(f))
        except Exception:
            pass
    env = os.environ.get("PROMPT_HABITS_MODELS")
    if env:
        try:
            models.update(json.loads(env))
        except Exception:
            pass
    return models


def detect_model():
    """探测当前使用的模型名。优先级：ANTHROPIC_MODEL > CLAUDE_MODEL > settings.json。

    匹配不到返回 None（调用方回退 default）。Claude Code 的模型名一般带日期后缀
    （如 claude-haiku-4-5-20251001），前缀匹配由 _price_for 处理。
    """
    for env in ("ANTHROPIC_MODEL", "CLAUDE_MODEL"):
        m = os.environ.get(env)
        if m:
            return m
    for path in (
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.claude/settings.local.json"),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            continue
        m = cfg.get("model")
        if m:
            return m
    return None


def _price_for(model, models):
    """取某模型的定价；未知模型回退到 default。支持前缀匹配（模型 id 带日期后缀）。

    models 里除模型名外还有 usd_to_cny / note 等全局配置键，用结构判断跳过，
    避免把它们当模型参与前缀匹配。
    """
    if not models:
        models = load_models()
    if model in models:
        return models[model]
    # 前缀匹配：按键长倒序，避免 gpt-5.4 误配 gpt-5.4-mini、gemini-3.5-flash 误配 lite
    candidates = sorted(
        (k for k, v in models.items() if isinstance(v, dict) and "input_per_million" in v),
        key=len,
        reverse=True,
    )
    for key in candidates:
        if model and model.startswith(key):
            return models[key]
    return models.get("default", DEFAULT_MODELS["default"])


def _model_tokenizer(model, models):
    """按模型取分词器（models.json 的 tokenizer 字段），未配置回退 o200k_base。

    分词器跟随模型走：OpenAI 用 o200k_base（精确），Claude 用 cl100k_base（代理），
    DeepSeek/Qwen/Gemini 暂无 tiktoken 官方编码，先用 o200k_base 代理。
    """
    models = models or load_models()
    enc = _price_for(model, models).get("tokenizer")
    return enc if isinstance(enc, str) and enc else "o200k_base"
