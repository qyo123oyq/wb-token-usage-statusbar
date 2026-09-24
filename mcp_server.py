# -*- coding: utf-8 -*-
"""WorkBuddy Token 用量状态栏 —— MCP server（stdio，标准库实现，零依赖）。

通过 line-delimited JSON-RPC 2.0 实现 MCP（无第三方依赖）。注册工具：
  token_usage(scope)  scope ∈ now | today | json | days:N | sessions:N | session:<prefix> | workspace:<kw>

被 WorkBuddy 注册到 ~/.workbuddy/mcp.json：
  {"mcpServers":{"wb-token-usage-statusbar":{"command":"python","args":["<data>/mcp_server.py"]}}}
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
import busage  # noqa: E402

TOOL_SCHEMA = {
    "name": "token_usage",
    "description": (
        "Query WorkBuddy token & credit usage from the local workbuddy.db (read-only). "
        "scope: 'now' (current/recent active session), 'today' (all of today's sessions), "
        "'json' (full snapshot), 'days:N' (last N days), 'sessions:N' (recent N sessions), "
        "'session:<id-prefix>' (one session detail), 'workspace:<dir-keyword>' "
        "(aggregate a workspace's sessions). Default scope is 'now'."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "Query scope, e.g. now / today / days:7 / sessions:10 / session:abc123 / workspace:AIwork",
                "default": "now",
            }
        },
    },
}


def lang():
    try:
        return busage.cfg_lang()
    except Exception:
        return "zh"


def L(zh, en):
    return en if lang() == "en" else zh


def run(scope):
    """返回 MCP 工具结果（text content 列表）。"""
    try:
        if scope in (None, "", "now"):
            text = busage.render_now()
        elif scope == "today":
            text = busage.render_today()
        elif scope == "json":
            text = json.dumps(busage.snapshot(), ensure_ascii=False, indent=2)
        elif scope.startswith("days:"):
            n = int(scope.split(":", 1)[1])
            text = busage.render_days(n)
        elif scope.startswith("sessions:"):
            n = int(scope.split(":", 1)[1])
            text = busage.render_sessions(n)
        elif scope.startswith("session:"):
            text = busage.render_session(scope.split(":", 1)[1])
        elif scope.startswith("workspace:"):
            text = busage.render_workspace(scope.split(":", 1)[1])
        else:
            text = L(f"未知 scope：{scope}（支持 now / today / json / days:N / sessions:N / session:<prefix> / workspace:<kw>）",
                     f"unknown scope: {scope} (supported: now / today / json / days:N / sessions:N / session:<prefix> / workspace:<kw>)")
        return {"content": [{"type": "text", "text": text}]}
    except Exception as e:
        return {"isError": True,
                "content": [{"type": "text", "text": f"token_usage error: {e}"}]}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "wb-token-usage-statusbar", "version": "1.0.0"},
        }}
    if method == "initialized" or method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"tools": [TOOL_SCHEMA]}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "token_usage":
            return {"jsonrpc": "2.0", "id": mid, "result": run(args.get("scope", "now"))}
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"unknown tool: {name}"}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    # 未知方法：有 id 则返回错误，无 id（通知）则忽略
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()