# -*- coding: utf-8 -*-
"""WorkBuddy app.asar 注入/卸载工具（wb-token-usage-statusbar）。

用法：
  python patch_install.py install            # 安装/重定向（幂等；自动替换旧注入行）
  python patch_install.py install --finalize # 客户端退出后完成替换
  python patch_install.py remove             # 卸载（从 asar 剥离本工具注入行，不依赖备份）
  python patch_install.py check              # 检查当前注入状态与入口语法

原理：WorkBuddy asar 主入口 main/index.js 尾部追加一行 require(loader)（CommonJS；
package.json 未设 type:module）。Electron fuses 未嵌入（无 sentinel），改动 asar 可正常加载。
安装/卸载均只增删本工具自己的注入行（WBUSAGE_LINE_RE 识别，不限目录的历史行一并匹配），
不制作也不依赖 asar 备份。
"""
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if IS_WIN:
    ASAR_DEFAULT = Path(r"E:\WorkBuddy\resources\app.asar")
elif IS_MAC:
    ASAR_DEFAULT = Path("/Applications/WorkBuddy.app/Contents/Resources/app.asar")
else:
    ASAR_DEFAULT = Path("/opt/workbuddy/resources/app.asar")
ASAR = ASAR_DEFAULT
TMP = ASAR.with_name("app.asar.wbusage.tmp")
HERE = Path(__file__).parent.resolve()
RUNTIME = HERE
LOADER = RUNTIME / "inject-main.cjs"
ENTRY = "main/index.js"   # WorkBuddy asar 主入口（package.json main 字段）
# CJS 注入行：只在「Electron 主进程」加载本 loader；CLI/utility/renderer 子进程直接跳过。
# WorkBuddy 的 CLI 子进程也加载同一个 app.asar 的 main/index.js，若在它们里跑 inject-main
# 会因 require("electron") 失败 / 无 BrowserWindow 而 exit 1，被 daemon 判为「cli 意外崩溃」。
# 判据：process.type === 'browser'（Electron 主进程）；缺该字段（纯 node CLI）则跳过。
_INJECT_LINE_TMPL = (
    '\n;try{{if(process.type==="browser"){{require({pp})}}}}catch(e){{console.error("[wb-usage] load failed",e);}}'
)
INJECT_LINE = None  # 由 set_runtime 生成

WBUSAGE_TAG = "[wb-usage]"


def _gen_line():
    pp = repr(str(LOADER))
    return _INJECT_LINE_TMPL.format(pp=pp)


# 匹配任意本工具注入行（不限目录、兼容 v1.0.0 无守卫旧形式与 v1.0.1+ 带进程类型守卫新形式）
# ——迁移/重装/卸载时剥离任何历史注入行用。两种形式：
#   旧: ;try{require("...")}catch(e){console.error("[wb-usage] load failed",e);}
#   新: ;try{if(process.type==="browser"){require("...")}}catch(e){console.error("[wb-usage] load failed",e);}
# 末尾 } 数量不同：旧 1 个（catch 闭合），新 2 个（守卫 + catch）→ 用 \}\}? 容纳
WBUSAGE_LINE_RE = re.compile(
    rb'\n;try\{'
    rb'(?:if\(process\.type==="browser"\)\{)?'          # 可选守卫（v1.0.1+）
    rb'require\([^)]*\)'                                 # require(...)
    rb'(?:\})?'                                           # 可选守卫闭合 }
    rb'\}catch\(e\)\{console\.error\("\[wb-usage\] load failed",e\);\}'  # catch 块
)

WORKBUDDY_EXE = None
ALIGN = 4
BLOCK = 4194304


def set_runtime(path):
    global RUNTIME, LOADER, INJECT_LINE
    RUNTIME = Path(path)
    LOADER = RUNTIME / "inject-main.cjs"
    INJECT_LINE = _gen_line()


def workbuddy_exe_for(asar_path):
    root = asar_path.parent.parent
    if IS_WIN:
        exe = root / "WorkBuddy.exe"
        return exe if exe.is_file() else None
    if IS_MAC:
        exe = root / "MacOS" / "WorkBuddy"
        return exe if exe.is_file() else exe
    if sys.platform.startswith("linux"):
        exe = root / "workbuddy"
        return exe if exe.is_file() else None
    return None


def set_target(asar_path):
    global ASAR, TMP, WORKBUDDY_EXE
    asar_path = Path(asar_path)
    ASAR = asar_path
    TMP = asar_path.with_name("app.asar.wbusage.tmp")
    WORKBUDDY_EXE = workbuddy_exe_for(asar_path)


def client_running():
    try:
        if IS_WIN:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WorkBuddy.exe"],
                capture_output=True, text=True, encoding="gbk", errors="replace",
            ).stdout
            return "WorkBuddy.exe" in out
        return subprocess.run(["pgrep", "-x", "WorkBuddy"], capture_output=True).returncode == 0
    except Exception:
        return True


# ---------- asar 读写 ----------
def read_header(f):
    f.seek(0)
    a, b, c, d = struct.unpack("<4I", f.read(16))
    assert a == 4, f"unexpected pickle prefix {a}"
    header = json.loads(f.read(d))
    return header, 8 + b


def iter_files(node, path=""):
    for name, ch in node.get("files", {}).items():
        p = f"{path}/{name}"
        if "files" in ch:
            yield from iter_files(ch, p)
        else:
            yield p, ch


def compute_integrity(data: bytes):
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": BLOCK,
        "blocks": [hashlib.sha256(data[i:i + BLOCK]).hexdigest() for i in range(0, len(data), BLOCK)],
    }


