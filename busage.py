# -*- coding: utf-8 -*-
"""WorkBuddy Token 用量状态栏 —— 数据层 / CLI / 本地 HTTP 服务（标准库实现，零依赖）。

数据来源：~/.workbuddy/workbuddy.db（只读），核心表：
  sessions(id, cwd, status, mode, model, context_window, created_at,
           updated_at, last_activity_at, is_background_automation, ...)
  session_usage(session_id, used, size, updated_at, credit_json)
  workspaces(path, last_opened_at)

会计口径：
  used   —— 当前会话已占用上下文 token 数（客户端 computed_total_tokens 口径）。
  size   —— 当前会话上下文窗口容量（token），与 sessions.context_window 一致。
  credit —— session_usage.credit_json 是 WorkBuddy 自身的用量/计费账本，
            形如 {"<请求哈希>": <数值>}。本工具对其求和作为「额度消耗」展示，
            数值含义以 WorkBuddy 客户端为准（仅汇总，不臆测单位）。

用法：
  python busage.py now                  # 当前/最近活跃会话概览
  python busage.py today                # 今日所有会话汇总
  python busage.py json                 # 全量 JSON（供 overlay / 调试）
  python busage.py days N               # 最近 N 天汇总
  python busage.py sessions [N]         # 最近 N 个会话列表（默认 10）
  python busage.py workspace <关键字>   # 按工作区目录聚合
  python busage.py session <id 前缀>    # 单会话详情
  python busage.py watch                # 实时刷新当前会话（每 2s）
  python busage.py serve [--port 0] [--host 127.0.0.1]   # 本地 HTTP JSON 服务
  python busage.py --lang en ...        # 临时切换输出语言
"""
import argparse
import json
import os
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).parent.resolve()
HOME = Path.home()

# —— 路径 ——
DB_PATH = HOME / ".workbuddy" / "workbuddy.db"
MODELS_PATH = HOME / ".workbuddy" / "models.json"
CONFIG_PATH = HOME / ".workbuddy" / "wb-token-usage-statusbar" / "config.json"
# 仓库内 config（--dev 或运行时数据目录尚未生成时回退）
CONFIG_PATH_FALLBACK = HERE / "config.json"

DEFAULT_CONTEXT_WINDOW = 300000   # 兜底：DB 无 size/context_window 时用

LANG = "zh"


def L(zh, en):
    return en if LANG == "en" else zh


def load_config():
    for p in (CONFIG_PATH, CONFIG_PATH_FALLBACK):
        try:
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def cfg_lang():
    cfg = load_config()
    return cfg.get("lang") if cfg.get("lang") in ("zh", "en") else "zh"


def cfg_context_window():
    cfg = load_config()
    v = cfg.get("context_window", 0)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# —— 时间 ——
def now_ms():
    return int(time.time() * 1000)


def start_of_today_ms():
    """本地时区今日 00:00 的毫秒时间戳。"""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def ms_to_str(ms):
    if not ms:
        return "-"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "-"


# —— DB ——
def connect():
    if not DB_PATH.is_file():
        raise FileNotFoundError(L(f"找不到 WorkBuddy 数据库：{DB_PATH}",
                                 f"WorkBuddy database not found: {DB_PATH}"))
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def parse_credits(raw):
    """credit_json 是 {hash: 数值}；解析失败返回 {}。"""
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return {k: float(v) for k, v in d.items()
                    if isinstance(v, (int, float)) or (isinstance(v, str) and _is_float(v))}
    except (ValueError, TypeError):
        pass
    return {}


def _is_float(s):
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def sum_credits(raw):
    return sum(parse_credits(raw).values())


def context_window_for(session_row, usage_row):
    """窗口容量优先级：config 覆盖 > session_usage.size > sessions.context_window > 默认。"""
    ov = cfg_context_window()
    if ov and ov > 0:
        return ov
    if usage_row and usage_row["size"]:
        return int(usage_row["size"])
    if session_row and session_row["context_window"]:
        return int(session_row["context_window"])
    return DEFAULT_CONTEXT_WINDOW


