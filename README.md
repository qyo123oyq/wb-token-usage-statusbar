# WorkBuddy Token 用量状态栏

[English](README.en.md) | 中文

WorkBuddy 的 token 与额度用量查询工具。**只读本地 `~/.workbuddy/workbuddy.db` SQLite 数据库——绝不联网，绝不修改 WorkBuddy 本体。**

灵感来自 [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar)，按 WorkBuddy 的数据模型重写。

> **致谢**：本项目是 [@xhwxt](https://github.com/xhwxt) 的 [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar) 在 WorkBuddy 上的移植版（原作者 MIT 协议）。详见[致谢](#致谢)。

## ⚠️ 关于悬浮状态条（asar 注入）

悬浮条方案需要 patch WorkBuddy 的 `app.asar`，**风险过高，已弃用**：
- v1.0.0 会导致 WorkBuddy CLI 子进程崩溃（注入行没做进程类型判断）
- v1.0.1 修了进程守卫，但 asar 重打包本身仍有结构风险
- WorkBuddy 升级会覆盖 asar，需反复重装

**推荐使用安全的 MCP + CLI 方式**（不改 WorkBuddy 本体，零风险）。

## 安装（安全方式：MCP + CLI）

要求：Python 3.8+（零第三方依赖）。

```
git clone https://github.com/qyo123oyq/wb-token-usage-statusbar.git
cd wb-token-usage-statusbar
python install.py            # 注册 MCP + 装 CLI（不碰 asar）
```

或者只装 CLI（不注册 MCP）：
```
python busage.py now    # 直接用，无需安装
```

## 功能

### MCP 对话内查询
在 WorkBuddy 对话里调用 `token_usage(scope)` 工具：
- `now` — 当前/最近活跃会话
- `today` — 今日所有会话汇总
- `days:N` — 最近 N 天
- `sessions:N` — 最近 N 个会话
- `session:<id 前缀>` — 单会话详情
- `workspace:<目录关键字>` — 按工作区聚合

### CLI 命令行
```bash
python busage.py now                    # 当前/最近活跃会话
python busage.py today                   # 今日汇总
python busage.py sessions 10             # 最近 10 个会话
python busage.py workspace AIwork        # 按目录关键字聚合
python busage.py session 9ddc            # 单会话详情（id 前缀）
python busage.py watch                    # 实时刷新（每 2s）
python busage.py serve --port 0          # 本地 HTTP JSON 服务
python busage.py --lang en now           # 临时切英文
```

### 悬浮状态条（已弃用）
原方案的悬浮条需注入 `app.asar`，因风险过高已弃用。`overlay.js` 和 `inject-main.cjs` 保留在仓库作参考，但**不建议使用**。

## 数据来源

只读 `~/.workbuddy/workbuddy.db`，核心表：

- `sessions`（id, cwd, status, mode, model, context_window, created_at, updated_at, …）
- `session_usage`（session_id, used, size, updated_at, credit_json）
- `workspaces`（path, last_opened_at）

「当前」会话取最近活跃的会话近似。额度是 `session_usage.credit_json` 各项之和——WorkBuddy 自身的账本，原样汇总不臆测。

## 卸载

```
python install.py --remove      # 移除 MCP 注册与数据目录（不碰 asar）
```

## 配置（config.json）

```json
{
  "python_path": "python",
  "poll_ms": 2000,
  "context_window": 0,
  "lang": "zh"
}
```

## 致谢

本项目直接移植自 **[@xhwxt](https://github.com/xhwxt) 的 [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar)**。数据层（Python 标准库、零依赖）、CLI、MCP 的设计均改编自原项目。感谢 @xhwxt 提供的设计与零依赖实现。

悬浮条（asar 注入）部分因 WorkBuddy 的 CLI 子进程架构与 ZCode 不同，注入后会导致 CLI 崩溃，已弃用。MCP + CLI 部分安全可用。

## 注意事项
- 只读 `workbuddy.db`，不修改 WorkBuddy 本体（asar 注入方案已弃用）。
- 数据每次查询时读取，不做后台轮询。
- 许可证：MIT。