def repack(src_path: Path, modify: dict, dst_path: Path):
    """重建 asar。modify: {asar内路径(带前导/): 新内容bytes}。流式拷贝未改动文件。"""
    with open(src_path, "rb") as src:
        header, base = read_header(src)
        header = json.loads(json.dumps(header))
        nodes = dict(iter_files(header))
        missing = set(modify) - set(nodes)
        assert not missing, f"paths not in asar: {missing}"

        data_parts = []
        offset = 0
        for p, node in nodes.items():
            if node.get("unpacked"):
                node["offset"] = "0"
                continue
            if p in modify:
                data = modify[p]
                node["size"] = len(data)
                node["integrity"] = compute_integrity(data)
            else:
                src.seek(base + int(node["offset"]))
                data = src.read(node["size"])
            node["offset"] = str(offset)
            data_parts.append(data)
            offset += len(data)

        payload = b"".join(data_parts)
        header_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        d = len(header_bytes)
        c = (d + 4 + ALIGN - 1) // ALIGN * ALIGN
        b_total = c + 4
        with open(dst_path, "wb") as out:
            out.write(struct.pack("<4I", 4, b_total, c, d))
            out.write(header_bytes)
            out.write(b"\0" * (c - d - 4))
            assert out.tell() == 8 + b_total
            out.write(payload)
    return dst_path


def entry_bytes_of(asar_path: Path) -> bytes:
    with open(asar_path, "rb") as f:
        header, base = read_header(f)
        nodes = dict(iter_files(header))
        node = nodes["/" + ENTRY]
        f.seek(base + int(node["offset"]))
        return f.read(node["size"])


def self_check(asar_path: Path, expect=True):
    with open(asar_path, "rb") as f:
        header, base = read_header(f)
        n = sum(1 for _ in iter_files(header))
    has = INJECT_LINE.encode() in entry_bytes_of(asar_path)
    ok = has == expect
    print(f"  [check] header ok, files={n}, injection line {'as expected' if ok else 'UNEXPECTED'} "
          f"(expected {'present' if expect else 'absent'})")
    return ok


def syntax_check(asar_path: Path):
    exe = WORKBUDDY_EXE
    if not exe or not exe.is_file():
        print("  [check] WorkBuddy executable not found; syntax check skipped")
        return True
    src = entry_bytes_of(asar_path)
    tmp_js = HERE / ".entry-check.js"
    tmp_js.write_bytes(src)
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    try:
        r = subprocess.run([str(exe), "--check", str(tmp_js)],
                           capture_output=True, text=True, env=env)
    except OSError as e:
        print(f"  [check] syntax check failed to run ({e}); skipped")
        return True
    finally:
        tmp_js.unlink(missing_ok=True)
    print("  [check] node --check exit=", r.returncode, r.stderr.strip()[:200])
    return r.returncode == 0


def install(finalize=False):
    assert INJECT_LINE, "INJECT_LINE not set"
    assert LOADER.exists(), f"loader missing: {LOADER}"
    if not os.access(ASAR, os.W_OK) or not os.access(ASAR.parent, os.W_OK):
        print(f"[permission] app.asar or its directory is not writable: {ASAR}")
        print("try sudo (Linux system locations) or run installer as admin")
        return False
    entry = entry_bytes_of(ASAR)
    stripped = WBUSAGE_LINE_RE.sub(b"", entry)
    if stripped + INJECT_LINE.encode() == entry:
        print("already installed; injection line points at current directory.")
        return True
    new_entry = stripped + INJECT_LINE.encode()
    if stripped != entry:
        print("old injection line detected; replacing with current path.")
    print("repacking asar (this takes a few seconds)...")
    repack(ASAR, {"/" + ENTRY: new_entry}, TMP)
    print("self-check:")
    if not (self_check(TMP) and syntax_check(TMP)):
        print("self-check failed; not replaced. TMP kept for inspection:", TMP)
        return False
    if client_running() and not finalize:
        try:
            os.replace(TMP, ASAR)
            print("WorkBuddy is running, but asar was replaced atomically; "
                  "restart WorkBuddy to activate the floating bar.")
            return True
        except OSError as e:
            print(f"replacement while running failed ({e}); quit WorkBuddy then run "
                  "python patch_install.py install --finalize")
            return False
    os.replace(TMP, ASAR)
    print("done. start WorkBuddy and the floating bar appears at the bottom.")
    return True


def remove():
    old = entry_bytes_of(ASAR)
    stripped = WBUSAGE_LINE_RE.sub(b"", old)
    if stripped == old:
        print("the current asar is not injected.")
        return True
    print("repacking (stripping the injection line)...")
    repack(ASAR, {"/" + ENTRY: stripped}, TMP)
    print("self-check:")
    if not (self_check(TMP, expect=False) and syntax_check(TMP)):
        print("self-check failed; not replaced. TMP kept for inspection:", TMP)
        return False
    running = client_running()
    try:
        os.replace(TMP, ASAR)
    except OSError as e:
        print(f"replacement failed ({e}); quit WorkBuddy then re-run "
              "python patch_install.py remove")
        return False
    print("injection line stripped" +
          (" (WorkBuddy was running; replaced atomically)." if running else ".") +
          " restart WorkBuddy to take effect.")
    return True


def check():
    injected = bool(WBUSAGE_LINE_RE.search(entry_bytes_of(ASAR)))
    print("asar:", ASAR, ASAR.stat().st_size, "bytes")
    print("injection:", "injected" if injected else "not injected")
    if TMP.exists():
        print("pending replacement TMP exists:", TMP, "(quit WorkBuddy, run install --finalize)")


def _bootstrap():
    set_runtime(HERE)


_bootstrap()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"install": install, "remove": remove, "check": check}.get(cmd, check)()