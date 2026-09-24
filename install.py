# -*- coding: utf-8 -*-
"""「WorkBuddy Token 用量状态栏」一键安装（标准库实现，零依赖）。

标准安装形态：仓库只是源码，install.py 把运行时复制到数据目录
  ~/.workbuddy/wb-token-usage-statusbar/
（inject-main.cjs / overlay.js / busage.py / mcp_server.py + config.json），
asar 注入行与 MCP 注册都指向数据目录 —— 之后 clone 目录可以随意搬走或删除，
已安装实例照常运行。

用法（仓库根目录）：
  python install.py               # 全量：复制运行时 → 注入 asar → 注册 MCP → /usage 命令
  python install.py --root PATH   # 指定 WorkBuddy 根目录（自动接 resources/app.asar）
                                  #   Windows：python install.py --root E:\\WorkBuddy
  python install.py --asar PATH   # 指定 app.asar 完整路径
  python install.py --no-mcp      # 只装状态条，不动 MCP
  python install.py --dev         # 开发模式：不复制运行时，注入直指本仓库目录
  python install.py --remove      # 卸载
  python install.py --dry-run
  python install.py --lang en
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).parent.resolve())


def _real_home():
    if sys.platform != "win32" and os.environ.get("SUDO_USER"):
        try:
            import pwd
            if os.geteuid() == 0:
                return Path(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir)
        except Exception:
            pass
    return Path.home()


DATA_DIR = _real_home() / ".workbuddy" / "wb-token-usage-statusbar"
WORKBUDDY_CONFIG = _real_home() / ".workbuddy" / "mcp.json"   # WorkBuddy MCP 配置
MCP_NAME = "wb-token-usage-statusbar"
RUNTIME_FILES = ("inject-main.cjs", "overlay.js", "busage.py", "mcp_server.py")

if sys.platform == "darwin":
    ASAR_CANDIDATES = [
        "/Applications/WorkBuddy.app/Contents/Resources/app.asar",
        "~/Applications/WorkBuddy.app/Contents/Resources/app.asar",
    ]
elif sys.platform.startswith("linux"):
    ASAR_CANDIDATES = [
        "/opt/workbuddy/resources/app.asar",
        "/opt/WorkBuddy/resources/app.asar",
        "/usr/lib/workbuddy/resources/app.asar",
    ]
else:
    ASAR_CANDIDATES = [
        r"E:\WorkBuddy\resources\app.asar",
        r"D:\WorkBuddy\resources\app.asar",
        r"C:\WorkBuddy\resources\app.asar",
        r"%LOCALAPPDATA%\Programs\WorkBuddy\resources\app.asar",
        r"%ProgramFiles%\WorkBuddy\resources\app.asar",
    ]

LANG = "zh"


def L(zh, en):
    return en if LANG == "en" else zh


def expand(p):
    return Path(os.path.expandvars(os.path.expanduser(p)))


def load_lang_from_config(dev):
    cfg = HERE / "config.json" if dev else DATA_DIR / "config.json"
    try:
        lang = json.loads(cfg.read_text(encoding="utf-8")).get("lang")
        return lang if lang in ("zh", "en") else None
    except (OSError, ValueError):
        return None


def asar_package_name(asar_path):
    import struct
    try:
        with open(asar_path, "rb") as f:
            a, b, c, d = struct.unpack("<4I", f.read(16))
            if a != 4:
                return None
            header = json.loads(f.read(d))
        node = header.get("files", {}).get("package.json")
        if not isinstance(node, dict) or "size" not in node:
            return None
        with open(asar_path, "rb") as f:
            f.seek(8 + b + int(node["offset"]))
            data = f.read(int(node["size"]))
        if b"\x00" in data:
            return None
        return json.loads(data.decode("utf-8")).get("name")
    except Exception:
        return None


def is_workbuddy_app(asar_path):
    asar_path = Path(asar_path)
    if (asar_path.parent.parent / "WorkBuddy.exe").is_file():
        return True
    name = asar_package_name(asar_path)
    if isinstance(name, str) and "workbuddy" in name.lower():
        return True
    return False


def find_asar():
    env = os.environ.get("WORKBUDDY_ASAR")
    if env:
        p = expand(env)
        if p.is_file():
            return p
    for c in ASAR_CANDIDATES:
        p = expand(c)
        if p.is_file():
            return p
    if sys.platform == "win32":
        prog = expand(r"%LOCALAPPDATA%\Programs")
        if prog.is_dir():
            for ch in prog.iterdir():
                p = ch / "resources" / "app.asar"
                if p.is_file() and is_workbuddy_app(p):
                    return p
    return None


def ask_asar():
    if not sys.stdin.isatty():
        return None
    try:
        s = input(L("未自动找到 WorkBuddy，请输入 app.asar 完整路径（回车取消）: ",
                    "WorkBuddy not found. Enter the full path to app.asar (Enter to cancel): ")).strip('" ')
    except (EOFError, KeyboardInterrupt):
        return None
    p = Path(s)
    return p if p.is_file() else None


def find_installed_asar(explicit=None):
    if explicit:
        return Path(explicit)
    for cfg in (DATA_DIR / "config.json", HERE / "config.json"):
        try:
            p = json.loads(cfg.read_text(encoding="utf-8")).get("asar_path")
            if p and Path(p).is_file():
                return Path(p)
        except (OSError, ValueError):
            pass
    return find_asar() or ask_asar()


def remember_asar(asar, dev):
    cfg = HERE / "config.json" if dev else DATA_DIR / "config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    except (OSError, ValueError):
        data = {}
    if data.get("asar_path") == str(asar):
        return
    data["asar_path"] = str(asar)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(L(f"[目标] 已记住安装位置 → {cfg}",
             f"[target] install location remembered -> {cfg}"))


def chown_to_user(path):
    if sys.platform != "win32" and os.environ.get("SUDO_USER"):
        try:
            import pwd
            st = pwd.getpwnam(os.environ["SUDO_USER"])
            os.chown(path, st.pw_uid, st.pw_gid)
        except Exception:
            pass


def copy_runtime(dry):
    for name in RUNTIME_FILES:
        src = HERE / name
        assert src.is_file(), L(f"缺少运行时文件：{src}", f"Missing runtime file: {src}")
    print(L(f"[运行时] 复制 {len(RUNTIME_FILES)} 个文件 → {DATA_DIR}",
             f"[runtime] copying {len(RUNTIME_FILES)} files -> {DATA_DIR}"))
    if not dry:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        chown_to_user(DATA_DIR)
        for name in RUNTIME_FILES:
            shutil.copy2(HERE / name, DATA_DIR / name)
            chown_to_user(DATA_DIR / name)
    return True


def prepare_config(dry, dev):
    cfg = HERE / "config.json" if dev else DATA_DIR / "config.json"
    if cfg.exists():
        if args_lang:
            if not dry:
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    data["lang"] = LANG
                    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                except (OSError, ValueError):
                    pass
            print(L(f"[配置] 沿用 {cfg}（lang = {LANG}）",
                     f"[config] keeping {cfg} (lang = {LANG})"))
        else:
            print(L(f"[配置] 沿用 {cfg}", f"[config] keeping existing {cfg}"))
        return True
    if not dev and (HERE / "config.json").exists():
        if not dry:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(HERE / "config.json", cfg)
        print(L(f"[配置] 迁移 {HERE / 'config.json'} → {cfg}",
                 f"[config] migrating {HERE / 'config.json'} -> {cfg}"))
        return True
    vals = {
        "python_path": sys.executable,
        "poll_ms": 2000,
        "hot_reload": True,
        "context_window": 0,
        "lang": LANG,
        "show": {"context": True, "turn": True, "session": True,
                 "today": True, "model": True, "status": True},
    }
    print(L(f"[配置] 生成 {cfg}（python_path = {sys.executable}）",
             f"[config] generating {cfg} (python_path = {sys.executable})"))
    if not dry:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        chown_to_user(cfg.parent)
        cfg.write_text(json.dumps(vals, indent=2, ensure_ascii=False), encoding="utf-8")
        chown_to_user(cfg)
    return True


def register_mcp(dry, dev):
    mcp_py = HERE / "mcp_server.py" if dev else DATA_DIR / "mcp_server.py"
    entry = {"command": sys.executable, "args": [str(mcp_py)]}
    if not WORKBUDDY_CONFIG.is_file():
        data = {"mcpServers": {MCP_NAME: entry}}
    else:
        try:
            data = json.loads(WORKBUDDY_CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(L(f"[MCP] 跳过：{WORKBUDDY_CONFIG} 不是有效 JSON（{e}）",
                     f"[mcp] skipped: {WORKBUDDY_CONFIG} is not valid JSON ({e})"))
            return False
        servers = data.get("mcpServers", data.get("mcp", {}).get("servers", {}))
        servers[MCP_NAME] = entry
        data["mcpServers"] = servers
    print(L(f"[MCP] 注册 {MCP_NAME} → {mcp_py}",
             f"[mcp] registering {MCP_NAME} -> {mcp_py}"))
    if not dry:
        WORKBUDDY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        chown_to_user(WORKBUDDY_CONFIG.parent)
        if WORKBUDDY_CONFIG.is_file():
            shutil.copy2(WORKBUDDY_CONFIG, WORKBUDDY_CONFIG.with_suffix(".json.wbusage.bak"))
        WORKBUDDY_CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        chown_to_user(WORKBUDDY_CONFIG)
    return True


def remove_mcp(dry):
    if not WORKBUDDY_CONFIG.is_file():
        return True
    try:
        data = json.loads(WORKBUDDY_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    servers = data.get("mcpServers", data.get("mcp", {}).get("servers", {}))
    if MCP_NAME in servers:
        del servers[MCP_NAME]
        print(L(f"[MCP] 移除注册：{MCP_NAME}", f"[mcp] removing registration: {MCP_NAME}"))
        if not dry:
            shutil.copy2(WORKBUDDY_CONFIG, WORKBUDDY_CONFIG.with_suffix(".json.wbusage.bak"))
            WORKBUDDY_CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def install_command(dry):
    """复制 /usage 命令模板到 WorkBuddy 命令目录（如存在则写入，否则仅提示）。"""
    cmd_dir = _real_home() / ".workbuddy" / "commands"
    dst = cmd_dir / "usage.md"
    src = HERE / "usage.command.md"
    if not src.is_file():
        return True
    print(L(f"[命令] {dst}", f"[command] {dst}"))
    if not dry:
        cmd_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        chown_to_user(dst)
    return True


def remove_command(dry):
    dst = _real_home() / ".workbuddy" / "commands" / "usage.md"
    if dst.is_file():
        if not dry:
            dst.unlink()
        print(L(f"[命令] 删除 {dst}", f"[command] deleting {dst}"))
    return True


def remove_data_dir(dry):
    if not DATA_DIR.exists():
        return True
    print(L(f"[数据] 删除数据目录 {DATA_DIR}", f"[data] deleting data directory {DATA_DIR}"))
    if not dry:
        shutil.rmtree(DATA_DIR)
    return True


def main():
    global LANG, args_lang
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=("zh", "en"))
    pre.add_argument("--dev", action="store_true")
    pre_args, _ = pre.parse_known_args()
    LANG = pre_args.lang or load_lang_from_config(pre_args.dev) or "zh"

    ap = argparse.ArgumentParser(
        description=L("WorkBuddy Token 用量状态栏 一键安装",
                       "WorkBuddy Token Usage Status Bar installer"))
    ap.add_argument("--asar", help=L("app.asar 完整路径", "full path to app.asar"))
    ap.add_argument("--root", help=L("WorkBuddy 根目录（如 E:\\WorkBuddy）",
                                     "WorkBuddy root directory (e.g. E:\\WorkBuddy)"))
    ap.add_argument("--no-mcp", action="store_true", help=L("跳过 MCP 注册", "skip MCP"))
    ap.add_argument("--dev", action="store_true",
                    help=L("开发模式：不复制运行时，注入直指本仓库",
                           "dev mode: no runtime copy; injection points at this repo"))
    ap.add_argument("--remove", action="store_true", help=L("卸载", "uninstall"))
    ap.add_argument("--dry-run", action="store_true", help=L("只打印不落盘", "dry run"))
    ap.add_argument("--lang", choices=("zh", "en"), default=None,
                    help=L("输出语言", "output language"))
    args = ap.parse_args()
    args_lang = args.lang
    if args.lang:
        LANG = args.lang

    import patch_install as pi

    if args.remove:
        if args.dry_run:
            print(L("[卸载] （dry-run）剥离 asar 注入行 + 清理 MCP 注册 + 删除数据目录",
                     "[uninstall] (dry-run) strip asar injection + MCP + data dir"))
            return 0
        asar = find_installed_asar(args.asar)
        ok = True
        if asar and asar.is_file():
            print(L(f"[目标] {asar}", f"[target] {asar}"))
            pi.set_target(asar)
            pi.set_runtime(DATA_DIR)
            ok = pi.remove()
        if not args.no_mcp:
            remove_mcp(args.dry_run)
            remove_command(args.dry_run)
        remove_data_dir(args.dry_run)
        print(L("卸载完成。", "Uninstall complete."))
        return 0 if ok else 1

    if args.root:
        asar = expand(args.root) / "resources" / "app.asar"
    elif args.asar:
        p = expand(args.asar)
        asar = p / "app.asar" if p.is_dir() else p
    else:
        asar = find_asar() or ask_asar()
    if not asar or not asar.is_file():
        ex = r"--root E:\WorkBuddy" if sys.platform == "win32" else (
            "--root /Applications/WorkBuddy.app" if IS_MAC else "--root /opt/workbuddy")
        print(L(f"找不到 app.asar。用 --root 指向 WorkBuddy 安装目录，例如：python install.py {ex}",
                 f"app.asar not found. Point --root at the WorkBuddy install dir, e.g.: python install.py {ex}"))
        return 1
    print(L(f"[目标] {asar}", f"[target] {asar}"))
    if sys.platform != "win32" and os.geteuid() != 0 and not os.access(ASAR, os.W_OK):
        print(L(f"[权限] {asar.parent} 不可写，需要 sudo：sudo {Path(sys.executable).name} install.py",
                 f"[permission] not writable; use sudo"))
        if not args.dry_run:
            return 1

    if not args.dry_run:
        pi.set_target(asar)
        if not args.dev:
            pi.set_runtime(DATA_DIR)
        else:
            pi.set_runtime(HERE)

    if not args.dev:
        copy_runtime(args.dry_run)
    prepare_config(args.dry_run, args.dev)
    if args.dry_run:
        print(L("[注入] （dry-run）patch_install.py install",
                 "[inject] (dry-run) patch_install.py install"))
        ok = True
    else:
        ok = pi.install()
        remember_asar(asar, args.dev)
    if not ok:
        print(L("asar 注入未完成，MCP 部分仍会继续。",
                 "asar injection did not finish; MCP part continues."))
    if not args.no_mcp:
        register_mcp(args.dry_run, args.dev)
        install_command(args.dry_run)
    print("\n" + L("全部完成。重启 WorkBuddy 后窗口底部出现悬浮条；对话内可用 token_usage 工具查询。",
                     "All done. Restart WorkBuddy for the floating bar; use the token_usage tool in chat."))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)