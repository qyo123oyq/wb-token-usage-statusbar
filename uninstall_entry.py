# -*- coding: utf-8 -*-
"""懒人卸载包入口（PyInstaller onefile）。

与安装包共享同一套运行时文件（从 _MEIPASS 解压），但入口直接走卸载流程：
  1. 定位已安装的 asar（config 里记住的 asar_path > 自动探测 > 询问）
  2. 剥离本工具注入行
  3. 移除 MCP 注册
  4. 删除数据目录

用法：
  wb-usage-uninstall.exe            # 交互式卸载
  wb-usage-uninstall.exe --yes      # 跳过确认，直接卸载
  wb-usage-uninstall.exe --dry-run  # 只打印不落盘
"""
import os
import sys
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", None) or Path(__file__).parent.resolve())
sys.path.insert(0, str(HERE))

import install as installer  # noqa: E402
import patch_install as pi   # noqa: E402


def main():
    global LANG
    pre_lang = None
    for a in sys.argv[1:]:
        if a in ("--lang",):
            pre_lang = True
    # 复用 install.py 的语言逻辑
    installer.LANG = installer.cfg_lang() if hasattr(installer, "cfg_lang") else "zh"
    installer.args_lang = None

    dry = "--dry-run" in sys.argv
    yes = "--yes" in sys.argv or "-y" in sys.argv

    lang = installer.LANG

    def L(zh, en):
        return en if lang == "en" else zh

    print(L("=" * 50, "=" * 50))
    print(L("WorkBuddy Token 用量状态栏 · 卸载",
             "WorkBuddy Token Usage Status Bar · Uninstall"))
    print(L("=" * 50, "=" * 50))
    print()

    if not yes:
        try:
            ans = input(L("确认卸载？将剥离 asar 注入行、移除 MCP 注册并删除数据目录。[y/N] ",
                           "Confirm uninstall? Will strip asar injection, remove MCP reg and data dir. [y/N] "))
        except (EOFError, KeyboardInterrupt):
            print(L("已取消。", "Cancelled."))
            return 0
        if ans.strip().lower() not in ("y", "yes"):
            print(L("已取消。", "Cancelled."))
            return 0

    # 定位 asar
    asar = installer.find_installed_asar(None)
    if not asar or not Path(asar).is_file():
        print(L("[卸载] 未找到 app.asar（WorkBuddy 可能已卸载或换了位置），跳过 asar 剥离，仅清理注册与数据。",
                 "[uninstall] app.asar not found; skipping asar strip, cleaning registration & data only."))
        asar = None
    else:
        print(L(f"[目标] {asar}", f"[target] {asar}"))

    ok = True
    if asar:
        pi.set_target(asar)
        # 数据目录里的 inject-main.cjs 才是注入行指向的 loader；卸载时用数据目录作 runtime
        pi.set_runtime(installer.DATA_DIR if installer.DATA_DIR.exists() else HERE)
        if dry:
            print(L("[注入] （dry-run）patch_install.py remove",
                     "[inject] (dry-run) patch_install.py remove"))
        else:
            ok = pi.remove()
    if not dry:
        installer.remove_mcp(dry)
        installer.remove_command(dry)
        installer.remove_data_dir(dry)
    else:
        print(L("[MCP] （dry-run）移除注册", "[mcp] (dry-run) remove registration"))
        print(L("[命令] （dry-run）删除 /usage", "[cmd] (dry-run) delete /usage"))
        print(L("[数据] （dry-run）删除数据目录", "[data] (dry-run) delete data dir"))

    print()
    print(L("卸载完成。重启 WorkBuddy 后悬浮条消失。",
             "Uninstall complete. Restart WorkBuddy and the floating bar is gone."))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)