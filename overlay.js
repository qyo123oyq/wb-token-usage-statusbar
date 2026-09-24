// overlay.js —— WorkBuddy 渲染进程悬浮状态条。自包含，无外部依赖，幂等（重复注入只保留一份）。
// 由 inject-main.cjs 经 executeJavaScript 注入；运行前已设置 window.__WB_USAGE_BASE__ 与 __WB_USAGE_CONFIG__。
;(function () {
  if (window.__WB_USAGE_MOUNTED__) { try { window.__WB_USAGE_RESTART__ && window.__WB_USAGE_RESTART__(); } catch (_) {} return; }
  window.__WB_USAGE_MOUNTED__ = true;

  var BASE = window.__WB_USAGE_BASE__ || "";
  var CFG = window.__WB_USAGE_CONFIG__ || {};
  var POLL = (CFG.poll_ms || 2000) | 0;
  var LANG = CFG.lang === "en" ? "en" : "zh";
  var SHOW = CFG.show || {};

  function L(zh, en) { return LANG === "en" ? en : zh; }
  function q(s) { return document.querySelector(s); }

  // 覆盖 config：本地存储用户切换的项
  var LS_KEY = "wb-usage-show";
  var lsShow = {};
  try { lsShow = JSON.parse(localStorage.getItem(LS_KEY) || "{}") || {}; } catch (_) {}
  var show = Object.assign({
    context: true, turn: true, session: true, today: true, model: true, status: true
  }, SHOW, lsShow);

  function saveShow() { try { localStorage.setItem(LS_KEY, JSON.stringify(show)); } catch (_) {} }

  // —— 样式 ——
  var css = [
    "#wb-usage-bar{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:2147483646;",
    "display:flex;align-items:center;gap:10px;padding:5px 10px;border-radius:14px;",
    "font:12px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;",
    "background:rgba(28,28,30,.82);color:#e8e8ea;backdrop-filter:blur(8px);",
    "box-shadow:0 6px 22px rgba(0,0,0,.28);user-select:none;pointer-events:auto;",
    "border:1px solid rgba(255,255,255,.12);max-width:92vw;}",
    "@media (prefers-color-scheme:light){#wb-usage-bar{background:rgba(255,255,255,.9);color:#1c1c1e;border-color:rgba(0,0,0,.1);box-shadow:0 6px 22px rgba(0,0,0,.14);}}",
    "#wb-usage-bar .it{display:flex;align-items:center;gap:5px;white-space:nowrap;}",
    "#wb-usage-bar .sep{width:1px;height:14px;background:rgba(255,255,255,.18);}",
    "@media (prefers-color-scheme:light){#wb-usage-bar .sep{background:rgba(0,0,0,.12);}}",
    "#wb-usage-bar .cap{position:relative;width:78px;height:8px;border-radius:6px;overflow:hidden;background:rgba(255,255,255,.16);}",
    "@media (prefers-color-scheme:light){#wb-usage-bar .cap{background:rgba(0,0,0,.1);}}",
    "#wb-usage-bar .cap>i{position:absolute;left:0;top:0;bottom:0;border-radius:6px;transition:width .4s ease,background .3s;}",
    "#wb-usage-bar .g{color:#34c759}#wb-usage-bar .y{color:#ffd60a}#wb-usage-bar .r{color:#ff453a}#wb-usage-bar .b{color:#0a84ff}#wb-usage-bar .m{color:#bf5af2}",
    "#wb-usage-bar .dot{width:7px;height:7px;border-radius:50%;display:inline-block;}",
    "#wb-usage-bar .gear{cursor:pointer;opacity:.6;padding:0 2px;border-radius:6px;}#wb-usage-bar .gear:hover{opacity:1;background:rgba(255,255,255,.1)}",
    "@media (prefers-color-scheme:light){#wb-usage-bar .gear:hover{background:rgba(0,0,0,.06)}}",
    "#wb-usage-panel{position:fixed;right:14px;bottom:48px;z-index:2147483647;background:rgba(28,28,30,.95);color:#e8e8ea;",
    "border-radius:12px;padding:12px 14px;min-width:240px;font:12px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;",
    "box-shadow:0 8px 28px rgba(0,0,0,.32);border:1px solid rgba(255,255,255,.12);}",
    "@media (prefers-color-scheme:light){#wb-usage-panel{background:#fff;color:#1c1c1e;border-color:rgba(0,0,0,.1)}}",
    "#wb-usage-panel h4{margin:0 0 8px;font-size:13px;font-weight:600;}",
    "#wb-usage-panel .row{display:flex;align-items:center;justify-content:space-between;padding:3px 0;}",
    "#wb-usage-panel .row label{cursor:pointer}",
    "#wb-usage-panel .sel{margin-top:8px;display:flex;gap:6px;}",
    "#wb-usage-panel button{flex:1;padding:5px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:transparent;color:inherit;cursor:pointer;font-size:12px;}",
    "@media (prefers-color-scheme:light){#wb-usage-panel button{border-color:rgba(0,0,0,.15)}}",
    "#wb-usage-tip{position:fixed;left:50%;bottom:46px;transform:translateX(-50%);z-index:2147483647;",
    "background:rgba(28,28,30,.94);color:#e8e8ea;padding:7px 11px;border-radius:9px;font:12px/1.4 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;",
    "box-shadow:0 6px 20px rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.12);max-width:80vw;}",
    "@media (prefers-color-scheme:light){#wb-usage-tip{background:#fff;color:#1c1c1e;border-color:rgba(0,0,0,.1)}}",
  ].join("");

  function mountStyle() {
    if (q("#wb-usage-style")) return;
    var s = document.createElement("style");
    s.id = "wb-usage-style";
    s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
  }

  // —— DOM ——
  var bar, panel, gear, items = {};

  function el(cls, html) {
    var d = document.createElement("div");
    d.className = "it" + (cls ? " " + cls : "");
    if (html != null) d.innerHTML = html;
    return d;
  }

  function buildBar() {
    if (q("#wb-usage-bar")) q("#wb-usage-bar").remove();
    bar = document.createElement("div");
    bar.id = "wb-usage-bar";

    items.model = el("m", "");
    items.status = el("", "");
    items.context = el("", "");
    items.turn = el("b", "");
    items.session = el("g", "");
    items.today = el("y", "");

    function sep() { var s = document.createElement("div"); s.className = "sep"; return s; }

    bar.appendChild(items.model);
    bar.appendChild(sep());
    bar.appendChild(items.status);
    bar.appendChild(sep());
    bar.appendChild(items.context);
    bar.appendChild(sep());
    bar.appendChild(items.turn);
    bar.appendChild(items.session);
    bar.appendChild(sep());
    bar.appendChild(items.today);

    gear = document.createElement("div");
    gear.className = "it gear";
    gear.textContent = "⚙";
    gear.title = L("设置", "Settings");
    gear.onclick = function (e) { e.stopPropagation(); togglePanel(); };
    bar.appendChild(gear);

    (document.body || document.documentElement).appendChild(bar);
    applyShow();
    makeDraggable();
  }

  function applyShow() {
    var map = { model: items.model, status: items.status, context: items.context,
                turn: items.turn, session: items.session, today: items.today };
    Object.keys(map).forEach(function (k) {
      map[k].style.display = show[k] ? "" : "none";
    });
    // 隐藏多余的 sep：连续隐藏的项之间的 sep 不显示
    var seps = bar.querySelectorAll(".sep");
    seps.forEach(function (s) {
      var prev = s.previousElementSibling, next = s.nextElementSibling;
      var prevShow = prev && prev.classList.contains("it") && prev.style.display !== "none";
      var nextShow = next && next.classList.contains("it") && next.style.display !== "none";
      s.style.display = (prevShow && nextShow) ? "" : "none";
    });
  }

  // —— 拖动 ——
  function makeDraggable() {
    var dragging = false, sx = 0, sy = 0, bx = 0, by = 0;
    bar.addEventListener("mousedown", function (e) {
      if (e.target === gear) return;
      dragging = true;
      var r = bar.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; bx = r.left; by = r.top;
      bar.style.transform = "none";
      bar.style.left = bx + "px";
      bar.style.bottom = "auto";
      bar.style.top = by + "px";
      e.preventDefault();
    });
    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      bar.style.left = (bx + e.clientX - sx) + "px";
      bar.style.top = (by + e.clientY - sy) + "px";
    });
    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      try { localStorage.setItem("wb-usage-pos", bar.style.left + "," + bar.style.top); } catch (_) {}
    });
    try {
      var p = localStorage.getItem("wb-usage-pos");
      if (p) {
        var pp = p.split(",");
        bar.style.transform = "none";
        bar.style.left = pp[0]; bar.style.top = pp[1];
        bar.style.bottom = "auto";
      }
    } catch (_) {}
  }

  // —— 设置面板 ——
  function togglePanel() {
    if (panel) { closePanel(); return; }
    panel = document.createElement("div");
    panel.id = "wb-usage-panel";
    function row(key, label) {
      var r = document.createElement("div"); r.className = "row";
      var lbl = document.createElement("label");
      var cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!show[key];
      cb.onchange = function () { show[key] = cb.checked; saveShow(); applyShow(); };
      lbl.appendChild(cb); lbl.appendChild(document.createTextNode(" " + label));
      r.appendChild(lbl);
      return r;
    }
    var h = document.createElement("h4"); h.textContent = L("显示项", "Show items");
    panel.appendChild(h);
    panel.appendChild(row("model", L("模型", "Model")));
    panel.appendChild(row("status", L("状态", "Status")));
    panel.appendChild(row("context", L("上下文容量", "Context capacity")));
    panel.appendChild(row("turn", L("本轮用量", "This turn")));
    panel.appendChild(row("session", L("会话合计", "Session total")));
    panel.appendChild(row("today", L("今日合计", "Today total")));
    var sel = document.createElement("div"); sel.className = "sel";
    var bZh = document.createElement("button"); bZh.textContent = "中文"; bZh.onclick = function () { setLang("zh"); };
    var bEn = document.createElement("button"); bEn.textContent = "English"; bEn.onclick = function () { setLang("en"); };
    sel.appendChild(bZh); sel.appendChild(bEn);
    panel.appendChild(sel);
    var info = document.createElement("div");
    info.style.cssText = "margin-top:8px;opacity:.6;font-size:11px";
    info.textContent = L("数据来源：~/.workbuddy/workbuddy.db（只读）",
                         "Source: ~/.workbuddy/workbuddy.db (read-only)");
    panel.appendChild(info);
    (document.body || document.documentElement).appendChild(panel);
    setTimeout(function () {
      document.addEventListener("mousedown", outsideClose, true);
    }, 0);
  }
  function outsideClose(e) { if (panel && !panel.contains(e.target) && e.target !== gear) closePanel(); }
  function closePanel() {
    if (panel) { panel.remove(); panel = null; document.removeEventListener("mousedown", outsideClose, true); }
  }
  function setLang(l) { LANG = l; CFG.lang = l; saveCfgLang(l); closePanel(); buildBar(); }

  function saveCfgLang(l) {
    var p = (window.__WB_USAGE_CONFIG__ && window.__WB_USAGE_CONFIG__.__data_path);
    // 语言写入 config.json 由 install/CLI 负责；overlay 仅写本地缓存做即时切换
    try { localStorage.setItem("wb-usage-lang", l); } catch (_) {}
  }

  // —— 工具 ——
  function fmtTok(n) {
    n = +n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }
  function fmtCred(n) { return (+n || 0).toFixed(2); }
  function clsForPct(pct, big) {
    var lo = big ? 40 : 60, hi = big ? 60 : 85;
    return pct < lo ? "g" : (pct < hi ? "y" : "r");
  }
  function setHTML(node, html) { if (node) node.innerHTML = html; }

  // —— 状态机：本轮增量 ——
  var prev = { used: null, credits: null, usage_updated_at: null, sessionId: null };
  var lastTurn = { tokens: 0, credits: 0, at: 0 }; // 最近一次完成的「轮」增量

  function trackTurn(cur) {
    if (!cur) return;
    // 会话切换 → 重置
    if (prev.sessionId && prev.sessionId !== cur.session_id) {
      prev = { used: null, credits: null, usage_updated_at: null, sessionId: cur.session_id };
    }
    var u = cur.usage_updated_at;
    if (prev.usage_updated_at != null && u && u !== prev.usage_updated_at && cur.session_id === prev.sessionId) {
      // usage_updated_at 变化 → 一轮完成
      lastTurn = {
        tokens: Math.max(0, (cur.used || 0) - (prev.used || 0)),
        credits: Math.max(0, (cur.credits_total || 0) - (prev.credits || 0)),
        at: u,
      };
    }
    prev = { used: cur.used || 0, credits: cur.credits_total || 0,
             usage_updated_at: u, sessionId: cur.session_id };
  }

  function render(snap) {
    var cur = snap && snap.current;
    trackTurn(cur);
    if (!cur) { setHTML(items.context, L("无会话", "no session")); return; }

    var pct = cur.context_pct, big = cur.size >= 1e6;
    var cls = clsForPct(pct, big);
    if (show.context) {
      setHTML(items.context,
        '<span>' + L("上下文", "ctx") + '</span>' +
        '<span class="cap"><i class="' + cls + '" style="width:' + Math.min(100, pct) + '%"></i></span>' +
        '<span class="' + cls + '">' + pct.toFixed(0) + '%</span>' +
        '<span style="opacity:.6">' + fmtTok(cur.used) + '/' + fmtTok(cur.size) + '</span>');
    }
    if (show.model) setHTML(items.model, cur.model || '-');
    if (show.status) {
      var stColor = cur.status === "working" ? "b" : (cur.status === "completed" ? "g" : "y");
      var stLabel = ({ working: L("生成中", "working"), completed: L("已完成", "done"),
                        pending: L("待处理", "pending"), failed: L("失败", "failed") })[cur.status] || cur.status;
      setHTML(items.status, '<span class="dot ' + stColor + '"></span><span>' + stLabel + '</span>');
    }
    if (show.turn) {
      setHTML(items.turn,
        L("轮", "turn") + ' +' + fmtTok(lastTurn.tokens) + ' / ' + fmtCred(lastTurn.credits));
    }
    if (show.session) {
      setHTML(items.session,
        L("会话", "sess") + ' ' + fmtTok(cur.used) + ' / ' + fmtCred(cur.credits_total));
    }
    if (show.today) {
      var t = snap.today || {};
      setHTML(items.today,
        L("今日", "today") + ' ' + fmtTok(t.used) + ' / ' + fmtCred(t.credits_total) +
        ' <span style="opacity:.6">(' + (t.sessions || 0) + ')</span>');
    }
  }

  // —— 轮询 ——
  var alive = false, timer = null, failCount = 0;
  async function poll() {
    if (!BASE) { return; }
    try {
      var r = await fetch(BASE + "/now?_=" + Date.now(), { cache: "no-store" });
      if (!r.ok) { failCount++; return; }
      var j = await r.json();
      failCount = 0;
      render(j);
    } catch (e) { failCount++; if (failCount > 5) { /* 静默，下次再试 */ } }
  }
  function loop() { if (!alive) return; poll().finally(function () { timer = setTimeout(loop, POLL); }); }

  function start() {
    mountStyle();
    if (!q("#wb-usage-bar")) buildBar();
    alive = true;
    if (timer) clearTimeout(timer);
    loop();
  }

  // 等待 body 就绪
  function whenBody(fn) {
    if (document.body) { fn(); return; }
    var iv = setInterval(function () {
      if (document.body) { clearInterval(iv); fn(); }
    }, 50);
  }

  whenBody(start);
  // 支持重复注入时重启
  window.__WB_USAGE_RESTART__ = function () {
    alive = false; if (timer) clearTimeout(timer);
    if (q("#wb-usage-bar")) q("#wb-usage-bar").remove();
    start();
  };
})();