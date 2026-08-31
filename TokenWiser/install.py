#!/usr/bin/env python3
"""
TokenWiser 一键安装器

下载整个文件夹后运行:

    python install.py

自动完成三件事，幂等（重复运行不产生重复配置、不覆盖你已有的其他设置）:

  1. 把 skill 本体装到 ~/.claude/skills/tokenwiser/
     （排除 data/、.git、__pycache__ —— 个人数据与缓存不进安装）
  2. 按检测到的 agent 配置底部状态栏（statusLine，同一份 scripts/status.py）:
       Claude Code        ->  ~/.claude/settings.json    hook + statusLine（全自动）
       Gemini/Antigravity ->  ~/.gemini/.../settings.json statusLine（协议与 Claude 相同）
       Cursor / Windsurf  ->  提示装"自定义状态栏"扩展并指向 status.py
       Codex CLI          ->  提示内置 used-tokens 段（自定义命令待上游支持）
  3. 检查 Python 依赖（cryptography / tiktoken / flask），缺失可选安装

选项:
  --link       用符号链接指向当前目录（开发模式；Windows 需开发者模式或管理员）
  --no-deps    跳过依赖检查与安装
  --yes        依赖缺失时直接安装，不询问
  --dry-run    只打印将要执行的动作，不做任何改动
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_HOME = os.path.expanduser("~")

# 路径默认值；环境变量用于测试/自定义
SKILLS_DIR = os.environ.get("TW_SKILLS_DIR", os.path.join(_HOME, ".claude", "skills"))
SETTINGS = os.environ.get("TW_SETTINGS", os.path.join(_HOME, ".claude", "settings.json"))
GEMINI_SETTINGS = os.environ.get("TW_GEMINI_SETTINGS", os.path.join(_HOME, ".gemini", "antigravity-cli", "settings.json"))
CODEX_CONFIG = os.environ.get("TW_CODEX_CONFIG", os.path.join(_HOME, ".codex", "config.toml"))
CURSOR_DIR = os.path.join(_HOME, ".cursor")
WINDSURF_DIR = os.path.join(_HOME, ".codeium", "windsurf")

DEST_NAME = "tokenwiser"
DEST = os.path.join(SKILLS_DIR, DEST_NAME)
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))

_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "data")
DEFAULT_DEPS = ["cryptography", "tiktoken", "flask"]


def wsl_path(path):
    """路径转正斜杠（Windows 命令串安全）。"""
    return path.replace(os.sep, "/")


def load_json(path):
    """读 JSON 配置；不存在返回 {}，读坏则备份后返回 {}。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        shutil.copy2(path, path + ".bak")
        print(f"! {path} 解析失败，已备份为 .bak 并重建")
        return {}


