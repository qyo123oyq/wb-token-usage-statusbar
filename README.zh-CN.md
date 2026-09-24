# WorkBuddy Token 用量状态栏

[English](README.md) | 中文

WorkBuddy 桌面客户端（Electron）的悬浮状态栏，实时显示当前对话的 token 与额度用量。
只读本地 `~/.workbuddy/workbuddy.db` SQLite 数据库——绝不联网。

灵感来自 [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar)，
按 WorkBuddy 的数据模型重写。

## 功能

悬浮条停在 WorkBuddy 窗口底部，实时显示用量。所有项目均可在 ⚙ 面板开关。

### ① 上下文容量
迷你进度条 + 百分比，显示当前会话已占上下文比例（`session_usage.used / size`）；
颜色随用量绿 → 黄 → 红；≥1M token 的窗口在 40% / 60% 提前预警。

### ② 本轮用量
最近一轮完成请求的 token 与额度增量——通过轮询 `usage_updated_at` 变化客户端推导
（WorkBuddy 本地不存每轮明细行，故增量由连续两次读取差值算出）。

### ③ 会话合计
当前会话的 token 与额度累计、请求次数（来自 `session_usage.credit_json`）。

### ④ 今日合计
今日所有会话的 token 与额度合计（按 `last_activity_at` 归属今天）。

### ⑤ 模型与状态
当前模型 id 与会话状态（`working` / `completed` / `pending`）。

### ⑥ 设置面板（⚙）
逐项开关、切换语言（中文 / English）。位置可拖动并记忆。自动跟随系统亮/暗色。

### 更多
- **MCP 对话内查询**：`token_usage(scope)` —— `now` / `today` / `json` / `days:N` /
  `sessions:N` / `session:<id 前缀>` / `workspace:<目录关键字>`。
- **CLI**：`python busage.py [now|today|json|days N|sessions [N]|workspace <kw>|session <前缀>|watch|serve]`。
- **`/usage` 斜杠命令**模板。

## 安装

要求：Windows（或 macOS）；Python 3.8+（零第三方依赖）。

```
git clone https://github.com/qyo123oyq/wb-token-usage-statusbar.git
cd wb-token-usage-statusbar
python install.py            # 加 --lang en 切英文安装器
```

一条命令完成：定位 WorkBuddy（`WORKBUDDY_ASAR` 环境变量 → 常见安装位置 → `--root`，
如 `--root E:\WorkBuddy`）→ 复制运行时到 `~/.workbuddy/wb-token-usage-statusbar/` →
生成 `config.json` → 注入 `app.asar`（一行 `require()` loader）→ 在 `~/.workbuddy/mcp.json`
注册 MCP → 安装 `/usage` 命令 → 提醒重启 WorkBuddy。

**WorkBuddy 升级会覆盖 `app.asar` —— 升级后重跑 `python install.py`。**

## 数据来源

只读 `~/.workbuddy/workbuddy.db`，核心表：

- `sessions`（id, cwd, status, mode, model, context_window, created_at, updated_at, …）
- `session_usage`（session_id, used, size, updated_at, credit_json）
- `workspaces`（path, last_opened_at）

「当前」会话取最近活跃的会话近似（WorkBuddy 未把焦点窗口会话 id 暴露给本地）。
额度是 `session_usage.credit_json` 各项之和——WorkBuddy 自身的账本，数值单位以客户端为准，
原样汇总不臆测。

## 卸载

```
python install.py --remove
```

只剥离本工具注入行（不影响其它工具的注入），移除 MCP 注册与数据目录。

## 与 ZCode 版的差异

WorkBuddy 本地 DB 粒度比 ZCode（每请求一行的 `model_usage` / `turn_usage` /
`tool_usage`）粗，故：
- 无按工具调用的明细与错误徽标；
- 无按模型 / 缓存读写 / 思考 token 的拆分；
- 「本轮用量」是客户端差值，非存储行；
- 无子代理追踪（本地 schema 无父子会话关联）。

原样保留：悬浮条交互、上下文容量条、今日/会话合计、双语设置面板、CLI、MCP、
零依赖 Python、asar 注入安装模型。

## 用法示例

```bash
python busage.py now                    # 当前/最近活跃会话
python busage.py today                   # 今日汇总
python busage.py sessions 10             # 最近 10 个会话
python busage.py workspace AIwork        # 按目录关键字聚合
python busage.py session 9ddc            # 单会话详情（id 前缀）
python busage.py watch                   # 实时刷新（每 2s）
python busage.py serve --port 0          # 本地 HTTP JSON 服务
python busage.py --lang en now           # 临时切英文
```

```bash
python install.py --root E:\WorkBuddy    # 指定安装目录
python install.py --dev                  # 开发模式：注入直指仓库，改完即时热更新
python install.py --no-mcp               # 只装状态条，不注册 MCP
python install.py --dry-run
python install.py --remove
```

## 配置（config.json）

```json
{
  "python_path": "python",
  "poll_ms": 2000,
  "hot_reload": true,
  "context_window": 0,
  "lang": "zh",
  "show": { "context": true, "turn": true, "session": true, "today": true, "model": true, "status": true }
}
```

- `context_window`：0 = 自动（按 DB 的 size/context_window）；填正数则强制覆盖。
- `poll_ms`：悬浮条轮询间隔（毫秒）。
- `lang`：zh / en。
- `show`：默认显示项（面板切换会覆盖到 localStorage）。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│ WorkBuddy (Electron)                                         │
│  app.asar  ← 注入一行 require(inject-main.cjs)  (CJS)        │
│   └ main process: inject-main.cjs                            │
│       ├ spawn busage.py serve  (本地 HTTP JSON)              │
│       ├ 放宽 CSP（让 renderer 能 fetch 127.0.0.1）            │
│       └ 把 overlay.js 注入所有渲染窗口 (executeJavaScript)    │
│   └ renderer: overlay.js (悬浮条 DOM + 每 poll_ms 轮询)       │
└─────────────────────────────────────────────────────────────┘
        │ fetch http://127.0.0.1:<port>/now
        ▼
┌─────────────────────────────────────────────────────────────┐
│ busage.py (Python stdlib, 零依赖)                             │
│  ├ 只读 ~/.workbuddy/workbuddy.db (sessions / session_usage)  │
│  ├ CLI: now / today / json / days / sessions / workspace …    │
│  └ serve: 本地 HTTP JSON 服务（端口 0 = OS 分配）             │
└─────────────────────────────────────────────────────────────┘
```

## 注意事项
- 注入 `app.asar` 是非官方途径；WorkBuddy 升级会覆盖——升级后重跑 install。
- WorkBuddy 的 Electron 构建未嵌入完整性校验 fuse（无 sentinel），改动 asar 可正常加载。
- 数据每 `poll_ms` 刷新一次；不是事件驱动（悬浮条主动轮询）。
- 许可证：MIT。