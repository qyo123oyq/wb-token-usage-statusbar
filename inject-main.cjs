// inject-main.cjs —— 在 WorkBuddy 主进程加载（app.asar 注入行 require 本文件）。
// 职责：1) 启动 busage.py --serve 本地 HTTP 服务；2) 把 overlay.js 注入到所有渲染窗口；
//       3) 放宽 CSP 让 overlay 能 fetch 127.0.0.1；4) 退出时回收子进程。
// 全部基于 __dirname 自定位，副本目录即自洽运行。
"use strict";
const { app, session, BrowserWindow, webContents } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const BUSAGE = path.join(HERE, "busage.py");
const OVERLAY = path.join(HERE, "overlay.js");
const CONFIG = path.join(HERE, "config.json");
const PORT_FILE = path.join(HERE, ".serve.port");

const TAG = "[wb-usage]";

function log(...a) { try { console.log(TAG, ...a); } catch (_) {} }
function err(...a) { try { console.error(TAG, ...a); } catch (_) {} }

function readJson(p, fallback) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); }
  catch (_) { return fallback || {}; }
}

function pickPython(cfg) {
  if (cfg && cfg.python_path && fs.existsSync(cfg.python_path)) return cfg.python_path;
  if (process.env.WORKBUDDY_USAGE_PYTHON && fs.existsSync(process.env.WORKBUDDY_USAGE_PYTHON))
    return process.env.WORKBUDDY_USAGE_PYTHON;
  // WorkBuddy 自带 Python（若有）
  const home = app.getPath("home");
  const bundled = path.join(home, ".workbuddy", "binaries", "python",
                            "versions", "3.13.12", "python.exe");
  if (fs.existsSync(bundled)) return bundled;
  return "python";
}

let serveProc = null;
let base = ""; // http://127.0.0.1:PORT
let overlaySrc = "";

function startServer() {
  const cfg = readJson(CONFIG, {});
  const py = pickPython(cfg);
  if (!fs.existsSync(BUSAGE)) { err("busage.py missing:", BUSAGE); return; }
  try {
    serveProc = spawn(py, [BUSAGE, "serve", "--host", "127.0.0.1", "--port", "0"],
                      { cwd: HERE, windowsHide: true,
                        env: Object.assign({}, process.env, { PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" }) });
  } catch (e) { err("spawn python failed:", e); return; }

  let buf = "";
  const onLine = (line) => {
    line = line.trim();
    const m = line.match(/^WBUSAGE_PORT=(\d+)$/);
    if (m && !base) {
      base = `http://127.0.0.1:${m[1]}`;
      log("usage server at", base);
    }
  };
  serveProc.stdout.on("data", (d) => { buf += d.toString("utf8");
    let i; while ((i = buf.indexOf("\n")) >= 0) { onLine(buf.slice(0, i)); buf = buf.slice(i + 1); } });
  serveProc.stderr.on("data", (d) => { /* 静默 */ });
  serveProc.on("exit", (code) => { log("server exited", code); serveProc = null; });

  // 兜底：若 stdout 未及时给端口，等 1.5s 读端口文件
  setTimeout(() => {
    if (!base && fs.existsSync(PORT_FILE)) {
      const p = fs.readFileSync(PORT_FILE, "utf8").trim();
      if (/^\d+$/.test(p)) base = `http://127.0.0.1:${p}`;
    }
  }, 1500);
}

function relaxCsp() {
  // 渲染窗口 CSP 可能拦 127.0.0.1 fetch；剥掉相关响应头。
  try {
    session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
      const h = (details.responseHeaders || {});
      for (const k of Object.keys(h)) {
        if (/content-security-policy/i.test(k)) delete h[k];
      }
      cb({ responseHeaders: h });
    });
  } catch (e) { err("relax csp failed:", e); }
}

function loadOverlaySrc() {
  try { overlaySrc = fs.readFileSync(OVERLAY, "utf8"); }
  catch (e) { err("overlay.js missing:", e); }
}

function injectInto(wc) {
  if (!overlaySrc) return;
  try {
    const url = wc.getURL();
    // 仅注入到 http/https/file 页面，跳过 devtools / about:blank 之外的内部页
    if (!/^(https?|file):/i.test(url) && url !== "" && !url.startsWith("about:")) return;
    const boot = `;(function(){try{window.__WB_USAGE_BASE__=${JSON.stringify(base)};window.__WB_USAGE_CONFIG__=${JSON.stringify(readJson(CONFIG,{}))};}catch(e){}})();\n`;
    wc.executeJavaScript(boot + overlaySrc, true).catch(() => {});
  } catch (_) {}
}

function attachWebContents(wc) {
  try {
    if (wc.isDevTools()) return;
    wc.on("dom-ready", () => injectInto(wc));
    wc.on("did-finish-load", () => injectInto(wc));
    // 已加载完毕的也尝试一次
    setImmediate(() => injectInto(wc));
  } catch (_) {}
}

function attachWindow(win) {
  try {
    attachWebContents(win.webContents);
    win.on("show", () => attachWebContents(win.webContents));
  } catch (_) {}
}

function wireRenderer() {
  // 已存在的窗口
  try {
    for (const wc of webContents.getAllWebContents()) attachWebContents(wc);
  } catch (_) {}
  try {
    app.on("browser-window-created", (e, win) => attachWindow(win));
  } catch (_) {}
  // webContents 创建（部分场景不经过 browser-window-created）
  try {
    webContents.on("did-attach-webview", (e, wc) => attachWebContents(wc));
  } catch (_) {}
}

app.whenReady().then(() => {
  log("inject-main loaded, data dir =", HERE);
  loadOverlaySrc();
  startServer();
  relaxCsp();
  wireRenderer();
});

// 退出回收
const cleanup = () => {
  try { if (serveProc) { try { serveProc.kill(); } catch (_) {} serveProc = null; } } catch (_) {}
};
app.on("before-quit", cleanup);
process.on("exit", cleanup);
process.on("SIGINT", () => { cleanup(); process.exit(0); });
process.on("SIGTERM", () => { cleanup(); process.exit(0); });