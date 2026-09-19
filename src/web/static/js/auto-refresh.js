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
  // 1 秒后 reload 页面（保证用户一定看到新数据；dynamic refresh 是补充）
  bus.dispatchEvent(new CustomEvent("refresh:start"));
  try {
    const r = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const result = await r.json();
    bus.dispatchEvent(new CustomEvent("refresh:done", {
      detail: { broadcast_count: result.broadcast_count || 0 },
    }));
    // 触发 dynamic refresh（让用户立即看到变化，不等 reload）
    document.dispatchEvent(new CustomEvent("cgr:trigger-refresh"));
  } catch (e) {
    errors.bump(`manual refresh failed: ${e.message}`);
    return;
  }
  // reload 兜底（即使 dynamic refresh 因 JS 缓存等原因失效，1s 后 reload 也保证看到新数据）
  setTimeout(() => window.location.reload(), 1000);
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

