// inject-main.cjs —— 在 WorkBuddy 主进程加载（app.asar 注入行 require 本文件）。
// 职责：1) 启动 busage.py --serve 本地 HTTP 服务；2) 把 overlay.js 注入到所有渲染窗口；
//       3) 放宽 CSP 让 overlay 能 fetch 127.0.0.1；4) 退出时回收子进程。
// 全部基于 __dirname 自定位，副本目录即自洽运行。
// 安全：只在 Electron 主进程（process.type==="browser"）运行；CLI/utility/renderer 进程
//       加载本文件时立即 return，绝不 spawn 子进程或触碰 BrowserWindow——否则 WorkBuddy
//       的 CLI 子进程会 exit 1，被 daemon 判为「cli 意外崩溃」。
"use strict";
(function () {
  // 进程类型守卫：非 Electron 主进程一律退出，不做任何事
  if (typeof process === "undefined" || process.type !== "browser") return;
  // require electron 在非主进程会抛，放守卫之后才安全
  var electron;
  try { electron = require("electron"); } catch (e) { return; }
  var app = electron.app, session = electron.session,
      BrowserWindow = electron.BrowserWindow, webContents = electron.webContents;
  if (!app || !BrowserWindow || !webContents) return;

  var spawn = require("child_process").spawn;
  var fs = require("fs");
  var path = require("path");

  var HERE = __dirname;
  var BUSAGE = path.join(HERE, "busage.py");
  var OVERLAY = path.join(HERE, "overlay.js");
  var CONFIG = path.join(HERE, "config.json");
  var PORT_FILE = path.join(HERE, ".serve.port");

  var TAG = "[wb-usage]";

  function log() { try { console.log.apply(console, [TAG].concat([].slice.call(arguments))); } catch (_) {} }
  function errlog() { try { console.error.apply(console, [TAG].concat([].slice.call(arguments))); } catch (_) {} }

  function readJson(p, fallback) {
    try { return JSON.parse(fs.readFileSync(p, "utf8")); }
    catch (_) { return fallback || {}; }
  }

  function pickPython(cfg) {
    if (cfg && cfg.python_path && fs.existsSync(cfg.python_path)) return cfg.python_path;
    if (process.env.WORKBUDDY_USAGE_PYTHON && fs.existsSync(process.env.WORKBUDDY_USAGE_PYTHON))
      return process.env.WORKBUDDY_USAGE_PYTHON;
    var home = app.getPath("home");
    var bundled = path.join(home, ".workbuddy", "binaries", "python",
                            "versions", "3.13.12", "python.exe");
    if (fs.existsSync(bundled)) return bundled;
    return "python";
  }

  var serveProc = null;
  var base = ""; // http://127.0.0.1:PORT
  var overlaySrc = "";

  function startServer() {
    var cfg = readJson(CONFIG, {});
    var py = pickPython(cfg);
    if (!fs.existsSync(BUSAGE)) { errlog("busage.py missing:", BUSAGE); return; }
    try {
      serveProc = spawn(py, [BUSAGE, "serve", "--host", "127.0.0.1", "--port", "0"],
                        { cwd: HERE, windowsHide: true,
                          env: Object.assign({}, process.env, { PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" }) });
    } catch (e) { errlog("spawn python failed:", e); return; }

    var buf = "";
    serveProc.stdout.on("data", function (d) {
      buf += d.toString("utf8");
      var i;
      while ((i = buf.indexOf("\n")) >= 0) {
        var line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        var m = line.match(/^WBUSAGE_PORT=(\d+)$/);
        if (m && !base) { base = "http://127.0.0.1:" + m[1]; log("usage server at", base); }
      }
    });
    serveProc.stderr.on("data", function () { /* 静默 */ });
    serveProc.on("exit", function (code) { log("server exited", code); serveProc = null; });

    setTimeout(function () {
      if (!base && fs.existsSync(PORT_FILE)) {
        var p = fs.readFileSync(PORT_FILE, "utf8").trim();
        if (/^\d+$/.test(p)) base = "http://127.0.0.1:" + p;
      }
    }, 1500);
  }

  function relaxCsp() {
    try {
      session.defaultSession.webRequest.onHeadersReceived(function (details, cb) {
        var h = (details.responseHeaders || {});
        Object.keys(h).forEach(function (k) {
          if (/content-security-policy/i.test(k)) delete h[k];
        });
        cb({ responseHeaders: h });
      });
    } catch (e) { errlog("relax csp failed:", e); }
  }

  function loadOverlaySrc() {
    try { overlaySrc = fs.readFileSync(OVERLAY, "utf8"); }
    catch (e) { errlog("overlay.js missing:", e); }
  }

  function injectInto(wc) {
    if (!overlaySrc) return;
    try {
      var url = wc.getURL();
      if (!/^(https?|file):/i.test(url) && url !== "" && !url.startsWith("about:")) return;
      var boot = ";(function(){try{window.__WB_USAGE_BASE__=" + JSON.stringify(base) +
                 ";window.__WB_USAGE_CONFIG__=" + JSON.stringify(readJson(CONFIG, {})) +
                 ";}catch(e){}})();\n";
      wc.executeJavaScript(boot + overlaySrc, true).catch(function () {});
    } catch (_) {}
  }

  function attachWebContents(wc) {
    try {
      if (wc.isDevTools()) return;
      wc.on("dom-ready", function () { injectInto(wc); });
      wc.on("did-finish-load", function () { injectInto(wc); });
      setImmediate(function () { injectInto(wc); });
    } catch (_) {}
  }

  function attachWindow(win) {
    try {
      attachWebContents(win.webContents);
      win.on("show", function () { attachWebContents(win.webContents); });
    } catch (_) {}
  }

  function wireRenderer() {
    try {
      webContents.getAllWebContents().forEach(attachWebContents);
    } catch (_) {}
    try {
      app.on("browser-window-created", function (e, win) { attachWindow(win); });
    } catch (_) {}
    try {
      webContents.on("did-attach-webview", function (e, wc) { attachWebContents(wc); });
    } catch (_) {}
  }

  var cleanup = function () {
    try { if (serveProc) { try { serveProc.kill(); } catch (_) {} serveProc = null; } } catch (_) {}
  };

  app.whenReady().then(function () {
    log("inject-main loaded, data dir =", HERE);
    loadOverlaySrc();
    startServer();
    relaxCsp();
    wireRenderer();
  });

  app.on("before-quit", cleanup);
  process.on("exit", cleanup);
  process.on("SIGINT", function () { cleanup(); process.exit(0); });
  process.on("SIGTERM", function () { cleanup(); process.exit(0); });
})();