def save_json(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# 1. 安装 skill 本体
# ---------------------------------------------------------------------------

def install_skill(dry_run, use_link):
    """把 skill 装到 DEST，返回脚本目录。"""
    scripts_dir = os.path.join(DEST, "scripts")
    if os.path.islink(DEST):
        print(f"· {DEST} 已是链接（指向源码），跳过复制")
        return scripts_dir
    if os.path.isfile(DEST):
        print(f"! {DEST} 是文件不是目录，请先删除后再装")
        return None
    if os.path.isdir(DEST):
        print(f"· {DEST} 已存在，增量更新代码（数据/缓存不动）")
        if not dry_run:
            shutil.copytree(SOURCE_DIR, DEST, dirs_exist_ok=True, ignore=_IGNORE)
        return scripts_dir
    # 全新安装
    if dry_run:
        print(f"· 将安装到 {DEST}")
        return scripts_dir
    os.makedirs(SKILLS_DIR, exist_ok=True)
    if use_link:
        try:
            os.symlink(SOURCE_DIR, DEST, target_is_directory=True)
            print(f"· 已建链接 {DEST} -> {SOURCE_DIR}")
            return scripts_dir
        except OSError as e:
            print(f"! 建链接失败（{e}）。Windows 需开发者模式或管理员。改为复制。")
    shutil.copytree(SOURCE_DIR, DEST, ignore=_IGNORE)
    print(f"· 已安装到 {DEST}")
    return scripts_dir


# ---------------------------------------------------------------------------
# 2. 状态栏配置（同一份 status.py，按 agent 落到不同配置文件）
# ---------------------------------------------------------------------------

def ensure_hook(cfg, scripts_dir):
    """Claude Code 的 UserPromptSubmit hook，幂等。"""
    cmd = sys.executable + " " + wsl_path(os.path.join(scripts_dir, "hook.py"))
    hooks = cfg.setdefault("hooks", {})
    entries = hooks.setdefault("UserPromptSubmit", [])
    for entry in entries:
        for h in entry.get("hooks", []):
            c = h.get("command", "")
            if "tokenwiser" in c and "hook.py" in c:
                return False
    entries.append({"hooks": [{"type": "command", "command": cmd, "timeout": 30}]})
    return True


def ensure_statusline(cfg, scripts_dir, refresh_interval=None):
    """给任意 agent 写 statusLine（协议相同：command -> stdout 文本）。"""
    cmd = sys.executable + " " + wsl_path(os.path.join(scripts_dir, "status.py"))
    cur = cfg.get("statusLine")
    if cur:
        c = str(cur.get("command", ""))
        if "tokenwiser" in c and "status.py" in c:
            return False  # 已是我们的，不动
        return "conflict"  # 已有别人的，不覆盖
    block = {"type": "command", "command": cmd}
    if refresh_interval:
        block["refreshInterval"] = refresh_interval
    cfg["statusLine"] = block
    return True


def config_claude(scripts_dir):
    cfg = load_json(SETTINGS)
    h = ensure_hook(cfg, scripts_dir)
    s = ensure_statusline(cfg, scripts_dir, refresh_interval=5)
    save_json(SETTINGS, cfg)
    return h, s


def config_gemini(scripts_dir):
    cfg = load_json(GEMINI_SETTINGS)
    s = ensure_statusline(cfg, scripts_dir)  # Gemini 不认 refreshInterval，不写
    save_json(GEMINI_SETTINGS, cfg)
    return s


def print_guide_cursor(scripts_dir):
    print("""
· Cursor 检测到：状态栏为可选增强（核心实时显示走 hook 行内提示与本地面板，无需必配）。如需要：
  状态栏需借 VS Code 扩展。步骤：
  1) 装扩展 "自定义状态栏" (leo-zhao.custom-status-bar)
  2) 在 ~/.cursor/User/settings.json 加:
     "customStatusBar.items": [{
       "id": "tokenwiser",
       "shell": "python %s",
       "intervalSec": 5,
       "text": "${output}"
     }]
""" % wsl_path(os.path.join(scripts_dir, "status.py")))


def print_guide_windsurf(scripts_dir):
    print("""
· Windsurf 检测到：状态栏为可选增强（核心实时显示走 hook 行内提示与本地面板，无需必配）。如需要：
  状态栏需借 VS Code 扩展。步骤：
  1) 装扩展 "自定义状态栏" (leo-zhao.custom-status-bar)
  2) 在 ~/.codeium/windsurf/User/settings.json 加:
     "customStatusBar.items": [{
       "id": "tokenwiser",
       "shell": "python %s",
       "intervalSec": 5,
       "text": "${output}"
     }]
""" % wsl_path(os.path.join(scripts_dir, "status.py")))


def print_guide_codex():
    print("""
· Codex CLI 检测到：当前只支持内置 status_line 段，不支持自定义命令。
  可先在 ~/.codex/config.toml 加内置用量段:
     [tui]
     status_line = ["used-tokens", "context-remaining"]
  自定义命令（Claude/Gemini 同款 status.py）待上游支持:
  https://github.com/openai/codex/issues/20043
""")


# ---------------------------------------------------------------------------
# 3. 依赖检查
# ---------------------------------------------------------------------------

def check_deps(auto_install, yes):
    missing = [m for m in DEFAULT_DEPS if importlib.util.find_spec(m) is None]
    if not missing:
        print(f"· 依赖齐全（{', '.join(DEFAULT_DEPS)}）")
        return True
    print(f"· 缺少依赖: {', '.join(missing)}（加密/精确分词/面板可选但建议装）")
    if not auto_install:
        return False
    if not yes:
        try:
            ans = input("  现在安装？[y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans != "y":
            print("  跳过。之后可手动 pip install " + " ".join(missing))
            return False
    print("  正在 pip 安装 ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="TokenWiser 一键安装器")
    ap.add_argument("--link", action="store_true", help="符号链接到源码目录（开发模式）")
    ap.add_argument("--no-deps", action="store_true", help="跳过依赖检查/安装")
    ap.add_argument("--yes", action="store_true", help="依赖缺失直接安装，不询问")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不改动")
    args = ap.parse_args()

    print("=== TokenWiser 安装器 ===")
    scripts_dir = install_skill(args.dry_run, args.link)
    if scripts_dir is None:
        sys.exit(1)

    if args.dry_run:
        cmd = sys.executable + " " + wsl_path(os.path.join(scripts_dir, "status.py"))
        print(f"· [dry-run] 将写入 statusLine 命令: {cmd}")
        print("· [dry-run] Claude Code 还会写入 hook 命令: " + sys.executable + " "
              + wsl_path(os.path.join(scripts_dir, "hook.py")))
        print("（dry-run 结束，未做任何改动）")
        return

    # --- Claude Code: hook + statusLine ---
    if os.path.exists(SETTINGS) or os.path.exists(os.path.join(_HOME, ".claude")):
        h, s = config_claude(scripts_dir)
        print("· Claude Code hook:", "已添加" if h else "已存在（跳过）")
        print("· Claude Code statusLine:", "已添加" if s is True else
              ("已是本工具（跳过）" if s is False else "已有别的 statusLine（未覆盖）"))

    # --- Gemini / Antigravity: statusLine（同协议）---
    if os.path.exists(GEMINI_SETTINGS) or os.path.exists(os.path.join(_HOME, ".gemini")):
        s = config_gemini(scripts_dir)
        print("· Gemini CLI statusLine:", "已添加" if s is True else
              ("已是本工具（跳过）" if s is False else "已有别的 statusLine（未覆盖）"))

    # --- Cursor / Windsurf / Codex: 引导 ---
    if os.path.exists(CURSOR_DIR):
        print_guide_cursor(scripts_dir)
    if os.path.exists(WINDSURF_DIR):
        print_guide_windsurf(scripts_dir)
    if os.path.exists(CODEX_CONFIG) or os.path.exists(os.path.join(_HOME, ".codex")):
        print_guide_codex()

    # --- 依赖 ---
    if not args.no_deps:
        check_deps(True, args.yes)
    else:
        print("· 已跳过依赖检查")

    print("\n✓ 安装完成。请重启对应 agent（配置在启动时读取）生效。")
    print("  主动分析: echo '输入' | python scripts/analyze.py   |   面板: python scripts/server.py")


if __name__ == "__main__":
    main()
