// status-bar.js：顶部状态栏行为。
// 暴露 EventTarget 事件总线：refresh:start / refresh:done / refresh:error。
// 其他模块（auto-refresh / inline-edit）emit 与 listen。

const bus = new EventTarget();
const errors = {
  _count: 0,
  _recent: [],
  bump(reason) {
    this._count += 1;
    this._recent.unshift({ reason, at: new Date().toISOString() });
    if (this._recent.length > 5) this._recent.length = 5;
    _renderErrorBadge();
    bus.dispatchEvent(new CustomEvent("refresh:error", { detail: { reason } }));
  },
  clear() {
    this._count = 0;
    this._recent = [];
    _renderErrorBadge();
  },
  get count() { return this._count; },
  get recent() { return this._recent.slice(); },
};

function _renderErrorBadge() {
  const btn = document.querySelector('[data-action="show-errors"]');
  if (!btn) return;
  btn.hidden = errors._count === 0;
  btn.dataset.errorCount = String(errors._count);
  const txt = btn.querySelector("[data-error-count-text]");
  if (txt) txt.textContent = String(errors._count);
}

function _formatLocal(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function _updateLastRefresh() {
  const t = document.querySelector("[data-last-refresh]");
  if (!t) return;
  const iso = t.getAttribute("data-last-refresh");
  // SSR 已把 ISO 写到 data-last-refresh；这里转成本地时区显示
  // （fallback 用当前时间，auto-refresh 时维持 30s 内不变）
  if (iso) {
    t.textContent = _formatLocal(iso);
    t.setAttribute("title", `服务器时间: ${_formatLocal(iso)} (${iso})`);
  } else {
    t.textContent = "—";
  }
}

export function mount(rootSelector = "#status-bar") {
  const root = document.querySelector(rootSelector);
  if (!root) {
    console.warn("status-bar root not found:", rootSelector);
    return bus;
  }

  const manualBtn = root.querySelector('[data-action="manual-refresh"]');
  const toggleBtn = root.querySelector('[data-action="auto-refresh-toggle"]');
  const toggleState = toggleBtn?.querySelector("[data-auto-refresh-state]");

  if (manualBtn) {
    manualBtn.addEventListener("click", () => {
      bus.dispatchEvent(new CustomEvent("manual:refresh"));
    });
  }
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const cur = localStorage.getItem("cgr.autoRefresh") !== "false";
      const next = !cur;
      localStorage.setItem("cgr.autoRefresh", String(next));
      if (toggleState) toggleState.textContent = next ? "⏸ 自动刷新:开" : "▶ 自动刷新:关";
      toggleBtn.setAttribute("aria-pressed", String(next));
      bus.dispatchEvent(new CustomEvent("auto-refresh:toggle", { detail: { enabled: next } }));
    });
  }

  // 错误按钮：单击展开最近 5 条；双击清零
  const errBtn = root.querySelector('[data-action="show-errors"]');
  if (errBtn) {
    errBtn.addEventListener("click", () => {
      const lines = errors._recent.map((e) => `${e.at}: ${e.reason}`).join("\n");
      alert(`最近错误:\n${lines || "(无)"}`);
    });
    errBtn.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      errors.clear();
    });
  }

  return { bus, errors, updateLastRefresh: _updateLastRefresh };
}

export { bus, errors };