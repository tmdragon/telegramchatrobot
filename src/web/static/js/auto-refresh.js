// auto-refresh.js：每 60s 拉一次页面数据。
// - 默认开启，状态栏 toggle 可关；localStorage key 'cgr.autoRefresh' 持久化
// - 页面不可见时（visibilitychange hidden）暂停；可见且开启时立即恢复
// - 失败保留旧 DOM + 发 refresh:error 事件（status-bar 会 bump）

import { bus, errors } from "./status-bar.js";

function _isAutoOn() {
  return localStorage.getItem("cgr.autoRefresh") !== "false";
}

function _pageUrl() {
  const page = document.body.dataset.page || "overview";
  switch (page) {
    case "overview": return "/api/projects";
    case "detail":   return `/api/projects/${encodeURIComponent(document.querySelector("[data-project-id]")?.dataset.projectId || "")}`;
    case "mappings": return "/api/mappings";
    default:         return null;
  }
}

async function _tick() {
  const url = _pageUrl();
  if (!url) return;
  bus.dispatchEvent(new CustomEvent("refresh:start"));
  try {
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    bus.dispatchEvent(new CustomEvent("refresh:done", { detail: data }));
    // 触发页面特定的重渲染（由 inline-edit / mapping-crud 监听 refresh:done 实现）
    document.dispatchEvent(new CustomEvent("cgr:data-refreshed", { detail: { page: document.body.dataset.page, data } }));
  } catch (e) {
    errors.bump(`auto-refresh failed: ${e.message}`);
  }
}

async function _manualRefresh() {
  // 手动刷新：POST /api/refresh 触发 sheet 拉取 + 状态变化播报
  // 立即显示"刷新中..."覆盖层 + spinner（用户立刻看到反馈）
  // POST 返回后 reload 页面（看到新数据）
  bus.dispatchEvent(new CustomEvent("refresh:start"));
  const overlay = _showRefreshOverlay();
  let result;
  try {
    const r = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    result = await r.json();
  } catch (e) {
    overlay.remove();
    errors.bump(`manual refresh failed: ${e.message}`);
    return;
  }
  bus.dispatchEvent(new CustomEvent("refresh:done", {
    detail: { broadcast_count: result.broadcast_count || 0 },
  }));
  // reload 前把 overlay 文案改成"刷新完成"+ 结果
  _setOverlayText(overlay, result.broadcast_count
    ? `✓ 已播报 ${result.broadcast_count} 条变化`
    : "✓ 已是最新");
  // 短暂停留让用户看到结果，然后 reload
  setTimeout(() => window.location.reload(), 600);
}

function _showRefreshOverlay() {
  const o = document.createElement("div");
  o.className = "refresh-overlay";
  o.innerHTML = `
    <div class="refresh-overlay__panel">
      <div class="spinner"></div>
      <div class="refresh-overlay__text">刷新中…</div>
    </div>`;
  document.body.appendChild(o);
  return o;
}

function _setOverlayText(o, text) {
  const t = o.querySelector(".refresh-overlay__text");
  if (t) t.textContent = text;
}

export function start({ intervalMs = 60_000 } = {}) {
  let timer = null;

  function _restart() {
    if (timer) { clearInterval(timer); timer = null; }
    if (!_isAutoOn() || document.hidden) return;
    timer = setInterval(_tick, intervalMs);
  }

  document.addEventListener("visibilitychange", _restart);
  window.addEventListener("storage", (e) => {
    if (e.key === "cgr.autoRefresh") _restart();
  });
  bus.addEventListener("auto-refresh:toggle", _restart);
  bus.addEventListener("manual:refresh", _manualRefresh);

  _restart();
}