def session_detail(con, session_id):
    """单会话详情（join sessions + session_usage）。"""
    row = con.execute(
        """SELECT s.id, s.cwd, s.status, s.mode, s.model, s.expert_id,
                  s.context_window, s.created_at, s.updated_at, s.last_activity_at,
                  s.is_background_automation,
                  u.used, u.size, u.updated_at AS usage_updated_at, u.credit_json
           FROM sessions s
           LEFT JOIN session_usage u ON u.session_id = s.id
           WHERE s.id = ?""", (session_id,)).fetchone()
    if not row:
        return None
    credits = parse_credits(row["credit_json"])
    return {
        "session_id": row["id"],
        "cwd": row["cwd"],
        "status": row["status"],
        "mode": row["mode"],
        "model": row["model"],
        "expert_id": row["expert_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_activity_at": row["last_activity_at"],
        "is_background_automation": bool(row["is_background_automation"]),
        "used": int(row["used"] or 0),
        "size": context_window_for(row, row),
        "usage_updated_at": row["usage_updated_at"],
        "credits_total": round(sum(credits.values()), 4),
        "credit_count": len(credits),
        "context_pct": _pct(int(row["used"] or 0), context_window_for(row, row)),
    }


def _pct(used, size):
    if not size:
        return 0.0
    return round(used / size * 100, 2)


def recent_sessions(con, limit=10):
    rows = con.execute(
        """SELECT s.id, s.cwd, s.status, s.mode, s.model, s.last_activity_at,
                  u.used, u.size, u.credit_json, u.updated_at AS usage_updated_at
           FROM sessions s
           LEFT JOIN session_usage u ON u.session_id = s.id
           WHERE s.deleted_at IS NULL
           ORDER BY COALESCE(s.last_activity_at, s.updated_at) DESC
           LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "session_id": r["id"],
            "cwd": r["cwd"],
            "status": r["status"],
            "model": r["model"],
            "last_activity_at": r["last_activity_at"],
            "used": int(r["used"] or 0),
            "size": context_window_for(r, r),
            "credits_total": round(sum_credits(r["credit_json"]), 4),
            "context_pct": _pct(int(r["used"] or 0), context_window_for(r, r)),
        })
    return out


def current_session(con):
    """「当前」会话：优先 status='working' 中最近活跃的；否则取最近活跃会话。
    WorkBuddy 未把「焦点窗口会话」暴露给本地，故以最近活跃会话作近似（README 已说明）。"""
    row = con.execute(
        """SELECT s.id FROM sessions s
           WHERE s.deleted_at IS NULL AND s.status = 'working'
           ORDER BY COALESCE(s.last_activity_at, s.updated_at) DESC LIMIT 1""").fetchone()
    if not row:
        row = con.execute(
            """SELECT s.id FROM sessions s
               WHERE s.deleted_at IS NULL
               ORDER BY COALESCE(s.last_activity_at, s.updated_at) DESC LIMIT 1""").fetchone()
    if not row:
        return None
    return session_detail(con, row["id"])


def today_sessions(con):
    since = start_of_today_ms()
    rows = con.execute(
        """SELECT s.id, s.cwd, s.status, s.model, s.last_activity_at,
                  u.used, u.size, u.credit_json
           FROM sessions s
           LEFT JOIN session_usage u ON u.session_id = s.id
           WHERE s.deleted_at IS NULL
             AND COALESCE(s.last_activity_at, s.updated_at, 0) >= ?""", (since,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "session_id": r["id"],
            "cwd": r["cwd"],
            "status": r["status"],
            "model": r["model"],
            "last_activity_at": r["last_activity_at"],
            "used": int(r["used"] or 0),
            "credits_total": round(sum_credits(r["credit_json"]), 4),
        })
    return out


def aggregate(rows):
    used = sum(r.get("used", 0) for r in rows)
    credits = sum(r.get("credits_total", 0) for r in rows)
    return {"sessions": len(rows), "used": used, "credits_total": round(credits, 4)}


def days_sessions(con, n):
    since = now_ms() - n * 86400000
    rows = con.execute(
        """SELECT s.id, s.cwd, s.status, s.model, s.last_activity_at,
                  u.used, u.size, u.credit_json
           FROM sessions s
           LEFT JOIN session_usage u ON u.session_id = s.id
           WHERE s.deleted_at IS NULL
             AND COALESCE(s.last_activity_at, s.updated_at, 0) >= ?""", (since,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "session_id": r["id"],
            "cwd": r["cwd"],
            "status": r["status"],
            "model": r["model"],
            "last_activity_at": r["last_activity_at"],
            "used": int(r["used"] or 0),
            "credits_total": round(sum_credits(r["credit_json"]), 4),
        })
    return out


def workspace_sessions(con, keyword):
    """按工作区目录关键字聚合（子串匹配 cwd；主会话+后台自动化会话都计入）。"""
    rows = con.execute(
        """SELECT s.id, s.cwd, s.status, s.model, s.last_activity_at,
                  u.used, u.size, u.credit_json
           FROM sessions s
           LEFT JOIN session_usage u ON u.session_id = s.id
           WHERE s.deleted_at IS NULL AND s.cwd LIKE ?""", (f"%{keyword}%",)).fetchall()
    out = []
    for r in rows:
        out.append({
            "session_id": r["id"],
            "cwd": r["cwd"],
            "status": r["status"],
            "model": r["model"],
            "last_activity_at": r["last_activity_at"],
            "used": int(r["used"] or 0),
            "size": context_window_for(r, r),
            "credits_total": round(sum_credits(r["credit_json"]), 4),
            "context_pct": _pct(int(r["used"] or 0), context_window_for(r, r)),
        })
    return out


def find_workspace_candidates(con, keyword):
    """workspace 关键字未命中时，给出候选工作区目录供用户选择。"""
    rows = con.execute(
        """SELECT DISTINCT s.cwd FROM sessions s
           WHERE s.deleted_at IS NULL AND s.cwd != '' ORDER BY s.cwd""").fetchall()
    cwds = [r["cwd"] for r in rows]
    k = keyword.lower()
    # 子串 + 各段首字母缩写匹配
    cands = []
    for c in cwds:
        if k in c.lower():
            cands.append(c)
        else:
            # 取每段首字母（path segments）
            segs = re_path_segs(c)
            acr = "".join(s[0] for s in segs if s).lower()
            if k in acr:
                cands.append(c)
    # 去重保序
    seen = set(); out = []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def re_path_segs(p):
    import re
    parts = re.split(r"[\\/.]+", p)
    return [x for x in parts if x]


def models_catalog():
    """读取 ~/.workbuddy/models.json，返回 {id: entry}。"""
    try:
        arr = json.loads(MODELS_PATH.read_text(encoding="utf-8"))
        return {m.get("id"): m for m in arr if isinstance(m, dict) and m.get("id")}
    except (OSError, ValueError):
        return {}


# —— 数据组装 ——
def snapshot():
    """一次性汇总快照（overlay / json 用）。"""
    con = connect()
    try:
        cur = current_session(con)
        today = today_sessions(con)
        sess = recent_sessions(con, 50)
        return {
            "ts": now_ms(),
            "current": cur,
            "today": {
                "sessions": len(today),
                "used": sum(r["used"] for r in today),
                "credits_total": round(sum(r["credits_total"] for r in today), 4),
                "items": today,
            },
            "recent": sess,
            "db_path": str(DB_PATH),
            "lang": LANG,
        }
    finally:
        con.close()


# —— 文本渲染 ——
def fmt_tokens(n):
    if n is None:
        return "-"
    n = int(n)
    if n >= 1000000:
        return f"{n/1000000:.2f}M"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def fmt_credits(n):
    if n is None:
        return "-"
    return f"{n:.2f}"


def bar(pct, width=12):
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def color_for_pct(pct, big=False):
    if big:
        return "green" if pct < 40 else ("yellow" if pct < 60 else "red")
    return "green" if pct < 60 else ("yellow" if pct < 85 else "red")


def render_now():
    snap = snapshot()
    cur = snap["current"]
    lines = []
    if not cur:
        lines.append(L("（暂无会话）", "(no session)"))
        return "\n".join(lines)
    pct = cur["context_pct"]
    lines.append(L(f"当前会话  {cur['session_id'][:8]}…", f"Current session  {cur['session_id'][:8]}..."))
    if cur.get("model"):
        lines.append(L(f"模型      {cur['model']}", f"Model     {cur['model']}"))
    lines.append(L(f"状态      {cur['status']}", f"Status    {cur['status']}"))
    if cur.get("cwd"):
        lines.append(L(f"工作区    {cur['cwd']}", f"Workspace {cur['cwd']}"))
    lines.append(L(f"上下文    {bar(pct)} {pct:.1f}%  ({fmt_tokens(cur['used'])}/{fmt_tokens(cur['size'])})",
                   f"Context   {bar(pct)} {pct:.1f}%  ({fmt_tokens(cur['used'])}/{fmt_tokens(cur['size'])})"))
    lines.append(L(f"额度消耗  {fmt_credits(cur['credits_total'])}（{cur['credit_count']} 次请求）",
                   f"Credits   {fmt_credits(cur['credits_total'])} ({cur['credit_count']} requests)"))
    t = snap["today"]
    lines.append("")
    lines.append(L(f"今日汇总  {t['sessions']} 个会话 | 上下文 {fmt_tokens(t['used'])} | 额度 {fmt_credits(t['credits_total'])}",
                   f"Today     {t['sessions']} sessions | tokens {fmt_tokens(t['used'])} | credits {fmt_credits(t['credits_total'])}"))
    return "\n".join(lines)


def render_today():
    snap = snapshot()
    t = snap["today"]
    lines = [L(f"今日会话 {t['sessions']} 个 | 上下文 {fmt_tokens(t['used'])} | 额度 {fmt_credits(t['credits_total'])}",
               f"Today  {t['sessions']} sessions | tokens {fmt_tokens(t['used'])} | credits {fmt_credits(t['credits_total'])}")]
    lines.append("")
    for it in t["items"]:
        wd = Path(it["cwd"]).name if it.get("cwd") else "-"
        lines.append(f"  {it['session_id'][:8]}…  {it['status']:<10}  {it.get('model') or '-':<16}  {fmt_tokens(it['used']):>8}  {fmt_credits(it['credits_total']):>8}  {wd}")
    return "\n".join(lines)


def render_sessions(limit):
    snap = snapshot()
    rows = snap["recent"][:limit]
    lines = [L(f"最近 {len(rows)} 个会话", f"Recent {len(rows)} sessions")]
    lines.append("")
    for it in rows:
        wd = Path(it["cwd"]).name if it.get("cwd") else "-"
        lines.append(f"  {it['session_id'][:8]}…  {it['status']:<10}  {it.get('model') or '-':<16}  {fmt_tokens(it['used']):>8}/{fmt_tokens(it['size'])}  {it['context_pct']:>5.1f}%  {fmt_credits(it['credits_total']):>7}  {wd}")
    return "\n".join(lines)


def render_days(n):
    con = connect()
    try:
        rows = days_sessions(con, n)
    finally:
        con.close()
    agg = aggregate(rows)
    lines = [L(f"最近 {n} 天  {agg['sessions']} 会话 | 上下文 {fmt_tokens(agg['used'])} | 额度 {fmt_credits(agg['credits_total'])}",
               f"Last {n} days  {agg['sessions']} sessions | tokens {fmt_tokens(agg['used'])} | credits {fmt_credits(agg['credits_total'])}")]
    return "\n".join(lines)


def render_workspace(keyword):
    con = connect()
    try:
        rows = workspace_sessions(con, keyword)
        if not rows:
            cands = find_workspace_candidates(con, keyword)
            lines = [L(f"未匹配到工作区「{keyword}」。", f"No workspace matched '{keyword}'.")]
            if cands:
                lines.append(L("候选工作区：", "Candidate workspaces:"))
                for c in cands[:20]:
                    lines.append(f"  {c}")
            return "\n".join(lines)
        agg = aggregate(rows)
        lines = [L(f"工作区「{keyword}」  {agg['sessions']} 会话 | 上下文 {fmt_tokens(agg['used'])} | 额度 {fmt_credits(agg['credits_total'])}",
                   f"Workspace '{keyword}'  {agg['sessions']} sessions | tokens {fmt_tokens(agg['used'])} | credits {fmt_credits(agg['credits_total'])}")]
        lines.append("")
        for it in rows:
            lines.append(f"  {it['session_id'][:8]}…  {it['status']:<10}  {it.get('model') or '-':<16}  {fmt_tokens(it['used']):>8}/{fmt_tokens(it['size'])}  {it['context_pct']:>5.1f}%  {fmt_credits(it['credits_total']):>7}  {it['cwd']}")
        return "\n".join(lines)
    finally:
        con.close()


def render_session(prefix):
    con = connect()
    try:
        row = con.execute("SELECT id FROM sessions WHERE id LIKE ? AND deleted_at IS NULL",
                          (prefix + "%",)).fetchone()
        if not row:
            return L(f"未找到会话前缀「{prefix}」。", f"No session with prefix '{prefix}'.")
        det = session_detail(con, row["id"])
    finally:
        con.close()
    lines = [
        L(f"会话 {det['session_id']}", f"Session {det['session_id']}"),
        L(f"  状态      {det['status']}", f"  Status    {det['status']}"),
        L(f"  模型      {det.get('model') or '-'}", f"  Model     {det.get('model') or '-'}"),
        L(f"  模式      {det.get('mode') or '-'}", f"  Mode      {det.get('mode') or '-'}"),
        L(f"  工作区    {det['cwd']}", f"  Workspace {det['cwd']}"),
        L(f"  上下文    {fmt_tokens(det['used'])}/{fmt_tokens(det['size'])}  ({det['context_pct']:.1f}%)",
          f"  Context   {fmt_tokens(det['used'])}/{fmt_tokens(det['size'])}  ({det['context_pct']:.1f}%)"),
        L(f"  额度消耗  {fmt_credits(det['credits_total'])}（{det['credit_count']} 次请求）",
          f"  Credits   {fmt_credits(det['credits_total'])} ({det['credit_count']} requests)"),
        L(f"  创建      {ms_to_str(det['created_at'])}", f"  Created   {ms_to_str(det['created_at'])}"),
        L(f"  最近活动  {ms_to_str(det['last_activity_at'])}", f"  Last act  {ms_to_str(det['last_activity_at'])}"),
        L(f"  用量更新  {ms_to_str(det['usage_updated_at'])}", f"  Usage upd {ms_to_str(det['usage_updated_at'])}"),
    ]
    return "\n".join(lines)


# —— HTTP 服务 ——
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/now":
                snap = snapshot()
                self._json({"ok": True, **snap})
                return
            if u.path == "/today":
                snap = snapshot()
                self._json({"ok": True, "today": snap["today"]})
                return
            if u.path == "/sessions":
                limit = int(q.get("limit", ["10"])[0])
                snap = snapshot()
                self._json({"ok": True, "sessions": snap["recent"][:limit]})
                return
            if u.path == "/days":
                n = int(q.get("n", ["7"])[0])
                con = connect()
                try:
                    rows = days_sessions(con, n)
                finally:
                    con.close()
                self._json({"ok": True, "days": n, **aggregate(rows), "items": rows})
                return
            if u.path == "/workspace":
                kw = q.get("q", [""])[0]
                if not kw:
                    self._json({"ok": False, "error": "missing ?q="}, 400)
                    return
                con = connect()
                try:
                    rows = workspace_sessions(con, kw)
                    if not rows:
                        cands = find_workspace_candidates(con, kw)
                        self._json({"ok": True, "matched": False, "candidates": cands})
                        return
                    self._json({"ok": True, "matched": True, **aggregate(rows), "items": rows})
                    return
                finally:
                    con.close()
            if u.path == "/session":
                pf = q.get("id", [""])[0]
                if not pf:
                    self._json({"ok": False, "error": "missing ?id="}, 400)
                    return
                con = connect()
                try:
                    row = con.execute(
                        "SELECT id FROM sessions WHERE id LIKE ? AND deleted_at IS NULL",
                        (pf + "%",)).fetchone()
                    if not row:
                        self._json({"ok": False, "error": "not found"}, 404)
                        return
                    self._json({"ok": True, "session": session_detail(con, row["id"])})
                    return
                finally:
                    con.close()
            if u.path == "/health":
                self._json({"ok": True, "ts": now_ms(),
                            "db": DB_PATH.is_file(), "lang": LANG})
                return
            self._json({"ok": False, "error": "not found",
                        "endpoints": ["/now", "/today", "/sessions", "/days",
                                      "/workspace?q=", "/session?id=", "/health"]}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


def serve(host="127.0.0.1", port=0):
    # 选端口：port=0 让 OS 分配
    srv = ThreadingHTTPServer((host, port), Handler)
    actual = srv.server_address[1]
    # 输出给父进程解析；同时写端口文件（inject-main.cjs 兜底用）
    print(f"WBUSAGE_PORT={actual}", flush=True)
    port_file = HERE / ".serve.port"
    try:
        port_file.write_text(str(actual), encoding="utf-8")
    except OSError:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


# —— CLI ——
def main():
    global LANG
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=("zh", "en"))
    pre_args, _ = pre.parse_known_args()
    LANG = pre_args.lang or cfg_lang()

    ap = argparse.ArgumentParser(description=L("WorkBuddy Token 用量状态栏 · 数据层/CLI",
                                               "WorkBuddy Token Usage Status Bar · data layer / CLI"))
    ap.add_argument("cmd", nargs="?", default="now",
                    help="now | today | json | days | sessions | workspace | session | watch | serve")
    ap.add_argument("arg", nargs="?", default=None,
                    help=L("命令参数（days 的天数 / sessions 的条数 / workspace 的关键字 / session 的 id 前缀）",
                           "command argument (days N / sessions N / workspace <kw> / session <id prefix>)"))
    ap.add_argument("--lang", choices=("zh", "en"), default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    if args.lang:
        LANG = args.lang

    cmd = args.cmd
    try:
        if cmd == "now":
            print(render_now())
        elif cmd == "today":
            print(render_today())
        elif cmd == "json":
            print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
        elif cmd == "days":
            n = int(args.arg) if args.arg else 7
            print(render_days(n))
        elif cmd == "sessions":
            n = int(args.arg) if args.arg else 10
            print(render_sessions(n))
        elif cmd == "workspace":
            if not args.arg:
                print(L("用法：python busage.py workspace <目录关键字>",
                         "usage: python busage.py workspace <dir keyword>"))
                return 1
            print(render_workspace(args.arg))
        elif cmd == "session":
            if not args.arg:
                print(L("用法：python busage.py session <id 前缀>",
                         "usage: python busage.py session <id prefix>"))
                return 1
            print(render_session(args.arg))
        elif cmd == "watch":
            return _watch()
        elif cmd == "serve":
            serve(args.host, args.port)
        else:
            ap.print_help()
            return 1
    except FileNotFoundError as e:
        print(str(e))
        return 1
    return 0


def _watch():
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print(render_now())
            print(L("\n（每 2s 刷新，Ctrl+C 退出）", "\n(refresh 2s, Ctrl+C to exit)"))
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)